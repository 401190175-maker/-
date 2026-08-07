# Tool 层与 QA 编排功能分析报告

## 0. 分析范围与当前结论

本报告分析当前项目架构，以及新增“问答编排和适配层”的规划内容。范围只覆盖架构分析与未来设计建议，不修改 `src/`、`scripts/`、Schema、测试或真实 `data/` 数据。

已核对的当前文件：

- `README.md`
- `Module.md`
- `architecture.md`
- `scripts/create_schema.cypher`
- `scripts/drawing_graph_tool.py`
- `changes/tool-facade/design.md`
- `changes/tool-facade/tasks.md`
- `changes/tool-facade/Feature_Analysis_Report.md`
- `changes/语义证据层/Feature_Analysis_Report.md`
- `changes/skill封装/Feature_Analysis_Report.md`
- `src/drawing_graph/tool_facade.py`
- `src/drawing_graph/tool_factory.py`
- `src/drawing_graph/tool_models.py`
- `src/drawing_graph/query_service.py`
- `src/drawing_graph/query_ports.py`
- `src/drawing_graph/query_port_adapter.py`
- `src/drawing_graph/source_fact_query.py`
- `src/drawing_graph/semantic_*`
- `src/drawing_graph/section_match_service.py`
- `src/drawing_graph/candidate_review.py`
- `src/drawing_graph/relation_repository.py`
- `tests/` 文件清单

当前结论：

1. 项目底层图谱能力已经不是空白：来源事实导入、离线派生关系增强、候选复核骨架、`DrawingGraphToolFacade`、薄 CLI adapter、语义证据层、断面匹配投影和项目级 Codex Skill 操作边界均已落地。
2. 上文规划中的 `DrawingGraphQAService` 不应重做图谱查询、语义识别或候选复核，而应作为 facade 外侧的“问答编排层”：识别问题类型，调用现有 facade，聚合证据，返回结构化 answer。
3. `scripts/drawing_graph_qa.py`、HTTP API、MCP Tool adapter 或 Skill 强化都应依赖 `DrawingGraphQAService -> DrawingGraphToolFacade`，不能直接依赖 Neo4j driver、Cypher、repository 写回方法或离线规则函数。
4. 第一阶段工程量确实是中等偏小：核心增量主要是 QA DTO、问题类型路由、证据聚合、CLI 参数适配和测试；不是重建数据库或重构底层图谱。
5. 当前仍未实现 HTTP/REST API、MCP Tool adapter、Ava 对接、全量自动语义扫描、默认真实云多模态模型调用。报告中不得把这些规划能力写成当前能力。

推荐主线：

```text
Codex Skill / CLI / HTTP / MCP
  -> DrawingGraphQAService
  -> DrawingGraphToolFacade
  -> read port / source fact query / semantic service / semantic repository / section match service / candidate review service
  -> controlled repository / Neo4j
```

## 1. 数据库设计

### 1.1 当前图谱分层

当前数据库设计按三层事实模型组织：

```text
来源事实层
  -> 空间与上下文派生关系层
  -> 语义证据层
  -> 统一查询输出 / Tool facade / 未来 QA 编排
```

来源事实层由基础导入写入，代表从 XAnyLabeling JSON/PNG 可以直接确定的事实。核心链路是：

```text
Project -[:HAS_SET]-> DrawingSet
DrawingSet -[:HAS_PAGE]-> DrawingPage
DrawingPage -[:HAS_BLOCK]-> DrawingBlock
DrawingPage -[:HAS_TABLE]-> Table
DrawingPage -[:HAS_BASIC_INFO]-> DrawingBasicInfo
DrawingPage -[:HAS_ANNOTATION]-> DrawingAnnotation
DrawingPage -[:HAS_TEXT]-> PlainText / Title
DrawingPage -[:HAS_ELEMENT]-> BlockCaption / TableCaption / CrossSection / IgnoredElement
DrawingPage -[:IMPORTED_IN]-> ImportBatch
```

派生关系层由显式离线增强写入，代表按几何和上下文规则生成的正式派生关系或候选关系：

```text
Table -[:HAS_CAPTION]-> TableCaption
DrawingPage -[:USES_BASIC_INFO]-> DrawingBasicInfo
DrawingBlock -[:HAS_CAPTION]-> BlockCaption
DrawingBlock -[:HAS_ANNOTATION]-> DrawingAnnotation
DrawingBlock -[:HAS_SECTION_MARK]-> CrossSection
BlockCaption -[:CANDIDATE_CAPTION_OF]-> DrawingBlock
DrawingBlock -[:CANDIDATE_HAS_SECTION_MARK]-> CrossSection
```

语义证据层已引入图谱内语义证据节点和受控语义边：

```text
TextObservation
BlockInterpretation
BasicInfoInterpretation
TableInterpretation

来源元素 -[:HAS_OBSERVATION]-> TextObservation
来源元素 -[:HAS_INTERPRETATION]-> Interpretation
Interpretation -[:SUPPORTED_BY]-> TextObservation
CrossSection -[:CANDIDATE_MATCHES_SECTION_CAPTION]-> BlockCaption
CrossSection -[:MATCHES_SECTION_CAPTION]-> BlockCaption
```

关键边界：`RecognitionRun` 是图谱外运行日志，不是 Neo4j 图谱节点；图谱内 `TextObservation` 和各类 `Interpretation` 只通过 `recognition_run_id` 回查图谱外运行记录。

### 1.2 约束与索引

`scripts/create_schema.cypher` 当前已经为核心业务节点建立唯一约束，包括 `Project`、`DrawingSet`、`DrawingPage`、`DrawingBlock`、`Table`、`BlockCaption`、`TableCaption`、`CrossSection`、`DrawingBasicInfo`、`DrawingAnnotation`、`PlainText`、`Title`、`IgnoredElement` 和 `ImportBatch`。

语义证据层也已有唯一约束和查询索引：

- `TextObservation.id`
- `BlockInterpretation.id`
- `BasicInfoInterpretation.id`
- `TableInterpretation.id`
- `TextObservation.page_id`
- `TextObservation.target_element_id`
- `TextObservation.recognition_run_id`
- `TextObservation.status`
- `TextObservation.cache_key`
- 各类 `Interpretation` 的目标元素 ID、`recognition_run_id`、`status` 和部分 cache key 索引

这对未来 QA 层很重要：问答层不需要新增核心数据库节点即可回答 MVP 问题。它只需组合已有 `page_id`、`block_id`、候选关系 ID、observation、interpretation、payload 和匹配状态。

### 1.3 对 QAService 的数据库影响

第一阶段 `DrawingGraphQAService` 不建议改 Neo4j schema。原因：

- `page_summary` 可由 `get_page_source_facts()`、`list_text_observations()`、`list_interpretations()` 聚合得到。
- `block_relations` 可由 `get_block_trace()`、`get_block_relations()`、候选关系查询和语义投影得到。
- `candidate_relations` 可由 `list_candidate_relations()` 和 `list_section_matches()` 得到。
- `section_matches` 可由 `match_section_caption(write_back=false)` 和 `list_section_matches()` 得到。
- `table_caption_status` 可由页面来源事实、表格标题派生关系和候选状态查询组合得到；若当前 facade 没有直接暴露表格标题状态，可先作为 QA 编排层的能力缺口记录，不应直接写 Cypher 绕过 facade。

未来可能需要新增的数据库设计不是 QAService 自身，而是“问答运行日志”或“用户问题审计”。建议后置，除非要追踪 Ava 或 HTTP 调用：

```text
QARun / ToolCallLog / HTTPRequestLog
```

这些如果实现，也应放在图谱外或独立审计存储中，不应混入来源事实层。

## 2. 核心模块

### 2.1 当前核心模块分组

基础导入模块：

| 模块 | 当前职责 |
|---|---|
| `scanner.py` | 扫描数据根目录和 JSON/PNG 配对 |
| `validation.py` | 校验 XAnyLabeling 文档结构 |
| `image_paths.py` | 规范化同名 PNG 路径，必要时只修正 `imagePath` |
| `page_number.py` | 从 `road_<数字>.json` 解析页码 |
| `geometry.py` | 计算 bbox、中心点和归一化 bbox |
| `identifiers.py` | 生成稳定业务 ID 和 shape hash |
| `mapping.py` | 将标注 label 映射到 Neo4j 标签和页面关系 |
| `import_service.py` | 编排单页、图纸册、全量导入 |
| `neo4j_repository.py` | 受控写入来源事实节点、关系和导入批次 |

空间与上下文派生关系模块：

| 模块 | 当前职责 |
|---|---|
| `block_relation_enrichment.py` | 计算表格标题、图块标题、基础信息、注释和断面标记的正式/候选关系 |
| `relation_service.py` | 按 project / drawing-set / page 范围编排离线增强 |
| `relation_repository.py` | 读取页面快照、写入受控派生关系、查询候选关系和断面匹配、候选提升 |
| `candidate_review.py` | 候选关系三态复核和硬规则校验 |

查询与 Tool facade 模块：

| 模块 | 当前职责 |
|---|---|
| `query_service.py` | 预定义只读 Neo4j 查询，不开放任意 Cypher |
| `query_ports.py` | facade 依赖的只读 port 和 fake port |
| `query_port_adapter.py` | 将 `QueryService` dict 输出投影为 Tool DTO |
| `source_fact_query.py` | 读取单页来源事实、图片、元素和 bbox |
| `tool_models.py` | Tool DTO、错误分类、候选/语义/断面输出模型 |
| `tool_facade.py` | 当前稳定应用门面，统一只读查询、语义识别、候选查询、候选复核和断面匹配 |
| `tool_factory.py` | 装配内存 facade 或 Neo4j-backed facade；不在 import 时连接数据库 |
| `scripts/drawing_graph_tool.py` | 薄 CLI adapter，读取环境变量、创建 driver、调用 facade、输出 JSON |

语义证据模块：

| 模块 | 当前职责 |
|---|---|
| `semantic_models.py` | `TextObservation`、三类 `Interpretation`、`RecognitionRunSummary`、候选语义关系和状态 |
| `semantic_service.py` | 编排按需识别、缓存、payload、dry-run/write-back |
| `semantic_client.py` | 多模态识别客户端协议和 fake client |
| `semantic_image_inputs.py` | 基于页面来源事实构造模型输入 |
| `semantic_cache.py` | 确定性 cache key 和内存缓存 |
| `semantic_payload_store.py` | 不可变 payload 存储和 `payload_ref` |
| `recognition_run_log.py` | 图谱外 run log port 和内存实现 |
| `semantic_repository.py` | 语义证据 repository port 和内存实现 |
| `semantic_neo4j_repository.py` | Neo4j-backed 语义证据写入与查询 |
| `semantic_query_projection.py` | 统一投影来源事实、派生关系、语义观察、解释、候选/正式关系 |
| `section_label_normalization.py` | 断面标签规范化和符号体系识别 |
| `section_alias_rules.py` | 图谱外断面别名规则 |
| `section_match_service.py` | 断面候选与正式匹配判断 |

项目操作层：

| 模块 | 当前职责 |
|---|---|
| `.codex/skills/drawing-graph-operator/` | Codex 操作本项目的 Skill 规则包，位于 facade 外侧，不封装真实数据和密钥 |

### 2.2 新增 QA 层建议模块

建议新增“问答编排和适配层”，而不是修改底层图谱模块：

| 建议模块 | 职责 | 阶段 |
|---|---|---|
| `src/drawing_graph/qa_models.py` | 定义 `QuestionType`、`QARequest`、`QAAnswer`、`AnswerSection`、`EvidenceRef`、错误分类 | 阶段 1 |
| `src/drawing_graph/qa_service.py` | `DrawingGraphQAService`，问题类型路由、调用 facade、聚合证据、返回结构化 answer | 阶段 1 |
| `scripts/drawing_graph_qa.py` | 薄 QA CLI，支持 `ask-page`、`ask-block`、`ask-candidates` 等命令 | 阶段 1 |
| `src/drawing_graph/qa_http.py` 或 `api/drawing_qa.py` | FastAPI/轻量 HTTP 入口，给 Ava 或网页调用 | 阶段 2 |
| `.codex/skills/drawing-graph-operator/references/qa-workflows.md` | Skill 强化：自然语言问题到 QA 命令/服务的映射 | 阶段 3 |
| MCP Tool adapter | 机器到机器调用协议，包装 QAService 或 facade | 阶段 3 可选 |

`DrawingGraphQAService` 的核心问题类型可采用上文规划：

```text
page_summary
block_relations
candidate_relations
section_matches
table_caption_status
```

但建议补两个保守类型：

```text
unknown_or_unsupported
diagnostic_status
```

前者用于无法安全映射的问题，避免胡乱查询；后者用于回答“这页是否导入/是否增强/是否有语义证据/哪些验证未做”。

## 3. 数据流

### 3.1 当前数据流

基础导入数据流：

```text
XAnyLabeling JSON + PNG
  -> scanner / validation / image_paths / page_number / geometry / identifiers / mapping
  -> ImportService
  -> Neo4jRepository
  -> Neo4j 来源事实层 + ImportBatch 审计
```

离线派生关系增强数据流：

```text
Neo4j 来源事实层
  -> RelationRepository.read_pages()
  -> block_relation_enrichment.enrich_page_relations()
  -> RelationRepository.write_relations()
  -> 派生关系 / 候选关系 / RelationBatchAudit
```

候选复核数据流：

```text
CANDIDATE_* 候选集合
  -> CandidateReviewService
  -> accepted / rejected / unresolved
  -> 硬规则校验
  -> update_candidate_review()
  -> 可选 promote_candidate_relation()
```

语义证据数据流：

```text
DrawingGraphToolFacade
  -> get_page_source_facts()
  -> SemanticImageInputBuilder
  -> MultimodalRecognitionClient(fake 或后续真实供应商)
  -> TextObservation / Interpretation / payload_ref
  -> write_back=false: 返回临时结果，不持久化
  -> write_back=true: RecognitionRun 图谱外日志 + TextObservation/Interpretation 图谱内证据
```

断面匹配数据流：

```text
CrossSection TextObservation
  + BlockCaption TextObservation
  + 同页候选集合 / 别名规则
  -> SectionMatchService
  -> CANDIDATE_MATCHES_SECTION_CAPTION 或 MATCHES_SECTION_CAPTION
```

当前 CLI Tool 数据流：

```text
scripts/drawing_graph_tool.py
  -> ImportConfig.from_env()
  -> GraphDatabase.driver()
  -> create_neo4j_tool_facade(driver)
  -> DrawingGraphToolFacade
  -> JSON 输出
```

### 3.2 未来 QA 数据流

推荐的 QA 数据流：

```text
用户自然语言 / CLI 子命令 / HTTP 请求 / Codex Skill
  -> QARequest
  -> 问题类型识别与参数校验
  -> DrawingGraphQAService
  -> DrawingGraphToolFacade
  -> 当前 read/semantic/candidate/section 能力
  -> QAAnswer 结构化输出
  -> 可选中文简短渲染
```

各问题类型的数据组合建议：

| 问题类型 | 输入 | facade 调用 | 输出重点 |
|---|---|---|---|
| `page_summary` | `page_id` | `get_page_source_facts()`、可选 `list_text_observations(page_id)`、`list_interpretations(page_id)` | 页面图片、元素计数、来源事实、语义证据状态 |
| `block_relations` | `block_id` | `get_block_trace()`、`get_block_relations()`、`list_candidate_relations(block_id)` | 图块位置证据、正式派生关系、候选关系、增强状态 |
| `candidate_relations` | `page_id` 或 `block_id` | `list_candidate_relations()`、`list_section_matches(statuses=candidate)` | 候选类型、状态、证据、冲突原因，不写成事实 |
| `section_matches` | `cross_section_id` 或 `page_id` | `match_section_caption(write_back=false)`、`list_section_matches()` | dry-run 判断、候选/正式关系、逻辑键、符号体系 |
| `table_caption_status` | `page_id` 或 table/table caption ID | 第一版可从 `get_page_source_facts()` 和后续专门 facade 查询组合；缺口要显式说明 | 表格标题是否已派生、是否缺候选或冲突 |

QA 层输出不建议直接生成大段自然语言。推荐结构：

```text
QAAnswer
  question_type
  scope
  status
  summary
  facts[]
    fact_kind: source_fact / derived_relation / semantic_observation / semantic_interpretation / candidate_relation / formal_relation
    ids
    evidence
  warnings[]
  unsupported_parts[]
```

这样 Codex、CLI、HTTP 和 Ava 可以各自选择渲染方式，而不会丢失证据类型。

## 4. 模块依赖关系

### 4.1 当前依赖关系

当前健康的依赖方向：

```text
scripts/import_json.py
  -> ImportConfig / Neo4jRepository / ImportService

scripts/enrich_block_relations.py
  -> ImportConfig / RelationRepository / RelationEnrichmentService

scripts/review_candidate_relations.py
  -> CandidateReviewService / RelationRepository

scripts/drawing_graph_tool.py
  -> ImportConfig / create_neo4j_tool_facade()
  -> DrawingGraphToolFacade

.codex Skill
  -> DrawingGraphToolFacade / scripts/drawing_graph_tool.py
```

核心应用依赖方向：

```text
DrawingGraphToolFacade
  -> DrawingGraphReadPort
  -> SemanticRecognitionService
  -> RecognitionRunLogPort
  -> SemanticEvidenceRepositoryPort
  -> SectionMatchService
  -> SectionMatchWritePort / SectionMatchQueryPort
  -> CandidateReviewService

create_neo4j_tool_facade(driver)
  -> QueryServiceReadPortAdapter
  -> QueryService
  -> SourceFactQuery / Neo4jPageSourceFactReader
  -> SemanticNeo4jRepository
  -> RelationRepository*Port
```

底层 repository 可以知道 Neo4j；facade 可以知道 port/service；Tool adapter 和 Skill 不应知道 Neo4j、Cypher 或 repository 写回细节。

### 4.2 QA 层依赖边界

建议 QA 层只依赖 facade 和 QA 自身 DTO：

```text
scripts/drawing_graph_qa.py / HTTP / MCP / Skill
  -> DrawingGraphQAService
  -> DrawingGraphToolFacade
```

禁止依赖方向：

```text
DrawingGraphQAService -> Neo4j driver
DrawingGraphQAService -> Cypher
DrawingGraphQAService -> RelationRepository.write_relations()
DrawingGraphQAService -> RelationRepository.promote_candidate_relation()
DrawingGraphQAService -> block_relation_enrichment.py 单条规则函数
DrawingGraphQAService -> scripts/import_json.py / scripts/enrich_block_relations.py 的 CLI 主函数
```

原因：

1. QAService 是编排和投影层，不应产生数据库副作用。
2. 现有 facade 已经封装 `write_back=false`、候选关系不是正式事实、语义证据投影等边界。
3. 如果 QAService 直接读 repository 或 Cypher，就会重复产生一个绕过 facade 的工具入口，后续 Skill/HTTP/MCP 都会继承风险。

### 4.3 CLI、HTTP、Skill、MCP 的关系

四者应是同级 adapter，不互相调用：

```text
CLI adapter
HTTP adapter
Codex Skill workflow
MCP Tool adapter
  -> DrawingGraphQAService 或 DrawingGraphToolFacade
```

推荐：

- QA CLI 调 `DrawingGraphQAService`。
- HTTP API 调 `DrawingGraphQAService`。
- Codex Skill 优先指导自然语言问题映射到 QA CLI/QAService；必要时仍可直接使用 `scripts/drawing_graph_tool.py` 查询底层证据。
- MCP Tool adapter 如果实现，应包装 QAService 的稳定问题类型，而不是暴露所有内部 facade 方法。

## 5. 技术债务

### 5.1 当前技术债务

| 债务 | 说明 | 影响 |
|---|---|---|
| `QueryService` 仍直接持有 Neo4j driver | 当前通过 adapter 投影为 DTO，已经隔离到 facade 外，但查询实现本身仍与 Neo4j 耦合 | 可接受；不要在 QAService 中再次直接依赖它 |
| 薄 CLI 与 facade 能力不完全等价 | `scripts/drawing_graph_tool.py` 暴露了常用只读查询，但不暴露所有 facade 方法，例如语义识别和候选复核写回 | QA CLI 需要单独设计，不宜强行复用旧 CLI 子命令 |
| `RecognitionRun` 生产级图谱外存储仍偏轻 | `tool_factory.py` 当前默认使用 `InMemoryRecognitionRunLog`；跨进程审计能力有限 | HTTP/Ava 场景可能需要文件或数据库型 run log |
| payload store 默认内存实现 | `InMemorySemanticPayloadStore` 适合测试和当前边界，但不适合长期追溯大规模模型输出 | 正式语义问答前需考虑持久化 payload |
| 当前未实现 HTTP API | Ava 或网页集成还没有稳定机器接口 | 阶段 2 需要补 FastAPI/轻量 HTTP |
| 当前未实现 MCP Tool adapter | Codex Skill 是操作规则，不是机器接口 | 若需要可发现工具，需要单独实现 MCP |
| 默认 fake 多模态客户端 | 适合单元测试，不代表真实模型能力 | 不能把语义识别准确性写成已验证 |
| 表格标题状态缺少明确 QA 级查询 | 底层已有表格标题派生关系，但 facade 当前主要围绕 page/block/semantic/candidate/section 输出 | `table_caption_status` 可能需要新增只读 facade 方法或 QA 层缺口提示 |
| 命名历史包袱 | `enrich_block_relations.py` 现在也处理 table caption、page basic info 等，不只是 block | 保留兼容可接受；新 QA 命名应更准确 |
| 文档历史状态有漂移风险 | 早期 `Feature_Analysis_Report` 中的“未实现”在当前代码中已经变为已实现 | 新报告必须以当前源码和根文档为准 |

### 5.2 QA 规划中的潜在债务

| 风险点 | 说明 | 缓解 |
|---|---|---|
| 问答层输出自然语言过早 | 如果 QAService 直接生成长中文答案，后续 CLI/HTTP/Ava 很难复用 | QAService 输出结构化 answer，渲染层再转中文 |
| 问题类型识别做得太智能 | 第一版如果做自由问句解析，容易误判 ID 或意图 | MVP 先用显式命令和枚举 question_type，自然语言映射交给 Codex Skill |
| QAService 兼做业务查询 | 为了方便直接拼查询，会破坏 facade 边界 | 只调 facade；缺能力时记录需要新增 facade 只读方法 |
| HTTP 与 CLI 分别实现业务逻辑 | 适配层各写一套汇总规则会导致不一致 | 业务编排只放 QAService，CLI/HTTP 只做参数和渲染 |
| 候选关系语义误报 | “有没有候选关系”很容易被用户理解成“已经确认” | 输出中强制 `fact_kind=candidate_relation`，并带 `status/conflict_reason` |
| `write_back` 语义混乱 | QA 问答默认应只读，但断面匹配 facade 可 dry-run 也可 write_back | QAService MVP 默认不传 `write_back=true`；写回类问题另走复核流程 |

## 6. 未来扩展方向

### 6.1 阶段 1：QAService + QA CLI

目标：让当前 Codex 会话和命令行可以问“这页有什么”“这个 block 有什么关系”“有没有候选关系”。

建议能力：

- `DrawingGraphQAService.ask(request) -> QAAnswer`
- 问题类型：`page_summary`、`block_relations`、`candidate_relations`、`section_matches`、`table_caption_status`
- CLI：`scripts/drawing_graph_qa.py ask-page --page-id ...`
- CLI：`scripts/drawing_graph_qa.py ask-block --block-id ...`
- CLI：`scripts/drawing_graph_qa.py ask-candidates --page-id ...`
- 输出模式：`--format json` 和 `--format zh-brief`

关键约束：

- 默认只读。
- 不新增 schema。
- 不连接真实模型供应商。
- 不把候选关系写成正式事实。
- 单元测试使用 fake facade 或 fake read port。

### 6.2 阶段 2：HTTP API

目标：给 Ava、网页或其他本地软件提供稳定机器接口。

建议接口：

```text
POST /drawing-qa/ask
GET /drawing-qa/pages/{page_id}/summary
GET /drawing-qa/blocks/{block_id}/relations
GET /drawing-qa/candidates
GET /drawing-qa/section-matches
```

设计边界：

- HTTP 层只负责请求校验、认证/本机访问控制、错误脱敏和 JSON 响应。
- 连接生命周期由 app startup/shutdown 管理。
- Neo4j 密码仍来自环境变量或受控配置，不来自请求体。
- HTTP 不能开放任意 Cypher。
- 默认只读；任何 `write_back=true` 都应单独立项并有权限控制。

### 6.3 阶段 3：Codex Skill 强化

目标：让 Codex 更稳定地把自然语言问题映射到 QA 工具。

建议新增或更新：

- `.codex/skills/drawing-graph-operator/references/qa-workflows.md`
- 说明自然语言问题到 `question_type` 的映射。
- 说明什么时候用 QA CLI，什么时候直接用底层 `scripts/drawing_graph_tool.py`。
- 说明输出时必须区分 `source_fact`、`derived_relation`、`semantic_observation`、`semantic_interpretation`、`candidate_relation`、`formal_relation`。

Skill 仍不是业务逻辑本体，也不是 HTTP/MCP adapter。

### 6.4 阶段 4：MCP Tool adapter

目标：让外部 Agent 能以标准工具协议调用 QA 能力。

建议只暴露少量稳定工具：

- `ask_drawing_page`
- `ask_drawing_block`
- `list_drawing_candidates`
- `match_section_caption_dry_run`
- `get_table_caption_status`

MCP adapter 不应暴露所有 facade 方法，更不应暴露 repository 或 Cypher。

### 6.5 阶段 5：更强语义与 OCR 扩展

当前项目明确不做全量自动语义扫描和 OCR，但未来如果业务需要，可以按独立离线流程扩展：

```text
OCR batch / semantic batch
  -> raw artifact store
  -> TextObservation / Interpretation
  -> candidate semantic relations
  -> explicit review / hard rules
  -> formal relations
  -> QAAnswer 引用证据
```

关键原则：

- OCR 是独立离线 enrichment，不应塞进 `scripts/import_json.py`。
- 模型输出只进入语义证据或候选关系，不覆盖来源事实。
- `DrawingBlock.block_type` 不由 AI 自动写入。
- 跨符号体系断面匹配需要 confirmed alias rule，不靠外观猜测。

## 7. 推荐实施路线

结合上文规划，建议采用三阶段主线：

```text
第 1 阶段：2-3 天
DrawingGraphQAService + QA CLI

第 2 阶段：2-3 天
HTTP API

第 3 阶段：1-2 天
Codex Skill 强化 / 可选 MCP adapter
```

第一阶段具体边界：

1. 新增 QA DTO 和 `QuestionType`。
2. 新增 `DrawingGraphQAService`，只依赖 `DrawingGraphToolFacade`。
3. 为五类问题实现结构化聚合。
4. 新增 `scripts/drawing_graph_qa.py`，只做参数解析和结果渲染。
5. 增加单元测试覆盖问题类型、缺失 ID、not found、候选关系不当事实、`write_back=false` 边界。

第一阶段不做：

- 不做 HTTP。
- 不做 MCP。
- 不做真实模型供应商。
- 不做数据库 schema 变更。
- 不直接写 Cypher。
- 不修改导入和离线增强流程。

最终判断：本次规划不是大工程。底层图谱、facade、语义证据和候选边界已经存在，真正要补的是面向用户问题的“编排、证据聚合和适配层”。只要守住 `DrawingGraphQAService -> DrawingGraphToolFacade` 的依赖方向，第一版可控、可测试，也能自然延伸到 Ava、HTTP 和 Codex Skill。
