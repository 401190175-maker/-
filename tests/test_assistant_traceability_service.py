"""Tests for the traceability service (07 traceability loop)."""

import ast
import unittest
from pathlib import Path

from drawing_graph.assistant_models import (
    AnswerPackage,
    AssistantRequest,
    AssistantScope,
    Claim,
    FactKind,
    QuestionUnderstandingResult,
)
from drawing_graph.assistant_trace_models import (
    TraceRecord,
    TraceWriteStatus,
)
from drawing_graph.assistant_trace_store import InMemoryTraceStore
from drawing_graph.assistant_traceability_service import TraceabilityService

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src" / "drawing_graph"


def _request():
    return AssistantRequest(request_id="req:1", question="q")


def _question_result():
    return QuestionUnderstandingResult(
        request_id="req:1",
        question_type="block_relations",
        scope=AssistantScope(block_id="block:1"),
    )


def _package():
    claim = Claim(
        claim_id="claim:1",
        statement="候选关系",
        fact_kinds=(FactKind.CANDIDATE_RELATION,),
    )
    return AnswerPackage(
        request_id="req:1",
        question_type="block_relations",
        status="answered",
        claims=(claim,),
    )


class _FailingStore:
    def append_trace(self, record):
        raise RuntimeError("store down")

    def get_trace(self, request_id):
        raise RuntimeError("store down")

    def append_claim_trace(self, claim_trace):
        raise RuntimeError("store down")

    def get_claim_trace(self, claim_id):
        raise RuntimeError("store down")

    def list_feedback_refs(self, request_id):
        raise RuntimeError("store down")


class TraceabilityServiceTests(unittest.TestCase):
    def test_record_and_get_trace(self):
        service = TraceabilityService(InMemoryTraceStore())
        result = service.record_answer_trace(
            request=_request(),
            question_result=_question_result(),
            answer_package=_package(),
        )
        self.assertEqual(TraceWriteStatus.RECORDED, result.status)
        query = service.get_trace("req:1")
        self.assertTrue(query.found)
        self.assertEqual("req:1", query.record.request_id)
        self.assertEqual(("claim:1",), query.record.claim_ids)

    def test_record_indexes_claim_traces(self):
        service = TraceabilityService(InMemoryTraceStore())
        service.record_answer_trace(
            request=_request(),
            question_result=_question_result(),
            answer_package=_package(),
        )
        trace = service.get_claim_trace("claim:1")
        self.assertIsNotNone(trace)
        self.assertEqual("claim:1", trace.claim_id)
        self.assertEqual((FactKind.CANDIDATE_RELATION,), trace.fact_kinds)

    def test_get_trace_unknown_returns_not_found(self):
        service = TraceabilityService(InMemoryTraceStore())
        query = service.get_trace("missing")
        self.assertFalse(query.found)
        self.assertIsNone(query.record)

    def test_get_claim_trace_unknown_returns_none(self):
        service = TraceabilityService(InMemoryTraceStore())
        self.assertIsNone(service.get_claim_trace("missing"))

    def test_store_unavailable_does_not_raise_and_does_not_fail_answer(self):
        service = TraceabilityService(_FailingStore())
        result = service.record_answer_trace(
            request=_request(),
            question_result=_question_result(),
            answer_package=_package(),
        )
        self.assertEqual(TraceWriteStatus.UNAVAILABLE, result.status)
        self.assertIsNotNone(result.warning)
        query = service.get_trace("req:1")
        self.assertFalse(query.found)
        self.assertIn("trace_unavailable", query.warnings)

    def test_record_uses_builder_and_projector_without_write_back(self):
        store = InMemoryTraceStore()
        service = TraceabilityService(store)
        service.record_answer_trace(
            request=_request(),
            question_result=_question_result(),
            answer_package=_package(),
        )
        self.assertIsInstance(store.get_trace("req:1"), TraceRecord)
        self.assertIsNotNone(store.get_claim_trace("claim:1"))


class TraceabilityServiceBoundaryTests(unittest.TestCase):
    def test_service_does_not_import_forbidden_backends(self):
        source = (SRC_DIR / "assistant_traceability_service.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        for name in ("neo4j", "neo4j_repository", "relation_repository", "semantic_repository"):
            self.assertNotIn(name, imported)


if __name__ == "__main__":
    unittest.main()
