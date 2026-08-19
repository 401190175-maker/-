# 证据融合与缓存闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 按任务逐项实施；每个任务完成后单独评审和验证。

**Goal:** 在复用 01–04 产品链路、现有语义缓存和受控持久化能力的前提下，实现确定性的证据组织、规范化、冲突分析、stale/lineage、claim 支撑、answerability 与缓存闭环。

**Architecture:** 新增位于 04 之后、06 之前的 `EvidenceFusionService`，只消费强类型 DTO，固定执行投影、规范化、去重、lineage、冲突、claim 支撑、answerability、缓存汇总和可选受控写回。05 不查询 Neo4j、不调用模型、不提升候选关系；产品链路中的 04 先 dry-run 产生已验证批次，05 通过授权与冲突门控后复用同一持久化组件完成延迟写回。

**Tech Stack:** Python 3.11+、dataclasses/Enum、标准库 `unittest`、现有 assistant/recognition/semantic/facade 模块、Neo4j 5.x（仅受控 repository 集成测试）。

## 全局约束

- 本文只定义实施任务，不实施代码；禁止无意义重构，只修改各任务明确列出的文件。
- 每个任务只交付一个可独立评审的能力；实施时先增加失败断言、确认失败、做最小实现，再运行该任务列出的测试。
- 默认 `write_back=false`；dry-run 不持久化 run、attempt、payload、语义节点、stale 状态或 persistent cache。
- `EvidenceFusionService` 不调用 Neo4j、repository、Cypher、Qwen/DashScope、HTTP、MCP、CLI 或候选提升接口。
- 来源事实、派生关系、语义观察、语义解释、候选关系、正式关系和 diagnostic 必须保持分层；融合、置信度、用户确认和写回授权均不得提升 `fact_kind`。
- `candidate_relation` 只能支撑可能关系，不能支撑 confirmed/formal claim；正式关系提升仍只属于 `CandidateReviewService`。
- `cache_key` 只用于精确复用；`evidence_family_key` 只用于 lineage/stale；`comparison_key` 只用于可比证据分组；`content_fingerprint` 只用于确定性去重。
- `RecognitionRun`/`RecognitionAttempt` 保持图谱外；图谱内语义证据只通过稳定 `recognition_run_id` 关联。
- 不新增 Neo4j 业务节点、业务关系、来源事实约束或索引；只允许为既有语义证据增加设计规定的可选 lineage/stale 属性。
- 不新增 OCR、事件平台、消息队列、工作流引擎、通用规则 DSL、外部产品 API 或第二套缓存算法。
- 单元/fake、live Neo4j、live DashScope 和完整产品链路验证必须分开报告；skipped 不得报告为 live 验证通过。

## 文件责任与实施顺序

| 文件 | 单一责任 | 首次建立任务 |
|---|---|---:|
| `assistant_evidence_fusion_models.py` | 05 枚举、不可变 DTO 和协议输入输出合同 | Task 1 |
| `assistant_recognition_projection.py` | 04 结果到统一证据的安全投影 | Task 8 |
| `assistant_evidence_normalization.py` | 规范化、能力、比较键、family key 与 fingerprint | Task 12 |
| `assistant_evidence_deduplication.py` | 内容去重与 provenance 保留 | Task 19 |
| `assistant_evidence_rules.py` | 03/05 共用的 scope、fact/status/formal 纯规则 | Task 20 |
| `assistant_evidence_lineage.py` | 同族证据的 supersede/stale 计划 | Task 22 |
| `assistant_evidence_conflicts.py` | 确定性冲突矩阵和稳定冲突 ID | Task 24 |
| `assistant_claim_support.py` | 逐 requirement 的 claim 支撑评估 | Task 28 |
| `assistant_answerability.py` | subrequest/request answerability 聚合 | Task 31 |
| `assistant_cache_closure.py` | expected/actual/lineage/write-back 缓存汇总 | Task 36 |
| `assistant_semantic_write_back.py` | 写回门控与受控持久化 adapter | Task 43 |
| `assistant_evidence_fusion.py` | 05 唯一编排入口 | Task 46 |
| `assistant_evidence_fusion_factory.py` | 无副作用默认装配与可选 port 注入 | Task 48 |

## 任务总览

1. 融合枚举与原因码合同
2. FusionEvidence 与 provenance 合同
3. 冲突合同
4. Claim 支撑与 answerability 合同
5. Lineage 与缓存汇总合同
6. 受控写回合同
7. 融合请求与 EvidenceBundle 合同
8. TextObservation 识别投影
9. Interpretation 识别投影
10. Candidate 与 diagnostic 识别投影
11. 识别目标 scope 校验与隔离
12. 规范化规则注册表
13. Comparison key 构造
14. Evidence family key 构造
15. Content fingerprint 构造
16. Claim capability 注册表
17. 通用值与关系规范化
18. 断面标签规范化复用
19. 确定性证据去重
20. 03/05 共用证据门控规则
21. 证据集合 freshness 窄接口
22. Stale policy 注册表
23. Lineage 与 supersede 计划
24. 冲突分组与稳定冲突 ID
25. Source/derived 冲突矩阵
26. Semantic 冲突矩阵
27. Relation/diagnostic 冲突矩阵
28. Requirement 到 claim capability 映射
29. Claim scope/status/freshness 支撑判断
30. Claim 冲突、formal gate 与限定语
31. Subrequest answerability
32. Request answerability 聚合
33. 检索证据融合元数据补齐
34. CacheOutcome 公共合同与实际命中结果
35. Dry-run request memo 与 persistent cache 隔离
36. Cache closure 汇总
37. 稳定 recognition_run_id
38. SemanticWriteBatch 构造
39. 既有持久化尾部提取复用
40. 语义 lineage repository port
41. Neo4j stale/supersede 受控写入
42. 语义 lineage 只读投影
43. 写回授权与安全门控
44. 写回状态机与部分成功
45. Facade 与 factory 写回兼容
46. 融合输入关联校验
47. EvidenceFusionService 固定流水线
48. 融合工厂装配
49. 纯融合静态依赖边界
50. 输出数据最小化与错误脱敏
51. 融合资源上限
52. 架构与模块文档同步
53. Change 文档状态同步
54. 专项文档合同测试
55. 05 专项回归验收
56. 完整离线回归与 live 状态记录

---

## Task 1：融合枚举与原因码合同

**明确目标：** 定义 05 使用的稳定枚举和公开原因码，作为后续模块唯一的状态字符串来源。

**指定修改文件：**

- 新增：`src/drawing_graph/assistant_evidence_fusion_models.py`
- 修改：`src/drawing_graph/assistant_models.py`
- 新增：`tests/test_assistant_evidence_fusion_models.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_fusion_models -v
```

**完成标准：**

- `Answerability`、`ClaimCapability`、`ClaimSupportStatus`、`EvidenceComparison`、`ConflictType`、`ConflictSeverity`、`CacheClosureStatus`、`WriteBackStatus` 和 `WriteBackItemStatus` 与 design.md 稳定值一致。
- `ReasonCode` 只添加 05 所需稳定值，不删除或改名现有值。
- 未知枚举值被拒绝，序列化不依赖中文文案。
- 新模块只依赖公共合同，不导入数据库、模型客户端或 adapter。

## Task 2：FusionEvidence 与 provenance 合同

**明确目标：** 定义包装原始 `EvidenceItem` 的融合证据和 provenance 合同，不修改原始证据值或事实等级。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_evidence_fusion_models.py`
- 修改：`tests/test_assistant_evidence_fusion_models.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_fusion_models -v
```

**完成标准：**

- 存在不可变 `FusionMetadata`、`EvidenceProvenance` 和 `FusionEvidence`。
- `FusionMetadata` 能表达 normalized value、四类 key、capabilities、freshness 与版本，但不包含 secret、原始 payload 或绝对路径。
- `FusionEvidence.item` 保留原 `EvidenceItem.value`、`fact_kind` 和稳定 ID。
- 现有 `EvidenceItem` 构造方式保持兼容。

## Task 3：冲突合同

**明确目标：** 定义可解释、可稳定排序的冲突记录合同。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_evidence_fusion_models.py`
- 修改：`tests/test_assistant_evidence_fusion_models.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_fusion_models -v
```

**完成标准：**

- `ConflictRecord` 包含 conflict ID、comparison key、排序后的 evidence IDs、类型、严重度、blocking、原因码与安全摘要。
- 合同能表达多方冲突，不要求选出 winner。
- blocking 与 severity 的非法组合被校验拒绝或按明确规则规范化。
- 合同不携带 traceback、Cypher、provider 原文或完整 payload。

## Task 4：Claim 支撑与 answerability 合同

**明确目标：** 定义逐 requirement 支撑结果和 answerability 计算结果的稳定 DTO。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_evidence_fusion_models.py`
- 修改：`tests/test_assistant_evidence_fusion_models.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_fusion_models -v
```

**完成标准：**

- `ClaimSupportAssessment` 能记录 requirement、capability、采用/拒绝/冲突证据、限定语和原因码。
- `AnswerabilityResult` 能表达 subrequest 与 request 级状态、阻断原因和受影响 requirement。
- `formal_review_required` 是 claim support 状态，不被伪装成正式关系已确认。
- DTO 使用 tuple/不可变集合语义并具有确定性序列化顺序。

## Task 5：Lineage 与缓存汇总合同

**明确目标：** 定义 evidence lineage、待执行 lineage 计划和逐目标/请求级缓存汇总合同。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_evidence_fusion_models.py`
- 修改：`tests/test_assistant_evidence_fusion_models.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_fusion_models -v
```

**完成标准：**

- 存在 `EvidenceLineage`、`LineagePlan`、`CacheTargetSummary` 和 `CacheSummary`。
- lineage 明确 current、superseded、family、stale reason，不把 lineage 当成 formal relation。
- cache summary 区分 expected、actual、provider_called、evidence IDs、run ID 与 persistent commit。
- `unknown`、`stale` 和 `miss` 语义彼此独立。

## Task 6：受控写回合同

**明确目标：** 定义强类型写回批次、策略、逐项结果和总结果合同。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_evidence_fusion_models.py`
- 修改：`tests/test_assistant_evidence_fusion_models.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_fusion_models -v
```

**完成标准：**

- 存在 `SemanticWriteBatch`、`WriteBackPolicy`、`WriteBackItemResult` 和 `WriteBackResult`。
- policy 显式包含 request/module/environment 三层授权和 schema、scope、payload、audit、conflict、cache 门控。
- batch 只接受已验证的 run/attempt/payload envelope/observation/interpretation/candidate audit/cache entry，不接受任意 Cypher、Label 或 dict 写命令。
- `not_requested`、`skipped`、`persisted`、`partial`、`failed` 能准确区分。

## Task 7：融合请求与 EvidenceBundle 合同

**明确目标：** 定义 05 唯一输入 `EvidenceFusionRequest` 和唯一输出 `EvidenceBundle`。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_evidence_fusion_models.py`
- 修改：`tests/test_assistant_evidence_fusion_models.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_fusion_models -v
```

**完成标准：**

- request 显式携带 `AssistantRequest`、`QuestionUnderstandingResult`、`RetrievalBundle`、`SemanticGapDecision`、recognition results 和 `WriteBackPolicy`。
- bundle 包含 accepted/conflicting evidence、conflicts、claim support、unsupported claims、lineage、cache、provenance、confidence、answerability、warnings 和 write-back result。
- `accepted_evidence` 的合同文档明确表示“可用于当前回答”，不表示已持久化或 formal。
- 所有新增字段都有明确默认值或构造校验，不破坏 01–04 公共合同。

## Task 8：TextObservation 识别投影

**明确目标：** 将 04 返回的 `TextObservation` 安全投影为 `semantic_observation` EvidenceItem。

**指定修改文件：**

- 新增：`src/drawing_graph/assistant_recognition_projection.py`
- 新增：`tests/test_assistant_recognition_projection.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_recognition_projection.RecognitionObservationProjectionTests -v
```

**完成标准：**

- observation 保留 evidence ID、page/element scope、bbox、run、payload、版本和置信度。
- 输出 `fact_kind` 固定为 `semantic_observation`，不能由模型自由字段覆盖。
- 原观察文本不被规范化结果覆盖。
- 投影不访问文件、缓存、provider 或数据库。

## Task 9：Interpretation 识别投影

**明确目标：** 将三类 interpretation 安全投影为 `semantic_interpretation` EvidenceItem。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_recognition_projection.py`
- 修改：`tests/test_assistant_recognition_projection.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_recognition_projection.RecognitionInterpretationProjectionTests -v
```

**完成标准：**

- Block、BasicInfo、Table interpretation 均投影到稳定 scope 和 value slot。
- `SUPPORTED_BY` 引用保留为 evidence refs，不把 interpretation 提升为 observation/source/formal。
- stale/status、model/prompt/contract/preprocessing 版本完整保留。
- `interpreted_type` 不写入或暗示 `DrawingBlock.block_type` 已改变。

## Task 10：Candidate 与 diagnostic 识别投影

**明确目标：** 将 relation candidate 与执行摘要分别投影到 candidate 和 diagnostic 桶。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_recognition_projection.py`
- 修改：`tests/test_assistant_recognition_projection.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_recognition_projection.RecognitionCandidateDiagnosticProjectionTests -v
```

**完成标准：**

- candidate evidence 固定为 `candidate_relation`，保留 relation type、方向和 candidate group。
- summary、usage、cost、latency、attempt 状态、安全错误和 persisted 状态只进入 `diagnostic`。
- projector 永不产生 `source_fact`、`derived_relation` 或 `formal_relation`。
- candidate 不触发关系写入或候选提升。

## Task 11：识别目标 scope 校验与隔离

**明确目标：** 对 recognition result 与 selected target 的归属关系做 fail-closed 校验，并隔离无法安全归属的输出。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_recognition_projection.py`
- 修改：`tests/test_assistant_recognition_projection.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_recognition_projection.RecognitionScopeProjectionTests -v
```

**完成标准：**

- page、element、bbox 和 target ID 必须与 selected targets 唯一对应。
- 跨页、额外 target 或 bbox 不一致的输出进入 rejected outputs，并生成 `recognition_scope_mismatch` diagnostic。
- 单条 optional 输出失败可降级，required 输出受影响时留下稳定原因码。
- 投影器不猜测或扩张请求 scope。

## Task 12：规范化规则注册表

**明确目标：** 建立不可变、版本化的规范化规则注册和查找机制。

**指定修改文件：**

- 新增：`src/drawing_graph/assistant_evidence_normalization.py`
- 新增：`tests/test_assistant_evidence_normalization.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_normalization.NormalizationRegistryTests -v
```

**完成标准：**

- `NormalizationRuleRegistry` 按 fact kind、task type 和 value slot 唯一路由规则。
- 重复规则、空版本、未知 slot 和可变注册表被拒绝。
- 规则缺失时返回稳定失败，不使用通用字符串猜测。
- registry 无文件、网络、环境变量或数据库副作用。

## Task 13：Comparison key 构造

**明确目标：** 生成只用于可比证据分组的稳定 `comparison_key`。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_evidence_normalization.py`
- 修改：`tests/test_assistant_evidence_normalization.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_normalization.ComparisonKeyTests -v
```

**完成标准：**

- key 由 scope、predicate/value slot 和 qualifiers 的规范 JSON 生成。
- 不同 scope、关系方向或时间基线不会得到相同 key。
- key 不包含 confidence、secret、绝对路径、payload 或 provider 原文。
- 相同输入跨顺序和进程生成相同结果。

## Task 14：Evidence family key 构造

**明确目标：** 生成只用于 lineage/stale 的稳定 `evidence_family_key`。

**指定修改文件：**

- 修改：`src/drawing_graph/semantic_cache.py`
- 修改：`src/drawing_graph/assistant_evidence_normalization.py`
- 修改：`tests/test_semantic_cache.py`
- 修改：`tests/test_assistant_evidence_normalization.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_semantic_cache.EvidenceFamilyKeyTests tests.test_assistant_evidence_normalization.EvidenceFamilyKeyTests -v
```

**完成标准：**

- 存在 `EvidenceFamilyKeyInput` 和 `build_evidence_family_key()` 唯一算法。
- family key 只含稳定 target、task、output slot 和 normalization scope。
- image/model/prompt/contract 版本变化可保持同族，但仍生成不同精确 cache key。
- 任何 cache lookup/put 接口拒绝把 family key 当精确 cache key 使用。

## Task 15：Content fingerprint 构造

**明确目标：** 为确定性去重生成版本化的内容 fingerprint。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_evidence_normalization.py`
- 修改：`tests/test_assistant_evidence_normalization.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_normalization.ContentFingerprintTests -v
```

**完成标准：**

- fingerprint 使用 fact kind、comparison key、normalized value 和可信 source fingerprint 的规范 JSON。
- 字典键顺序或 provenance 顺序变化不改变结果。
- scope、关系方向、事实等级或规范化值变化会改变结果。
- fingerprint 不承担 cache hit 或 lineage 判定职责。

## Task 16：Claim capability 注册表

**明确目标：** 从可信 fact kind、schema field 和 relation type 推导证据可支撑的 claim capability。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_evidence_normalization.py`
- 修改：`tests/test_assistant_evidence_normalization.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_normalization.ClaimCapabilityRegistryTests -v
```

**完成标准：**

- 七类 capability 映射与 design.md 矩阵一致。
- candidate 只能获得 `possible_relation`，diagnostic 只能获得 `runtime_or_cache_status`。
- 模型自由文本中的 capability/fact kind 声明不作为权威输入。
- 未注册 schema slot fail closed 为 unsupported。

## Task 17：通用值与关系规范化

**明确目标：** 将普通文本、bbox 和有向关系转换为可比较的规范化值，同时保留原值。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_evidence_normalization.py`
- 修改：`tests/test_assistant_evidence_normalization.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_normalization.EvidenceNormalizerTests -v
```

**完成标准：**

- 文本规范化不覆盖 `EvidenceItem.value`，bbox 统一为四坐标结构。
- 关系值固定为 subject/predicate/object 方向，反向关系不被错误合并。
- 输出同时填充规范化版本、comparison key、family key、fingerprint 和 capabilities。
- 不可规范化值被隔离并保留原 evidence ID，不猜测补值。

## Task 18：断面标签规范化复用

**明确目标：** 在融合规范化中复用现有 `SectionLabelNormalizer`，避免第二套断面符号规则。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_evidence_normalization.py`
- 修改：`tests/test_assistant_evidence_normalization.py`
- 修改：`tests/test_section_label_normalization.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_normalization.SectionNormalizationReuseTests tests.test_section_label_normalization -v
```

**完成标准：**

- alphabetic、roman、numeric、alphanumeric、unknown 分类与既有规则一致。
- 未经 alias rule 不自动合并 `I-I`、`Ⅰ-Ⅰ` 和 `1-1`。
- 原始标签和符号体系保留在 provenance/normalized structure 中。
- 既有断面匹配行为无回归。

## Task 19：确定性证据去重

**明确目标：** 只合并事实等级、comparison key、normalized value 和 fingerprint 全部相同的证据，并保留全部 provenance。

**指定修改文件：**

- 新增：`src/drawing_graph/assistant_evidence_deduplication.py`
- 新增：`tests/test_assistant_evidence_deduplication.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_deduplication -v
```

**完成标准：**

- 不同 fact kind、scope、关系方向或规范化槽永不合并。
- 合并结果保留全部原 evidence IDs、run、attempt、payload 和 source refs。
- canonical 选择按“持久化稳定 ID、created/version、evidence ID”确定性排序。
- 去重只影响展示分组，不改变事实等级、置信度或持久化状态。

## Task 20：03/05 共用证据门控规则

**明确目标：** 抽取 scope、fact-kind、status 和 formal gate 的纯规则供 03 与 05 共用，保持 03 行为兼容。

**指定修改文件：**

- 新增：`src/drawing_graph/assistant_evidence_rules.py`
- 修改：`src/drawing_graph/assistant_evidence_sufficiency.py`
- 新增：`tests/test_assistant_evidence_rules.py`
- 修改：`tests/test_assistant_evidence_sufficiency.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_rules tests.test_assistant_evidence_sufficiency -v
```

**完成标准：**

- helper 分别暴露 scope match、fact-kind gate、minimum status gate 和 formal gate。
- 03 原入口、原因码和既有用例保持兼容。
- candidate/semantic 仍不能满足 formal/source fact requirement。
- 05 只依赖纯 helper，不反向调用完整 `SemanticGapDecisionService`。

## Task 21：证据集合 freshness 窄接口

**明确目标：** 在现有 freshness 权威实现上增加针对任意证据集合的窄评估接口。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_evidence_freshness.py`
- 修改：`tests/test_assistant_evidence_freshness.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_freshness -v
```

**完成标准：**

- 新 helper 复用现有 image/bbox/model/prompt/preprocessing/normalization/contract/age 规则。
- 缺关键元数据返回 unknown/stale，不默认 current。
- 03 原 evaluator API 和 cache disposition 行为不变。
- helper 只读，不做 cache get/put、模型调用或持久化。

## Task 22：Stale policy 注册表

**明确目标：** 定义 observation 与 interpretation 分离的 stale 策略，并限制可被语义 lineage 处理的事实类型。

**指定修改文件：**

- 新增：`src/drawing_graph/assistant_evidence_lineage.py`
- 新增：`tests/test_assistant_evidence_lineage.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_lineage.StalePolicyRegistryTests -v
```

**完成标准：**

- `StalePolicyRegistry` 分别注册 observation 和 interpretation 策略。
- source、derived、candidate、formal 和 diagnostic 被明确排除。
- registry 缺失或重复策略时 fail closed。
- 策略只生成判断，不执行 repository 写入。

## Task 23：Lineage 与 supersede 计划

**明确目标：** 按 evidence family 和 freshness 生成 lineage 结果及待写回 supersede/stale 计划。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_evidence_lineage.py`
- 修改：`tests/test_assistant_evidence_lineage.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_lineage.EvidenceLineageResolverTests -v
```

**完成标准：**

- 同 cache key 且同内容只表示复用，不产生 supersede。
- 同 family、不同 cache key 且新证据 current/valid 时才生成 supersede 候选。
- resolver 不修改持久化旧证据；写回失败时仅在本次 bundle 中限制旧证据使用。
- 输出排序和 lineage ID 对相同输入稳定。

## Task 24：冲突分组与稳定冲突 ID

**明确目标：** 建立仅比较同 comparison key/明确可比 family 的冲突检测骨架和稳定 ID 算法。

**指定修改文件：**

- 新增：`src/drawing_graph/assistant_evidence_conflicts.py`
- 新增：`tests/test_assistant_evidence_conflicts.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_conflicts.ConflictGroupingTests -v
```

**完成标准：**

- 不同 scope/slot 默认 `not_comparable`，不产生伪冲突。
- conflict ID 由 comparison key、conflict type 和排序后的 evidence IDs 确定性生成。
- 冲突组比较受大小上限约束，不执行无界全量笛卡尔积。
- confidence 仅作为诊断字段，不单独选 winner。

## Task 25：Source/derived 冲突矩阵

**明确目标：** 实现 source fact 与 derived relation 相关的冲突矩阵规则。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_evidence_conflicts.py`
- 修改：`tests/test_assistant_evidence_conflicts.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_conflicts.SourceDerivedConflictMatrixTests -v
```

**完成标准：**

- source/source 同键不同值为 blocking `hard_conflict`。
- source/derived 默认互补，派生否定来源时为 `rule_conflict`。
- derived/derived 同规格同槽不同目标为 `rule_conflict`。
- 任何规则都不覆盖或删除来源事实。

## Task 26：Semantic 冲突矩阵

**明确目标：** 实现 observation/interpretation 与 source/derived/彼此之间的语义冲突规则。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_evidence_conflicts.py`
- 修改：`tests/test_assistant_evidence_conflicts.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_conflicts.SemanticConflictMatrixTests -v
```

**完成标准：**

- model/source、semantic/rule、observation peer、interpretation peer 冲突类型与 design.md 一致。
- interpretation 未引用必要 observation 时产生 `support_conflict`。
- stale 证据不作为 current winner，但仍保留在冲突/lineage 输出。
- 语义高置信度不能覆盖 source 或 formal 事实等级。

## Task 27：Relation/diagnostic 冲突矩阵

**明确目标：** 实现 candidate/formal/diagnostic 相关冲突规则并保留候选历史。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_evidence_conflicts.py`
- 修改：`tests/test_assistant_evidence_conflicts.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_conflicts.RelationDiagnosticConflictMatrixTests -v
```

**完成标准：**

- 同候选组多目标为 `candidate_ambiguity`，不自动选择 winner。
- candidate/formal 共存时 formal 可支撑当前正式状态，candidate 不被删除或提升。
- formal/formal 互斥为 critical/blocking integrity conflict；formal/semantic 不撤销 formal。
- 同 run diagnostic 状态矛盾产生 `diagnostic_conflict`。

## Task 28：Requirement 到 claim capability 映射

**明确目标：** 将完整 `EvidenceRequirement` 确定性映射到所需 claim capability。

**指定修改文件：**

- 新增：`src/drawing_graph/assistant_claim_support.py`
- 新增：`tests/test_assistant_claim_support.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_claim_support.RequirementCapabilityMappingTests -v
```

**完成标准：**

- identity/location、confirmed relation、rule context、observed symbol、semantic meaning、possible relation、runtime/cache 均有明确映射。
- 未知 requirement/schema slot 返回 unsupported，不使用通用 fallback 提升证据。
- required/optional、minimum status、freshness 和 formal 要求完整保留。
- 映射不读取问题自由文本来放宽 capability。

## Task 29：Claim scope/status/freshness 支撑判断

**明确目标：** 按固定顺序评估证据对 requirement 的 scope、capability、minimum status 和 freshness 支撑。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_claim_support.py`
- 修改：`tests/test_assistant_claim_support.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_claim_support.ClaimSupportGateTests -v
```

**完成标准：**

- 评估顺序固定为 scope、capability、minimum status、freshness。
- current observation 可支撑 observed text；stale-only 只能得到 `stale_only`。
- interpretation 支撑 semantic meaning 时必须满足其 observation 支撑链要求。
- 被拒绝证据 ID 和原因码完整保留。

## Task 30：Claim 冲突、formal gate 与限定语

**明确目标：** 完成 claim 支撑的冲突门控、formal gate 和限定性支撑输出。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_claim_support.py`
- 修改：`tests/test_assistant_claim_support.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_claim_support.ClaimConflictFormalGateTests -v
```

**完成标准：**

- blocking/critical 冲突令相关 claim 为 conflicting，不能悄悄忽略。
- required formal claim 只有 candidate 时为 `formal_review_required`。
- 低置信、partial 或非阻断歧义只在规则许可时产生 `supported_with_qualifier`。
- 每个 assessment 使用稳定 evidence/conflict ID 排序。

## Task 31：Subrequest answerability

**明确目标：** 根据单个 subrequest 的 required/optional claim support 和冲突计算 answerability。

**指定修改文件：**

- 新增：`src/drawing_graph/assistant_answerability.py`
- 新增：`tests/test_assistant_answerability.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_answerability.SubrequestAnswerabilityTests -v
```

**完成标准：**

- scope 缺失/冲突/指代不唯一优先为 `clarification_required`。
- 所有 required 满足且无 blocking conflict 才为 `answerable`。
- missing、stale-only、识别失败、deferred 或 formal review 令结果至多 `partially_answerable`。
- capability 不支持且没有可答 required 时为 `unsupported`。

## Task 32：Request answerability 聚合

**明确目标：** 按明确优先级将多个 subrequest 状态聚合为 request 级 answerability。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_answerability.py`
- 修改：`tests/test_assistant_answerability.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_answerability.RequestAnswerabilityTests -v
```

**完成标准：**

- 全部 answerable 才聚合为 answerable。
- 任一不可继续的 clarification 优先为 clarification required。
- 全部 unsupported 才为 unsupported，其余混合状态为 partially answerable。
- 输出保留每个 subrequest 的状态和原因，不丢失局部可答结果。

## Task 33：检索证据融合元数据补齐

**明确目标：** 为已持久化检索证据补齐 05 所需的稳定 task/cache/version/关系元数据，不在投影层做融合判断。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_retrieval_projection.py`
- 修改：`tests/test_assistant_retrieval_projection.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_retrieval_projection -v
```

**完成标准：**

- 可用时投影 task、cache key、image hash、model/prompt/input/output/preprocessing/normalization 版本和 created_at。
- 关系证据可用时投影 candidate group、relation type 和 direction。
- 缺失元数据保持 unknown，不伪造默认 current 值。
- projection 不生成 comparison/family key，不判冲突或 answerability。

## Task 34：CacheOutcome 公共合同与实际命中结果

**明确目标：** 让每个 recognition target 返回可核对的实际缓存处置结果。

**指定修改文件：**

- 修改：`src/drawing_graph/recognition_models.py`
- 修改：`src/drawing_graph/semantic_service.py`
- 修改：`tests/test_recognition_models.py`
- 修改：`tests/test_semantic_service.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_recognition_models.CacheOutcomeTests tests.test_semantic_service.SemanticServiceCacheOutcomeTests -v
```

**完成标准：**

- `CacheOutcome` 逐目标表达 hit/miss/bypassed、cache key、实际 evidence IDs 和 `provider_called`。
- `SemanticRecognitionResult` 以有默认值字段返回 `cache_outcomes`，保持旧构造兼容。
- cache hit 必须引用实际可复用 evidence ID，不能只凭 key 存在报告命中。
- 纯 cache hit 不创建真实执行 run/attempt。

## Task 35：Dry-run request memo 与 persistent cache 隔离

**明确目标：** 修复 dry-run 跨请求缓存写副作用，只允许请求内 memo 复用。

**指定修改文件：**

- 修改：`src/drawing_graph/semantic_cache.py`
- 修改：`src/drawing_graph/semantic_service.py`
- 修改：`src/drawing_graph/tool_factory.py`
- 修改：`tests/test_semantic_cache.py`
- 修改：`tests/test_semantic_service_dry_run.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_semantic_cache.RequestSemanticMemoTests tests.test_semantic_service_dry_run -v
```

**完成标准：**

- 存在请求生命周期内的 `RequestSemanticMemo`，同请求可复用、跨请求不可见。
- dry-run 允许 persistent cache 只读 lookup，但不调用 persistent `put`。
- 只有受控写回允许 persistent cache commit。
- 现有 `SemanticCacheService.get/put` 和 factory 默认 fake 行为保持兼容。

## Task 36：Cache closure 汇总

**明确目标：** 汇总 03 expected、04 actual、lineage 和实际写回结果，生成不夸大的请求级缓存状态。

**指定修改文件：**

- 新增：`src/drawing_graph/assistant_cache_closure.py`
- 新增：`tests/test_assistant_cache_closure.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_cache_closure -v
```

**完成标准：**

- full hit、partial hit、miss、stale、bypassed、mixed、unknown 均有参数化测试。
- expected/actual target 无法对应时为 unknown + warning，不伪报 hit。
- 只有 `persistent_cache_committed=true` 才报告跨请求缓存已建立。
- evaluator 只汇总，不直接调用 cache get/put。

## Task 37：稳定 recognition_run_id

**明确目标：** 让真实执行在 provider 调用前生成稳定 run ID，并允许延迟写回沿用同一 ID。

**指定修改文件：**

- 修改：`src/drawing_graph/recognition_run_log.py`
- 修改：`src/drawing_graph/recognition_execution.py`
- 修改：`src/drawing_graph/semantic_service.py`
- 修改：`tests/test_recognition_run_log.py`
- 修改：`tests/test_recognition_execution.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_recognition_run_log.ExplicitRunIdTests tests.test_recognition_execution.StableRunIdTests -v
```

**完成标准：**

- 每次真实执行在首次 provider 调用前生成一个 ID，并贯穿 attempt、语义 DTO 和返回结果。
- `create_run()` 接受可选显式 ID；不传时保留现有自动生成行为。
- dry-run 不写 run/attempt log，因此其 ID 不可跨请求查询。
- cache-hit 兼容 envelope ID 不进入 new run 或持久化审计。

## Task 38：SemanticWriteBatch 构造

**明确目标：** 在 04 合同校验和投影成功后构造可延迟持久化的强类型 batch，但不执行写入。

**指定修改文件：**

- 修改：`src/drawing_graph/recognition_models.py`
- 修改：`src/drawing_graph/semantic_service.py`
- 修改：`tests/test_semantic_service_dry_run.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_semantic_service_dry_run.SemanticWriteBatchTests -v
```

**完成标准：**

- `SemanticRecognitionResult.write_batch` 为可选兼容字段。
- batch 使用稳定 run ID，包含已脱敏 payload envelope、attempt、observation、interpretation、candidate audit 和 cache entry。
- schema/scope/payload/audit 完整性标志来自已执行校验，不由 05 猜测。
- 构造 batch 不调用日志、payload store、repository 或 persistent cache put。

## Task 39：既有持久化尾部提取复用

**明确目标：** 将 04 现有写回尾部提取为 `persist_validated_batch()`，供原入口和 05 adapter 共同使用。

**指定修改文件：**

- 修改：`src/drawing_graph/semantic_service.py`
- 修改：`tests/test_semantic_service_write_back.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_semantic_service_write_back.ValidatedBatchPersistenceTests -v
```

**完成标准：**

- helper 只接受已验证 `SemanticWriteBatch`，不重新调用 provider 或重新生成 run ID。
- 现有 `write_back=true` 路径委托该 helper，外部 facade 行为保持兼容。
- 相同 batch 重放遵守现有稳定 ID/幂等约束。
- candidate evidence 仅进入允许的图谱外审计，不直接写正式或候选边。

## Task 40：语义 lineage repository port

**明确目标：** 定义只允许标记既有语义 observation/interpretation stale 的窄 repository port。

**指定修改文件：**

- 修改：`src/drawing_graph/semantic_repository.py`
- 修改：`src/drawing_graph/semantic_models.py`
- 修改：`tests/test_semantic_repository.py`
- 修改：`tests/test_semantic_models.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_semantic_repository.SemanticLineagePortTests tests.test_semantic_models.SemanticLineageModelTests -v
```

**完成标准：**

- port 接口严格接收 evidence IDs、superseding ID、reason、time 和 family key。
- `TextObservation` 与三类 interpretation 以可选默认字段支持 family、normalization、supersede/stale 信息。
- `ObservationStatus` 可表达 stale，旧构造方式不破坏。
- port 不允许来源事实、派生关系、candidate/formal 关系或任意 Cypher 输入。

## Task 41：Neo4j stale/supersede 受控写入

**明确目标：** 在 Neo4j repository 中按 family 和白名单证据类型幂等更新 stale/supersede 属性。

**指定修改文件：**

- 修改：`src/drawing_graph/semantic_neo4j_repository.py`
- 修改：`tests/test_semantic_neo4j_observations.py`
- 修改：`tests/test_semantic_neo4j_interpretations.py`
- 修改：`tests/integration/test_neo4j_semantic_evidence.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_semantic_neo4j_observations.SemanticObservationLineageWriteTests tests.test_semantic_neo4j_interpretations.SemanticInterpretationLineageWriteTests -v
```

**完成标准：**

- 只更新 `TextObservation` 与三类 interpretation 的受控 lineage/stale 属性。
- 新证据未持久化或 family 不匹配时不标记旧证据 stale。
- 重放相同 lineage plan 幂等，参数值全部参数化。
- live 集成测试保留独立入口；未配置环境时明确 skipped，不计为 live 通过。

## Task 42：语义 lineage 只读投影

**明确目标：** 通过现有稳定查询 DTO 返回语义证据 lineage/stale 元数据。

**指定修改文件：**

- 修改：`src/drawing_graph/semantic_query_projection.py`
- 修改：`src/drawing_graph/tool_facade.py`
- 修改：`tests/test_semantic_query_projection.py`
- 修改：`tests/test_tool_facade_semantic_queries.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_semantic_query_projection.SemanticLineageProjectionTests tests.test_tool_facade_semantic_queries -v
```

**完成标准：**

- 投影返回 family key、superseded by、supersedes IDs、stale reason/time 和 normalization version。
- 不暴露 Neo4j 内部 ID、driver/session 或 Cypher。
- lineage 字段不被解释为正式关系或来源事实。
- 缺少新属性的历史数据仍可兼容读取。

## Task 43：写回授权与安全门控

**明确目标：** 实现 `ControlledSemanticWritePort` 协议和 request/module/environment/schema/scope/payload/audit/conflict 的 fail-closed 门控。

**指定修改文件：**

- 新增：`src/drawing_graph/assistant_semantic_write_back.py`
- 新增：`tests/test_assistant_semantic_write_back.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_semantic_write_back.WriteBackGateTests -v
```

**完成标准：**

- `AssistantRequest.allow_write_back` 与 policy request 授权必须一致，policy 只能收紧授权。
- request/module/environment 任一 false 均返回 skipped，且零持久化调用。
- schema、scope、payload、audit、allowed kind、dependency 或 blocking conflict 任一失败均 fail closed。
- recommendation、模型文本、confidence 和用户问题文字都不能提升写回授权。

## Task 44：写回状态机与部分成功

**明确目标：** 按固定阶段执行受控持久化，并准确报告各阶段部分成功与幂等重放。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_semantic_write_back.py`
- 修改：`tests/test_assistant_semantic_write_back.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_semantic_write_back.WriteBackStateMachineTests -v
```

**完成标准：**

- 顺序固定为 run/attempt/payload、semantic evidence、lineage stale、persistent cache、run completion。
- 每步返回独立 item result；后一步失败不伪造前一步未发生或整体原子成功。
- semantic 成功但 stale/cache 失败时为 partial，且只报告实际 IDs/commit 状态。
- 相同 batch 重放不重复创建证据、payload、stale 变化或 cache entry。

## Task 45：Facade 与 factory 写回兼容

**明确目标：** 让现有 facade `write_back=true` 与产品延迟写回复用同一持久化组件，同时保持默认只读入口不变。

**指定修改文件：**

- 修改：`src/drawing_graph/tool_facade.py`
- 修改：`src/drawing_graph/tool_factory.py`
- 修改：`tests/test_tool_facade.py`
- 修改：`tests/test_tool_factory.py`
- 修改：`tests/test_semantic_service_write_back.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_tool_facade tests.test_tool_factory tests.test_semantic_service_write_back -v
```

**完成标准：**

- 现有识别入口签名及默认 `write_back=false` 保持兼容。
- 直接 `write_back=true` 与 05 adapter 最终调用相同 persist component。
- factory 显式区分 persistent cache、request memo factory 与持久化组件。
- facade 不依赖 05，不暴露 repository、Cypher 或通用写接口。

## Task 46：融合输入关联校验

**明确目标：** 在任何投影或写回前校验 request/subrequest/decision/result/policy 的关联一致性。

**指定修改文件：**

- 新增：`src/drawing_graph/assistant_evidence_fusion.py`
- 新增：`tests/test_assistant_evidence_fusion.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_fusion.FusionInputValidationTests -v
```

**完成标准：**

- 四类 request ID 必须一致，subrequest 必须能唯一映射。
- recognition target 必须属于 selected targets 和当前 scope，同 run ID 不得有矛盾状态。
- policy request 授权必须等于原 `AssistantRequest` 显式授权。
- fatal 输入错误返回稳定脱敏 `FusionInputError`，且下游组件和写回 port 零调用。

## Task 47：EvidenceFusionService 固定流水线

**明确目标：** 实现 05 唯一编排入口并产出稳定排序的完整 `EvidenceBundle`。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_evidence_fusion.py`
- 修改：`tests/test_assistant_evidence_fusion.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_fusion.EvidenceFusionPipelineTests -v
```

**完成标准：**

- 顺序固定为校验、收集、投影、规范化、去重、freshness/lineage、冲突、claim、answerability、pre-cache、可选写回、final-cache/bundle。
- `write_back=false` 产出完整临时 bundle 且零持久化；写回失败不抹去本次可用证据。
- 单条可选投影/规范化失败可降级，registry/事实越权等 fatal 错误 fail closed。
- 输出按 subrequest、requirement、comparison key、fact kind、evidence ID 稳定排序。

## Task 48：融合工厂装配

**明确目标：** 提供无副作用的默认融合工厂，并允许最外层显式注入受控写回 port 和规则注册表。

**指定修改文件：**

- 新增：`src/drawing_graph/assistant_evidence_fusion_factory.py`
- 新增：`tests/test_assistant_evidence_fusion_factory.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_fusion_factory -v
```

**完成标准：**

- `create_evidence_fusion_service()` 默认装配全部纯组件且 `controlled_write_port=None`。
- 默认实例收到写回请求时返回 persistence unavailable/skipped，不创建数据库或模型客户端。
- 可注入 normalization、capability、stale policy 和 controlled port。
- import/factory 不读取 secret、环境变量、图片或数据目录，不产生网络/数据库副作用。

## Task 49：纯融合静态依赖边界

**明确目标：** 用静态测试锁定 05 纯模块和现有只读 adapter 的依赖方向。

**指定修改文件：**

- 新增：`tests/test_assistant_evidence_fusion_boundaries.py`
- 修改：`tests/test_qa_mcp_boundaries.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_fusion_boundaries.FusionDependencyBoundaryTests tests.test_qa_mcp_boundaries -v
```

**完成标准：**

- 纯融合模块禁止导入 neo4j、semantic Neo4j repository、relation repository、candidate review、Qwen、HTTP/MCP/CLI。
- 只有 `assistant_semantic_write_back.py` 可依赖受控 application persistence component，仍不得直接导入 Neo4j repository 或 Cypher。
- QAService/HTTP/MCP 不反向依赖 05 或获得写回能力。
- facade 不依赖 05，融合工厂不在 import 时创建外部连接。

## Task 50：输出数据最小化与错误脱敏

**明确目标：** 保证融合投影、错误和最终 bundle 只暴露完成 claim 支撑所需的安全摘要与稳定引用。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_recognition_projection.py`
- 修改：`src/drawing_graph/assistant_evidence_fusion.py`
- 修改：`tests/test_assistant_recognition_projection.py`
- 修改：`tests/test_assistant_evidence_fusion_boundaries.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_recognition_projection.ProjectionDataMinimizationTests tests.test_assistant_evidence_fusion_boundaries.FusionRedactionTests -v
```

**完成标准：**

- 默认 bundle 只含摘要、稳定 ID、必要 provenance 和 `payload_ref`，不展开大 payload。
- 对外错误和 diagnostics 不包含 secret、绝对路径、Base64、完整 prompt/payload/provider error 或 traceback。
- 模型文本、payload 内容和图内指令始终作为数据，不触发命令、查询或事实等级变化。
- 脱敏失败时 fail closed，不回退输出原始异常正文。

## Task 51：融合资源上限

**明确目标：** 为 evidence、recognition result、conflict group、provenance 和 write batch 建立确定性资源上限。

**指定修改文件：**

- 修改：`src/drawing_graph/assistant_evidence_fusion.py`
- 修改：`src/drawing_graph/assistant_evidence_conflicts.py`
- 修改：`src/drawing_graph/assistant_semantic_write_back.py`
- 修改：`tests/test_assistant_evidence_fusion_boundaries.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_fusion_boundaries.FusionResourceLimitTests -v
```

**完成标准：**

- 每类集合有显式正整数上限，非法或超大配置被拒绝。
- 超限时按稳定顺序截断或拒绝并输出原因码，不依赖集合偶然顺序。
- required evidence 被截断时 answerability 不得为 answerable。
- 冲突检测按 comparison key 分组，禁止无界全量笛卡尔积；write batch 同时限制证据数、payload 大小和 attempt 数。

## Task 52：架构与模块文档同步

**明确目标：** 在实现证据齐全后，把 05 的已实现架构、模块职责和用户边界同步到当前维护文档。

**指定修改文件：**

- 修改：`architecture.md`
- 修改：`Module.md`
- 修改：`README.md`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_readme tests.test_assistant_docs tests.test_semantic_docs -v
```

**完成标准：**

- 文档准确说明 03/04/05 分工、默认只读、延迟写回、四类 key、冲突、claim 和 answerability。
- 文档不把候选写成 formal，不把 dry-run ID 写成已持久化 run。
- 文档明确 05 不新增外部 API，也不代表 06/07 完整产品闭环已实现。
- 不改写与本功能无关的导入、增强、QA、HTTP 或 MCP 章节。

## Task 53：Change 文档状态同步

**明确目标：** 在实现与验证完成后，将本 change 的分析、proposal、design 和 tasks 状态更新为与事实一致的实施记录。

**指定修改文件：**

- 修改：`changes/产品实现层/证据融合与缓存闭环/Feature_Analysis_Report.md`
- 修改：`changes/产品实现层/证据融合与缓存闭环/proposal.md`
- 修改：`changes/产品实现层/证据融合与缓存闭环/design.md`
- 修改：`changes/产品实现层/证据融合与缓存闭环/tasks.md`

**可独立测试：**

```powershell
rg -n "文档状态|已实现|未实施|write_back=false|candidate|formal|live Neo4j|live DashScope" changes\产品实现层\证据融合与缓存闭环\*.md
```

**完成标准：**

- 每份文档的状态、日期、已实现与未实现范围一致。
- 任务完成标记只依据对应测试证据，不因整体进度推断。
- 设计差异以显式变更记录说明，不静默改写原决策。
- live 验证状态如实记录，skipped 不写成已通过。

## Task 54：专项文档合同测试

**明确目标：** 建立自动化文档合同，防止 05 的核心边界在后续维护中漂移。

**指定修改文件：**

- 新增：`tests/test_assistant_evidence_fusion_docs.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_fusion_docs -v
```

**完成标准：**

- 测试覆盖三份根文档与四份 change 文档的 03/04/05 分工和默认只读表述。
- 测试锁定 candidate 不等于 formal、family key 不用于 cache hit、05 不调用模型/Neo4j/Cypher。
- 测试锁定“不新增外部 API”和“06/07 未因 05 自动完成”。
- 测试不依赖易变的总行数、整段文案或测试总数。

## Task 55：05 专项回归验收

**明确目标：** 运行并记录仅覆盖 05 及其直接兼容面的专项离线回归。

**指定修改文件：**

- 修改：`changes/产品实现层/证据融合与缓存闭环/tasks.md`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_fusion_models tests.test_assistant_recognition_projection tests.test_assistant_evidence_normalization tests.test_assistant_evidence_deduplication tests.test_assistant_evidence_rules tests.test_assistant_evidence_lineage tests.test_assistant_evidence_conflicts tests.test_assistant_claim_support tests.test_assistant_answerability tests.test_assistant_cache_closure tests.test_assistant_semantic_write_back tests.test_assistant_evidence_fusion tests.test_assistant_evidence_fusion_factory tests.test_assistant_evidence_fusion_boundaries tests.test_assistant_evidence_fusion_docs -v
```

**完成标准：**

- 命令退出码为 0，05 专项及直接边界用例全部通过。
- 实际执行时间、通过数、失败数、错误数和 skipped 数写入任务记录。
- skipped 单独列出原因，不计入 live Neo4j 或 live DashScope 通过。
- 未执行的 live/完整产品验证不在本任务中做成功声明。

## Task 56：完整离线回归与 live 状态记录

**明确目标：** 运行整个仓库的离线测试并单独记录 live Neo4j、live DashScope 和完整产品链路验证状态。

**指定修改文件：**

- 修改：`changes/产品实现层/证据融合与缓存闭环/tasks.md`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest discover tests -v
```

**完成标准：**

- 完整回归命令退出码为 0；通过、失败、错误和 skipped 数按实际输出记录。
- 01–04、QA、HTTP、MCP、导入、关系增强和候选审核兼容回归无新增失败。
- live Neo4j、live DashScope、黄金集和完整 `DrawingAssistantService -> 06/07` 链路分别标记为已验证、未验证或 skipped。
- 没有把 fake、单元、HTTP health、MCP smoke 或 skipped 集成测试报告成 live 验证。

---

## 任务依赖与执行规则

- Task 1–7 先建立合同；后续任务不得私自创建同名 DTO、枚举或并行字符串常量。
- Task 8–11 完成识别结果投影后，Task 12–19 才能对统一证据做规范化和去重。
- Task 20–23 建立共享门控、freshness 与 lineage；Task 24–32 在其输出上完成冲突、claim 和 answerability。
- Task 33–45 是缓存和持久化闭环；任何任务都不得为方便测试绕过 facade/application port 直接调用 Neo4j。
- Task 46–48 最后装配纯融合链；Task 49–51 锁定静态、安全和资源边界；Task 52–54 在实现证据齐全后同步并锁定文档；Task 55–56 分别执行专项与完整验收。
- 每完成一个 Task，只提交该任务列出的源码、测试和必要文档；若发现设计缺口，先更新本 change 的 proposal/design/tasks 并经评审，不在实现中静默扩展范围。

## 最终完成定义

全部任务只有同时满足以下条件才可宣布完成：

1. 56 个任务均有独立红—绿测试证据，且没有把多个未验收能力合并为一次完成声明。
2. 相同输入产生稳定 evidence/conflict/lineage/cache/bundle 输出；`fact_kind` 和 provenance 无丢失或提升。
3. dry-run 零持久化，cache hit 不调用 provider，延迟写回不重复模型调用，persistent cache 只在授权写回后提交。
4. blocking 冲突、stale-only、candidate-only formal claim 会正确限制 claim support 与 answerability。
5. 写回只允许已验证 observation/interpretation；candidate 不写边、不提升 formal；stale 只在新证据成功持久化后更新。
6. 01–04、QA、HTTP、MCP、导入、关系增强和候选审核兼容回归保持通过。
7. 单元/fake、live Neo4j、live DashScope、完整产品链路四类验证状态如实分开报告。

本计划不授权代码实施。开始实施前，应由用户评审本文件并选择 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 执行方式。

---

## 实施完成记录（2026-08-14）

Task 1-56 已全部实现并通过离线/fake 验证。

### 05 专项回归（Task 55）

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_fusion_models tests.test_assistant_recognition_projection tests.test_assistant_evidence_normalization tests.test_assistant_evidence_deduplication tests.test_assistant_evidence_rules tests.test_assistant_evidence_lineage tests.test_assistant_evidence_conflicts tests.test_assistant_claim_support tests.test_assistant_answerability tests.test_assistant_cache_closure tests.test_assistant_semantic_write_back tests.test_assistant_evidence_fusion tests.test_assistant_evidence_fusion_factory tests.test_assistant_evidence_fusion_boundaries tests.test_assistant_evidence_fusion_docs -v
```

结果：280 项运行，0 失败，0 错误，0 跳过（全部离线/合同/静态边界测试，不连接真实 Neo4j，不调用真实模型）。

### 完整离线回归（Task 56）

```powershell
$env:PYTHONPATH='src'; python -m unittest discover tests -v
```

结果：2150 项运行，0 失败，0 错误，4 项跳过（跳过原因为缺少 live Neo4j 测试环境变量 `NEO4J_TEST_URI`/`NEO4J_TEST_USER`/`NEO4J_TEST_PASSWORD`）。01–04、QA、HTTP、MCP、导入、关系增强和候选审核兼容回归无新增失败。

### live 验证状态（如实记录）

- live Neo4j：未验证（集成测试因缺少测试环境变量而 skipped，skipped 不等于 live Neo4j 通过）。
- live DashScope：未验证（本层不重复证明 04 模型质量，且未执行 live DashScope）。
- 黄金集：未验证。
- 完整 `DrawingAssistantService -> 06/07` 产品链路：未验证（06 答案生成、07 追溯反馈仍未实现）。

以上均为离线/fake 验证结论；未把 fake、单元、HTTP health、MCP smoke 或 skipped 集成测试报告为 live 验证通过。
