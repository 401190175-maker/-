"""Tests for the constrained text-embedding HTTP client."""

from __future__ import annotations

import json
import unittest

from drawing_graph.text_embedding_client import (
    EmbeddingClientConfig,
    HttpTextEmbeddingClient,
    text_embedding_client_from_env,
)


class _FakePost:
    def __init__(self, vectors: list[list[float]]) -> None:
        self._vectors = vectors
        self.calls: list[dict[str, object]] = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append({"url": url, "body": body})
        payload = {
            "data": [
                {"embedding": vector, "index": index}
                for index, vector in enumerate(self._vectors)
            ]
        }
        return 200, json.dumps(payload)


class TextEmbeddingClientTests(unittest.TestCase):
    def test_embed_returns_vectors(self) -> None:
        post = _FakePost([[0.1, 0.2], [0.3, 0.4]])
        client = HttpTextEmbeddingClient(
            EmbeddingClientConfig(api_key="k"),
            http_post=post,
        )
        vectors = client.embed(["排水管道", "挡土墙"])
        self.assertEqual(vectors, [[0.1, 0.2], [0.3, 0.4]])
        self.assertTrue(post.calls)
        self.assertIn("/embeddings", post.calls[0]["url"])

    def test_from_env_returns_none_without_key(self) -> None:
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(text_embedding_client_from_env())

    def test_from_env_returns_client_with_key(self) -> None:
        import os
        from unittest import mock

        with mock.patch.dict(
            os.environ,
            {
                "DASHSCOPE_API_KEY": "k",
                "DRAWING_GRAPH_EMBEDDING_MODEL": "text-embedding-v3",
            },
            clear=False,
        ):
            client = text_embedding_client_from_env()
        self.assertIsNotNone(client)


if __name__ == "__main__":
    unittest.main()
