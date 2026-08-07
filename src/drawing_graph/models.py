"""Domain data models for normalized drawing graph records."""

from __future__ import annotations

from dataclasses import dataclass, field
from numbers import Real
from typing import Any, Literal


ImportStatus = Literal["success", "skipped", "failed", "running"]


class ModelError(ValueError):
    """Raised when a domain model receives invalid data."""

    def __init__(self, category: str, message: str):
        self.category = category
        super().__init__(message)


@dataclass(frozen=True)
class BBox:
    """Absolute image-space bounding box."""

    x_min: float
    y_min: float
    x_max: float
    y_max: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "x_min", _read_number(self.x_min, "x_min"))
        object.__setattr__(self, "y_min", _read_number(self.y_min, "y_min"))
        object.__setattr__(self, "x_max", _read_number(self.x_max, "x_max"))
        object.__setattr__(self, "y_max", _read_number(self.y_max, "y_max"))
        if self.x_max <= self.x_min or self.y_max <= self.y_min:
            raise ModelError("invalid_bbox", "bbox must have positive width and height")

    def to_dict(self) -> dict[str, float]:
        """Serialize bbox using the fixed graph/query field names."""

        return {
            "x_min": self.x_min,
            "y_min": self.y_min,
            "x_max": self.x_max,
            "y_max": self.y_max,
        }


@dataclass(frozen=True)
class NormalizedBBox(BBox):
    """Bounding box normalized to the 0-to-1 image range."""

    def __post_init__(self) -> None:
        super().__post_init__()
        if not all(0 <= value <= 1 for value in (self.x_min, self.y_min, self.x_max, self.y_max)):
            raise ModelError("invalid_normalized_bbox", "normalized bbox values must be between 0 and 1")


@dataclass(frozen=True)
class PageRecord:
    """Normalized drawing page record before graph mapping."""

    id: str
    page_number: int
    file_name: str
    json_path: str
    image_path: str
    original_image_path: str
    image_width: float
    image_height: float

    def __post_init__(self) -> None:
        _require_text(self.id, "id")
        _require_positive_int(self.page_number, "page_number")
        _require_text(self.file_name, "file_name")
        _require_text(self.json_path, "json_path")
        _require_text(self.image_path, "image_path")
        _require_text(self.original_image_path, "original_image_path")
        object.__setattr__(self, "image_width", _read_positive_number(self.image_width, "image_width"))
        object.__setattr__(self, "image_height", _read_positive_number(self.image_height, "image_height"))


@dataclass(frozen=True)
class ElementRecord:
    """Normalized page element record with source label and geometry evidence."""

    id: str
    page_id: str
    label: str
    confidence: float | None
    shape_type: str
    bbox: BBox
    normalized_bbox: NormalizedBBox
    source_label: str
    original_points: tuple[tuple[float, float], ...]
    citation_ref: str

    def __post_init__(self) -> None:
        _require_text(self.id, "id")
        _require_text(self.page_id, "page_id")
        _require_text(self.label, "label")
        _require_text(self.shape_type, "shape_type")
        _require_text(self.source_label, "source_label")
        _require_text(self.citation_ref, "citation_ref")
        if not isinstance(self.bbox, BBox):
            raise ModelError("invalid_bbox", "bbox must be a BBox")
        if not isinstance(self.normalized_bbox, NormalizedBBox):
            raise ModelError("invalid_normalized_bbox", "normalized_bbox must be a NormalizedBBox")
        if self.confidence is not None:
            object.__setattr__(self, "confidence", _read_confidence(self.confidence))
        object.__setattr__(self, "original_points", _read_original_points(self.original_points))


@dataclass(frozen=True)
class GraphNode:
    """Neo4j node payload with fixed labels and parameterized properties."""

    id: str
    labels: tuple[str, ...]
    properties: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.id, "id")
        object.__setattr__(self, "labels", _read_text_tuple(self.labels, "labels"))
        if not isinstance(self.properties, dict):
            raise ModelError("invalid_properties", "properties must be a dictionary")


@dataclass(frozen=True)
class GraphRelation:
    """Neo4j relationship payload between two stable business IDs."""

    start_id: str
    end_id: str
    relation_type: str
    properties: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.start_id, "start_id")
        _require_text(self.end_id, "end_id")
        _require_text(self.relation_type, "relation_type")
        if not isinstance(self.properties, dict):
            raise ModelError("invalid_properties", "properties must be a dictionary")


@dataclass(frozen=True)
class ImportResult:
    """Single import operation result with status, warnings, and errors."""

    status: ImportStatus
    page_id: str | None
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in ("success", "skipped", "failed", "running"):
            raise ModelError("invalid_import_status", "status must be success, skipped, failed, or running")
        if self.page_id is not None:
            _require_text(self.page_id, "page_id")
        object.__setattr__(self, "warnings", _read_text_tuple(self.warnings, "warnings"))
        object.__setattr__(self, "errors", _read_text_tuple(self.errors, "errors"))


def _read_number(value: Real, field_name: str) -> float:
    if not isinstance(value, Real) or isinstance(value, bool):
        raise ModelError("invalid_number", f"{field_name} must be a number")
    return float(value)


def _read_positive_number(value: Real, field_name: str) -> float:
    number = _read_number(value, field_name)
    if number <= 0:
        raise ModelError("invalid_image_size", f"{field_name} must be positive")
    return number


def _require_positive_int(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ModelError("invalid_page_number", f"{field_name} must be a positive integer")


def _require_text(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ModelError("missing_required_field", f"{field_name} must be a non-empty string")


def _read_confidence(value: Real) -> float:
    confidence = _read_number(value, "confidence")
    if not 0 <= confidence <= 1:
        raise ModelError("invalid_confidence", "confidence must be between 0 and 1")
    return confidence


def _read_original_points(points: Any) -> tuple[tuple[float, float], ...]:
    if not isinstance(points, tuple) or not points:
        raise ModelError("invalid_points", "original_points must be a non-empty tuple")

    normalized_points: list[tuple[float, float]] = []
    for index, point in enumerate(points):
        if not isinstance(point, tuple) or len(point) != 2:
            raise ModelError("invalid_points", f"original_points[{index}] must contain two coordinates")
        normalized_points.append((_read_number(point[0], "x"), _read_number(point[1], "y")))
    return tuple(normalized_points)


def _read_text_tuple(values: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise ModelError("invalid_sequence", f"{field_name} must be a tuple")
    for index, value in enumerate(values):
        if not isinstance(value, str) or not value:
            raise ModelError("invalid_sequence", f"{field_name}[{index}] must be a non-empty string")
    return values


__all__ = (
    "BBox",
    "ElementRecord",
    "GraphNode",
    "GraphRelation",
    "ImportResult",
    "ModelError",
    "NormalizedBBox",
    "PageRecord",
)
