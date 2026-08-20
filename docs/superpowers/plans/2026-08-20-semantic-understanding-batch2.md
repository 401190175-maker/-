# 语义理解升级批次二实施计划（Phase 2B 向量语义检索）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 `search-pages` 增加向量语义检索：查询词与页文本块做余弦相似度 top-k，与词面/同义词结果混合排序；embedding 不可用时自动降级为纯词面。

**Architecture:** 新增 `TextEmbeddingClient`（DashScope 兼容 HTTP）、`PageEmbeddingStore`（SQLite，图谱外缓存）、`HybridScorer`（词面 + 语义融合）；`PageContentSearchService` 在词面扫描后追加语义路径，结果 `PageSearchMatch` 增加 `semantic` 标记，coverage 增加 `embedded_pages/embedded_now/semantic_hits`。

**Tech Stack:** Python 3.14、unittest、sqlite3、struct、DashScope 兼容 HTTP。

**设计文档:** `docs/superpowers/specs/2026-08-20-semantic-understanding-upgrade-design.md`

---

## 文件结构

新建：
- `src/drawing_graph/text_embedding_client.py` — `EmbeddingClientConfig`/`TextEmbeddingClient`/`HttpTextEmbeddingClient`/`text_embedding_client_from_env`
- `src/drawing_graph/page_embedding_store.py` — `PageEmbeddingStore`（SQLite）与 `cosine_similarity`
- `src/drawing_graph/hybrid_search_scorer.py` — `HybridScorer` 与结果合并
- `tests/test_text_embedding_client.py`
- `tests/test_page_embedding_store.py`
- `tests/test_hybrid_search_scorer.py`

修改：
- `src/drawing_graph/page_search_service.py`（`PageSearchMatch.semantic`、语义路径、coverage 扩展）
- `scripts/drawing_graph_tool.py`（语义相关 CLI 参数）
- `README.md`、`docs/acceptance/USER_RUNBOOK.md`
- `tests/test_page_search_service.py`

测试约定：`$env:PYTHONPATH="src"; python -m unittest tests.test_xxx -v`；全量 `python -m unittest discover tests -v`。

---

## Task 1: TextEmbeddingClient + env helper

**Files:**
- Create: `src/drawing_graph/text_embedding_client.py`
- Test: `tests/test_text_embedding_client.py`

- [ ] **Step 1: Write the failing test**

```python
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
            {"DASHSCOPE_API_KEY": "k", "DRAWING_GRAPH_EMBEDDING_MODEL": "text-embedding-v3"},
            clear=False,
        ):
            client = text_embedding_client_from_env()
        self.assertIsNotNone(client)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_text_embedding_client -v` → FAIL（模块不存在）。

- [ ] **Step 3: Implement**

```python
"""Constrained text-embedding client (DashScope-compatible HTTP)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Sequence


@dataclass(frozen=True)
class EmbeddingClientConfig:
    model: str = "text-embedding-v3"
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    timeout_seconds: float = 60.0
    api_key: str = ""


class TextEmbeddingClient:
    """Embedding client protocol: embed texts into fixed-size vectors."""

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        raise NotImplementedError


class HttpTextEmbeddingClient(TextEmbeddingClient):
    def __init__(
        self,
        config: EmbeddingClientConfig,
        http_post: Callable[..., tuple[int, str]] | None = None,
    ) -> None:
        self._config = config
        self._http_post = http_post or self._default_post

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        status, body = self._http_post(
            f"{self._config.base_url.rstrip('/')}/embeddings",
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._config.api_key}",
            },
            {
                "model": self._config.model,
                "input": list(texts),
            },
            self._config.timeout_seconds,
        )
        if status != 200:
            raise RuntimeError(f"text embedding HTTP {status}")
        payload = json.loads(body)
        items = sorted(payload["data"], key=lambda item: item["index"])
        return [list(item["embedding"]) for item in items]

    @staticmethod
    def _default_post(url, headers, body, timeout):
        import requests

        response = requests.post(url, headers=headers, json=body, timeout=timeout)
        return response.status_code, response.text


def text_embedding_client_from_env() -> HttpTextEmbeddingClient | None:
    """Build the embedding client from environment when an API key is present."""

    import os

    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        return None
    return HttpTextEmbeddingClient(
        EmbeddingClientConfig(
            model=os.environ.get("DRAWING_GRAPH_EMBEDDING_MODEL", "text-embedding-v3").strip(),
            base_url=os.environ.get(
                "DRAWING_GRAPH_EMBEDDING_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ).strip(),
            timeout_seconds=float(
                os.environ.get("DRAWING_GRAPH_EMBEDDING_TIMEOUT_SECONDS", "60.0")
            ),
            api_key=api_key,
        )
    )
```

- [ ] **Step 4: Run test to verify it passes** — `python -m unittest tests.test_text_embedding_client -v` → PASS。

- [ ] **Step 5: Commit**

```bash
git add src/drawing_graph/text_embedding_client.py tests/test_text_embedding_client.py
git commit -m "feat(search): constrained text embedding client"
```

---

## Task 2: PageEmbeddingStore（SQLite）+ cosine

**Files:**
- Create: `src/drawing_graph/page_embedding_store.py`
- Test: `tests/test_page_embedding_store.py`

- [ ] **Step 1: Write the failing test**

```python
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
        self.store.upsert("page:1", "observation", "element:1", "hash1", "model-v1", [0.1, 0.2])
        self.store.upsert("page:1", "interpretation", "element:2", "hash2", "model-v1", [0.3, 0.4])
        vectors = self.store.page_vectors("page:1")
        self.assertEqual(len(vectors), 2)
        self.assertEqual(vectors[0][2], [0.1, 0.2])

    def test_missing_page_returns_empty(self) -> None:
        self.assertEqual(self.store.page_vectors("page:9"), ())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails** — `python -m unittest tests.test_page_embedding_store -v` → FAIL。

- [ ] **Step 3: Implement**

```python
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
    return struct.pack(f"{len(tuple(vector))}f", *vector)


def _unpack_vector(blob: bytes) -> list[float]:
    return list(struct.unpack(f"{len(blob) // 4}f", blob))


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
        return tuple((kind, text_hash, _unpack_vector(blob)) for kind, text_hash, blob in rows)

    def has_page(self, page_id: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM page_embedding WHERE page_id = ? LIMIT 1",
            (page_id,),
        ).fetchone()
        return row is not None

    def close(self) -> None:
        self._connection.close()
```

- [ ] **Step 4: Run test to verify it passes** — `python -m unittest tests.test_page_embedding_store -v` → PASS。

- [ ] **Step 5: Commit**

```bash
git add src/drawing_graph/page_embedding_store.py tests/test_page_embedding_store.py
git commit -m "feat(search): sqlite page embedding cache with cosine similarity"
```

---

## Task 3: HybridScorer + PageSearchMatch.semantic

**Files:**
- Modify: `src/drawing_graph/page_search_service.py`（`PageSearchMatch` 加 `semantic: bool = False`）
- Create: `src/drawing_graph/hybrid_search_scorer.py`
- Test: `tests/test_hybrid_search_scorer.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for hybrid lexical + semantic match merging."""

from __future__ import annotations

import unittest

from drawing_graph.hybrid_search_scorer import HybridScorer, SemanticCandidate
from drawing_graph.page_search_service import PageSearchHit, PageSearchMatch


class HybridScorerTests(unittest.TestCase):
    def test_lexical_matches_are_kept(self) -> None:
        lexical = (
            PageSearchMatch(
                page_id="page:1",
                page_title="road_68",
                hits=(PageSearchHit(kind="observation", snippet="排水管道"),),
            ),
        )
        merged = HybridScorer().merge(lexical, (), threshold=0.25, top_k=20)
        self.assertEqual([item.page_id for item in merged], ["page:1"])
        self.assertFalse(merged[0].semantic)

    def test_semantic_only_match_above_threshold_is_added(self) -> None:
        candidates = (
            SemanticCandidate(
                page_id="page:2",
                page_title="road_69",
                score=0.7,
                kind="observation",
                snippet="雨水管布置",
                element_id="element:o",
            ),
        )
        merged = HybridScorer().merge((), candidates, threshold=0.25, top_k=20)
        self.assertEqual([item.page_id for item in merged], ["page:2"])
        self.assertTrue(merged[0].semantic)

    def test_below_threshold_is_dropped_and_top_k_caps(self) -> None:
        candidates = (
            SemanticCandidate("page:a", "a", 0.1, "observation", "x", None),
            SemanticCandidate("page:b", "b", 0.9, "observation", "y", None),
        )
        merged = HybridScorer().merge((), candidates, threshold=0.25, top_k=1)
        self.assertEqual([item.page_id for item in merged], ["page:b"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails** — `python -m unittest tests.test_hybrid_search_scorer -v` → FAIL。

- [ ] **Step 3: Implement**

`src/drawing_graph/page_search_service.py`：`PageSearchMatch` 增加字段：

```python
@dataclass(frozen=True)
class PageSearchMatch:
    page_id: str
    page_title: str
    hits: tuple[PageSearchHit, ...] = field(default_factory=tuple)
    semantic: bool = False
```

`src/drawing_graph/hybrid_search_scorer.py`：

```python
"""Hybrid lexical + semantic search result merging."""

from __future__ import annotations

from dataclasses import dataclass

from .page_search_service import PageSearchHit, PageSearchMatch


@dataclass(frozen=True)
class SemanticCandidate:
    page_id: str
    page_title: str
    score: float
    kind: str
    snippet: str
    element_id: str | None = None


class HybridScorer:
    """Merge lexical matches with semantic candidates by score threshold."""

    def merge(
        self,
        lexical_matches: tuple[PageSearchMatch, ...],
        semantic_candidates: tuple[SemanticCandidate, ...],
        *,
        threshold: float,
        top_k: int,
    ) -> tuple[PageSearchMatch, ...]:
        result: dict[str, PageSearchMatch] = {
            item.page_id: item for item in lexical_matches
        }
        ordered = sorted(
            (item for item in semantic_candidates if item.score >= threshold),
            key=lambda item: item.score,
            reverse=True,
        )
        for candidate in ordered:
            existing = result.get(candidate.page_id)
            if existing is not None:
                result[candidate.page_id] = PageSearchMatch(
                    page_id=existing.page_id,
                    page_title=existing.page_title,
                    hits=existing.hits,
                    semantic=True,
                )
                continue
            if len(result) >= top_k:
                break
            result[candidate.page_id] = PageSearchMatch(
                page_id=candidate.page_id,
                page_title=candidate.page_title,
                hits=(PageSearchHit(kind=candidate.kind, snippet=candidate.snippet, element_id=candidate.element_id),),
                semantic=True,
            )
        return tuple(result.values())
```

- [ ] **Step 4: Run test to verify it passes** — `python -m unittest tests.test_hybrid_search_scorer -v` → PASS。

- [ ] **Step 5: Commit**

```bash
git add src/drawing_graph/page_search_service.py src/drawing_graph/hybrid_search_scorer.py tests/test_hybrid_search_scorer.py
git commit -m "feat(search): hybrid lexical-semantic result scorer"
```

---

## Task 4: 检索服务语义路径 + coverage

**Files:**
- Modify: `src/drawing_graph/page_search_service.py`
- Modify: `tests/test_page_search_service.py`

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_page_search_service.py`：

```python
class SemanticSearchTests(unittest.TestCase):
    def test_semantic_candidate_added_when_client_and_store_configured(self) -> None:
        from drawing_graph.hybrid_search_scorer import HybridScorer, SemanticCandidate
        from drawing_graph.page_embedding_store import PageEmbeddingStore
        from drawing_graph.text_embedding_client import TextEmbeddingClient

        class _EmbeddingClient(TextEmbeddingClient):
            def embed(self, texts):
                return [[1.0, 0.0] for _ in texts]

        class _Store:
            def has_page(self, page_id):
                return page_id == "page:2"

            def page_vectors(self, page_id):
                if page_id == "page:2":
                    return (("observation", "h", [1.0, 0.0]),)
                return ()

        service = PageContentSearchService(
            _ObservingFacade([_page(1), _page(2)], observed_page_id="page:1", text="道路平面图"),
            embedding_client=_EmbeddingClient(),
            embedding_store=_Store(),
            hybrid_scorer=HybridScorer(),
            semantic_threshold=0.5,
            semantic_top_k=20,
        )
        result = service.search("set:1", "排水")
        self.assertEqual(result.coverage.embedded_pages, 1)
        self.assertTrue(any(match.page_id == "page:2" and match.semantic for match in result.matches))
```

- [ ] **Step 2: Run test to verify it fails** — `python -m unittest tests.test_page_search_service.SemanticSearchTests -v` → FAIL（构造参数不存在）。

- [ ] **Step 3: Implement**

`PageContentSearchService.__init__` 增加：

```python
        embedding_client: TextEmbeddingClient | None = None,
        embedding_store: PageEmbeddingStore | None = None,
        hybrid_scorer: HybridScorer | None = None,
        embedding_model_version: str = "text-embedding-v3",
        semantic_threshold: float = 0.25,
        semantic_top_k: int = 20,
        embed_page_limit: int = 20,
```

赋值：

```python
        self._embedding_client = embedding_client
        self._embedding_store = embedding_store
        self._hybrid_scorer = hybrid_scorer or HybridScorer()
        self._embedding_model_version = embedding_model_version
        self._semantic_threshold = semantic_threshold
        self._semantic_top_k = semantic_top_k
        self._embed_page_limit = embed_page_limit
```

`search()` 词面循环后追加：

```python
        semantic_candidates: list[SemanticCandidate] = []
        embedded_now = 0
        embedded_pages = 0
        if self._embedding_client is not None and self._embedding_store is not None:
            query_vector = self._embedding_client.embed([query])[0]
            embed_budget = max(0, embed_page_limit)
            for page in pages:
                if not self._embedding_store.has_page(page.page_id):
                    if embed_budget <= 0:
                        continue
                    content = self._collector.collect(page)
                    if not content.has_semantic_content:
                        continue
                    embed_budget -= 1
                    self._embed_chunks(content)
                    embedded_now += 1
                for kind, _text_hash, vector in self._embedding_store.page_vectors(page.page_id):
                    score = cosine_similarity(query_vector, vector)
                    if score >= self._semantic_threshold:
                        semantic_candidates.append(
                            SemanticCandidate(
                                page_id=page.page_id,
                                page_title=page.file_stem,
                                score=score,
                                kind=kind,
                                snippet=kind,
                            )
                        )
            matches = list(
                self._hybrid_scorer.merge(
                    tuple(matches),
                    tuple(semantic_candidates),
                    threshold=self._semantic_threshold,
                    top_k=self._semantic_top_k,
                )
            )
            embedded_pages = sum(
                1 for page in pages if self._embedding_store.has_page(page.page_id)
            )
```

新增辅助方法：

```python
    def _embed_chunks(self, content: PageContent) -> None:
        for item in content.items:
            if item.kind in ("observation", "interpretation"):
                vector = self._embedding_client.embed([item.text])[0]
                self._embedding_store.upsert(
                    content.page_id,
                    item.kind,
                    item.element_id,
                    _text_hash(item.text),
                    self._embedding_model_version,
                    vector,
                )
```

并在文件顶部提供 `_text_hash(text) -> str`（`hashlib.sha256(text.encode("utf-8")).hexdigest()`）；引入 `from .hybrid_search_scorer import HybridScorer, SemanticCandidate`、`from .page_embedding_store import PageEmbeddingStore, cosine_similarity`、`from .text_embedding_client import TextEmbeddingClient`、`import hashlib`。coverage 返回增加：

```python
        embedded_pages=embedded_pages,
        embedded_now=embedded_now,
        semantic_hits=sum(1 for match in matches if match.semantic),
```

（`PageSearchCoverage` 增加三个默认字段 `embedded_pages: int = 0`、`embedded_now: int = 0`、`semantic_hits: int = 0`；`embedded_pages` 统计本册内 `has_page` 的页数。）

- [ ] **Step 4: Run test to verify it passes** — `python -m unittest tests.test_page_search_service -v` → PASS（含新增）。

- [ ] **Step 5: Commit**

```bash
git add src/drawing_graph/page_search_service.py tests/test_page_search_service.py
git commit -m "feat(search): semantic retrieval path with hybrid ranking and coverage"
```

---

## Task 5: CLI 语义参数

**Files:**
- Modify: `scripts/drawing_graph_tool.py`
- Modify: `tests/test_page_search_service.py`（CLI 用例扩展）

- [ ] **Step 1: Write the failing test**

追加：

```python
class SemanticCliTests(unittest.TestCase):
    def test_cli_accepts_semantic_flags(self) -> None:
        import io
        import json
        import sys

        import scripts.drawing_graph_tool as cli

        class _Config:
            neo4j_uri = "bolt://127.0.0.1:7687"
            neo4j_user = "neo4j"
            neo4j_password = "x"

        class _Driver:
            pass

        captured = io.StringIO()
        original = sys.stdout
        sys.stdout = captured
        try:
            code = cli.main(
                [
                    "search-pages",
                    "--drawing-set-id",
                    "set:1",
                    "--query",
                    "排水",
                    "--semantic-threshold",
                    "0.3",
                    "--semantic-top-k",
                    "10",
                ],
                config_loader=lambda: _Config(),
                driver_factory=lambda uri, auth: _Driver(),
                facade_factory=lambda driver: _ObservingFacade(
                    [_page(1)],
                    observed_page_id="page:1",
                    text="排水管道",
                ),
            )
        finally:
            sys.stdout = original
        self.assertEqual(code, 0)
        payload = json.loads(captured.getvalue())
        self.assertEqual(payload["status"], "ok")
```

- [ ] **Step 2: Run test to verify it fails** — `python -m unittest tests.test_page_search_service.SemanticCliTests -v` → FAIL（参数不识别）。

- [ ] **Step 3: Implement**

`search-pages` 子命令增加：

```python
    search_pages.add_argument("--semantic-threshold", type=float, default=0.25)
    search_pages.add_argument("--semantic-top-k", type=int, default=20)
    search_pages.add_argument("--embed-page-limit", type=int, default=20)
```

`_run_selected_command` 的 `search-pages` 分支改为构造语义组件并传入：

```python
    if args.command == "search-pages":
        from drawing_graph.hybrid_search_scorer import HybridScorer
        from drawing_graph.page_embedding_store import PageEmbeddingStore
        from drawing_graph.page_search_service import PageContentSearchService
        from drawing_graph.text_embedding_client import text_embedding_client_from_env

        embedding_client = text_embedding_client_from_env()
        embedding_store = None
        if embedding_client is not None:
            embedding_store = PageEmbeddingStore(
                PROJECT_ROOT / ".search_cache" / "page_embeddings.sqlite"
            )
        service = PageContentSearchService(
            facade,
            embedding_client=embedding_client,
            embedding_store=embedding_store,
            hybrid_scorer=HybridScorer(),
            semantic_threshold=args.semantic_threshold,
            semantic_top_k=args.semantic_top_k,
            embed_page_limit=args.embed_page_limit,
        )
        return service.search(
            args.drawing_set_id,
            args.query,
            allow_recognition=args.allow_recognition,
            recognize_page_limit=args.recognize_page_limit,
            write_back=args.write_back,
        )
```

（`PROJECT_ROOT` 已在脚本顶部定义。）

- [ ] **Step 4: Run test to verify it passes** — `python -m unittest tests.test_page_search_service -v` → PASS。

- [ ] **Step 5: Commit**

```bash
git add scripts/drawing_graph_tool.py tests/test_page_search_service.py
git commit -m "feat(cli): semantic search flags for search-pages"
```

---

## Task 6: 文档、全量回归与 live 验收

**Files:**
- Modify: `README.md`、`docs/acceptance/USER_RUNBOOK.md`

- [ ] **Step 1: Run full regression** — `python -m unittest discover tests -v` → 全量通过（integration 跳过）。

- [ ] **Step 2: Update docs**

README/RUNBOOK 的 `search-pages` 段追加：配置 `DASHSCOPE_API_KEY` 且设置 `DRAWING_GRAPH_EMBEDDING_MODEL`（默认 `text-embedding-v3`）后启用向量语义检索，支持 `--semantic-threshold`/`--semantic-top-k`/`--embed-page-limit`；向量缓存位于 `.search_cache/page_embeddings.sqlite`，不可用时自动降级词面。

- [ ] **Step 3: Live acceptance**

```powershell
加载 .env 后：
python scripts\drawing_graph_tool.py search-pages --drawing-set-id set:road-project:lslq_yhd_2_2 --query 排水 --semantic-top-k 10
```

期望：`status=ok`、`coverage.total_pages=230`；语义命中如实返回（含 `semantic` 标记），无命中返回空且不编造。

- [ ] **Step 4: Commit**

```bash
git add README.md docs/acceptance/USER_RUNBOOK.md
git commit -m "docs(search): document semantic retrieval"
```
