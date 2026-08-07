"""Read-only business ports used by the tool facade."""

from __future__ import annotations

from typing import Protocol

from .tool_models import BlockRelations, BlockTrace, DrawingSetSummary, PageSourceFacts, PageSummary


class DrawingGraphReadPort(Protocol):
    """Minimum read contract exposed to the tool facade."""

    def list_drawing_sets(self, project_id: str, limit: int = 100) -> list[DrawingSetSummary]:
        """Return drawing set summaries for one project."""

    def list_pages(self, drawing_set_id: str, limit: int = 100) -> list[PageSummary]:
        """Return page summaries for one drawing set."""

    def get_page_source_facts(
        self,
        page_id: str,
        element_types: tuple[str, ...] | None = None,
        include_image_meta: bool = True,
    ) -> PageSourceFacts | None:
        """Return source evidence for one page."""

    def get_block_trace(self, block_id: str) -> BlockTrace | None:
        """Return project, set, page, and geometry trace for one block."""

    def get_block_relations(self, block_id: str) -> BlockRelations | None:
        """Return derived relation identifiers for one block."""


class FakeDrawingGraphReadPort:
    """In-memory read port for facade unit tests."""

    def __init__(
        self,
        drawing_sets: tuple[DrawingSetSummary, ...] = (),
        pages: tuple[PageSummary, ...] = (),
        source_facts: dict[str, PageSourceFacts] | None = None,
        block_traces: dict[str, BlockTrace] | None = None,
        block_relations: dict[str, BlockRelations] | None = None,
    ):
        self._drawing_sets = tuple(drawing_sets)
        self._pages = tuple(pages)
        self._source_facts = dict(source_facts or {})
        self._block_traces = dict(block_traces or {})
        self._block_relations = dict(block_relations or {})
        self.calls_with_internal_dependencies: list[str] = []

    def list_drawing_sets(self, project_id: str, limit: int = 100) -> list[DrawingSetSummary]:
        return [item for item in self._drawing_sets if item.project_id == project_id][:limit]

    def list_pages(self, drawing_set_id: str, limit: int = 100) -> list[PageSummary]:
        return [item for item in self._pages if item.drawing_set_id == drawing_set_id][:limit]

    def get_page_source_facts(
        self,
        page_id: str,
        element_types: tuple[str, ...] | None = None,
        include_image_meta: bool = True,
    ) -> PageSourceFacts | None:
        facts = self._source_facts.get(page_id)
        if facts is None:
            return None
        elements = facts.elements
        if element_types is not None:
            allowed = set(element_types)
            elements = tuple(element for element in elements if element.element_type in allowed)
        image_size = facts.image_size if include_image_meta else None
        return PageSourceFacts(
            page_id=facts.page_id,
            image_path=facts.image_path,
            image_size=image_size,
            elements=elements,
        )

    def get_block_trace(self, block_id: str) -> BlockTrace | None:
        return self._block_traces.get(block_id)

    def get_block_relations(self, block_id: str) -> BlockRelations | None:
        return self._block_relations.get(block_id)


__all__ = ("DrawingGraphReadPort", "FakeDrawingGraphReadPort")
