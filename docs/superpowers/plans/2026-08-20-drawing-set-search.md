# 图纸册全册检索（A+B+问题理解增强）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让产品问答能识别并回答“哪些图关于排水”“挡土墙在哪一页”“哪块砖是 C35”等工程师口吻问题：新增图纸册级只读内容检索（含按需识别补齐与缓存复用），并增强问题理解（规则扩展 + LLM 兜底）。

**Architecture:** 新增 `PageContentCollector`（逐页收集标题/来源标签/观察/解释文本）、`TextMatcher`（中文分词 token 子串匹配）、`PageContentSearchService`（分页枚举 + 匹配 + coverage + 按需识别钩子）、`PageContentSearchAnswerBuilder`（把检索结果组装为 `AnswerPackage`）。产品问答在 `DrawingAssistantService` 中对 `page_content_search` 走专用窄路径，不动既有证据融合流水线；问题理解以规则扩展为主，LLM 客户端仅兜底。

**Tech Stack:** Python 3.14、unittest、Neo4j（只读 facade）、DashScope 兼容 HTTP（识别与 LLM 兜底）、argparse CLI。

**设计文档:** `docs/superpowers/specs/2026-08-20-drawing-set-search-design.md`

---

## 文件结构

新建：
- `src/drawing_graph/page_search_matcher.py` — `TextMatcher` 与 `normalize_text`
- `src/drawing_graph/page_search_collector.py` — `PageContentItem`/`PageContent`/`PageContentCollector`
- `src/drawing_graph/page_search_service.py` — `PageSearchHit`/`PageSearchMatch`/`PageSearchCoverage`/`PageSearchResult`/`PageContentSearchService`
- `src/drawing_graph/page_search_answer_builder.py` — `PageContentSearchAnswerBuilder`
- `src/drawing_graph/question_understanding_client.py` — `QuestionUnderstandingClientConfig`/`HttpQuestionUnderstandingClient`
- `tests/test_page_search_matcher.py`
- `tests/test_page_search_collector.py`
- `tests/test_page_search_service.py`
- `tests/test_page_search_answer_builder.py`
- `tests/test_page_search_contracts.py`
- `tests/test_page_search_pagination.py`
- `tests/test_page_search_routing.py`
- `tests/test_page_search_scope.py`
- `tests/test_question_understanding_client.py`

修改：
- `src/drawing_graph/assistant_models.py` — `QuestionType.PAGE_CONTENT_SEARCH`
- `src/drawing_graph/assistant_evidence_templates.py` — 证据映射
- `src/drawing_graph/assistant_clarification.py` — 必需 scope
- `src/drawing_graph/assistant_question_rules.py` — 新规则与漏网句式修正
- `src/drawing_graph/assistant_scope_resolution.py` — `drawing_set` 前缀提取
- `src/drawing_graph/assistant_question_understanding.py` — LLM 兜底接入
- `src/drawing_graph/query_service.py` — `get_set_pages` offset
- `src/drawing_graph/query_ports.py` — read port `list_pages` offset
- `src/drawing_graph/query_port_adapter.py` — offset 透传
- `src/drawing_graph/tool_facade.py` — `list_pages` offset
- `src/drawing_graph/drawing_assistant_service.py` — `page_content_search` 专用路径
- `scripts/drawing_graph_tool.py` — `search-pages` 命令与 `list-pages --offset`

测试命令约定：项目使用 unittest，运行单个文件用 `python -m unittest tests.test_xxx -v`；全量回归用 `python -m unittest discover tests -v`。

---

## Task 1: page_content_search 契约（QuestionType/证据模板/澄清）

**Files:**
- Modify: `src/drawing_graph/assistant_models.py`（QuestionType 枚举）
- Modify: `src/drawing_graph/assistant_evidence_templates.py`
- Modify: `src/drawing_graph/assistant_clarification.py`
- Test: `tests/test_page_search_contracts.py`

- [ ] **Step 1: Write the failing test**

```python
"""Contract tests for the page_content_search question type."""

from __future__ import annotations

import unittest

from drawing_graph.assistant_clarification import _REQUIRED_SCOPE_FIELDS
from drawing_graph.assistant_evidence_templates import EvidenceRequirementFactory
from drawing_graph.assistant_models import (
    AssistantRequest,
    AssistantScope,
    EvidenceType,
    QuestionType,
)


def _request() -> AssistantRequest:
    return AssistantRequest(request_id="req:search-contract", question="哪些图关于排水")


class PageContentSearchContractTests(unittest.TestCase):
    def test_question_type_value(self) -> None:
        self.assertEqual(QuestionType.PAGE_CONTENT_SEARCH.value, "page_content_search")

    def test_evidence_template_maps_to_search_evidence(self) -> None:
        factory = EvidenceRequirementFactory()
        requirements = factory.build(
            QuestionType.PAGE_CONTENT_SEARCH,
            AssistantScope(drawing_set_id="set:road-project:lslq_yhd_2_2"),
            _request(),
        )
        types = tuple(item.evidence_type for item in requirements)
        self.assertEqual(
            types,
            (
                EvidenceType.DRAWING_SET_PAGES,
                EvidenceType.PAGE_SOURCE_FACTS,
                EvidenceType.TEXT_OBSERVATIONS,
                EvidenceType.STRUCTURED_INTERPRETATIONS,
            ),
        )

    def test_clarification_requires_drawing_set_id(self) -> None:
        self.assertEqual(_REQUIRED_SCOPE_FIELDS["page_content_search"], ("drawing_set_id",))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_page_search_contracts -v`
Expected: FAIL — `QuestionType` has no `PAGE_CONTENT_SEARCH`，`_REQUIRED_SCOPE_FIELDS` 无 `page_content_search` 键。

- [ ] **Step 3: Implement minimal changes**

在 `src/drawing_graph/assistant_models.py` 的 `QuestionType` 枚举末尾（`UNKNOWN_OR_UNSUPPORTED` 之前）加入：

```python
      PAGE_CONTENT_SEARCH = "page_content_search"
```

在 `src/drawing_graph/assistant_evidence_templates.py` 的 `_evidence_types_for` 中、`return ()` 之前加入：

```python
    if question_type == QuestionType.PAGE_CONTENT_SEARCH.value:
        return (
            EvidenceType.DRAWING_SET_PAGES,
            EvidenceType.PAGE_SOURCE_FACTS,
            EvidenceType.TEXT_OBSERVATIONS,
            EvidenceType.STRUCTURED_INTERPRETATIONS,
        )
```

在 `src/drawing_graph/assistant_clarification.py` 的 `_REQUIRED_SCOPE_FIELDS` 中、`source_trace` 行之后加入：

```python
    "page_content_search": ("drawing_set_id",),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_page_search_contracts -v`
Expected: PASS（3 个用例）。

- [ ] **Step 5: Commit**

```bash
git add src/drawing_graph/assistant_models.py src/drawing_graph/assistant_evidence_templates.py src/drawing_graph/assistant_clarification.py tests/test_page_search_contracts.py
git commit -m "feat(question): add page_content_search question type contract"
```

---

## Task 2: list_pages offset 分页

**Files:**
- Modify: `src/drawing_graph/query_service.py`
- Modify: `src/drawing_graph/query_ports.py`
- Modify: `src/drawing_graph/query_port_adapter.py`
- Modify: `src/drawing_graph/tool_facade.py`
- Modify: `scripts/drawing_graph_tool.py`
- Test: `tests/test_page_search_pagination.py`

- [ ] **Step 1: Write the failing test**

```python
"""Pagination tests for the page read path."""

from __future__ import annotations

import unittest

from drawing_graph.query_port_adapter import QueryServiceReadPortAdapter


class _FakeQueryService:
    def __init__(self, page_count: int) -> None:
        self._page_count = page_count

    def get_set_pages(self, drawing_set_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, object]]:
        pages = [
            {
                "id": f"page:{index}",
                "file_name": f"road_{index}.json",
                "page_number": index,
                "image_path": None,
            }
            for index in range(self._page_count)
        ]
        return pages[offset : offset + limit]


class PagePaginationTests(unittest.TestCase):
    def test_list_pages_honors_offset(self) -> None:
        adapter = QueryServiceReadPortAdapter(_FakeQueryService(page_count=5))
        pages = adapter.list_pages("set:1", limit=2, offset=3)
        self.assertEqual([page.page_id for page in pages], ["page:3", "page:4"])

    def test_list_pages_default_offset_is_zero(self) -> None:
        adapter = QueryServiceReadPortAdapter(_FakeQueryService(page_count=3))
        pages = adapter.list_pages("set:1", limit=2)
        self.assertEqual([page.page_id for page in pages], ["page:0", "page:1"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_page_search_pagination -v`
Expected: FAIL — `get_set_pages` 不接受 `offset` 参数。

- [ ] **Step 3: Implement minimal changes**

`src/drawing_graph/query_service.py`：

```python
    def get_set_pages(self, drawing_set_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, object]]:
        """Return pages that belong to a drawing set ordered by page number."""

        _require_text(drawing_set_id, "drawing_set_id")
        result_limit = _require_positive_int(limit, "limit")
        result_offset = _require_non_negative_int(offset, "offset")

        with self.driver.session() as session:
            return session.execute_read(
                lambda transaction: _get_set_pages(transaction, drawing_set_id, result_limit, result_offset)
            )
```

同一文件中 `_get_set_pages` 改为：

```python
def _get_set_pages(
    transaction: Any,
    drawing_set_id: str,
    limit: int,
    offset: int,
) -> list[dict[str, object]]:
    cypher = (
        "MATCH (drawing_set:DrawingSet {id: $drawing_set_id})-[:HAS_PAGE]->(page:DrawingPage)\n"
        "RETURN page.id AS id,\n"
        "       page.file_name AS file_name,\n"
        "       page.page_number AS page_number,\n"
        "       page.image_path AS image_path\n"
        "ORDER BY page.page_number ASC, page.file_name ASC, page.id ASC\n"
        "SKIP $offset\n"
        "LIMIT $limit"
    )
    records = transaction.run(
        cypher,
        drawing_set_id=drawing_set_id,
        limit=limit,
        offset=offset,
    )
    return [
        {
            "id": _record_value(record, "id"),
            "file_name": _record_value(record, "file_name"),
            "page_number": _record_value(record, "page_number"),
            "image_path": _record_value(record, "image_path"),
        }
        for record in records
    ]
```

若 `_require_non_negative_int` 不存在，在文件顶部 `_require_positive_int` 附近新增：

```python
def _require_non_negative_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value
```

`src/drawing_graph/query_ports.py`：`DrawingGraphReadPort` 与 `FakeDrawingGraphReadPort` 的 `list_pages` 签名改为 `def list_pages(self, drawing_set_id: str, limit: int = 100, offset: int = 0) -> list[PageSummary]:`，Fake 实现改为 `return self.pages[offset : offset + limit]`（字段名按现有 Fake 实现，若不存在 `self.pages`，用其既有列表字段）。

`src/drawing_graph/query_port_adapter.py`：

```python
    def list_pages(self, drawing_set_id: str, limit: int = 100, offset: int = 0) -> list[PageSummary]:
        rows = self._call(
            lambda: self.query_service.get_set_pages(drawing_set_id, limit, offset)
        )
        return [
            PageSummary(
                drawing_set_id=drawing_set_id,
                page_id=_text(row.get("id"), "id"),
                file_stem=_file_stem(_text(row.get("file_name"), "file_name")),
                page_number=row.get("page_number"),
                image_path=row.get("image_path"),
            )
            for row in rows
        ]
```

`src/drawing_graph/tool_facade.py`：

```python
    def list_pages(
        self,
        drawing_set_id: str,
        limit: int = 100,
        offset: int = 0,
        write_back: bool = False,
    ) -> list[PageSummary]:
        _reject_write_back(write_back)
        return self._read_call(
            lambda: self.read_port.list_pages(drawing_set_id, limit, offset)
        )
```

`scripts/drawing_graph_tool.py`：`pages` 子命令加参数并在 `_run_selected_command` 透传：

```python
    pages.add_argument("--offset", type=int, default=0)
```

```python
    if args.command == "list-pages":
        return facade.list_pages(args.drawing_set_id, limit=args.limit, offset=args.offset)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_page_search_pagination -v`
Expected: PASS（2 个用例）。

- [ ] **Step 5: Commit**

```bash
git add src/drawing_graph/query_service.py src/drawing_graph/query_ports.py src/drawing_graph/query_port_adapter.py src/drawing_graph/tool_facade.py scripts/drawing_graph_tool.py tests/test_page_search_pagination.py
git commit -m "feat(query): add offset pagination to list_pages read path"
```

---

## Task 3: TextMatcher

**Files:**
- Create: `src/drawing_graph/page_search_matcher.py`
- Test: `tests/test_page_search_matcher.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for deterministic page-search text matching."""

from __future__ import annotations

import unittest

from drawing_graph.page_search_matcher import TextMatcher, normalize_text


class TextMatcherTests(unittest.TestCase):
    def test_normalize_removes_punctuation(self) -> None:
        self.assertEqual(normalize_text("A-A剖面！"), "a-a剖面")

    def test_all_query_tokens_must_match(self) -> None:
        matcher = TextMatcher()
        self.assertTrue(matcher.matches("排水", "本页含排水管道"))
        self.assertFalse(matcher.matches("排水 挡土墙", "本页含排水管道"))

    def test_query_tokens_are_normalized(self) -> None:
        matcher = TextMatcher()
        self.assertTrue(matcher.matches("A-A", "图上有 a-a 剖面"))

    def test_empty_query_never_matches(self) -> None:
        matcher = TextMatcher()
        self.assertFalse(matcher.matches("   ", "任意文本"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_page_search_matcher -v`
Expected: FAIL — `ModuleNotFoundError: drawing_graph.page_search_matcher`。

- [ ] **Step 3: Implement minimal code**

```python
"""Deterministic Chinese-aware text matching for page content search."""

from __future__ import annotations

import re


_TOKEN_SPLIT = re.compile(r"[\s,，。；;:：!！?？()（）]+")
_STRIP = re.compile(r"[^\w\u4e00-\u9fff]+", re.UNICODE)


def normalize_text(text: str) -> str:
    """Lowercase and strip punctuation/space, keeping CJK and ASCII word chars."""

    return _STRIP.sub("", (text or "").lower())


class TextMatcher:
    """Substring token matcher: every normalized query token must appear in text."""

    def __init__(self, tokenizer: object | None = None) -> None:
        self._tokenizer = tokenizer or _TOKEN_SPLIT.split

    def query_tokens(self, query: str) -> tuple[str, ...]:
        """Return normalized, non-empty query tokens."""

        parts = self._tokenizer(query) if callable(self._tokenizer) else _TOKEN_SPLIT.split(query)
        return tuple(normalize_text(part) for part in parts if normalize_text(part))

    def matches(self, query: str, text: str) -> bool:
        """Return True when every query token is a substring of the text."""

        tokens = self.query_tokens(query)
        if not tokens:
            return False
        normalized = normalize_text(text)
        return all(token in normalized for token in tokens)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_page_search_matcher -v`
Expected: PASS（4 个用例）。

- [ ] **Step 5: Commit**

```bash
git add src/drawing_graph/page_search_matcher.py tests/test_page_search_matcher.py
git commit -m "feat(search): add deterministic text matcher"
```

---

## Task 4: PageContentCollector

**Files:**
- Create: `src/drawing_graph/page_search_collector.py`
- Test: `tests/test_page_search_collector.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for per-page searchable content collection."""

from __future__ import annotations

import unittest

from drawing_graph.page_search_collector import PageContentCollector, PageContentItem
from drawing_graph.tool_models import PageSourceFacts, PageSummary, ToolModelError


class _FakeFacade:
    def __init__(
        self,
        facts: PageSourceFacts | None = None,
        observations: tuple[object, ...] = (),
        interpretations: tuple[object, ...] = (),
    ) -> None:
        self._facts = facts
        self._observations = observations
        self._interpretations = interpretations

    def get_page_source_facts(self, page_id: str, element_types=None, include_image_meta=True):
        return self._facts

    def list_text_observations(self, page_id=None, element_id=None, recognition_run_id=None, statuses=None, write_back=False):
        if not self._observations:
            raise ToolModelError("NOT_FOUND", "text observations were not found")
        return self._observations

    def list_interpretations(self, page_id=None, element_id=None, recognition_run_id=None, statuses=None, write_back=False):
        if not self._interpretations:
            raise ToolModelError("NOT_FOUND", "interpretations were not found")
        return self._interpretations


class _FakeObservation:
    raw_text = "排水管道"
    normalized_text = "排水管道"
    target_element_id = "element:1"


class _FakeInterpretation:
    summary = "挡土墙"
    interpreted_type = "retaining_wall"
    element_id = "element:2"


class PageContentCollectorTests(unittest.TestCase):
    def _page(self) -> PageSummary:
        return PageSummary(
            drawing_set_id="set:1",
            page_id="page:1",
            file_stem="road_68",
        )

    def test_collect_includes_title_and_observations(self) -> None:
        collector = PageContentCollector(_FakeFacade(observations=(_FakeObservation(),)))
        content = collector.collect(self._page())
        kinds = {item.kind for item in content.items}
        self.assertIn("page_title", kinds)
        self.assertIn("observation", kinds)
        self.assertTrue(content.has_semantic_content)

    def test_collect_empty_page_has_no_semantic_content(self) -> None:
        collector = PageContentCollector(_FakeFacade())
        content = collector.collect(self._page())
        self.assertFalse(content.has_semantic_content)
        self.assertTrue(any(item.kind == "page_title" for item in content.items))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_page_search_collector -v`
Expected: FAIL — `ModuleNotFoundError: drawing_graph.page_search_collector`。

- [ ] **Step 3: Implement minimal code**

```python
"""Per-page searchable content collection through the read-only facade."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .tool_models import PageSummary, ToolModelError


@dataclass(frozen=True)
class PageContentItem:
    """One searchable text fragment with its source kind."""

    kind: str
    text: str
    element_id: str | None = None

    def __post_init__(self) -> None:
        if not self.kind or not self.text:
            raise ValueError("kind and text must be non-empty")


@dataclass(frozen=True)
class PageContent:
    """All searchable text collected from one page."""

    page_id: str
    file_stem: str
    items: tuple[PageContentItem, ...] = field(default_factory=tuple)
    has_semantic_content: bool = False


class PageContentCollector:
    """Collect page title, source labels, observations, and interpretations."""

    _SEMANTIC_KINDS = frozenset({"observation", "interpretation"})

    def __init__(self, facade: Any) -> None:
        self._facade = facade

    def collect(self, page: PageSummary) -> PageContent:
        items: list[PageContentItem] = [
            PageContentItem(kind="page_title", text=page.file_stem)
        ]
        facts = self._facade.get_page_source_facts(page.page_id)
        if facts is not None:
            for element in facts.elements:
                label = (element.source_label or "").strip()
                element_type = (element.element_type or "").strip()
                text = f"{element_type} {label}".strip()
                if text:
                    items.append(
                        PageContentItem(
                            kind="source_label",
                            text=text,
                            element_id=element.element_id,
                        )
                    )
        for observation in self._observations(page.page_id):
            for field_name in ("raw_text", "normalized_text"):
                text = getattr(observation, field_name, None)
                if text:
                    items.append(
                        PageContentItem(
                            kind="observation",
                            text=str(text),
                            element_id=getattr(observation, "target_element_id", None),
                        )
                    )
        for interpretation in self._interpretations(page.page_id):
            for field_name in ("summary", "interpreted_type"):
                text = getattr(interpretation, field_name, None)
                if text:
                    items.append(
                        PageContentItem(
                            kind="interpretation",
                            text=str(text),
                            element_id=getattr(interpretation, "element_id", None),
                        )
                    )
        return PageContent(
            page_id=page.page_id,
            file_stem=page.file_stem,
            items=tuple(items),
            has_semantic_content=any(
                item.kind in self._SEMANTIC_KINDS for item in items
            ),
        )

    def _observations(self, page_id: str) -> tuple[Any, ...]:
        try:
            result = self._facade.list_text_observations(page_id=page_id)
        except ToolModelError as error:
            if error.category != "NOT_FOUND":
                raise
            return ()
        return tuple(result)

    def _interpretations(self, page_id: str) -> tuple[Any, ...]:
        try:
            result = self._facade.list_interpretations(page_id=page_id)
        except ToolModelError as error:
            if error.category != "NOT_FOUND":
                raise
            return ()
        return tuple(result)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_page_search_collector -v`
Expected: PASS（2 个用例）。

- [ ] **Step 5: Commit**

```bash
git add src/drawing_graph/page_search_collector.py tests/test_page_search_collector.py
git commit -m "feat(search): add per-page searchable content collector"
```

---

## Task 5: PageContentSearchService（扫描+匹配+coverage）

**Files:**
- Create: `src/drawing_graph/page_search_service.py`
- Test: `tests/test_page_search_service.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the full-set page search service (no recognition yet)."""

from __future__ import annotations

import unittest

from drawing_graph.page_search_collector import PageContentCollector
from drawing_graph.page_search_service import PageContentSearchService
from drawing_graph.tool_models import PageSummary, ToolModelError


class _FakeFacade:
    def __init__(self, pages: list[PageSummary]) -> None:
        self._pages = pages

    def list_pages(self, drawing_set_id: str, limit: int = 100, offset: int = 0):
        return tuple(self._pages[offset : offset + limit])

    def get_page_source_facts(self, page_id: str, element_types=None, include_image_meta=True):
        return None

    def list_text_observations(self, page_id=None, element_id=None, recognition_run_id=None, statuses=None, write_back=False):
        raise ToolModelError("NOT_FOUND", "no observations")

    def list_interpretations(self, page_id=None, element_id=None, recognition_run_id=None, statuses=None, write_back=False):
        raise ToolModelError("NOT_FOUND", "no interpretations")


class _ObservingFacade(_FakeFacade):
    def __init__(self, pages: list[PageSummary], observed_page_id: str, text: str) -> None:
        super().__init__(pages)
        self._observed_page_id = observed_page_id
        self._text = text

    def list_text_observations(self, page_id=None, element_id=None, recognition_run_id=None, statuses=None, write_back=False):
        if page_id == self._observed_page_id:
            return (type("O", (), {"raw_text": self._text, "normalized_text": self._text, "target_element_id": "element:o"})(),)
        raise ToolModelError("NOT_FOUND", "no observations")


def _page(index: int) -> PageSummary:
    return PageSummary(
        drawing_set_id="set:1",
        page_id=f"page:{index}",
        file_stem=f"road_{index}",
    )


class PageContentSearchServiceTests(unittest.TestCase):
    def test_search_matches_observed_text(self) -> None:
        pages = [_page(1), _page(2)]
        facade = _ObservingFacade(pages, observed_page_id="page:2", text="排水管道")
        service = PageContentSearchService(facade, page_batch_size=1)
        result = service.search("set:1", "排水")
        self.assertEqual([match.page_id for match in result.matches], ["page:2"])
        self.assertEqual(result.coverage.total_pages, 2)
        self.assertEqual(result.coverage.scanned, 2)

    def test_search_no_match_returns_empty_matches(self) -> None:
        facade = _FakeFacade([_page(1)])
        service = PageContentSearchService(facade)
        result = service.search("set:1", "挡土墙")
        self.assertEqual(result.matches, ())
        self.assertEqual(result.coverage.total_pages, 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_page_search_service -v`
Expected: FAIL — `ModuleNotFoundError: drawing_graph.page_search_service`。

- [ ] **Step 3: Implement minimal code**

```python
"""Full-set page content search over a drawing set (read-only)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .page_search_collector import PageContent, PageContentCollector
from .page_search_matcher import TextMatcher
from .tool_models import PageSummary, ToolModelError


@dataclass(frozen=True)
class PageSearchHit:
    kind: str
    snippet: str
    element_id: str | None = None


@dataclass(frozen=True)
class PageSearchMatch:
    page_id: str
    page_title: str
    hits: tuple[PageSearchHit, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PageSearchCoverage:
    total_pages: int = 0
    scanned: int = 0
    from_cache: int = 0
    recognized_now: int = 0
    skipped: int = 0


@dataclass(frozen=True)
class PageSearchResult:
    matches: tuple[PageSearchMatch, ...] = field(default_factory=tuple)
    coverage: PageSearchCoverage = field(default_factory=PageSearchCoverage)


def _truncate(text: str, limit: int = 120) -> str:
    return text if len(text) <= limit else text[:limit] + "..."


class PageContentSearchService:
    """Enumerate pages, collect searchable text, and return deterministic matches."""

    def __init__(
        self,
        facade: Any,
        collector: PageContentCollector | None = None,
        matcher: TextMatcher | None = None,
        page_batch_size: int = 100,
    ) -> None:
        self._facade = facade
        self._collector = collector or PageContentCollector(facade)
        self._matcher = matcher or TextMatcher()
        self._page_batch_size = page_batch_size

    def search(
        self,
        drawing_set_id: str,
        query: str,
        *,
        allow_recognition: bool = False,
        recognize_page_limit: int = 10,
    ) -> PageSearchResult:
        """Search one drawing set; recognition hook is added in Task 11."""

        del allow_recognition, recognize_page_limit
        if not self._matcher.query_tokens(query):
            raise ToolModelError("INVALID_ARGUMENT", "query must contain at least one search token")
        pages = self._enumerate_pages(drawing_set_id)
        matches: list[PageSearchMatch] = []
        from_cache = 0
        for page in pages:
            content = self._collector.collect(page)
            if content.has_semantic_content:
                from_cache += 1
            hit_items = [
                item
                for item in content.items
                if self._matcher.matches(query, item.text)
            ]
            if hit_items:
                matches.append(
                    PageSearchMatch(
                        page_id=page.page_id,
                        page_title=page.file_stem,
                        hits=tuple(
                            PageSearchHit(
                                kind=item.kind,
                                snippet=_truncate(item.text),
                                element_id=item.element_id,
                            )
                            for item in hit_items
                        ),
                    )
                )
        return PageSearchResult(
            matches=tuple(matches),
            coverage=PageSearchCoverage(
                total_pages=len(pages),
                scanned=len(pages),
                from_cache=from_cache,
            ),
        )

    def _enumerate_pages(self, drawing_set_id: str) -> list[PageSummary]:
        pages: list[PageSummary] = []
        offset = 0
        while True:
            batch = self._facade.list_pages(
                drawing_set_id,
                limit=self._page_batch_size,
                offset=offset,
            )
            pages.extend(batch)
            if len(batch) < self._page_batch_size:
                break
            offset += len(batch)
        return pages
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_page_search_service -v`
Expected: PASS（2 个用例）。

- [ ] **Step 5: Commit**

```bash
git add src/drawing_graph/page_search_service.py tests/test_page_search_service.py
git commit -m "feat(search): add full-set page search service with coverage"
```

---

## Task 6: CLI search-pages

**Files:**
- Modify: `scripts/drawing_graph_tool.py`
- Test: `tests/test_page_search_service.py`（追加 CLI 用例）

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_page_search_service.py` 末尾：

```python
class SearchPagesCliTests(unittest.TestCase):
    def test_cli_search_pages_prints_ok(self) -> None:
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
                ["search-pages", "--drawing-set-id", "set:1", "--query", "排水"],
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
        self.assertEqual(payload["data"]["matches"][0]["page_id"], "page:1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_page_search_service.SearchPagesCliTests -v`
Expected: FAIL — `error: argument command: invalid choice: 'search-pages'`。

- [ ] **Step 3: Implement minimal changes**

`scripts/drawing_graph_tool.py` 的 `_build_parser()` 中、`section_matches` 定义之后追加：

```python
    search_pages = subparsers.add_parser(
        "search-pages",
        help="Search page content across one drawing set (read-only).",
    )
    search_pages.add_argument("--drawing-set-id", required=True)
    search_pages.add_argument("--query", required=True)
    search_pages.add_argument("--allow-recognition", action="store_true")
    search_pages.add_argument("--recognize-page-limit", type=int, default=10)
```

`_run_selected_command` 中追加：

```python
    if args.command == "search-pages":
        from drawing_graph.page_search_service import PageContentSearchService

        service = PageContentSearchService(facade)
        return service.search(
            args.drawing_set_id,
            args.query,
            allow_recognition=args.allow_recognition,
            recognize_page_limit=args.recognize_page_limit,
        )
```

`scripts/drawing_graph_tool.py` 顶层需把项目 `src` 加入 `sys.path`（若尚未加入）：

```python
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_page_search_service -v`
Expected: PASS（原 2 个用例 + 新增 1 个 CLI 用例）。

- [ ] **Step 5: Commit**

```bash
git add scripts/drawing_graph_tool.py tests/test_page_search_service.py
git commit -m "feat(cli): add search-pages command"
```

---

## Task 7: 问题路由规则扩展与漏网句式修正

**Files:**
- Modify: `src/drawing_graph/assistant_question_rules.py`
- Test: `tests/test_page_search_routing.py`

- [ ] **Step 1: Write the failing test**

```python
"""Routing tests for civil-engineer phrasing."""

from __future__ import annotations

import unittest

from drawing_graph.assistant_question_rules import RuleQuestionRouter


class CivilEngineerRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = RuleQuestionRouter()

    def assert_routes(self, question: str, expected: str) -> None:
        self.assertEqual(self.router.route(question, None).question_type, expected)

    def test_full_set_search_phrasings(self) -> None:
        self.assert_routes("挡土墙的横断面图在哪一页", "page_content_search")
        self.assert_routes("哪些图是关于排水的", "page_content_search")
        self.assert_routes("哪块砖的混凝土强度等级是C35", "page_content_search")

    def test_section_location_phrasing(self) -> None:
        self.assert_routes("A-A剖面在哪个图块上", "section_matches")

    def test_short_component_phrasing(self) -> None:
        self.assert_routes("这块是什么", "block_semantic_identification")

    def test_existing_intents_are_not_regressed(self) -> None:
        self.assert_routes("这张图主要讲什么", "page_summary")
        self.assert_routes("这个图块有哪些候选关系", "candidate_relations")
        self.assert_routes("这个图块是什么构件", "block_semantic_identification")
        self.assert_routes("这个元素是什么", "element_text_or_meaning")
        self.assert_routes("这个断面对应哪个标题", "section_matches")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_page_search_routing -v`
Expected: FAIL — 新增句式路由为 `unknown_or_unsupported`。

- [ ] **Step 3: Implement minimal changes**

`src/drawing_graph/assistant_question_rules.py` 的 `_DEFAULT_RULES` 中新增：

```python
    _Rule(
        rule_id="rule:page_content_search",
        question_type=QuestionType.PAGE_CONTENT_SEARCH.value,
        patterns=(
            ("哪一页",),
            ("哪些图",),
            ("哪几张图",),
            ("哪几页",),
            ("哪块",),
            ("关于", "图"),
            ("涉及",),
            ("在", "哪一页"),
            ("查找", "图"),
            ("搜索", "图"),
        ),
        excluded=("图块", "断面", "候选", "关系", "标题"),
    ),
```

`section_matches` 规则的 patterns 追加：

```python
            ("剖面", "图块"),
            ("在哪个图块",),
```

新增 `block_semantic_identification` 兜底句式（放在该规则 patterns 中追加）：

```python
            ("是什么",),
```

并把 `block_semantic_identification` 规则的 `excluded` 设为：

```python
        excluded=("元素", "图", "页", "候选", "关系", "标题", "断面", "表", "册"),
```

（`_Rule` 已支持 `excluded` 参数；`element_text_or_meaning` 规则位于 `block_semantic_identification` 之后，`"是什么"` 模式不会抢走含“元素”的句子。）

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_page_search_routing -v`
Expected: PASS（4 组用例）。

- [ ] **Step 5: Commit**

```bash
git add src/drawing_graph/assistant_question_rules.py tests/test_page_search_routing.py
git commit -m "feat(question): route civil-engineer search phrasings"
```

---

## Task 8: scope 提取 drawing_set

**Files:**
- Modify: `src/drawing_graph/assistant_scope_resolution.py`
- Test: `tests/test_page_search_scope.py`

- [ ] **Step 1: Write the failing test**

```python
"""Scope resolution tests for drawing_set extraction."""

from __future__ import annotations

import unittest

from drawing_graph.assistant_scope_resolution import ScopeResolver


class DrawingSetScopeTests(unittest.TestCase):
    def test_extracts_drawing_set_prefix(self) -> None:
        result = ScopeResolver().resolve(
            "在 set:road-project:lslq_yhd_2_2 里哪些图关于排水"
        )
        self.assertEqual(result.scope.drawing_set_id, "set:road-project:lslq_yhd_2_2")

    def test_missing_drawing_set_leaves_scope_none(self) -> None:
        result = ScopeResolver().resolve("哪些图关于排水")
        self.assertIsNone(result.scope)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_page_search_scope -v`
Expected: FAIL — `drawing_set_id` 为 `None`。

- [ ] **Step 3: Implement minimal changes**

`src/drawing_graph/assistant_scope_resolution.py`：

```python
_SCOPE_FIELD_BY_PREFIX = {
    "cross_section": "cross_section_id",
    "table_caption": "table_caption_id",
    "element": "element_id",
    "block": "block_id",
    "page": "page_id",
    "table": "table_id",
    "claim": "claim_id",
    "drawing_set": "drawing_set_id",
}
```

```python
_ID_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?P<prefix>cross_section|table_caption|element|block|page|table|claim|drawing_set):"
    r"(?P<id>[A-Za-z0-9_][A-Za-z0-9_.\-]*)"
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_page_search_scope -v`
Expected: PASS（2 个用例）。

- [ ] **Step 5: Commit**

```bash
git add src/drawing_graph/assistant_scope_resolution.py tests/test_page_search_scope.py
git commit -m "feat(question): extract drawing_set id from question text"
```

---

## Task 9: PageContentSearchAnswerBuilder

**Files:**
- Create: `src/drawing_graph/page_search_answer_builder.py`
- Test: `tests/test_page_search_answer_builder.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for converting page search results into AnswerPackage."""

from __future__ import annotations

import unittest

from drawing_graph.assistant_models import (
    ANSWER_CONTRACT_VERSION,
    AssistantScope,
    QuestionType,
)
from drawing_graph.page_search_answer_builder import PageContentSearchAnswerBuilder
from drawing_graph.page_search_service import (
    PageSearchCoverage,
    PageSearchHit,
    PageSearchMatch,
    PageSearchResult,
)


class PageContentSearchAnswerBuilderTests(unittest.TestCase):
    def test_build_answered_with_matches(self) -> None:
        result = PageSearchResult(
            matches=(
                PageSearchMatch(
                    page_id="page:2",
                    page_title="road_68",
                    hits=(PageSearchHit(kind="observation", snippet="排水管道"),),
                ),
            ),
            coverage=PageSearchCoverage(total_pages=2, scanned=2, from_cache=1),
        )
        scope = AssistantScope(drawing_set_id="set:1")
        package = PageContentSearchAnswerBuilder().build(
            request_id="req:1",
            scope=scope,
            result=result,
        )
        self.assertEqual(package.status, "answered")
        self.assertEqual(package.question_type, QuestionType.PAGE_CONTENT_SEARCH.value)
        self.assertEqual(len(package.claims), 1)
        self.assertEqual(package.claims[0].fact_kinds[0], "source_fact")
        self.assertEqual(package.machine_answer.answer_contract_version, ANSWER_CONTRACT_VERSION)

    def test_build_partial_without_matches(self) -> None:
        result = PageSearchResult(coverage=PageSearchCoverage(total_pages=1, scanned=1))
        package = PageContentSearchAnswerBuilder().build(
            request_id="req:2",
            scope=AssistantScope(drawing_set_id="set:1"),
            result=result,
        )
        self.assertEqual(package.status, "partial")
        self.assertEqual(package.claims, ())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_page_search_answer_builder -v`
Expected: FAIL — `ModuleNotFoundError: drawing_graph.page_search_answer_builder`。

- [ ] **Step 3: Implement minimal code**

```python
"""Build AnswerPackage from page search results (narrow read-only path)."""

from __future__ import annotations

from typing import Any

from .assistant_answer_templates import ChineseAnswerTemplateRenderer
from .assistant_models import (
    ANSWER_CONTRACT_VERSION,
    AnswerPackage,
    AnswerStatus,
    AssistantScope,
    Citation,
    Claim,
    ClaimStatus,
    MachineAnswer,
    QuestionType,
    TextRenderMode,
)
from .page_search_service import PageSearchResult


class PageContentSearchAnswerBuilder:
    """Convert PageSearchResult into a stable AnswerPackage."""

    def __init__(self, template_renderer: Any | None = None) -> None:
        self.template_renderer = template_renderer or ChineseAnswerTemplateRenderer()

    def build(
        self,
        request_id: str,
        scope: AssistantScope | None,
        result: PageSearchResult,
    ) -> AnswerPackage:
        claims: list[Claim] = []
        citations: list[Citation] = []
        for match in result.matches:
            claim_id = f"claim:page-search:{match.page_id}"
            citation_id = f"citation:page-search:{match.page_id}"
            claims.append(
                Claim(
                    claim_id=claim_id,
                    statement=f"页面 {match.page_title} 命中检索",
                    status=ClaimStatus.SUPPORTED.value,
                    fact_kinds=("source_fact",),
                    scope=AssistantScope(page_id=match.page_id),
                    citation_ids=(citation_id,),
                )
            )
            citations.append(
                Citation(
                    citation_id=citation_id,
                    evidence_id=f"evidence:page-search:{match.page_id}",
                    claim_ids=(claim_id,),
                    page_id=match.page_id,
                )
            )
        status = AnswerStatus.ANSWERED if claims else AnswerStatus.PARTIAL
        machine = MachineAnswer(
            answer_contract_version=ANSWER_CONTRACT_VERSION,
            request_id=request_id,
            question_type=QuestionType.PAGE_CONTENT_SEARCH.value,
            scope=scope,
            status=status,
            claims=tuple(claims),
            citations=tuple(citations),
        )
        text = self.template_renderer.render(machine)
        return AnswerPackage(
            request_id=request_id,
            question_type=QuestionType.PAGE_CONTENT_SEARCH.value,
            scope=scope,
            status=status.value,
            machine_answer=machine,
            text_answer=text,
            claims=tuple(claims),
            citations=tuple(citations),
            render_mode=TextRenderMode.TEMPLATE,
        )
```

若 `MachineAnswer` 校验要求 `status` 为 `AnswerStatus` 枚举实例（`_coerce_enum` 已兼容 str），本代码保持枚举传入；`Claim.claim_type` 可为 `None`（模型允许）。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_page_search_answer_builder -v`
Expected: PASS（2 个用例）。

- [ ] **Step 5: Commit**

```bash
git add src/drawing_graph/page_search_answer_builder.py tests/test_page_search_answer_builder.py
git commit -m "feat(question): build AnswerPackage from page search results"
```

---

## Task 10: DrawingAssistantService 接入 page_content_search

**Files:**
- Modify: `src/drawing_graph/drawing_assistant_service.py`
- Test: `tests/test_page_search_answer_builder.py`（追加集成用例）

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_page_search_answer_builder.py` 末尾：

```python
class DrawingAssistantSearchPathTests(unittest.TestCase):
    def test_service_answers_search_question(self) -> None:
        from drawing_graph.assistant_models import (
            AssistantRequest,
            AssistantScope,
            QuestionType,
        )
        from drawing_graph.drawing_assistant_factory import (
            create_drawing_assistant_service,
        )

        # 通过工厂创建真实服务（在单测环境使用 fake provider，不连 Neo4j）。
        service = create_drawing_assistant_service(
            facade=_SearchFakeFacade(),
        )
        request = AssistantRequest(
            request_id="req:search-e2e",
            question="哪些图关于排水",
            scope_hint=AssistantScope(drawing_set_id="set:1"),
        )
        package = service.answer(request)
        self.assertEqual(package.question_type, QuestionType.PAGE_CONTENT_SEARCH.value)
        self.assertIn(package.status, {"answered", "partial"})


class _SearchFakeFacade:
    def list_pages(self, drawing_set_id: str, limit: int = 100, offset: int = 0):
        return tuple(
            PageSummary(drawing_set_id=drawing_set_id, page_id="page:1", file_stem="road_68")
        )

    def get_page_source_facts(self, page_id: str, element_types=None, include_image_meta=True):
        return None

    def list_text_observations(self, page_id=None, element_id=None, recognition_run_id=None, statuses=None, write_back=False):
        return (
            type("O", (), {"raw_text": "排水管道", "normalized_text": "排水管道", "target_element_id": "element:o"})(),
        )

    def list_interpretations(self, page_id=None, element_id=None, recognition_run_id=None, statuses=None, write_back=False):
        raise ToolModelError("NOT_FOUND", "no interpretations")
```

（若 `create_drawing_assistant_service` 签名不接受 `facade` 关键字，按该工厂实际签名注入；见 Step 3 说明。）

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_page_search_answer_builder.DrawingAssistantSearchPathTests -v`
Expected: FAIL — `page_content_search` 走通用检索路径且证据模板缺检索实现，或工厂参数不符。

- [ ] **Step 3: Implement minimal changes**

先确认 `src/drawing_graph/drawing_assistant_factory.py` 中 `create_drawing_assistant_service` 的参数；以既有 `create_neo4j_tool_facade` 产物注入 facade。随后在 `src/drawing_graph/drawing_assistant_service.py`：

1. 顶部 import 增加：

```python
from .assistant_models import QuestionType
from .page_search_answer_builder import PageContentSearchAnswerBuilder
from .page_search_service import PageContentSearchService
```

2. `DrawingAssistantService.__init__` 参数增加：

```python
        page_search_service: PageContentSearchService | None = None,
        page_search_answer_builder: PageContentSearchAnswerBuilder | None = None,
        page_search_recognize_limit: int = 10,
```

并在 `__init__` 内赋值：

```python
        self.page_search_service = page_search_service or PageContentSearchService(self.facade)
        self.page_search_answer_builder = page_search_answer_builder or PageContentSearchAnswerBuilder()
        self.page_search_recognize_limit = page_search_recognize_limit
```

3. `_answer_single_intent` 开头插入专用分支：

```python
        if question_result.question_type == QuestionType.PAGE_CONTENT_SEARCH.value:
            return self._answer_page_content_search(request, question_result)
```

4. 新增方法：

```python
    def _answer_page_content_search(
        self,
        request: AssistantRequest,
        question_result: QuestionUnderstandingResult,
    ) -> AnswerPackage:
        scope = question_result.scope
        if scope is None or scope.drawing_set_id is None:
            raise AssistantExecutionError(
                "missing_scope",
                "drawing_set_id is required for page content search",
            )
        result = self.page_search_service.search(
            scope.drawing_set_id,
            request.question,
            allow_recognition=request.allow_recognition,
            recognize_page_limit=self.page_search_recognize_limit,
        )
        return self.page_search_answer_builder.build(
            request.request_id,
            scope,
            result,
        )
```

5. 若 `DrawingAssistantService` 通过工厂创建，需把新依赖透传；在工厂里用默认值即可（service 构造时 `self.facade` 已可用）。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_page_search_answer_builder -v`
Expected: PASS（原 2 个用例 + 集成用例；若工厂注入路径与本地不一致，调整测试按实际工厂签名构造）。

- [ ] **Step 5: Commit**

```bash
git add src/drawing_graph/drawing_assistant_service.py src/drawing_graph/drawing_assistant_factory.py tests/test_page_search_answer_builder.py
git commit -m "feat(question): wire page_content_search into product assistant"
```

---

## Task 11: 按需识别补齐（dry-run）与 coverage

**Files:**
- Modify: `src/drawing_graph/page_search_service.py`
- Test: `tests/test_page_search_service.py`（追加用例）

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_page_search_service.py` 末尾：

```python
class RecognitionBackfillTests(unittest.TestCase):
    def test_recognizes_unrecognized_page_then_matches(self) -> None:
        class _RecognitionFacade(_FakeFacade):
            def __init__(self, pages):
                super().__init__(pages)
                self.recognized: list[str] = []

            def get_page_source_facts(self, page_id, element_types=None, include_image_meta=True):
                return type("F", (), {"elements": ()})()

            def list_text_observations(self, page_id=None, element_id=None, recognition_run_id=None, statuses=None, write_back=False):
                if page_id == "page:2" and "page:2" in self.recognized:
                    return (type("O", (), {"raw_text": "排水管道", "normalized_text": "排水管道", "target_element_id": "element:o"})(),)
                raise ToolModelError("NOT_FOUND", "no observations")

            def recognize_page_semantics(self, page_id, target_types, model_profile="default", prompt_version="default", write_back=False):
                self.recognized.append(page_id)
                return object()

        facade = _RecognitionFacade([_page(1), _page(2)])
        service = PageContentSearchService(facade, page_batch_size=1)
        result = service.search("set:1", "排水", allow_recognition=True, recognize_page_limit=1)
        self.assertEqual([m.page_id for m in result.matches], ["page:2"])
        self.assertEqual(facade.recognized, ["page:2"])
        self.assertEqual(result.coverage.recognized_now, 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_page_search_service.RecognitionBackfillTests -v`
Expected: FAIL — `recognized` 为空、`coverage.recognized_now == 0`。

- [ ] **Step 3: Implement minimal changes**

`src/drawing_graph/page_search_service.py` 的 `search()` 改为：

```python
    def search(
        self,
        drawing_set_id: str,
        query: str,
        *,
        allow_recognition: bool = False,
        recognize_page_limit: int = 10,
    ) -> PageSearchResult:
        if not self._matcher.query_tokens(query):
            raise ToolModelError("INVALID_ARGUMENT", "query must contain at least one search token")
        pages = self._enumerate_pages(drawing_set_id)
        matches: list[PageSearchMatch] = []
        from_cache = 0
        recognized_now = 0
        skipped = 0
        recognition_budget = max(0, recognize_page_limit)
        for page in pages:
            content = self._collector.collect(page)
            if content.has_semantic_content:
                from_cache += 1
            elif allow_recognition and recognition_budget > 0:
                recognized_now += 1
                recognition_budget -= 1
                try:
                    self._facade.recognize_page_semantics(
                        page.page_id,
                        target_types=("block", "text"),
                        write_back=False,
                    )
                    content = self._collector.collect(page)
                except Exception:
                    recognized_now -= 1
                    skipped += 1
            elif not content.has_semantic_content:
                skipped += 1
            hit_items = [
                item
                for item in content.items
                if self._matcher.matches(query, item.text)
            ]
            if hit_items:
                matches.append(
                    PageSearchMatch(
                        page_id=page.page_id,
                        page_title=page.file_stem,
                        hits=tuple(
                            PageSearchHit(
                                kind=item.kind,
                                snippet=_truncate(item.text),
                                element_id=item.element_id,
                            )
                            for item in hit_items
                        ),
                    )
                )
        return PageSearchResult(
            matches=tuple(matches),
            coverage=PageSearchCoverage(
                total_pages=len(pages),
                scanned=len(pages),
                from_cache=from_cache,
                recognized_now=recognized_now,
                skipped=skipped,
            ),
        )
```

（`recognize_page_semantics` 的 `target_types` 值按 facade 实际支持的类型调整；dry-run 固定 `write_back=False`。）

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_page_search_service -v`
Expected: PASS（原用例 + 新增 1 个）。

- [ ] **Step 5: Commit**

```bash
git add src/drawing_graph/page_search_service.py tests/test_page_search_service.py
git commit -m "feat(search): backfill unrecognized pages with dry-run recognition"
```

---

## Task 12: CLI 显式写缓存授权

**Files:**
- Modify: `src/drawing_graph/page_search_service.py`
- Modify: `scripts/drawing_graph_tool.py`
- Test: `tests/test_page_search_service.py`（追加用例）

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_page_search_service.py` 末尾：

```python
class CacheWriteAuthorizationTests(unittest.TestCase):
    def test_cli_write_back_flag_forwards_to_recognition(self) -> None:
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

        calls: list[dict[str, object]] = []

        class _RecordingFacade(_FakeFacade):
            def get_page_source_facts(self, page_id, element_types=None, include_image_meta=True):
                return type("F", (), {"elements": ()})()

            def list_text_observations(self, page_id=None, element_id=None, recognition_run_id=None, statuses=None, write_back=False):
                raise ToolModelError("NOT_FOUND", "no observations")

            def recognize_page_semantics(self, page_id, target_types, model_profile="default", prompt_version="default", write_back=False):
                calls.append({"page_id": page_id, "write_back": write_back})
                return object()

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
                    "--allow-recognition",
                    "--write-back",
                ],
                config_loader=lambda: _Config(),
                driver_factory=lambda uri, auth: _Driver(),
                facade_factory=lambda driver: _RecordingFacade([_page(1)]),
            )
        finally:
            sys.stdout = original
        self.assertEqual(code, 0)
        self.assertEqual(calls[0]["write_back"], True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_page_search_service.CacheWriteAuthorizationTests -v`
Expected: FAIL — CLI 尚无 `--write-back` 参数。

- [ ] **Step 3: Implement minimal changes**

`scripts/drawing_graph_tool.py` 的 `search-pages` 增加：

```python
    search_pages.add_argument("--write-back", action="store_true", help="Explicitly authorize persisting recognition cache.")
```

`_run_selected_command` 的 `search-pages` 分支改为：

```python
    if args.command == "search-pages":
        from drawing_graph.page_search_service import PageContentSearchService

        service = PageContentSearchService(facade)
        return service.search(
            args.drawing_set_id,
            args.query,
            allow_recognition=args.allow_recognition,
            recognize_page_limit=args.recognize_page_limit,
            write_back=args.write_back,
        )
```

`src/drawing_graph/page_search_service.py` 的 `search()` 增加 `write_back: bool = False` 关键字，并在识别调用处替换：

```python
                    self._facade.recognize_page_semantics(
                        page.page_id,
                        target_types=("block", "text"),
                        write_back=write_back,
                    )
```

（产品路径 `DrawingAssistantService` 调用时保持默认 `write_back=False`，不暴露该参数。）

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_page_search_service -v`
Expected: PASS（含新增 1 个）。

- [ ] **Step 5: Commit**

```bash
git add src/drawing_graph/page_search_service.py scripts/drawing_graph_tool.py tests/test_page_search_service.py
git commit -m "feat(cli): explicit cache write-back authorization for search-pages"
```

---

## Task 13: LLM 问题理解兜底客户端

**Files:**
- Create: `src/drawing_graph/question_understanding_client.py`
- Modify: `src/drawing_graph/assistant_question_understanding.py`
- Test: `tests/test_question_understanding_client.py`

- [ ] **Step 1: Write the failing test**

```python
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

    def __call__(self, url: str, headers: dict[str, str], body: dict[str, object], timeout: float) -> tuple[int, str]:
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_question_understanding_client -v`
Expected: FAIL — `ModuleNotFoundError: drawing_graph.question_understanding_client`。

- [ ] **Step 3: Implement minimal code**

```python
"""Constrained HTTP question-understanding client (rule fallback enhancement)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from .assistant_models import AssistantScope
from .assistant_question_llm import (
    ModelOutputValidation,
    QuestionUnderstandingCandidate,
    QuestionUnderstandingModelClient,
)


@dataclass(frozen=True)
class QuestionUnderstandingClientConfig:
    model: str = "qwen3-vl-plus"
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    timeout_seconds: float = 60.0
    api_key: str = ""


_PROMPT = (
    "你是图纸问答意图分类器。只从以下类型中选择一个 question_type："
    "page_summary, block_relations, block_semantic_identification, "
    "element_text_or_meaning, candidate_relations, section_matches, "
    "table_caption_status, drawing_diagnostic, source_trace, comparison, "
    "page_content_search, unknown_or_unsupported。"
    "只输出 JSON：{\"question_type\": ..., \"confidence\": 0..1, "
    "\"ambiguities\": [...], \"unsupported_parts\": [...]}。"
    "不得输出任何事实、查询语句或写回授权。"
)


class HttpQuestionUnderstandingClient(QuestionUnderstandingModelClient):
    """Call an OpenAI-compatible chat endpoint and validate the candidate."""

    def __init__(
        self,
        config: QuestionUnderstandingClientConfig,
        http_post: Callable[..., tuple[int, str]] | None = None,
    ) -> None:
        self._config = config
        self._http_post = http_post or self._default_post
        self._validator = ModelOutputValidation()

    def understand(
        self,
        question: str,
        scope: AssistantScope | None = None,
    ) -> QuestionUnderstandingCandidate:
        messages = [
            {"role": "system", "content": _PROMPT},
            {"role": "user", "content": question},
        ]
        status, body = self._http_post(
            f"{self._config.base_url.rstrip('/')}/chat/completions",
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._config.api_key}",
            },
            {
                "model": self._config.model,
                "messages": messages,
                "temperature": 0.0,
                "response_format": {"type": "json_object"},
            },
            self._config.timeout_seconds,
        )
        if status != 200:
            raise RuntimeError(f"question understanding HTTP {status}")
        content = json.loads(body)["choices"][0]["message"]["content"]
        raw = json.loads(content)
        candidate = QuestionUnderstandingCandidate(
            question_type=str(raw["question_type"]),
            confidence=float(raw.get("confidence", 0.0)),
            ambiguities=tuple(raw.get("ambiguities") or ()),
            unsupported_parts=tuple(raw.get("unsupported_parts") or ()),
        )
        self._validator.validate(candidate)
        return candidate

    @staticmethod
    def _default_post(
        url: str,
        headers: dict[str, str],
        body: dict[str, object],
        timeout: float,
    ) -> tuple[int, str]:
        import requests

        response = requests.post(url, headers=headers, json=body, timeout=timeout)
        return response.status_code, response.text
```

`src/drawing_graph/assistant_question_understanding.py`：在 `understand()` 的 `UNKNOWN_OR_UNSUPPORTED` 分支中、`return` 之前插入 LLM 兜底：

```python
        if route_result.question_type == QuestionType.UNKNOWN_OR_UNSUPPORTED.value:
            if self.model_client is not None:
                try:
                    candidate = self.model_client.understand(normalized, scope_result.scope)
                    if candidate.question_type != QuestionType.UNKNOWN_OR_UNSUPPORTED.value:
                        return QuestionUnderstandingResult(
                            request_id=request.request_id,
                            question_type=candidate.question_type,
                            scope=scope,
                            confidence=candidate.confidence,
                            ambiguities=candidate.ambiguities,
                            unsupported_parts=candidate.unsupported_parts,
                        )
                except Exception:
                    pass
            return QuestionUnderstandingResult(
                request_id=request.request_id,
                question_type=QuestionType.UNKNOWN_OR_UNSUPPORTED.value,
                scope=scope,
                confidence=route_result.confidence,
                ambiguities=route_result.ambiguities,
                unsupported_parts=route_result.unsupported_parts
                or ("question_type",),
            )
```

（`QuestionUnderstandingResult` 的必需字段以 `assistant_models.py` 定义为准；兜底失败时保持原 `unknown_or_unsupported` 语义。）

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_question_understanding_client -v`
Expected: PASS（1 个用例）；随后跑 `python -m unittest tests.test_assistant_question_rules tests.test_assistant_question_understanding tests.test_assistant_clarification -v` 确认无回归。

- [ ] **Step 5: Commit**

```bash
git add src/drawing_graph/question_understanding_client.py src/drawing_graph/assistant_question_understanding.py tests/test_question_understanding_client.py
git commit -m "feat(question): constrained LLM understanding fallback"
```

---

## Task 14: 全量回归、文档与 live 验收

**Files:**
- Modify: `README.md`
- Modify: `docs/acceptance/USER_RUNBOOK.md`
- Test: 全量 unittest

- [ ] **Step 1: Run full regression**

Run: `python -m unittest discover tests -v`
Expected: 全量通过（`tests/integration/` 因缺少 `NEO4J_TEST_URI`/`NEO4J_TEST_USER`/`NEO4J_TEST_PASSWORD` 按既有设计跳过）。

- [ ] **Step 2: Update README**

在 README「5. CLI 查询」之后追加：

```markdown
搜索图纸册页内容（只读）：

```powershell
python scripts\drawing_graph_tool.py search-pages --drawing-set-id set:road-project:lslq_yhd_2_2 --query 排水
python scripts\drawing_graph_tool.py search-pages --drawing-set-id set:road-project:lslq_yhd_2_2 --query 排水 --allow-recognition
```

`--allow-recognition` 对无缓存观察的页面按需识别（默认 dry-run）；显式持久化识别缓存需追加 `--write-back`。
```

- [ ] **Step 3: Update USER_RUNBOOK**

在「5. CLI 查询」追加：

```markdown
搜索页内容：

```powershell
python scripts\drawing_graph_tool.py search-pages --drawing-set-id set:road-project:lslq_yhd_2_2 --query 排水
```

返回 `matches`（命中页 + 命中片段）与 `coverage`（扫描/缓存/本次识别/跳过）；无命中返回 `NOT_FOUND` 是正常状态。
```

- [ ] **Step 4: Live acceptance**

在 Neo4j 运行、`NEO4J_URI/USER/PASSWORD` 已加载的终端执行：

```powershell
python scripts\drawing_graph_tool.py search-pages --drawing-set-id set:road-project:lslq_yhd_2_2 --query 排水 --allow-recognition --recognize-page-limit 5
```

期望：输出 `status=ok`、`matches` 包含命中页与 hits、`coverage.total_pages=230`；识别页计入 `recognized_now`。将该结果按分层格式（CLI / live Neo4j）记入验收记录，不冒充宿主原生 MCP。

- [ ] **Step 5: Commit**

```bash
git add README.md docs/acceptance/USER_RUNBOOK.md
git commit -m "docs(search): document search-pages CLI and acceptance"
```

---

## 自检记录

- 覆盖：设计文档 §2.1（检索/识别/问题理解/入口）均有对应任务（Task 1–14）；§2.2 延后项（语义/向量）无任务，符合范围。
- 占位符：本计划不含 TBD/TODO；Task 10/13 两处“按实际工厂/模型定义调整”为对既有签名的显式核对动作，不是占位。
- 类型一致性：`list_pages(..., offset)`、`PageContentSearchService.search(..., allow_recognition, recognize_page_limit, write_back)`、`PageContentSearchAnswerBuilder.build(request_id, scope, result)`、`PageSearchResult/PageSearchMatch/PageSearchHit/PageSearchCoverage` 在各任务间签名一致。
