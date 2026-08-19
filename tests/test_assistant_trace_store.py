"""Tests for the in-memory trace store (port + implementation)."""

import ast
import unittest
from pathlib import Path

from drawing_graph.assistant_models import AssistantScope
from drawing_graph.assistant_trace_models import (
    ClaimTrace,
    TraceRecord,
    TraceWriteStatus,
)
from drawing_graph.assistant_trace_store import InMemoryTraceStore

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src" / "drawing_graph"


def _make_record(request_id="req:1"):
    return TraceRecord(
        request_id=request_id,
        question="q",
        question_type="page_summary",
        scope=AssistantScope(page_id="page:1"),
        evidence_ids=("evidence:1",),
        claim_ids=("claim:1",),
        answer_status="answered",
    )


def _make_claim_trace(claim_id="claim:1"):
    return ClaimTrace(
        claim_id=claim_id,
        request_id="req:1",
        claim_status="supported",
        statement="s",
        evidence_ids=("evidence:1",),
        citation_ids=("citation:1",),
    )


class InMemoryTraceStoreTests(unittest.TestCase):
    def test_append_trace_returns_recorded(self):
        store = InMemoryTraceStore()
        result = store.append_trace(_make_record())
        self.assertEqual(TraceWriteStatus.RECORDED, result.status)

    def test_get_trace_returns_stored_record(self):
        store = InMemoryTraceStore()
        store.append_trace(_make_record())
        record = store.get_trace("req:1")
        self.assertIsNotNone(record)
        self.assertEqual("req:1", record.request_id)
        self.assertEqual(("evidence:1",), record.evidence_ids)

    def test_get_trace_unknown_returns_none(self):
        store = InMemoryTraceStore()
        self.assertIsNone(store.get_trace("missing"))

    def test_duplicate_request_id_is_not_silently_overwritten(self):
        store = InMemoryTraceStore()
        first = _make_record()
        store.append_trace(first)
        second = _make_record()
        second = TraceRecord(
            request_id="req:1",
            question="different",
            evidence_ids=("evidence:2",),
        )
        result = store.append_trace(second)
        self.assertEqual(TraceWriteStatus.DUPLICATE, result.status)
        stored = store.get_trace("req:1")
        self.assertEqual(("evidence:1",), stored.evidence_ids)

    def test_claim_trace_index_and_lookup(self):
        store = InMemoryTraceStore()
        store.append_claim_trace(_make_claim_trace())
        trace = store.get_claim_trace("claim:1")
        self.assertIsNotNone(trace)
        self.assertEqual("claim:1", trace.claim_id)
        self.assertEqual(("citation:1",), trace.citation_ids)

    def test_get_claim_trace_unknown_returns_none(self):
        store = InMemoryTraceStore()
        self.assertIsNone(store.get_claim_trace("missing"))

    def test_list_feedback_refs_is_empty_by_default(self):
        store = InMemoryTraceStore()
        self.assertEqual((), store.list_feedback_refs("req:1"))


class TraceStoreBoundaryTests(unittest.TestCase):
    def test_store_does_not_import_forbidden_backends(self):
        source = (SRC_DIR / "assistant_trace_store.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        forbidden = (
            "neo4j",
            "neo4j_repository",
            "relation_repository",
            "semantic_repository",
            "semantic_neo4j_repository",
            "qa_http",
            "qa_mcp",
            "qa_service",
            "import_service",
        )
        for name in forbidden:
            self.assertNotIn(name, imported)


if __name__ == "__main__":
    unittest.main()
