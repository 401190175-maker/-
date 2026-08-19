"""Tests for the append-only feedback store (port + implementation)."""

import ast
import unittest
from pathlib import Path

from drawing_graph.assistant_models import FeedbackEvent
from drawing_graph.assistant_feedback_models import (
    FeedbackAuditEvent,
    FeedbackStatus,
)
from drawing_graph.assistant_feedback_store import InMemoryFeedbackStore

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src" / "drawing_graph"


def _event(feedback_id="feedback:1", request_id="req:1", action="confirm"):
    return FeedbackEvent(
        feedback_id=feedback_id,
        request_id=request_id,
        claim_id="claim:1",
        action=action,
        user_id="user:1",
    )


class InMemoryFeedbackStoreTests(unittest.TestCase):
    def test_append_and_get_feedback(self):
        store = InMemoryFeedbackStore()
        store.append_feedback(_event())
        event = store.get_feedback("feedback:1")
        self.assertIsNotNone(event)
        self.assertEqual("feedback:1", event.feedback_id)

    def test_duplicate_feedback_id_raises(self):
        store = InMemoryFeedbackStore()
        store.append_feedback(_event())
        with self.assertRaises(ValueError):
            store.append_feedback(_event())

    def test_get_feedback_unknown_returns_none(self):
        store = InMemoryFeedbackStore()
        self.assertIsNone(store.get_feedback("missing"))

    def test_audit_events_are_append_only(self):
        store = InMemoryFeedbackStore()
        first = FeedbackAuditEvent(audit_event_id="audit:1", feedback_id="feedback:1")
        second = FeedbackAuditEvent(audit_event_id="audit:2", feedback_id="feedback:1")
        store.append_audit(first)
        store.append_audit(second)
        self.assertEqual(("audit:1", "audit:2"), tuple(a.audit_event_id for a in store.list_audit("feedback:1")))

    def test_list_feedback_for_request(self):
        store = InMemoryFeedbackStore()
        store.append_feedback(_event("feedback:1", "req:1"))
        store.append_feedback(_event("feedback:2", "req:1"))
        store.append_feedback(_event("feedback:3", "req:2"))
        events = store.list_feedback_for_request("req:1")
        self.assertEqual(("feedback:1", "feedback:2"), tuple(e.feedback_id for e in events))

    def test_status_tracking(self):
        store = InMemoryFeedbackStore()
        store.append_feedback(_event())
        store.set_status("feedback:1", FeedbackStatus.RECORDED)
        self.assertEqual(FeedbackStatus.RECORDED, store.get_status("feedback:1"))


class FeedbackStoreBoundaryTests(unittest.TestCase):
    def test_store_does_not_import_forbidden_backends(self):
        source = (SRC_DIR / "assistant_feedback_store.py").read_text(encoding="utf-8")
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
