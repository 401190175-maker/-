"""In-memory region image preprocessing for the 04 execution layer."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from typing import Any

from PIL import Image, ImageOps

from .recognition_models import (
    RecognitionImageRole,
    RecognitionTaskType,
    ValidatedRecognitionRequest,
)
from .recognition_tasks import RecognitionTaskSpec
from .tool_models import BBox


class RecognitionImageError(ValueError):
    """Stable image preprocessing error raised before any provider attempt."""

    def __init__(self, category: str, message: str):
        self.category = category
        super().__init__(message)


_CROP_POLICY_PADDING = {
    "crop/page-summary-full-page-v1": 0,
    "crop/element-text-local-v1": 8,
    "crop/block-local-min-context-v1": 12,
    "crop/basic-info-local-v1": 8,
    "crop/table-local-caption-context-v1": 8,
    "crop/section-label-local-v1": 8,
    "crop/relation-primary-local-context-v1": 12,
}


@dataclass(frozen=True)
class PreparedRecognitionImage:
    """One in-memory provider image with auditable preprocessing metadata.

    The image bytes are excluded from ``repr`` and never persisted; the
    source path is deliberately not part of this DTO.
    """

    role: RecognitionImageRole | str
    mime: str
    content: bytes = field(repr=False)
    source_hash: str = ""
    prepared_hash: str = ""
    source_size: tuple[int, int] = (0, 0)
    crop_bbox: BBox | None = None
    padding: int = 0
    output_size: tuple[int, int] = (0, 0)
    scale: float = 1.0
    preprocessing_version: str = "preprocess-v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", _coerce_role(self.role))
        _require_text(self.mime, "mime")
        if not isinstance(self.content, bytes) or not self.content:
            raise RecognitionImageError("invalid_image_content", "content must be non-empty bytes")
        _require_text(self.source_hash, "source_hash")
        _require_text(self.prepared_hash, "prepared_hash")
        _require_size(self.source_size, "source_size")
        _require_size(self.output_size, "output_size")
        if self.crop_bbox is not None and not isinstance(self.crop_bbox, BBox):
            raise RecognitionImageError("invalid_crop_bbox", "crop_bbox must be a BBox or None")
        if not isinstance(self.padding, int) or isinstance(self.padding, bool) or self.padding < 0:
            raise RecognitionImageError("invalid_padding", "padding must be a non-negative integer")
        if not isinstance(self.scale, (int, float)) or isinstance(self.scale, bool) or self.scale <= 0:
            raise RecognitionImageError("invalid_scale", "scale must be a positive number")
        _require_text(self.preprocessing_version, "preprocessing_version")


class RegionImagePreprocessor:
    """Build in-memory provider images from validated requests and source facts."""

    def __init__(
        self,
        *,
        max_image_bytes: int = 20 * 1024 * 1024,
        max_image_pixels: int = 50_000_000,
        max_prepared_side: int = 2048,
        max_crop_area: int = 4_000_000,
        context_side: int = 512,
    ):
        for field_name, value in (
            ("max_image_bytes", max_image_bytes),
            ("max_image_pixels", max_image_pixels),
            ("max_prepared_side", max_prepared_side),
            ("max_crop_area", max_crop_area),
            ("context_side", context_side),
        ):
            _require_positive_int(value, field_name)
        self.max_image_bytes = max_image_bytes
        self.max_image_pixels = max_image_pixels
        self.max_prepared_side = max_prepared_side
        self.max_crop_area = max_crop_area
        self.context_side = context_side

    def prepare(
        self,
        validated_request: ValidatedRecognitionRequest,
        task_spec: RecognitionTaskSpec,
    ) -> tuple[PreparedRecognitionImage, ...]:
        """Return one prepared image per target (or one full-page image)."""

        _require_instance(validated_request, ValidatedRecognitionRequest, "validated_request")
        _require_instance(task_spec, RecognitionTaskSpec, "task_spec")
        if not validated_request.image_path:
            raise RecognitionImageError("missing_image_path", "validated request must carry a source image path")

        source_bytes = _read_source_bytes(validated_request.image_path, self.max_image_bytes)
        image = _open_verified_image(source_bytes, self.max_image_pixels)
        image = ImageOps.exif_transpose(image)
        width, height = image.size
        task_type = validated_request.task_type

        if task_type is RecognitionTaskType.PAGE_SUMMARY:
            resized, scale = _resize_within(image, self.max_prepared_side)
            content = _encode_png(resized)
            return (
                _build_prepared_image(
                    role=RecognitionImageRole.PAGE,
                    source_bytes=source_bytes,
                    source_size=(width, height),
                    crop_bbox=BBox(0, 0, resized.width, resized.height),
                    padding=0,
                    output_size=(resized.width, resized.height),
                    scale=scale,
                    content=content,
                    preprocessing_version=validated_request.preprocessing_version,
                ),
            )

        padding = _padding_for(task_spec.crop_policy_id)
        prepared: list[PreparedRecognitionImage] = []
        for target in validated_request.targets:
            if target.bbox is None:
                raise RecognitionImageError("missing_bbox", "element task targets must carry a bbox")
            crop_bbox = _padded_crop_bbox(target.bbox, padding, width, height)
            _require_crop_area(crop_bbox, self.max_crop_area)
            crop_image, scale = _crop_and_resize(image, crop_bbox, self.max_prepared_side)
            content = _encode_png(crop_image)
            prepared.append(
                _build_prepared_image(
                    role=RecognitionImageRole.TARGET,
                    source_bytes=source_bytes,
                    source_size=(width, height),
                    crop_bbox=crop_bbox,
                    padding=padding,
                    output_size=(crop_image.width, crop_image.height),
                    scale=scale,
                    content=content,
                    preprocessing_version=validated_request.preprocessing_version,
                )
            )
            prepared.extend(
                _prepare_context_images(
                    image=image,
                    source_bytes=source_bytes,
                    target=target,
                    validated_request=validated_request,
                    context_side=self.context_side,
                    max_crop_area=self.max_crop_area,
                )
            )
        return tuple(prepared)


def _build_prepared_image(
    *,
    role: RecognitionImageRole,
    source_bytes: bytes,
    source_size: tuple[int, int],
    crop_bbox: BBox,
    padding: int,
    output_size: tuple[int, int],
    scale: float,
    content: bytes,
    preprocessing_version: str,
) -> PreparedRecognitionImage:
    return PreparedRecognitionImage(
        role=role,
        mime="image/png",
        content=content,
        source_hash=hashlib.sha256(source_bytes).hexdigest(),
        prepared_hash=hashlib.sha256(content).hexdigest(),
        source_size=source_size,
        crop_bbox=crop_bbox,
        padding=padding,
        output_size=output_size,
        scale=scale,
        preprocessing_version=preprocessing_version,
    )


def _padding_for(crop_policy_id: str) -> int:
    try:
        return _CROP_POLICY_PADDING[crop_policy_id]
    except KeyError as exc:
        raise RecognitionImageError("unknown_crop_policy", "crop policy is not registered") from exc


def _padded_crop_bbox(bbox: BBox, padding: int, width: int, height: int) -> BBox:
    return BBox(
        max(0, bbox.x_min - padding),
        max(0, bbox.y_min - padding),
        min(width, bbox.x_max + padding),
        min(height, bbox.y_max + padding),
    )


def _prepare_context_images(
    *,
    image: Image.Image,
    source_bytes: bytes,
    target: Any,
    validated_request: ValidatedRecognitionRequest,
    context_side: int,
    max_crop_area: int,
) -> tuple[PreparedRecognitionImage, ...]:
    prepared: list[PreparedRecognitionImage] = []
    for ref in validated_request.context_elements:
        if ref.element_id not in target.context_element_ids:
            continue
        _require_crop_area(ref.bbox, max_crop_area)
        context_image, scale = _crop_and_resize(image, ref.bbox, context_side)
        content = _encode_png(context_image)
        prepared.append(
            _build_prepared_image(
                role=RecognitionImageRole.CONTEXT,
                source_bytes=source_bytes,
                source_size=image.size,
                crop_bbox=ref.bbox,
                padding=0,
                output_size=(context_image.width, context_image.height),
                scale=scale,
                content=content,
                preprocessing_version=validated_request.preprocessing_version,
            )
        )
    return tuple(prepared)


def _crop_and_resize(image: Image.Image, crop_bbox: BBox, max_side: int) -> tuple[Image.Image, float]:
    crop = image.crop((crop_bbox.x_min, crop_bbox.y_min, crop_bbox.x_max, crop_bbox.y_max))
    return _resize_within(crop, max_side)


def _resize_within(image: Image.Image, max_side: int) -> tuple[Image.Image, float]:
    width, height = image.size
    if max(width, height) <= max_side:
        return image, 1.0
    factor = max_side / max(width, height)
    new_size = (max(1, round(width * factor)), max(1, round(height * factor)))
    resized = image.resize(new_size, Image.Resampling.LANCZOS)
    return resized, width / resized.width


def _require_crop_area(crop_bbox: BBox, max_crop_area: int) -> None:
    area = (crop_bbox.x_max - crop_bbox.x_min) * (crop_bbox.y_max - crop_bbox.y_min)
    if area > max_crop_area:
        raise RecognitionImageError("crop_too_large", "crop area exceeds the configured limit")


def _read_source_bytes(image_path: str, max_image_bytes: int) -> bytes:
    try:
        with open(image_path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        raise RecognitionImageError("image_not_readable", "source image file is not readable") from exc
    if len(data) > max_image_bytes:
        raise RecognitionImageError("image_too_large", "source image exceeds the configured byte limit")
    return data


def _open_verified_image(source_bytes: bytes, max_image_pixels: int) -> Image.Image:
    previous_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = max_image_pixels
    try:
        with Image.open(io.BytesIO(source_bytes)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(source_bytes)) as image:
            if image.width * image.height > max_image_pixels:
                raise RecognitionImageError(
                    "image_pixels_exceeded",
                    "source image pixel count exceeds the configured limit",
                )
            return image.copy()
    except Exception as exc:
        if isinstance(exc, RecognitionImageError):
            raise
        raise RecognitionImageError("invalid_image", "source image could not be verified or decoded") from exc
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit


def _encode_png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _coerce_role(value: RecognitionImageRole | str) -> RecognitionImageRole:
    try:
        return value if isinstance(value, RecognitionImageRole) else RecognitionImageRole(value)
    except ValueError as exc:
        raise RecognitionImageError("invalid_image_role", "unsupported image role") from exc


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecognitionImageError("missing_required_field", f"{field_name} must be a non-empty string")
    return value


def _require_size(value: Any, field_name: str) -> None:
    if (
        not isinstance(value, tuple)
        or len(value) != 2
        or not all(isinstance(item, int) and not isinstance(item, bool) and item > 0 for item in value)
    ):
        raise RecognitionImageError("invalid_size", f"{field_name} must be a positive (width, height) tuple")


def _require_instance(value: Any, expected: type, field_name: str) -> None:
    if not isinstance(value, expected):
        raise RecognitionImageError("invalid_input", f"{field_name} must be a {expected.__name__}")


def _require_positive_int(value: Any, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RecognitionImageError("invalid_limit", f"{field_name} must be a positive integer")


__all__ = ("PreparedRecognitionImage", "RecognitionImageError", "RegionImagePreprocessor")
