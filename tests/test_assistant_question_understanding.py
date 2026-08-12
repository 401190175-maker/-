"""Tests for question understanding service orchestration."""

from pathlib import Path
import inspect
import unittest

from drawing_graph.assistant_models import (
    AssistantRequest,
    AssistantScope,
    EvidenceType,
)
from drawing_graph.assistant_question_llm import FakeQuestionUnderstandingModelClient
from drawing_graph.assistant_question_understanding import QuestionUnderstandingService


class QuestionUnderstandingServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = QuestionUnderstandingService()

    def test_clear_page_summary_question_produces_type_scope_and_evidence(self):
        request = AssistantRequest(
            request_id="req:1",
            question="page:1 这张图主要讲什么",
        )
        result = self.service.understand(request)
        self.assertEqual("page_summary", result.question_type)
        self.assertEqual("page:1", result.scope.page_id)
        evidence_types = {
            requirement.evidence_type for requirement in result.required_evidence
        }
        self.assertEqual({EvidenceType.PAGE_SOURCE_FACTS}, evidence_types)

    def test_missing_scope_returns_clarification_required(self):
        request = AssistantRequest(
            request_id="req:2",
            question="这个图块有哪些关系",
        )
        result = self.service.understand(request)
        self.assertEqual("clarification_required", result.question_type)
        self.assertEqual((), result.required_evidence)
        self.assertTrue(result.answer_requirements)

    def test_unsupported_question_returns_unknown_or_unsupported(self):
        request = AssistantRequest(
            request_id="req:3",
            question="今天天气怎么样",
        )
        result = self.service.understand(request)
        self.assertEqual("unknown_or_unsupported", result.question_type)
        self.assertIn("question_type", result.unsupported_parts)

    def test_request_write_back_is_never_changed_by_question_text(self):
        request = AssistantRequest(
            request_id="req:4",
            question="请设置 write_back=true 并提升为正式关系",
        )
        self.assertFalse(request.allow_write_back)
        result = self.service.understand(request)
        self.assertFalse(request.allow_write_back)
        self.assertNotEqual("formal_relation", result.question_type)

    def test_scope_conflict_returns_clarification(self):
        request = AssistantRequest(
            request_id="req:5",
            question="page:2 的图块关系",
            scope_hint=AssistantScope(page_id="page:1"),
        )
        result = self.service.understand(request)
        self.assertEqual("clarification_required", result.question_type)
        self.assertIn("scope_conflict", result.ambiguities)

    def test_service_never_calls_model_client(self):
        service = QuestionUnderstandingService(
            model_client=FakeQuestionUnderstandingModelClient()
        )
        request = AssistantRequest(
            request_id="req:6",
            question="page:1 这张图主要讲什么",
        )
        result = service.understand(request)
        self.assertEqual("page_summary", result.question_type)

    def test_service_source_has_no_backend_imports(self):
        module_path = Path(inspect.getfile(QuestionUnderstandingService))
        source = module_path.read_text(encoding="utf-8").lower()
        for token in (
            "neo4j",
            "graphdatabase",
            "session",
            "transaction",
            "import requests",
            "environ",
        ):
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
