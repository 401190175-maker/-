# 语义缺口决策闭环 Feature Analysis Report

**日期：** 2026-08-12  
**状态：** 新需求分析，不包含代码实现  
**需求名：** 增加语义缺口决策闭环  
**范围：** 充分性矩阵、freshness、缓存判断、预算/时延限制、最小识别目标规划

## 0. 结论摘要

当前架构对本需求是**部分支持**：产品公共合同、问题理解闭环、通用只读检索、语义证据、确定性缓存键、按需多模态识别和事实分层均已具备；但真正负责“证据是否足够、缓存是否仍有效、是否值得识别、识别哪些最小目标、是否超过预算/时延”的产品级决策服务尚未实现。

推荐采用**确定性策略引擎 + 可注入估算器 + 执行前二次缓存校验**的方案：

```text
QuestionUnderstandingResult + RetrievalBundle + RecognitionPolicy
  -> SufficiencyEvaluator
  -> FreshnessEvaluator
  -> CacheDecisionEvaluator
  -> RecognitionTargetPlanner
  -> RecognitionBudgetEvaluator
  -> SemanticGapDecisionService
  -> SemanticGapDecision
```

该方案应位于 `GraphRetrievalService` 之后、现有语义识别服务之前；默认只读，不调用 Qwen、不创建 `RecognitionRun`、不写缓存、不写 Neo4j、不提升候选关系。首阶段不需要修改 Neo4j schema，也不应把决策逻辑塞入 `DrawingGraphQAService`、adapter、`SemanticRecognitionService` 或答案生成模块。

## 1. 阅读范围与现状核对

本次按要求读取了：

- 项目根目录 `architecture.md`；
- 项目根目录 `Module.md`；
- `changes/产品实现层/00-product-closure-blueprint.md`；
- `changes/产品实现层/01-question-understanding.md`；
- `changes/产品实现层/02-graph-retrieval.md`；
- `changes/产品实现层/03-semantic-gap-decision.md`；
- `changes/产品实现层/04-multimodal-recognition.md`；
- `changes/产品实现层/05-evidence-fusion-and-cache.md`；
- `changes/产品实现层/06-answer-generation.md`；
- `changes/产品实现层/07-traceability-and-feedback.md`。

路径说明：用户描述中的 `图块图谱构造/` 与 `modules.md` 在当前工作区没有对应项；本报告以实际项目根目录 `C:\Users\40119\Desktop\图块图谱构建` 下的 `architecture.md` 和大小写敏感名称 `Module.md` 为准。

为判断“当前架构是否支持”，还只读核对了现有 `assistant_*.py`、`semantic_*.py`、`tool_models.py`、`tool_facade.py` 及相关测试索引。未修改任何 Python 源码或测试。

## 2. 当前架构是否支持？

### 2.1 已支持的基础

| 能力 | 当前状态 | 对本需求的价值 |
|---|---|---|
| 产品公共合同 | 已有 `AssistantRequest`、`EvidenceRequirement`、`EvidenceItem`、`RetrievalBundle` 等 DTO | 决策模块有稳定输入基础 |
| 问题理解 | `QuestionUnderstandingService` 与证据需求模板已实现 | 已能声明“需要什么证据” |
| 通用检索 | `GraphRetrievalService` 已实现 | 已能只读获取“当前有什么证据” |
| 事实分层 | source/derived/observation/interpretation/candidate/formal/diagnostic 已分桶 | 可防止低等级证据冒充高等级事实 |
| freshness 声明 | `EvidenceRequirement.freshness_policy` 已存在 | 具备策略字段，但尚无实际判定器 |
| 语义元数据 | observation/interpretation DTO 已包含部分 image hash、cache key、模型、prompt、合同版本信息 | 可作为 freshness 与缓存判断原料 |
| 确定性缓存键 | `SemanticCacheKeyInput` 已覆盖图片、bbox、任务、模型、prompt、预处理、规范化和合同版本 | 可复用，不必重建另一套 key 算法 |
| 语义缓存执行 | `SemanticRecognitionService` 已能跳过已缓存的元素 | 可作为执行阶段最后一道缓存保护 |
| 按需识别 | facade 与语义服务已有受控识别入口，默认 `write_back=false` | 可承接缺口模块输出 |
| 安全边界 | 模型结果、候选关系、正式关系和写回权限已明确分离 | 适合新增纯决策层 |

### 2.2 尚未支持的核心能力

当前源码中没有 `SemanticGapDecision`、`RecognitionPolicy`、`RecognitionTarget`、充分性评估结果或预算评估结果的运行时实现；相关概念目前只存在于产品文档。

具体缺口如下：

1. **没有逐项充分性矩阵。** `RetrievalBundle` 能分桶，但没有按每个 `EvidenceRequirement` 检查 scope、fact kind、状态、freshness、冲突和正式审核门槛。
2. **freshness 只有声明，没有执行语义。** 当前枚举包含 `any/current_image/current_prompt/current_contract`，但没有统一解释“多个维度同时要求当前”的组合规则，也没有判断服务。
3. **检索投影丢失部分决策元数据。** facade 的语义 DTO 含 `status`、`created_at`、`image_hash`、`cache_key`、`contract_version` 等字段，但 `RetrievalBundleBuilder` 没有把它们全部提升到稳定 `EvidenceItem` 元数据；页面来源事实投影也没有稳定携带页面 `image_hash`。若只从 `value` 字典临时解析，会造成合同脆弱和字段漂移。
4. **缓存判断分散在识别服务内部。** 当前没有产品级“完整命中/部分命中/失效/绕过”判断，也不能在调用识别服务前解释为什么复用或失效。
5. **当前识别接口不够精确。** `recognize_page_semantics()` / `recognize_page()` 主要按 `target_types` 选择页面内元素，不能直接消费带 `target_element_id + task_type + required_output + context` 的最小目标计划。
6. **当前 task type 粒度不足。** 语义服务构造缓存键时使用固定 `text_observation`，还不能稳定区分页面摘要、构件解释、断面标签、关系证据等输出合同。
7. **没有预算和时延门控。** 当前没有最大目标数、估算成本、剩余预算、总时延上限、重试余量或降级选择器。
8. **没有最小覆盖规划。** 多项证据需求如何合并为一个兼容目标、如何避免重复 bbox、如何在预算不足时保留最关键目标，尚无算法和稳定规则。
9. **严格的“缓存命中不创建 RecognitionRun”尚未在所有执行路径成立。** 当前语义服务会先生成临时 run ID；在 `write_back=true` 路径中还可能先创建运行日志再进行内部缓存检查。产品闭环需要把可复用判断前移，并在执行前再次核验缓存，避免无意义运行记录。

因此结论是：**架构方向支持，基础组件可复用，但 03 语义缺口决策闭环本身尚未落地，且现有检索投影和识别入口需要小范围补口。**

## 3. 需求边界与决策职责

语义缺口决策模块只负责作出可解释决定，不负责执行副作用。

它应负责：

- 对每项证据需求生成充分/不足/过期/冲突评估；
- 计算预期缓存键并判断缓存候选；
- 形成最小、确定、有序的识别目标集合；
- 估算目标数、成本和时延，执行策略门控；
- 返回稳定 decision、reason codes、missing requirements、deferred targets 和 warning；
- 给出 `write_back_recommendation`，但不改变请求授权。

它不应负责：

- 不调用 `DrawingGraphToolFacade` 或 Neo4j；
- 不调用 Qwen/DashScope；
- 不创建或持久化 `RecognitionRun`；
- 不写缓存、payload、语义证据或正式关系；
- 不融合冲突证据为最终 claim；
- 不生成最终中文答案；
- 不把 candidate、`matched_candidate` 或模型解释提升为 formal。

## 4. 需要新增哪些模块？

建议采用“一个编排服务 + 四个窄职责组件 + 公共 DTO 扩展”，避免把所有逻辑堆进一个大类。

| 模块 | 建议文件 | 单一职责 |
|---|---|---|
| 公共决策合同 | 扩展 `src/drawing_graph/assistant_models.py` | 定义 decision、逐需求评估、freshness/cache 结果、识别目标、预算估算、稳定原因码 |
| 充分性评估器 | `src/drawing_graph/assistant_evidence_sufficiency.py` | 按 requirement 对证据做 scope/fact kind/status/formal gate/conflict 检查，输出逐项矩阵 |
| freshness 与缓存评估器 | `src/drawing_graph/assistant_evidence_freshness.py` | 比较图片、bbox、task、模型、prompt、预处理、规范化、合同版本及 stale/rejected 状态，生成缓存处置 |
| 最小识别目标规划器 | `src/drawing_graph/assistant_recognition_target_planner.py` | 从未满足需求生成元素级/页面级目标，做兼容合并、覆盖去重、上下文最小化和稳定排序 |
| 预算/时延评估器 | `src/drawing_graph/assistant_recognition_budget.py` | 用可注入估算器计算 cost/latency 上界，应用 max targets、预算和时延限制，返回 selected/deferred targets |
| 决策编排服务 | `src/drawing_graph/assistant_semantic_gap_decision.py` | 串联上述组件，输出唯一 `SemanticGapDecision`，不执行识别或写回 |
| 模块测试 | `tests/test_assistant_semantic_gap_*.py` | 充分性矩阵、freshness、缓存、预算、时延、最小目标、安全不变量和编排顺序 |

不建议为矩阵单独引入数据库或规则引擎框架。首版用版本化、不可变的 Python 策略表即可；当策略需要业务配置化时，再抽象 `SemanticGapPolicyProvider`。

## 5. 充分性矩阵设计

### 5.1 逐需求矩阵

每个 `EvidenceRequirement` 应生成一条 `RequirementAssessment`，而不是只给整包 evidence 一个总分。

| 检查维度 | 判定问题 | 失败结果示例 |
|---|---|---|
| 目标存在性 | 是否有证据绑定到所需稳定 scope | `scope_missing` / `evidence_missing` |
| scope 精确匹配 | page/block/element 是否与目标一致 | `scope_mismatch` |
| fact kind | 证据层级是否满足需求 | `evidence_kind_mismatch` |
| 状态 | 是否属于该证据类型可接受状态集合 | `status_insufficient` |
| freshness | 图片、bbox、模型、prompt、合同等是否满足策略 | `image_changed` / `prompt_version_changed` |
| 冲突 | 是否存在同目标同字段冲突或等价候选 | `evidence_conflict` |
| formal gate | 要求正式关系时是否真的有 formal | `formal_review_required` |
| 生成许可 | 缺口是否允许模型补充 | `recognition_forbidden` / `unsupported_evidence_type` |

输出至少应包含：`requirement_id`、`assessment_status`、`matched_evidence_ids`、`rejected_evidence_ids`、`reason_codes`、`freshness_result`、`cache_disposition` 和 `recognition_capability`。

### 5.2 不使用一个全局状态排序

`confirmed > partial > ambiguous` 不能作为所有证据类型的统一排序。例如 candidate 即使状态为 accepted，也不能自动满足 formal requirement；来源事实也不应按模型置信度排序。

推荐按 `evidence_type + fact_kind` 定义允许状态集合：

- `source_fact`：目标存在且来源字段完整即可；
- `semantic_observation`：通常接受 `confirmed`，特定问法可接受 `partial`，拒绝 `stale/rejected/recognition_failed`；
- `semantic_interpretation`：按问题需要接受 `confirmed` 或带限定语的 `partial/ambiguous`；
- `candidate_relation`：只能满足“有哪些候选/是否存在待确认关系”；
- `formal_relation`：只能由正式关系证据满足，candidate 和模型输出永远不能替代。

### 5.3 典型问题矩阵

| 问题 | 充分条件 | 缺口动作 |
|---|---|---|
| 图块在哪里 | block trace + 页面/bbox 来源事实 | 来源事实缺失时澄清或 unsupported，不调用模型猜位置 |
| 图块是什么构件 | 当前图片上的有效 block interpretation | 规划单个 block 的语义解释目标 |
| 标记写了什么 | 当前图片上的有效 element observation | 规划单个 element 文字观察目标 |
| 断面对应哪个标题 | 双方有效 observation + 正式匹配或可说明的候选状态 | 只识别缺 observation 的一方；formal 缺失时返回待复核，不靠识别直接确认 |
| 是否为正式关系 | formal relation | 只有 candidate 时返回 `formal_review_required`，不生成“正式”答案 |
| 页面摘要 | 页面来源事实 + 满足策略的页面级语义摘要 | 只做一次页面任务，不默认扫描全部元素 |

## 6. Freshness 与缓存判断方案

### 6.1 freshness 应以内容和版本为主

工程图纸语义证据的 freshness 不应只理解为 TTL。首版应按以下维度判断：

1. `image_hash` 是否仍是当前页面图片；
2. bbox 与目标元素 ID 是否仍对应当前目标；
3. `task_type` 与 `required_output` 是否兼容；
4. `model_profile/model_version` 是否满足策略；
5. `prompt_version` 是否满足策略；
6. `preprocessing_version` 与 `normalization_rule_version` 是否满足策略；
7. `output_contract_version` 是否满足策略；
8. 证据状态是否为 `stale/rejected/conflicting`；
9. 可选 TTL 是否适用于供应商行为变化明显的任务。

现有 `FreshnessPolicy` 是单值枚举，难以表达“当前图片 + 当前 prompt + 当前合同”的组合。建议保持旧值兼容，同时新增可组合的 `FreshnessRequirement` 或策略位集合；不要用自由文本拼接组合条件。

### 6.2 二阶段缓存判断

推荐采用两阶段判断，避免决策和执行之间发生状态变化：

```text
决策阶段：根据 RetrievalBundle 与预期 cache key 判断 full/partial/miss/stale
  -> 生成 selected RecognitionTarget
执行阶段：SemanticRecognitionService 在供应商调用前重算同一 cache key
  -> 若此时命中，直接复用，不调用 Qwen，不创建持久化 RecognitionRun
```

`cache_disposition` 建议固定为：

- `full_hit`：所有必需证据均由有效缓存/持久化证据满足；
- `partial_hit`：仅部分需求满足，只规划剩余目标；
- `miss`：没有兼容证据；
- `stale`：存在证据，但图片/版本/状态不满足；
- `bypassed`：策略明确要求跳过缓存；
- `unknown`：缺少形成确定判断的元数据。

缓存键算法应直接复用 `semantic_cache.py`，不在产品层复制另一套 hash 拼接逻辑。产品层可以构造标准 `SemanticCacheKeyInput`，但不直接写缓存。

## 7. 最小识别目标规划

### 7.1 RecognitionTarget 合同

每个目标至少应包含：

```text
target_id
page_id
target_element_id
target_type
task_type
required_outputs
bbox
context_element_ids
covered_requirement_ids
priority
estimated_cost
estimated_latency_ms
reason_codes
```

### 7.2 规划规则

1. 先过滤已经充分或可复用缓存的 requirement；
2. 按稳定 scope 找到来源事实中的 `image_path/image_hash/bbox/element_type`；
3. 缺定位证据时停止，不让模型猜路径、bbox 或对象；
4. 同一目标、同一 task type、兼容输出合同合并；
5. 不同 prompt/output contract 不合并，也不共享缓存；
6. element/block 问题优先局部 bbox；页面摘要才使用整页；
7. context 只带回答该 requirement 所需的最小邻近元素；
8. 目标按 required 优先、覆盖需求数、粒度、成本、时延和稳定 ID 排序；
9. 被预算裁掉的目标进入 `deferred_targets`，不能静默消失。

### 7.3 选择算法

首版推荐确定性贪心覆盖，不需要复杂优化器：

- 先选所有“唯一能覆盖必需 requirement”的目标；
- 再按“新增覆盖的必需 requirement 数 / 保守估算成本”排序；
- 成本相同则选范围更小、预估时延更低的目标；
- 最后用 `target_id` 保证输出顺序稳定。

如果必需目标本身已超过硬限制，不应伪装为成功最优解；应返回 `budget_exceeded` 或 `latency_exceeded`，并建议缩小 scope。

## 8. 预算与时延限制

### 8.1 RecognitionPolicy

建议至少包含：

- `allow_recognition`；
- `max_targets`；
- `max_estimated_cost`；
- `max_latency_seconds`；
- `preferred_model_profile`；
- `model_version_policy`；
- `prompt_version_policy`；
- `output_contract_version`；
- `max_attempts`；
- `reserve_latency_seconds`；
- `cache_mode`；
- `estimation_mode`（保守上界或历史 p95）。

### 8.2 估算原则

- 价格和模型能力配置应由可注入 profile/catalog 提供，不把供应商费率硬编码在决策算法中；
- 成本是估算，不写成实际账单；实际 token、费用和时延由识别结果与追溯模块记录；
- 时延优先使用同 `task_type + model_profile + 图像尺寸桶` 的历史 p95，无历史时使用保守静态上界；
- 重试余量必须计入总时延，不能只估一次调用；
- 无法估算且存在硬预算时应 fail closed，返回 `estimate_unavailable`，不能假定为零成本；
- `allow_recognition=false` 是绝对门槛，任何其他策略不得覆盖。

## 9. 影响哪些已有模块？

| 已有模块 | 影响程度 | 需要的变化 | 不应发生的变化 |
|---|---:|---|---|
| `assistant_models.py` | 高 | 增加决策 DTO、枚举、原因码、预算与目标合同；补充 freshness 组合表达 | 不改变默认 `allow_write_back=false` |
| `assistant_evidence_templates.py` | 中 | 为语义类需求明确 `minimum_status`、freshness 和 `allow_model_generation`；断面问题补齐双方 observation 需求 | 不读取图谱、不做充分性判断 |
| `assistant_retrieval_projection.py` | 高 | 稳定投影 status、image hash、cache key、模型/prompt、contract、created at；页面来源事实保留 image hash | 不在 projection 中决定是否识别 |
| `assistant_retrieval_planner.py` | 中 | 必要时确保语义需求同时获取定位来源事实与当前图片元数据 | 不调用 Qwen、不读缓存写口 |
| `assistant_retrieval_service.py` | 低 | 保持为上游只读输入；接口原则上可不变 | 不吸收语义缺口逻辑 |
| `tool_models.py` / `semantic_query_projection.py` | 中 | 补齐 interpretation 的模型、prompt、image hash/created at 等判断所需元数据，或提供稳定 evidence metadata | 不让产品层 DTO 反向污染 facade 内部实现 |
| `semantic_cache.py` | 中 | 复用统一 key；必要时拆出只读 lookup 协议和缓存元数据 | 不复制第二套缓存键算法 |
| `semantic_service.py` | 高 | 接受精确 targets/task type/output contract；供应商调用和持久化 run 前做最终缓存校验 | 不承担“是否值得识别”的产品决策 |
| `semantic_client.py` / `qwen_semantic_client.py` | 中 | 承接 task type、精确目标、输出合同以及 token/cost/latency 指标 | 不决定正式关系，不接收密钥字段进入领域 DTO |
| `tool_facade.py` | 中高 | 增加或兼容精确元素级识别入口，仍由 facade 受控执行 | 不开放任意 Cypher、repository 或候选提升捷径 |
| `tool_factory.py` | 中 | 装配决策所需策略/估算器及改造后的识别依赖 | 不在 import 时连接外部服务 |
| `DrawingAssistantService` | 后续高 | 未来串联 retrieve -> decide -> recognize -> fuse | 本需求阶段不必一次实现完整 00-07 |
| 05 证据融合 | 中 | 消费 decision、cache status、selected/deferred targets 和识别结果 | 不重新决定是否识别 |
| 06 答案生成 | 中 | 根据 budget/forbidden/stale/formal review reason 生成 partial/clarification 提示 | 不把预算裁剪掩盖成完整回答 |
| 07 追溯反馈 | 中 | 记录矩阵、缓存处置、估算与实际成本/时延、目标裁剪原因 | 不把运行审计写成来源事实 |
| 现有 QA CLI/HTTP/MCP | 低 | 首阶段保持不变；未来产品 adapter 另行接入 | 不把完整决策逻辑塞进 adapter 或 QAService |

推荐方案首阶段不改变 Neo4j 节点、关系、约束或索引，不创建 `RecognitionRun` 图谱节点，不设置 `DrawingBlock.block_type`。

## 10. 技术方案

### 方案 A：在 `SemanticRecognitionService` 内部补规则

识别服务收到页面后自行检查现有证据、缓存、预算和目标，再决定是否调用模型。

优点：改动文件少，缓存和模型调用在一个位置。  
缺点：把“是否识别”和“如何识别”混在一起；服务需要理解问题、证据充分性和预算；难以在调用前输出可解释 decision，也难以独立测试 candidate/formal 边界。

### 方案 B：独立确定性语义缺口策略引擎

在产品层新增纯决策服务，消费问题理解与检索结果，输出明确目标和原因码；识别服务只执行目标，并在执行前做最终缓存校验。

优点：边界清晰、可解释、可单测、可重放；与 00-07 设计一致；预算不足和禁止识别时不会进入模型层；便于保留默认只读和事实分层。  
缺点：需要补齐公共 DTO 和检索元数据；决策缓存与执行缓存必须使用同一 key 规范；组件数量略增。

### 方案 C：由 LLM/Agent 判断缺口和规划工具

把 `RetrievalBundle` 交给文本模型，让模型决定是否识别、识别哪些目标及预算优先级。

优点：对新问题类型适应快，原型代码少。  
缺点：不可稳定复现，成本和时延门控不可靠；容易把 candidate/interpretation 当正式事实；难以证明 `allow_recognition=false` 与硬预算绝不会被绕过；模型还可能生成不存在的 ID、bbox 或工具调用。

### 方案 D：固定模板表，不单独建决策服务

按 question type 写死“缺什么就识别什么”，不建立逐需求矩阵和统一策略。

优点：首批场景开发快。  
缺点：freshness、缓存、预算、冲突和多需求合并会分散到各模块；规则很快重复，后续 04-07 难以复用一致原因码。

## 11. 优缺点比较

| 方案 | 架构一致性 | 可解释性 | 最小目标能力 | 硬预算可靠性 | 实施规模 | 推荐度 |
|---|---:|---:|---:|---:|---:|---:|
| A 识别服务内嵌 | 中低 | 中 | 中 | 中 | 低到中 | 低 |
| B 独立确定性策略引擎 | 高 | 高 | 高 | 高 | 中 | **最高** |
| C LLM/Agent 决策 | 低 | 低 | 不稳定 | 低 | 原型低、治理高 | 不推荐 |
| D 固定模板分散实现 | 中低 | 中 | 低 | 中 | 初期低、长期高 | 低 |

## 12. 推荐方案

推荐**方案 B：独立确定性语义缺口策略引擎**。

推荐主线：

```text
QuestionUnderstandingResult
  + RetrievalBundle
  + RecognitionPolicy
  -> SemanticGapDecisionService
       1. Requirement-by-requirement sufficiency matrix
       2. Freshness and cache disposition
       3. Missing requirement classification
       4. Minimum recognition target generation and merge
       5. Conservative cost/latency estimation
       6. Hard policy gating and selected/deferred split
  -> SemanticGapDecision
       decision
       requirement_assessments
       missing_requirements
       cache_candidates
       selected_targets
       deferred_targets
       estimates
       reason_codes
       write_back_recommendation
       warnings
```

decision 保持现有文档的四个稳定值：`reuse_existing`、`recognize_required`、`clarification_required`、`unsupported`。其中 `reuse_existing` 只表示“不再识别并继续使用现有证据”，不保证最终一定是完整回答；预算不足或禁止识别但仍有部分证据时，可由 `missing_requirements + reason_codes` 交给融合/答案模块形成 `partial`。如果完全没有可回答证据，则使用 `unsupported` 或 `clarification_required`。

建议分三阶段实施：

1. **纯决策核心：** DTO、充分性矩阵、freshness、原因码和 deterministic tests；不接真实模型。
2. **目标与策略：** 最小目标合并、预算/时延估算、selected/deferred 结果；仍不调用真实模型。
3. **执行衔接：** 改造精确目标识别入口和执行前缓存二次校验，再由后续 `DrawingAssistantService` 串联。

首阶段验收不要求 live DashScope 或 live Neo4j；只有后续执行衔接才需要分别验证离线客户端合同、live DashScope、dry-run、live Neo4j 写回。

## 13. 风险与缓解

| 风险 | 表现 | 缓解措施 |
|---|---|---|
| 充分性规则过度简化 | 用全局状态排序把 partial/candidate 当成足够证据 | 按 evidence type/fact kind 定义允许状态集合；formal 单独硬门槛 |
| freshness 语义漂移 | 各模块对 current 的理解不同 | 统一可组合策略和原因码；统一 key 输入规范 |
| 元数据投影缺失 | 决策层只能从 `value` 私有字段猜 image hash/cache key | 把决策所需元数据纳入稳定 EvidenceItem 投影合同 |
| 决策与执行缓存竞态 | 决策为 miss，执行前已有其他请求写入缓存 | 执行前按同一 key 二次检查；命中则取消供应商调用 |
| 缓存命中仍创建 run | 产生无意义成本/运行记录，违反产品合同 | 将持久化 run 创建移动到最终 cache miss 之后 |
| 目标合并错误 | 不同 task/prompt/contract 被合并，复用错误缓存 | 只合并兼容输出合同；key 必须包含 task 和版本维度 |
| 页面级识别范围膨胀 | 为回答一个元素问题扫描整页全部元素 | 优先元素/bbox；页面级仅用于明确页面摘要 |
| 成本估算失真 | 把估算当账单，或价格变化后策略失效 | 费率由外部 profile 注入；保留估算版本；追溯中对比实际值 |
| 时延估算失真 | 忽略重试、排队和图片大小 | 使用 p95/保守上界并预留重试时延；无估算时硬限制 fail closed |
| 预算裁剪不可见 | 系统少识别目标却声称完整回答 | 输出 deferred targets 和 `budget_exceeded/latency_exceeded`，下游必须生成 partial/warning |
| `allow_recognition` 越权 | 其他策略覆盖用户禁止识别 | 将其设为第一优先级绝对门槛并做属性测试 |
| `write_back` 越权 | 决策建议被当成授权 | recommendation 与 authorization 分离；最终写回仍取多条件逻辑与 |
| candidate/formal 混淆 | 模型识别后直接确认正式关系 | 充分性矩阵和答案合同双重保护；正式提升仍只经审核与硬规则 |
| 决策模块职责膨胀 | 开始查询图谱、调用模型、融合或写回 | 以静态依赖测试保护纯产品层边界 |
| 与 05 缓存职责重复 | 03 判断缓存，05 又重新决定是否识别 | 03 负责“能否复用/是否需识别”；05 负责“融合与写回结果”，职责写入合同 |
| Live 验证误报 | 单元测试通过后宣称 Qwen/Neo4j 闭环已通过 | 单元、离线模型合同、live DashScope、live Neo4j 分开报告；skipped 不等于通过 |

## 14. 建议完成标准

未来实现本需求时，至少应满足：

- 每个 `EvidenceRequirement` 都有独立、可解释、可序列化的 assessment；
- source、derived、observation、interpretation、candidate、formal 不发生层级替代；
- freshness 同时支持图片、bbox、task、模型、prompt、预处理、规范化和合同版本；
- full hit 不产生识别目标，partial hit 只产生剩余目标；
- 相同兼容目标稳定合并，不同输出合同不错误共享缓存；
- `allow_recognition=false`、max targets、预算和时延限制均为硬门槛；
- 超限目标明确进入 deferred，不静默丢弃；
- 最小目标可以精确到 element/bbox，页面问题才允许整页；
- 决策模块不调用 facade、Qwen、repository、Neo4j 或写缓存；
- 执行前进行第二次缓存核验，缓存命中不调用供应商；
- 默认 `allow_write_back=false`，决策永远不能把它改为 true；
- candidate 永远不能满足 formal requirement；
- 单元/fake、live DashScope、live Neo4j 的验证状态分别报告。

## 15. 最终结论

本需求与当前产品架构是顺向演进关系，不需要推翻已有 `QuestionUnderstandingService`、`GraphRetrievalService`、`DrawingGraphToolFacade` 或语义证据层。真正需要补齐的是它们之间的产品级“决策层”：把证据需求与已有证据逐项对齐，以内容和版本判 freshness，以统一 cache key 判断复用，以硬预算/时延策略约束调用，并把缺口压缩成最小可执行识别目标。

最稳妥的实现方向是独立、确定性、无副作用的 `SemanticGapDecisionService`。它输出的是“为什么需要或不需要识别、识别什么、哪些目标因策略被延后”，而不是直接执行模型调用。这样既能满足自动闭环，也能继续保持本项目最重要的安全边界：图谱优先、默认只读、来源事实不可被模型覆盖、候选不冒充正式、所有运行和验证状态可追溯。

## 16. 实施状态更新（2026-08-12）

已实现：

- 产品公共合同扩展：`SemanticGapDecisionType`、`RequirementAssessmentStatus`、`CacheDisposition`、`RecognitionTargetStatus`、`EstimateStatus` 与 evidence/freshness/cache/budget/formal/target 原因码；`FreshnessRequirement`/`FreshnessResult`/`CacheCandidate`/`RecognitionPolicy`/`RequirementAssessment`/`RecognitionTarget`/`RecognitionEstimate`/`SemanticGapDecision` DTO；`EvidenceItem.evidence_metadata` 稳定元数据。
- 03 纯决策模块：充分性（scope/fact kind/formal gate/状态冲突/生成许可）、freshness/cache（统一 `semantic_cache` key，full/partial/miss/stale/bypassed/unknown）、最小目标规划（element/bbox/page、合并去重、稳定排序、缺定位 blocked）、预算/时延硬门控与 `SemanticGapDecisionService` 编排。
- 执行衔接预留：`SemanticTargetInput` 精确目标合同、`DrawingGraphToolFacade.recognize_semantic_targets()`、`SemanticRecognitionService.recognize_targets()`（执行前二次缓存校验，命中不调用供应商、不创建持久化 run log）、`create_semantic_gap_decision_service()`。
- 文档与测试：`architecture.md`/`Module.md`/`README.md` 同步；`tests/test_assistant_semantic_gap_*.py` 与静态边界测试覆盖。

未实现（后续范围）：

- 完整 `DrawingAssistantService` 端到端产品编排。
- 证据融合、最终 claim/答案生成、中文答案生成与用户反馈状态机。
- 产品级 CLI/HTTP/MCP/Web UI adapter；`DrawingGraphQAService` 六类只读问答不改造成完整自然语言产品服务。
- Neo4j schema 变更、语义证据写回、候选审核/正式关系提升与 `RecognitionRun` 图谱节点。

验证状态：单元/fake、合同与静态边界测试通过；live DashScope 与 live Neo4j 未验证，skipped live 测试不等于通过；默认 `write_back=false`，candidate 不等于 formal。
