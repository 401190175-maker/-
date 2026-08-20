"""Full-set page content search over a drawing set (read-only)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .page_search_collector import PageContentCollector
from .page_search_matcher import SynonymExpansionMatcher, TextMatcher
from .tool_models import PageSummary, ToolModelError


@dataclass(frozen=True)
class PageSearchHit:
    kind: str
    snippet: str
    element_id: str | None = None


@dataclass(frozen=True)
class PageSearchMatch:
    page_id: str
    page_title: str
    hits: tuple[PageSearchHit, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PageSearchCoverage:
    total_pages: int = 0
    scanned: int = 0
    from_cache: int = 0
    recognized_now: int = 0
    skipped: int = 0


@dataclass(frozen=True)
class PageSearchResult:
    matches: tuple[PageSearchMatch, ...] = field(default_factory=tuple)
    coverage: PageSearchCoverage = field(default_factory=PageSearchCoverage)


def _truncate(text: str, limit: int = 120) -> str:
    return text if len(text) <= limit else text[:limit] + "..."


class PageContentSearchService:
    """Enumerate pages, collect searchable text, and return deterministic matches."""

    def __init__(
        self,
        facade: Any,
        collector: PageContentCollector | None = None,
        matcher: TextMatcher | None = None,
        page_batch_size: int = 100,
    ) -> None:
        self._facade = facade
        self._collector = collector or PageContentCollector(facade)
        self._matcher = matcher or SynonymExpansionMatcher()
        self._page_batch_size = page_batch_size

    def search(
        self,
        drawing_set_id: str,
        query: str,
        *,
        allow_recognition: bool = False,
        recognize_page_limit: int = 10,
        write_back: bool = False,
    ) -> PageSearchResult:
        """Search one drawing set, optionally backfilling unrecognized pages."""

        if not self._matcher.query_tokens(query):
            raise ToolModelError("INVALID_ARGUMENT", "query must contain at least one search token")
        pages = self._enumerate_pages(drawing_set_id)
        matches: list[PageSearchMatch] = []
        from_cache = 0
        recognized_now = 0
        skipped = 0
        recognition_budget = max(0, recognize_page_limit)
        for page in pages:
            content = self._collector.collect(page)
            if content.has_semantic_content:
                from_cache += 1
            elif allow_recognition and recognition_budget > 0:
                recognized_now += 1
                recognition_budget -= 1
                try:
                    self._facade.recognize_page_semantics(
                        page.page_id,
                        target_types=("block", "text"),
                        write_back=write_back,
                    )
                    content = self._collector.collect(page)
                except Exception:
                    recognized_now -= 1
                    skipped += 1
            elif not content.has_semantic_content:
                skipped += 1
            hit_items = [
                item
                for item in content.items
                if self._matcher.matches(query, item.text)
            ]
            if hit_items:
                matches.append(
                    PageSearchMatch(
                        page_id=page.page_id,
                        page_title=page.file_stem,
                        hits=tuple(
                            PageSearchHit(
                                kind=item.kind,
                                snippet=_truncate(item.text),
                                element_id=item.element_id,
                            )
                            for item in hit_items
                        ),
                    )
                )
        return PageSearchResult(
            matches=tuple(matches),
            coverage=PageSearchCoverage(
                total_pages=len(pages),
                scanned=len(pages),
                from_cache=from_cache,
                recognized_now=recognized_now,
                skipped=skipped,
            ),
        )

    def _enumerate_pages(self, drawing_set_id: str) -> list[PageSummary]:
        pages: list[PageSummary] = []
        offset = 0
        while True:
            batch = self._facade.list_pages(
                drawing_set_id,
                limit=self._page_batch_size,
                offset=offset,
            )
            pages.extend(batch)
            if len(batch) < self._page_batch_size:
                break
            offset += len(batch)
        return pages
