# 语义缺口决策闭环 Proposal

**文档状态：** 需求提案  
**日期：** 2026-08-12  
**适用范围：** 产品实现层 03 语义缺口决策模块

## 1. 背景

当前项目已经具备从图纸来源事实到产品层只读检索的基础链路：XAnyLabeling JSON/PNG 可以形成可追溯的图谱来源事实，离线增强可以形成正式派生关系和候选关系，语义证据层已经具备图谱内 `TextObservation`、三类 `Interpretation`、确定性缓存键、不可变 payload、图谱外 `RecognitionRun` 以及默认 `write_back=false` 的按需识别边界。

产品实现层已经落地公共合同、问题理解闭环和通用图谱检索闭环。`QuestionUnderstandingService` 可以把自然语言问题转换为 `QuestionUnderstandingResult` 和 `EvidenceRequirement`；`GraphRetrievalService` 可以通过 `DrawingGraphToolFacade` 白名单只读能力获取 `RetrievalBundle`，并保持来源事实、派生关系、语义观察、语义解释、候选关系和正式关系的事实分层。

但是，问题理解和图谱检索之后仍缺少一个产品级决策环节：系统尚不能统一回答“现有证据是否足够”“证据是否仍然有效”“是否可以复用缓存”“是否需要调用多模态模型”“应识别哪些最小目标”“识别是否超过预算或时延限制”。目前是否调用识别主要由外部调用方明确触发，不能形成稳定、可解释、可测试的自动决策闭环。

因此，需要在 `GraphRetrievalService` 之后、现有语义识别服务之前增加独立的语义缺口决策闭环。该闭环只进行确定性判断和目标规划，不执行图谱查询、模型调用或写回。

目标链路为：

```text
QuestionUnderstandingResult
  + RetrievalBundle
  + RecognitionPolicy
  -> SemanticGapDecisionService
       -> 证据充分性判断
       -> freshness 与缓存判断
       -> 最小识别目标规划
       -> 预算与时延门控
  -> SemanticGapDecision
  -> 后续多模态识别或证据融合
```

## 2. 当前问题

当前架构具备语义缺口决策所需的部分合同和元数据，但尚未形成完整运行时能力，主要问题如下：

- 当前没有独立的 `SemanticGapDecisionService`，也没有 `SemanticGapDecision`、`RecognitionPolicy`、`RecognitionTarget` 和逐需求充分性评估等完整运行时合同。
- `RetrievalBundle` 已按事实等级分桶，但没有逐项比较 `EvidenceRequirement` 与已有证据，无法稳定判断 scope、fact kind、状态、freshness、冲突和正式审核门槛是否满足。
- `EvidenceRequirement.freshness_policy` 已存在，但目前只有策略声明，没有统一的 freshness 判定服务，也不能完整表达图片、bbox、任务、模型、prompt、预处理、规范化和输出合同版本的组合约束。
- facade 语义投影已包含部分 `status`、`image_hash`、`cache_key`、模型、prompt、合同版本和创建时间信息，但检索投影没有把所有决策所需字段稳定提升为统一证据元数据，决策层若直接解析内部 `value` 字典会造成合同脆弱。
- 当前缓存检查主要位于语义识别服务内部，产品层无法在模型调用前解释完整命中、部分命中、失效、绕过或未知状态，也无法只为剩余缺口生成识别目标。
- 当前识别入口主要按页面和 `target_types` 处理目标，尚不能直接消费精确到 `target_element_id`、bbox、task type、required output 和最小上下文的识别计划。
- 当前缺少最大识别目标数、估算成本、最大时延、重试余量和估算不可用时的稳定门控策略。
- 当前缺少多项证据需求到最小识别目标集合的去重、合并和优先级规划，容易重复识别同一对象或把元素级问题扩大为整页扫描。
- 缓存判断与模型执行之间可能存在状态变化；如果没有执行前二次缓存校验，可能在其他请求已经产生有效结果后仍重复调用模型。
- 缺少统一原因码来解释 `evidence_missing`、`evidence_stale`、`image_changed`、`budget_exceeded`、`latency_exceeded`、`formal_review_required` 和 `recognition_forbidden` 等决策。
- 如果把该逻辑直接塞入 `SemanticRecognitionService`、`DrawingGraphQAService`、HTTP/MCP adapter 或自由 Agent，会造成职责膨胀，并增加绕过事实分层、预算硬限制和默认只读边界的风险。

## 3. 功能目标

本需求目标是在产品实现层增加一个独立、确定性、无副作用、可解释的语义缺口决策闭环。

### 3.1 证据充分性判断

- 对每个 `EvidenceRequirement` 生成独立评估结果，而不是只给整个 `RetrievalBundle` 一个总状态。
- 按目标存在性、scope、fact kind、证据状态、freshness、冲突、正式审核门槛和模型生成许可进行判断。
- 按 `evidence_type + fact_kind` 定义可接受状态，不建立一个适用于所有证据类型的全局状态排序。
- 保持事实等级不变：语义解释不能满足来源事实需求，候选关系不能满足正式关系需求，`matched_candidate` 不等于 formal。
- 对满足、缺失、过期、冲突、不可生成和需要正式审核的证据分别输出稳定原因码。

### 3.2 Freshness 判断

- freshness 以内容和版本一致性为主，不只依赖时间 TTL。
- 至少判断当前 `image_hash`、目标元素 ID、bbox、task type、required output、model profile/version、prompt version、preprocessing version、normalization rule version 和 output contract version。
- `stale`、`rejected`、`recognition_failed` 或存在冲突的语义证据不得作为当前有效证据使用。
- 保持现有 freshness 策略值兼容，并支持多个 freshness 维度的组合要求。
- 缺少关键 freshness 元数据时返回 `unknown` 或相应 warning，不把未知状态默认为有效。

### 3.3 缓存判断

- 复用现有 `semantic_cache.py` 的统一确定性 cache key 规范，不在产品层建立第二套缓存键算法。
- 输出 `full_hit`、`partial_hit`、`miss`、`stale`、`bypassed` 或 `unknown` 等稳定缓存处置状态。
- 完整命中时不生成识别目标；部分命中时只为剩余证据缺口生成目标。
- 决策阶段根据已有证据和预期 cache key 判断是否需要识别；执行阶段在供应商调用前按同一 key 再次检查缓存，避免并发或状态变化导致重复调用。
- 有效缓存命中不得触发真实 Qwen 调用，也不应创建无意义的持久化 `RecognitionRun`。

### 3.4 最小识别目标规划

- 只从未满足且允许模型生成的证据需求中产生 `RecognitionTarget`。
- 目标优先精确到单个 page、block、element 或 bbox；只有明确的页面摘要任务才使用整页输入。
- 每个目标保留 page ID、目标元素 ID、目标类型、task type、required outputs、bbox、最小 context、覆盖的 requirement IDs、优先级和原因码。
- 同一目标、同一 task type 和兼容输出合同的多个需求可以合并；不同 prompt 或输出合同不得错误合并或共享缓存。
- 缺少可信 image path、image hash、bbox 或合法稳定业务 ID 时，不调用模型猜测，应返回澄清或 unsupported。
- 所有目标按确定规则稳定排序，被预算或时延限制裁掉的目标进入 `deferred_targets`，不得静默丢失。

### 3.5 预算与时延门控

- 通过 `RecognitionPolicy` 明确 `allow_recognition`、`max_targets`、`max_estimated_cost`、`max_latency_seconds`、模型和版本策略、重试余量及缓存模式。
- `allow_recognition=false` 是绝对门槛，任何其他策略或问题文本都不能覆盖。
- 成本和时延由可注入估算 profile 提供，价格和模型能力不硬编码在决策算法中。
- 成本估算只用于决策和提示，不冒充实际账单；实际 token、费用和时延由后续识别结果和追溯模块记录。
- 时延估算应考虑图片范围、任务类型、模型 profile 和重试余量；无历史数据时使用保守上界。
- 存在硬预算但无法估算时，应保守返回 `estimate_unavailable`，不能按零成本处理。
- 必需目标超过目标数、预算或时延上限时，返回明确原因、selected/deferred targets 和缩小 scope 建议，不伪装为完整回答。

### 3.6 决策输出与安全边界

- 输出稳定 `SemanticGapDecision`，包含 decision、逐需求评估、缺失需求、缓存候选、selected targets、deferred targets、估算摘要、原因码、warning 和可选写回建议。
- decision 保持 `reuse_existing`、`recognize_required`、`clarification_required` 和 `unsupported` 四种稳定值。
- `reuse_existing` 只表示不需要继续识别，不保证最终答案一定完整；下游仍应根据缺失需求和 warning 输出 answered 或 partial。
- `write_back_recommendation` 只是建议，不能修改 `AssistantRequest.allow_write_back`，也不能代替模块策略、环境权限和 repository 可用性检查。
- 决策模块不产生持久化副作用，并能通过相同输入得到稳定、可重放的结果。

## 4. 修改范围

本需求建议包含以下修改范围：

- 扩展产品公共合同，增加语义缺口 decision、逐需求评估、freshness/cache 结果、识别目标、预算/时延估算、selected/deferred targets 和稳定原因码。
- 新增证据充分性评估能力，逐项比较 `EvidenceRequirement` 与 `RetrievalBundle` 中的来源事实、派生关系、语义观察、语义解释、候选关系和正式关系。
- 新增 freshness 与缓存评估能力，统一使用当前图片、bbox、任务、模型、prompt、预处理、规范化和输出合同版本判断证据是否可复用。
- 新增最小识别目标规划能力，将未满足且允许生成的证据需求转换为精确、去重、可合并、稳定排序的 `RecognitionTarget`。
- 新增预算与时延评估能力，通过可注入估算器执行最大目标数、成本和时延硬门控，并保留被延后的目标及原因。
- 新增 `SemanticGapDecisionService`，按照“充分性 -> freshness/cache -> 目标规划 -> 预算/时延 -> 最终 decision”的顺序编排决策。
- 补齐 `RetrievalBundleBuilder` 的稳定元数据投影，使决策层能够直接读取 status、image hash、cache key、model/prompt、contract version 和 created at，而不是依赖内部字典结构。
- 必要时补齐 `assistant_evidence_templates.py` 的最低状态、freshness 和模型生成许可，使问题理解模块能声明下游决策所需约束。
- 为后续执行衔接补充精确目标识别合同，使现有 facade、语义服务和多模态客户端能够消费元素级目标、task type 和 output contract。
- 调整语义执行顺序，使最终缓存检查发生在供应商调用和持久化 run 创建之前；缓存命中时直接复用结果。
- 增加单元测试、合同测试、属性测试和静态边界测试，覆盖充分性矩阵、freshness、缓存处置、目标合并、预算/时延、原因码、确定性和无副作用约束。
- 实施后同步 `architecture.md`、`Module.md`、产品实现层文档和相关状态说明，明确哪些能力已实现、哪些仍属于后续 04-07 模块。

首阶段应优先完成纯决策核心和 fake/离线测试，不要求同时完成完整 `DrawingAssistantService` 或真实模型调用。

## 5. 不包含范围

本需求不包含以下内容：

- 不实现完整 `DrawingAssistantService` 的端到端产品编排。
- 不实现证据融合、最终 claim 生成、中文答案生成和用户反馈状态机。
- 不新增产品级 CLI、HTTP、MCP 或 Web UI adapter。
- 不改造现有六类只读 `DrawingGraphQAService` 为完整自然语言产品服务。
- 语义缺口决策模块不调用 `DrawingGraphToolFacade`、Neo4j、repository、Cypher 或底层离线规则函数。
- 语义缺口决策模块不调用 Qwen、DashScope 或其他外部模型。
- 不建设独立 OCR 流程，也不引入 OCR 引擎。
- 不执行全量自动语义扫描，识别目标必须来自当前请求的最小证据缺口。
- 不在决策模块中创建 `RecognitionRun`、写缓存、写 payload、写语义证据或写 Neo4j。
- 不修改 Neo4j 节点、关系、约束或索引，不创建 `RecognitionRun` 图谱节点。
- 不设置或推断 `DrawingBlock.block_type`。
- 不覆盖来源事实，不删除历史 observation/interpretation，不把新模型结果当作来源标注原文。
- 不审核或提升候选关系，不绕过 `CandidateReviewService` 和硬规则建立正式关系。
- 不把 candidate、`matched_candidate`、语义观察、语义解释或用户确认当作 formal relation。
- 不从问题文本、估算结果或 `write_back_recommendation` 推断 `allow_write_back=true`。
- 不把估算成本写成实际账单，也不把单元/fake 测试写成 live DashScope 或 live Neo4j 已验证。

## 6. 影响模块

| 模块 | 影响 | 边界要求 |
|---|---|---|
| `src/drawing_graph/assistant_models.py` | 增加 decision、assessment、freshness/cache、recognition target、budget/latency 和原因码合同。 | 保持公共 DTO 无数据库、HTTP、MCP 或模型客户端依赖；默认 `allow_write_back=false`。 |
| `src/drawing_graph/assistant_evidence_templates.py` | 为语义类需求补充 minimum status、freshness 和 `allow_model_generation`；必要时补齐断面双方 observation 需求。 | 只声明证据需求，不读取图谱、不判断现有证据是否充分。 |
| `src/drawing_graph/assistant_retrieval_planner.py` | 必要时确保语义需求同时检索定位来源事实和当前图片元数据。 | 仍只生成只读 facade 计划，不读取缓存写口、不调用识别。 |
| `src/drawing_graph/assistant_retrieval_projection.py` | 稳定投影 status、image hash、cache key、model/prompt、contract version 和 created at；页面来源事实保留 image hash。 | 不在检索投影中决定是否识别或提升事实等级。 |
| `src/drawing_graph/assistant_retrieval_service.py` | 继续作为语义缺口决策的只读上游，输出 `RetrievalBundle`。 | 原则上接口保持不变，不吸收 freshness、预算或识别规划逻辑。 |
| `src/drawing_graph/assistant_evidence_sufficiency.py` | 新增逐需求充分性矩阵与 formal gate 判断。 | 不执行查询、识别、融合或写回。 |
| `src/drawing_graph/assistant_evidence_freshness.py` | 新增 freshness 和 cache disposition 判断，复用统一缓存键输入。 | 不复制缓存键算法，不写缓存。 |
| `src/drawing_graph/assistant_recognition_target_planner.py` | 新增最小目标生成、兼容合并、去重、上下文最小化和稳定排序。 | 不调用模型，不为缺少来源定位的对象猜测目标。 |
| `src/drawing_graph/assistant_recognition_budget.py` | 新增保守成本/时延估算、策略门控和 selected/deferred 拆分。 | 不硬编码供应商密钥或把估算当实际费用。 |
| `src/drawing_graph/assistant_semantic_gap_decision.py` | 新增语义缺口决策编排入口。 | 保持确定性和无副作用，不访问 facade、Neo4j、Qwen 或 repository。 |
| `src/drawing_graph/tool_models.py` / `semantic_query_projection.py` | 必要时补齐 interpretation 等语义摘要的模型、prompt、image hash、contract 和创建时间元数据。 | 保持 facade DTO 稳定，不让产品层决策逻辑反向进入投影模块。 |
| `src/drawing_graph/semantic_cache.py` | 继续作为统一 cache key 规范；必要时补充分离的只读 lookup 合同或缓存元数据。 | 不建立第二套缓存键规则，不在决策阶段写缓存。 |
| `src/drawing_graph/semantic_service.py` | 后续执行衔接时接受精确 targets/task type/output contract，并在供应商调用和持久化 run 前做最终缓存校验。 | 只负责执行识别，不负责产品级“是否值得识别”判断。 |
| `src/drawing_graph/semantic_client.py` / `qwen_semantic_client.py` | 后续承接精确目标、task type、输出合同及 token/cost/latency 指标。 | 模型输出只能成为语义观察、语义解释或候选证据，不能成为来源事实或正式关系。 |
| `src/drawing_graph/tool_facade.py` | 后续增加或兼容精确元素级识别入口，受控执行决策输出。 | 不开放任意 Cypher、repository 写回或候选提升捷径。 |
| `src/drawing_graph/tool_factory.py` | 装配决策策略、估算器和改造后的识别依赖。 | import 和工厂创建不得主动连接外部模型或数据库。 |
| 05 证据融合模块 | 消费 decision、cache status、selected/deferred targets 和识别结果。 | 不重新决定是否需要识别，不改变输入 fact kind。 |
| 06 答案生成模块 | 使用 missing requirements、预算/时延和 formal review 原因生成 partial、clarification 或 warning。 | 不把被裁剪目标掩盖成完整回答。 |
| 07 追溯反馈模块 | 记录充分性矩阵、缓存处置、估算与实际成本/时延、目标裁剪和识别运行。 | 运行审计不写成来源事实，用户反馈不直接提升 formal。 |
| `DrawingGraphQAService`、QA CLI/HTTP/MCP | 首阶段保持兼容，不接入完整产品决策闭环。 | 不在 adapter 或 QAService 中复制语义缺口业务逻辑。 |
| `tests/test_assistant_semantic_gap_*.py` 及相关测试 | 新增充分性、freshness、缓存、目标、预算、确定性、安全和静态依赖测试。 | 单元/fake、live DashScope、live Neo4j 分层报告，skipped 不等于通过。 |
| `architecture.md` / `Module.md` / 产品实现层文档 | 实施后同步模块职责、数据流、接口、状态和验证边界。 | 文档只描述当前已验证能力，不把后续完整助手或 live 能力提前写成已完成。 |
