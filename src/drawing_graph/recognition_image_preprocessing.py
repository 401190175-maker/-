"""In-memory region image preprocessing for the 04 execution layer."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from typing import Any

from PIL import Image

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

        source_bytes = _read_source_bytes(validated_request.image_path)
        image = _open_verified_image(source_bytes)
        width, height = image.size
        task_type = validated_request.task_type

        if task_type is RecognitionTaskType.PAGE_SUMMARY:
            content = _encode_png(image)
            return (
                _build_prepared_image(
                    role=RecognitionImageRole.PAGE,
                    source_bytes=source_bytes,
                    source_size=(width, height),
                    crop_bbox=BBox(0, 0, width, height),
                    padding=0,
                    output_size=(width, height),
                    scale=1.0,
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
            crop_image = image.crop((crop_bbox.x_min, crop_bbox.y_min, crop_bbox.x_max, crop_bbox.y_max))
            content = _encode_png(crop_image)
            prepared.append(
                _build_prepared_image(
                    role=RecognitionImageRole.TARGET,
                    source_bytes=source_bytes,
                    source_size=(width, height),
                    crop_bbox=crop_bbox,
                    padding=padding,
                    output_size=(crop_image.width, crop_image.height),
                    scale=1.0,
                    content=content,
                    preprocessing_version=validated_request.preprocessing_version,
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


def _read_source_bytes(image_path: str) -> bytes:
    try:
        with open(image_path, "rb") as handle:
            return handle.read()
    except OSError as exc:
        raise RecognitionImageError("image_not_readable", "source image file is not readable") from exc


def _open_verified_image(source_bytes: bytes) -> Image.Image:
    try:
        with Image.open(io.BytesIO(source_bytes)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(source_bytes)) as image:
            return image.copy()
    except Exception as exc:
        raise RecognitionImageError("invalid_image", "source image could not be verified or decoded") from exc


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


__all__ = ("PreparedRecognitionImage", "RecognitionImageError", "RegionImagePreprocessor")
