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
from drawing_graph.tool_models import PageSummary, ToolModelError


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


class _SearchFakeFacade:
    def list_pages(self, drawing_set_id: str, limit: int = 100, offset: int = 0):
        return (PageSummary(drawing_set_id=drawing_set_id, page_id="page:1", file_stem="road_68"),)

    def get_page_source_facts(self, page_id: str, element_types=None, include_image_meta=True):
        return None

    def list_text_observations(self, page_id=None, element_id=None, recognition_run_id=None, statuses=None, write_back=False):
        return (
            type(
                "O",
                (),
                {
                    "raw_text": "排水管道",
                    "normalized_text": "排水管道",
                    "target_element_id": "element:o",
                },
            )(),
        )

    def list_interpretations(self, page_id=None, element_id=None, recognition_run_id=None, statuses=None, write_back=False):
        raise ToolModelError("NOT_FOUND", "no interpretations")


class DrawingAssistantSearchPathTests(unittest.TestCase):
    def test_service_answers_search_question(self) -> None:
        from drawing_graph.assistant_models import AssistantRequest, AssistantScope, QuestionType
        from drawing_graph.drawing_assistant_factory import create_drawing_assistant_service

        service = create_drawing_assistant_service(facade=_SearchFakeFacade())
        request = AssistantRequest(
            request_id="req:search-e2e",
            question="哪些图关于排水",
            scope_hint=AssistantScope(drawing_set_id="set:1"),
        )
        package = service.answer(request)
        self.assertEqual(package.question_type, QuestionType.PAGE_CONTENT_SEARCH.value)
        self.assertIn(package.status, {"answered", "partial"})


if __name__ == "__main__":
    unittest.main()
