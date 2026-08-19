# 证据融合与缓存闭环 Feature Analysis Report

**文档状态：** 需求分析与技术方案建议，已实施（Task 1-56 全部完成，离线/fake 验证通过）  
**日期：** 2026-08-13  
**需求范围：** `EvidenceItem`、证据规范化、冲突矩阵、`stale`、claim 支撑能力、`answerability`、受控语义写回  
**非本轮范围：** 不写代码，不修改现有架构文档，不实现答案生成、追溯反馈或外部产品 adapter

## 0. 分析依据与结论摘要

### 0.1 已读取材料

- 当前实现基线：`architecture.md`、`Module.md`。
- 产品闭环设计：`changes/产品实现层/00-product-closure-blueprint.md` 至 `07-traceability-and-feedback.md` 共八个文件。
- 为避免把规划误写成实现，本次还只读核对了相关现行源码接口：产品公共合同、检索投影、证据充分性/freshness、语义缓存、语义识别服务和语义 Neo4j repository。

### 0.2 总体结论

当前架构**支持新增该能力，但只具备底座，不具备完整闭环**。

已经可复用的基础包括：

- 产品公共合同中已有 `EvidenceItem`、`RetrievalBundle`、`Claim`、`AnswerPackage`、`FactKind`、`CacheDisposition`、`RequirementAssessment` 等 DTO/枚举。
- `RetrievalBundleBuilder` 已能把 facade 查询结果按 `source_fact`、`derived_relation`、`semantic_observation`、`semantic_interpretation`、`candidate_relation`、`formal_relation`、`diagnostic` 分桶规范化。
- 03 模块已能做逐 `EvidenceRequirement` 的充分性、freshness 和缓存处置判断，并生成最小识别目标。
- 04/语义服务已能在执行前二次查缓存，缓存命中不调用供应商；新识别结果可 dry-run，也可经受控路径写入语义证据。
- 语义 payload 已采用不可变 `payload_ref`，Neo4j 中的旧 interpretation 已有 `stale` 状态机制。
- 候选关系、正式关系、来源事实和模型语义证据已有明确隔离，默认 `write_back=false`。

尚未实现的核心是：

- 没有问题级 `EvidenceBundle` 和 `EvidenceFusionService`。
- 没有统一接入 `RetrievalBundle + SemanticGapDecision + RecognitionResult[]` 的规范化入口。
- 没有字段/命题级冲突分组与冲突矩阵。
- 现有 `EvidenceItem` 没有显式 `claim_capabilities`、规范化值、证据家族/取代链等融合字段。
- 没有从证据需求到 claim 支撑集合的完整可解释判断，也没有整体 `answerability` 计算器。
- 没有把请求授权、模块策略、结果有效性、scope 与 repository 可用性集中为一次受控写回决策和结果。
- 完整 `DrawingAssistantService`、06 答案生成、07 追溯反馈仍未实现，因此本需求只能先形成可独立验收的 05 模块，不能宣称端到端产品闭环完成。

推荐采用：**独立、确定性、策略驱动的 EvidenceFusionService；复用现有 `EvidenceItem`，以兼容方式补充融合元数据；缓存复用继续由 03/04 负责，05 负责汇总与 stale/lineage 表达；语义写回委托现有受控语义服务，不直接访问 repository。**

---

## 1. 当前架构是否支持？

### 1.1 支持程度判断

| 能力 | 当前状态 | 判断 |
|---|---|---|
| `EvidenceItem` 公共合同 | 已有 | 可扩展复用，不应另建同名并行 DTO |
| 图谱证据规范化 | 部分已有 | 检索结果已规范化；临时识别结果尚缺统一产品层投影 |
| 事实等级隔离 | 已有 | 可直接作为融合硬边界 |
| 证据充分性 | 已有前置判断 | 03 面向“是否需要识别”；05 仍需面向“识别后能否支撑 claim”复评 |
| freshness/cache disposition | 已有前置判断 | 03 做只读决策，04 做执行期缓存命中；05 需要汇总最终 cache 状态 |
| `stale` | 部分已有 | 状态和 repository 标记存在，但缺跨 cache-key 的证据取代 lineage |
| 冲突识别 | 仅有粗粒度状态 | 缺统一冲突键、矩阵、冲突记录和解决策略 |
| claim 支撑能力 | 未实现 | `Claim` 有 `evidence_ids`，但 `EvidenceItem` 尚无显式能力声明与绑定结果 |
| `answerability` | 未实现 | 05 文档有目标枚举，当前公共合同和服务尚未落地 |
| 受控语义写回 | 底层已有 | 需产品层集中门控和批次级结果；不得绕过 semantic service |
| 候选提升 | 已有独立受控路径 | 不属于融合器，继续由 `CandidateReviewService` 处理 |

因此答案是：**架构方向兼容，已有约六成底层能力；缺的是产品层的统一融合策略、合同和编排，而不是 Neo4j 基础能力或新的模型执行器。**

### 1.2 可直接复用的架构边界

```text
QuestionUnderstandingResult
  -> GraphRetrievalService
  -> RetrievalBundle
  -> SemanticGapDecisionService
  -> [按需] SemanticRecognitionService / 04 执行层
  -> EvidenceFusionService（本需求新增）
  -> EvidenceBundle
  -> 06 AnswerGenerationService（后续）
```

融合模块处于 04 之后、06 之前。它只消费 DTO 和 port，不执行新的 Neo4j 查询，不调用 Qwen，不拼写 Cypher，也不承担自然语言生成。

### 1.3 必须保持不变的边界

- `fact_kind` 不因融合、置信度或用户偏好而提升。
- 来源事实不能被模型结果覆盖；模型结果只能保持为 observation、interpretation 或 candidate evidence。
- `candidate_relation` 和 `matched_candidate` 不能成为 `formal_relation`。
- `RecognitionRun`/`RecognitionAttempt` 继续位于图谱外；图谱内证据通过 `recognition_run_id` 关联。
- 默认 `write_back=false`；“允许识别”不等于“允许写回”。
- 正式关系提升继续经过 `CandidateReviewService` 和硬规则，不进入 EvidenceFusionService。
- 现有 `DrawingGraphQAService` 继续作为六类固定只读问题的兼容层，不反向依赖新的产品融合模块。

---

## 2. 需要新增哪些模块？

建议把 05 拆成边界清晰的纯逻辑组件，最终由一个服务编排，避免形成单一巨型融合文件。

| 建议模块 | 核心职责 | 输入/输出 | 是否产生副作用 |
|---|---|---|---|
| `assistant_evidence_fusion_models.py` | 定义 `EvidenceBundle`、`Answerability`、`ConflictRecord`、`ClaimSupportAssessment`、`WriteBackPolicy/Result`、`EvidenceLineage` 等 05 专用合同 | 纯 DTO | 否 |
| `assistant_recognition_projection.py` | 将 `SemanticRecognitionResult`/04 执行结果投影为统一 `EvidenceItem` | recognition result -> evidence items + diagnostics | 否 |
| `assistant_evidence_normalization.py` | 校验 ID/scope/fact kind，生成规范化值、冲突键、去重指纹与 lineage key | heterogeneous evidence -> normalized evidence | 否 |
| `assistant_evidence_deduplication.py` | 合并完全相同的语义内容，但保留全部 provenance、run、payload 和引用 | normalized items -> evidence groups | 否 |
| `assistant_evidence_conflicts.py` | 按冲突矩阵识别一致、互补、冲突、取代和不可比较 | evidence groups -> conflict records | 否 |
| `assistant_claim_support.py` | 建立“证据能支撑何种 claim”的能力矩阵；逐需求输出满足、部分满足、冲突、缺失或需正式审核 | requirements + accepted/conflicting evidence -> support assessments | 否 |
| `assistant_answerability.py` | 根据 required/optional 需求、识别失败、scope 歧义和冲突计算整体 `answerability` | support assessments -> stable enum + reason codes | 否 |
| `assistant_cache_closure.py` | 聚合 03 的 cache candidates、04 实际 cache hit/miss 与 05 stale/lineage，形成请求级 cache status | decision + execution + evidence -> cache summary | 否 |
| `assistant_semantic_write_back.py` | 集中执行五项门控，并把实际持久化委托给既有受控语义服务/port | policy + validated new evidence -> write-back result | 可选、受控 |
| `assistant_evidence_fusion.py` | `EvidenceFusionService.fuse()` 唯一编排入口，按固定阶段运行以上组件 | 规定的四类输入 -> `EvidenceBundle` | 默认否 |
| `assistant_evidence_fusion_factory.py` | 装配纯组件和可选写回 port，不读取密钥、不创建 Neo4j driver | dependencies -> service | 否 |

### 2.1 `EvidenceItem` 的推荐演进

现有 `assistant_models.EvidenceItem` 已被检索闭环使用，推荐**兼容扩展**，不新建第二个同名类型。建议增加或通过强类型融合元数据承载：

```text
claim_capabilities[]       # 可支撑的命题能力，不等于最终 claim
normalized_value          # 仅用于比较，不覆盖 value
comparison_key            # target + field/predicate + qualifier
evidence_family_key       # 同一目标/任务/语义槽的稳定家族
supersedes_evidence_ids[] # 新证据取代哪些旧证据
cache_key                 # 从松散 metadata 提升为明确可查询字段，或保留兼容读取
content_fingerprint       # 确定性去重
```

其中 `value`、原始 evidence refs、`fact_kind` 和 provenance 必须保留。规范化值仅服务比较和匹配，不能反向覆盖原始证据。

### 2.2 `EvidenceBundle` 推荐合同

```text
request_id
subrequest_id
accepted_evidence[]
conflicting_evidence[]
conflicts[]
claim_support[]
unsupported_claims[]
cache_summary
provenance[]
overall_confidence
answerability
reason_codes[]
warnings[]
write_back_result
```

`accepted_evidence` 表示“可参与当前回答”，不表示它已经变为正式事实。`conflicting_evidence` 也不能删除；06 模块需要它来生成明确的不确定性说明。

---

## 3. 影响哪些已有模块？

### 3.1 高影响模块

| 已有模块 | 影响 | 建议 |
|---|---|---|
| `assistant_models.py` | 需要补充 05 合同或提供兼容扩展点 | 保留现有字段与默认值，避免破坏 01–04；05 专用复杂 DTO 可独立文件定义 |
| `assistant_retrieval_projection.py` | 是持久化图谱证据到 `EvidenceItem` 的首个入口 | 补齐稳定的 task/cache/version/比较元数据；不在这里做冲突决策 |
| `assistant_evidence_sufficiency.py` | 已有需求匹配规则可复用 | 抽取共享“证据是否能满足需求”的纯规则，避免 03 和 05 判定漂移 |
| `assistant_evidence_freshness.py` | 已有 freshness 维度和 cache disposition | 作为 freshness 权威规则；05 消费结果并补充识别后的 lineage/stale 汇总 |
| `semantic_service.py` | 产生临时/持久化 observation、interpretation 和缓存命中结果 | 需要暴露明确的 per-target cache outcome/来源，避免 05 通过猜测判断命中 |
| `semantic_neo4j_repository.py` | 当前负责 interpretation stale 标记 | 需支持 evidence family/lineage 的受控持久化，或至少由 port 返回明确 stale 结果 |
| `tool_facade.py` / `tool_factory.py` | 产品编排最终仍经 facade/受控 application port | 可增加窄的语义证据持久化能力；不得暴露 repository 或通用写接口 |

### 3.2 中影响模块

| 已有模块 | 影响 | 建议 |
|---|---|---|
| `assistant_semantic_gap_decision.py` | 输出 cache candidates 和需求评估 | 保持纯决策；05 消费其结果，不把融合逻辑塞回 03 |
| `recognition_models.py` / `recognition_execution.py` | 04 结果需进入产品层投影 | 尽量不改执行内核，只补稳定适配所需字段 |
| `semantic_cache.py` | cache key 已统一 | 保持 key 算法权威；新增 lineage key 时明确二者用途不同 |
| `semantic_models.py` | observation/interpretation 是融合输入 | 可能补版本或证据 family 字段，但不改变图谱层级含义 |
| `semantic_query_projection.py` | 跨请求读取持久化语义证据 | 确保能返回 stale、版本、payload、run 和 lineage 信息 |
| `06-answer-generation.md` 对应后续模块 | 直接消费 `EvidenceBundle` | claim 生成必须使用 05 的 support assessment，不自行重做事实分级 |
| `07-traceability-and-feedback.md` 对应后续模块 | 记录冲突、claim 支撑和写回 | TraceRecord 以后需保存 evidence IDs、conflict IDs、cache summary 和 write-back result |

### 3.3 低影响或不应修改

- 基础导入、扫描、标注校验、几何规范化和 ID 生成：不应因 05 改变。
- 离线派生关系增强：仍负责规则关系，不吸收语义融合职责。
- `CandidateReviewService`：保持候选复核与正式提升的唯一受控路径。
- QA CLI/HTTP/MCP：本轮不扩展为产品入口，也不开放写回。
- Neo4j 来源事实 schema：不应因 EvidenceBundle 引入新业务节点。

---

## 4. 技术方案有哪些？

### 方案 A：在 `SemanticRecognitionService` 内直接补融合与写回

识别完成后，由现有语义服务合并检索证据、处理冲突并决定持久化。

优点：改动入口少；可直接复用缓存和 repository；短期实现快。

缺点：语义服务会同时承担“是否识别、执行识别、缓存、融合、claim 支撑、answerability、写回”，职责过载；不调用识别的纯图谱问题也难复用；03/05 规则容易散落；后续 06/07 对内部实现产生强耦合。

结论：不推荐作为正式架构。

### 方案 B：独立确定性融合服务，复用现有缓存和语义写回（推荐）

建立 `EvidenceFusionService`，所有输入先投影为统一 `EvidenceItem`，依次执行规范化、去重、freshness/stale、冲突检测、claim 支撑、answerability，最后按策略可选委托写回。

优点：边界与 00–07 蓝图一致；离线可测试；图谱证据、缓存证据和本次临时结果都能复用；冲突和 answerability 可解释；不会把模型或 repository 侵入融合规则；便于 06/07 消费。

缺点：需要新增较多 DTO 和纯逻辑组件；必须认真处理 03 与 05 的规则复用；现有 `EvidenceItem` 兼容迁移需要合同测试。

结论：最符合当前项目的分层、可追溯与安全边界。

### 方案 C：事件溯源式证据账本 + 物化 EvidenceBundle

所有 observation、interpretation、冲突、stale、取代、claim 支撑和写回都记录为 append-only 事件，再按 request 物化融合结果。

优点：审计和回放能力最强；天然支持历史版本、规则重算、反馈修订和异步处理；适合未来多用户、长生命周期系统。

缺点：需要事件存储、幂等消费、版本迁移和物化一致性；明显扩大 05 的首版范围；与当前同步优先架构不匹配；运维复杂度高。

结论：可作为 07 之后的演进方向，不适合本阶段直接落地。

### 方案 D：使用 LLM/Agent 做自由证据裁决

把所有证据交给文本模型，由模型决定冲突、可信度、claim 和是否可回答。

优点：对开放文本表达灵活，早期演示速度快。

缺点：结果不稳定、不可严格回归、可能提升事实等级或忽略冲突；难以证明 cache/stale/write-back 安全；成本和延迟增加；违反“结构化机器答案为权威、生成器不得新增 claim”的设计。

结论：不适合作为权威融合路径。未来若使用，只能生成非权威解释，且必须经过确定性合同校验。

---

## 5. 优缺点比较

| 维度 | 方案 A：塞入语义服务 | 方案 B：独立确定性融合 | 方案 C：事件账本 | 方案 D：LLM 裁决 |
|---|---:|---:|---:|---:|
| 与现有分层一致性 | 低 | 高 | 中 | 低 |
| 可解释性 | 中 | 高 | 最高 | 低 |
| 离线可测试性 | 中 | 高 | 高 | 低 |
| 首版实施成本 | 低 | 中 | 高 | 中 |
| 长期扩展性 | 低 | 高 | 最高 | 中 |
| 写回安全 | 中 | 高 | 高 | 低 |
| 规则漂移控制 | 低 | 高 | 高 | 低 |
| 对 06/07 的接口稳定性 | 低 | 高 | 高 | 低 |
| 当前推荐度 | 不推荐 | **推荐** | 后续演进 | 不推荐 |

---

## 6. 推荐方案

### 6.1 推荐结论

采用方案 B：**独立确定性 EvidenceFusionService + 共享规则组件 + 现有受控语义持久化路径**。

不要新增另一套 cache key、另一套 fact hierarchy 或第二个语义 repository。05 应是产品级“证据组织与裁决层”，而不是新的识别层或数据库层。

### 6.2 推荐数据流

```text
RetrievalBundle
SemanticGapDecision
SemanticRecognitionResult[]
WriteBackPolicy
  -> RecognitionEvidenceProjector
  -> EvidenceNormalizer
  -> EvidenceDeduplicator
  -> FreshnessAndLineageResolver
  -> EvidenceConflictDetector
  -> ClaimSupportEvaluator
  -> AnswerabilityEvaluator
  -> [可选] ControlledSemanticWriteBackPort
  -> EvidenceBundle
```

顺序必须固定：**先规范化，再去重，再处理 freshness/stale，再判冲突，再计算 claim 支撑和 answerability，最后才考虑写回。** 未通过 schema、scope 或事实等级校验的结果不能通过“先写回再修正”进入持久化层。

### 6.3 证据规范化规则

1. `fact_kind` 从可信输入映射中继承，后续只读。
2. 原始 `value` 不修改；另生成 `normalized_value`。
3. 每条证据至少具有稳定 `evidence_id`、scope、source system 和 provenance。
4. 语义证据尽可能携带 `recognition_run_id`、`payload_ref`、model/prompt/contract/preprocessing/normalization version、image hash 和 bbox。
5. 关系证据使用确定方向的 subject/predicate/object 规范化；不能仅用显示文本比较。
6. 去重键建议为：`fact_kind + comparison_key + normalized_value + source fingerprint`。内容相同但 run 不同的条目可以聚合显示，但所有 provenance 必须保留。
7. `claim_capabilities` 由可信的“fact kind + schema field + relation type”注册表生成，不接受模型自由声明为权威值。

### 6.4 Claim 支撑能力矩阵

不能使用一个全局“来源事实 > 正式关系 > 派生关系 > observation > interpretation > candidate”的排序解决所有问题。不同 claim 需要不同能力：

| Claim 能力 | 可直接支撑 | 只能限定性支撑 | 不能支撑 |
|---|---|---|---|
| `identity_and_location` | `source_fact` | 无 | 其他类型 |
| `confirmed_relation` | `formal_relation`；某些由规格明确的 `derived_relation` | 无 | candidate、observation、interpretation |
| `rule_derived_context` | `derived_relation` | 无 | semantic interpretation |
| `observed_text_or_symbol` | `semantic_observation` | stale/低置信 observation | interpretation、candidate |
| `semantic_meaning` | `semantic_interpretation` 且有 observation 支撑 | 低置信或冲突 interpretation | diagnostic |
| `possible_relation` | `candidate_relation` | 冲突或多候选 candidate | 不得表达为 confirmed relation |
| `runtime_or_cache_status` | `diagnostic` | 无 | 工程事实类型 |

逐 claim/requirement 的结果建议固定为：

```text
supported
supported_with_qualifier
conflicting
missing
stale_only
formal_review_required
unsupported
```

### 6.5 冲突矩阵

冲突判断必须以 `comparison_key = scope + semantic slot/predicate + qualifiers` 为前提；不同目标、不同字段或不同时间基线的证据不可直接判冲突。

| A \ B | source fact | derived relation | semantic observation | semantic interpretation | candidate relation | formal relation | diagnostic |
|---|---|---|---|---|---|---|---|
| source fact | 同键不同值：`hard_conflict` | 通常互补；若派生否定来源则 `rule_conflict` | 不一致：`model_vs_source` | 不一致：`model_vs_source` | 候选与 scope 冲突：候选无效 | 正式关系端点与来源冲突：`integrity_conflict` | 不比较 |
| derived relation | — | 同规格/版本不同目标：`rule_conflict` | 通常互补 | 不一致：`semantic_vs_rule` | candidate 不覆盖正式派生 | 若语义相同则互补；不同则 `relation_conflict` | 不比较 |
| semantic observation | — | — | 同区域/同任务不同值：`peer_conflict` | 若解释不受 observation 支撑：`support_conflict` | 通常互补 | observation 可质疑但不能撤销 formal | 不比较 |
| semantic interpretation | — | — | — | 同目标/字段不同值：`peer_conflict` | 解释可支撑候选但不提升 | 不一致：`formal_vs_semantic` | 不比较 |
| candidate relation | — | — | — | — | 同候选组多目标：`ambiguity`，不是 winner | formal 已存在时 candidate 保留历史但不作为当前确定答案 | 不比较 |
| formal relation | — | — | — | — | — | 同一互斥槽多个 formal：`critical_integrity_conflict` | 不比较 |
| diagnostic | — | — | — | — | — | — | 同一运行状态不一致：`diagnostic_conflict` |

处理原则：

- 冲突记录双方 evidence ID、冲突键、类型、严重度和原因码。
- “高等级证据胜出”只影响当前 claim 是否可成立，不删除或改写另一方。
- 同等级冲突不得用最高 confidence 自动挑选 winner；可以配置最小差值规则，但默认保持 ambiguous。
- 正式关系与新模型解释冲突时，正式关系继续作为当前正式状态，模型结果进入冲突集合，并建议人工复核；融合器不得撤边。
- 多个候选是歧义，不是事实冲突；仍需在 `answerability` 中反映其无法唯一回答。

### 6.6 `stale` 与缓存闭环

03、04、05 的职责应明确分开：

- **03 决策时 freshness：** 判断现有证据能否复用、是否需要识别；只读，不改状态。
- **04 执行时 cache：** 在供应商调用前二次查实际缓存；决定 hit/miss；不创建重复 run。
- **05 融合时 closure：** 汇总计划与实际结果，标记哪些旧证据只保留审计、哪些新证据是当前有效版本，并输出最终 cache summary。

现有 repository 通过相同 `cache_key` 查找旧 interpretation 并标 `stale`。但 cache key 本身包含图片、bbox、模型、prompt 和合同版本；这些维度变化后 key 会变化，因此仅按相同 key 无法可靠定位“同一语义槽的旧版本”。推荐新增：

```text
evidence_family_key = target_id + task_type + output_slot + normalization_scope
cache_key           = family + image/bbox/model/prompt/contract/preprocessing versions
```

- `evidence_family_key` 用于 lineage、取代和 stale 范围。
- `cache_key` 用于精确复用。
- 新结果成功且允许写回时，只将同 family 的旧语义 interpretation 标记 stale；payload 仍不可变。
- observation 是否自动 stale 应按任务策略配置。纯文字读取在图片/bbox 改变时应 stale；仅模型版本变化是否使 observation stale，需要由 freshness policy 决定，不能一刀切。
- 写回失败时，新临时结果仍可参与本次回答，但 `write_back_result=failed/partial`；不得把它报告为跨请求缓存已建立。

最终 cache status 建议包含总体状态和逐目标明细：

```text
overall: full_hit | partial_hit | miss | stale | bypassed | mixed
targets[]: expected_key, actual_disposition, evidence_ids, new_run_id, persisted
```

### 6.7 `answerability` 算法

整体状态由逐 requirement/claim support 计算，不能只看“是否有任意证据”：

1. scope 缺失、冲突或指代不唯一，且无法安全继续：`clarification_required`。
2. 问题类型或所需证据能力不受支持：`unsupported`。
3. 所有 required requirement 均 `supported` 或允许限定表达的 `supported_with_qualifier`，且无阻断性冲突：`answerable`。
4. 至少一个 required requirement 可回答，但还有 missing、stale-only、识别失败或非阻断冲突：`partially_answerable`。
5. 只有 stale、冲突或 candidate，且问题要求当前/正式确定答案：不得输出 `answerable`。
6. 只有 formal review 缺口时，可以回答“当前为候选、尚未正式确认”，但不能回答正式关系成立；通常为 `partially_answerable`。

建议同时输出 reason codes，例如 `required_evidence_missing`、`evidence_conflict`、`stale_only`、`formal_review_required`、`recognition_failed`，供 06 稳定映射为 `AnswerPackage.status`。

### 6.8 受控语义写回

写回策略至少执行以下逻辑与：

```text
effective_write_back =
  request_allow_write_back
  AND module_allow_write_back
  AND result_schema_valid
  AND target_scope_valid
  AND repository_available
  AND evidence_kind_allowed
  AND no_blocking_conflict
```

建议额外加入：权限/环境能力、payload 已脱敏、run/attempt 可审计、幂等键可用。

允许写回：经验证的 `semantic_observation`、`semantic_interpretation`，以及任务允许的图谱外运行/payload 审计。

禁止写回：

- 来源事实覆盖或 `DrawingBlock.block_type` 推断写入。
- diagnostic 作为工程事实。
- candidate 直接提升 formal。
- 冲突证据的静默覆盖或历史删除。
- 未通过 schema/scope 校验的模型输出。
- 通过 EvidenceFusionService 直接调用 repository/Cypher。

`WriteBackResult` 应逐条报告 `persisted`、`skipped`、`failed`、原因码、evidence IDs 和 stale/supersede 结果；部分失败不得伪装为全量成功。

### 6.9 推荐分阶段落地边界

本报告不是实施计划，但从依赖关系看，后续设计/任务应按以下能力切分：

1. 先冻结 05 DTO、能力矩阵、冲突矩阵和 answerability 枚举。
2. 建立 retrieval/recognition 两类 `EvidenceItem` 投影和合同测试。
3. 实现纯函数规范化、去重、conflict、claim support、answerability。
4. 实现 cache closure 与 evidence family/lineage；再调整 repository stale 行为。
5. 最后接入受控语义写回 port，并验证 dry-run 零副作用和部分失败。
6. 05 独立验收后，再由后续 `DrawingAssistantService` 串联 01–06；不要在 05 内提前实现产品 adapter 或文本答案生成。

---

## 7. 风险与缓解

| 风险 | 后果 | 缓解措施 |
|---|---|---|
| 03 与 05 重复判断充分性/freshness | 相同证据在识别前后得到矛盾结论 | 抽取共享纯规则；03 输出前置 assessment，05 只补充新证据后重算 |
| 另建一套 `EvidenceItem` | DTO 漂移、adapter 重复转换 | 兼容扩展现有公共合同；05 专用结果另建类型 |
| 全局优先级替代 claim 能力矩阵 | observation 被误当身份事实，candidate 被误报 formal | 使用 claim capability registry 和 formal gate |
| 规范化过度 | 原文、符号体系或工程差异被抹平 | 原始 value 永久保留；normalized value 仅比较；规则版本化 |
| 冲突键过粗 | 不相关证据被误判冲突 | comparison key 必须包含 scope、字段/关系谓词和必要限定符 |
| 冲突键过细 | 同一事实无法聚合，冲突漏检 | 为每类任务定义受测试的 slot schema 和 family key |
| 现有 stale 只按 cache key | 版本/图片变化后的旧证据无法形成取代链 | 分离 `evidence_family_key` 与 `cache_key`，显式保存 supersedes/lineage |
| observation 与 interpretation 使用同一 stale 策略 | 原始观察被不必要作废，或旧解释被错误复用 | 按 evidence kind 和 freshness policy 配置 stale 维度 |
| 内存缓存被误认为跨进程闭环 | 重启后丢失，命中率/成本判断失真 | 对外明确 cache backend；生产跨请求复用需持久化实现及一致性测试 |
| dry-run 结果先进入缓存 | `write_back=false` 产生跨请求副作用 | 明确区分 request-local memoization 与 persistent cache；dry-run 仅本请求可用 |
| 当前 `semantic_service` 在 `write_back=false` 下仍写入注入的 cache service | 可能违反 05 文档“不得跨请求持久化”的意图 | 设计阶段先定义 cache store 的持久性语义；测试 dry-run 不改变持久化 backend |
| 受控写回部分成功 | run、payload、cache、Neo4j 状态不一致 | 使用明确步骤状态、幂等键、补偿/重试策略；返回 partial，不伪造原子成功 |
| 正式关系与模型结果冲突 | 自动撤销正式事实或错误忽略新证据 | 保留 formal 当前状态，新增冲突/复核建议；只能由审核路径改变正式关系 |
| 多候选被算法强选 | 产生伪确定答案 | 默认 ambiguous；只有硬规则或明确审核才选唯一候选 |
| `overall_confidence` 被误用 | 不同事实等级的数字被错误平均 | 只做可解释聚合；answerability 以需求满足为主，不以平均置信度决定 |
| 大 payload 进入 `EvidenceBundle` | 内存、日志与隐私风险 | 继续只传摘要和 `payload_ref`，按需读取完整 payload |
| live 能力未验证 | 离线合同通过被误报为生产闭环可用 | 单元/fake、live DashScope、live Neo4j、产品端到端分别验收与报告 |

### 7.1 需要优先澄清的技术债

进入设计/实施前，应在书面规格中明确三点：

1. `SemanticCacheService` 在生产中是 request-local、进程内还是持久化 backend；不同语义决定 dry-run 是否构成副作用。
2. `EvidenceItem.claim_capabilities` 是持久字段还是由 registry 动态推导。推荐动态推导并把 registry/version 记录进 trace，避免不受控输入伪造能力。
3. `answerability` 是按整个 request 还是按 subrequest 计算。推荐先按 subrequest 计算，再确定性聚合到 request，避免多意图中一个失败拖成不可解释的全局状态。

---

## 8. 建议验收标准

后续实现至少应满足：

- 任意输入证据在融合前后保持原 `fact_kind`、原始 value 和 provenance。
- 检索证据与本次临时识别结果可进入同一 `EvidenceBundle`。
- 完全重复证据可去重展示，但 run、payload、引用和来源不丢失。
- 冲突矩阵覆盖 source/model、peer semantic、candidate ambiguity、formal/model 和 formal/formal 完整性冲突。
- stale 证据不会支撑要求 current 的 claim；旧 payload 不被覆盖。
- claim support 能解释“哪些证据支持/拒绝、为什么、需要何种限定语”。
- `answerability` 对 answered/partial/clarification/unsupported 的映射稳定且逐 subrequest 可解释。
- cache hit 不调用供应商、不创建新持久化 run；partial/miss/stale/bypass 可观测。
- `write_back=false` 不写 run log、Neo4j 或持久化缓存。
- 写回只能经 facade/semantic service/受控 application port；失败返回明确 partial/failed 结果。
- candidate 不因融合、置信度、用户确认或写回授权而变成 formal。
- 现有 01–04、QA/HTTP/MCP 兼容行为保持不变。
- 离线测试、live DashScope、live Neo4j 与完整产品链路分别报告；skipped 不等于通过。

---

## 9. 最终结论

该需求与当前产品蓝图一致，架构上可行，而且已有较好的底层积累；真正的工作重点不是再造缓存或模型调用，而是建立一个**问题级、claim-aware、保留冲突、可解释且默认只读的证据融合边界**。

推荐方案能够最小化对已有 01–04 的侵入，同时为 06 答案生成和 07 追溯反馈提供稳定输入。首版应坚持同步、确定性、规则驱动和 YAGNI：不引入事件平台，不让 LLM 决定事实等级，不新增产品 adapter，不改变来源事实 schema。只有在 05 的合同、矩阵、stale lineage、answerability 和写回门控独立验收后，才适合继续串联完整 `DrawingAssistantService`。
