# 问题理解闭环 Proposal

**文档状态：** 需求提案  
**日期：** 2026-08-12  
**适用范围：** 产品实现层 01 问题理解模块的运行时闭环

## 1. 背景

当前项目已经具备图块图谱的来源事实导入、离线派生关系增强、候选关系复核骨架、按需语义证据、QA 编排、只读 HTTP API、本地 STDIO MCP adapter，以及产品公共合同与通用检索闭环。

产品层已经定义 `AssistantRequest`、`AssistantScope`、`EvidenceRequirement`、`AssistantSubrequest`、`QuestionUnderstandingResult`、`TraceRecord`、`FeedbackEvent` 等公共 DTO，并已实现 `GraphRetrievalService`，可以消费 `QuestionUnderstandingResult` 并执行只读图谱检索。

但完整产品助手的第一步仍缺少运行时能力：系统尚不能稳定地把用户自然语言问题转换为可执行、可测试、可追溯的 `QuestionUnderstandingResult`。因此需要增加问题理解闭环，使自然语言问题能够进入后续检索、缺口判断、识别、融合和回答流程。

## 2. 当前问题

当前问题主要集中在产品入口层：

- 用户仍需要由外部调用方或人工预先选择固定问题类型和准确 scope，产品本身不能稳定理解“用户在问什么”。
- 现有 `DrawingGraphQAService` 只支持六类确定性结构化问题，不承担完整自然语言问题理解，也不应被扩展成完整产品助手。
- 现有产品公共合同只有 `QuestionUnderstandingResult` 等数据结构，缺少独立 `QuestionUnderstandingService`。
- 缺少从自然语言到问题类型、scope、证据需求、回答要求和置信度的运行时转换。
- 缺少多意图拆分能力，无法把一个用户问题拆成多个有序子请求。
- 缺少澄清闭环；当缺少 page/block/element 等必要 scope、指代不唯一或问题类型低置信度时，系统没有结构化方式要求用户补充信息。
- 缺少问题理解追溯；系统无法记录规则命中、歧义、unsupported parts、澄清原因和后续用户修正。
- 如果直接依赖 Agent 或自由文本模型编排，容易绕过事实分层、facade 白名单、候选关系边界和默认 `write_back=false` 安全约束。

## 3. 功能目标

本需求目标是在产品实现层增加一个可测试、可追溯、默认只读的问题理解闭环。

核心目标：

- 将 `AssistantRequest` 稳定转换为 `QuestionUnderstandingResult`。
- 支持稳定 ID、`scope_hint` 和有限对话上下文的 scope 解析与指代消解。
- 支持首版问题类型映射，包括现有六类 QA 兼容问题，以及产品层规划中的页面摘要、图块关系、构件语义、元素文本或含义、候选关系、断面匹配、表题状态、诊断、来源追溯、比较和 unsupported。
- 根据问题类型生成明确的 `EvidenceRequirement`，供 `GraphRetrievalService` 消费。
- 支持多意图拆分，输出稳定 `AssistantSubrequest`，并保留父 `request_id`。
- 在 scope 缺失、scope 冲突、指代不唯一、问题类型低置信度或不支持时，输出结构化澄清或 unsupported 结果，而不是猜测。
- 记录问题理解阶段的可追溯事件，包括规则命中、歧义、澄清原因、证据需求来源和可选模型回退状态。
- 保持 `allow_write_back=false` 默认边界，问题文本不得把写回权限推断为 true。

首阶段推荐采用规则优先方案，并预留受约束文本模型适配口。规则能处理明确 ID、固定句式和现有 QA 兼容问题；规则无法唯一分类时返回澄清或 unsupported。后续如加入文本模型，模型输出必须经过枚举、scope、证据需求和字段白名单校验。

## 4. 修改范围

本需求建议修改范围如下：

- 新增问题理解服务模块，用于编排自然语言规范化、scope 解析、问题类型路由、证据需求生成和澄清策略。
- 新增规则路由模块，用于处理稳定 ID、明确中文句式、现有六类 QA 兼容问题和高频产品问题类型。
- 新增证据需求模板模块，将不同 `question_type` 对应的 `EvidenceRequirement` 集中管理。
- 新增 scope 解析与指代消解模块，合并 `scope_hint`、问题文本中的稳定业务 ID 和有限对话上下文；该模块不访问 Neo4j。
- 新增澄清策略模块，在缺少必要 scope、scope 冲突、多意图歧义或低置信度时生成结构化澄清结果。
- 必要时扩展 `assistant_models.py` 中的稳定枚举、原因码或澄清项 DTO，但不得破坏现有公共合同默认只读语义。
- 与现有 `GraphRetrievalService` 做只读衔接验证，确保 `QuestionUnderstandingResult` 可被下游检索模块消费。
- 增加单元测试和合同测试，覆盖问题分类、scope 解析、证据需求、多意图拆分、澄清、安全输入、unsupported 和现有 QA 兼容映射。
- 同步相关文档，明确问题理解服务的已实现范围和未实现范围。

建议的目标链路：

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

## 5. 不包含范围

本需求不包含以下内容：

- 不实现完整 `DrawingAssistantService` 端到端编排。
- 不实现语义缺口判断、多模态识别、证据融合、答案生成和追溯反馈模块的完整运行时。
- 不新增真实 Qwen、DashScope 或其他外部模型调用。
- 不新增独立 OCR 流程。
- 不新增产品级 HTTP、MCP、CLI 或 Web UI adapter。
- 不改造现有只读 QA HTTP API 或本地 STDIO MCP adapter。
- 不修改 Neo4j schema。
- 不直接访问 Neo4j driver、session、transaction、Cypher、repository 或底层离线规则函数。
- 不调用 `DrawingGraphToolFacade` 执行图谱查询；对象存在性和证据获取由后续图谱检索模块负责。
- 不创建 `RecognitionRun`，不写入语义证据，不写 Neo4j。
- 不提升候选关系为正式关系。
- 不把用户确认、模型解释或 `matched_candidate` 视为正式事实。
- 不从问题文本中推断 `allow_write_back=true`。

## 6. 影响模块

| 模块 | 影响 |
|---|---|
| `src/drawing_graph/assistant_models.py` | 可能补充问题类型、原因码、澄清项或问题理解追溯 DTO；需保持默认只读和向后兼容。 |
| `src/drawing_graph/assistant_retrieval_service.py` | 作为问题理解后的下游继续消费 `QuestionUnderstandingResult`；不加入自然语言解析逻辑。 |
| `src/drawing_graph/assistant_retrieval_planner.py` | 会接收更完整的 `EvidenceRequirement`；仍只负责检索规划，不负责理解问题。 |
| `src/drawing_graph/assistant_qa_mapping.py` | 可作为现有六类 QA 兼容映射参考；保持 QA 到产品层的单向兼容，不反向依赖。 |
| `src/drawing_graph/qa_models.py` / `src/drawing_graph/qa_service.py` | 现有六类固定 QA 需保持兼容；不把 QAService 改成完整自然语言产品服务。 |
| `src/drawing_graph/tool_facade.py` | 问题理解阶段原则上不直接调用 facade；后续检索仍经 facade 白名单只读能力。 |
| `src/drawing_graph/qa_http.py` / `src/drawing_graph/qa_mcp_*.py` | 首阶段不改造；后续产品级 adapter 可复用其只读、安全、脱敏和生命周期模式。 |
| `TraceRecord` / `FeedbackEvent` 相关合同 | 问题理解闭环需要记录规则命中、澄清原因、歧义和用户修正事件；反馈不得直接改变来源事实或正式关系。 |
| `tests/test_assistant_*.py` | 需要新增或扩展测试，覆盖问题理解服务、规则路由、scope 解析、证据需求、澄清和边界约束。 |
| `README.md` / `architecture.md` / `Module.md` / 产品实现层文档 | 实施后需要同步当前状态，避免把后续完整产品助手、真实模型调用或写回能力误写成已完成。 |
