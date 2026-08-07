"""Match table captions to the nearest table on the same drawing page."""

from __future__ import annotations

import math
from dataclasses import dataclass

from drawing_graph.models import BBox, ElementRecord, GraphRelation


class CaptionMatchingError(ValueError):
    """Raised when table-caption matching cannot produce classified relations."""

    def __init__(self, category: str, message: str):
        self.category = category
        super().__init__(message)


@dataclass(frozen=True)
class TableCaptionMatchInput:
    """Minimal geometry input required by the table-caption matcher."""

    id: str
    bbox: BBox

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise CaptionMatchingError("invalid_match_input", "match input id must be a non-empty string")
        if not isinstance(self.bbox, BBox):
            raise CaptionMatchingError("invalid_match_input", "match input bbox must be a BBox value")


@dataclass(frozen=True)
class TableCaptionMatch:
    """Pure table-to-caption match result with distance evidence."""

    table_id: str
    table_caption_id: str
    distance: float


def match_table_caption_inputs(
    tables: list[TableCaptionMatchInput],
    captions: list[TableCaptionMatchInput],
) -> list[TableCaptionMatch]:
    """Return nearest-table matches for minimal table-caption inputs."""

    _validate_match_inputs(tables)
    _validate_match_inputs(captions)
    if captions and not tables:
        raise CaptionMatchingError("missing_table", "cannot match table captions without tables")

    matches: list[TableCaptionMatch] = []
    for caption in captions:
        nearest_table = min(
            tables,
            key=lambda table: (_bbox_distance(table.bbox, caption.bbox), table.id),
        )
        matches.append(
            TableCaptionMatch(
                table_id=nearest_table.id,
                table_caption_id=caption.id,
                distance=_bbox_distance(nearest_table.bbox, caption.bbox),
            )
        )

    return matches


def match_table_captions(
    tables: list[ElementRecord],
    captions: list[ElementRecord],
) -> list[GraphRelation]:
    """Return one nearest-table HAS_CAPTION relation for each table caption."""

    _validate_tables(tables)
    _validate_captions(captions)
    matches = match_table_caption_inputs(
        tables=[TableCaptionMatchInput(id=table.id, bbox=table.bbox) for table in tables],
        captions=[TableCaptionMatchInput(id=caption.id, bbox=caption.bbox) for caption in captions],
    )

    relations: list[GraphRelation] = []
    for match in matches:
        relations.append(
            GraphRelation(
                start_id=match.table_id,
                end_id=match.table_caption_id,
                relation_type="HAS_CAPTION",
                properties={},
            )
        )

    return relations


def _validate_tables(tables: list[ElementRecord]) -> None:
    for table in tables:
        if not isinstance(table, ElementRecord):
            raise CaptionMatchingError("invalid_table", "tables must contain ElementRecord values")
        if table.label != "table":
            raise CaptionMatchingError("invalid_table_label", "tables must contain only table elements")


def _validate_captions(captions: list[ElementRecord]) -> None:
    for caption in captions:
        if not isinstance(caption, ElementRecord):
            raise CaptionMatchingError("invalid_caption", "captions must contain ElementRecord values")
        if caption.label != "table caption":
            raise CaptionMatchingError("invalid_caption_label", "captions must contain only table caption elements")


def _validate_match_inputs(inputs: list[TableCaptionMatchInput]) -> None:
    for item in inputs:
        if not isinstance(item, TableCaptionMatchInput):
            raise CaptionMatchingError("invalid_match_input", "match inputs must contain TableCaptionMatchInput values")


def _bbox_distance(first_bbox: BBox, second_bbox: BBox) -> float:
    horizontal_gap = max(first_bbox.x_min - second_bbox.x_max, second_bbox.x_min - first_bbox.x_max, 0)
    vertical_gap = max(first_bbox.y_min - second_bbox.y_max, second_bbox.y_min - first_bbox.y_max, 0)

    return math.hypot(horizontal_gap, vertical_gap)


__all__ = (
    "CaptionMatchingError",
    "TableCaptionMatch",
    "TableCaptionMatchInput",
    "match_table_captions",
    "match_table_caption_inputs",
)
