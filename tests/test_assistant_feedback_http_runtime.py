"""Tests for the feedback HTTP runtime."""

from __future__ import annotations

import unittest

from drawing_graph.assistant_feedback_http_models import HttpFeedbackRequest
from drawing_graph.assistant_feedback_http_runtime import FeedbackHttpRuntime
from drawing_graph.assistant_feedback_store import InMemoryFeedbackStore


class _FakeTraceStore:
    def __init__(self, known_claims: tuple[str, ...] = ()) -> None:
        self._known = set(known_claims)

    def get_claim_trace(self, claim_id: str):
        return object() if claim_id in self._known else None


class FeedbackHttpRuntimeTests(unittest.TestCase):
    def test_confirm_with_default_permission_is_recorded(self) -> None:
        store = InMemoryFeedbackStore()
        trace = _FakeTraceStore(("claim:1",))
        runtime = FeedbackHttpRuntime(
            store=store,
            trace_store=trace,
            default_permissions=("record_feedback",),
            allow_candidate_review=False,
        )
        result = runtime.submit(HttpFeedbackRequest(action="confirm", claim_id="claim:1"))
        self.assertIn(result.status.value, {"recorded", "received", "validated"})
        self.assertTrue(store.get_feedback(result.feedback_id) is not None)

    def test_request_review_without_permission_is_forbidden(self) -> None:
        runtime = FeedbackHttpRuntime(
            store=InMemoryFeedbackStore(),
            trace_store=_FakeTraceStore(("claim:1",)),
            default_permissions=("record_feedback",),
            allow_candidate_review=False,
        )
        result = runtime.submit(
            HttpFeedbackRequest(action="request_review", claim_id="claim:1")
        )
        self.assertEqual(result.status.value, "forbidden")


if __name__ == "__main__":
    unittest.main()
