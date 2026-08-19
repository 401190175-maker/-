# 证据融合与缓存闭环 Design

**文档状态：** 技术方案，已实施  
**日期：** 2026-08-13  
**适用范围：** 产品实现层 05 证据融合与缓存闭环  
**设计依据：** 本目录 `proposal.md`、`Feature_Analysis_Report.md`，产品实现层 00–07 文档，以及当前 `architecture.md`、`Module.md` 和已落地的 01–04 代码边界。

## 0. 设计原则与关键决策

本设计采用 proposal 推荐的“独立、确定性 EvidenceFusionService”方案，保持同步、规则驱动和默认只读。关键决策如下：

1. **复用现有公共证据合同。** `assistant_models.EvidenceItem` 继续作为原始统一证据，不新建另一个同名 DTO；融合期新增 `FusionEvidence` 包装 `EvidenceItem` 和强类型融合元数据，避免把大量 05 专用字段硬塞入已被 01–04 使用的公共 DTO。
2. **复用 03 的事实等级、scope、状态和 freshness 规则。** 05 在加入本次识别结果后重新评估支撑情况，但不复制第二套事实等级或 freshness 算法。
3. **复用 04 的识别、校验、run/attempt、payload 和持久化能力。** 05 不调用供应商、不解析原始 provider 响应、不直接接触 repository。
4. **产品链路采用延迟写回。** 04 先以 `write_back=false` 产生已校验的临时结果和可持久化材料，05 完成冲突与授权门控后，才通过窄的 `ControlledSemanticWritePort` 委托既有 semantic service 持久化；不为写回重新调用模型。
5. **保留现有非产品入口兼容性。** `DrawingGraphToolFacade.recognize_semantic_targets(write_back=true)` 仍可用于已有显式工具流程，但其持久化尾部应复用同一个受控写回组件，避免形成两套保存规则。
6. **区分精确缓存键与证据家族键。** `cache_key` 继续表示特定输入和版本的精确复用；新增 `evidence_family_key` 只用于 lineage、supersede 和 stale 范围，不替代 cache key。
7. **冲突不被“解决掉”。** 冲突矩阵决定证据能否支撑当前 claim，但不删除、覆盖或提升任何输入证据。
8. **不做无意义重构。** 不移动现有模块、不改造 QA/HTTP/MCP/CLI、不引入通用工作流框架、事件平台、消息队列、OCR 或新的 repository 总接口。

## 1. 系统架构变化

### 1.1 当前产品链路

当前已落地链路为：

```text
AssistantRequest
  -> QuestionUnderstandingService
  -> QuestionUnderstandingResult
  -> GraphRetrievalService
  -> RetrievalBundle
  -> SemanticGapDecisionService
  -> SemanticGapDecision
  -> [按需] DrawingGraphToolFacade.recognize_semantic_targets(...)
  -> SemanticRecognitionService
  -> SemanticRecognitionResult
```

当前 `RetrievalBundle` 与 `SemanticRecognitionResult` 仍是两类独立结果。后续 06 没有一个统一、冲突可见、claim-aware 的输入。

### 1.2 目标链路

新增 05 后，产品内部链路变为：

```text
AssistantRequest
QuestionUnderstandingResult
RetrievalBundle
SemanticGapDecision
SemanticRecognitionResult[]
WriteBackPolicy
  -> EvidenceFusionService.fuse(EvidenceFusionRequest)
       -> RecognitionEvidenceProjector
       -> EvidenceNormalizer
       -> EvidenceDeduplicator
       -> EvidenceLineageResolver
       -> EvidenceConflictDetector
       -> ClaimSupportEvaluator
       -> AnswerabilityEvaluator
       -> CacheClosureEvaluator
       -> [可选] ControlledSemanticWritePort.persist(...)
  -> EvidenceBundle
  -> 后续 AnswerGenerationService
```

`EvidenceFusionRequest` 必须显式携带 `AssistantRequest` 和 `QuestionUnderstandingResult`：前者是 `allow_write_back` 的授权来源，后者提供完整 `EvidenceRequirement`。不能仅凭 `SemanticGapDecision.write_back_recommendation`、`missing_requirements` 或 `RetrievalBundle` 反推授权、required/optional、minimum status、freshness 和生成许可。

### 1.3 依赖方向

```text
assistant_evidence_fusion.py
  -> assistant_evidence_fusion_models.py
  -> assistant_models.py
  -> assistant_recognition_projection.py
  -> assistant_evidence_normalization.py
  -> assistant_evidence_deduplication.py
  -> assistant_evidence_lineage.py
  -> assistant_evidence_conflicts.py
  -> assistant_claim_support.py
  -> assistant_answerability.py
  -> assistant_cache_closure.py
  -> ControlledSemanticWritePort（可选）

ControlledSemanticWritePort adapter
  -> SemanticRecognitionService 的受控持久化组件
  -> run/attempt log + payload store + semantic repository + persistent cache
```

禁止依赖方向：

```text
EvidenceFusionService
  -X-> Neo4j driver / session / transaction / Cypher
  -X-> SemanticNeo4jRepository
  -X-> Qwen/DashScope client
  -X-> HTTP / MCP / CLI adapter
  -X-> CandidateReviewService.promote / RelationRepository.promote
```

### 1.4 03、04、05 的职责分离

| 阶段 | 权威职责 | 不负责 |
|---|---|---|
| 03 语义缺口决策 | 识别前充分性、freshness、预期 cache disposition、目标与预算 | 实际 cache hit、模型执行、识别后融合、写回 |
| 04 多模态识别 | 执行前实际 cache lookup、供应商调用、输出合同校验、语义 DTO 投影、可持久化材料构造 | claim 支撑、跨来源冲突、answerability、产品级写回授权 |
| 05 证据融合 | 融合、去重、lineage、冲突、claim 支撑、answerability、cache closure、写回门控 | 新查询、新识别、重试、答案文案、formal 提升 |

### 1.5 写回时序

产品链路固定采用：

```text
04 execute with write_back=false
  -> validated SemanticRecognitionResult
  -> SemanticWriteBatch（内存、未持久化）
05 fuse and authorize
  -> write_back=false: return skipped result，零持久化
  -> write_back=true: ControlledSemanticWritePort.persist(batch, lineage_plan)
       -> reuse existing run/attempt/payload/repository/cache components
```

已有工具入口若直接传 `write_back=true`，仍允许 04 完成后立即调用同一 persist 组件。这样保持接口兼容，同时让产品级 05 获得识别后门控能力。

### 1.6 不改变的架构

- `DrawingGraphQAService` 及六类只读 QA 保持不变。
- QA CLI、HTTP、STDIO MCP 仍是同级只读 adapter，不接入 05 写回。
- `DrawingGraphToolFacade` 仍是图谱和语义能力边界，不暴露 repository/Cypher。
- 基础导入、离线派生关系增强、断面匹配和候选审核流程保持原职责。
- `CandidateReviewService` 继续是候选复核与 formal 提升的唯一受控路径。
- `RecognitionRun`/`RecognitionAttempt` 继续位于图谱外。

## 2. 新增模块

### 2.1 融合合同：`assistant_evidence_fusion_models.py`

定义 05 专用枚举和不可变 DTO。该模块只依赖 `assistant_models.py`，不依赖数据库、模型客户端或 adapter。

建议枚举：

| 枚举 | 稳定值 |
|---|---|
| `Answerability` | `answerable`、`partially_answerable`、`clarification_required`、`unsupported` |
| `ClaimCapability` | `identity_and_location`、`confirmed_relation`、`rule_derived_context`、`observed_text_or_symbol`、`semantic_meaning`、`possible_relation`、`runtime_or_cache_status` |
| `ClaimSupportStatus` | `supported`、`supported_with_qualifier`、`conflicting`、`missing`、`stale_only`、`formal_review_required`、`unsupported` |
| `EvidenceComparison` | `consistent`、`complementary`、`conflicting`、`superseded`、`ambiguous`、`not_comparable` |
| `ConflictType` | `hard_conflict`、`rule_conflict`、`model_vs_source`、`semantic_vs_rule`、`peer_conflict`、`support_conflict`、`relation_conflict`、`formal_vs_semantic`、`critical_integrity_conflict`、`candidate_ambiguity`、`diagnostic_conflict` |
| `ConflictSeverity` | `info`、`warning`、`blocking`、`critical` |
| `CacheClosureStatus` | `full_hit`、`partial_hit`、`miss`、`stale`、`bypassed`、`mixed`、`unknown` |
| `WriteBackStatus` | `not_requested`、`skipped`、`persisted`、`partial`、`failed` |
| `WriteBackItemStatus` | `persisted`、`skipped`、`failed` |

建议 DTO：

| DTO | 职责 |
|---|---|
| `FusionMetadata` | 保存规范化值、比较键、family key、cache key、fingerprint、能力、freshness 与版本 |
| `EvidenceProvenance` | 聚合 source call、run、attempt、payload、规则和原始 evidence refs |
| `FusionEvidence` | 包装原 `EvidenceItem`、`FusionMetadata` 和 provenance；不修改原 item |
| `ConflictRecord` | 记录冲突键、双方/多方证据、类型、严重度、阻断状态和原因码 |
| `ClaimSupportAssessment` | 按 requirement/claim capability 记录采用、拒绝、冲突证据与限定语 |
| `EvidenceLineage` | 记录 family、current evidence、superseded evidence 和 stale 原因 |
| `CacheTargetSummary` | 逐目标记录 expected/actual cache 状态、run、证据和持久化状态 |
| `CacheSummary` | 请求级 cache closure 状态和逐目标摘要 |
| `SemanticWriteBatch` | 04 已验证、可持久化但尚未写入的 run/attempt/payload/语义 DTO |
| `WriteBackPolicy` | 集中表达请求、模块、环境、证据类型和冲突门控 |
| `WriteBackItemResult` | 单条/单组持久化结果和原因码 |
| `WriteBackResult` | 总体写回状态、逐项结果、stale/supersede 和 warning |
| `EvidenceFusionRequest` | 融合唯一输入容器 |
| `EvidenceBundle` | 05 唯一输出，供 06/07 消费 |

### 2.2 识别结果投影：`assistant_recognition_projection.py`

`RecognitionEvidenceProjector.project()` 将 `SemanticRecognitionResult` 映射为 `EvidenceItem`：

- `TextObservation` -> `semantic_observation`；
- 三类 `Interpretation` -> `semantic_interpretation`；
- `RecognitionCandidateEvidence` -> `candidate_relation`；
- summary、usage、cost、latency、attempt 状态、safe error、persisted -> `diagnostic`；
- 不产生 `source_fact`、`derived_relation` 或 `formal_relation`。

投影器使用 `RecognitionTarget`/`SemanticTargetInput` 映射恢复稳定 page/element scope。目标无法对应时，隔离该输出并产生 `recognition_scope_mismatch` diagnostic，不能猜测归属。

### 2.3 规范化：`assistant_evidence_normalization.py`

该模块包含：

- `EvidenceNormalizer`：将 `EvidenceItem` 变为 `FusionEvidence`；
- `NormalizationRuleRegistry`：按 `fact_kind + task_type + value slot` 路由规则；
- `ClaimCapabilityRegistry`：从可信 schema 字段和关系类型推导 capability；
- `ComparisonKeyBuilder`：生成 scope + predicate/slot + qualifiers；
- `EvidenceFamilyKeyBuilder`：生成 target + task + output slot + normalization scope；
- `ContentFingerprintBuilder`：生成稳定去重指纹。

规则要求：

- 原 `EvidenceItem.value` 不变；
- 关系规范化为有方向的 subject/predicate/object；
- bbox 使用统一四坐标结构；
- 文本规范化保留原文和符号体系；
- 断面标签复用现有 `SectionLabelNormalizer`，不新增第二套断面规则；
- normalization version 写入 `FusionMetadata`。

### 2.4 去重：`assistant_evidence_deduplication.py`

`EvidenceDeduplicator.deduplicate()` 只合并以下全部相同的条目：

```text
fact_kind
comparison_key
normalized_value
content_fingerprint
```

不同 fact kind、不同关系方向、不同 scope 或不同规范化槽不合并。合并后保留所有原 evidence IDs 和 provenance。canonical evidence 按稳定规则选择：优先已有持久化稳定 ID，其次按 `created_at_or_version`，最后按 evidence ID 字典序；该选择只影响展示，不改变事实等级。

### 2.5 Lineage 与 stale：`assistant_evidence_lineage.py`

`EvidenceLineageResolver.resolve()` 按 `evidence_family_key` 比较同族证据，输出 `EvidenceLineage` 和待写回的 `LineagePlan`。

核心规则：

- cache key 相同且内容相同：重复/复用，不产生 supersede；
- family 相同、cache key 不同且新证据通过当前 freshness：形成 supersede 候选；
- 只有本次新证据合同有效且写回成功时，旧证据才持久化标记 stale；
- 写回失败时只在本次 `EvidenceBundle` 中把旧证据视为不可用于 current claim，不修改持久状态；
- observation 与 interpretation 分别应用 `StalePolicyRegistry`；
- formal/source/derived/candidate/diagnostic 不由语义 lineage resolver 标 stale。

### 2.6 冲突检测：`assistant_evidence_conflicts.py`

`EvidenceConflictDetector.detect()` 只比较相同 `comparison_key` 或规则明确可比较的 evidence family，输出 `ConflictRecord`。

冲突矩阵：

| A / B | 处理 |
|---|---|
| source / source 同键不同值 | `hard_conflict`，blocking |
| source / derived | 通常 complementary；派生否定来源时 `rule_conflict` |
| source / observation 或 interpretation | `model_vs_source`；来源事实不被覆盖 |
| derived / derived 同规格同槽不同目标 | `rule_conflict` |
| derived / interpretation | `semantic_vs_rule`，warning 或 blocking 由 claim 决定 |
| observation / observation 同区域同任务不同文本 | `peer_conflict`，默认 ambiguous |
| observation / interpretation | interpretation 未引用支持 observation 时 `support_conflict` |
| interpretation / interpretation 同字段不同值 | `peer_conflict` |
| candidate / candidate 同候选组多目标 | `candidate_ambiguity`，不选 winner |
| candidate / formal | formal 可支撑当前正式状态；candidate 保留历史，不被删除 |
| formal / semantic | `formal_vs_semantic`；建议复核，不撤销 formal |
| formal / formal 互斥槽多值 | `critical_integrity_conflict`，critical/blocking |
| diagnostic / diagnostic 同 run 状态矛盾 | `diagnostic_conflict` |
| 不同 scope/slot | `not_comparable`，不产生冲突 |

置信度只能作为 conflict 诊断字段，不单独决定 winner。

### 2.7 Claim 支撑：`assistant_claim_support.py`

`ClaimSupportEvaluator.evaluate()` 消费完整 `EvidenceRequirement`、融合证据、冲突和 03 assessment，输出逐需求 `ClaimSupportAssessment`。

能力矩阵：

| Claim capability | 可直接支撑 | 仅限定性支撑 | 禁止支撑 |
|---|---|---|---|
| identity/location | source fact | 无 | semantic/candidate/diagnostic |
| confirmed relation | formal relation；规格明确的 derived relation | 无 | candidate/semantic |
| rule-derived context | derived relation | 无 | interpretation |
| observed text/symbol | current semantic observation | partial/low-confidence observation | interpretation/candidate |
| semantic meaning | current interpretation 且 observation 链完整 | partial/ambiguous interpretation | diagnostic |
| possible relation | candidate relation | 多候选/冲突 candidate | 不得表达 confirmed |
| runtime/cache status | diagnostic | 无 | 工程事实证据 |

评估顺序：scope -> capability -> minimum status -> freshness -> conflict -> formal gate -> qualifier。03 的 `EvidenceSufficiencyEvaluator` 中可共享的纯规则应抽取为小型 helper；不得让 03 依赖整个 05。

### 2.8 Answerability：`assistant_answerability.py`

`AnswerabilityEvaluator.evaluate()` 先对每个 subrequest 聚合 required/optional assessment，再聚合 request：

1. scope 缺失/冲突/指代不唯一且无法继续 -> `clarification_required`；
2. 问题或 capability 不支持 -> `unsupported`；
3. 所有 required 均 supported 或允许的 supported_with_qualifier，且无 blocking conflict -> `answerable`；
4. 至少一个 required 可回答，但存在 missing、stale-only、识别失败、deferred target 或非全局阻断冲突 -> `partially_answerable`；
5. required formal claim 只有 candidate -> `formal_review_required`，整体至多 partially answerable；
6. required current claim 只有 stale -> 不得 answerable。

多 subrequest 聚合：全部 answerable 才是 answerable；存在 clarification 时优先 clarification；全部 unsupported 才是 unsupported；其他混合状态为 partially answerable。

### 2.9 缓存闭环：`assistant_cache_closure.py`

`CacheClosureEvaluator.evaluate()` 合并：

- 03 `CacheCandidate` 的 expected disposition；
- 04 每目标实际 `CacheOutcome`；
- 本次 run/attempt 是否发生；
- 新旧 evidence IDs 与 lineage；
- persistent cache 是否实际提交；
- write-back 是否成功。

总体状态不是简单覆盖：目标全命中为 full hit；部分命中为 partial hit；全 bypass 为 bypassed；存在多种处置为 mixed；元数据不足为 unknown。只有 `persistent_cache_committed=true` 才可报告跨请求缓存已经建立。

### 2.10 受控写回：`assistant_semantic_write_back.py`

定义 `ControlledSemanticWritePort` 协议和 `SemanticServiceWriteAdapter`。

门控条件为逻辑与：

```text
request_allow_write_back
AND module_allow_write_back
AND environment_allow_write_back
AND batch_schema_valid
AND target_scope_valid
AND persistence_dependencies_available
AND evidence_kind_allowed
AND payload_sanitized
AND audit_material_complete
AND no_blocking_conflict
```

adapter 只接收 `SemanticWriteBatch + LineagePlan`。其实现复用现有 run/attempt log、payload store、semantic repository 和 persistent cache，不重新调用 recognition client。candidate evidence 只允许保留在图谱外 payload/审计中，不直接写边。

### 2.11 编排服务：`assistant_evidence_fusion.py`

`EvidenceFusionService.fuse()` 是 05 唯一入口，固定顺序：

```text
1. validate request/subrequest correlation
2. collect RetrievalBundle EvidenceItem
3. project RecognitionResult into EvidenceItem
4. normalize and derive capabilities/keys
5. deduplicate while preserving provenance
6. reuse freshness rules and resolve lineage
7. detect conflicts
8. evaluate claim support
9. derive answerability
10. build pre-write cache summary
11. evaluate and optionally execute controlled write-back
12. finalize cache summary and EvidenceBundle
```

所有输出使用稳定排序：subrequest order、requirement order、comparison key、fact kind、evidence ID。

### 2.12 工厂：`assistant_evidence_fusion_factory.py`

提供：

```text
create_evidence_fusion_service(
    controlled_write_port=None,
    normalization_registry=None,
    capability_registry=None,
    stale_policy_registry=None,
) -> EvidenceFusionService
```

默认工厂创建纯融合服务，`controlled_write_port=None`，因此即使 policy 请求写回也只能返回 `persistence_unavailable`/skipped，不连接数据库或模型。真实 port 由产品 runtime 在最外层注入。

## 3. 修改模块

### 3.1 `assistant_models.py`

最小修改：

- 为 `ReasonCode` 增加 05 使用的稳定原因码；
- 不删除、不重命名现有 DTO/枚举；
- `EvidenceItem` 保持现有构造方式兼容，不强制增加新必填字段；
- 如需要，将通用的 `cache_key`/版本值继续放在稳定 `evidence_metadata` 中，由 `FusionMetadata` 强类型化。

不把全部 05 DTO 放入该文件，避免公共合同继续膨胀。

### 3.2 `assistant_retrieval_projection.py`

最小补充已持久化证据的稳定 metadata：

```text
task_type
cache_key
image_hash
model_profile / model_version
prompt_version
input/output contract version
preprocessing_version
normalization_rule_version
created_at
candidate_group_id / relation_type / direction（关系适用）
```

projection 不生成 comparison key、不判冲突、不算 answerability。

### 3.3 `assistant_evidence_sufficiency.py`

将 scope matching、fact-kind gate、status gate、formal gate 等可复用规则提取为同文件或小型 `assistant_evidence_rules.py` 纯 helper。03 原入口和行为保持兼容；05 只依赖 helper，不调用完整 `SemanticGapDecisionService` 重跑识别决策。

### 3.4 `assistant_evidence_freshness.py`

保留为 freshness 权威实现。新增按任意证据集合评估的窄 helper，或让 05 构造临时 `RetrievalBundle` 复用现有 evaluator。优先窄 helper，避免为适配而伪造 bundle。现有 03 API 不变。

### 3.5 `semantic_models.py`

兼容性增加：

- `TextObservation` 可增加可选 `evidence_family_key`、`normalization_rule_version`；
- 三类 interpretation 可增加可选 `evidence_family_key`、`supersedes_evidence_ids`；
- `ObservationStatus` 增加 `stale`，但仅在 stale policy 明确要求且受控写回成功时使用；
- 所有新字段有默认值，现有构造方式不破坏。

不改变 `interpreted_type` 的语义，不写入 `DrawingBlock.block_type`。

### 3.6 `recognition_models.py` / `semantic_service.py`

添加性修改：

- `SemanticRecognitionResult` 增加 `cache_outcomes` 和可选 `write_batch`；
- `CacheOutcome` 逐目标表达 hit/miss/bypassed、cache key、evidence IDs、provider_called；
- 04 投影成功后构造 `SemanticWriteBatch`，但 dry-run 不持久化；
- 04 在执行开始时生成与持久化无关的稳定 `recognition_run_id`；dry-run 时该 ID 只存在于返回对象、不可通过 run log 查询，延迟写回时沿用同一 ID，禁止静默换 ID；
- 将现有 write-back 尾部提取为可复用 `persist_validated_batch()`；
- 原 `write_back=true` 路径调用该 helper，保持现有 facade 行为；
- 05 adapter 也调用同一 helper，不重复供应商调用。

缓存语义调整：

- persistent cache 的 `put` 只能在写回授权通过时执行；
- dry-run 仅允许写请求内 `RequestSemanticMemo`，不得写跨请求 backend；
- persistent cache 仍可只读 lookup；
- 现有 `SemanticCacheService.get/put` 保持兼容，factory 显式区分 persistent cache 与 request memo。

这是修复 dry-run 副作用边界所必需的定向调整，不扩展为通用缓存框架。

### 3.7 `semantic_cache.py`

继续保留 `SemanticCacheKeyInput` 和 `build_semantic_cache_key()` 为唯一精确 key 算法。新增独立：

```text
EvidenceFamilyKeyInput
build_evidence_family_key(...)
RequestSemanticMemo
```

family key 不含 image/model/prompt/contract 等会变化的精确版本维度，只包含稳定 target、task、output slot 和 normalization scope。它不能用于缓存命中。

### 3.8 `semantic_repository.py` / `semantic_neo4j_repository.py`

在现有 `SemanticEvidenceRepositoryPort` 增加窄方法或新增专用 `SemanticEvidenceLineageWritePort`：

```text
mark_evidence_stale(
    evidence_ids,
    *,
    superseded_by_evidence_id,
    stale_reason,
    stale_at,
    evidence_family_key,
) -> tuple[str, ...]
```

Neo4j 实现只允许更新图谱内 semantic observation/interpretation 的受控属性。不得匹配来源事实、派生关系、candidate/formal 关系。当前按相同 `cache_key` 标记 interpretation stale 的逻辑应迁移为调用 family-aware helper，避免两套 stale 规则并存。

### 3.9 `semantic_query_projection.py` / Tool DTO

只读投影补充：

```text
evidence_family_key
superseded_by_evidence_id
supersedes_evidence_ids
stale_reason
stale_at
normalization_rule_version
```

不暴露 Neo4j 内部 ID，不把 lineage 属性解释为 formal relation。

### 3.10 `recognition_run_log.py` / attempt log

- `RecognitionRunLogPort.create_run()` 增加可选 `recognition_run_id`，不传时保持现有自动生成行为；
- 延迟写回必须使用 `SemanticWriteBatch.recognition_run_id`，若相同 ID 已存在且摘要不一致则拒绝，不能覆盖；
- attempt ID 和 observation/interpretation 的 `recognition_run_id` 在执行后不可重绑定；
- dry-run 不调用 run/attempt log，因此稳定 ID 不等于已经持久化或可查询。

### 3.11 `tool_facade.py` / `tool_factory.py`

- 现有识别入口签名保持兼容；
- factory 注入 persistent cache、request memo factory 和复用的 persist component；
- 产品 runtime 可在 facade 外侧装配 `EvidenceFusionService`，但 facade 不依赖 05；
- 不在本阶段新增外部产品 API。

### 3.12 文档与测试

实施后同步直接相关 `architecture.md`、`Module.md` 和本 change 文档。新增 05 专项测试，但不修改无关导入/增强/QA 测试结构。

## 4. 数据模型变化

### 4.1 Neo4j 业务模型

不新增业务节点标签、业务关系类型、来源事实约束或索引。继续复用：

- `TextObservation`；
- `BlockInterpretation`；
- `BasicInfoInterpretation`；
- `TableInterpretation`；
- `HAS_OBSERVATION`；
- `HAS_INTERPRETATION`；
- `SUPPORTED_BY`。

`EvidenceBundle`、`ConflictRecord`、`ClaimSupportAssessment`、`RecognitionRun`、`RecognitionAttempt` 不作为 Neo4j 业务节点。

### 4.2 图谱内语义证据属性

建议增加可选属性：

```text
evidence_family_key
normalization_rule_version
superseded_by_evidence_id
stale_reason
stale_at
```

新 evidence 可通过 payload/DTO 的 `supersedes_evidence_ids` 记录它取代的旧 evidence；旧节点使用单值 `superseded_by_evidence_id` 指向当前直接后继。完整多跳历史通过逐节点链回放，不把数组无限增长写入单节点。

首阶段不要求为这些属性新增索引。若 live 数据证明 family lookup 成为瓶颈，再单独评估索引；不能仅为“可能有用”修改 schema。

### 4.3 `FusionEvidence`

```text
FusionEvidence
  item: EvidenceItem
  metadata: FusionMetadata
  provenance: EvidenceProvenance[]
  original_evidence_ids[]
```

`FusionMetadata`：

```text
normalized_value
comparison_key
evidence_family_key
content_fingerprint
claim_capabilities[]
cache_key
task_type
freshness_result
normalization_rule_version
is_current_for_request
```

`FusionEvidence` 是请求期产品 DTO，不默认持久化。

### 4.4 `ConflictRecord`

```text
conflict_id
comparison_key
conflict_type
severity
evidence_ids[]
preferred_for_current_claim_ids[]
blocks_answer
reason_codes[]
review_recommended
```

`preferred_for_current_claim_ids` 仅表示某 claim 当前采用哪类权威证据，不表示删除、撤销或提升其他证据。

### 4.5 `ClaimSupportAssessment`

```text
requirement_id
subrequest_id
claim_capability
status
supporting_evidence_ids[]
qualifying_evidence_ids[]
rejected_evidence_ids[]
conflict_ids[]
qualifiers[]
confidence
confidence_basis
reason_codes[]
```

置信度规则：确定性 source/formal/derived 可使用 `confidence_basis=deterministic` 且数值为 `None`；模型证据保留原置信度。多个互补证据的 claim confidence 取可量化必需证据的最小值；冗余一致证据不简单相加。整体 confidence 取 required claim 中可量化值的最小值；任何 required claim 无法可靠量化时可以为 `None`，不伪造数字。

### 4.6 `CacheSummary`

```text
status
targets[]
persistent_cache_committed
request_memo_used
new_recognition_run_ids[]
reason_codes[]
warnings[]
```

逐目标 `CacheTargetSummary`：

```text
target_id
expected_cache_key
expected_disposition
actual_cache_key
actual_disposition
reused_evidence_ids[]
new_evidence_ids[]
recognition_run_id
provider_called
persisted
```

### 4.7 `WriteBackPolicy` 与 `WriteBackResult`

`WriteBackPolicy`：

```text
request_allow_write_back
module_allow_write_back
environment_allow_write_back
allowed_fact_kinds[]
require_valid_scope
require_sanitized_payload
require_audit_material
block_on_conflict_severities[]
allow_persistent_cache
```

`WriteBackResult`：

```text
status
items[]
persisted_evidence_ids[]
stale_evidence_ids[]
supersede_links[]
payload_refs[]
recognition_run_ids[]
persistent_cache_committed
reason_codes[]
warnings[]
```

### 4.8 `EvidenceBundle`

```text
request_id
subrequest_id
accepted_evidence[]
conflicting_evidence[]
conflicts[]
claim_support[]
unsupported_claims[]
lineage[]
cache_summary
provenance[]
overall_confidence
answerability
reason_codes[]
warnings[]
write_back_result
contract_version
```

`accepted_evidence` 仅表示可用于当前回答，不等于已持久化或已成为正式事实。

## 5. API 设计

### 5.1 唯一融合入口

```text
EvidenceFusionService.fuse(
    request: EvidenceFusionRequest,
) -> EvidenceBundle
```

`EvidenceFusionRequest`：

```text
assistant_request: AssistantRequest
question_result: QuestionUnderstandingResult
retrieval_bundle: RetrievalBundle
semantic_gap_decision: SemanticGapDecision
recognition_results: tuple[SemanticRecognitionResult, ...]
write_back_policy: WriteBackPolicy
```

输入校验：

- `AssistantRequest`、`QuestionUnderstandingResult`、`RetrievalBundle` 和 `SemanticGapDecision` 的 `request_id` 必须一致；
- subrequest ID 必须一致或能通过 `QuestionUnderstandingResult.subrequests` 唯一映射；
- recognition result 的 page/target 必须属于当前 scope 和 selected targets；
- 同一 recognition run ID 不得携带互相矛盾的状态；
- `write_back_policy.request_allow_write_back` 必须等于 `assistant_request.allow_write_back` 的显式值；policy 只能进一步收紧，不能从问题文本、模型结果或 recommendation 放宽授权；
- tuple、枚举、ID、bbox、置信度和版本字段必须通过 DTO 校验。

### 5.2 投影与规范化 API

```text
RecognitionEvidenceProjector.project(
    result: SemanticRecognitionResult,
    targets: tuple[RecognitionTarget, ...],
) -> ProjectionResult

EvidenceNormalizer.normalize(
    evidence: tuple[EvidenceItem, ...],
    context: FusionNormalizationContext,
) -> tuple[FusionEvidence, ...]

EvidenceDeduplicator.deduplicate(
    evidence: tuple[FusionEvidence, ...],
) -> DeduplicationResult
```

`ProjectionResult` 必须区分 projected evidence、diagnostics 和 rejected outputs；单条非法结果不一定使整个请求失败。

### 5.3 Lineage、冲突与支撑 API

```text
EvidenceLineageResolver.resolve(
    evidence: tuple[FusionEvidence, ...],
    freshness_requirements: Mapping[str, FreshnessRequirement],
) -> LineageResult

EvidenceConflictDetector.detect(
    evidence: tuple[FusionEvidence, ...],
) -> tuple[ConflictRecord, ...]

ClaimSupportEvaluator.evaluate(
    requirements: tuple[EvidenceRequirement, ...],
    evidence: tuple[FusionEvidence, ...],
    conflicts: tuple[ConflictRecord, ...],
    prior_assessments: tuple[RequirementAssessment, ...],
) -> tuple[ClaimSupportAssessment, ...]

AnswerabilityEvaluator.evaluate(
    question_result: QuestionUnderstandingResult,
    assessments: tuple[ClaimSupportAssessment, ...],
    conflicts: tuple[ConflictRecord, ...],
    decision: SemanticGapDecision,
) -> AnswerabilityResult
```

### 5.4 缓存闭环 API

```text
CacheClosureEvaluator.evaluate(
    expected: tuple[CacheCandidate, ...],
    actual: tuple[CacheOutcome, ...],
    lineage: LineageResult,
    write_back_result: WriteBackResult | None,
) -> CacheSummary
```

05 不调用 cache `get()` 或 `put()`；实际 lookup 由 04 完成，实际 persistent commit 由受控写回 adapter 完成。05 只做一致性汇总和状态判断。

### 5.5 受控写回 API

```text
ControlledSemanticWritePort.persist(
    batch: SemanticWriteBatch,
    lineage_plan: LineagePlan,
    policy: WriteBackPolicy,
) -> WriteBackResult
```

`SemanticWriteBatch` 只能由 04 合同校验后的投影过程构造，包含：

```text
recognition_run
attempts[]
sanitized_payload_envelope
observations[]
interpretations[]
candidate_evidence[]（audit only）
cache_entries[]
schema_valid
scope_valid
payload_sanitized
audit_material_complete
```

port 不接受任意 dict、Cypher、Label、关系类型或本地路径。

### 5.6 04 兼容 API

现有 API 保持：

```text
DrawingGraphToolFacade.recognize_semantic_targets(
    targets,
    model_profile="default",
    prompt_version="default",
    contract_version="1",
    write_back=False,
    execution_policy=None,
) -> SemanticRecognitionResult
```

只增加有默认值的 `cache_outcomes`/`write_batch` 返回字段，不删除现有字段。已有 `write_back=true` 调用仍工作，但内部委托相同 persist component。

稳定 ID 约定：04 每次真实执行在调用 provider 前生成一个稳定 `recognition_run_id` 并贯穿 attempt、observation、interpretation、payload envelope 和 `SemanticWriteBatch`。是否调用 run log 只决定该 ID 是否可跨请求查询，不改变 ID 本身。纯 cache hit 不创建真实执行 run；兼容返回所需的临时 envelope ID不得进入 `new_recognition_run_ids` 或持久化审计。

### 5.7 不新增外部 API

本阶段不新增 HTTP route、MCP tool、CLI subcommand 或 Web API。后续完整 `DrawingAssistantService` 只能消费 `EvidenceFusionService` 内部 API，不得让 adapter 重做融合逻辑。

### 5.8 稳定排序与幂等

- conflict ID 由 comparison key、conflict type 和排序后的 evidence IDs 生成；
- content fingerprint、family key、cache key 都使用规范 JSON 和版本化 hash；
- write batch 使用 recognition run ID + evidence IDs 作为幂等边界；
- 同一 batch 重放不得创建重复语义节点、重复 payload 或重复 stale 变更；
- 输出不得依赖 dict/set 的偶然迭代顺序。

## 6. 异常处理

### 6.1 异常分类

| 异常/错误码 | 场景 | 处理 |
|---|---|---|
| `FusionInputError` / `fusion_input_invalid` | request ID、subrequest、类型或范围不一致 | 拒绝本次融合；返回/抛出稳定输入错误，不执行写回 |
| `EvidenceProjectionError` / `evidence_projection_failed` | 单条 04 输出无法安全投影 | 隔离该输出，生成 diagnostic；required 证据受影响时 partial/unsupported |
| `EvidenceNormalizationError` / `evidence_normalization_failed` | 未知 schema slot、非法关系方向、不可规范化值 | 隔离该证据并保留原 ID；不猜测 normalized value |
| `EvidenceConflictPolicyError` / `conflict_policy_invalid` | 冲突矩阵或 registry 配置不完整 | fail closed；不执行 claim 支撑或写回 |
| `ClaimSupportError` / `claim_support_failed` | requirement 无法映射 capability | 标记 unsupported，不让通用 fallback 提升证据 |
| `CacheClosureError` / `cache_closure_inconsistent` | expected/actual target 无法对应 | cache status unknown + warning；不伪报 hit |
| `WriteBackDenied` / `write_back_denied` | 任一授权门控为 false | 正常 skipped 结果，不视为系统异常 |
| `WriteBackUnavailable` / `persistence_unavailable` | port 或依赖未配置 | 临时证据继续用于本次回答，写回 skipped/failed |
| `WriteBackPartialError` / `write_back_partial` | 多后端部分成功 | 返回 partial，列出每一步实际状态，不回滚或伪造原子成功 |
| `LineageWriteError` / `lineage_write_failed` | 新证据写入成功但 stale 标记失败 | 返回 partial；新证据保留，旧证据不声称已 stale |
| `InternalFusionError` / `internal_error` | 未分类错误 | 脱敏、fail closed、无写回；不返回 traceback |

### 6.2 Fatal 与可降级边界

Fatal：请求关联不一致、registry 配置不完整、事实等级越权、输入结构损坏。Fatal 时不执行任何持久化。

可降级：单条可选证据投影失败、optional requirement 缺失、cache 元数据未知、写回不可用。可降级场景保留已成功证据并通过 warning/partial 表达。

### 6.3 冲突不是异常

合法证据之间的差异由 `ConflictRecord` 表达，不抛系统异常。只有冲突策略配置本身非法才是异常。blocking/critical 冲突影响 claim support 和 answerability，并默认阻止相关语义写回。

### 6.4 写回状态机

```text
not_requested
  -> WriteBackResult(not_requested)

requested
  -> policy gate failed -> skipped
  -> validate batch
       -> invalid -> skipped/failed, no writes
       -> valid -> persist run/attempt/payload
            -> persist semantic evidence
            -> mark lineage stale
            -> commit persistent cache
            -> complete run
```

每一步都记录 item result。后一步失败不伪造前一步未发生；不自动删除已经写入的 append-only 审计。重试依赖幂等 ID，在更高层显式触发，不由 05 无限重试。

### 6.5 部分成功语义

- 临时融合成功、写回失败：`EvidenceBundle` 仍可 answerable/partial，`write_back_result=failed/partial`；
- payload 成功、语义节点失败：保留 payload/run 审计，persisted evidence 为空；
- 语义节点成功、stale 失败：新证据可持久化，但旧证据仍按原状态查询；cache summary 不报告 closure 完成；
- persistent cache 失败：证据可已持久化，但 `persistent_cache_committed=false`；
- candidate evidence 永不因其他步骤成功而写成 formal edge。

### 6.6 错误脱敏

对外只返回稳定 code、阶段、request/run/evidence ID 和安全摘要。禁止包含：

- Neo4j URI、Cypher、Label 内部拼接、driver/session 类型；
- API key、Authorization、cookie、环境变量值；
- 绝对图片路径、Base64、完整 payload、完整 prompt；
- provider 原始错误正文或 Python traceback。

## 7. 安全方案

### 7.1 默认只读与双重授权

- `AssistantRequest.allow_write_back` 默认 false；
- `WriteBackPolicy` 必须显式携带 request/module/environment 三层授权；
- 任一 false 即 skipped；
- `SemanticGapDecision.write_back_recommendation` 不能提升授权；
- QA/HTTP/MCP 现有入口继续固定只读。

### 7.2 事实等级不可提升

- `FusionEvidence.item.fact_kind` 在规范化、去重、冲突和 claim 支撑中只读；
- projector 只按来源 DTO 的可信类型映射，不解析自由文本中的 `fact_kind`；
- candidate relation 只能支撑 possible relation；
- formal relation 只能来自既有正式查询投影；
- 05 不调用 `CandidateReviewService` 或 relation promotion；
- 模型输出、用户确认、置信度和 write-back 授权都不能把 candidate 变 formal。

### 7.3 输入与 scope 安全

- 只接受稳定业务 ID，不接受 Neo4j 内部 ID、Cypher 或任意查询表达式；
- recognition target 必须属于当前 question/retrieval scope；
- bbox 必须与可信 source fact 一致；
- 跨页或额外 target 输出隔离为 scope mismatch；
- 图内文字、模型文本和 payload 均视为数据，不执行其中的命令、代码或查询。

### 7.4 写回最小权限

- `ControlledSemanticWritePort` 只接受强类型 `SemanticWriteBatch`；
- 允许的图谱内类型仅 `TextObservation` 和三类 interpretation；
- candidate evidence 只进入图谱外审计，不直接写关系；
- lineage port 只能更新受控语义节点的 stale 属性；
- 不允许覆盖来源节点、修改 `DrawingBlock.block_type`、删除历史证据或修改正式关系；
- repository、driver 和 secret 只存在于最外层 runtime/adapter。

### 7.5 缓存隔离

- persistent cache lookup 可在 dry-run 使用，但 persistent put 必须经过写回门控；
- request-local memo 随请求生命周期销毁，不进入跨请求 backend；
- cache key 不包含 secret、绝对路径或原始 payload；
- family key 不能用于缓存命中，避免错误复用；
- cache hit 必须返回实际 evidence IDs，不能仅凭 key 存在就视为有效。

### 7.6 冲突与 stale 安全

- blocking/critical 冲突默认阻止相关证据写回；
- formal 与 semantic 冲突不自动撤销 formal；
- stale 标记必须限定同一 evidence family、允许的 evidence kind 和明确 superseding evidence；
- 新结果未成功持久化时不得把旧结果持久化标 stale；
- payload 不可变，修订生成新 payload_ref。

### 7.7 数据最小化与隐私

- `EvidenceBundle` 默认只携带摘要和 `payload_ref`，不复制大 payload；
- provenance 只保留当前 claim 所需稳定引用；
- 不保存图像、crop、Base64、完整 prompt 或 provider response；
- 绝对路径由 adapter 数据最小化策略控制；
- run/attempt/payload 写入前继续复用 04 redactor。

### 7.8 资源与拒绝服务保护

- 输入 evidence、conflict group、provenance 和 recognition result 数量有策略上限；
- 超限时稳定截断并 warning，required evidence 被截断时 answerability 不得为 answerable；
- 规范化和冲突比较按 comparison key 分组，禁止无界全量笛卡尔积；
- payload 不在 05 默认展开；
- 写回 batch 有最大证据数、payload 大小和 attempt 数限制。

### 7.9 静态依赖保护

新增边界测试禁止 05 纯模块导入：

```text
neo4j
semantic_neo4j_repository
relation_repository
candidate_review
qwen_semantic_client
qa_http / qa_mcp / CLI scripts
```

只有 `assistant_semantic_write_back.py` 的 adapter 可以依赖受控 semantic persistence application component，仍不得直接依赖 Neo4j/Cypher。

## 8. 测试与验证设计

### 8.1 纯合同与规则测试

- DTO 枚举、默认值、不可变性、序列化和非法输入；
- `EvidenceItem` 兼容构造回归；
- recognition result 到所有允许 fact kind 的投影；
- 规范化值不覆盖原始 value；
- comparison/family/cache key 职责分离；
- 去重保留全部 provenance；
- 完整冲突矩阵参数化测试；
- claim capability 和 formal gate 安全测试；
- subrequest/request answerability 聚合；
- 相同输入稳定排序和确定性 ID。

### 8.2 缓存与 lineage 测试

- full/partial/miss/stale/bypassed/mixed/unknown；
- cache hit 不调用 provider、不创建持久化 run/attempt；
- dry-run 不写 persistent cache；
- request memo 可复用但不跨请求；
- family 相同、cache key 变化时生成 supersede 计划；
- 写回成功后旧证据 stale；写回失败时旧证据不变；
- observation/interpretation 使用不同 stale policy；
- payload_ref 不可变。

### 8.3 写回测试

- request/module/environment 任一授权 false 均 skipped；
- schema/scope/payload/audit/conflict gate；
- 只允许 observation/interpretation；
- candidate 不写边、不提升 formal；
- run/attempt/payload/evidence/stale/cache 分步结果；
- 各步骤故障注入和 partial 状态；
- 相同 batch 幂等重放；
- 既有 facade `write_back=true` 回归仍调用同一 persist component。

### 8.4 兼容与边界测试

- 01–04 现有专项测试保持通过；
- `DrawingGraphQAService` 不导入 assistant fusion；
- QA CLI/HTTP/MCP 无新增写回；
- 静态扫描禁止 Neo4j/repository/Qwen/Cypher 进入纯融合模块；
- import/factory 无数据库、网络和文件扫描副作用。

### 8.5 Live 验证分层

- 纯单元/fake：证明融合合同、规则、缓存与写回编排；
- live Neo4j：只验证受控语义节点属性、stale/supersede、幂等和查询投影；
- live DashScope：属于 04，05 不重复证明模型质量；
- 完整产品链路：待 `DrawingAssistantService` 和 06 落地后单独验收；
- skipped 集成测试不得报告为 live Neo4j 通过。

## 9. 兼容性与禁止无意义重构

实施中明确禁止：

- 重命名、移动或合并现有 assistant、semantic、QA、HTTP、MCP、CLI、导入、增强模块；
- 将所有 port 合并成通用 `interfaces`/`repository` 大层；
- 为统一代码风格改写无关 DTO、Cypher、配置、日志或测试；
- 把融合逻辑塞入 `SemanticRecognitionService`、facade 或 adapter；
- 建设事件溯源平台、异步队列、工作流引擎、通用规则 DSL、OCR 或新的模型代理层；
- 改变 Neo4j 来源事实 schema、候选审核和正式关系提升规则；
- 将 05 设计成 LLM/Agent 自由裁决流程。

允许的最小改动仅包括：新增 05 纯模块；为现有 DTO 增加有默认值字段；提取 03 可共享纯规则；为 04 增加 cache outcome/write batch 和复用的 persist component；为语义证据增加 family/stale 属性和窄 lineage port；更新直接相关测试与文档。

## 10. 设计完成标准

本设计进入 `tasks.md` 拆分前必须满足：

1. 七个必需设计章节完整，新增和修改模块职责无重叠。
2. `EvidenceFusionRequest` 明确携带原始 `AssistantRequest` 和完整 evidence requirements，授权、request/subrequest 关联无隐式全局状态。
3. `EvidenceItem`、`FusionEvidence`、`EvidenceBundle`、冲突、claim 支撑、answerability、cache summary 和 write-back DTO 语义明确。
4. comparison key、evidence family key、cache key 和 content fingerprint 的用途互不混淆。
5. 03、04、05 的 freshness/cache/识别/融合职责清晰，不产生重复规则或二次模型调用。
6. dry-run、cache hit、stale、冲突、部分成功和写回失败行为无歧义。
7. 默认 `write_back=false`，受控写回不接触 repository/Cypher，不覆盖来源事实，不提升 candidate。
8. 不修改 Neo4j 业务 schema，不改变 QA/HTTP/MCP 兼容行为，不引入无意义重构。
9. 单元/fake、live Neo4j、live DashScope 和完整产品验证状态明确分层。

本文件经用户评审确认后，下一步才可使用 Superpowers `writing-plans` 将方案拆成单一能力、指定文件、独立测试和完成标准明确的 `tasks.md`。本设计本身不授权代码实施。
