"""Hybrid lexical + semantic search result merging."""

from __future__ import annotations

from dataclasses import dataclass

from .page_search_service import PageSearchHit, PageSearchMatch


@dataclass(frozen=True)
class SemanticCandidate:
    page_id: str
    page_title: str
    score: float
    kind: str
    snippet: str
    element_id: str | None = None


class HybridScorer:
    """Merge lexical matches with semantic candidates by score threshold."""

    def merge(
        self,
        lexical_matches: tuple[PageSearchMatch, ...],
        semantic_candidates: tuple[SemanticCandidate, ...],
        *,
        threshold: float,
        top_k: int,
    ) -> tuple[PageSearchMatch, ...]:
        result: dict[str, PageSearchMatch] = {
            item.page_id: item for item in lexical_matches
        }
        ordered = sorted(
            (item for item in semantic_candidates if item.score >= threshold),
            key=lambda item: item.score,
            reverse=True,
        )
        for candidate in ordered:
            existing = result.get(candidate.page_id)
            if existing is not None:
                result[candidate.page_id] = PageSearchMatch(
                    page_id=existing.page_id,
                    page_title=existing.page_title,
                    hits=existing.hits,
                    semantic=True,
                )
                continue
            if len(result) >= top_k:
                break
            result[candidate.page_id] = PageSearchMatch(
                page_id=candidate.page_id,
                page_title=candidate.page_title,
                hits=(
                    PageSearchHit(
                        kind=candidate.kind,
                        snippet=candidate.snippet,
                        element_id=candidate.element_id,
                    ),
                ),
                semantic=True,
            )
        return tuple(result.values())
