"""Tests for the feedback DTO contracts (08 feedback loop)."""

import ast
import unittest
from pathlib import Path

from drawing_graph.assistant_feedback_models import (
    FeedbackAction,
    FeedbackAuditEvent,
    FeedbackPermission,
    FeedbackResult,
    FeedbackStatus,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src" / "drawing_graph"


class FeedbackEnumTests(unittest.TestCase):
    def test_feedback_actions_are_stable(self):
        self.assertEqual(
            {"confirm", "reject", "correct", "request_review"},
            {action.value for action in FeedbackAction},
        )

    def test_feedback_statuses_are_stable(self):
        self.assertEqual(
            {
                "received",
                "validated",
                "recorded",
                "review_required",
                "accepted",
                "rejected",
                "unresolved",
                "forbidden",
                "invalid",
            },
            {status.value for status in FeedbackStatus},
        )

    def test_feedback_permissions_are_stable(self):
        self.assertEqual(
            {
                "read_trace",
                "record_feedback",
                "request_candidate_review",
                "promote_formal_relation",
            },
            {permission.value for permission in FeedbackPermission},
        )


class FeedbackAuditEventTests(unittest.TestCase):
    def test_audit_event_carries_status_transition(self):
        event = FeedbackAuditEvent(
            audit_event_id="audit:1",
            feedback_id="feedback:1",
            request_id="req:1",
            event_type="transition",
            from_status=FeedbackStatus.RECEIVED,
            to_status=FeedbackStatus.VALIDATED,
            actor_id="user:1",
        )
        self.assertEqual("audit:1", event.audit_event_id)
        self.assertEqual(FeedbackStatus.VALIDATED, event.to_status)
        self.assertEqual("user:1", event.actor_id)

    def test_audit_event_requires_feedback_id(self):
        with self.assertRaises(ValueError):
            FeedbackAuditEvent(audit_event_id="audit:1", feedback_id="")


class FeedbackResultTests(unittest.TestCase):
    def test_result_carries_status_and_claim_ids(self):
        result = FeedbackResult(
            feedback_id="feedback:1",
            status=FeedbackStatus.RECORDED,
            affected_claim_ids=("claim:1",),
        )
        self.assertEqual("feedback:1", result.feedback_id)
        self.assertEqual(FeedbackStatus.RECORDED, result.status)
        self.assertEqual(("claim:1",), result.affected_claim_ids)

    def test_result_carries_candidate_review_reference(self):
        result = FeedbackResult(
            feedback_id="feedback:1",
            status=FeedbackStatus.ACCEPTED,
            candidate_review_request_id="review-run:1",
            candidate_review_result={"status": "accepted"},
        )
        self.assertEqual("review-run:1", result.candidate_review_request_id)
        self.assertEqual({"status": "accepted"}, result.candidate_review_result)

    def test_result_coerces_status_string(self):
        result = FeedbackResult(feedback_id="feedback:1", status="forbidden")
        self.assertEqual(FeedbackStatus.FORBIDDEN, result.status)

    def test_result_requires_feedback_id(self):
        with self.assertRaises(ValueError):
            FeedbackResult(feedback_id="")


class FeedbackModelsBoundaryTests(unittest.TestCase):
    def test_feedback_models_do_not_import_forbidden_backends(self):
        source = (SRC_DIR / "assistant_feedback_models.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        for name in ("neo4j", "candidate_review", "relation_repository", "semantic_repository"):
            self.assertNotIn(name, imported)


if __name__ == "__main__":
    unittest.main()
