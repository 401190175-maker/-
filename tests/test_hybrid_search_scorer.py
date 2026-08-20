"""Tests for hybrid lexical + semantic match merging."""

from __future__ import annotations

import unittest

from drawing_graph.hybrid_search_scorer import HybridScorer, SemanticCandidate
from drawing_graph.page_search_service import PageSearchHit, PageSearchMatch


class HybridScorerTests(unittest.TestCase):
    def test_lexical_matches_are_kept(self) -> None:
        lexical = (
            PageSearchMatch(
                page_id="page:1",
                page_title="road_68",
                hits=(PageSearchHit(kind="observation", snippet="排水管道"),),
            ),
        )
        merged = HybridScorer().merge(lexical, (), threshold=0.25, top_k=20)
        self.assertEqual([item.page_id for item in merged], ["page:1"])
        self.assertFalse(merged[0].semantic)

    def test_semantic_only_match_above_threshold_is_added(self) -> None:
        candidates = (
            SemanticCandidate(
                page_id="page:2",
                page_title="road_69",
                score=0.7,
                kind="observation",
                snippet="雨水管布置",
                element_id="element:o",
            ),
        )
        merged = HybridScorer().merge((), candidates, threshold=0.25, top_k=20)
        self.assertEqual([item.page_id for item in merged], ["page:2"])
        self.assertTrue(merged[0].semantic)

    def test_below_threshold_is_dropped_and_top_k_caps(self) -> None:
        candidates = (
            SemanticCandidate("page:a", "a", 0.1, "observation", "x", None),
            SemanticCandidate("page:b", "b", 0.9, "observation", "y", None),
        )
        merged = HybridScorer().merge((), candidates, threshold=0.25, top_k=1)
        self.assertEqual([item.page_id for item in merged], ["page:b"])


if __name__ == "__main__":
    unittest.main()
