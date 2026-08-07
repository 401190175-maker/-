"""Geometry normalization for XAnyLabeling shape points."""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Real
from typing import Any


class GeometryError(ValueError):
    """Raised when shape geometry cannot form a valid bounding box."""

    def __init__(self, category: str, message: str):
        self.category = category
        super().__init__(message)


@dataclass(frozen=True)
class GeometryWarning:
    """A non-fatal geometry warning for audit records."""

    category: str
    message: str


@dataclass(frozen=True)
class GeometryResult:
    """Normalized shape geometry with raw and normalized bounding boxes."""

    bbox: dict[str, float]
    normalized_bbox: dict[str, float]
    center_x: float
    center_y: float
    width: float
    height: float
    warnings: tuple[GeometryWarning, ...] = ()


def normalize_geometry(points: Any, image_width: Real, image_height: Real) -> GeometryResult:
    """Convert shape points into an outer bbox, center, size, and normalized bbox."""

    width_value = _read_positive_number(image_width, "image_width")
    height_value = _read_positive_number(image_height, "image_height")
    normalized_points = _read_points(points)

    x_values = [point[0] for point in normalized_points]
    y_values = [point[1] for point in normalized_points]
    x_min = min(x_values)
    y_min = min(y_values)
    x_max = max(x_values)
    y_max = max(y_values)

    bbox_width = x_max - x_min
    bbox_height = y_max - y_min
    if bbox_width <= 0 or bbox_height <= 0:
        raise GeometryError("invalid_points", "points must form a non-zero area")

    bbox = {
        "x_min": x_min,
        "y_min": y_min,
        "x_max": x_max,
        "y_max": y_max,
    }
    warnings = _out_of_bounds_warnings(bbox, width_value, height_value)

    return GeometryResult(
        bbox=bbox,
        normalized_bbox={
            "x_min": _clamp(x_min / width_value),
            "y_min": _clamp(y_min / height_value),
            "x_max": _clamp(x_max / width_value),
            "y_max": _clamp(y_max / height_value),
        },
        center_x=x_min + bbox_width / 2,
        center_y=y_min + bbox_height / 2,
        width=bbox_width,
        height=bbox_height,
        warnings=warnings,
    )


def _read_positive_number(value: Real, field_name: str) -> float:
    if not isinstance(value, Real) or value <= 0:
        raise GeometryError("invalid_image_size", f"{field_name} must be a positive number")
    return float(value)


def _read_points(points: Any) -> list[tuple[float, float]]:
    if not isinstance(points, list) or len(points) < 2:
        raise GeometryError("invalid_points", "points must contain at least two coordinate pairs")

    normalized_points: list[tuple[float, float]] = []
    for index, point in enumerate(points):
        if not _is_coordinate_pair(point):
            raise GeometryError("invalid_points", f"points[{index}] must be a numeric coordinate pair")
        normalized_points.append((float(point[0]), float(point[1])))

    return normalized_points


def _is_coordinate_pair(point: Any) -> bool:
    return (
        isinstance(point, list | tuple)
        and len(point) == 2
        and isinstance(point[0], Real)
        and isinstance(point[1], Real)
    )


def _out_of_bounds_warnings(
    bbox: dict[str, float],
    image_width: float,
    image_height: float,
) -> tuple[GeometryWarning, ...]:
    if (
        bbox["x_min"] < 0
        or bbox["y_min"] < 0
        or bbox["x_max"] > image_width
        or bbox["y_max"] > image_height
    ):
        return (
            GeometryWarning(
                category="coordinate_out_of_bounds",
                message="bbox extends outside image bounds",
            ),
        )
    return ()


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


__all__ = (
    "GeometryError",
    "GeometryResult",
    "GeometryWarning",
    "normalize_geometry",
)
