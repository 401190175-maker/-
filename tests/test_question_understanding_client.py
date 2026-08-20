"""Tests for the constrained question-understanding HTTP client."""

from __future__ import annotations

import json
import unittest

from drawing_graph.question_understanding_client import (
    HttpQuestionUnderstandingClient,
    QuestionUnderstandingClientConfig,
)


class _FakePost:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.calls: list[dict[str, object]] = []

    def __call__(
        self,
        url: str,
        headers: dict[str, str],
        body: dict[str, object],
        timeout: float,
    ) -> tuple[int, str]:
        self.calls.append({"url": url, "body": body})
        return 200, json.dumps(self._payload, ensure_ascii=False)


class HttpQuestionUnderstandingClientTests(unittest.TestCase):
    def test_understand_parses_candidate(self) -> None:
        post = _FakePost(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "question_type": "page_content_search",
                                    "confidence": 0.9,
                                    "ambiguities": [],
                                    "unsupported_parts": [],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }
        )
        client = HttpQuestionUnderstandingClient(
            QuestionUnderstandingClientConfig(api_key="k"),
            http_post=post,
        )
        candidate = client.understand("哪些图关于排水")
        self.assertEqual(candidate.question_type, "page_content_search")
        self.assertEqual(candidate.confidence, 0.9)
        self.assertTrue(post.calls)

    def test_invalid_question_type_raises(self) -> None:
        post = _FakePost(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "question_type": "not_a_real_type",
                                    "confidence": 0.9,
                                    "ambiguities": [],
                                    "unsupported_parts": [],
                                }
                            )
                        }
                    }
                ]
            }
        )
        client = HttpQuestionUnderstandingClient(
            QuestionUnderstandingClientConfig(api_key="k"),
            http_post=post,
        )
        with self.assertRaises(RuntimeError):
            client.understand("哪些图关于排水")


class EnvironmentWiringTests(unittest.TestCase):
    def test_from_env_returns_client_when_key_present(self) -> None:
        import os
        from unittest import mock

        from drawing_graph.question_understanding_client import (
            question_understanding_client_from_env,
        )

        with mock.patch.dict(
            os.environ,
            {
                "DASHSCOPE_API_KEY": "k",
                "DRAWING_GRAPH_QWEN_MODEL": "qwen3-vl-plus",
                "DRAWING_GRAPH_QWEN_BASE_URL": "https://example.com/v1",
            },
            clear=False,
        ):
            client = question_understanding_client_from_env()
        self.assertIsNotNone(client)
        self.assertEqual(client._config.api_key, "k")

    def test_from_env_returns_none_without_key(self) -> None:
        import os
        from unittest import mock

        from drawing_graph.question_understanding_client import (
            question_understanding_client_from_env,
        )

        with mock.patch.dict(os.environ, {}, clear=True):
            client = question_understanding_client_from_env()
        self.assertIsNone(client)

    def test_reason_code_exists(self) -> None:
        from drawing_graph.assistant_models import ReasonCode

        self.assertEqual(
            ReasonCode.QUESTION_UNDERSTANDING_FALLBACK_FAILED.value,
            "question_understanding_fallback_failed",
        )


if __name__ == "__main__":
    unittest.main()
