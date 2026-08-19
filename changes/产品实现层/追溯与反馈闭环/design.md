# 追溯与反馈闭环 Design

## 1. 系统架构变化

新增 `TraceabilityFeedbackService` 族模块，位置在产品应用层，位于 adapter 内侧、`DrawingGraphToolFacade` 外侧，与 `DrawingAssistantService` 同层协作。

推荐架构：

```text
Product CLI / future Product HTTP / future Product MCP / future Web UI
  -> DrawingAssistantService（01-06 只读问答）
       -> QuestionUnderstandingService
       -> GraphRetrievalService
       -> SemanticGapDecisionService
       -> DrawingGraphToolFacade.recognize_semantic_targets(write_back=false)
       -> EvidenceFusionService(write_back_policy=None)
       -> AnswerGenerationService
       -> optional TraceabilityService.record_answer_trace()

Feedback adapter（后续独立入口）
  -> FeedbackService
       -> FeedbackPermissionPolicy
       -> FeedbackStateMachine
       -> FeedbackStorePort
       -> CandidateReviewAdapter（仅 request_review）
            -> CandidateReviewService
            -> 受控 repository（由 CandidateReviewService 既有路径处理）
```

现有 QA CLI/HTTP/MCP 仍保持：

```text
QA adapter -> DrawingGraphQAService -> DrawingGraphToolFacade -> ports/services -> repository/Neo4j
```

本需求不改变 QA 链路，也不让 QA adapter 反向依赖产品 trace/feedback 模块。

## 2. 新增模块

### 2.1 `assistant_trace_models.py`

职责：

- 定义产品级追溯 DTO、模块事件、成本/时延摘要、trace 写入结果、claim trace 投影。
- 保留与 `assistant_models.TraceRecord` 的字段兼容，避免破坏现有公共合同测试。

建议核心模型：

- `TraceModuleEvent`
- `TraceCostSummary`
- `TraceLatencySummary`
- `TraceRecord`
- `TraceWriteResult`
- `ClaimTrace`
- `TraceQueryResult`

### 2.2 `assistant_trace_store.py`

职责：

- 定义 `TraceStorePort`。
- 提供 `InMemoryTraceStore` 作为首版 fake/offline 实现。
- 只做 append/read，不访问 Neo4j，不写业务事实。

建议接口：

```text
append_trace(record) -> TraceWriteResult
get_trace(request_id) -> TraceRecord | None
get_claim_trace(claim_id) -> ClaimTrace | None
list_feedback_refs(request_id) -> tuple[str, ...]
```

### 2.3 `assistant_trace_builder.py`

职责：

- 从 `AssistantRequest`、问题理解结果、检索 bundle、语义缺口决策、识别结果、EvidenceBundle、AnswerPackage 构造 `TraceRecord`。
- 对敏感字段执行数据最小化。
- 不发起查询、不调用模型、不写 store。

### 2.4 `assistant_claim_trace.py`

职责：

- 从 `TraceRecord` 与 `AnswerPackage` 构造 `ClaimTrace`。
- 支持 `claim_id -> citations/evidence/run/cache/module events` 回查。
- 保证 claim trace 只使用稳定业务 ID，不使用 Neo4j 内部 ID。

### 2.5 `assistant_traceability_service.py`

职责：

- 追溯服务入口。
- 接收已生成的 `AnswerPackage` 和中间阶段记录，写入 `TraceStorePort`。
- 提供只读 `get_trace()`、`get_claim_trace()`。
- 存储不可用时返回 trace warning，不把答案本身标记为失败。

### 2.6 `assistant_feedback_models.py`

职责：

- 定义反馈 action、状态、权限意图、审计事件和处理结果。

建议稳定枚举：

```text
FeedbackAction = confirm | reject | correct | request_review
FeedbackStatus = received | validated | recorded | review_required | accepted | rejected | unresolved | forbidden | invalid
FeedbackPermission = read_trace | record_feedback | request_candidate_review | promote_formal_relation
```

### 2.7 `assistant_feedback_store.py`

职责：

- 定义 `FeedbackStorePort`。
- 提供 append-only `InMemoryFeedbackStore`。
- 保存 `FeedbackEvent`、状态迁移、审计事件。

### 2.8 `assistant_feedback_permissions.py`

职责：

- 根据 actor、action、request/claim 上下文和请求授权判断是否允许记录反馈、发起候选审核或触发任何下游写操作。
- 默认 fail closed。

### 2.9 `assistant_feedback_state_machine.py`

职责：

- 管理 feedback 状态迁移。
- 防止非法跳转，如 `received -> accepted`、`confirm -> formal promotion`。

### 2.10 `assistant_candidate_review_adapter.py`

职责：

- 仅处理 `request_review`。
- 从 `ClaimTrace` 中找到候选关系集合、candidate IDs、page_id、rule_version、evidence refs。
- 构造 `CandidateReviewRequest` 并调用注入的 `CandidateReviewService`。
- 不直接调用 repository，不拼 Cypher，不创建 Neo4j driver。

### 2.11 `assistant_feedback_service.py`

职责：

- 反馈服务入口。
- 校验 feedback event、读取 trace/claim trace、检查权限、执行状态机、写入反馈审计。
- 对 `request_review` 调用 `CandidateReviewAdapter`。
- 对 `confirm/reject/correct` 只记录事件和审计，不产生正式事实。

## 3. 修改模块

### 3.1 `assistant_models.py`

可选修改：

- 保留薄版 `TraceRecord`、`FeedbackEvent` 或从新模型兼容导出。
- 新增 reason code 时必须稳定枚举，不破坏旧值。

### 3.2 `drawing_assistant_service.py`

第 7 次可选修改：

- 构造函数注入 `traceability_service=None`。
- `answer()` 成功生成 `AnswerPackage` 后尝试记录 trace。
- trace 存储失败只追加 warning 或返回 trace write result，不改变 answer 的业务状态。
- 服务仍必须拒绝 `request.allow_write_back=True`。

### 3.3 `drawing_assistant_factory.py`

可选修改：

- 支持装配 traceability service 的内存默认实现。
- 默认行为必须与未注入时兼容。

### 3.4 `candidate_review.py`

不建议修改核心审核规则。第 8 次只通过注入服务调用其公开 `review_candidate_group()`。

### 3.5 `scripts/drawing_assistant.py`

本需求不默认修改。若未来新增反馈 CLI，应使用独立显式命令，不给现有 answer 命令添加隐式 write-back。

## 4. 数据模型变化

### 4.1 Neo4j schema

本需求首版不新增 Neo4j schema。

不新增节点、关系、索引、约束或迁移脚本；不把 `TraceRecord`、`FeedbackEvent`、answer、claim 或用户修正默认写入业务图谱。正式关系提升仍仅能通过已有候选审核和受控 repository 路径发生。

### 4.2 产品运行审计模型

`TraceRecord` 至少包含：

```text
request_id
question
question_type
scope
module_events
retrieval_calls
semantic_gap_decision
recognition_run_ids
evidence_ids
claim_ids
answer_status
model_profiles
prompt_versions
cache_status
cost_summary
latency_summary
created_at
```

`ClaimTrace` 至少包含：

```text
claim_id
request_id
claim_status
statement
fact_kinds
evidence_ids
citation_ids
page_ids
block_ids
element_ids
bboxes
recognition_run_ids
candidate_group_ids
review_run_ids
payload_refs
warnings
```

`FeedbackEvent` 至少包含：

```text
feedback_id
request_id
claim_id
action
reason
correction
user_id
created_at
```

`FeedbackResult` 至少包含：

```text
feedback_id
status
affected_claim_ids
candidate_review_request_id
candidate_review_result
new_evidence_request
warnings
audit_event_ids
```

## 5. API 设计

本设计指 Python 内部应用 API，不新增外部 HTTP/MCP 接口。

### 5.1 TraceabilityService

```text
record_answer_trace(inputs...) -> TraceWriteResult
get_trace(request_id, actor=None) -> TraceQueryResult
get_claim_trace(claim_id, actor=None) -> ClaimTrace | None
```

要求：

- `record_answer_trace()` 可在只读问答后调用，但它只写产品运行审计 store，不写 Neo4j。
- `get_trace()` 与 `get_claim_trace()` 是只读操作。
- trace query 输出必须脱敏。

### 5.2 FeedbackService

```text
submit_feedback(event, actor, policy) -> FeedbackResult
get_feedback(feedback_id, actor) -> FeedbackResult | None
list_feedback_for_request(request_id, actor) -> tuple[FeedbackResult, ...]
```

要求：

- `confirm`：记录认可，不改变 fact_kind，不触发 formal promotion。
- `reject`：记录否认，不删除证据或历史答案。
- `correct`：保存修正文本，不把修正直接写成来源事实。
- `request_review`：仅当 claim trace 指向完整候选集合且权限允许时，调用 `CandidateReviewService`。

### 5.3 CandidateReviewAdapter

```text
build_review_request(feedback_event, claim_trace) -> CandidateReviewRequest
request_review(feedback_event, claim_trace) -> CandidateReviewResult
```

要求：

- 只支持候选关系 claim。
- candidate 集合不完整、跨页、方向不明确、缺少 evidence refs 时返回 unresolved/invalid，不调用 repository。
- 仅通过注入的 `CandidateReviewService.review_candidate_group()`。

## 6. 异常处理

| 异常 | 处理 |
|---|---|
| trace store 不可用 | 答案仍返回，记录 `trace_unavailable` warning |
| request_id 不存在 | trace 查询返回 not_found |
| claim_id 不存在 | feedback 拒绝，状态 `invalid` 或 not_found |
| feedback action 非法 | 状态 `invalid`，不写业务操作 |
| 权限不足 | 状态 `forbidden`，可记录拒绝审计 |
| correction 缺少依据 | 只记录反馈，不生成正式事实 |
| candidate 集合不完整 | `request_review` 进入 unresolved，不提升 formal |
| CandidateReviewService 不可用 | feedback 保持 review_required/unresolved，可重试 |
| store 写入失败 | fail closed，不调用后续审核 |

所有错误消息必须脱敏，不包含 key、Authorization、密码、Neo4j URI、Cypher、绝对路径、完整 payload、完整 prompt、provider 原文或 traceback。

## 7. 安全方案

### 7.1 只读与可写边界

只读模块：

- `QuestionUnderstandingService`
- `GraphRetrievalService`
- `SemanticGapDecisionService`
- `AnswerGenerationService`
- `TraceabilityService.get_trace()`
- `TraceabilityService.get_claim_trace()`
- `ClaimTraceProjector`

产品审计可写模块：

- `TraceabilityService.record_answer_trace()` 只写 `TraceStorePort`。
- `FeedbackService.submit_feedback()` 只写 `FeedbackStorePort` 和审计事件。

受控业务写入模块：

- `CandidateReviewService` 在其既有硬规则通过且 repository 注入时，才可能更新候选审核状态并提升正式关系。
- `SemanticRecognitionService` 在既有 `write_back=true` 授权链路下才可能写语义证据；本需求不新增该写回入口。

写回授权拒绝或控制位置：

- `DrawingAssistantService` 继续拒绝 `AssistantRequest.allow_write_back=True`。
- `FeedbackPermissionPolicy` 默认拒绝没有权限的 feedback 写入、candidate review request 和 formal promotion。
- `FeedbackStateMachine` 阻止 confirm/correct/reject 直接进入 formal promotion。
- `CandidateReviewAdapter` 只构造审核请求，不直接写 repository。
- `CandidateReviewService` 继续执行候选完整性、同页范围、方向和硬规则校验。

### 7.2 fact_kind 保护

- `source_fact` 只能来自来源事实读取路径。
- `semantic_observation`/`semantic_interpretation` 只能作为语义证据。
- `candidate_relation` 与 `matched_candidate` 永远不等于 `formal_relation`。
- 用户 `confirm` 不改变任何 evidence 的 `fact_kind`。
- 用户 `correct` 不生成来源事实；只能形成反馈事件或待审核新证据请求。
- 只有已存在候选集合经 `CandidateReviewService` accepted 且硬规则通过，才可能形成正式关系。

### 7.3 审计与隐私

- 审计事件 append-only。
- `user_id` 使用业务身份引用，不保存多余个人信息。
- 对外 trace 默认只暴露 claim 所需最小字段。
- 成本、延迟、内部诊断按权限输出。
- 所有 trace/feedback 输出复用脱敏策略。

## 8. 依赖方向

允许：

```text
assistant_traceability_service -> assistant_trace_store / assistant_trace_builder / assistant_claim_trace
assistant_feedback_service -> assistant_feedback_store / assistant_feedback_permissions / assistant_feedback_state_machine / assistant_candidate_review_adapter
assistant_candidate_review_adapter -> candidate_review.CandidateReviewService
drawing_assistant_service -> optional assistant_traceability_service
```

禁止：

```text
trace/feedback service -> Neo4j driver / session / transaction
trace/feedback service -> RelationRepository / SemanticNeo4jRepository
trace/feedback service -> Cypher 字符串
adapter -> repository / Cypher / driver
feedback confirm/correct -> formal relation write
```

## 9. 与现有模块的兼容策略

- 现有 QA CLI/HTTP/MCP 不接入反馈写入，不改变只读语义。
- `DrawingGraphToolFacade` 不需要为 trace store 扩展写路径。
- `DrawingAssistantService` 的 trace 接入是可选依赖，未注入时现有测试和行为不变。
- `assistant_models.py` 中已有 `TraceRecord`/`FeedbackEvent` 可通过兼容导出保留。
- `CandidateReviewService` 只作为注入下游；其硬规则与 repository 写入路径保持原样。
- 现有 01-06 模块不新增 Neo4j 查询、模型调用或业务写回。

## 10. 验证方案

### 10.1 第 7 次追溯闭环

```powershell
python -m unittest tests.test_assistant_trace_models tests.test_assistant_trace_store tests.test_assistant_trace_builder tests.test_assistant_claim_trace tests.test_assistant_traceability_service tests.test_drawing_assistant_service -v
```

验证点：

- TraceRecord 字段完整、不可变或等价安全。
- store append/read 稳定、不可静默覆盖。
- claim trace 能从 AnswerPackage/citation/evidence 中回查稳定 ID。
- trace 存储失败不把答案本身改成失败。
- 不导入 Neo4j driver、repository、Cypher、HTTP/MCP adapter 或 CLI。

### 10.2 第 8 次反馈闭环

```powershell
python -m unittest tests.test_assistant_feedback_models tests.test_assistant_feedback_store tests.test_assistant_feedback_permissions tests.test_assistant_feedback_state_machine tests.test_assistant_candidate_review_adapter tests.test_assistant_feedback_service tests.test_assistant_feedback_boundaries tests.test_candidate_review_service -v
```

验证点：

- 四类 action 状态机稳定。
- 权限不足 fail closed。
- confirm/reject/correct 不提升正式事实。
- request_review 只通过 `CandidateReviewService`。
- candidate 不完整或硬规则失败时 unresolved/rejected。
- 审计 append-only，不覆盖旧事件。
- 脱敏不泄漏 secret、URI、Cypher、路径、payload、prompt、traceback。

### 10.3 全量离线回归

```powershell
python -m unittest discover tests -v
```

该命令不应被描述为 live Neo4j 验证。若 `tests/integration/` 因未配置 `NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD` 而 skipped，必须报告为 live Neo4j 未验证。

### 10.4 live 验证

首版不新增 Neo4j schema，因此不要求新增 trace/feedback live Neo4j 验证。若后续新增 Neo4j 持久化 store，则必须另立 migration、隔离测试库和 live 验收。

