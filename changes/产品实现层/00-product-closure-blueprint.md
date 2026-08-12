# 智能图纸助手产品闭环蓝图

**文档状态：** 已确认设计规格  
**日期：** 2026-08-11  
**适用范围：** 图块图谱构建项目从自然语言提问到可追溯回答的完整产品闭环

## 1. 产品目标

最终产品应允许用户用自然语言询问页面、图块、标注元素、构件语义和图纸关系。系统先复用图谱中的确定性事实与已有语义证据，只在证据不足时按需调用 Qwen 多模态模型，并将图谱事实、模型结果、候选关系和正式关系分层融合，输出机器可读 JSON 与简短中文回答。

产品不是一组需要用户理解底层命令的工具。用户不应手工选择 facade 方法、预先判断是否需要识别，也不应负责拼接多个查询结果。

## 2. 当前架构基线

当前工作区已经具备以下可复用能力：

- XAnyLabeling JSON/PNG 到 Neo4j 的来源事实导入与稳定业务 ID。
- 表格标题、图块标题、基础信息、注释、断面标记等离线派生关系和候选关系。
- `DrawingGraphToolFacade` 统一查询、按需识别、语义查询和候选审核边界。
- 图谱外 `RecognitionRun`，图谱内 `TextObservation` 与三类 `Interpretation`。
- 语义缓存键、不可变 payload、断面匹配及候选/正式关系分层。
- `DrawingGraphQAService`、QA CLI、只读 HTTP API 和本地 STDIO MCP adapter。
- 可选 Qwen/DashScope 多模态客户端及 `recognize-page-semantics` 受控入口；默认 `write_back=false`。

当前仍缺少的是产品级自动编排：自然语言问题理解、证据需求规划、语义缺口判断、自动识别触发、跨来源证据融合、生成式回答和用户反馈闭环尚未串成一个稳定服务。

## 3. 目标架构

新增产品级 `DrawingAssistantService` 作为七个模块的编排器。它位于 CLI、HTTP、MCP、Web UI 等 adapter 内侧，位于 `DrawingGraphToolFacade` 外侧。

```text
CLI / HTTP / MCP / Web UI
  -> DrawingAssistantService
       -> 01 QuestionUnderstandingService
       -> 02 GraphRetrievalService
       -> 03 SemanticGapDecisionService
       -> 04 MultimodalRecognitionService
       -> 05 EvidenceFusionService
       -> 06 AnswerGenerationService
       -> 07 TraceabilityFeedbackService
  -> DrawingGraphToolFacade
  -> ports / services / controlled repositories
  -> Neo4j / run log / payload store / Qwen
```

现有 `DrawingGraphQAService` 保留，用于兼容六类确定性结构化问题。它不承担完整自然语言闭环，也不被删除或绕过。

## 4. 端到端数据流

```text
AssistantRequest
  -> QuestionUnderstandingResult
  -> RetrievalBundle
  -> SemanticGapDecision
  -> [必要时] RecognitionResult
  -> EvidenceBundle
  -> AnswerPackage
  -> TraceRecord / FeedbackEvent
```

标准执行顺序：

1. 理解用户问题，识别问题类型、scope 和所需证据。
2. 只读检索图谱中已有事实、关系、语义证据和缓存状态。
3. 判断证据是否足够、过期、冲突或缺失。
4. 仅在必要且允许时调用 Qwen，目标精确到页面、图块或元素。
5. 融合已有证据与本次临时识别结果，保留来源和事实等级。
6. 生成结构化答案和中文回答，每条结论绑定证据引用。
7. 保存追溯记录；用户反馈进入受控审核流程，不直接篡改事实。

## 5. 公共请求与输出

所有模块输入和输出都必须携带同一个 `request_id`；多意图拆分产生的子请求另带 `subrequest_id`，但不得丢失父请求关联。模块不得通过进程全局变量或隐式上下文关联一次问答。

### 5.1 `AssistantRequest`

| 字段 | 含义 | 默认值 |
|---|---|---|
| `request_id` | 单次请求稳定 ID | 系统生成 |
| `question` | 用户自然语言问题 | 必填 |
| `conversation_context` | 可选对话上下文 | 空 |
| `scope_hint` | `page_id`、`block_id`、`element_id` 等提示 | 空 |
| `language` | 回答语言 | `zh-CN` |
| `allow_recognition` | 是否允许按需调用模型 | `true` |
| `allow_write_back` | 是否允许持久化语义结果 | `false` |
| `answer_format` | 输出格式 | `json_and_text` |

`allow_recognition=true` 只授权模型调用，不等于授权写数据库。

### 5.2 `AnswerPackage`

| 字段 | 含义 |
|---|---|
| `machine_answer` | 权威机器可读答案 |
| `text_answer` | 简短中文答案 |
| `status` | `answered`、`partial`、`clarification_required`、`unsupported`、`recognition_failed` |
| `claims` | 带证据引用的结论集合 |
| `citations` | page/block/element、bbox、运行和证据引用 |
| `warnings` | 不确定性、降级和验证边界 |
| `unsupported_parts` | 无法回答的子问题 |
| `recognition_run_ids` | 本次涉及的识别运行 |
| `follow_up_actions` | 澄清、复核或反馈建议 |

## 6. 永久事实分层

所有模块必须保留以下分类：

| `fact_kind` | 含义 | 能否被模型直接生成 |
|---|---|---|
| `source_fact` | 标注数据及导入追溯事实 | 否 |
| `derived_relation` | 规则生成的正式派生关系 | 否 |
| `semantic_observation` | 模型对图像内容的观察 | 是 |
| `semantic_interpretation` | 模型基于观察形成的解释 | 是 |
| `candidate_relation` | 尚待审核的关系候选 | 是，但仍是候选 |
| `formal_relation` | 经规则和审核确认的正式关系 | 否，必须受控提升 |
| `diagnostic` | 运行、缓存、验证和缺口信息 | 系统生成 |

模型输出不得覆盖来源事实；`matched_candidate` 不等于正式关系；用户确认也不直接等于正式关系。

## 7. 核心策略

- 图谱优先：先检索已有证据，再考虑模型调用。
- 最小识别：只识别回答当前问题所需的最小目标集合。
- 缓存优先：有效缓存直接复用；缓存命中不创建新识别运行。
- 默认 dry-run：`allow_write_back=false` 时，识别结果仅用于本次回答。
- 失败可降级：Qwen 失败时返回已有图谱证据和明确缺口，不返回伪成功。
- 证据约束回答：每条 claim 必须至少有一个可追溯证据引用。
- 验证分层：单元测试、离线 Qwen 测试、live DashScope、live Neo4j 分别报告。

## 8. 模块文档索引

1. [问题理解模块](./01-question-understanding.md)
2. [图谱检索模块](./02-graph-retrieval.md)
3. [语义缺口判断模块](./03-semantic-gap-decision.md)
4. [多模态识别模块](./04-multimodal-recognition.md)
5. [证据融合与缓存模块](./05-evidence-fusion-and-cache.md)
6. [答案生成模块](./06-answer-generation.md)
7. [追溯与反馈模块](./07-traceability-and-feedback.md)

## 9. 实施顺序

代码实施建议按依赖顺序进行，而不是机械按文档编号：

1. 公共 DTO、状态枚举和序列化契约。
2. 图谱检索模块。
3. 问题理解模块。
4. 语义缺口判断模块。
5. 多模态识别模块。
6. 证据融合与缓存模块。
7. 答案生成模块。
8. 追溯与反馈模块。
9. `DrawingAssistantService` 端到端编排。
10. CLI、HTTP、MCP 和 Web UI adapter。

## 10. 产品级验收

- 用户只提供自然语言问题和必要上下文即可获得回答。
- 系统自动决定是否需要调用 Qwen。
- 已有有效语义证据优先复用，不重复付费识别。
- Qwen 失败仍返回已有事实、失败状态和可执行建议。
- 每条结论均可追溯至页面、图块、元素、bbox 或语义证据。
- `allow_write_back=false` 下不产生持久化副作用。
- 候选关系从不被误报为正式关系。
- 各模块可独立测试并可分别进入实施计划。
