"""Per-page searchable content collection through the read-only facade."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .tool_models import PageSummary, ToolModelError


@dataclass(frozen=True)
class PageContentItem:
    """One searchable text fragment with its source kind."""

    kind: str
    text: str
    element_id: str | None = None

    def __post_init__(self) -> None:
        if not self.kind or not self.text:
            raise ValueError("kind and text must be non-empty")


@dataclass(frozen=True)
class PageContent:
    """All searchable text collected from one page."""

    page_id: str
    file_stem: str
    items: tuple[PageContentItem, ...] = field(default_factory=tuple)
    has_semantic_content: bool = False


class PageContentCollector:
    """Collect page title, source labels, observations, and interpretations."""

    _SEMANTIC_KINDS = frozenset({"observation", "interpretation"})

    def __init__(self, facade: Any) -> None:
        self._facade = facade

    def collect(self, page: PageSummary) -> PageContent:
        items: list[PageContentItem] = [
            PageContentItem(kind="page_title", text=page.file_stem)
        ]
        facts = self._facade.get_page_source_facts(page.page_id)
        if facts is not None:
            for element in facts.elements:
                label = (element.source_label or "").strip()
                element_type = (element.element_type or "").strip()
                text = f"{element_type} {label}".strip()
                if text:
                    items.append(
                        PageContentItem(
                            kind="source_label",
                            text=text,
                            element_id=element.element_id,
                        )
                    )
        for observation in self._observations(page.page_id):
            for field_name in ("raw_text", "normalized_text"):
                text = getattr(observation, field_name, None)
                if text:
                    items.append(
                        PageContentItem(
                            kind="observation",
                            text=str(text),
                            element_id=getattr(observation, "target_element_id", None),
                        )
                    )
        for interpretation in self._interpretations(page.page_id):
            for field_name in ("summary", "interpreted_type"):
                text = getattr(interpretation, field_name, None)
                if text:
                    items.append(
                        PageContentItem(
                            kind="interpretation",
                            text=str(text),
                            element_id=getattr(interpretation, "element_id", None),
                        )
                    )
        return PageContent(
            page_id=page.page_id,
            file_stem=page.file_stem,
            items=tuple(items),
            has_semantic_content=any(
                item.kind in self._SEMANTIC_KINDS for item in items
            ),
        )

    def _observations(self, page_id: str) -> tuple[Any, ...]:
        try:
            result = self._facade.list_text_observations(page_id=page_id)
        except ToolModelError as error:
            if error.category != "NOT_FOUND":
                raise
            return ()
        return tuple(result)

    def _interpretations(self, page_id: str) -> tuple[Any, ...]:
        try:
            result = self._facade.list_interpretations(page_id=page_id)
        except ToolModelError as error:
            if error.category != "NOT_FOUND":
                raise
            return ()
        return tuple(result)
