# 语义缺口决策闭环 Tasks

**文档状态：** 实施任务计划  
**日期：** 2026-08-12  
**依据文档：** `proposal.md`、`design.md`、`Feature_Analysis_Report.md`  
**适用范围：** 产品实现层 03 语义缺口决策模块  

## 全局约束

- 不写实现代码到本任务文档之外；本文只定义后续实施任务。
- 03 模块是纯决策层，位于 `QuestionUnderstandingService` 与 `GraphRetrievalService` 之后、真实语义识别执行之前。
- 03 模块不得调用 `DrawingGraphToolFacade`、Neo4j、repository、Cypher、Qwen/DashScope、`SemanticRecognitionService`、HTTP/MCP/CLI adapter。
- 03 模块不得创建 `RecognitionRun`，不得写缓存、payload、语义证据、Neo4j 或候选/正式关系。
- 默认 `write_back=false`；`write_back_recommendation` 只能是建议，不能提升授权。
- candidate、`matched_candidate`、语义观察、语义解释不得满足 formal/source fact 需求。
- 每个任务必须独立测试；未配置 live Neo4j 或 live DashScope 时，skipped 不能报告为通过。

## 任务总览

1. 决策枚举与原因码合同
2. freshness/cache DTO 合同
3. 识别策略、目标与估算 DTO 合同
4. `EvidenceItem` 决策元数据合同
5. 语义需求模板补齐
6. 检索规划定位元数据补齐
7. 页面来源事实投影元数据补齐
8. 语义观察投影元数据补齐
9. 语义解释与候选投影元数据补齐
10. 充分性评估器骨架
11. requirement scope 匹配
12. fact kind 与 formal gate 判断
13. 状态与冲突判断
14. 模型生成许可判断
15. freshness 维度判断
16. 缓存键输入构造
17. cache disposition 命中分类
18. stale/unknown 缓存保护
19. 识别目标定位来源查找
20. 元素/bbox 与整页目标生成
21. 目标合并、去重与稳定排序
22. 缺定位目标阻断
23. 成本与时延估算 profile
24. `allow_recognition` 与 `max_targets` 门控
25. 成本、时延与不可估算门控
26. 决策服务输入校验
27. 决策服务编排与最终 decision
28. 03 模块静态边界测试
29. 精确识别目标合同预留
30. 执行前二次缓存校验预留
31. facade 精确目标入口预留
32. 工厂装配预留
33. 架构与模块文档同步
34. 专项文档合同测试
35. 最小回归验证

---

## Task 1：决策枚举与原因码合同

**明确目标：**  
在产品公共合同中增加语义缺口决策所需的稳定枚举和原因码，作为后续所有组件的唯一字符串来源。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_models.py`
- 新增或修改测试：`tests/test_assistant_semantic_gap_models.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_semantic_gap_models -v
```

**完成标准：**

- 存在 `SemanticGapDecisionType`，至少包含 `reuse_existing`、`recognize_required`、`clarification_required`、`unsupported`。
- 存在 `RequirementAssessmentStatus`，至少包含 `satisfied`、`missing`、`stale`、`conflicting`、`forbidden`、`unsupported`、`formal_review_required`。
- 存在 `CacheDisposition`、`RecognitionTargetStatus`、`EstimateStatus` 稳定枚举。
- `ReasonCode` 补齐 evidence/freshness/cache/budget/formal/target 相关原因码。
- 枚举值为稳定小写字符串，且序列化后不依赖中文文案。

## Task 2：freshness/cache DTO 合同

**明确目标：**  
定义 freshness 判断与缓存候选的公共 DTO，使后续评估器能表达组合 freshness 约束和缓存处置。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_models.py`
- 修改测试：`tests/test_assistant_semantic_gap_models.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_semantic_gap_models -v
```

**完成标准：**

- 存在 `FreshnessRequirement`，支持当前图片、bbox、模型、prompt、预处理、规范化、输出合同和可选年龄限制。
- 存在 `FreshnessResult`，能表达各维度是否满足、失败原因和缺失元数据。
- 存在 `CacheCandidate`，包含 requirement、target、cache key、disposition、可复用 evidence ID 和原因码。
- 缺少关键 freshness 元数据时可表达为 `unknown`，不能默认为有效。
- DTO 不导入数据库、facade、HTTP/MCP 或模型客户端。

## Task 3：识别策略、目标与估算 DTO 合同

**明确目标：**  
定义 `RecognitionPolicy`、`RecognitionTarget`、`RecognitionEstimate` 和 `SemanticGapDecision`，作为 03 模块统一输出合同。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_models.py`
- 修改测试：`tests/test_assistant_semantic_gap_models.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_semantic_gap_models -v
```

**完成标准：**

- `RecognitionPolicy` 包含 `allow_recognition`、`max_targets`、`max_estimated_cost`、`max_latency_seconds`、模型/prompt/合同策略和 cache mode。
- `RecognitionTarget` 包含 page、element/bbox、task type、required outputs、covered requirement IDs、cache key、priority、status 和原因码。
- `RecognitionEstimate` 包含 selected/deferred 数量、估算成本、估算时延、估算版本和状态。
- `SemanticGapDecision` 包含 decision、requirement assessments、missing requirements、cache candidates、selected/deferred targets、estimate、reason codes、warnings、contract version。
- 负数预算、负数时延、空目标 ID、空 requirement ID 被合同校验拒绝。

## Task 4：`EvidenceItem` 决策元数据合同

**明确目标：**  
让 `EvidenceItem` 能稳定承载 freshness/cache 所需元数据，避免 03 模块解析未约定的 `value` 私有字段。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_models.py`
- 修改测试：`tests/test_assistant_semantic_gap_models.py`
- 修改测试：`tests/test_assistant_retrieval_projection.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_semantic_gap_models tests.test_assistant_retrieval_projection -v
```

**完成标准：**

- `EvidenceItem` 或稳定 metadata 映射包含 `image_hash`、`cache_key`、`task_type`、`model_profile`、`model_version`、`prompt_version`、`contract_version`、`preprocessing_version`、`normalization_rule_version`。
- 元数据字段可序列化、无 secret、无 Neo4j 内部 ID、无未清洗 payload。
- 现有 fact kind 桶校验仍然阻止 candidate 进入 formal bucket。
- 现有检索合同测试不因新增可选元数据破坏兼容性。

## Task 5：语义需求模板补齐

**明确目标：**  
让问题理解输出的语义类 `EvidenceRequirement` 明确声明 minimum status、freshness 和是否允许模型补证。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_evidence_templates.py`
- 修改测试：`tests/test_assistant_evidence_templates.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_templates -v
```

**完成标准：**

- 语义观察类需求显式设置 `allow_model_generation=true` 或按设计允许生成。
- formal/source fact 类需求保持 `allow_model_generation=false`。
- 当前图片、当前 prompt、当前输出合同等需求能映射到组合 freshness 约束。
- 断面匹配问题能分别表达双方 observation 需求和 formal/candidate 关系需求。
- 模板只声明需求，不读取图谱、不判断充分性、不调用模型。

## Task 6：检索规划定位元数据补齐

**明确目标：**  
确保语义缺口决策所需的页面图片、元素 bbox、block trace 等定位来源事实能被检索规划请求到。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_retrieval_planner.py`
- 修改测试：`tests/test_assistant_retrieval_planner.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_retrieval_planner -v
```

**完成标准：**

- 语义 observation/interpretation 需求会附带定位来源事实检索 step。
- block/element 级语义需求保留原始 `requirement_id` 到检索 step。
- 页面级任务请求 `get_page_source_facts(..., include_image_meta=True)`。
- planner 不执行 freshness、cache、预算或识别目标规划。
- planner 不生成 `recognize_page_semantics` 或任何写回 step。

## Task 7：页面来源事实投影元数据补齐

**明确目标：**  
将页面图片路径、图片 hash、图片尺寸、元素 bbox 等来源事实稳定投影到 `EvidenceItem`。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_retrieval_projection.py`
- 修改测试：`tests/test_assistant_retrieval_projection.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_retrieval_projection -v
```

**完成标准：**

- page source facts 证据稳定携带 `image_path`、`image_hash`、图片尺寸和元素 bbox。
- element/block 来源事实能追溯到 page ID、element ID、bbox 和稳定业务 ID。
- 投影只补齐元数据，不决定是否识别。
- `fact_kind` 不被改变，不把来源事实与模型语义证据混合。

## Task 8：语义观察投影元数据补齐

**明确目标：**  
将 `TextObservation` 查询结果中的状态、图片、缓存、模型、prompt、合同和创建信息稳定投影出来。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_retrieval_projection.py`
- 修改测试：`tests/test_assistant_retrieval_projection.py`
- 必要时修改：`src/drawing_graph/tool_models.py`
- 必要时修改：`src/drawing_graph/semantic_query_projection.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_retrieval_projection -v
```

**完成标准：**

- observation 证据携带 `status`、`image_hash`、`cache_key`、`model_profile`、`model_version`、`prompt_version`、`contract_version`、`created_at_or_version`。
- 缺失字段以稳定 `None` 或 warning 表达，不解析私有 payload。
- observation 只进入 `semantic_observations` 桶。
- projection 不调用 cache、模型或 repository 写口。

## Task 9：语义解释与候选投影元数据补齐

**明确目标：**  
将 interpretation、candidate relation、section match 等证据稳定投影到正确 fact kind，并携带决策元数据。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_retrieval_projection.py`
- 修改测试：`tests/test_assistant_retrieval_projection.py`
- 必要时修改：`src/drawing_graph/tool_models.py`
- 必要时修改：`src/drawing_graph/semantic_query_projection.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_retrieval_projection -v
```

**完成标准：**

- interpretation 只进入 `semantic_interpretations` 桶。
- candidate relation 与 candidate section match 只进入 `candidate_relations` 桶。
- formal relation 只由 formal/confirmed 查询结果进入 `formal_relations` 桶。
- interpretation/candidate 均携带可用的 cache、模型、prompt、合同和状态元数据。
- 测试覆盖 candidate 不进入 formal、semantic interpretation 不进入 source facts。

## Task 10：充分性评估器骨架

**明确目标：**  
新增充分性评估器，按每个 `EvidenceRequirement` 输出独立 `RequirementAssessment`，不只给整个 bundle 一个总状态。

**指定修改文件：**

- 新增：`src/drawing_graph/assistant_evidence_sufficiency.py`
- 新增测试：`tests/test_assistant_evidence_sufficiency.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_sufficiency -v
```

**完成标准：**

- 存在 `EvidenceSufficiencyEvaluator.evaluate(question_result, retrieval_bundle)` 接口。
- 每个 requirement 均产生一条 assessment。
- assessment 包含 requirement ID、状态、matched evidence IDs、rejected evidence IDs 和 reason codes。
- 空 bundle 对 required requirement 返回 missing，不抛出未处理异常。
- 模块不导入 facade、Neo4j、repository、Qwen、HTTP/MCP/CLI。

## Task 11：requirement scope 匹配

**明确目标：**  
在充分性评估中实现 requirement scope 与 evidence scope 的稳定匹配，防止跨 page/block/element 误用证据。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_evidence_sufficiency.py`
- 修改测试：`tests/test_assistant_evidence_sufficiency.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_sufficiency -v
```

**完成标准：**

- page requirement 只匹配同 page 证据。
- block requirement 只匹配同 block 或明确属于该 block 的 element 证据。
- element requirement 只匹配同 element 证据。
- scope 缺失返回 `scope_missing` 或 `target_location_missing`，不让模型猜。
- scope mismatch 的证据进入 rejected evidence IDs，并带稳定原因码。

## Task 12：fact kind 与 formal gate 判断

**明确目标：**  
实现 fact kind 层级不可替代规则，特别保护 candidate/formal 与 source/semantic 边界。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_evidence_sufficiency.py`
- 修改测试：`tests/test_assistant_evidence_sufficiency.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_sufficiency -v
```

**完成标准：**

- source fact requirement 不能由 semantic observation 或 interpretation 满足。
- semantic interpretation requirement 不能由 observation 满足。
- formal relation requirement 不能由 candidate relation、`matched_candidate` 或用户确认文本满足。
- candidate relation 只能满足“候选/待复核”类 requirement。
- formal 缺失但有 candidate 时返回 `formal_review_required`，不产生识别目标。

## Task 13：状态与冲突判断

**明确目标：**  
实现 evidence status 与冲突判断，使 stale/rejected/failed/conflicting 证据不能被当成有效满足项。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_evidence_sufficiency.py`
- 修改测试：`tests/test_assistant_evidence_sufficiency.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_sufficiency -v
```

**完成标准：**

- `stale`、`rejected`、`recognition_failed` 状态不会满足 required requirement。
- 同一目标同一字段存在互斥证据时返回 `conflicting`。
- `minimum_status` 按 evidence type/fact kind 解释，不使用全局状态排序。
- rejected evidence IDs 保留被拒原因，便于追踪。
- 测试覆盖 confirmed、partial、ambiguous、stale、rejected、conflicting 场景。

## Task 14：模型生成许可判断

**明确目标：**  
在充分性评估中区分“缺口可由模型补证”和“缺口禁止或不支持模型生成”。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_evidence_sufficiency.py`
- 修改测试：`tests/test_assistant_evidence_sufficiency.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_sufficiency -v
```

**完成标准：**

- `allow_model_generation=false` 且 required 证据缺失时返回 `recognition_forbidden` 或 `unsupported_generation`。
- source fact、formal relation、candidate promotion 类缺口不被标记为可模型生成。
- semantic observation/interpretation 类缺口在策略允许时可标记为可生成。
- 该判断只产生 assessment，不调用模型、不生成目标。

## Task 15：freshness 维度判断

**明确目标：**  
新增 freshness evaluator，按图片、bbox、模型、prompt、预处理、规范化和输出合同维度判断证据是否当前有效。

**指定修改文件：**

- 新增：`src/drawing_graph/assistant_evidence_freshness.py`
- 新增测试：`tests/test_assistant_evidence_freshness.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_freshness -v
```

**完成标准：**

- 存在 `EvidenceFreshnessEvaluator.evaluate(assessments, retrieval_bundle, recognition_policy)` 接口。
- `current_image` 能检查 image hash 与目标 bbox/element。
- `current_prompt` 能检查 prompt version。
- `current_contract` 能检查 output contract version。
- 组合 `FreshnessRequirement` 可同时要求多个维度。
- 缺少关键元数据时返回 unknown/warning，不默认为满足。

## Task 16：缓存键输入构造

**明确目标：**  
让 freshness/cache evaluator 复用 `semantic_cache.SemanticCacheKeyInput` 与 `build_semantic_cache_key()` 构造预期 cache key。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_evidence_freshness.py`
- 必要时修改：`src/drawing_graph/semantic_cache.py`
- 修改测试：`tests/test_assistant_evidence_freshness.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_freshness -v
```

**完成标准：**

- 03 决策层不复制第二套 cache key 拼接算法。
- 可从 requirement、evidence 元数据和 policy 构造 `SemanticCacheKeyInput`。
- 缺少 image hash、bbox、task type、model/prompt/contract version 时 cache disposition 为 `unknown`。
- 测试确认相同输入得到与 `build_semantic_cache_key()` 一致的 key。
- 不写缓存、不读取缓存存储，只构造和比较 key。

## Task 17：cache disposition 命中分类

**明确目标：**  
实现 full/partial/miss/stale/bypassed/unknown 缓存处置分类，为目标规划提供剩余缺口。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_evidence_freshness.py`
- 修改测试：`tests/test_assistant_evidence_freshness.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_freshness -v
```

**完成标准：**

- 所有 required requirement 已由有效证据满足时，相关处置为 `full_hit`。
- 部分 requirement 满足时，处置为 `partial_hit`，并保留剩余缺口。
- 没有兼容证据时，处置为 `miss`。
- policy 要求跳过缓存时，处置为 `bypassed`。
- 输出 `CacheCandidate` 可追溯 requirement ID 和 evidence ID。

## Task 18：stale/unknown 缓存保护

**明确目标：**  
确保 stale、rejected、failed、conflicting 或关键元数据未知的证据不会被当成缓存命中。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_evidence_freshness.py`
- 修改测试：`tests/test_assistant_evidence_freshness.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_freshness -v
```

**完成标准：**

- stale evidence 产生 `stale` disposition 和对应 freshness reason。
- rejected/recognition_failed evidence 不产生 full hit。
- conflicting evidence 不产生 full hit。
- unknown 元数据不会被降级为 hit。
- freshness 更新后的 assessment 状态与 cache disposition 一致。

## Task 19：识别目标定位来源查找

**明确目标：**  
新增目标规划器的定位查找能力，从来源事实中找到 image path、image hash、bbox、page 和稳定 element/block ID。

**指定修改文件：**

- 新增：`src/drawing_graph/assistant_recognition_target_planner.py`
- 新增测试：`tests/test_assistant_recognition_target_planner.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_recognition_target_planner -v
```

**完成标准：**

- 存在 `RecognitionTargetPlanner.plan(assessments, retrieval_bundle, recognition_policy)` 接口。
- 能从 page source facts 和 block trace 找到目标定位元数据。
- 缺少可信 image path、image hash、bbox 或稳定业务 ID 时不生成 selected target。
- 定位查找只读取 `RetrievalBundle`，不调用 facade 或文件系统。

## Task 20：元素/bbox 与整页目标生成

**明确目标：**  
将未满足且允许模型生成的 requirement 转换为最小识别目标，优先 element/bbox，只有页面摘要类任务使用整页。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_recognition_target_planner.py`
- 修改测试：`tests/test_assistant_recognition_target_planner.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_recognition_target_planner -v
```

**完成标准：**

- block/element 语义缺口生成 element 或 bbox 级目标。
- 页面摘要 requirement 才能生成 page 级目标。
- 已满足、full hit、formal review only、forbidden requirement 不生成目标。
- target 保留 task type、required outputs、covered requirement IDs 和 reason codes。
- target 不包含未清洗 payload 或 secret。

## Task 21：目标合并、去重与稳定排序

**明确目标：**  
对同一目标、同一 task type、兼容 required outputs 和输出合同的识别目标进行合并，并保证稳定排序。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_recognition_target_planner.py`
- 修改测试：`tests/test_assistant_recognition_target_planner.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_recognition_target_planner -v
```

**完成标准：**

- 相同 page/element/bbox/task/output contract 的目标合并为一个 target。
- 合并后保留所有 covered requirement IDs。
- 不同 prompt 或 output contract 的目标不合并。
- 目标排序按 required 优先、覆盖需求数、粒度、估算成本/时延和稳定 target ID。
- 多次相同输入得到完全一致的 target 顺序。

## Task 22：缺定位目标阻断

**明确目标：**  
对缺少定位信息或 scope 过宽的可生成缺口输出 blocked/deferred target 信息，而不是让模型猜目标。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_recognition_target_planner.py`
- 修改测试：`tests/test_assistant_recognition_target_planner.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_recognition_target_planner -v
```

**完成标准：**

- 缺 image path、image hash、bbox、page ID 或稳定 element/block ID 时不进入 selected targets。
- 阻断结果带 `target_location_missing` 或 `scope_missing` 原因码。
- 需要用户缩小范围时可供上游决策为 `clarification_required`。
- 被阻断的 requirement 不被静默丢弃。

## Task 23：成本与时延估算 profile

**明确目标：**  
新增可注入的保守成本/时延估算配置，避免把供应商价格和模型能力硬编码进算法。

**指定修改文件：**

- 新增：`src/drawing_graph/assistant_recognition_budget.py`
- 新增测试：`tests/test_assistant_recognition_budget.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_recognition_budget -v
```

**完成标准：**

- 存在 `RecognitionCostProfile` 或等价配置对象。
- 存在 `RecognitionEstimator`，能按 task type、model profile、图片范围给出成本和时延估算。
- 无 profile 时返回 `estimate_unavailable`，不假设零成本。
- 估算结果标明 estimator version。
- 模块不读取供应商 API key、不请求网络。

## Task 24：`allow_recognition` 与 `max_targets` 门控

**明确目标：**  
实现识别授权和最大目标数硬门控，确保禁止识别时不产生 selected targets。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_recognition_budget.py`
- 修改测试：`tests/test_assistant_recognition_budget.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_recognition_budget -v
```

**完成标准：**

- 存在 `RecognitionBudgetEvaluator.evaluate(targets, policy)` 接口。
- `allow_recognition=false` 时所有目标进入 deferred/blocked，原因码为 `recognition_forbidden`。
- `max_targets` 超限时只选择稳定排序后的前 N 个目标。
- 被裁剪目标进入 `deferred_targets`，不静默丢失。
- 门控不改变 target 的 covered requirement IDs。

## Task 25：成本、时延与不可估算门控

**明确目标：**  
实现成本上限、时延上限和不可估算时的 fail closed 策略。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_recognition_budget.py`
- 修改测试：`tests/test_assistant_recognition_budget.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_recognition_budget -v
```

**完成标准：**

- `max_estimated_cost` 超限时目标进入 deferred 并带 `budget_exceeded`。
- `max_latency_seconds` 超限时目标进入 deferred 并带 `latency_exceeded`。
- 存在硬预算但无法估算时返回 `estimate_unavailable`，不按零成本处理。
- retry/reserve latency 被计入估算。
- `RecognitionEstimate` 汇总 selected/deferred 数量、成本、时延和原因码。

## Task 26：决策服务输入校验

**明确目标：**  
新增 `SemanticGapDecisionService` 的输入校验，确保 request/subrequest、requirement 和 policy 一致。

**指定修改文件：**

- 新增：`src/drawing_graph/assistant_semantic_gap_decision.py`
- 新增测试：`tests/test_assistant_semantic_gap_decision.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_semantic_gap_decision -v
```

**完成标准：**

- 存在 `SemanticGapDecisionService.decide(question_result, retrieval_bundle, recognition_policy=None)` 接口。
- `question_result.request_id` 与 `retrieval_bundle.request_id` 不一致时返回稳定错误或抛出受控 `ValueError`。
- requirement ID 为空时被拒绝。
- policy 中非布尔授权、负预算、负时延、非法 max targets 被拒绝。
- 校验阶段无 facade、Neo4j、repository、模型、缓存写入调用。

## Task 27：决策服务编排与最终 decision

**明确目标：**  
串联充分性、freshness/cache、目标规划和预算评估，生成唯一 `SemanticGapDecision`。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_semantic_gap_decision.py`
- 修改测试：`tests/test_assistant_semantic_gap_decision.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_semantic_gap_decision -v
```

**完成标准：**

- 编排顺序为输入校验、充分性、freshness/cache、缺口列表、目标规划、预算门控、最终 decision。
- 全部 required requirement 满足或只剩 formal review warning 时，decision 为 `reuse_existing`。
- 存在可生成缺口且至少一个目标 selected 时，decision 为 `recognize_required`。
- 缺 scope、image path、bbox 或用户需缩小范围时，decision 为 `clarification_required`。
- 缺口不可生成、禁止识别且无可回答证据、证据类型不支持时，decision 为 `unsupported`。
- `reuse_existing` 不等于最终答案一定完整，warning/missing 仍保留给后续模块。

## Task 28：03 模块静态边界测试

**明确目标：**  
用静态测试保护 03 纯决策模块不越权导入或调用外部执行能力。

**指定修改文件：**

- 新增：`tests/test_assistant_semantic_gap_boundaries.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_semantic_gap_boundaries -v
```

**完成标准：**

- 扫描 `assistant_evidence_sufficiency.py`、`assistant_evidence_freshness.py`、`assistant_recognition_target_planner.py`、`assistant_recognition_budget.py`、`assistant_semantic_gap_decision.py`。
- 禁止导入 `neo4j`、repository、`tool_facade`、`semantic_service`、Qwen/DashScope、HTTP/MCP/CLI 脚本。
- 禁止出现 Cypher 关键操作、`RecognitionRun` 创建、cache put/write、`write_back=True`。
- 允许导入 `assistant_models.py` 和 `semantic_cache.py` 的只读 cache key 工具。
- 测试失败时能指出违规文件和关键字。

## Task 29：精确识别目标合同预留

**明确目标：**  
为后续 04 执行模块预留精确目标识别输入合同，使执行层能消费 `RecognitionTarget` 而不是整页 `target_types`。

**指定修改文件：**

- 修改：`src/drawing_graph/tool_models.py`
- 修改：`src/drawing_graph/semantic_client.py`
- 修改测试：`tests/test_tool_models.py`
- 修改测试：`tests/test_semantic_client.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_tool_models tests.test_semantic_client -v
```

**完成标准：**

- 存在精确目标识别输入 DTO 或协议，能表达 page、target element、bbox、task type、required outputs、context 和 output contract。
- 该合同不包含产品层 decision、预算原因或 answer 状态。
- 模型输出仍只能成为 semantic observation/interpretation/candidate evidence。
- 不实现真实供应商调用逻辑，仅保证合同可序列化和 fake client 可消费。

## Task 30：执行前二次缓存校验预留

**明确目标：**  
在语义执行服务中预留按同一 cache key 进行供应商调用前二次缓存校验的路径。

**指定修改文件：**

- 修改：`src/drawing_graph/semantic_service.py`
- 修改测试：`tests/test_semantic_service.py`
- 修改测试：`tests/test_semantic_cache.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_semantic_service tests.test_semantic_cache -v
```

**完成标准：**

- 执行前使用与 03 目标相同的 `SemanticCacheKeyInput` 或 target cache key 校验缓存。
- 缓存命中时不调用 fake multimodal client。
- 缓存命中时不创建持久化 run log。
- 最终 cache miss 且确需供应商调用时才进入模型执行路径。
- 该任务不把“是否值得识别”的产品决策放入 `SemanticRecognitionService`。

## Task 31：facade 精确目标入口预留

**明确目标：**  
为后续执行层新增或预留受控 facade 入口，使其可以执行 selected `RecognitionTarget`。

**指定修改文件：**

- 修改：`src/drawing_graph/tool_facade.py`
- 修改测试：`tests/test_tool_facade.py`
- 必要时修改：`tests/test_assistant_semantic_gap_boundaries.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_tool_facade tests.test_assistant_semantic_gap_boundaries -v
```

**完成标准：**

- facade 入口只接收精确目标、模型/prompt/合同策略和显式 `write_back`。
- 默认 `write_back=false`。
- 不开放任意 Cypher、repository、候选提升或未授权写回。
- 03 决策模块测试确认不会调用该入口。
- 现有 `recognize_page_semantics` 兼容性不被破坏。

## Task 32：工厂装配预留

**明确目标：**  
为后续产品编排装配语义缺口决策服务及其纯策略依赖，但不启动完整 `DrawingAssistantService`。

**指定修改文件：**

- 修改：`src/drawing_graph/tool_factory.py`
- 新增或修改测试：`tests/test_assistant_semantic_gap_factory.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_semantic_gap_factory -v
```

**完成标准：**

- 可通过工厂或轻量 builder 创建 `SemanticGapDecisionService` 及其纯 evaluator 依赖。
- 工厂创建过程不连接 Neo4j、不读取供应商 API key、不请求网络。
- 决策服务可在 fake `QuestionUnderstandingResult + RetrievalBundle` 下运行。
- 不新增产品级 HTTP/MCP/CLI/Web adapter。

## Task 33：架构与模块文档同步

**明确目标：**  
实施完成后同步项目维护文档，说明 03 模块职责、边界、数据流和未实现范围。

**指定修改文件：**

- 修改：`architecture.md`
- 修改：`Module.md`
- 修改：`README.md`
- 修改：`changes/产品实现层/语义缺口决策闭环/design.md`
- 修改：`changes/产品实现层/语义缺口决策闭环/Feature_Analysis_Report.md`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_docs -v
```

**完成标准：**

- 文档记录 `SemanticGapDecisionService` 位于检索之后、识别之前。
- 文档明确 03 不调用模型、不写缓存、不写 Neo4j、不创建 `RecognitionRun`。
- 文档明确完整 `DrawingAssistantService`、证据融合、答案生成、反馈状态机和产品级 adapter 仍属后续范围。
- 文档继续声明 candidate 不等于 formal，skipped live 测试不等于 live 通过。
- 文档不提前宣称 live DashScope 或 live Neo4j 已验证。

## Task 34：专项文档合同测试

**明确目标：**  
为语义缺口决策闭环目录增加文档合同测试，防止 proposal/design/tasks 漂移或任务字段缺失。

**指定修改文件：**

- 新增：`tests/test_assistant_semantic_gap_docs.py`
- 修改：`changes/产品实现层/语义缺口决策闭环/tasks.md`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_semantic_gap_docs -v
```

**完成标准：**

- 测试确认 `proposal.md`、`design.md`、`Feature_Analysis_Report.md`、`tasks.md` 均存在。
- 测试确认每个 task 包含明确目标、指定修改文件、可独立测试、完成标准。
- 测试确认文档包含“不调用模型”“不写 Neo4j”“默认 write_back=false”“candidate 不等于 formal”等边界。
- 测试不依赖 live Neo4j 或 live DashScope。

## Task 35：最小回归验证

**明确目标：**  
运行语义缺口决策闭环相关最小测试集，证明新增 03 模块与现有产品检索、语义证据、QA 边界兼容。

**指定修改文件：**

- 不新增业务代码。
- 必要时只修改失败测试对应的最小相关文件。

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest `
  tests.test_assistant_semantic_gap_models `
  tests.test_assistant_evidence_templates `
  tests.test_assistant_retrieval_planner `
  tests.test_assistant_retrieval_projection `
  tests.test_assistant_evidence_sufficiency `
  tests.test_assistant_evidence_freshness `
  tests.test_assistant_recognition_target_planner `
  tests.test_assistant_recognition_budget `
  tests.test_assistant_semantic_gap_decision `
  tests.test_assistant_semantic_gap_boundaries `
  tests.test_assistant_semantic_gap_docs `
  -v
```

**完成标准：**

- 上述最小测试集全部通过。
- 现有 `tests.test_assistant_retrieval_boundaries` 仍通过。
- 未配置 live Neo4j 或 live DashScope 时，不报告 live 验证通过。
- 失败时只修复与语义缺口决策闭环相关的最小文件，不做无关重构。
- 最终变更不新增外部依赖、不改变 Neo4j schema、不改变 QA/HTTP/MCP 默认只读边界。

---

## 实施状态（2026-08-12）

- Tasks 1-35 已按本计划实施，单元/合同/静态边界测试通过；live DashScope 与 live Neo4j 未验证，skipped 不计为通过。
- 03 决策模块不调用模型、不写缓存、不写 Neo4j、不创建 RecognitionRun；默认 `write_back=false`，`write_back_recommendation` 只是建议；candidate 不等于 formal。
- 执行衔接已预留：`SemanticTargetInput` 精确目标合同、`DrawingGraphToolFacade.recognize_semantic_targets()`、`SemanticRecognitionService.recognize_targets()`（执行前二次缓存校验）与 `create_semantic_gap_decision_service()`。
- 完整 `DrawingAssistantService`、证据融合、答案生成、反馈状态机与产品级 adapter 仍属后续范围。
