"""Stable DTOs for full-set page content search."""

from __future__ import annotations

from dataclasses import dataclass, field


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
    semantic: bool = False


@dataclass(frozen=True)
class PageSearchCoverage:
    total_pages: int = 0
    scanned: int = 0
    from_cache: int = 0
    recognized_now: int = 0
    skipped: int = 0
    embedded_pages: int = 0
    embedded_now: int = 0
    semantic_hits: int = 0


@dataclass(frozen=True)
class PageSearchResult:
    matches: tuple[PageSearchMatch, ...] = field(default_factory=tuple)
    coverage: PageSearchCoverage = field(default_factory=PageSearchCoverage)


def truncate_snippet(text: str, limit: int = 120) -> str:
    return text if len(text) <= limit else text[:limit] + "..."
