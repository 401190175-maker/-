"""Tests for the SQLite page embedding store and cosine similarity."""

from __future__ import annotations

import math
import os
import tempfile
import unittest

from drawing_graph.page_embedding_store import (
    PageEmbeddingStore,
    cosine_similarity,
)


class CosineTests(unittest.TestCase):
    def test_cosine_identical_and_orthogonal(self) -> None:
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [1.0, 0.0]), 1.0)
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [0.0, 1.0]), 0.0)
        self.assertTrue(math.isclose(cosine_similarity([0.0, 0.0], [1.0, 1.0]), 0.0))


class PageEmbeddingStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.store = PageEmbeddingStore(os.path.join(self._dir.name, "emb.sqlite"))

    def tearDown(self) -> None:
        self.store.close()
        self._dir.cleanup()

    def test_upsert_and_load_vectors(self) -> None:
        self.store.upsert(
            "page:1",
            "observation",
            "element:1",
            "hash1",
            "model-v1",
            [0.1, 0.2],
        )
        self.store.upsert(
            "page:1",
            "interpretation",
            "element:2",
            "hash2",
            "model-v1",
            [0.3, 0.4],
        )
        vectors = self.store.page_vectors("page:1")
        self.assertEqual(len(vectors), 2)
        self.assertEqual(
            {tuple(vector) for _kind, _hash, vector in vectors},
            {(0.1, 0.2), (0.3, 0.4)},
        )

    def test_missing_page_returns_empty(self) -> None:
        self.assertEqual(self.store.page_vectors("page:9"), ())


if __name__ == "__main__":
    unittest.main()
