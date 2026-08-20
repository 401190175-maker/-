# 语义理解升级批次一实施计划（Phase 1 LLM 完整接通 + Phase 2A 同义词匹配）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 LLM 问题理解的生产装配与全类型兜底（Phase 1），并给检索增加域内同义词扩展（Phase 2A）。

**Architecture:** `question_understanding_client_from_env()` 按环境装配 `HttpQuestionUnderstandingClient`；`QuestionUnderstandingService` 抽出 `_complete_route`，LLM 兜底命中任意合法类型后重建证据需求；检索默认匹配器换成 `SynonymExpansionMatcher`（词面行为不变）。

**Tech Stack:** Python 3.14、unittest、DashScope 兼容 HTTP、现有 `drawing_graph` 包。

**设计文档:** `docs/superpowers/specs/2026-08-20-semantic-understanding-upgrade-design.md`

---

## 文件结构

修改：
- `src/drawing_graph/assistant_models.py`（ReasonCode 新成员）
- `src/drawing_graph/question_understanding_client.py`（env helper）
- `src/drawing_graph/assistant_question_understanding.py`（`_complete_route` 重构 + LLM 全类型兜底）
- `src/drawing_graph/drawing_assistant_factory.py`（注入 `question_understanding_client`）
- `scripts/drawing_assistant.py`、`src/drawing_graph/assistant_mcp_runtime.py` 或 `scripts/serve_drawing_assistant_mcp.py`（装配 env helper）
- `src/drawing_graph/page_search_matcher.py`（`SynonymExpansionMatcher` + `DOMAIN_SYNONYMS`）
- `src/drawing_graph/page_search_service.py`（默认匹配器切换）
- `tests/test_question_understanding_client.py`、`tests/test_assistant_question_understanding.py`、`tests/test_page_search_matcher.py`、`tests/test_page_search_service.py`
- `README.md`、`docs/acceptance/USER_RUNBOOK.md`

测试约定：`$env:PYTHONPATH="src"; python -m unittest tests.test_xxx -v`；全量 `python -m unittest discover tests -v`。

---

## Task 1: ReasonCode 新成员 + env 装配 helper

**Files:**
- Modify: `src/drawing_graph/assistant_models.py`
- Modify: `src/drawing_graph/question_understanding_client.py`
- Test: `tests/test_question_understanding_client.py`

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_question_understanding_client.py`：

```python
class EnvironmentWiringTests(unittest.TestCase):
    def test_from_env_returns_client_when_key_present(self) -> None:
        import os
        from unittest import mock

        from drawing_graph.question_understanding_client import question_understanding_client_from_env

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

        from drawing_graph.question_understanding_client import question_understanding_client_from_env

        with mock.patch.dict(os.environ, {}, clear=True):
            client = question_understanding_client_from_env()
        self.assertIsNone(client)

    def test_reason_code_exists(self) -> None:
        from drawing_graph.assistant_models import ReasonCode

        self.assertEqual(
            ReasonCode.QUESTION_UNDERSTANDING_FALLBACK_FAILED.value,
            "question_understanding_fallback_failed",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_question_understanding_client.EnvironmentWiringTests -v`
Expected: FAIL — `question_understanding_client_from_env` 不存在、ReasonCode 无新成员。

- [ ] **Step 3: Implement**

`src/drawing_graph/assistant_models.py` 的 `ReasonCode` 枚举中追加：

```python
    QUESTION_UNDERSTANDING_FALLBACK_FAILED = "question_understanding_fallback_failed"
```

`src/drawing_graph/question_understanding_client.py` 末尾追加：

```python
def question_understanding_client_from_env() -> HttpQuestionUnderstandingClient | None:
    """Build the HTTP client from environment when an API key is present."""

    import os

    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        return None
    return HttpQuestionUnderstandingClient(
        QuestionUnderstandingClientConfig(
            model=os.environ.get("DRAWING_GRAPH_QWEN_MODEL", "qwen3-vl-plus").strip(),
            base_url=os.environ.get(
                "DRAWING_GRAPH_QWEN_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ).strip(),
            timeout_seconds=float(
                os.environ.get("DRAWING_GRAPH_QWEN_TIMEOUT_SECONDS", "60.0")
            ),
            api_key=api_key,
        )
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_question_understanding_client -v` → PASS。

- [ ] **Step 5: Commit**

```bash
git add src/drawing_graph/assistant_models.py src/drawing_graph/question_understanding_client.py tests/test_question_understanding_client.py
git commit -m "feat(question): env wiring for LLM understanding client"
```

---

## Task 2: _complete_route 重构 + LLM 全类型兜底

**Files:**
- Modify: `src/drawing_graph/assistant_question_understanding.py`
- Test: `tests/test_assistant_question_understanding.py`

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_assistant_question_understanding.py`：

```python
class LlmFallbackTests(unittest.TestCase):
    def test_llm_fallback_adopts_any_valid_type_with_evidence(self) -> None:
        from drawing_graph.assistant_models import AssistantRequest, QuestionType
        from drawing_graph.assistant_question_llm import FakeQuestionUnderstandingModelClient

        client = FakeQuestionUnderstandingModelClient(
            QuestionUnderstandingCandidate(
                question_type="candidate_relations",
                confidence=0.8,
            )
        )
        service = QuestionUnderstandingService(model_client=client)
        result = service.understand(
            AssistantRequest(request_id="r1", question="这页的关系情况")
        )
        self.assertEqual(result.question_type, QuestionType.CANDIDATE_RELATIONS.value)
        self.assertTrue(result.required_evidence)

    def test_llm_fallback_failure_keeps_unknown_with_reason_code(self) -> None:
        from drawing_graph.assistant_models import AssistantRequest, ReasonCode
        from drawing_graph.assistant_question_llm import QuestionUnderstandingModelClient

        class _BoomClient(QuestionUnderstandingModelClient):
            def understand(self, question, scope=None):
                raise RuntimeError("boom")

        service = QuestionUnderstandingService(model_client=_BoomClient())
        result = service.understand(
            AssistantRequest(request_id="r1", question="今天天气怎么样")
        )
        self.assertEqual(result.question_type, "unknown_or_unsupported")
        self.assertIn(ReasonCode.QUESTION_UNDERSTANDING_FALLBACK_FAILED.value, result.reason_codes)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_assistant_question_understanding.LlmFallbackTests -v`
Expected: FAIL — 兜底仍限定 `page_content_search`，`candidate_relations` 不被采纳。

- [ ] **Step 3: Implement**

`src/drawing_graph/assistant_question_understanding.py`：

1. 删除 `_LLM_FALLBACK_TYPES` 常量。
2. 把 `understand()` 中 `route_result` 之后的管线（splitter/evidence/clarification）抽为 `_complete_route(self, request, route_result, scope_result, normalized)`，原 `understand()` 改为调用它。
3. `UNKNOWN_OR_UNSUPPORTED` 分支改为：

```python
        if route_result.question_type == QuestionType.UNKNOWN_OR_UNSUPPORTED.value:
            if self.model_client is not None:
                try:
                    candidate = self.model_client.understand(
                        normalized,
                        scope_result.scope,
                    )
                    if candidate.question_type != QuestionType.UNKNOWN_OR_UNSUPPORTED.value:
                        synthetic = QuestionRouteResult(
                            question_type=candidate.question_type,
                            confidence=candidate.confidence,
                            ambiguities=candidate.ambiguities,
                            unsupported_parts=candidate.unsupported_parts,
                        )
                        return self._complete_route(
                            request,
                            synthetic,
                            scope_result,
                            normalized,
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
                reason_codes=(ReasonCode.QUESTION_UNDERSTANDING_FALLBACK_FAILED.value,),
            )
```

（`QuestionUnderstandingResult` 已支持 `reason_codes` 字段；`QuestionRouteResult` 从 `assistant_question_rules` 导入。）

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_assistant_question_understanding -v` → PASS（含新增 2 个）。

- [ ] **Step 5: Commit**

```bash
git add src/drawing_graph/assistant_question_understanding.py tests/test_assistant_question_understanding.py
git commit -m "feat(question): full-type LLM understanding fallback with evidence rebuild"
```

---

## Task 3: 工厂与 adapter 装配

**Files:**
- Modify: `src/drawing_graph/drawing_assistant_factory.py`
- Modify: `scripts/drawing_assistant.py` 或 `src/drawing_graph/assistant_mcp_runtime.py`
- Test: `tests/test_drawing_assistant_factory.py`（若不存在则新建 `tests/test_semantic_wiring.py`）

- [ ] **Step 1: Write the failing test**

新建 `tests/test_semantic_wiring.py`：

```python
"""Tests for semantic understanding wiring in the product factory."""

from __future__ import annotations

import unittest

from drawing_graph.assistant_question_llm import FakeQuestionUnderstandingModelClient


class FactoryWiringTests(unittest.TestCase):
    def test_factory_injects_model_client(self) -> None:
        from drawing_graph.drawing_assistant_factory import create_drawing_assistant_service

        class _Facade:
            pass

        client = FakeQuestionUnderstandingModelClient()
        service = create_drawing_assistant_service(
            facade=_Facade(),
            question_understanding_client=client,
        )
        self.assertIs(service.question_service.model_client, client)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_semantic_wiring -v`
Expected: FAIL — 工厂不接受 `question_understanding_client` 参数。

- [ ] **Step 3: Implement**

`src/drawing_graph/drawing_assistant_factory.py`：

```python
def create_drawing_assistant_service(
    facade: object,
    text_generator: object | None = None,
    question_service: object | None = None,
    question_understanding_client: object | None = None,
    retrieval_service: object | None = None,
    gap_decision_service: object | None = None,
    fusion_service: object | None = None,
    answer_service: object | None = None,
    traceability_service: object | None = None,
    trace_store: object | None = None,
) -> DrawingAssistantService:
    question_service = question_service or QuestionUnderstandingService(
        model_client=question_understanding_client,
    )
    ...
```

在 `scripts/drawing_assistant.py` 与 MCP 装配处调用：

```python
from drawing_graph.question_understanding_client import question_understanding_client_from_env
service = create_drawing_assistant_service(
    facade=facade,
    question_understanding_client=question_understanding_client_from_env(),
)
```

（按实际 adapter 的装配位置调整：`scripts/drawing_assistant.py` 与 `serve_drawing_assistant_mcp.py`/`assistant_mcp_runtime` 均以同一方式注入。）

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_semantic_wiring -v` → PASS；随后跑 `python -m unittest tests.test_drawing_assistant_cli tests.test_assistant_mcp_runtime -v` 确认无回归（按实际存在的测试模块调整）。

- [ ] **Step 5: Commit**

```bash
git add src/drawing_graph/drawing_assistant_factory.py scripts/drawing_assistant.py tests/test_semantic_wiring.py
git commit -m "feat(question): wire LLM understanding client into product assembly"
```

---

## Task 4: SynonymExpansionMatcher + DOMAIN_SYNONYMS

**Files:**
- Modify: `src/drawing_graph/page_search_matcher.py`
- Test: `tests/test_page_search_matcher.py`

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_page_search_matcher.py`：

```python
class SynonymExpansionMatcherTests(unittest.TestCase):
    def test_expands_query_token(self) -> None:
        from drawing_graph.page_search_matcher import SynonymExpansionMatcher

        matcher = SynonymExpansionMatcher()
        self.assertTrue(matcher.matches("排水", "本页含雨水管"))
        self.assertTrue(matcher.matches("挡土墙", "挡墙结构"))
        self.assertTrue(matcher.matches("混凝土", "砼"))

    def test_plain_token_still_matches(self) -> None:
        from drawing_graph.page_search_matcher import SynonymExpansionMatcher

        matcher = SynonymExpansionMatcher()
        self.assertTrue(matcher.matches("C35", "强度 C35"))
        self.assertFalse(matcher.matches("C35", "强度 C30"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_page_search_matcher.SynonymExpansionMatcherTests -v`
Expected: FAIL — `SynonymExpansionMatcher` 不存在。

- [ ] **Step 3: Implement**

`src/drawing_graph/page_search_matcher.py` 追加：

```python
DOMAIN_SYNONYMS = {
    "排水": ("雨水", "雨水口", "雨水管", "管道", "排水沟"),
    "雨水": ("排水", "雨水口", "雨水管"),
    "挡土墙": ("挡墙", "挡土结构"),
    "挡墙": ("挡土墙", "挡土结构"),
    "混凝土": ("砼",),
    "砼": ("混凝土",),
    "路基": ("路床",),
    "路面": ("面层", "铺装"),
    "断面": ("剖面", "截面"),
    "涵洞": ("箱涵", "管涵"),
    "桥梁": ("桥",),
    "标高": ("高程",),
    "护栏": ("防撞栏",),
    "沥青": ("柏油",),
}


class SynonymExpansionMatcher(TextMatcher):
    """TextMatcher with domain synonym expansion on query tokens."""

    def __init__(
        self,
        tokenizer=None,
        synonyms: Mapping[str, tuple[str, ...]] | None = None,
    ) -> None:
        super().__init__(tokenizer)
        self._synonyms = dict(synonyms or DOMAIN_SYNONYMS)

    def matches(self, query: str, text: str) -> bool:
        tokens = self.query_tokens(query)
        if not tokens:
            return False
        normalized = normalize_text(text)
        for token in tokens:
            expanded = (token,) + tuple(self._synonyms.get(token, ()))
            if not any(item in normalized for item in expanded):
                return False
        return True
```

顶部 import 增加 `from typing import Mapping`。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_page_search_matcher -v` → PASS（含新增 2 个）。

- [ ] **Step 5: Commit**

```bash
git add src/drawing_graph/page_search_matcher.py tests/test_page_search_matcher.py
git commit -m "feat(search): domain synonym expansion matcher"
```

---

## Task 5: 检索服务默认匹配器切换

**Files:**
- Modify: `src/drawing_graph/page_search_service.py`
- Test: `tests/test_page_search_service.py`

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_page_search_service.py`：

```python
class SynonymSearchTests(unittest.TestCase):
    def test_search_hits_synonym_text(self) -> None:
        facade = _ObservingFacade(
            [_page(1)],
            observed_page_id="page:1",
            text="雨水管布置",
        )
        service = PageContentSearchService(facade)
        result = service.search("set:1", "排水")
        self.assertEqual([m.page_id for m in result.matches], ["page:1"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_page_search_service.SynonymSearchTests -v`
Expected: FAIL — 默认 `TextMatcher` 词面不命中“雨水管”。

- [ ] **Step 3: Implement**

`src/drawing_graph/page_search_service.py`：

```python
from .page_search_matcher import SynonymExpansionMatcher, TextMatcher
```

```python
        self._matcher = matcher or SynonymExpansionMatcher()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_page_search_service -v` → PASS（含新增 1 个）。

- [ ] **Step 5: Commit**

```bash
git add src/drawing_graph/page_search_service.py tests/test_page_search_service.py
git commit -m "feat(search): use synonym expansion matcher by default"
```

---

## Task 6: 文档、全量回归与 live 验收

**Files:**
- Modify: `README.md`、`docs/acceptance/USER_RUNBOOK.md`

- [ ] **Step 1: Run full regression**

Run: `python -m unittest discover tests -v` → 全量通过（integration 按既有设计跳过）。

- [ ] **Step 2: Update docs**

README 的 `search-pages` 段追加：查询词支持域内同义词展开（排水↔雨水/管道等，见 `DOMAIN_SYNONYMS`）。

USER_RUNBOOK 的搜索段追加：`search-pages` 支持同义词；配置 `DASHSCOPE_API_KEY` 后启用 LLM 问题理解兜底（规则未命中时），无 key 保持纯规则。

- [ ] **Step 3: Live acceptance**

```powershell
$env:PYTHONPATH="src"; 加载 .env 后：
python scripts\drawing_graph_tool.py search-pages --drawing-set-id set:road-project:lslq_yhd_2_2 --query 排水
```

期望：`status=ok`、`coverage.total_pages=230`；命中与否按库内观察如实返回，不编造。

- [ ] **Step 4: Commit**

```bash
git add README.md docs/acceptance/USER_RUNBOOK.md
git commit -m "docs(search): document synonym expansion and LLM fallback"
```
