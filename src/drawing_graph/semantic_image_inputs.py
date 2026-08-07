"""Build immutable model inputs from page source facts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .tool_models import BBox, PageSourceFacts, ToolModelError


@dataclass(frozen=True)
class ElementContextRef:
    """Stable reference to one page element for model context."""

    element_id: str
    element_type: str
    bbox: BBox
    normalized_bbox: BBox

    def __post_init__(self) -> None:
        for field_name in ("element_id", "element_type"):
            _require_text(getattr(self, field_name), field_name)
        _require_bbox(self.bbox)
        _require_bbox(self.normalized_bbox)
        _require_normalized_bbox(self.normalized_bbox)


@dataclass(frozen=True)
class SemanticImageInput:
    """One immutable recognition input for a target page element."""

    page_id: str
    element_id: str
    element_type: str
    image_path: str
    bbox: BBox
    normalized_bbox: BBox
    image_hash: str
    context_refs: tuple[ElementContextRef, ...]

    def __post_init__(self) -> None:
        for field_name in ("page_id", "element_id", "element_type", "image_path", "image_hash"):
            _require_text(getattr(self, field_name), field_name)
        _require_bbox(self.bbox)
        _require_bbox(self.normalized_bbox)
        _require_normalized_bbox(self.normalized_bbox)
        if not isinstance(self.context_refs, tuple) or not all(
            isinstance(item, ElementContextRef) for item in self.context_refs
        ):
            raise ToolModelError("invalid_context_refs", "context_refs must be a tuple of ElementContextRef")


class SemanticImageInputBuilder:
    """Build semantic image inputs without calling models or writing the graph."""

    def __init__(self, image_hash_provider: Callable[[str], str] | None = None):
        self.image_hash_provider = image_hash_provider or _file_image_hash

    def build_input(self, page_facts: PageSourceFacts, element_id: str) -> SemanticImageInput:
        """Build one semantic image input for a target element."""

        if not isinstance(page_facts, PageSourceFacts):
            raise ToolModelError("invalid_page_facts", "page_facts must be a PageSourceFacts")
        _require_text(element_id, "element_id")
        if page_facts.image_path is None:
            raise ToolModelError("INVALID_ARGUMENT", "page image reference is missing")
        target = next((element for element in page_facts.elements if element.element_id == element_id), None)
        if target is None:
            raise ToolModelError("NOT_FOUND", "target element was not found on the page")
        _require_bbox(target.bbox)
        _require_bbox(target.normalized_bbox)
        _require_normalized_bbox(target.normalized_bbox)
        image_hash = page_facts.image_hash or self.image_hash_provider(page_facts.image_path)
        _require_text(image_hash, "image_hash")
        return SemanticImageInput(
            page_id=page_facts.page_id,
            element_id=target.element_id,
            element_type=target.element_type,
            image_path=page_facts.image_path,
            bbox=target.bbox,
            normalized_bbox=target.normalized_bbox,
            image_hash=image_hash,
            context_refs=tuple(
                ElementContextRef(
                    element_id=element.element_id,
                    element_type=element.element_type,
                    bbox=element.bbox,
                    normalized_bbox=element.normalized_bbox,
                )
                for element in page_facts.elements
            ),
        )


def _file_image_hash(image_path: str) -> str:
    try:
        digest = hashlib.sha256()
        with Path(image_path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError as exc:
        raise ToolModelError("INVALID_ARGUMENT", "image file is not readable") from exc


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolModelError("missing_required_field", f"{field_name} must be a non-empty string")
    return value


def _require_bbox(value: Any) -> None:
    if not isinstance(value, BBox):
        raise ToolModelError("invalid_bbox", "bbox must be a BBox instance")


def _require_normalized_bbox(bbox: BBox) -> None:
    if not all(0 <= getattr(bbox, field_name) <= 1 for field_name in ("x_min", "y_min", "x_max", "y_max")):
        raise ToolModelError("invalid_normalized_bbox", "normalized_bbox values must be between 0 and 1")


__all__ = ("ElementContextRef", "SemanticImageInput", "SemanticImageInputBuilder")
