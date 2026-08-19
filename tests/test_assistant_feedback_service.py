"""Tests for the feedback service (08 feedback loop)."""

import unittest
from types import SimpleNamespace

from drawing_graph.assistant_models import FeedbackEvent, FactKind
from drawing_graph.assistant_feedback_models import (
    FeedbackAction,
    FeedbackPermission,
    FeedbackStatus,
)
from drawing_graph.assistant_feedback_permissions import FeedbackPermissionPolicy
from drawing_graph.assistant_feedback_service import FeedbackService
from drawing_graph.assistant_feedback_store import InMemoryFeedbackStore
from drawing_graph.assistant_candidate_review_adapter import CandidateReviewAdapterError
from drawing_graph.assistant_trace_models import ClaimTrace
from drawing_graph.assistant_trace_store import InMemoryTraceStore


class _Actor:
    def __init__(self, permissions=()):
        self.permissions = frozenset(permissions)


class _FakeAdapter:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = 0

    def request_review(self, event, claim_trace):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


class _FailingFeedbackStore:
    def append_feedback(self, event):
        raise RuntimeError("store down")

    def append_audit(self, audit):
        raise RuntimeError("store down")

    def get_feedback(self, feedback_id):
        return None

    def list_feedback_for_request(self, request_id):
        return ()

    def list_audit(self, feedback_id):
        return ()

    def set_status(self, feedback_id, status):
        raise RuntimeError("store down")

    def get_status(self, feedback_id):
        return None


def _claim_trace(fact_kinds=(FactKind.CANDIDATE_RELATION,), **overrides):
    values = {
        "claim_id": "claim:1",
        "request_id": "req:1",
        "fact_kinds": fact_kinds,
        "candidate_group_ids": ("candidate-group:1",),
        "relation_spec": "candidate_caption_of",
        "rule_version": "relation-rules-v1",
        "candidates": (
            {
                "candidate_id": "candidate:1",
                "start_id": "caption:1",
                "end_id": "block:1",
                "page_id": "page:1",
                "relation_spec": "candidate_caption_of",
            },
        ),
        "evidence_refs": ("crop:caption:1",),
    }
    values.update(overrides)
    return ClaimTrace(**values)


def _event(action="confirm", claim_id="claim:1", **overrides):
    values = {
        "feedback_id": "feedback:1",
        "request_id": "req:1",
        "claim_id": claim_id,
        "action": action,
        "user_id": "user:1",
    }
    values.update(overrides)
    return FeedbackEvent(**values)


def _trace_store():
    store = InMemoryTraceStore()
    store.append_claim_trace(_claim_trace())
    return store


def _service(trace_store=None, adapter=None, permission_policy=None, feedback_store=None):
    return FeedbackService(
        store=feedback_store or InMemoryFeedbackStore(),
        trace_store=trace_store or _trace_store(),
        permission_policy=permission_policy,
        candidate_review_adapter=adapter,
    )


class FeedbackServiceRecordActionTests(unittest.TestCase):
    def test_confirm_records_feedback_and_returns_recorded(self):
        store = InMemoryFeedbackStore()
        service = _service(feedback_store=store)
        result = service.submit_feedback(
            _event(action="confirm"),
            _Actor((FeedbackPermission.RECORD_FEEDBACK,)),
        )
        self.assertEqual(FeedbackStatus.RECORDED, result.status)
        self.assertEqual(("claim:1",), result.affected_claim_ids)
        self.assertIsNotNone(store.get_feedback("feedback:1"))
        self.assertEqual(FeedbackStatus.RECORDED, store.get_status("feedback:1"))
        self.assertTrue(store.list_audit("feedback:1"))

    def test_reject_and_correct_record_only(self):
        for action in ("reject", "correct"):
            store = InMemoryFeedbackStore()
            service = _service(feedback_store=store)
            result = service.submit_feedback(
                _event(action=action),
                _Actor((FeedbackPermission.RECORD_FEEDBACK,)),
            )
            self.assertEqual(FeedbackStatus.RECORDED, result.status, action)
            self.assertIsNone(result.candidate_review_result)

    def test_correct_sets_new_evidence_request(self):
        service = _service()
        result = service.submit_feedback(
            _event(action="correct", correction="应为候选关系"),
            _Actor((FeedbackPermission.RECORD_FEEDBACK,)),
        )
        self.assertEqual("应为候选关系", result.new_evidence_request)
        self.assertEqual(FeedbackStatus.RECORDED, result.status)

    def test_invalid_action_returns_invalid(self):
        service = _service()
        result = service.submit_feedback(
            _event(action="bogus"),
            _Actor((FeedbackPermission.RECORD_FEEDBACK,)),
        )
        self.assertEqual(FeedbackStatus.INVALID, result.status)

    def test_missing_claim_id_returns_invalid(self):
        service = _service()
        result = service.submit_feedback(
            _event(claim_id=None),
            _Actor((FeedbackPermission.RECORD_FEEDBACK,)),
        )
        self.assertEqual(FeedbackStatus.INVALID, result.status)

    def test_unknown_claim_returns_invalid(self):
        service = _service()
        result = service.submit_feedback(
            _event(claim_id="claim:missing"),
            _Actor((FeedbackPermission.RECORD_FEEDBACK,)),
        )
        self.assertEqual(FeedbackStatus.INVALID, result.status)

    def test_no_permission_returns_forbidden_and_does_not_record(self):
        store = InMemoryFeedbackStore()
        service = _service(feedback_store=store)
        result = service.submit_feedback(_event(action="confirm"), _Actor())
        self.assertEqual(FeedbackStatus.FORBIDDEN, result.status)
        self.assertIsNone(store.get_feedback("feedback:1"))


class FeedbackServiceReviewTests(unittest.TestCase):
    def test_request_review_with_permission_calls_adapter(self):
        adapter = _FakeAdapter(
            result=SimpleNamespace(status="accepted", review_run_id="review-run:1")
        )
        service = _service(
            adapter=adapter,
            permission_policy=FeedbackPermissionPolicy(allow_write_back=True),
        )
        result = service.submit_feedback(
            _event(action="request_review"),
            _Actor(
                (
                    FeedbackPermission.RECORD_FEEDBACK,
                    FeedbackPermission.REQUEST_CANDIDATE_REVIEW,
                )
            ),
        )
        self.assertEqual(FeedbackStatus.ACCEPTED, result.status)
        self.assertEqual(1, adapter.calls)
        self.assertEqual("review-run:1", result.candidate_review_request_id)

    def test_request_review_without_write_back_is_forbidden(self):
        adapter = _FakeAdapter(
            result=SimpleNamespace(status="accepted", review_run_id="review-run:1")
        )
        service = _service(
            adapter=adapter,
            permission_policy=FeedbackPermissionPolicy(allow_write_back=False),
        )
        result = service.submit_feedback(
            _event(action="request_review"),
            _Actor(
                (
                    FeedbackPermission.RECORD_FEEDBACK,
                    FeedbackPermission.REQUEST_CANDIDATE_REVIEW,
                )
            ),
        )
        self.assertEqual(FeedbackStatus.FORBIDDEN, result.status)
        self.assertEqual(0, adapter.calls)

    def test_request_review_adapter_error_returns_unresolved(self):
        adapter = _FakeAdapter(
            error=CandidateReviewAdapterError("incomplete_candidates", "no candidates")
        )
        service = _service(
            adapter=adapter,
            permission_policy=FeedbackPermissionPolicy(allow_write_back=True),
        )
        result = service.submit_feedback(
            _event(action="request_review"),
            _Actor(
                (
                    FeedbackPermission.RECORD_FEEDBACK,
                    FeedbackPermission.REQUEST_CANDIDATE_REVIEW,
                )
            ),
        )
        self.assertEqual(FeedbackStatus.UNRESOLVED, result.status)

    def test_request_review_unresolved_review_result(self):
        adapter = _FakeAdapter(
            result=SimpleNamespace(status="unresolved", review_run_id="review-run:1")
        )
        service = _service(
            adapter=adapter,
            permission_policy=FeedbackPermissionPolicy(allow_write_back=True),
        )
        result = service.submit_feedback(
            _event(action="request_review"),
            _Actor(
                (
                    FeedbackPermission.RECORD_FEEDBACK,
                    FeedbackPermission.REQUEST_CANDIDATE_REVIEW,
                )
            ),
        )
        self.assertEqual(FeedbackStatus.UNRESOLVED, result.status)


class FeedbackServiceFailClosedTests(unittest.TestCase):
    def test_store_write_failure_fails_closed(self):
        adapter = _FakeAdapter(
            result=SimpleNamespace(status="accepted", review_run_id="review-run:1")
        )
        service = _service(
            adapter=adapter,
            feedback_store=_FailingFeedbackStore(),
            permission_policy=FeedbackPermissionPolicy(allow_write_back=True),
        )
        result = service.submit_feedback(
            _event(action="request_review"),
            _Actor(
                (
                    FeedbackPermission.RECORD_FEEDBACK,
                    FeedbackPermission.REQUEST_CANDIDATE_REVIEW,
                )
            ),
        )
        self.assertEqual(FeedbackStatus.FORBIDDEN, result.status)
        self.assertEqual(0, adapter.calls)


if __name__ == "__main__":
    unittest.main()
