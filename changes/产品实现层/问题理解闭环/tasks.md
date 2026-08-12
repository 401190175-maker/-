# 问题理解闭环 Tasks

**文档状态：** 实施任务计划  
**日期：** 2026-08-12  
**依据文档：** `proposal.md`、`design.md`、`Feature_Analysis_Report.md`  
**全局约束：**

- 禁止无意义重构。
- 优先复用已有 `assistant_models.py`、`GraphRetrievalService`、`assistant_qa_mapping.py`、QA/facade 边界。
- 默认 `write_back=false`，问题理解模块不得把问题文本推断为写回授权。
- 问题理解模块不得访问 Neo4j、不得调用 `DrawingGraphToolFacade`、不得调用 Qwen/DashScope、不得创建 `RecognitionRun`、不得写数据库。
- 每个任务必须独立测试；未配置 live Neo4j 或 live 模型时，不得把 skipped 报告为通过。

## Task 1：补充问题理解公共枚举与原因码

**明确目标：**  
在产品公共合同中补充问题理解闭环需要的稳定问题类型和原因码，为后续模块提供统一字符串来源。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_models.py`
- 新增测试：`tests/test_assistant_question_models.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_question_models -v
```

**完成标准：**

- `assistant_models.py` 中存在稳定 `QuestionType` 问题类型枚举。
- 枚举至少覆盖 `page_summary`、`block_relations`、`block_semantic_identification`、`element_text_or_meaning`、`candidate_relations`、`section_matches`、`table_caption_status`、`drawing_diagnostic`、`source_trace`、`comparison`、`clarification_required`、`unknown_or_unsupported`。
- `ReasonCode` 补充 `ambiguous_reference`、`ambiguous_question_type`、`multi_intent_ambiguous`、`unsupported_question`、`model_output_invalid`。
- 既有 `AssistantRequest`、`EvidenceRequirement`、`QuestionUnderstandingResult` 行为不被破坏。

## Task 2：新增澄清项数据契约

**明确目标：**  
新增结构化澄清项 DTO，使 scope 缺失、冲突和指代不唯一可以被机器稳定消费。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_models.py`
- 修改测试：`tests/test_assistant_question_models.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_question_models -v
```

**完成标准：**

- 存在 `ClarificationItem` DTO。
- 字段至少包含 `clarification_id`、`reason_code`、`target_field`、`message`、`allowed_scope_types`、`candidate_refs`、`required`。
- DTO 拒绝空 `clarification_id`、空 `reason_code`、空 `target_field`。
- `candidate_refs` 只承载稳定业务 ID 或上下文引用，不承载 Neo4j 内部 ID。

## Task 3：新增问题理解追溯事件数据契约

**明确目标：**  
新增问题理解阶段的轻量追溯事件 DTO，用于记录规则命中、scope 来源、歧义和澄清原因。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_models.py`
- 修改测试：`tests/test_assistant_question_models.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_question_models -v
```

**完成标准：**

- 存在 `QuestionUnderstandingEvent` DTO。
- 字段至少包含 `event_id`、`request_id`、`stage`、`question_type`、`confidence`、`reason_codes`、`details`。
- 事件 DTO 可放入 `TraceRecord.module_events`。
- 测试覆盖敏感字段不作为必填字段，且不要求保存 traceback、Cypher 或 secret。

## Task 4：实现问题文本规范化模块

**明确目标：**  
新增文本规范化能力，把用户问题整理为规则路由可稳定处理的形式，但不改变原始问题语义。

**指定修改文件：**

- 新增：`src/drawing_graph/assistant_question_text.py`
- 新增测试：`tests/test_assistant_question_text.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_question_text -v
```

**完成标准：**

- 提供 `QuestionTextNormalizer.normalize(question: str) -> str` 接口。
- 去除首尾空白，统一常见全角标点和重复空白。
- 保留稳定业务 ID、中文语义和大小写敏感 ID 内容。
- 空字符串由上游 `AssistantRequest` 负责拒绝，本模块不吞掉错误。

## Task 5：实现稳定业务 ID 提取

**明确目标：**  
从用户问题文本中提取 page/block/element/cross_section/table/table_caption/claim 等稳定业务 ID。

**指定修改文件：**

- 新增：`src/drawing_graph/assistant_scope_resolution.py`
- 新增测试：`tests/test_assistant_scope_resolution.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_scope_resolution -v
```

**完成标准：**

- 提供 `ScopeResolver` 类。
- 能从文本中提取 `page:`、`block:`、`element:`、`cross_section:`、`table:`、`table_caption:`、`claim:` 前缀 ID。
- 提取结果写入 `ScopeResolutionResult.scope`。
- 不接受 Neo4j 内部 ID、Cypher 片段、driver URI 或文件路径作为 scope。

## Task 6：实现 scope_hint 合并与冲突检测

**明确目标：**  
合并 `AssistantRequest.scope_hint` 与文本中提取的稳定 ID，并在冲突时返回冲突信息而不是擅自选择。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_scope_resolution.py`
- 修改测试：`tests/test_assistant_scope_resolution.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_scope_resolution -v
```

**完成标准：**

- `scope_hint` 与文本 ID 一致时生成合并后的 `AssistantScope`。
- `scope_hint.page_id` 与文本中的另一个 page ID 冲突时返回 `scope_conflict`。
- 本轮明确文本 ID 优先于对话上下文，但不静默覆盖冲突的 `scope_hint`。
- 不查询图谱验证对象是否存在。

## Task 7：实现有限对话上下文指代消解

**明确目标：**  
支持“这张图”“这个图块”等指代在唯一上下文对象存在时解析，非唯一时返回歧义。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_scope_resolution.py`
- 修改测试：`tests/test_assistant_scope_resolution.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_scope_resolution -v
```

**完成标准：**

- 对话上下文中只有一个 page ID 且问题含“这张图”时可解析 `page_id`。
- 对话上下文中只有一个 block ID 且问题含“这个图块”时可解析 `block_id`。
- 多个同类候选时返回 `ambiguous_reference`。
- 对话上下文不能覆盖本轮明确 ID。

## Task 8：实现规则路由结果 DTO 与路由器骨架

**明确目标：**  
新增规则路由模块和稳定路由结果，先覆盖无命中、单命中、多命中三种基础行为。

**指定修改文件：**

- 新增：`src/drawing_graph/assistant_question_rules.py`
- 新增测试：`tests/test_assistant_question_rules.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_question_rules -v
```

**完成标准：**

- 提供 `RuleQuestionRouter.route(question, scope)` 接口。
- 路由结果包含 `question_type`、`confidence`、`matched_rules`、`unsupported_parts`、`ambiguities`。
- 无规则命中时返回 `unknown_or_unsupported`。
- 多个同等级规则命中时返回 `ambiguous_question_type`。

## Task 9：实现首版问题类型规则

**明确目标：**  
为产品层首版问题类型添加确定性中文规则，不依赖外部文本模型。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_question_rules.py`
- 修改测试：`tests/test_assistant_question_rules.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_question_rules -v
```

**完成标准：**

- 规则覆盖 `page_summary`、`block_relations`、`block_semantic_identification`、`element_text_or_meaning`、`candidate_relations`、`section_matches`、`table_caption_status`、`drawing_diagnostic`、`source_trace`、`comparison`。
- 每类至少有一个中文典型问题测试。
- “是什么构件”映射到 `block_semantic_identification`。
- “对应哪个标题”映射到 `section_matches` 或表题相关类型时有明确规则边界。

## Task 10：实现多意图拆分

**明确目标：**  
把明确列举式或连接式多意图问题拆分为稳定 `AssistantSubrequest`，不确定时返回歧义。

**指定修改文件：**

- 新增：`src/drawing_graph/assistant_intent_splitter.py`
- 新增测试：`tests/test_assistant_intent_splitter.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_intent_splitter -v
```

**完成标准：**

- 提供 `IntentSplitter.split(...) -> tuple[AssistantSubrequest, ...]` 接口。
- 能拆分“这张图主要讲什么，并列出候选关系”这类两个明确意图。
- 每个子请求有稳定 `subrequest_id`。
- 拆分不确定时返回 `multi_intent_ambiguous`，不丢弃任何子问题。

## Task 11：实现证据需求模板工厂

**明确目标：**  
按 `question_type + scope` 生成 `EvidenceRequirement`，集中维护问题到证据的映射。

**指定修改文件：**

- 新增：`src/drawing_graph/assistant_evidence_templates.py`
- 新增测试：`tests/test_assistant_evidence_templates.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_templates -v
```

**完成标准：**

- 提供 `EvidenceRequirementFactory.build(question_type, scope, request)` 接口。
- `page_summary` 生成 `PAGE_SOURCE_FACTS`。
- `block_relations` 生成 `BLOCK_TRACE` 与 `BLOCK_RELATIONS`。
- `candidate_relations` 生成 `CANDIDATE_RELATIONS`。
- `section_matches` 生成 `SECTION_MATCHES`。
- `allow_model_generation` 只在语义类需求中为 true，且不触发模型调用。

## Task 12：实现澄清策略

**明确目标：**  
根据 scope 缺失、冲突、指代不唯一、问题类型歧义生成结构化澄清结果。

**指定修改文件：**

- 新增：`src/drawing_graph/assistant_clarification.py`
- 新增测试：`tests/test_assistant_clarification.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_clarification -v
```

**完成标准：**

- 提供 `ClarificationPolicy.evaluate(...)` 接口。
- 缺 `block_id` 的 block 级问题返回 `scope_missing` 澄清项。
- `scope_conflict` 输入返回 required 澄清。
- `ambiguous_reference` 输入返回 required 澄清。
- 澄清场景不生成可触发 facade 调用的必需证据需求。

## Task 13：实现问题理解追溯构造器

**明确目标：**  
生成问题理解阶段事件，记录规则命中、scope 来源、歧义、澄清原因和证据需求来源。

**指定修改文件：**

- 新增：`src/drawing_graph/assistant_question_trace.py`
- 新增测试：`tests/test_assistant_question_trace.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_question_trace -v
```

**完成标准：**

- 提供 `QuestionUnderstandingTraceBuilder` 类。
- 可生成 `QuestionUnderstandingEvent`。
- 事件可放入 `TraceRecord.module_events`。
- 事件 details 不包含 Cypher、secret、Authorization header 或 traceback。

## Task 14：新增受约束文本模型适配口

**明确目标：**  
预留可注入的文本模型协议，但默认不启用真实模型、不新增外部依赖。

**指定修改文件：**

- 新增：`src/drawing_graph/assistant_question_llm.py`
- 新增测试：`tests/test_assistant_question_llm.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_question_llm -v
```

**完成标准：**

- 定义 `QuestionUnderstandingModelClient` 协议。
- 协议方法返回受约束的问题理解候选结果。
- 模块不读取 API key、不导入 DashScope/OpenAI 客户端、不发起网络请求。
- 测试覆盖模块导入无外部网络或环境变量依赖。

## Task 15：新增文本模型 fake 客户端与非法输出校验

**明确目标：**  
提供可测试的 fake 文本模型客户端，并确保非法模型输出不会进入权威问题理解结果。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_question_llm.py`
- 新增或修改测试：`tests/test_assistant_question_llm.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_question_llm -v
```

**完成标准：**

- 提供 `FakeQuestionUnderstandingModelClient`。
- 非法模型输出返回 `model_output_invalid` 结果。
- fake client 不发起网络请求。
- 非法输出不生成 `source_fact`、`formal_relation`、Cypher 或写回指令。

## Task 16：实现 QuestionUnderstandingService 编排

**明确目标：**  
新增问题理解服务，将 `AssistantRequest` 编排为 `QuestionUnderstandingResult`。

**指定修改文件：**

- 新增：`src/drawing_graph/assistant_question_understanding.py`
- 新增测试：`tests/test_assistant_question_understanding.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_question_understanding -v
```

**完成标准：**

- 提供 `QuestionUnderstandingService.understand(request) -> QuestionUnderstandingResult`。
- 明确 ID 的典型问题能输出正确 `question_type`、scope 和 `required_evidence`。
- 缺 scope 的问题输出 `clarification_required`。
- unsupported 问题输出 `unknown_or_unsupported`。
- 服务不调用 facade、不访问 Neo4j、不调用模型真实客户端。

## Task 17：实现与 GraphRetrievalService 的只读衔接测试

**明确目标：**  
验证问题理解输出可被现有通用检索闭环消费，且澄清/unsupported 不触发 facade 调用。

**指定修改文件：**

- 新增测试：`tests/test_assistant_question_retrieval_integration.py`
- 不修改：`src/drawing_graph/assistant_retrieval_service.py`，除非测试暴露空需求处理缺陷
- 可选修改：`src/drawing_graph/assistant_retrieval_planner.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_question_retrieval_integration -v
```

**完成标准：**

- `page_summary` 问题理解结果可传入 `GraphRetrievalService.retrieve()`。
- fake facade 收到预期只读调用。
- `clarification_required` 不触发 fake facade 调用。
- `unknown_or_unsupported` 不触发 fake facade 调用或只产生 unsupported warning。

## Task 18：补充 QA 兼容映射一致性测试

**明确目标：**  
确保新问题类型与现有六类固定 QA 兼容，不改变 `DrawingGraphQAService` 行为。

**指定修改文件：**

- 修改测试：`tests/test_assistant_qa_mapping.py`
- 可选修改：`src/drawing_graph/assistant_qa_mapping.py`
- 不修改：`src/drawing_graph/qa_service.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_qa_mapping -v
```

**完成标准：**

- 现有六类 `QARequest` 仍能映射到 `QuestionUnderstandingResult`。
- 映射后的 `question_type` 与产品层问题类型常量一致或值兼容。
- `DrawingGraphQAService` 无新增产品层依赖。
- QA 写回拒绝逻辑不被修改。

## Task 19：增加问题理解模块静态边界测试

**明确目标：**  
用静态测试防止问题理解模块越过架构边界访问 Neo4j、facade、repository、CLI 或写回能力。

**指定修改文件：**

- 新增：`tests/test_assistant_question_boundaries.py`
- 不修改业务代码，除非静态测试暴露违规导入

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_question_boundaries -v
```

**完成标准：**

- `assistant_question_*.py` 不导入 `neo4j`。
- `assistant_question_*.py` 不导入 repository、relation service、semantic write repository。
- `assistant_question_*.py` 不调用 `DrawingGraphToolFacade`。
- `assistant_question_*.py` 不包含 Cypher 关键操作或 CLI subprocess 调用。
- 测试明确覆盖 `write_back` 不可被问题文本提升。

## Task 20：补充问题理解安全行为测试

**明确目标：**  
验证恶意或越权文本不会触发写回、Cypher、正式关系提升或模型事实注入。

**指定修改文件：**

- 新增：`tests/test_assistant_question_security.py`
- 可选修改：`src/drawing_graph/assistant_question_understanding.py`
- 可选修改：`src/drawing_graph/assistant_scope_resolution.py`
- 可选修改：`src/drawing_graph/assistant_question_llm.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_question_security -v
```

**完成标准：**

- 问题文本包含 `write_back=true` 时，`AssistantRequest.allow_write_back` 不被改变。
- 问题文本包含 Cypher 时，不生成自由查询或执行意图。
- 用户要求“提升为正式关系”不会生成正式关系写回动作。
- fake 模型输出正式事实或 Cypher 时被拒绝为非法输出。

## Task 21：同步架构与模块文档

**明确目标：**  
把问题理解闭环的实际实现状态同步到项目维护文档，避免把未实现的完整产品助手写成已完成。

**指定修改文件：**

- 修改：`architecture.md`
- 修改：`Module.md`
- 修改：`README.md`
- 修改：`changes/产品实现层/问题理解闭环/design.md`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_docs -v
```

**完成标准：**

- 文档记录 `QuestionUnderstandingService` 已实现范围。
- 文档仍明确完整 `DrawingAssistantService`、产品级 HTTP/MCP/CLI/Web adapter、真实文本模型调用、03-07 运行时仍未实现。
- 文档保留 `write_back=false`、不访问 Neo4j、不调用 facade、不写数据库的边界。
- `tests.test_assistant_docs` 通过。

## Task 22：补充问题理解专项文档测试

**明确目标：**  
为 `changes/产品实现层/问题理解闭环/` 下的 proposal/design/tasks 文档增加合同测试，防止后续文档漂移。

**指定修改文件：**

- 新增或修改：`tests/test_assistant_question_docs.py`
- 不修改业务代码

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_question_docs -v
```

**完成标准：**

- 测试确认 `proposal.md`、`design.md`、`tasks.md` 均存在。
- 测试确认 `tasks.md` 每个任务包含明确目标、指定修改文件、可独立测试、完成标准。
- 测试确认文档包含“不改 Neo4j schema”“不调用真实模型”“默认 write_back=false”等边界。
- 测试不依赖 live Neo4j 或 live DashScope。

## Task 23：运行问题理解闭环最小回归

**明确目标：**  
运行与本阶段相关的最小测试集合，证明新增问题理解闭环与现有产品检索、QA 映射和文档合同兼容。

**指定修改文件：**

- 不新增业务代码
- 可选修改：失败测试对应的最小相关文件

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest `
  tests.test_assistant_question_models `
  tests.test_assistant_question_text `
  tests.test_assistant_scope_resolution `
  tests.test_assistant_question_rules `
  tests.test_assistant_intent_splitter `
  tests.test_assistant_evidence_templates `
  tests.test_assistant_clarification `
  tests.test_assistant_question_trace `
  tests.test_assistant_question_llm `
  tests.test_assistant_question_understanding `
  tests.test_assistant_question_retrieval_integration `
  tests.test_assistant_qa_mapping `
  tests.test_assistant_question_boundaries `
  tests.test_assistant_question_security `
  tests.test_assistant_question_docs `
  -v
```

**完成标准：**

- 上述测试全部通过。
- 未运行 live Neo4j 或 live DashScope 时，不报告 live 验证通过。
- 失败时只修复与问题理解闭环相关的最小文件，不做无关重构。
- 最终变更仍不新增外部依赖、不改 Neo4j schema、不改 QA/facade 依赖方向。
