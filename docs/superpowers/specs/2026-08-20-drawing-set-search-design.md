# 图纸册全册检索能力设计（A + B + 问题理解增强）

- 日期：2026-08-20
- 状态：已批准（待用户复审本文件）
- 关联：`drawing-graph-operator` Skill、`图块图谱方案.md`、产品问答链路（`DrawingAssistantService.answer()`）

## 1. 背景与目标

当前产品问答存在两个叠加缺口：

1. **全册检索能力缺失**：无法回答“哪些图是关于排水的”“挡土墙的横断面图在哪一页”“哪块砖的混凝土强度等级是 C35”这类跨页问题。现有查询面全部是页/块/元素级（`list_pages`、`page-source-facts`、`list-text-observations`、`list-interpretations` 等），没有“按内容检索页面”的入口。
2. **问题理解缺口**：实测路由确认，`RuleQuestionRouter` 只有 10 类硬编码中文短语规则；“这张图是哪个路段的”“挡土墙在哪一页”“哪块砖 C35”等工程师口吻的问题全部落入 `unknown_or_unsupported`。代码预留的 `QuestionUnderstandingModelClient`（LLM 理解通道）在 `QuestionUnderstandingService.understand()` 中从未被调用，仅作占位。

本设计目标：工程师口吻的自然问题能够被识别、能够跨页检索、能够带证据回答；识别结果按需补齐并逐步缓存（“越用越快”）；全程默认只读，写识别缓存必须显式授权。

## 2. 范围

### 2.1 范围内

- 图纸册级内容检索（页面标题、图块标题/注释、`TextObservation` 文本、`Interpretation` 摘要、表题、断面标签）。
- 未识别页面的按需识别补齐（dry-run 默认；显式授权后持久化缓存）。
- 问题理解增强：规则扩展为主 + LLM 理解通道接通（可选兜底）。
- 入口：CLI `search-pages`、产品问答意图 `page_content_search`；MCP 工具 `search_drawing_pages` 作为可选交付。
- 测试、验收与文档。

### 2.2 范围外（本期不做）

- 语义/向量检索（embedding 或 LLM 相关性匹配）——作为后续增强项，不在本期实施计划内。
- 全量离线 OCR。
- 跨册自动聚合报告。
- 任何业务写回（候选提升、正式关系写入等）。

## 3. 已确认决策

1. A（只读页内容扫描 + 关键词命中）与 B（按需识别补齐 + 缓存）合并为一个实施计划。
2. LLM 问题理解接通一并纳入本期；语义/向量匹配延后。
3. 问题理解以规则扩展为主，LLM 作为兜底/增强，规则命中优先。
4. 识别默认 `write_back=false`（dry-run）；持久化识别缓存必须显式授权。
5. 单次查询识别页数配额默认 10 页，可配置。
6. 先交付 CLI 与产品问答意图；MCP 工具 `search_drawing_pages` 为可选交付。

## 4. 架构与组件

新增组件（全部通过现有只读 facade 访问图谱，不直连 Neo4j driver、不写 Cypher）：

- `PageContentCollector`：对单个页面收集可检索文本（页面标题/文件名、图块标题与注释、观察文本、解释摘要、表题、断面标签）。
- `TextMatcher`：中文二元/三元 n-gram 与子串匹配；多词 AND 语义；预留同义词扩展点（接口可替换）。
- `PageContentSearchService`：编排“分页枚举 → 逐页收集 → 匹配 → 命中结果 + coverage”。
- 识别补齐：复用 `DrawingGraphToolFacade.recognize_semantic_targets()`（`write_back=false` 默认），缓存复用 `SemanticCacheKeyInput` 缓存键。

既有代码的小改动：

- `QueryServiceReadPortAdapter.list_pages` 增加 offset/分页（当前仅 `limit=100`，`lslq_yhd_2_2` 有 230 页）。
- `QuestionType` 增加 `PAGE_CONTENT_SEARCH = "page_content_search"`。
- `EvidenceRequirementFactory` 增加 `page_content_search → DRAWING_SET_PAGES + PAGE_SOURCE_FACTS + TEXT_OBSERVATIONS + STRUCTURED_INTERPRETATIONS`。
- `ScopeResolver` 支持 `drawing_set:`/“图纸册”前缀提取 `drawing_set_id`；否则 `page_content_search` 必需 `scope_hint.drawing_set_id`，缺失时走澄清。
- `ClarificationPolicy` 将 `page_content_search` 的必需字段设为 `drawing_set_id`。

## 5. 数据流（一次查询）

1. 规范化问题 → scope 解析（缺 `drawing_set_id` → 澄清）。
2. 路由到 `page_content_search`。
3. 分页枚举册内页面（不使用 `DrawingSet.page_count` 属性，避免已知 bug）。
4. 逐页收集可检索文本（缓存观察/解释优先）。
5. 匹配查询词 → 命中页 + 命中片段 + 来源类型 + 元素 ID。
6. （B）对无缓存页且 `allow_recognition=true` 时按需识别：默认 dry-run；显式授权才持久化。
7. 组装 `AnswerPackage`：命中页带 claims/citations；无命中返回 `NOT_FOUND`/`partial`，不编造页码。

## 6. 检索内容与匹配策略

- 字段优先级：页面标题 → 图块标题/注释 → 观察文本 → 解释摘要 → 表题 → 断面标签。
- 规范化：复用 `QuestionTextNormalizer`；断面符号复用现有规范化逻辑。
- 匹配：n-gram 命中，多词 AND；首版不含同义词，保留扩展点。
- 输出：`matches[{page_id, page_title, hits[{kind, snippet, element_id, cached}]}]`。
- `coverage{total_pages, scanned_from_cache, recognized_now, skipped}` 必须如实返回。

## 7. 识别补齐与缓存（B）

- 触发条件：页面无任何缓存观察/解释，且请求 `allow_recognition=true`。
- 默认 dry-run：识别结果仅用于本次回答，不持久化。
- 写缓存：需显式授权；持久化复用 `SemanticCacheKeyInput` 缓存键，命中不重复识别。
- 配额：单次查询识别页数上限（默认 10）、超时、失败页计入 `skipped` 并说明原因。
- “越用越快”：同册二次查询命中缓存页占比上升，属预期行为，纳入验收指标。

## 8. 问题理解增强

### 8.1 规则扩展（本期）

- 新增 `page_content_search` 模式：“哪一页”“哪些图”“哪几张图”“关于X”“涉及X”“在哪一页”“查找/搜索 X 的图”等。
- 修正现有漏网句式：
  - “A-A 剖面在哪个图块上” → `section_matches`；
  - “这块是什么” → `block_semantic_identification`；
- 已有规则覆盖的句式（“这个断面对应哪个标题”）保持不变，避免重复匹配。
- 复用排除词机制防串扰（如“候选关系”不落入 `block_relations`）。
- 多意图与歧义继续走现有 `clarification_required` 机制，不新增旁路。

### 8.2 LLM 理解通道（本期，兜底）

- 接通已预留的 `QuestionUnderstandingModelClient` 协议。
- 规则命中优先；仅当规则未命中或置信度不足时使用 LLM 兜底。
- 输出约束为受控候选（`question_type/confidence/ambiguities/unsupported_parts`），不允许生成事实、查询语言或写回授权。
- 提示词只做意图分类；配套提示词版本、输出校验与失败回退（回落到 `unknown_or_unsupported` 或澄清）。

## 9. 入口与契约

- CLI：`python scripts\drawing_graph_tool.py search-pages --drawing-set-id set:road-project:lslq_yhd_2_2 --query 排水 [--allow-recognition] [--recognize-page-limit 10]`
- 产品问答：`ask_drawing_assistant` 识别“哪些图/哪一页/哪块”类问题后路由到 `page_content_search`。
- MCP QA 工具（可选）：`search_drawing_pages`，只读，与六个窄口径工具并列。
- 响应契约：`{status, matches, coverage, warnings, unsupported_parts}`；只使用稳定业务 ID，不暴露内部字段。

## 10. 错误处理与边界

- 无命中 = `NOT_FOUND`/`partial`，是合法状态，不是错误。
- `page_count` 属性 bug 不作为计数来源，页数一律来自分页枚举。
- 空册、超时、识别失败、配额用尽 → `coverage` 如实说明。
- 无写缓存授权时，识别结果不持久化（dry-run）。
- 不把候选关系、观察或解释表述为正式事实。

## 11. 测试与验收

- 单元：路由矩阵（工程师句式 → 期望意图）、匹配器（n-gram/多词 AND）、coverage 计算、scope 解析（含 `drawing_set` 提取）、澄清策略。
- 合同：CLI 输出结构、MCP 工具 schema、`AnswerPackage` 集成。
- live Neo4j：使用 `lslq_yhd_2_2` 真实册验证“排水/挡土墙/哪一页/C35”类问题；分层报告（CLI / MCP STDIO / live Neo4j 分开标注，宿主原生注册另行标注）。
- 性能基线：纯缓存扫描 230 页 <10s；首次含识别按配额执行。
- 回归：既有 2577 项测试保持通过（`tests/integration/` 跳过逻辑不变）。

## 12. 实施计划（合并版）

单一实现计划，按里程碑推进：

1. **基础设施**：`list_pages` 分页扩展；`QuestionType.PAGE_CONTENT_SEARCH`；证据模板；scope 解析与澄清策略。
2. **检索核心**：`PageContentCollector`、`TextMatcher`、`PageContentSearchService`；CLI `search-pages`。
3. **路由与产品问答**：规则扩展；产品意图接入 `DrawingAssistantService`；`AnswerPackage` 集成。
4. **识别补齐与缓存（B）**：dry-run 调用、写缓存授权、配额与 coverage。
5. **LLM 理解接通（兜底）**：真实客户端、提示词、输出校验、回退与测试。
6. **验收与文档**：测试矩阵、live Neo4j 验收、RUNBOOK/README 更新。

延后项：语义/向量匹配（embedding / LLM 相关性），作为独立设计另行立项。

## 13. 交付物

- 设计文档（本文件）。
- 实现计划（由 writing-plans 生成）。
- 代码与测试、验收记录、运行手册更新。
