# 语义理解升级设计（LLM 完整接通 + 语义匹配）

- 日期：2026-08-20
- 状态：待用户复审
- 关联：`2026-08-20-drawing-set-search-design.md`（已实现）、产品问答链路、检索服务 `PageContentSearchService`

## 1. 背景与现状

全册检索已实现并合并（`page_content_search`、CLI `search-pages`、规则路由、`TextMatcher` 词面子串匹配）。本设计补齐两个延后/半成品：

1. **LLM 问题理解半接通**：`HttpQuestionUnderstandingClient`（qwen chat completions + 约束 JSON + `validate_model_output` 校验）与规则兜底已实现，但：
   - 生产未装配：工厂仍创建 `QuestionUnderstandingService(model_client=None)`，线上为纯规则；
   - 兜底只采纳 `page_content_search`，其它类型会因缺证据需求进入非法下游。
2. **语义匹配未做**：当前 `TextMatcher` 只能命中字面 token，“排水”无法命中“雨水管/管道”等语义相关页面。

## 2. 目标与范围

### 2.1 范围内

- Phase 1：LLM 问题理解完整接通（生产装配 + 全类型兜底 + 失败语义）。
- Phase 2A：域内同义词/规范化扩展（离线、确定、可验收）。
- Phase 2B：向量语义检索（embedding + 混合排序 + 缓存），纳入本设计、分二期实施。

### 2.2 范围外

- 不改变既有规则路由的确定性优先级（规则命中优先，LLM 仅兜底）。
- 不引入全量离线 OCR 或新的图谱 schema 节点（向量存储位于图谱外）。
- 不做跨图纸册自动聚合或业务写回。

## 3. 已确认决策

1. Phase 1 + Phase 2A 为一个实施批次；Phase 2B 为后续批次（同设计、分计划）。
2. 无 `DASHSCOPE_API_KEY` 或未配置时，LLM 理解与 embedding 一律不启用，回落到纯规则/纯词面。
3. LLM 兜底返回任意合法 `QuestionType` 时，复用现有 splitter/evidence/clarification 重建证据需求。
4. 语义匹配采用“词面 + 同义词”先行，向量为二期；向量不可用时自动降级词面。
5. 页向量随识别/搜索缓存一起构建（“越用越快”），向量存储在图谱外。

## 4. 架构与组件

### 4.1 Phase 1：LLM 理解完整接通

- `question_understanding_client_from_env()`：从环境读取 `DASHSCOPE_API_KEY`、`DRAWING_GRAPH_QWEN_MODEL`、`DRAWING_GRAPH_QWEN_BASE_URL`、`DRAWING_GRAPH_QWEN_TIMEOUT_SECONDS`，构造 `HttpQuestionUnderstandingClient`；无 key 返回 `None`。
- 装配点：`drawing_assistant_factory.create_drawing_assistant_service` 增加可选 `question_understanding_client` 注入；MCP/CLI adapter 装配处调用 `question_understanding_client_from_env()`。
- `QuestionUnderstandingService.understand()` 重构：把“规则路由后处理”（splitter → evidence_factory → clarification）抽为 `_complete_route(...)`；LLM 兜底命中任意合法类型时，以合成 `QuestionRouteResult` 重新进入 `_complete_route`，保证证据需求完整。
- 失败语义：HTTP 非 200、JSON 解析失败、`validate_model_output` 非法 → 回落 `unknown_or_unsupported` 并追加稳定原因码（新增 `ReasonCode.QUESTION_UNDERSTANDING_FALLBACK_FAILED`）；不抛给用户、不伪造分类。

### 4.2 Phase 2A：同义词/规范化扩展

- 新增 `SynonymExpansionMatcher(TextMatcher)`：可注入 `synonyms: Mapping[str, tuple[str, ...]]`；查询 token 展开为同义词集合，命中任一即算命中。
- 内置 `DOMAIN_SYNONYMS`（示例）：`排水 → {雨水, 管道, 排水沟}`、`挡土墙 → {挡墙, 挡墙结构}`、`混凝土 → {砼}`。
- `PageContentSearchService` 的 `matcher` 已可注入，默认改为 `SynonymExpansionMatcher()`（词面行为不变，仅增加展开）。
- 同义词表为纯数据模块，可测试、可版本化。

### 4.3 Phase 2B：向量语义检索

- `TextEmbeddingClient`：协议 + DashScope HTTP 实现（`text-embedding-v3` 兼容接口），与 `HttpQuestionUnderstandingClient` 同构（可注入、可 fake）。
- 向量存储（图谱外）：SQLite 表 `page_embedding(page_id, kind, element_id, text_hash, model_version, vector_blob)`；索引由搜索/识别时按需构建，键与语义缓存对齐（`text_hash` 来自规范化文本）。
- `HybridScorer`：词面命中（lexical）+ 语义相似度（cosine）融合排序；`threshold`/`top_k` 可配置；embedding 不可用或未构建时仅用词面结果。
- 降级链：向量不可用 → 词面+同义词；两者皆无命中 → `NOT_FOUND`/`partial`，如实上报 coverage。

## 5. 数据流

### Phase 1

问题 → 规范化 → 规则路由 → 未命中时 LLM 兜底（受约束候选）→ `_complete_route`（splitter/evidence/clarification）→ 检索/生成。

### Phase 2A/B

`search-pages --query 排水` → 查询 token 展开（同义词）→ 词面匹配；二期追加：查询向量 → 语义 top-k → 混合排序 → 命中页 + hits + coverage（含 `semantic_hits` 标记）。

## 6. 契约

- `SynonymExpansionMatcher.query_tokens()` 返回展开后的 token 集合；`matches()` 任一展开命中即 True。
- `TextEmbeddingClient.embed(texts) -> list[list[float]]`；`HybridScorer.score(lexical_hits, semantic_hits) -> tuple[PageSearchMatch, ...]`。
- 检索结果新增可选字段 `semantic: bool`（二期），coverage 新增 `embedded_pages`/`embedded_now`。
- LLM 兜底失败原因码：`reason_codes` 增加 `question_understanding_fallback_failed`。

## 7. 错误处理与边界

- LLM/embedding 无 key、超时、非法输出 → 静默降级（规则/词面），不中断用户请求。
- 向量未构建的页不计入命中，也不编造相似度。
- 同义词展开不改变原文语义分层（候选关系/观察/解释边界不变）。
- 写回边界不变：识别缓存持久化仍需显式 `--write-back`；embedding 索引视为只读缓存，可重建。

## 8. 测试与验收

- Phase 1：fake client 端到端（规则未命中→LLM→各类型检索）、无 key 缺省、超时/非法输出回退、既有 2783 测试无回归。
- Phase 2A：同义词矩阵（排水/雨水管、挡土墙/挡墙、混凝土/砼）、词面行为回归。
- Phase 2B：embedding fake 相似度排序、阈值与 top_k、降级链、live 抽样（`lslq_yhd_2_2`）。
- 验收按分层报告：CLI / MCP STDIO / live Neo4j / 宿主原生注册（如实标注）。

## 9. 实施批次

- **批次一（Phase 1 + 2A）**：工厂装配与 env helper；`_complete_route` 重构；LLM 全类型兜底；失败原因码；`SynonymExpansionMatcher` + 内置同义词表；测试与文档。
- **批次二（Phase 2B，独立计划）**：`TextEmbeddingClient`；SQLite 向量存储；`HybridScorer`；覆盖/缓存；验收。

## 10. 交付物

- 本设计文档。
- 批次一实现计划（writing-plans 生成）与代码/测试。
- 批次二设计随本文件固化，实施计划另行生成。
