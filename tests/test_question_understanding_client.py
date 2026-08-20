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


if __name__ == "__main__":
    unittest.main()
