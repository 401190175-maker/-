"""Tests for converting page search results into AnswerPackage."""

from __future__ import annotations

import unittest

from drawing_graph.assistant_models import (
    ANSWER_CONTRACT_VERSION,
    AssistantScope,
    QuestionType,
)
from drawing_graph.page_search_answer_builder import PageContentSearchAnswerBuilder
from drawing_graph.page_search_service import (
    PageSearchCoverage,
    PageSearchHit,
    PageSearchMatch,
    PageSearchResult,
)


class PageContentSearchAnswerBuilderTests(unittest.TestCase):
    def test_build_answered_with_matches(self) -> None:
        result = PageSearchResult(
            matches=(
                PageSearchMatch(
                    page_id="page:2",
                    page_title="road_68",
                    hits=(PageSearchHit(kind="observation", snippet="排水管道"),),
                ),
            ),
            coverage=PageSearchCoverage(total_pages=2, scanned=2, from_cache=1),
        )
        scope = AssistantScope(drawing_set_id="set:1")
        package = PageContentSearchAnswerBuilder().build(
            request_id="req:1",
            scope=scope,
            result=result,
        )
        self.assertEqual(package.status, "answered")
        self.assertEqual(package.question_type, QuestionType.PAGE_CONTENT_SEARCH.value)
        self.assertEqual(len(package.claims), 1)
        self.assertEqual(package.claims[0].fact_kinds[0], "source_fact")
        self.assertEqual(
            package.machine_answer.answer_contract_version,
            ANSWER_CONTRACT_VERSION,
        )

    def test_build_partial_without_matches(self) -> None:
        result = PageSearchResult(coverage=PageSearchCoverage(total_pages=1, scanned=1))
        package = PageContentSearchAnswerBuilder().build(
            request_id="req:2",
            scope=AssistantScope(drawing_set_id="set:1"),
            result=result,
        )
        self.assertEqual(package.status, "partial")
        self.assertEqual(package.claims, ())


if __name__ == "__main__":
    unittest.main()
