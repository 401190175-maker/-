"""Tests for the feedback FastAPI application."""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from drawing_graph.assistant_feedback_http import create_feedback_app
from drawing_graph.config import FeedbackHttpConfig


def _config(**overrides) -> FeedbackHttpConfig:
    values = {
        "api_token": "secret",
        "default_permissions": ("record_feedback",),
        "allow_candidate_review": False,
    }
    values.update(overrides)
    return FeedbackHttpConfig(**values)


class _SeededTraceStore:
    def get_claim_trace(self, claim_id: str):
        return object() if claim_id == "claim:1" else None


class FeedbackHttpAppTests(unittest.TestCase):
    def test_health_live_is_anonymous(self) -> None:
        app = create_feedback_app(_config())
        app.state.feedback_runtime = None
        client = TestClient(app)
        response = client.get("/health/live")
        self.assertEqual(response.status_code, 200)

    def test_feedback_requires_token(self) -> None:
        app = create_feedback_app(_config())
        client = TestClient(app)
        response = client.post(
            "/api/v1/drawing-assistant/feedback",
            json={"action": "confirm", "claim_id": "claim:1"},
        )
        self.assertEqual(response.status_code, 401)

    def test_feedback_success_path(self) -> None:
        from drawing_graph.assistant_feedback_http_runtime import FeedbackHttpRuntime
        from drawing_graph.assistant_feedback_store import InMemoryFeedbackStore

        app = create_feedback_app(_config())
        app.state.feedback_runtime = FeedbackHttpRuntime(
            store=InMemoryFeedbackStore(),
            trace_store=_SeededTraceStore(),
            default_permissions=("record_feedback",),
        )
        client = TestClient(app)
        response = client.post(
            "/api/v1/drawing-assistant/feedback",
            headers={"Authorization": "Bearer secret"},
            json={"action": "confirm", "claim_id": "claim:1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertIn("feedback_id", response.json()["data"])


if __name__ == "__main__":
    unittest.main()
