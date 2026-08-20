"""Full-set page content search over a drawing set (read-only)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from .hybrid_search_scorer import HybridScorer, SemanticCandidate
from .page_search_models import (
    PageSearchCoverage,
    PageSearchHit,
    PageSearchMatch,
    PageSearchResult,
    truncate_snippet as _truncate,
)
from .page_embedding_store import PageEmbeddingStore, cosine_similarity
from .page_search_collector import PageContentCollector
from .page_search_matcher import SynonymExpansionMatcher, TextMatcher
from .text_embedding_client import TextEmbeddingClient
from .tool_models import PageSummary, ToolModelError


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class PageContentSearchService:
    """Enumerate pages, collect searchable text, and return deterministic matches."""

    def __init__(
        self,
        facade: Any,
        collector: PageContentCollector | None = None,
        matcher: TextMatcher | None = None,
        page_batch_size: int = 100,
        embedding_client: TextEmbeddingClient | None = None,
        embedding_store: PageEmbeddingStore | None = None,
        hybrid_scorer: HybridScorer | None = None,
        embedding_model_version: str = "text-embedding-v3",
        semantic_threshold: float = 0.25,
        semantic_top_k: int = 20,
        embed_page_limit: int = 20,
    ) -> None:
        self._facade = facade
        self._collector = collector or PageContentCollector(facade)
        self._matcher = matcher or SynonymExpansionMatcher()
        self._page_batch_size = page_batch_size
        self._embedding_client = embedding_client
        self._embedding_store = embedding_store
        self._hybrid_scorer = hybrid_scorer or HybridScorer()
        self._embedding_model_version = embedding_model_version
        self._semantic_threshold = semantic_threshold
        self._semantic_top_k = semantic_top_k
        self._embed_page_limit = embed_page_limit

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
        semantic_candidates: list[SemanticCandidate] = []
        embedded_now = 0
        embedded_pages = 0
        if self._embedding_client is not None and self._embedding_store is not None:
            query_vector = self._embedding_client.embed([query])[0]
            embed_budget = max(0, self._embed_page_limit)
            for page in pages:
                if not self._embedding_store.has_page(page.page_id):
                    if embed_budget <= 0:
                        continue
                    content = self._collector.collect(page)
                    if not content.has_semantic_content:
                        continue
                    embed_budget -= 1
                    self._embed_chunks(content)
                    embedded_now += 1
                for kind, _text_hash_value, vector in self._embedding_store.page_vectors(
                    page.page_id
                ):
                    score = cosine_similarity(query_vector, vector)
                    if score >= self._semantic_threshold:
                        semantic_candidates.append(
                            SemanticCandidate(
                                page_id=page.page_id,
                                page_title=page.file_stem,
                                score=score,
                                kind=kind,
                                snippet=kind,
                            )
                        )
            matches = list(
                self._hybrid_scorer.merge(
                    tuple(matches),
                    tuple(semantic_candidates),
                    threshold=self._semantic_threshold,
                    top_k=self._semantic_top_k,
                )
            )
            embedded_pages = sum(
                1
                for page in pages
                if self._embedding_store.has_page(page.page_id)
            )
        return PageSearchResult(
            matches=tuple(matches),
            coverage=PageSearchCoverage(
                total_pages=len(pages),
                scanned=len(pages),
                from_cache=from_cache,
                recognized_now=recognized_now,
                skipped=skipped,
                embedded_pages=embedded_pages,
                embedded_now=embedded_now,
                semantic_hits=sum(
                    1 for match in matches if match.semantic
                ),
            ),
        )

    def _embed_chunks(self, content: PageContent) -> None:
        for item in content.items:
            if item.kind in ("observation", "interpretation"):
                vector = self._embedding_client.embed([item.text])[0]
                self._embedding_store.upsert(
                    content.page_id,
                    item.kind,
                    item.element_id,
                    _text_hash(item.text),
                    self._embedding_model_version,
                    vector,
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
