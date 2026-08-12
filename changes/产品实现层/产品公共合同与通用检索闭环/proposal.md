# 产品公共合同与通用检索闭环 Proposal

**文档状态：** 需求提案  
**日期：** 2026-08-11  
**依据文档：** `Feature_Analysis_Report.md`  
**适用范围：** 产品实现层中公共合同、通用检索闭环及后续 `DrawingAssistantService` 编排基础

## 1. 背景

当前图块图谱构建项目已经完成来源事实导入、离线派生关系增强、候选关系复核骨架、语义证据层、Tool Facade、QA 编排层、只读 HTTP API 和本地只读 MCP adapter。现有架构的稳定方向是：

```text
QA adapter
  -> DrawingGraphQAService
  -> DrawingGraphToolFacade
  -> ports / services
  -> controlled repository / Neo4j
```

产品实现层 00-07 文档已经规划了从自然语言问题到可追溯回答的完整闭环，包括问题理解、图谱检索、语义缺口判断、多模态识别、证据融合、答案生成、追溯与反馈。

这些文档中已经出现了大量跨模块共享概念，例如 `AssistantRequest`、`QuestionUnderstandingResult`、`EvidenceRequirement`、`RetrievalBundle`、`SemanticGapDecision`、`RecognitionRequest`、`RecognitionResult`、`EvidenceBundle`、`AnswerPackage`、`TraceRecord` 和 `FeedbackEvent`。这些概念如果继续分散在各模块中，会导致字段重复、状态漂移、证据等级混淆和 adapter 逻辑膨胀。

因此，本需求提出在正式实现完整 `DrawingAssistantService` 之前，先建立产品公共合同与通用检索闭环，作为 00-07 后续实施的共同基础。

## 2. 当前问题

### 2.1 公共合同分散

当前 00-07 文档分别定义了请求、证据、识别结果、融合结果、答案、追溯和反馈等结构，但尚未形成一个权威公共合同。后续如果各模块各自实现 DTO、枚举、状态码和错误码，容易出现同名字段含义不同、状态不可组合、序列化规则不一致的问题。

### 2.2 现有 QA 合同不足以承载完整产品闭环

`QARequest` 和 `QAAnswer` 适合现有六类固定只读问答，但不足以覆盖产品级自然语言闭环中的多意图拆分、证据需求规划、语义缺口判断、识别策略、融合 claim、追溯记录和用户反馈。

如果强行扩展 `DrawingGraphQAService` 承担完整产品闭环，会导致 QAService 变厚，职责从固定只读问答扩张为产品编排器，影响现有 CLI、HTTP、MCP 兼容边界。

### 2.3 缺少通用检索计划

当前 `DrawingGraphQAService` 主要按固定问题类型组合 facade 调用，还没有根据 `EvidenceRequirement` 自动生成最小只读查询计划的能力。

这会带来三个问题：

- 新问题类型需要继续手写检索组合，扩展成本高。
- 语义缺口判断无法稳定知道“需要什么证据、已有多少证据、缺什么证据”。
- 证据融合和答案生成难以消费统一的 `RetrievalBundle`。

### 2.4 检索结果缺少统一归一化

当前 facade DTO、QA facts、语义投影、候选关系和诊断信息已经具备事实分层基础，但尚未统一归一为产品级 `EvidenceItem` 和 `RetrievalBundle`。

如果没有统一归一化规则，后续容易把候选关系、模型解释、正式关系、来源事实混用。例如：

- 把 `candidate_relation` 当作 `formal_relation`。
- 把 `semantic_interpretation` 写成来源事实。
- 把 `matched_candidate` 误报为正式图谱关系。
- 把空结果和基础设施错误混为同一类失败。

### 2.5 产品请求缺少统一上下文

完整产品闭环需要在一次请求内稳定传递 `request_id`、`subrequest_id`、scope、source calls、warnings、missing evidence、recognition run ids、evidence ids、claim ids 和 trace record。

当前这些信息分散在不同层中，尚未形成贯穿问题理解、检索、缺口判断、识别、融合、回答、追溯反馈的统一上下文。

## 3. 功能目标

### 3.1 建立产品公共合同

建立一个产品实现层权威公共合同，用于定义后续 00-07 模块共享的 DTO、枚举、状态码、错误码、原因码、证据引用和序列化边界。

首版公共合同应覆盖：

- 产品请求：`AssistantRequest`
- 产品 scope：项目、图纸册、页面、图块、元素、断面、表格、表题、claim 等稳定业务 ID
- 问题理解结果：`QuestionUnderstandingResult`、`AssistantSubrequest`
- 证据需求：`EvidenceRequirement`、`EvidenceType`、`FreshnessPolicy`
- 通用检索：`RetrievalPlan`、`RetrievalStep`、`RetrievalBundle`
- 统一证据：`EvidenceItem`、`EvidenceRef`、`Citation`
- 语义缺口：`SemanticGapDecision`、reason codes
- 识别结果引用：`RecognitionResult` 的公共字段
- 融合结果：`EvidenceBundle`
- 答案：`AnswerPackage`、`Claim`
- 追溯与反馈：`TraceRecord`、`FeedbackEvent`
- 错误与状态：answer status、retrieval status、cache status、feedback status、unsupported 和 degraded 状态

### 3.2 建立通用检索闭环

建立从 `EvidenceRequirement` 到 `RetrievalBundle` 的稳定闭环：

```text
QuestionUnderstandingResult
  -> EvidenceRequirement[]
  -> RetrievalPlan
  -> DrawingGraphToolFacade read calls
  -> normalized EvidenceItem[]
  -> RetrievalBundle
  -> SemanticGapDecision / EvidenceFusion / AnswerGeneration
```

通用检索闭环必须满足：

- 只读。
- 默认无写回。
- 不调用 Qwen。
- 不创建 `RecognitionRun`。
- 不写 Neo4j。
- 不绕过 `DrawingGraphToolFacade` 或受控只读 port。
- 能区分来源事实、派生关系、语义观察、语义解释、候选关系、正式关系、诊断和不支持项。

### 3.3 保护现有兼容能力

现有 `DrawingGraphQAService`、QA CLI、只读 HTTP API 和本地只读 MCP adapter 继续保留。

新增产品公共合同和通用检索闭环不应破坏现有六类固定 QA 问题：

- `page_summary`
- `block_relations`
- `candidate_relations`
- `section_matches`
- `table_caption_status`
- `diagnostic_status`

后续可以将现有 QA 能力适配到新公共合同，但不应在本需求中删除或替换现有 QAService。

### 3.4 为后续 DrawingAssistantService 提供基础

本需求完成后，后续 `DrawingAssistantService` 可以在此基础上继续串联：

- 问题理解
- 通用图谱检索
- 语义缺口判断
- 多模态识别
- 证据融合
- 答案生成
- 追溯与反馈

本需求本身不要求一次性实现完整助手，只要求先建立公共合同与通用检索闭环。

## 4. 修改范围

### 4.1 产品公共合同范围

本需求范围内应规划并后续实现产品公共合同模块或等价文档/模型层，集中管理：

- 产品级请求、响应、scope 和上下文。
- 证据需求、证据项、证据引用、claim 和 citation。
- 检索计划、检索步骤、检索结果和缺失证据。
- 状态码、错误码、原因码和合同版本。
- JSON 序列化、错误 envelope 和敏感信息脱敏规则。

公共合同应作为产品实现层共享基础，不应依赖 Neo4j driver、repository、Cypher、HTTP 框架、MCP SDK 或 Qwen 客户端。

### 4.2 通用检索规划范围

本需求范围内应规划并后续实现通用检索规划能力：

- 消费 `QuestionUnderstandingResult` 和 `EvidenceRequirement`。
- 校验 scope 是否足够、是否冲突、是否需要澄清。
- 将证据需求映射为 facade 只读能力。
- 生成可执行、可去重、可审计的 `RetrievalPlan`。
- 标记必需查询、可选查询、按需 payload 展开和分页限制。

### 4.3 通用检索执行范围

本需求范围内应规划并后续实现通用检索执行能力：

- 按 `RetrievalPlan` 调用 `DrawingGraphToolFacade`。
- 记录每次受控调用为 `source_calls`。
- 对同一次请求内相同查询去重。
- 区分 `not_found`、`empty`、`partial`、`degraded`、`error` 和 `unsupported`。
- 返回结构化 `RetrievalBundle`。

### 4.4 检索结果归一化范围

本需求范围内应规划并后续实现检索结果归一化：

- 将 facade DTO、语义投影、候选关系、正式关系和诊断结果映射为统一 `EvidenceItem`。
- 保留稳定业务 ID、bbox、page/block/element 引用、recognition run id、payload ref、rule version 和状态。
- 保证 `fact_kind` 不被提升或篡改。
- 在 `missing_evidence` 和 `warnings` 中表达能力缺口、截断、权限限制和部分失败。

### 4.5 测试与验证范围

本需求范围内应规划后续测试：

- 公共合同序列化测试。
- `EvidenceRequirement -> RetrievalPlan` 映射测试。
- facade 调用去重测试。
- 事实分层不变性测试。
- candidate 不可满足 formal requirement 的安全测试。
- `write_back=false` 无持久化副作用测试。
- 架构边界测试：产品检索模块不得导入 Neo4j driver、repository、Cypher、CLI 脚本。

## 5. 不包含范围

本需求不包含以下内容：

- 不实现完整 `DrawingAssistantService` 端到端自然语言助手。
- 不实现新的 Web UI。
- 不新增远程 MCP、Streamable HTTP MCP、OAuth、RBAC、TLS 或多 worker。
- 不新增 HTTP 写回能力。
- 不新增数据库 schema 变更，除非后续设计明确需要并单独审批。
- 不默认调用真实 Qwen/DashScope 多模态模型。
- 不实现 OCR 或独立 OCR 流程。
- 不实现全量自动语义扫描。
- 不自动创建、删除或提升正式图谱关系。
- 不把候选关系、`matched_candidate` 或模型解释写成正式事实。
- 不覆盖来源事实，不设置或推断 `DrawingBlock.block_type`。
- 不直接创建 Neo4j driver，不直接写 Cypher，不直接调用 repository 写回方法。
- 不修改现有基础导入、离线派生关系增强、候选关系复核和语义证据写回边界。
- 不把 skipped 集成测试报告为 live Neo4j 通过。

## 6. 影响模块

### 6.1 新增产品公共合同模块

影响类型：新增。

该模块将成为 00-07 产品实现层共享的合同基础。它应独立于运行时 adapter 和数据库实现，负责定义稳定 DTO、枚举、状态、错误、原因码、证据引用和合同版本。

### 6.2 新增通用检索模块

影响类型：新增。

该模块将包含检索规划、检索执行和结果归一化能力。它位于 `DrawingAssistantService` 内侧或其下游，位于 `DrawingGraphToolFacade` 外侧，只通过 facade 或受控只读 port 查询图谱。

### 6.3 `DrawingGraphToolFacade`

影响类型：复用为主，可能少量扩展。

通用检索闭环会复用 facade 已有只读接口。若发现必要检索能力缺失，应优先通过新增受控 facade/port 能力解决，而不是让通用检索模块直接访问 Neo4j、repository 或 Cypher。

### 6.4 `tool_models.py`

影响类型：被投影或适配。

现有 Tool DTO 可作为检索结果的重要来源，但不建议直接等同于产品公共合同。产品公共合同应面向端到端问答，Tool DTO 仍保持 facade 层语义。

### 6.5 `qa_models.py` 与 `qa_service.py`

影响类型：兼容保留，边界澄清。

现有 QA 层继续服务六类固定只读问答。后续可以为其增加到产品公共合同的映射，但不应把 `DrawingGraphQAService` 改造成完整产品编排器。

### 6.6 `qa_serialization.py`

影响类型：可能复用或抽取。

现有 JSON 转换、错误 envelope 和脱敏规则可以作为产品公共合同序列化的参考。若后续出现重复，应考虑抽出更通用的产品层序列化能力。

### 6.7 语义证据相关模块

影响模块：

- `semantic_models.py`
- `semantic_service.py`
- `semantic_query_projection.py`
- `semantic_cache.py`
- `semantic_payload_store.py`

影响类型：只读引用与状态对齐。

公共合同需要统一表达 observation、interpretation、recognition run id、payload ref、cache key、model profile、prompt version 和合同版本。通用检索只读取这些信息，不触发识别、不写回语义证据。

### 6.8 候选关系与复核相关模块

影响模块：

- `candidate_review.py`
- `relation_repository.py`

影响类型：只读引用与边界保护。

通用检索可以读取候选关系状态，但不负责审核、提升或删除候选。任何正式关系提升仍必须通过 `CandidateReviewService` 和硬规则。

### 6.9 CLI / HTTP / MCP adapter

影响类型：短期不改，后续可新增产品级入口。

本需求不要求修改现有 adapter。后续 `DrawingAssistantService` 成熟后，可以新增产品级 CLI/HTTP/MCP 入口，同时保留现有 QA adapter 兼容行为。

### 6.10 测试模块

影响类型：新增测试覆盖。

后续实施时需要新增公共合同测试、通用检索规划测试、检索执行测试、证据归一化测试和架构边界测试，并继续区分单元测试、离线模型合同测试、live DashScope 验证和 live Neo4j 验证。
