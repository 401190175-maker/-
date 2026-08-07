"""Stable business identifiers for drawing graph records."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal


ElementKind = Literal["block", "element"]


class IdentifierError(ValueError):
    """Raised when stable ID input cannot be classified."""

    def __init__(self, category: str, message: str):
        self.category = category
        super().__init__(message)


def make_project_id(project_slug: str) -> str:
    """Return the stable project ID."""

    return f"project:{_require_text(project_slug, 'project_slug')}"


def make_set_id(project_slug: str, drawing_set_name: str) -> str:
    """Return the stable drawing-set ID."""

    return f"set:{_require_text(project_slug, 'project_slug')}:{_require_text(drawing_set_name, 'drawing_set_name')}"


def make_page_id(project_slug: str, drawing_set_name: str, file_stem: str) -> str:
    """Return the stable drawing-page ID."""

    return (
        f"page:{_require_text(project_slug, 'project_slug')}:"
        f"{_require_text(drawing_set_name, 'drawing_set_name')}:"
        f"{_require_text(file_stem, 'file_stem')}"
    )


def make_element_id(
    kind: ElementKind,
    project_slug: str,
    drawing_set_name: str,
    file_stem: str,
    shape_hash: str,
) -> str:
    """Return a stable block or non-block page-element ID."""

    if kind not in ("block", "element"):
        raise IdentifierError("invalid_element_kind", "kind must be 'block' or 'element'")

    return (
        f"{kind}:{_require_text(project_slug, 'project_slug')}:"
        f"{_require_text(drawing_set_name, 'drawing_set_name')}:"
        f"{_require_text(file_stem, 'file_stem')}:"
        f"{_require_text(shape_hash, 'shape_hash')}"
    )


def make_shape_hash(shape: dict[str, Any]) -> str:
    """Return a deterministic hash from normalized label, shape_type, and points."""

    if not isinstance(shape, dict):
        raise IdentifierError("invalid_shape", "shape must be a dictionary")

    payload = {
        "label": _require_text(shape.get("label"), "label"),
        "shape_type": _require_text(shape.get("shape_type"), "shape_type"),
        "points": _canonical_points(shape.get("points")),
    }
    serialized_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    return hashlib.sha256(serialized_payload.encode("utf-8")).hexdigest()[:16]


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise IdentifierError("invalid_identifier_part", f"{field_name} must be a non-empty string")
    return value


def _canonical_points(points: Any) -> list[list[int | float]]:
    if not isinstance(points, list):
        raise IdentifierError("invalid_points", "points must be a list")

    return [_canonical_point(point, index) for index, point in enumerate(points)]


def _canonical_point(point: Any, index: int) -> list[int | float]:
    if not isinstance(point, list | tuple) or len(point) != 2:
        raise IdentifierError("invalid_points", f"points[{index}] must contain exactly two coordinates")

    return [_canonical_number(point[0], index), _canonical_number(point[1], index)]


def _canonical_number(value: Any, index: int) -> int | float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise IdentifierError("invalid_points", f"points[{index}] coordinates must be numbers")
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


__all__ = (
    "IdentifierError",
    "make_element_id",
    "make_page_id",
    "make_project_id",
    "make_set_id",
    "make_shape_hash",
)
