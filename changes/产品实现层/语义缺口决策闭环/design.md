# 语义缺口决策闭环 Design

**文档状态：** 技术方案  
**日期：** 2026-08-12  
**适用范围：** 产品实现层 03 语义缺口决策模块  
**设计依据：** `proposal.md`、`Feature_Analysis_Report.md`、产品实现层 00-07 文档、当前 `architecture.md`、`Module.md` 与已落地的产品公共合同/通用检索闭环。

## 1. 设计目标

本设计在 `QuestionUnderstandingService` 与 `GraphRetrievalService` 之后新增独立的语义缺口决策闭环，用于回答：

- 当前检索到的证据是否足够回答每个 `EvidenceRequirement`；
- 已有语义证据是否仍满足图片、bbox、模型、prompt 和输出合同版本的 freshness 要求；
- 是否可以复用已有缓存或持久化语义证据；
- 是否需要调用多模态识别；
- 如果需要识别，应识别哪些最小目标；
- 当前策略是否允许识别，以及是否超过目标数、预算或时延上限。

本模块只做确定性判断和目标规划，不执行任何副作用。它不调用 `DrawingGraphToolFacade`、不访问 Neo4j、不调用 Qwen/DashScope、不创建 `RecognitionRun`、不写缓存、不写 payload、不写语义证据、不提升候选关系、不生成最终答案。

## 2. 系统架构变化

### 2.1 当前链路

当前产品层已经具备公共合同、问题理解和只读检索基础：

```text
AssistantRequest
  -> QuestionUnderstandingService
  -> QuestionUnderstandingResult
  -> GraphRetrievalService
       -> RetrievalPlanner
       -> RetrievalExecutor
       -> RetrievalBundleBuilder
  -> RetrievalBundle
```

语义识别能力当前仍通过 facade/semantic service 受控执行：

```text
DrawingGraphToolFacade.recognize_page_semantics(...)
  -> SemanticRecognitionService
  -> MultimodalRecognitionClient
  -> TextObservation / Interpretation
```

是否识别主要由外部调用方显式触发，缺少产品级“证据是否足够、是否值得识别”的中间决策层。

### 2.2 新增目标链路

新增 `SemanticGapDecisionService` 后，产品层内部链路调整为：

```text
AssistantRequest
  -> QuestionUnderstandingService
  -> QuestionUnderstandingResult
  -> GraphRetrievalService
  -> RetrievalBundle
  -> SemanticGapDecisionService
       -> EvidenceSufficiencyEvaluator
       -> EvidenceFreshnessEvaluator
       -> RecognitionTargetPlanner
       -> RecognitionBudgetEvaluator
  -> SemanticGapDecision
  -> 后续 04 MultimodalRecognitionService 或 05 EvidenceFusionService
```

依赖方向保持：

```text
Product layer
  -> assistant_models.py DTO
  -> semantic gap pure evaluators
  -> RetrievalBundle / EvidenceItem

Semantic gap module 不依赖：
  Neo4j driver / repository / Cypher
  DrawingGraphToolFacade
  SemanticRecognitionService
  HTTP / MCP / CLI adapter
  Qwen / DashScope client
```

### 2.3 与 04-07 的边界

语义缺口决策模块输出“是否需要识别”和“识别什么”，但不执行识别。后续模块职责保持清晰：

| 模块 | 消费 03 的内容 | 不应由 03 完成 |
|---|---|---|
| 04 多模态识别 | `selected_targets`、`RecognitionPolicy`、cache key 输入 | 调用供应商、解析模型输出、写 run log |
| 05 证据融合 | `requirement_assessments`、`cache_dispositions`、识别结果 | 重新决定是否识别 |
| 06 答案生成 | `reason_codes`、`deferred_targets`、缺失需求 | 伪装成完整回答 |
| 07 追溯反馈 | 充分性矩阵、预算/时延、目标裁剪原因 | 把运行审计写成来源事实 |

### 2.4 不改变的架构

本设计不改变现有 QA、HTTP、MCP 链路：

```text
QA adapter
  -> DrawingGraphQAService
  -> DrawingGraphToolFacade
```

首阶段不新增产品级 CLI/HTTP/MCP/Web UI adapter，不把语义缺口逻辑塞进 `DrawingGraphQAService` 或 adapter，不重构现有 facade、QAService、HTTP/MCP 安全策略。

## 3. 新增模块

### 3.1 公共合同扩展：`assistant_models.py`

在 `src/drawing_graph/assistant_models.py` 中增加产品层 DTO 和枚举。该文件继续保持纯公共合同，不依赖数据库、HTTP、MCP、Qwen 或 repository。

建议新增枚举：

| 枚举 | 值 |
|---|---|
| `SemanticGapDecisionType` | `reuse_existing`、`recognize_required`、`clarification_required`、`unsupported` |
| `RequirementAssessmentStatus` | `satisfied`、`missing`、`stale`、`conflicting`、`forbidden`、`unsupported`、`formal_review_required` |
| `CacheDisposition` | `full_hit`、`partial_hit`、`miss`、`stale`、`bypassed`、`unknown` |
| `RecognitionTargetStatus` | `selected`、`deferred`、`blocked` |
| `EstimateStatus` | `estimated`、`not_required`、`estimate_unavailable`、`budget_exceeded`、`latency_exceeded` |

建议扩展 `ReasonCode`，至少新增：

```text
evidence_complete
evidence_missing
observation_missing
interpretation_missing
evidence_stale
image_changed
bbox_changed
model_profile_changed
prompt_version_changed
contract_version_changed
preprocessing_version_changed
normalization_rule_changed
evidence_conflict
status_insufficient
evidence_kind_mismatch
recognition_forbidden
budget_exceeded
latency_exceeded
estimate_unavailable
formal_review_required
unsupported_generation
cache_key_unavailable
target_location_missing
```

建议新增 DTO：

| DTO | 职责 |
|---|---|
| `FreshnessRequirement` | 表达可组合 freshness 维度，兼容旧 `FreshnessPolicy` |
| `FreshnessResult` | 记录 image/bbox/model/prompt/contract 等维度是否满足 |
| `CacheCandidate` | 记录预期 cache key、命中状态、可复用证据 ID |
| `RequirementAssessment` | 每个 `EvidenceRequirement` 的充分性评估结果 |
| `RecognitionPolicy` | 识别授权、目标数、预算、时延、模型和版本策略 |
| `RecognitionTarget` | 最小识别目标，精确到 page/block/element/bbox/task/output contract |
| `RecognitionEstimate` | 目标数、成本、时延和估算状态 |
| `SemanticGapDecision` | 决策服务的统一输出 |

`SemanticGapDecision` 建议字段：

```text
request_id
subrequest_id
decision
requirement_assessments[]
missing_requirements[]
cache_candidates[]
selected_targets[]
deferred_targets[]
estimate
reason_codes[]
write_back_recommendation
warnings[]
contract_version
```

### 3.2 充分性评估器：`assistant_evidence_sufficiency.py`

职责：逐个 `EvidenceRequirement` 比较 `RetrievalBundle` 中的证据，输出 `RequirementAssessment` 的基础状态。

核心规则：

1. 按 `requirement_id` 独立评估，不只给整个 `RetrievalBundle` 一个总状态；
2. scope 必须匹配目标稳定业务 ID；
3. `fact_kind` 不能被提升或替代；
4. `minimum_status` 按证据类型解释，不建立一个全局状态排序；
5. candidate 不能满足 formal requirement；
6. observation 不能满足 interpretation requirement；
7. semantic interpretation 不能满足 source fact requirement；
8. 缺失且 `allow_model_generation=false` 时，输出 `recognition_forbidden` 或 `unsupported_generation`。

输入：

```text
QuestionUnderstandingResult
RetrievalBundle
```

输出：

```text
tuple[RequirementAssessment, ...]
```

### 3.3 Freshness 与缓存评估器：`assistant_evidence_freshness.py`

职责：判断已匹配证据是否满足 freshness 策略，并构造可解释的 cache disposition。

核心规则：

- 复用 `semantic_cache.SemanticCacheKeyInput` 与 `build_semantic_cache_key()`；
- 不复制第二套 cache key 算法；
- 决策阶段只读判断，不写缓存；
- 缺少 `image_hash`、bbox、task type、model version、prompt version 或 contract version 时输出 `unknown`，不能默认为有效；
- `stale`、`rejected`、`recognition_failed`、冲突证据不得作为有效缓存命中。

输入：

```text
RequirementAssessment
RetrievalBundle
RecognitionPolicy
```

输出：

```text
RequirementAssessment with freshness_result and cache_disposition
tuple[CacheCandidate, ...]
```

### 3.4 最小目标规划器：`assistant_recognition_target_planner.py`

职责：把未满足且允许模型生成的需求转为最小 `RecognitionTarget`。

规划规则：

1. 只为缺失、过期或缓存未命中的 requirement 生成目标；
2. 目标优先精确到 `target_element_id` 或 bbox；
3. 只有明确页面摘要任务才允许整页目标；
4. 缺少可信 `image_path`、`image_hash`、bbox 或稳定业务 ID 时，不生成目标，输出 `target_location_missing`；
5. 同一目标、同一 `task_type`、兼容 `required_outputs` 和输出合同可以合并；
6. 不同 prompt/output contract 不合并；
7. context 只包含当前目标所需的最小邻近元素 ID；
8. 输出顺序稳定，不能依赖 dict 遍历偶然顺序。

输出的 `RecognitionTarget` 至少包含：

```text
target_id
page_id
target_element_id
target_type
task_type
required_outputs[]
bbox
normalized_bbox
context_element_ids[]
covered_requirement_ids[]
cache_key
priority
reason_codes[]
```

### 3.5 预算与时延评估器：`assistant_recognition_budget.py`

职责：对候选目标执行硬门控，输出 selected/deferred 拆分。

模块包含：

- `RecognitionCostProfile`：可注入模型、任务、图像范围的保守估算配置；
- `RecognitionEstimator`：估算单目标 cost/latency；
- `RecognitionBudgetEvaluator`：执行 `allow_recognition`、`max_targets`、`max_estimated_cost`、`max_latency_seconds` 门控。

约束：

- 成本估算不是实际账单；
- 价格、模型能力、时延上界不硬编码在算法内部；
- 无法估算且存在硬预算时，返回 `estimate_unavailable`，不能按零成本处理；
- `allow_recognition=false` 是绝对门槛；
- 被裁剪目标进入 `deferred_targets`，不能静默丢弃。

### 3.6 决策编排服务：`assistant_semantic_gap_decision.py`

职责：串联充分性、freshness/cache、目标规划和预算门控，生成唯一 `SemanticGapDecision`。

推荐编排顺序：

```text
1. validate inputs
2. evaluate requirement sufficiency
3. evaluate freshness and cache disposition
4. build missing requirement list
5. plan recognition targets
6. evaluate budget and latency
7. derive final decision
8. attach warnings and reason codes
```

最终 decision 规则：

| 条件 | decision |
|---|---|
| 所有 required requirement 满足，或仅剩 formal review warning | `reuse_existing` |
| 存在可生成缺口，且策略允许识别，且至少一个目标被选中 | `recognize_required` |
| 缺少 scope、image path、bbox、合法稳定 ID 或需要用户缩小范围 | `clarification_required` |
| 缺口不可生成、禁止识别且无可回答证据、或证据类型不支持 | `unsupported` |

`reuse_existing` 只表示“不需要识别”，不等于最终答案一定是 `answered`。最终 answer status 由 05/06 根据可回答程度决定。

## 4. 修改模块

### 4.1 `assistant_models.py`

修改内容：

- 增加 03 所需 DTO、枚举和原因码；
- 保持已有 `AssistantRequest.allow_write_back=False` 默认不变；
- 保持公共合同模块无外部依赖；
- DTO 校验应拒绝空 ID、负数预算、非法枚举、非布尔授权字段。

不做：

- 不引入 Neo4j、FastAPI、MCP、Qwen、repository 依赖；
- 不把 `write_back_recommendation` 变成授权字段。

### 4.2 `assistant_evidence_templates.py`

修改内容：

- 为语义类问题补齐 `minimum_status`；
- 为需要模型补证的需求显式设置 `allow_model_generation=true`；
- 为需要当前图片、当前 prompt 或当前合同的需求补充 freshness 约束；
- 断面匹配问题应表达双方 observation 与候选/正式关系需求。

不做：

- 不读取图谱；
- 不判断已有证据是否充分；
- 不调用模型。

### 4.3 `assistant_retrieval_planner.py`

修改内容：

- 确保语义缺口决策所需的定位来源事实被检索，例如 page image meta、block trace、element bbox；
- 对语义需求保留 requirement ID，以便决策层回溯每个 requirement。

不做：

- 不加入 freshness、预算或识别目标规划逻辑；
- 不调用 cache 写口或模型。

### 4.4 `assistant_retrieval_projection.py`

修改内容：

- 将决策所需元数据稳定投影到 `EvidenceItem` 的顶层字段或明确 `value.metadata`；
- 语义 observation/interpretation 至少稳定携带 `status`、`image_hash`、`cache_key`、`model_profile`、`model_version`、`prompt_version`、`contract_version`、`created_at_or_version`；
- 页面来源事实应稳定携带 `image_path`、`image_hash`、图片尺寸、元素 bbox；
- 不再要求决策层解析未约定的私有 `value` 字典路径。

不做：

- 不在 projection 中判断是否识别；
- 不改变 `fact_kind`；
- 不把 candidate 放入 formal bucket。

### 4.5 `tool_models.py` / `semantic_query_projection.py`

修改内容：

- 必要时补齐 facade 语义摘要 DTO 的 image hash、cache key、model/prompt/contract、created at；
- 保持 facade DTO 与产品 DTO 分层，产品决策不反向污染查询/投影实现。

不做：

- 不在 facade DTO 中加入产品级预算、decision 或 answer 语义。

### 4.6 `semantic_cache.py`

修改内容：

- 继续作为唯一语义 cache key 规范来源；
- 如需要，可补充只读 helper，帮助产品层从目标生成 `SemanticCacheKeyInput`；
- 不改变已有 key 的确定性。

不做：

- 不建立第二套 cache key 算法；
- 不在 03 决策阶段写缓存。

### 4.7 `semantic_service.py`

本需求首阶段不要求立即改造执行服务，但设计预留后续衔接：

- 后续 04 执行阶段应接受精确 `RecognitionTarget`；
- 在供应商调用前按同一 cache key 二次校验缓存；
- 缓存命中时不调用 Qwen，不创建持久化 `RecognitionRun`；
- 只有最终 cache miss 且确需调用供应商时，才进入模型调用和可选 run log。

不做：

- 不把“是否值得识别”的产品决策放入 `SemanticRecognitionService`；
- 不让 semantic service 读取自然语言问题或预算策略。

### 4.8 `tool_facade.py`

后续执行衔接时可增加精确目标识别入口，例如：

```text
recognize_semantic_targets(targets, model_profile, prompt_version, write_back=false)
```

首阶段 03 决策不调用该入口，只定义目标合同并用 fake/单元测试验证。

不做：

- 不开放任意 Cypher；
- 不暴露 repository；
- 不绕过 `CandidateReviewService`；
- 不让 `write_back=true` 成为默认。

### 4.9 文档与测试

实施后同步：

- `architecture.md`；
- `Module.md`；
- 产品实现层 03 文档；
- `Feature_Analysis_Report.md` 中已实现/未实现边界。

新增测试建议：

- `tests/test_assistant_semantic_gap_models.py`
- `tests/test_assistant_evidence_sufficiency.py`
- `tests/test_assistant_evidence_freshness.py`
- `tests/test_assistant_recognition_target_planner.py`
- `tests/test_assistant_recognition_budget.py`
- `tests/test_assistant_semantic_gap_decision.py`
- 静态边界测试，禁止 03 模块导入 Neo4j、repository、Cypher、Qwen、HTTP、MCP、CLI 脚本。

## 5. 数据模型变化

### 5.1 Neo4j 数据模型

首阶段不修改 Neo4j schema：

- 不新增节点标签；
- 不新增关系类型；
- 不新增约束或索引；
- 不创建 `RecognitionRun` 图谱节点；
- 不设置或推断 `DrawingBlock.block_type`；
- 不写 `TextObservation`、`Interpretation`、candidate 或 formal relation。

### 5.2 产品公共合同变化

新增产品层 DTO 属于 Python 内部公共合同，不是数据库 schema。

核心对象关系：

```text
SemanticGapDecision
  -> RequirementAssessment[]
       -> FreshnessResult
       -> CacheDisposition
       -> matched_evidence_ids[]
       -> rejected_evidence_ids[]
  -> RecognitionTarget[] selected_targets
  -> RecognitionTarget[] deferred_targets
  -> RecognitionEstimate
  -> reason_codes[]
```

### 5.3 EvidenceItem 元数据补充

为避免决策层解析不稳定字典，建议对 `EvidenceItem` 补充或稳定约定以下元数据：

```text
image_hash
cache_key
model_version
contract_version
task_type
preprocessing_version
normalization_rule_version
```

如果不想扩大 `EvidenceItem` 顶层字段，可引入只读 `evidence_metadata` 映射，但必须：

- 字段名稳定；
- 序列化稳定；
- 不包含 secret；
- 不包含 Neo4j 内部 ID；
- 不承载未清洗 payload。

### 5.4 Freshness 策略兼容

现有 `FreshnessPolicy` 保持兼容：

| 旧值 | 兼容解释 |
|---|---|
| `any` | 不要求当前版本，但仍拒绝 `stale/rejected/recognition_failed` |
| `current_image` | 要求 image hash 和 bbox/target 当前 |
| `current_prompt` | 要求 prompt version 当前 |
| `current_contract` | 要求 output contract version 当前 |

新增组合策略可通过 `FreshnessRequirement` 表达：

```text
require_current_image
require_current_bbox
require_current_model
require_current_prompt
require_current_preprocessing
require_current_normalization
require_current_contract
allow_stale
max_age_seconds
```

### 5.5 估算数据

预算与时延只作为决策元数据，不写入 Neo4j。

`RecognitionEstimate` 建议包含：

```text
status
selected_target_count
deferred_target_count
estimated_cost
estimated_latency_ms
currency
estimator_version
reason_codes[]
```

实际 token、实际成本、实际时延由后续 04/07 记录，不由 03 伪造。

## 6. API 设计

### 6.1 内部 Python API

首阶段只设计内部 Python API，不新增 HTTP/MCP/CLI 对外入口。

核心入口：

```text
SemanticGapDecisionService.decide(
    question_result: QuestionUnderstandingResult,
    retrieval_bundle: RetrievalBundle,
    recognition_policy: RecognitionPolicy | None = None,
) -> SemanticGapDecision
```

默认策略：

- `allow_recognition` 默认继承 `AssistantRequest.allow_recognition`，但服务入口只消费显式 `RecognitionPolicy` 或由上游构造的默认 policy；
- `max_targets` 使用保守默认值；
- `max_estimated_cost` 和 `max_latency_seconds` 未配置时不按零成本处理；
- `write_back_recommendation` 默认为 `false`，且只作为建议。

### 6.2 组件 API

充分性评估：

```text
EvidenceSufficiencyEvaluator.evaluate(
    question_result: QuestionUnderstandingResult,
    retrieval_bundle: RetrievalBundle,
) -> tuple[RequirementAssessment, ...]
```

Freshness/cache 评估：

```text
EvidenceFreshnessEvaluator.evaluate(
    assessments: tuple[RequirementAssessment, ...],
    retrieval_bundle: RetrievalBundle,
    recognition_policy: RecognitionPolicy,
) -> tuple[RequirementAssessment, ...]
```

目标规划：

```text
RecognitionTargetPlanner.plan(
    assessments: tuple[RequirementAssessment, ...],
    retrieval_bundle: RetrievalBundle,
    recognition_policy: RecognitionPolicy,
) -> tuple[RecognitionTarget, ...]
```

预算评估：

```text
RecognitionBudgetEvaluator.evaluate(
    targets: tuple[RecognitionTarget, ...],
    policy: RecognitionPolicy,
) -> tuple[RecognitionTarget, ...], tuple[RecognitionTarget, ...], RecognitionEstimate
```

### 6.3 输入校验

`SemanticGapDecisionService.decide()` 必须校验：

- `question_result.request_id == retrieval_bundle.request_id`；
- subrequest 场景下 `subrequest_id` 一致或显式可映射；
- `RecognitionPolicy.allow_recognition` 是布尔值；
- `max_targets` 为正整数或 None；
- 成本/时延上限非负；
- 所有 requirement 有稳定 `requirement_id`；
- 所有 selected/deferred target 有稳定 `target_id`。

### 6.4 输出约定

输出必须满足：

- 相同输入产生相同输出顺序；
- 每个 missing requirement 可追溯到 requirement ID；
- 每个 selected target 可追溯到 covered requirement IDs；
- 每个 deferred target 有原因码；
- `reason_codes` 使用稳定枚举，不依赖中文自由文本解析；
- warning 不包含密钥、Cypher、内部 traceback 或本地敏感路径。

### 6.5 后续执行 API 衔接

本阶段不实现 04，但为后续识别预留以下输入形态：

```text
MultimodalRecognitionService.recognize_targets(
    targets: tuple[RecognitionTarget, ...],
    policy: RecognitionPolicy,
    write_back: bool = False,
) -> tuple[RecognitionResult, ...]
```

执行服务必须在供应商调用前使用 target 中的 cache key 或同一 `SemanticCacheKeyInput` 重算 key，再次查缓存。

## 7. 异常处理

### 7.1 异常分类

语义缺口决策模块不应把所有异常抛给上层形成 traceback。可恢复业务问题应进入 `SemanticGapDecision`。

| 情况 | 处理 |
|---|---|
| request_id 不一致 | 返回稳定 validation error 或抛出领域 `ValueError`，测试中固定错误信息 |
| requirement scope 缺失 | `clarification_required` + `scope_missing` |
| 目标定位缺少 image path/bbox | `clarification_required` 或 `unsupported` + `target_location_missing` |
| evidence kind 不满足 | assessment 为 `missing` 或 `unsupported` + `evidence_kind_mismatch` |
| candidate 不能满足 formal | assessment 为 `formal_review_required` + `formal_review_required` |
| freshness 元数据不足 | cache disposition 为 `unknown` + warning |
| 证据状态 stale/rejected | assessment 为 `stale` + 对应原因码 |
| `allow_recognition=false` 且存在缺口 | 不创建 target，输出 `recognition_forbidden` |
| 预算或时延超限 | selected/deferred 拆分，输出 `budget_exceeded` 或 `latency_exceeded` |
| 无法估算且存在硬限制 | 不按零成本处理，输出 `estimate_unavailable` |
| 内部不支持的 evidence type | `unsupported` + `unsupported_evidence_type` |

### 7.2 降级策略

- 有部分可用证据但仍缺必需模型证据时，03 输出缺口和原因，最终由 05/06 形成 `partial`；
- 缺口只涉及 formal review 时，不调用模型，输出 `reuse_existing` 加 `formal_review_required`；
- 禁止识别时，不调用模型，不生成 target；
- 预算不足时，保留 selected/deferred，不静默丢失目标；
- 缓存状态 unknown 时，默认不视为 full hit。

### 7.3 错误信息脱敏

错误和 warning 中禁止出现：

- Neo4j URI、用户名、密码；
- DashScope/OpenAI API key；
- Authorization header；
- 本地完整敏感 payload；
- Cypher；
- 底层 traceback。

## 8. 安全方案

### 8.1 只读与无副作用

03 模块必须是纯决策模块：

- 不导入 Neo4j driver；
- 不导入 repository；
- 不拼写或执行 Cypher；
- 不调用 `DrawingGraphToolFacade`；
- 不调用 `SemanticRecognitionService`；
- 不调用 Qwen/DashScope；
- 不写缓存；
- 不创建 `RecognitionRun`；
- 不写 Neo4j；
- 不提升候选关系。

通过静态边界测试保护这些约束。

### 8.2 写回权限隔离

`write_back_recommendation` 只能表达“如果后续识别成功，是否建议持久化语义证据”。它不能：

- 修改 `AssistantRequest.allow_write_back`；
- 覆盖 adapter 权限；
- 覆盖模块策略；
- 替代 repository 可用性检查；
- 直接触发写回。

后续 04/05 写回仍必须满足：

```text
request_allow_write_back
module_allow_write_back
environment_permission
schema_valid
target_scope_valid
repository_available
```

全部为 true 才能持久化。

### 8.3 事实分层保护

决策规则必须硬编码以下安全不变量：

- `semantic_interpretation` 不能满足 `source_fact`；
- `semantic_observation` 不能满足 `semantic_interpretation`；
- `candidate_relation` 不能满足 `formal_relation`；
- `matched_candidate` 不等于正式图谱关系；
- 用户确认不等于正式关系；
- 模型输出不能覆盖来源事实；
- 模型输出不能设置 `DrawingBlock.block_type`。

### 8.4 模型调用门控

`allow_recognition=false` 是绝对门槛。任何问题文本、估算结果、默认策略或模型建议都不能把它改为 true。

03 模块不调用模型。后续 04 调用模型时必须使用 03 生成的 selected targets，并在执行前二次缓存检查。

### 8.5 预算与时延硬限制

硬限制必须 fail closed：

- 无法估算且存在预算限制时，不按零成本处理；
- 超出目标数、成本或时延时，目标进入 deferred；
- deferred target 必须在输出和追溯中可见；
- 下游不得把被裁剪目标当作已经回答。

### 8.6 Adapter 安全

本需求首阶段不新增产品级 HTTP/MCP/CLI。未来新增 adapter 时：

- adapter 只能调用 `DrawingAssistantService`；
- 不得直接调用 `SemanticGapDecisionService` 以绕过 01/02；
- 不得直接调用 facade、repository 或 Cypher；
- HTTP 仍默认 loopback；
- MCP 仍优先本机只读；
- 写回能力必须单独授权。

## 9. 测试与验证方案

### 9.1 单元测试

覆盖：

- 每种 `fact_kind` 的充分性矩阵；
- observation 与 interpretation 不可互相替代；
- candidate 不可满足 formal；
- 缺 scope、缺 image path、缺 bbox；
- stale/rejected/conflicting 状态；
- current image/prompt/contract freshness；
- full/partial/miss/stale/unknown cache disposition；
- target 去重、合并、稳定排序；
- `allow_recognition=false`；
- max targets、预算、时延；
- estimate unavailable；
- selected/deferred 输出；
- `write_back_recommendation` 不改变授权。

### 9.2 合同测试

覆盖：

- DTO 序列化与枚举稳定值；
- reason code 稳定；
- 同输入输出顺序稳定；
- `SemanticGapDecision` 不包含 secret、Cypher、traceback；
- `EvidenceItem` 决策元数据字段稳定。

### 9.3 静态边界测试

禁止新增 03 模块导入：

```text
neo4j
repository
cypher
qwen_semantic_client
semantic_service
qa_http
qa_mcp
scripts.
```

### 9.4 Live 验证边界

本需求首阶段不要求 live DashScope 或 live Neo4j。验证报告必须分层：

- 单元/fake 测试通过；
- 离线模型合同测试通过；
- live DashScope 通过；
- live Neo4j dry-run 或写回通过。

skipped live 测试不能报告为通过。

## 10. 实施边界

首阶段建议包含：

- 公共 DTO 与原因码；
- 充分性评估；
- freshness/cache 判断；
- 最小目标规划；
- 预算/时延门控；
- `SemanticGapDecisionService`；
- 检索投影元数据补口；
- 单元、合同、静态边界测试；
- 文档同步。

首阶段不包含：

- 完整 `DrawingAssistantService`；
- 真实 Qwen/DashScope 调用；
- 语义识别执行改造的 live 验证；
- 证据融合；
- 最终答案生成；
- 用户反馈状态机；
- 产品级 HTTP/MCP/CLI/Web UI；
- Neo4j schema 变更；
- 写回语义证据；
- 候选审核或正式关系提升。

## 11. 完成标准

本设计对应实现完成时，至少满足：

- 每个 `EvidenceRequirement` 都有独立 `RequirementAssessment`；
- 所有 assessment 均有稳定 reason codes；
- `fact_kind` 不发生层级替代；
- candidate 永远不能满足 formal requirement；
- freshness 支持图片、bbox、模型、prompt、预处理、规范化和合同版本；
- full hit 不产生识别目标；
- partial hit 只产生剩余目标；
- selected/deferred targets 稳定、可追溯；
- `allow_recognition=false`、预算和时延限制均为硬门槛；
- 决策模块不调用 facade、Neo4j、repository、Qwen、semantic service 或写缓存；
- 决策不能把 `allow_write_back` 改为 true；
- 单元/fake 与 live 验证状态分开报告。

## 12. 结论

语义缺口决策闭环应作为产品实现层 03 的独立纯决策模块，而不是识别服务、QAService、adapter 或 Agent 的附属逻辑。它复用现有 `QuestionUnderstandingResult`、`RetrievalBundle`、`EvidenceItem`、`semantic_cache.py` 和事实分层边界，在模型调用之前形成可解释、可测试、可重放的 `SemanticGapDecision`。

该设计不要求无意义重构，不改造现有 QA/HTTP/MCP 兼容链路，不改变 Neo4j schema。它只补齐产品闭环中最关键的一层判断：现有证据够不够、缓存能不能用、是否允许识别、识别哪些最小目标，以及哪些目标因预算、时延、scope 或权限被延后。

## 13. 实施状态（2026-08-12）

- 首阶段 Tasks 1-35 已按本设计实施：公共 DTO/原因码、逐需求充分性评估、freshness/cache 判断、最小目标规划、预算/时延门控、`SemanticGapDecisionService` 编排、03 静态边界测试、精确识别目标合同预留、执行前二次缓存校验、facade/工厂装配预留与文档同步。
- 新增模块：`assistant_evidence_sufficiency.py`、`assistant_evidence_freshness.py`、`assistant_recognition_target_planner.py`、`assistant_recognition_budget.py`、`assistant_semantic_gap_decision.py`。
- 边界保持：03 不调用模型、不写缓存、不写 Neo4j、不创建 RecognitionRun；默认 `write_back=false`，`write_back_recommendation` 只是建议；candidate 不等于 formal。
- 验证状态：单元/合同/静态边界测试通过；live DashScope 与 live Neo4j 未验证，skipped 不计为通过。
- 仍未实现：完整 `DrawingAssistantService`、证据融合、答案生成、反馈状态机、产品级 HTTP/MCP/CLI/Web adapter、Neo4j schema 变更与写回语义证据。
