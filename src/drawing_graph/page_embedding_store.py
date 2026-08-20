"""SQLite-backed page embedding cache (outside the graph)."""

from __future__ import annotations

import math
import sqlite3
import struct
from pathlib import Path
from typing import Iterable


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """Return cosine similarity; zero vectors score 0.0."""

    dot = sum(a * b for a, b in zip(left, right))
    norm_left = math.sqrt(sum(value * value for value in left))
    norm_right = math.sqrt(sum(value * value for value in right))
    if norm_left == 0.0 or norm_right == 0.0:
        return 0.0
    return dot / (norm_left * norm_right)


def _pack_vector(vector: Iterable[float]) -> bytes:
    values = tuple(vector)
    return struct.pack(f"{len(values)}d", *values)


def _unpack_vector(blob: bytes) -> list[float]:
    return list(struct.unpack(f"{len(blob) // 8}d", blob))


class PageEmbeddingStore:
    """Cache page text-chunk embeddings keyed by page/kind/element/text-hash."""

    def __init__(self, path: str | Path) -> None:
        self._connection = sqlite3.connect(str(path))
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS page_embedding ("
            "page_id TEXT NOT NULL,"
            "kind TEXT NOT NULL,"
            "element_id TEXT,"
            "text_hash TEXT NOT NULL,"
            "model_version TEXT NOT NULL,"
            "vector BLOB NOT NULL,"
            "PRIMARY KEY (page_id, kind, element_id, text_hash)"
            ")"
        )
        self._connection.commit()

    def upsert(
        self,
        page_id: str,
        kind: str,
        element_id: str | None,
        text_hash: str,
        model_version: str,
        vector: list[float],
    ) -> None:
        self._connection.execute(
            "INSERT OR REPLACE INTO page_embedding "
            "(page_id, kind, element_id, text_hash, model_version, vector) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                page_id,
                kind,
                element_id,
                text_hash,
                model_version,
                _pack_vector(vector),
            ),
        )
        self._connection.commit()

    def page_vectors(self, page_id: str) -> tuple[tuple[str, str, list[float]], ...]:
        """Return (kind, text_hash, vector) rows for one page."""

        rows = self._connection.execute(
            "SELECT kind, text_hash, vector FROM page_embedding WHERE page_id = ?",
            (page_id,),
        ).fetchall()
        return tuple(
            (kind, text_hash, _unpack_vector(blob))
            for kind, text_hash, blob in rows
        )

    def has_page(self, page_id: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM page_embedding WHERE page_id = ? LIMIT 1",
            (page_id,),
        ).fetchone()
        return row is not None

    def close(self) -> None:
        self._connection.close()
