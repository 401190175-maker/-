"""Integration tests: question understanding -> read-only graph retrieval."""

import unittest

from drawing_graph.assistant_models import AssistantRequest
from drawing_graph.assistant_question_understanding import QuestionUnderstandingService
from drawing_graph.assistant_retrieval_service import GraphRetrievalService


class FakePageFacts:
    page_id = "page:1"
    image_path = "images/page1.png"
    image_size = (100, 200)
    elements = ()


class RecordingFacade:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def get_page_source_facts(
        self,
        page_id: str,
        element_types=None,
        include_image_meta: bool = True,
    ):
        self.calls.append(("get_page_source_facts", page_id))
        return FakePageFacts()


class QuestionRetrievalIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.question_service = QuestionUnderstandingService()

    def test_page_summary_result_can_drive_read_only_retrieval(self):
        facade = RecordingFacade()
        retrieval = GraphRetrievalService(facade)
        question_result = self.question_service.understand(
            AssistantRequest(
                request_id="req:1",
                question="page:1 这张图主要讲什么",
            )
        )
        bundle = retrieval.retrieve(question_result)
        self.assertEqual(("get_page_source_facts", "page:1"), facade.calls[0])
        self.assertTrue(bundle.source_facts)

    def test_clarification_required_does_not_trigger_facade(self):
        facade = RecordingFacade()
        retrieval = GraphRetrievalService(facade)
        question_result = self.question_service.understand(
            AssistantRequest(
                request_id="req:2",
                question="这个图块有哪些关系",
            )
        )
        self.assertEqual("clarification_required", question_result.question_type)
        bundle = retrieval.retrieve(question_result)
        self.assertEqual([], facade.calls)
        self.assertEqual((), bundle.source_facts)

    def test_unknown_or_unsupported_does_not_trigger_facade(self):
        facade = RecordingFacade()
        retrieval = GraphRetrievalService(facade)
        question_result = self.question_service.understand(
            AssistantRequest(
                request_id="req:3",
                question="今天天气怎么样",
            )
        )
        self.assertEqual("unknown_or_unsupported", question_result.question_type)
        bundle = retrieval.retrieve(question_result)
        self.assertEqual([], facade.calls)
        self.assertEqual((), bundle.source_facts)


if __name__ == "__main__":
    unittest.main()
