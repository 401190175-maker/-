"""Tests for feedback HTTP request/response models."""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from drawing_graph.assistant_feedback_http_models import (
    HttpFeedbackRequest,
    feedback_result_to_data,
)
from drawing_graph.assistant_feedback_models import FeedbackResult, FeedbackStatus


class HttpFeedbackRequestTests(unittest.TestCase):
    def test_valid_request(self) -> None:
        request = HttpFeedbackRequest(
            action="confirm",
            claim_id="claim:1",
            reason="同意",
        )
        self.assertEqual(request.action, "confirm")
        self.assertEqual(request.claim_id, "claim:1")

    def test_invalid_action_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            HttpFeedbackRequest(action="delete", claim_id="claim:1")

    def test_missing_claim_id_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            HttpFeedbackRequest(action="confirm", claim_id="")


class FeedbackResultSerializationTests(unittest.TestCase):
    def test_result_to_data(self) -> None:
        result = FeedbackResult(
            feedback_id="fb:1",
            status=FeedbackStatus.RECORDED,
            affected_claim_ids=("claim:1",),
            warnings=("note",),
        )
        data = feedback_result_to_data(result)
        self.assertEqual(data["feedback_id"], "fb:1")
        self.assertEqual(data["status"], "recorded")
        self.assertEqual(data["affected_claim_ids"], ["claim:1"])
        self.assertEqual(data["warnings"], ["note"])


if __name__ == "__main__":
    unittest.main()
