# 问题理解闭环 Feature Analysis Report

**日期：** 2026-08-12  
**状态：** 新需求分析，不包含代码实现  
**需求名：** 增加问题理解闭环  
**结论摘要：** 当前架构已经支持“问题理解闭环”的基础合同、事实分层和只读检索承接，但尚不支持完整运行时闭环。推荐在现有 `assistant_models.py` 与 `GraphRetrievalService` 之上新增 `QuestionUnderstandingService`，并把澄清、纠错、路由回退和问题理解追溯作为首阶段闭环范围；不要绕过 `DrawingGraphToolFacade`，也不要把问题理解模块扩展成图谱检索、Qwen 识别或答案生成模块。

## 0. 阅读范围与路径说明

本次按用户要求读取并分析以下文档：

- `architecture.md`
- `Module.md`
- `changes/产品实现层/00-product-closure-blueprint.md`
- `changes/产品实现层/01-question-understanding.md`
- `changes/产品实现层/02-graph-retrieval.md`
- `changes/产品实现层/03-semantic-gap-decision.md`
- `changes/产品实现层/04-multimodal-recognition.md`
- `changes/产品实现层/05-evidence-fusion-and-cache.md`
- `changes/产品实现层/06-answer-generation.md`
- `changes/产品实现层/07-traceability-and-feedback.md`

用户提到的 `图块图谱构造/architecture.md` 与 `图块图谱构造/modules.md` 在当前工作区不存在；当前实际存在的是项目根目录的 `architecture.md` 与 `Module.md`。本报告以当前实际文件为准。

为确认实现状态，还只读核对了 `src/drawing_graph/assistant_*.py`、QA、facade 与相关测试索引。未修改任何 Python 源码或测试。

## 1. 当前架构是否支持？

**部分支持。**

当前架构已经具备问题理解闭环的承接基础：

- 产品公共合同已存在：`AssistantRequest`、`AssistantScope`、`EvidenceRequirement`、`AssistantSubrequest`、`QuestionUnderstandingResult`、`TraceRecord`、`FeedbackEvent` 等 DTO 已在 `assistant_models.py` 中落地。
- 通用图谱检索闭环已存在：`GraphRetrievalService` 串联 `RetrievalPlanner -> RetrievalExecutor -> RetrievalBundleBuilder`，能消费 `QuestionUnderstandingResult` 并输出 `RetrievalBundle`。
- 六类固定 QA 到产品检索需求的兼容映射已存在：`assistant_qa_mapping.py` 可把现有 `QARequest` 映射为 `QuestionUnderstandingResult`。
- 安全边界清楚：产品层检索只经 `DrawingGraphToolFacade` 白名单只读能力，默认 `write_back=false`，不调用 Qwen，不创建 `RecognitionRun`，不写 Neo4j。
- 产品级目标架构已经明确：`DrawingAssistantService` 未来应编排 01-07 七个模块，现有 QAService 保留兼容，不承担完整自然语言闭环。

但当前架构尚不支持完整问题理解运行时闭环：

- 没有独立 `QuestionUnderstandingService`。
- 没有自然语言到 `QuestionUnderstandingResult` 的稳定运行时分类、scope 解析、证据需求生成和置信度输出。
- 没有多意图拆分服务。
- 没有 clarification 状态机，也没有“缺 scope -> 追问 -> 用户补充 -> 重建 QuestionUnderstandingResult”的闭环。
- 没有问题理解失败、低置信度、模型路由回退的运行追溯。
- 没有将用户反馈用于修正问题理解规则或歧义样例的受控反馈机制。

因此，当前架构不是从零开始；它已经有合同和下游承接层，但缺少 01 模块的可执行服务与围绕该服务的澄清/反馈闭环。

## 2. 需要新增哪些模块？

建议新增模块按“最小闭环”拆分，而不是一次实现完整产品助手。

| 模块 | 建议文件 | 职责 |
|---|---|---|
| 问题理解服务 | `src/drawing_graph/assistant_question_understanding.py` | 将 `AssistantRequest` 转换为 `QuestionUnderstandingResult`。 |
| 规则路由器 | `src/drawing_graph/assistant_question_rules.py` | 对明确 ID、固定句式、现有六类 QA 兼容问题做确定性分类。 |
| 证据需求模板 | `src/drawing_graph/assistant_evidence_templates.py` | 按 `question_type` 生成 `EvidenceRequirement`，避免散落在理解逻辑中。 |
| Scope 解析与指代消解 | `src/drawing_graph/assistant_scope_resolution.py` | 合并 `scope_hint`、问题文本中的稳定 ID、对话上下文；不访问 Neo4j。 |
| 澄清策略 | `src/drawing_graph/assistant_clarification.py` | 在缺少或冲突 scope、低置信度、多意图不明确时输出可执行澄清项。 |
| 可选文本模型适配 | `src/drawing_graph/assistant_question_llm.py` | 规则无法唯一分类时调用受约束文本模型；首阶段可先用 fake/协议，不默认真实调用。 |
| 问题理解追溯事件 | 可先复用 `TraceRecord.module_events`，必要时新增 `QuestionUnderstandingTrace` DTO | 记录规则命中、模型尝试、歧义、澄清原因、证据需求来源。 |
| 测试模块 | `tests/test_assistant_question_*.py` | 覆盖分类、scope、证据需求、安全边界、多意图、澄清与兼容映射。 |

是否新增外部 adapter 取决于阶段目标。若只做 01 模块闭环，不建议立即新增产品级 HTTP/MCP/Web 入口；可以先通过服务和测试完成运行时核心。

## 3. 影响哪些已有模块？

| 已有模块 | 影响方式 | 边界 |
|---|---|---|
| `assistant_models.py` | 可能需要补充稳定枚举、原因码、澄清项 DTO 或问题类型常量。 | 不应破坏现有 DTO 默认只读与 `allow_write_back=false`。 |
| `assistant_retrieval_planner.py` | 会消费更丰富的 `EvidenceRequirement`。 | 不应把自然语言分类逻辑放入 planner。 |
| `assistant_retrieval_service.py` | 作为问题理解后的下游继续使用。 | 不访问模型，不做问题理解。 |
| `assistant_qa_mapping.py` | 可作为兼容入口或规则路由模板来源。 | 保持单向映射，不让 QAService 依赖产品层。 |
| `qa_models.py` / `qa_service.py` | 现有六类 QA 需要兼容映射。 | 不改 QAService 为完整自然语言服务。 |
| `DrawingGraphToolFacade` | 问题理解模块原则上不直接调用。 | 如果确需验证对象存在，应放在图谱检索模块，而不是理解模块。 |
| `qa_http.py` / `qa_mcp_*` | 后续产品级入口可能复用其 adapter 安全模式。 | 首阶段不建议改造现有只读 QA API。 |
| `TraceRecord` / `FeedbackEvent` | 问题理解闭环需要记录模块事件和澄清/反馈。 | 反馈不能直接修改来源事实或正式关系。 |
| 文档测试 | 需要同步“问题理解服务已实现/未实现”的描述。 | 文档不得把后续 DrawingAssistantService 写成已完成。 |

## 4. 技术方案有哪些？

### 方案 A：规则优先的确定性问题理解闭环

用规则解析稳定 ID、scope_hint、固定中文句式和现有六类 QA 问题，输出 `QuestionUnderstandingResult`。无法识别或歧义时返回 `clarification_required` 或 `unknown_or_unsupported`。

适合首阶段，因为项目已有明确问题类型、证据需求和下游检索合同。

### 方案 B：规则 + 受约束文本模型的混合问题理解闭环

规则先处理明确问题；规则无法唯一分类时调用文本模型，要求模型只输出受约束 JSON，再由本地枚举、scope、证据需求校验器验收。模型失败则回退为澄清或 unsupported。

适合在规则覆盖典型问题后扩展口语表达、多意图表达和模糊意图。

### 方案 C：端到端 Agent/LLM 直接编排闭环

由 Agent 或大模型直接理解问题、决定调用哪些工具、解释结果并追问用户。项目级 Skill 当前已经能辅助人工操作，但这不是稳定可测的产品运行时能力。

该方案实现快，但与当前架构的“受控合同、事实分层、只读边界、可测试模块”冲突较多，不适合作为主线。

### 方案 D：直接扩展现有 `DrawingGraphQAService`

把自然语言理解、scope 解析和证据需求生成加入 QAService，让现有 CLI/HTTP/MCP 立即获得自然语言能力。

该方案短期接入成本低，但会把“固定 QA 兼容层”和“完整产品助手理解层”混在一起，违背当前文档中 QAService 保留兼容、DrawingAssistantService 负责完整闭环的方向。

## 5. 优缺点比较

| 方案 | 优点 | 缺点 | 适配当前架构 |
|---|---|---|---|
| A 规则优先 | 可测试、可解释、无外部模型依赖、默认安全；容易保证 `write_back=false`。 | 覆盖口语和复杂多意图能力有限，规则会逐步增多。 | 高，适合首阶段。 |
| B 规则 + 文本模型 | 保留确定性边界，同时提升自然语言覆盖率；模型输出可被合同校验。 | 需要模型协议、JSON Schema、失败回退、脱敏和离线/Live 分层验证。 | 高，适合第二阶段或首阶段预留接口。 |
| C Agent 直接编排 | 原型快，用户体验看起来更自然。 | 难以稳定测试，容易绕过证据分层，把 candidate/interpretation 写成事实，追溯弱。 | 低，不建议作为产品主线。 |
| D 扩展 QAService | 可复用现有 CLI/HTTP/MCP，改动路径短。 | QAService 职责膨胀，破坏“QA 兼容层 vs 产品助手层”分工。 | 中低，不建议。 |

## 6. 推荐方案

推荐采用 **方案 A 起步，预留方案 B 的模型适配口**。

具体主线：

1. 新增 `QuestionUnderstandingService`，输入 `AssistantRequest`，输出 `QuestionUnderstandingResult`。
2. 首阶段只实现规则优先能力：稳定 ID 提取、scope_hint 合并、现有六类 QA 兼容、首版问题类型映射、证据需求模板、歧义和 unsupported 输出。
3. 把澄清作为问题理解闭环的核心：当 scope 缺失、指代不唯一、问题类型低置信度或多意图冲突时，不进入检索/识别，而是输出结构化澄清项。
4. 把问题理解事件写入追溯结构：记录规则命中、证据需求来源、unsupported parts、clarification reason。
5. 与现有 `GraphRetrievalService` 对接验证：用 `QuestionUnderstandingResult` 驱动只读检索，证明下游可消费。
6. 预留 `QuestionUnderstandingModelClient` 协议，但首阶段不默认调用真实文本模型；真实模型能力后续按离线合同测试和 live 验证分阶段加入。

推荐的运行链路：

```text
AssistantRequest
  -> QuestionUnderstandingService
       -> ScopeResolver
       -> RuleQuestionRouter
       -> EvidenceRequirementFactory
       -> ClarificationPolicy
  -> QuestionUnderstandingResult
  -> GraphRetrievalService
  -> RetrievalBundle
```

后续完整产品助手再扩展为：

```text
AssistantRequest
  -> QuestionUnderstandingService
  -> GraphRetrievalService
  -> SemanticGapDecisionService
  -> MultimodalRecognitionService
  -> EvidenceFusionService
  -> AnswerGenerationService
  -> TraceabilityFeedbackService
  -> AnswerPackage
```

首阶段完成标准建议：

- 明确 ID 的典型问题能稳定生成正确 `question_type`、scope 和 `required_evidence`。
- 缺少关键 scope 时返回澄清，不触发检索或识别。
- 多意图请求能拆分为稳定 `AssistantSubrequest`，或在歧义时要求澄清。
- 现有六类 QA 问题兼容，且不修改 `DrawingGraphQAService` 行为。
- 任意问题文本都不能把 `allow_write_back` 推断为 true。
- 单元测试覆盖每类问题、scope 冲突、unsupported、模型回退预留、安全输入。

## 7. 风险

| 风险 | 表现 | 缓解 |
|---|---|---|
| 问题类型边界漂移 | “是什么”“在哪里”“对应哪个”被错误映射，导致证据需求错误。 | 使用证据需求模板和参数化测试；低置信度返回澄清。 |
| Scope 指代误判 | “这个图块”在上下文不唯一时被错误绑定。 | ScopeResolver 只在唯一上下文对象存在时自动解析。 |
| 模型输出越权 | 文本模型把 `write_back=true`、Cypher、正式事实等塞入结果。 | 模型输出只作为候选理解结果，必须经过枚举和字段白名单校验。 |
| QAService 职责膨胀 | 为了快接入把自然语言理解塞进 QAService。 | 保持 QAService 兼容六类固定问题；产品层新增独立服务。 |
| 候选/正式事实混淆 | 用户问“是不是正式关系”时，用 candidate 或模型解释直接回答确定事实。 | EvidenceRequirement 明确 `minimum_status` 与 `fact_kind`，candidate 不能满足 formal。 |
| 澄清闭环缺少追溯 | 系统追问后无法说明为什么追问，后续反馈也无法定位问题。 | 在 `TraceRecord.module_events` 中记录理解决策、歧义和澄清原因。 |
| 规则膨胀 | 中文表达越来越多，规则不可维护。 | 规则只覆盖高频稳定模式；复杂表达交给受约束模型适配口。 |
| 与后续 03-07 模块耦合过早 | 问题理解阶段提前判断缓存、调用 Qwen 或生成答案。 | 严格遵守 01 模块边界：只声明证据需求，不访问图谱，不调用 Qwen，不生成最终答案。 |
| Live 能力被误报 | 离线测试通过后被描述为 live Neo4j 或 live 模型通过。 | 验证报告分层：单元、离线模型合同、live DashScope、live Neo4j 分开记录。 |

## 8. 建议实施边界

本需求应作为“产品实现层 01 问题理解模块”的独立实施阶段，不应合并实现 03-07。

建议包含：

- `AssistantRequest -> QuestionUnderstandingResult` 的服务实现。
- 规则路由、scope 解析、证据需求模板、澄清策略。
- 与 `GraphRetrievalService` 的只读衔接测试。
- 追溯事件的轻量记录。
- 文档同步。

建议暂不包含：

- 不新增真实 Qwen/DashScope 调用。
- 不新增完整 `DrawingAssistantService` 端到端编排。
- 不新增 HTTP/MCP 产品级入口。
- 不做反馈写回或候选正式提升。
- 不改 Neo4j schema。
- 不把用户确认变成正式事实。

## 9. 总结

“问题理解闭环”在当前项目中应定位为产品层的入口闭环：把自然语言问题稳定转成 `QuestionUnderstandingResult`，在歧义时形成可追问、可追溯、可反馈的结构化结果，并把明确问题交给已落地的通用检索闭环。

最稳妥的路径不是直接上 Agent，也不是扩展 QAService，而是在现有产品公共合同上补齐独立 `QuestionUnderstandingService`。这样既能复用已完成的 `assistant_models.py` 和 `GraphRetrievalService`，又能保持项目已有的核心边界：图谱优先、facade 白名单、事实分层、候选不冒充正式、默认 `write_back=false`。
