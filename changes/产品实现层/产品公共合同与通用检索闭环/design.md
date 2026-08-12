# 产品公共合同与通用检索闭环技术设计

**文档状态：** 技术设计  
**日期：** 2026-08-11  
**依据文档：** `proposal.md`、`Feature_Analysis_Report.md`  
**设计原则：** 优先复用已有架构，禁止无意义重构，默认只读，默认 `write_back=false`

## 1. 系统架构变化

### 1.1 当前架构保持不变的部分

本设计不改变当前基础导入、离线派生关系增强、候选关系复核、语义证据写回、QA CLI、HTTP API 和 MCP adapter 的既有职责。

现有稳定链路继续保留：

```text
QA adapter
  -> DrawingGraphQAService
  -> DrawingGraphToolFacade
  -> ports / services
  -> controlled repository / Neo4j
```

`DrawingGraphQAService` 继续作为六类固定只读问答的兼容编排层，不被改造成完整产品助手，不承担多意图拆分、通用检索计划、语义缺口判断、证据融合和追溯反馈等新增产品职责。

### 1.2 新增产品层架构

新增产品公共合同与通用检索闭环后，目标依赖方向为：

```text
Product adapter（后续 CLI / HTTP / MCP / Web UI）
  -> DrawingAssistantService（后续完整产品编排）
       -> QuestionUnderstandingService
       -> GraphRetrievalService
            -> RetrievalPlanner
            -> RetrievalExecutor
            -> RetrievalBundleBuilder
       -> SemanticGapDecisionService
       -> MultimodalRecognitionService
       -> EvidenceFusionService
       -> AnswerGenerationService
       -> TraceabilityFeedbackService
  -> DrawingGraphToolFacade
  -> ports / services
  -> controlled repository / Neo4j
```

本需求首阶段只设计并后续实现：

```text
ProductContracts
  + GraphRetrievalService
       -> RetrievalPlanner
       -> RetrievalExecutor
       -> RetrievalBundleBuilder
```

其中：

- `ProductContracts` 是产品实现层的公共 DTO、枚举、状态、错误、证据引用和序列化契约。
- `GraphRetrievalService` 是通用检索闭环入口，消费 `QuestionUnderstandingResult` 和 `EvidenceRequirement`，输出 `RetrievalBundle`。
- `RetrievalPlanner` 只负责计划，不访问 facade。
- `RetrievalExecutor` 只通过 `DrawingGraphToolFacade` 或新增受控只读 port 执行查询。
- `RetrievalBundleBuilder` 只做证据归一化和缺失/警告汇总，不提升事实等级。

### 1.3 与现有 QAService 的关系

新增产品检索闭环与 `DrawingGraphQAService` 是并列上层能力，不互相替代。

```text
现有固定 QA：
CLI / HTTP / MCP
  -> DrawingGraphQAService
  -> DrawingGraphToolFacade

新增产品闭环：
Product adapter / DrawingAssistantService
  -> GraphRetrievalService
  -> DrawingGraphToolFacade
```

后续如需兼容现有六类 QA，可通过 mapper 将固定 `QARequest` 转为产品层 `QuestionUnderstandingResult` 和 `EvidenceRequirement`，但不要求在本需求中重写现有 QAService。

## 2. 新增模块

### 2.1 产品公共合同模块

已冻结模块名：`assistant_models.py`（不再使用 `product_contracts.py`）。

职责：

- 定义产品层请求、scope、证据需求、检索计划、证据项、检索结果、答案、追溯和反馈的公共 DTO。
- 定义稳定枚举：`fact_kind`、`evidence_type`、`retrieval_status`、`answer_status`、`gap_decision`、`cache_status`、`feedback_status`、`reason_code`。
- 定义 `contract_version` 与 `output_contract_version` 传递规则。
- 不依赖 Neo4j driver、repository、Cypher、HTTP 框架、MCP SDK 或 Qwen 客户端。

首版核心对象：

- `AssistantRequest`
- `AssistantScope`
- `QuestionUnderstandingResult`
- `AssistantSubrequest`
- `EvidenceRequirement`
- `RetrievalPlan`
- `RetrievalStep`
- `SourceCallRecord`
- `EvidenceItem`
- `RetrievalBundle`
- `MissingEvidence`
- `AnswerPackage`
- `Claim`
- `Citation`
- `TraceRecord`
- `FeedbackEvent`

### 2.2 通用检索规划模块

已冻结模块名：`assistant_retrieval_planner.py`（不再使用 `graph_retrieval_planner.py`）。

职责：

- 接收 `QuestionUnderstandingResult` 和 `EvidenceRequirement[]`。
- 校验 scope 是否完整、冲突或需要澄清。
- 将证据需求映射为 `DrawingGraphToolFacade` 只读能力。
- 生成去重后的 `RetrievalPlan`。
- 标记必需查询、可选查询、payload 按需展开、limit 和分页策略。

本模块不得：

- 调用 facade。
- 调用 Qwen。
- 读写 Neo4j。
- 写 run log。
- 修改任何证据状态。

### 2.3 通用检索执行模块

已冻结模块名：`assistant_retrieval_executor.py`（不再使用 `graph_retrieval_executor.py`）。

职责：

- 按 `RetrievalPlan` 调用 `DrawingGraphToolFacade`。
- 记录每次调用的 `SourceCallRecord`。
- 将 facade 调用异常转换为稳定检索错误。
- 对同一请求内相同查询去重。
- 可在后续支持并发执行独立只读查询，但输出顺序必须稳定。

本模块只允许依赖：

- 产品公共合同。
- `DrawingGraphToolFacade` 的公开只读方法。
- 必要的通用错误脱敏工具。

### 2.4 检索结果归一化模块

已冻结模块名：`assistant_retrieval_projection.py`（不再使用 `retrieval_bundle_builder.py`）。

职责：

- 将 facade DTO、语义投影、候选关系和诊断结果映射为统一 `EvidenceItem`。
- 构造 `RetrievalBundle`。
- 保留 `fact_kind`、稳定业务 ID、bbox、page/block/element 引用、payload ref、recognition run id、rule version 和状态。
- 输出 `missing_evidence`、`warnings` 和 `diagnostics`。

事实等级约束：

- 来源事实只能映射为 `source_fact`。
- 规则派生关系映射为 `derived_relation`。
- `TextObservation` 映射为 `semantic_observation`。
- 三类 `Interpretation` 映射为 `semantic_interpretation`。
- `CANDIDATE_*` 映射为 `candidate_relation`。
- 受控确认关系映射为 `formal_relation`。
- 运行状态、缺口、截断、降级映射为 `diagnostic` 或 `unsupported`。

### 2.5 通用检索服务模块

已冻结模块名：`assistant_retrieval_service.py`（不再使用 `graph_retrieval_service.py`）。

职责：

- 作为通用检索闭环的唯一产品层入口。
- 编排 planner、executor、bundle builder。
- 对外提供 `retrieve()` 方法。
- 不承担自然语言理解、语义缺口判断、识别、融合、答案生成或追溯写入。

推荐调用形态：

```text
GraphRetrievalService(facade, planner, executor, bundle_builder)
  .retrieve(question_result, policy)
  -> RetrievalBundle
```

## 3. 修改模块

### 3.1 `DrawingGraphToolFacade`

修改策略：优先复用，少量补口。

当前 facade 已提供足够的首版只读能力，包括：

- `list_drawing_sets`
- `list_pages`
- `get_page_source_facts`
- `get_block_trace`
- `get_block_relations`
- `list_text_observations`
- `list_interpretations`
- `get_semantic_payload`
- `list_candidate_relations`
- `list_section_matches`

首版通用检索应先基于这些能力设计。只有当 `EvidenceRequirement` 无法通过现有 facade 表达时，才新增受控只读方法或 port。新增能力必须仍由 facade 暴露，不能让产品检索模块直接调用 `QueryService`、repository、Neo4j session 或 Cypher。

### 3.2 `tool_models.py`

修改策略：保留 facade DTO，不反向依赖产品合同。

`tool_models.py` 的 DTO 贴近 facade 边界，可作为 `RetrievalBundleBuilder` 的输入来源。产品公共合同不应污染 facade DTO；如需要转换，新增 mapper/projection，而不是改写已有 Tool DTO 语义。

### 3.3 `qa_models.py` / `qa_service.py`

修改策略：兼容保留，不无意义重构。

已冻结模块名：`assistant_qa_mapping.py`（六类 QA 兼容映射模块）。

现有 `QARequest`、`QAAnswer` 和 `DrawingGraphQAService.ask()` 保持稳定。后续可新增可选 mapper：

```text
QARequest
  -> QuestionUnderstandingResult
  -> EvidenceRequirement[]
```

但首版不要求 QAService 反向依赖产品公共合同，也不要求删除已有固定问题路由。

首版兼容映射已落地为 `src/drawing_graph/assistant_qa_mapping.py` 的
`qa_request_to_question_result()`，只做 `QARequest -> QuestionUnderstandingResult`
与 `EvidenceRequirement[]` 的单向转换；`qa_service.py` 不反向导入任何
`assistant_` 模块。

### 3.4 `qa_serialization.py`

修改策略：复用脱敏与 JSON 转换经验。

产品公共合同可以复用 `to_jsonable`、错误 envelope 和 `sanitize_error_message` 的思路。若后续实施中发现通用性足够，再提取共享序列化工具；本设计不要求为了新需求提前重构现有 QA serialization。

### 3.5 语义证据相关模块

影响模块：

- `semantic_models.py`
- `semantic_query_projection.py`
- `semantic_cache.py`
- `semantic_payload_store.py`
- `semantic_service.py`

修改策略：

- 通用检索仅读取已有 observation、interpretation、payload ref、cache key、recognition run id、model profile、prompt version。
- 通用检索不触发 `SemanticRecognitionService`。
- 通用检索不创建或完成 `RecognitionRun`。
- 如需补充状态枚举映射，优先在产品 projection 层处理，不改语义证据内部语义。

### 3.6 候选关系与复核相关模块

影响模块：

- `candidate_review.py`
- `relation_repository.py`

修改策略：

- 通用检索只读取候选状态。
- 不执行候选审核。
- 不执行候选提升。
- 不删除候选边。
- formal 提升仍只能经 `CandidateReviewService` 和硬规则。

### 3.7 CLI / HTTP / MCP adapter

修改策略：首版不改。

现有 adapter 继续指向 `DrawingGraphQAService`。产品级 adapter 入口放到后续 `DrawingAssistantService` 成熟后单独设计，例如：

- `scripts/drawing_graph_assistant.py`
- `POST /api/v1/drawing-assistant/ask`
- MCP 产品级只读工具

本设计不要求当前阶段新增这些 adapter。

## 4. 数据模型变化

### 4.1 Neo4j 数据模型

首版不改变 Neo4j 节点、关系、约束或索引。

不新增：

- 新业务节点标签。
- 新图谱关系类型。
- 新 Neo4j schema 文件变更。
- `RecognitionRun` 图谱节点。
- `DrawingBlock.block_type` 字段。
- HTTP/MCP 写回关系。

原因：本需求是产品层公共合同和只读检索闭环，主要变化发生在应用层 DTO 和查询结果归一化层。

### 4.2 产品层公共数据模型

新增产品层 DTO，不写入 Neo4j。核心模型如下。

#### 4.2.1 `AssistantScope`

用于统一表达请求范围。

字段：

- `project_id`
- `drawing_set_id`
- `page_id`
- `block_id`
- `element_id`
- `cross_section_id`
- `table_id`
- `table_caption_id`
- `claim_id`

约束：

- 所有 ID 必须是稳定业务 ID，不接受 Neo4j 内部 ID。
- 不接受 Cypher 或自由查询语句。
- 对同一请求中冲突的 scope 返回 `clarification_required`。

#### 4.2.2 `EvidenceRequirement`

用于描述“回答问题需要什么证据”。

字段：

- `requirement_id`
- `evidence_type`
- `target_scope`
- `required`
- `minimum_status`
- `freshness_policy`
- `allow_model_generation`
- `include_payload`
- `limit`

约束：

- `allow_model_generation` 只表达是否允许模型生成缺失语义证据，不代表允许写数据库。
- `include_payload=false` 为默认值，只有答案确实需要完整解析 JSON 时才读取 payload。

#### 4.2.3 `RetrievalPlan`

用于表达只读查询计划。

字段：

- `request_id`
- `subrequest_id`
- `steps[]`
- `dedupe_keys[]`
- `warnings[]`

`RetrievalStep` 字段：

- `step_id`
- `facade_method`
- `scope`
- `parameters`
- `required`
- `depends_on`
- `limit`
- `include_payload`
- `requirement_ids[]`

约束：

- `facade_method` 只能来自白名单。
- `parameters` 不得包含 Neo4j URI、用户名、密码、token、Cypher 或内部 driver/session 对象。

#### 4.2.4 `EvidenceItem`

用于统一承载检索结果。

字段：

- `evidence_id`
- `fact_kind`
- `status`
- `scope`
- `value`
- `confidence`
- `source_system`
- `source_call_id`
- `recognition_run_id`
- `payload_ref`
- `model_profile`
- `prompt_version`
- `rule_version`
- `created_at_or_version`
- `evidence_refs[]`

约束：

- `fact_kind` 在归一化后不可被后续模块提升。
- `candidate_relation` 不能满足 `formal_relation` 需求。
- `semantic_interpretation` 不能冒充 `source_fact`。

#### 4.2.5 `RetrievalBundle`

用于传递通用检索闭环输出。

字段：

- `request_id`
- `subrequest_id`
- `scope`
- `source_facts[]`
- `derived_relations[]`
- `semantic_observations[]`
- `semantic_interpretations[]`
- `candidate_relations[]`
- `formal_relations[]`
- `diagnostics[]`
- `missing_evidence[]`
- `warnings[]`
- `source_calls[]`
- `status`

### 4.3 合同版本

首版建议固定：

- `contract_version = "drawing-assistant-contract-v1"`
- `retrieval_contract_version = "drawing-assistant-retrieval-v1"`

合同版本只进入产品层 DTO 和输出，不写入 Neo4j。后续如字段破坏性变更，新增版本而不是静默改变同一版本语义。

## 5. API 设计

### 5.1 内部 Python API

首版 API 是应用层内部 API，不直接对外开放 HTTP/MCP。

#### 5.1.1 `RetrievalPlanner.plan`

输入：

```text
QuestionUnderstandingResult
RetrievalPolicy
```

输出：

```text
RetrievalPlan
```

行为：

- 校验 scope。
- 将 `EvidenceRequirement` 映射为 facade 方法。
- 对重复查询生成同一个 dedupe key。
- 对缺少 facade 能力的需求生成 `MissingEvidence` 或 unsupported step。

#### 5.1.2 `RetrievalExecutor.execute`

输入：

```text
RetrievalPlan
DrawingGraphToolFacade
```

输出：

```text
RawRetrievalResult
SourceCallRecord[]
```

行为：

- 只调用白名单 facade 方法。
- 捕获并脱敏异常。
- 对 required step 失败标记 degraded/error。
- 对 optional step 失败保留 warning。

#### 5.1.3 `RetrievalBundleBuilder.build`

输入：

```text
QuestionUnderstandingResult
RetrievalPlan
RawRetrievalResult
SourceCallRecord[]
```

输出：

```text
RetrievalBundle
```

行为：

- 将原始结果映射为 `EvidenceItem`。
- 按 `fact_kind` 分组。
- 输出 missing evidence、warnings、diagnostics。

#### 5.1.4 `GraphRetrievalService.retrieve`

输入：

```text
QuestionUnderstandingResult
RetrievalPolicy
```

输出：

```text
RetrievalBundle
```

行为：

```text
plan = planner.plan(question_result, policy)
raw = executor.execute(plan, facade)
bundle = bundle_builder.build(question_result, plan, raw)
return bundle
```

### 5.2 Facade 方法白名单

通用检索首版只允许调用：

- `list_drawing_sets(project_id, limit)`
- `list_pages(drawing_set_id, limit)`
- `get_page_source_facts(page_id, element_types=None, include_image_meta=True)`
- `get_block_trace(block_id)`
- `get_block_relations(block_id)`
- `list_text_observations(page_id=None, element_id=None, recognition_run_id=None, statuses=None)`
- `list_interpretations(page_id=None, element_id=None, recognition_run_id=None, statuses=None)`
- `get_semantic_payload(payload_ref)`
- `list_candidate_relations(page_id=None, block_id=None, relation_type=None, status=None)`
- `list_section_matches(cross_section_id=None, page_id=None, statuses=None)`

不允许调用：

- `recognize_page_semantics`
- `review_candidate_relation`
- `match_section_caption(..., write_back=True)`
- 任何 repository、Neo4j driver、session、Cypher 或 CLI 脚本。

说明：`match_section_caption(write_back=False)` 当前是 dry-run 语义匹配能力，是否纳入通用检索白名单需在后续任务中单独评估。首版通用检索优先使用 `list_section_matches()` 读取已有断面候选/正式匹配，避免检索阶段触发新的语义匹配决策。

### 5.3 EvidenceRequirement 到 facade 能力映射

| 证据类型 | 首选 facade 方法 | 输出 fact_kind |
|---|---|---|
| 项目图纸册 | `list_drawing_sets` | `source_fact` |
| 图纸册页面 | `list_pages` | `source_fact` |
| 页面来源事实 | `get_page_source_facts` | `source_fact` |
| 图块位置追溯 | `get_block_trace` | `source_fact` |
| 图块派生关系 | `get_block_relations` | `derived_relation` / `candidate_relation` / `diagnostic` |
| 文字观察 | `list_text_observations` | `semantic_observation` |
| 结构化解释 | `list_interpretations` | `semantic_interpretation` |
| 完整语义 payload | `get_semantic_payload` | `semantic_observation` 或 `semantic_interpretation` 的附属引用 |
| 候选关系 | `list_candidate_relations` | `candidate_relation` |
| 断面匹配关系 | `list_section_matches` | `candidate_relation` / `formal_relation` |

### 5.4 后续外部 API

本设计不要求首版新增外部 API。后续 `DrawingAssistantService` 成熟后可新增：

- CLI：`scripts/drawing_graph_assistant.py ask`
- HTTP：`POST /api/v1/drawing-assistant/ask`
- MCP：产品级只读 assistant tool

这些 adapter 必须只调用 `DrawingAssistantService`，不得直接调用 `GraphRetrievalService`、facade、repository 或 Cypher。

## 6. 异常处理

### 6.1 异常分类

通用检索闭环使用稳定错误分类，不透出底层异常细节。

| 分类 | 含义 | 处理 |
|---|---|---|
| `invalid_request` | 请求结构无效 | 返回 error bundle，不执行检索 |
| `scope_missing` | 必需 scope 缺失 | 返回 `clarification_required` 诊断 |
| `scope_conflict` | 多个 scope 冲突 | 返回 `clarification_required` 诊断 |
| `unsupported_evidence_type` | 证据需求无受控查询能力 | 写入 `missing_evidence` |
| `target_not_found` | 目标业务 ID 不存在 | 目标相关 required step 停止 |
| `empty_result` | 查询成功但无结果 | 记录空结果，不当作基础设施错误 |
| `facade_call_failed` | facade 调用失败 | required step 标记 degraded/error |
| `payload_unavailable` | payload 缺失或不可读取 | 保留摘要，写 warning |
| `result_truncated` | 结果超过 limit | 返回截断结果和 warning |
| `internal_error` | 未预期错误 | 脱敏后返回 degraded/error |

### 6.2 required 与 optional 策略

- required step 失败：`RetrievalBundle.status` 至少为 `partial` 或 `error`。
- optional step 失败：保留已成功证据，写入 warning。
- 目标不存在：停止目标相关查询，但保留其他子请求证据。
- payload 不可用：不丢弃 observation/interpretation 摘要。
- 空结果：标记 `missing_evidence`，不伪装成系统故障。

### 6.3 错误脱敏

错误输出不得包含：

- Neo4j URI 中的认证信息。
- Neo4j 密码。
- API key。
- Bearer token。
- 本地敏感路径的完整上下文。
- Cypher。
- driver/session/transaction 对象。
- Python traceback。

### 6.4 验证状态报告

设计和后续实现必须分开报告：

- 单元测试。
- 合同测试。
- 架构边界测试。
- fake facade 测试。
- live Neo4j 集成测试。
- live DashScope 测试。

未配置 live 环境导致测试 skipped 时，不得报告为通过。

## 7. 安全方案

### 7.1 只读边界

通用检索闭环默认只读，首版不提供写回参数。

禁止行为：

- 调用 `recognize_page_semantics` 触发新识别。
- 创建 `RecognitionRun`。
- 写入 `TextObservation` 或 `Interpretation`。
- 审核或提升候选关系。
- 写 Neo4j。
- 修改 JSON。
- 执行 Cypher。

### 7.2 `write_back=false` 传递

产品公共合同中的 `AssistantRequest.allow_write_back` 默认仍为 `false`。但通用检索阶段不消费写回授权，即使上游请求未来显式允许写回，检索模块也不得执行任何持久化操作。

写回只能在后续语义识别、融合或反馈模块中经过独立授权、策略和环境检查后进行。

### 7.3 事实分层保护

公共合同必须强制 `fact_kind`：

- `candidate_relation` 不是 `formal_relation`。
- `semantic_interpretation` 不是 `source_fact`。
- `semantic_observation` 不能覆盖来源标注。
- `matched_candidate` 不能当作正式图谱关系。
- 用户反馈不能直接提升正式关系。

任何后续答案生成都必须根据 `fact_kind` 使用不同措辞和置信表达。

### 7.4 依赖边界保护

产品公共合同模块不得依赖：

- Neo4j driver。
- repository。
- Cypher。
- HTTP/FastAPI。
- MCP SDK。
- Qwen/DashScope 客户端。
- CLI 脚本。

通用检索模块不得依赖：

- Neo4j driver/session/transaction。
- `QueryService`。
- `RelationRepository`。
- `SemanticNeo4jRepository`。
- `CandidateReviewService` 的写回方法。
- `scripts/import_json.py`、`scripts/enrich_block_relations.py`、`scripts/review_candidate_relations.py`。

### 7.5 输入校验

- 所有 scope ID 必须为稳定业务 ID。
- 禁止传入 Cypher。
- 禁止传入 Neo4j 内部 ID。
- `limit` 必须有上限。
- `include_payload` 默认关闭。
- 未知字段在 adapter 层应被拒绝；内部 DTO 应通过合同测试保证字段白名单。

### 7.6 数据最小化

通用检索默认返回回答所需最小证据：

- 默认不读取完整 payload。
- 页面级大集合必须分页或 limit。
- 图片路径按现有 facade 策略返回，不扩大暴露范围。
- 诊断信息只返回分类原因，不返回底层 traceback。

### 7.7 兼容安全

现有 QA CLI、HTTP、MCP adapter 不因本需求改变默认安全策略：

- HTTP 仍默认 loopback。
- MCP 仍为本机 STDIO。
- `write_back=true` 仍被 QAService 拒绝。
- HTTP/MCP 不新增写回工具。
- ready/live health 仍不等于 live Neo4j 验证。

## 8. 测试设计

虽然本文件重点是技术方案，后续实施必须按模块独立测试。

已落地测试文件：

- `tests/test_assistant_models_contract.py`
- `tests/test_assistant_retrieval_planner.py`
- `tests/test_assistant_retrieval_executor.py`
- `tests/test_assistant_retrieval_projection.py`
- `tests/test_assistant_retrieval_service.py`
- `tests/test_assistant_qa_mapping.py`
- `tests/test_assistant_retrieval_boundaries.py`
- `tests/test_assistant_docs.py`

关键测试：

- 公共 DTO 序列化和默认值。
- `allow_write_back` 默认 false。
- `EvidenceRequirement` 到 facade 方法映射。
- 相同 facade 调用去重。
- `fact_kind` 不变性。
- candidate 不可满足 formal。
- payload 默认不展开。
- scope 缺失和冲突。
- facade required/optional 失败策略。
- 禁止导入 Neo4j driver、repository、Cypher 和 CLI 脚本的静态边界。

## 9. 实施顺序建议

后续实施计划建议按以下顺序拆分，不合并多个目标：

1. 建立产品公共合同 DTO 与枚举。
2. 建立合同序列化和默认值测试。
3. 建立 `EvidenceRequirement -> RetrievalPlan` 映射。
4. 建立 fake facade 检索执行。
5. 建立检索结果归一化。
6. 建立 `GraphRetrievalService.retrieve()` 编排。
7. 增加架构边界测试。
8. 增加现有六类 QA 到产品检索需求的兼容映射设计或测试。

每一步都应可独立测试，不应顺手重构既有 QA、HTTP、MCP 或语义证据写回模块。
