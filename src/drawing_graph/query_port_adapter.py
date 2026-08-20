"""Adapters from existing query services to facade read ports."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .query_service import QueryError
from .tool_models import (
    BBox,
    BlockRelations,
    BlockTrace,
    DrawingSetSummary,
    PageSourceFacts,
    PageSummary,
    ToolModelError,
)


class QueryServiceReadPortAdapter:
    """Project QueryService dictionaries into stable tool facade DTOs."""

    def __init__(self, query_service: Any, source_fact_reader: Any | None = None):
        self.query_service = query_service
        self.source_fact_reader = source_fact_reader

    def list_drawing_sets(self, project_id: str, limit: int = 100) -> list[DrawingSetSummary]:
        rows = self._call(lambda: self.query_service.get_project_sets(project_id, limit))
        return [
            DrawingSetSummary(
                project_id=project_id,
                drawing_set_id=_text(row.get("id"), "id"),
                name=_text(row.get("name"), "name"),
                page_count=row.get("page_count"),
            )
            for row in rows
        ]

    def list_pages(self, drawing_set_id: str, limit: int = 100, offset: int = 0) -> list[PageSummary]:
        rows = self._call(
            lambda: self.query_service.get_set_pages(drawing_set_id, limit, offset)
        )
        return [
            PageSummary(
                drawing_set_id=drawing_set_id,
                page_id=_text(row.get("id"), "id"),
                file_stem=_file_stem(_text(row.get("file_name"), "file_name")),
                page_number=row.get("page_number"),
                image_path=row.get("image_path"),
            )
            for row in rows
        ]

    def get_page_source_facts(
        self,
        page_id: str,
        element_types: tuple[str, ...] | None = None,
        include_image_meta: bool = True,
    ) -> PageSourceFacts | None:
        if self.source_fact_reader is None:
            return None
        return self._call(
            lambda: self.source_fact_reader.get_page_source_facts(page_id, element_types, include_image_meta)
        )

    def get_block_trace(self, block_id: str) -> BlockTrace | None:
        row = self._call(lambda: self.query_service.get_block_trace(block_id))
        if row is None:
            return None
        return BlockTrace(
            block_id=block_id,
            project_id=_text(row.get("project_id"), "project_id"),
            drawing_set_id=_text(row.get("drawing_set_id"), "drawing_set_id"),
            page_id=_text(row.get("page_id"), "page_id"),
            page_number=row.get("page_number"),
            image_path=row.get("image_path"),
            bbox=_bbox(row.get("bbox")),
            normalized_bbox=_bbox(row.get("normalized_bbox")),
            citation_ref=row.get("citation_ref"),
        )

    def get_block_relations(self, block_id: str) -> BlockRelations | None:
        row = self._call(lambda: self.query_service.get_block_relations(block_id))
        if row is None:
            return None
        return BlockRelations(
            block_id=_text(row.get("block_id"), "block_id"),
            caption_ids=tuple(row.get("caption_ids") or ()),
            basic_info_ids=tuple(row.get("basic_info_ids") or ()),
            annotation_ids=tuple(row.get("annotation_ids") or ()),
            section_mark_ids=tuple(row.get("section_mark_ids") or ()),
            candidate_caption_ids=tuple(row.get("candidate_caption_ids") or ()),
            candidate_section_mark_ids=tuple(row.get("candidate_section_mark_ids") or ()),
            relation_status=_text(row.get("relation_status"), "relation_status"),
            basic_info_status=row.get("basic_info_status"),
            basic_info_source=row.get("basic_info_source"),
        )

    def _call(self, callback: Callable[[], Any]) -> Any:
        try:
            return callback()
        except QueryError as exc:
            raise ToolModelError(exc.category, "query service rejected the request") from exc


def _bbox(value: Any) -> BBox:
    if not isinstance(value, dict):
        raise ToolModelError("invalid_bbox", "bbox must be a mapping")
    return BBox(value.get("x_min"), value.get("y_min"), value.get("x_max"), value.get("y_max"))


def _text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolModelError("missing_required_field", f"{field_name} must be a non-empty string")
    return value


def _file_stem(file_name: str) -> str:
    return Path(file_name).stem


__all__ = ("QueryServiceReadPortAdapter",)
