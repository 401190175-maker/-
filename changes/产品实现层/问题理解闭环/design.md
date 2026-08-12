# 问题理解闭环 Design

**文档状态：** 技术设计  
**日期：** 2026-08-12  
**前置文档：** `proposal.md`、`Feature_Analysis_Report.md`  
**设计原则：** 禁止无意义重构；优先复用已有产品公共合同、通用检索闭环、QA 兼容映射和 facade 边界。

## 0. 实现状态（Task 1-23）

本阶段实施任务已按 `tasks.md` 完成并通过专项测试：

- 公共合同补充：`QuestionType`（12 个稳定值）、`ReasonCode` 新增 5 个原因码、`ClarificationItem`、`QuestionUnderstandingEvent`。
- 已实现模块：`assistant_question_text.py`、`assistant_scope_resolution.py`、`assistant_question_rules.py`、`assistant_intent_splitter.py`、`assistant_evidence_templates.py`、`assistant_clarification.py`、`assistant_question_trace.py`、`assistant_question_llm.py`（协议 + fake + 输出校验）、`assistant_question_understanding.py`。
- 已实现闭环：`AssistantRequest -> QuestionUnderstandingService -> QuestionUnderstandingResult -> GraphRetrievalService -> RetrievalBundle`；clarification/unsupported 不进入检索。
- QA 兼容映射：`diagnostic_status` 映射为产品层 `drawing_diagnostic`，其余五类固定 QA 与 `QuestionType` 值一致；`DrawingGraphQAService` 无新增产品层依赖。
- 边界保持：`write_back=false` 默认且不受问题文本影响；问题理解模块不访问 Neo4j、不调用 `DrawingGraphToolFacade`、不创建 RecognitionRun、不写数据库；不默认真实文本模型调用。
- 验证：专项单元/合同测试全部通过；未运行 live Neo4j 或 live DashScope 时，不报告 live 验证通过。

## 1. 系统架构变化

当前产品实现层已经具备公共 DTO 与通用图谱检索闭环：

```text
QuestionUnderstandingResult
  -> GraphRetrievalService
       -> RetrievalPlanner
       -> RetrievalExecutor
       -> RetrievalBundleBuilder
  -> DrawingGraphToolFacade
```

本阶段只补齐产品入口的 01 问题理解运行时，不改变已有 QA、HTTP、MCP、facade、repository 和 Neo4j 依赖方向。

新增后的产品层局部链路为：

```text
AssistantRequest
  -> QuestionUnderstandingService
       -> QuestionTextNormalizer
       -> ScopeResolver
       -> RuleQuestionRouter
       -> IntentSplitter
       -> EvidenceRequirementFactory
       -> ClarificationPolicy
       -> QuestionUnderstandingTraceBuilder
  -> QuestionUnderstandingResult
  -> GraphRetrievalService
  -> RetrievalBundle
```

依赖方向固定为：

```text
assistant_question_understanding
  -> assistant_models
  -> assistant_question_rules
  -> assistant_scope_resolution
  -> assistant_evidence_templates
  -> assistant_clarification
  -> assistant_qa_mapping
```

关键架构边界：

- 问题理解模块只处理自然语言、scope、问题类型、证据需求和澄清，不访问 Neo4j。
- 问题理解模块不调用 `DrawingGraphToolFacade`。对象是否存在、证据是否完整由 `GraphRetrievalService` 和后续模块判断。
- `DrawingGraphQAService` 保持六类固定 QA 的兼容层，不改造成完整自然语言产品服务。
- `GraphRetrievalService` 继续作为通用只读检索入口，不加入自然语言解析逻辑。
- 不新增产品级 HTTP/MCP/CLI/Web adapter；后续 adapter 可在外层调用 `QuestionUnderstandingService`。
- 不新增真实文本模型调用；仅预留可注入协议和 fake 实现，默认规则优先。
- 不改 Neo4j schema，不新增图谱节点或关系。

首阶段执行分支：

```text
明确且支持的问题
  -> QuestionUnderstandingResult(status-like outcome via question_type/ambiguities/unsupported_parts)
  -> 可交给 GraphRetrievalService

缺 scope、scope 冲突或指代不唯一
  -> QuestionUnderstandingResult(question_type="clarification_required")
  -> required_evidence 为空或仅保留可安全表达的需求
  -> 不进入检索

不支持或低置信度问题
  -> QuestionUnderstandingResult(question_type="unknown_or_unsupported")
  -> unsupported_parts / ambiguities 说明原因
```

## 2. 新增模块

### 2.1 `assistant_question_understanding.py`

核心服务模块，提供 `QuestionUnderstandingService`。

职责：

- 接收 `AssistantRequest`。
- 编排文本规范化、scope 解析、问题路由、多意图拆分、证据需求生成和澄清策略。
- 输出 `QuestionUnderstandingResult`。
- 保证问题文本不能改变 `allow_write_back`。
- 不访问 facade、Neo4j、Qwen、HTTP、MCP 或 CLI 脚本。

主要对象：

```text
QuestionUnderstandingService
  understand(request: AssistantRequest) -> QuestionUnderstandingResult
```

### 2.2 `assistant_question_rules.py`

规则路由模块。

职责：

- 根据规范化后的中文问题和稳定业务 ID 识别问题类型。
- 覆盖高频、可解释、可测试的规则。
- 保持现有六类 QA 兼容问题的语义一致。
- 对不确定或多命中结果返回候选路由结果，不直接猜测。

首版规则类型：

- `page_summary`
- `block_relations`
- `block_semantic_identification`
- `element_text_or_meaning`
- `candidate_relations`
- `section_matches`
- `table_caption_status`
- `drawing_diagnostic`
- `source_trace`
- `comparison`
- `unknown_or_unsupported`

### 2.3 `assistant_scope_resolution.py`

Scope 解析与指代消解模块。

职责：

- 从问题文本中提取稳定业务 ID。
- 合并 `AssistantRequest.scope_hint`。
- 使用有限 `conversation_context` 做指代消解。
- 在多个 scope 冲突时保留冲突信息，不擅自选择。

边界：

- 不查询对象是否存在。
- 不接受 Neo4j 内部 ID、Cypher 或自由查询语句。
- “这个图块”“这张图”等指代只有在上下文唯一时才解析。

### 2.4 `assistant_evidence_templates.py`

证据需求模板模块。

职责：

- 将 `question_type + scope` 映射为 `EvidenceRequirement`。
- 复用现有 `EvidenceType`，不重复定义检索类型。
- 集中维护不同问题类型需要的来源事实、派生关系、语义观察、语义解释、候选关系和正式关系需求。

示例映射：

| question_type | required_evidence |
|---|---|
| `page_summary` | `PAGE_SOURCE_FACTS`，可选 `TEXT_OBSERVATIONS` / `STRUCTURED_INTERPRETATIONS` |
| `block_relations` | `BLOCK_TRACE`、`BLOCK_RELATIONS` |
| `block_semantic_identification` | `BLOCK_TRACE`、`STRUCTURED_INTERPRETATIONS`，允许模型生成语义解释 |
| `element_text_or_meaning` | `PAGE_SOURCE_FACTS`、`TEXT_OBSERVATIONS` |
| `candidate_relations` | `CANDIDATE_RELATIONS` |
| `section_matches` | `SECTION_MATCHES`、必要时 `TEXT_OBSERVATIONS` |
| `source_trace` | 与 claim/page/block/element 对应的来源事实或追溯证据 |

### 2.5 `assistant_clarification.py`

澄清策略模块。

职责：

- 根据 scope 缺失、scope 冲突、指代不唯一、多意图歧义和低置信度生成结构化澄清项。
- 将澄清原因写入 `ambiguities` 或新增澄清 DTO。
- 保证澄清场景不进入后续检索或识别。

首版澄清原因：

- `scope_missing`
- `scope_conflict`
- `ambiguous_reference`
- `ambiguous_question_type`
- `multi_intent_ambiguous`
- `unsupported_question`

### 2.6 `assistant_question_trace.py`

问题理解追溯事件模块。

职责：

- 构造轻量问题理解事件，供 `TraceRecord.module_events` 承载。
- 记录规则命中、scope 来源、歧义、澄清原因、证据需求来源和可选模型回退状态。
- 只生成数据对象，不持久化。

### 2.7 `assistant_question_llm.py`（预留）

受约束文本模型适配口。

职责：

- 定义 `QuestionUnderstandingModelClient` 协议和 fake 实现。
- 只在规则无法唯一分类时可选调用。
- 模型输出必须是受约束结构化结果，并经本地校验后才可进入 `QuestionUnderstandingResult`。

首阶段默认不配置真实模型，不新增外部依赖，不读取 API key。

## 3. 修改模块

### 3.1 `assistant_models.py`

尽量复用现有 DTO。只在确有必要时增加最小合同：

- `QuestionType` 或稳定问题类型常量，避免散落字符串。
- `ClarificationPrompt` 或 `ClarificationItem`，用于结构化表达需要用户补充的信息。
- `QuestionUnderstandingEvent`，用于 `TraceRecord.module_events`。
- 补充 `ReasonCode`：`AMBIGUOUS_REFERENCE`、`AMBIGUOUS_QUESTION_TYPE`、`MULTI_INTENT_AMBIGUOUS`、`UNSUPPORTED_QUESTION`、`MODEL_OUTPUT_INVALID`。

不修改：

- `AssistantRequest.allow_write_back` 默认值。
- `QuestionUnderstandingResult` 的核心消费结构。
- `EvidenceRequirement` 的检索语义。
- 已有 `EvidenceType` 的含义。

### 3.2 `assistant_qa_mapping.py`

保持现有单向兼容映射。

可补充：

- 将固定 QA 的问题类型常量与新问题类型枚举对齐。
- 将已有六类 QA 映射作为规则路由测试样例。

不允许：

- 让 `DrawingGraphQAService` 依赖产品层问题理解服务。
- 修改现有 QAService 行为。

### 3.3 `assistant_retrieval_planner.py`

原则上不需要重构。

可能补充：

- 接收新增证据需求时的 unsupported warning。
- 对澄清类 `question_type` 或空 `required_evidence` 保持稳定返回，不误触发 facade 调用。

不允许：

- 在 planner 中解析自然语言。
- 在 planner 中调用模型或 facade 之外的能力。

### 3.4 文档与测试

实施后同步：

- `architecture.md`
- `Module.md`
- `README.md`
- `changes/产品实现层/问题理解闭环/*.md`

新增测试建议：

- `tests/test_assistant_question_understanding.py`
- `tests/test_assistant_question_rules.py`
- `tests/test_assistant_scope_resolution.py`
- `tests/test_assistant_evidence_templates.py`
- `tests/test_assistant_clarification.py`
- `tests/test_assistant_question_boundaries.py`
- `tests/test_assistant_question_docs.py`

## 4. 数据模型变化

本阶段不改变 Neo4j 数据模型，不新增节点、关系、约束或索引。

数据模型变化仅限 Python 产品公共合同与运行时 DTO。

### 4.1 复用现有模型

继续复用：

- `AssistantRequest`
- `AssistantScope`
- `EvidenceRequirement`
- `AssistantSubrequest`
- `QuestionUnderstandingResult`
- `EvidenceType`
- `ReasonCode`
- `FreshnessPolicy`
- `TraceRecord`
- `FeedbackEvent`

### 4.2 建议新增 `QuestionType`

用途：稳定表达产品层问题类型，减少自由字符串漂移。

建议枚举值：

```text
page_summary
block_relations
block_semantic_identification
element_text_or_meaning
candidate_relations
section_matches
table_caption_status
drawing_diagnostic
source_trace
comparison
clarification_required
unknown_or_unsupported
```

兼容策略：

- `QuestionUnderstandingResult.question_type` 可以继续保存字符串值。
- 构造时可由服务内部使用枚举，再输出 `.value`。
- 不强制一次性重写已有 `assistant_qa_mapping.py`。

### 4.3 建议新增 `ClarificationItem`

用途：结构化表达“需要用户补充什么”。

字段建议：

```text
clarification_id
reason_code
target_field
message
allowed_scope_types
candidate_refs
required
```

说明：

- `candidate_refs` 只能使用稳定业务 ID 或用户上下文引用，不放 Neo4j 内部 ID。
- `message` 只作为人类可读提示，不作为下游机器判断的唯一依据。

### 4.4 建议新增 `QuestionUnderstandingEvent`

用途：追溯问题理解阶段的决策。

字段建议：

```text
event_id
request_id
stage
rule_id
question_type
scope_source
confidence
reason_codes
details
```

约束：

- `details` 不保存敏感密钥、Cypher、底层异常 traceback 或完整外部模型响应。
- 如果后续接入文本模型，仅记录模型 profile、prompt version、校验状态和脱敏错误类别。

### 4.5 证据需求模板约束

每个 `EvidenceRequirement` 必须满足：

- `requirement_id` 稳定、可预测。
- `evidence_type` 来自 `EvidenceType`。
- `target_scope` 来自解析后的 `AssistantScope`。
- `allow_model_generation` 只表达“后续模块可用模型补证据”，不代表本模块调用模型。
- `include_payload` 默认 false，只有明确需要完整语义 payload 时才 true。

## 5. API 设计

本阶段 API 是 Python 应用层 API，不新增 HTTP/MCP/CLI 对外协议。

### 5.1 `QuestionUnderstandingService`

```text
QuestionUnderstandingService(
    normalizer: QuestionTextNormalizer | None = None,
    scope_resolver: ScopeResolver | None = None,
    router: RuleQuestionRouter | None = None,
    evidence_factory: EvidenceRequirementFactory | None = None,
    clarification_policy: ClarificationPolicy | None = None,
    trace_builder: QuestionUnderstandingTraceBuilder | None = None,
    model_client: QuestionUnderstandingModelClient | None = None,
)

understand(request: AssistantRequest) -> QuestionUnderstandingResult
```

行为：

1. 校验 `AssistantRequest` 已由 DTO 完成基本字段校验。
2. 规范化问题文本和语言。
3. 提取稳定业务 ID。
4. 合并 `scope_hint` 与有限上下文。
5. 执行规则路由。
6. 必要时拆分多意图。
7. 根据问题类型生成证据需求。
8. 对缺 scope、冲突和低置信度应用澄清策略。
9. 输出 `QuestionUnderstandingResult`。

### 5.2 `ScopeResolver`

```text
resolve(
    question: str,
    scope_hint: AssistantScope | None,
    conversation_context: str | None,
) -> ScopeResolutionResult
```

`ScopeResolutionResult` 字段建议：

```text
scope
scope_sources
conflicts
ambiguities
extracted_ids
```

### 5.3 `RuleQuestionRouter`

```text
route(
    question: str,
    scope: AssistantScope | None,
) -> QuestionRouteResult
```

`QuestionRouteResult` 字段建议：

```text
question_type
confidence
matched_rules
unsupported_parts
ambiguities
```

规则命中策略：

- 单个强规则命中：直接返回问题类型。
- 多个同等级规则命中：返回歧义。
- 无规则命中：返回 `unknown_or_unsupported`。

### 5.4 `IntentSplitter`

```text
split(
    question: str,
    route_result: QuestionRouteResult,
    scope: AssistantScope | None,
) -> tuple[AssistantSubrequest, ...]
```

约束：

- 多意图拆分只在连接词、列举式问题或明确多个目标时执行。
- 每个子请求都有稳定 `subrequest_id`。
- 拆分失败时返回澄清，不随意丢弃子问题。

### 5.5 `EvidenceRequirementFactory`

```text
build(
    question_type: str,
    scope: AssistantScope | None,
    request: AssistantRequest,
) -> tuple[EvidenceRequirement, ...]
```

约束：

- 不访问图谱。
- 不调用模型。
- 不修改请求权限。
- 对 scope 不足的问题返回空需求或最小安全需求，并交给澄清策略处理。

### 5.6 `ClarificationPolicy`

```text
evaluate(
    request: AssistantRequest,
    route_result: QuestionRouteResult,
    scope_result: ScopeResolutionResult,
    requirements: tuple[EvidenceRequirement, ...],
) -> ClarificationDecision
```

`ClarificationDecision` 字段建议：

```text
required
items
reason_codes
```

### 5.7 与现有检索 API 的衔接

调用方可按以下方式组合：

```text
question_result = question_understanding_service.understand(request)

if question_result.question_type not in ("clarification_required", "unknown_or_unsupported"):
    retrieval_bundle = graph_retrieval_service.retrieve(question_result)
```

本阶段不新增端到端 `DrawingAssistantService`；该组合可先在测试中验证。

## 6. 异常处理

问题理解模块应优先返回结构化结果，只有非法输入或编程错误才抛出异常。

| 场景 | 处理 |
|---|---|
| `question` 为空 | 由 `AssistantRequest` 校验拒绝；服务不继续处理。 |
| `scope_hint` 类型错误 | 由 `AssistantRequest` 校验拒绝。 |
| 问题类型不支持 | 返回 `question_type="unknown_or_unsupported"`，填充 `unsupported_parts`。 |
| 缺少必要 scope | 返回 `question_type="clarification_required"`，填充澄清项和 `scope_missing`。 |
| scope 冲突 | 返回澄清项，原因码为 `scope_conflict`。 |
| 指代不唯一 | 返回澄清项，原因码为 `ambiguous_reference`。 |
| 多意图拆分不确定 | 返回澄清项或保守 unsupported，不丢弃子问题。 |
| 多个规则同等级命中 | 返回 `ambiguous_question_type`，不静默选择。 |
| 证据需求模板缺失 | 返回 `unknown_or_unsupported` 或内部 warning，测试应覆盖。 |
| 可选文本模型不可用 | 回退规则结果；无规则结果则 unsupported 或澄清。 |
| 可选文本模型输出非法 | 丢弃模型结果，记录 `model_output_invalid`，回退规则或 unsupported。 |

异常脱敏：

- 不输出底层 traceback 给用户可见字段。
- 不保留 API key、Authorization header、Neo4j URI 密码、Cypher 或本地敏感路径。
- 规则错误应暴露为稳定 reason code，而不是自由文本堆栈。

降级原则：

- 能确定 scope 和问题类型时，输出可检索的 `QuestionUnderstandingResult`。
- 不能确定时，优先澄清。
- 不支持时，明确 unsupported。
- 任一错误都不得触发写回、识别或候选提升。

## 7. 安全方案

### 7.1 只读与写回边界

- `AssistantRequest.allow_write_back` 默认保持 false。
- 问题理解模块不读取、设置或升级写回权限。
- 用户问题中出现“写入”“确认”“提升为正式”等语句，不得导致 `allow_write_back=true`。
- 本模块不调用 `recognize_page_semantics()`、`review_candidate_relation()` 或任何写回能力。

### 7.2 图谱访问边界

- 不创建 Neo4j driver。
- 不创建 session、transaction。
- 不拼写或执行 Cypher。
- 不导入 repository 写回模块。
- 不直接调用 `DrawingGraphToolFacade`。
- 不调用 CLI 脚本或 HTTP/MCP adapter 作为子进程。

### 7.3 输入安全

- `scope_hint` 和文本中提取的 ID 只接受稳定业务 ID 字符串。
- 拒绝或忽略 Neo4j 内部 ID、Cypher 片段、驱动连接信息、文件路径注入和 secret 字段。
- `conversation_context` 只用于指代消解，不覆盖本轮明确 scope。
- 对超长问题和上下文设置长度上限，超限返回稳定错误或截断 warning。

### 7.4 模型安全

首阶段不启用真实文本模型。

如后续启用：

- 模型只输出受约束 JSON。
- 模型输出必须经过枚举、scope、字段白名单和证据需求校验。
- 模型不得生成来源事实、正式关系、Cypher 或写回指令。
- 模型结果只作为问题理解候选，不作为权威图谱事实。
- API key 只从运行环境读取，不进入 DTO、日志、命令参数或输出。

### 7.5 事实分层安全

- 问题理解模块只声明所需证据，不判断证据是否真实存在。
- `candidate_relation` 不能满足 `formal_relation` 需求。
- `semantic_interpretation` 不能冒充 `source_fact`。
- `matched_candidate` 不能被当成正式图谱关系。
- 用户反馈和澄清只影响后续理解，不直接修改事实。

### 7.6 测试与边界验证

必须增加静态边界测试：

- 问题理解模块不得导入 Neo4j driver。
- 不得导入 repository、relation service、semantic write repository。
- 不得包含 Cypher 字符串或调用 CLI 脚本。
- 不得调用 `DrawingGraphToolFacade`。
- 不得修改 `allow_write_back`。

必须增加行为安全测试：

- 问题文本注入 `write_back=true` 无效。
- 问题文本包含 Cypher 不会被执行或透传为查询。
- 缺 scope 不进入检索。
- candidate/formal 需求不混淆。
- 模型非法输出不进入 `QuestionUnderstandingResult`。

## 8. 非目标与重构约束

本设计明确不做以下重构：

- 不重写 `assistant_models.py` 的既有 DTO。
- 不重写 `GraphRetrievalService`。
- 不重写 `DrawingGraphQAService`。
- 不改造现有 QA HTTP/MCP adapter。
- 不合并产品层 03-07 模块。
- 不新增数据库 schema。
- 不把问题理解模块做成 Agent 编排器。

本阶段只补齐 01 问题理解闭环，使它能稳定产出下游已经可以消费的 `QuestionUnderstandingResult`。
