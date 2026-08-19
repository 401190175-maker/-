# 证据融合与缓存闭环 Proposal

**文档状态：** 需求提案，已实施（Task 1-56 全部完成，离线/fake 验证通过）  
**日期：** 2026-08-13  
**适用范围：** 产品实现层 05 证据融合与缓存闭环

## 1. 背景

当前项目已经建立从图纸来源事实到按需多模态识别的主要基础链路：

- 来源事实导入、离线派生关系增强和候选关系复核能够形成可追溯的图谱事实与关系。
- `DrawingGraphToolFacade` 提供统一的只读查询、语义识别、语义证据查询和受控写回边界。
- 产品公共合同已经定义 `AssistantRequest`、`EvidenceRequirement`、`EvidenceItem`、`RetrievalBundle`、`Claim` 和 `AnswerPackage` 等 DTO，并通过 `FactKind` 区分来源事实、派生关系、语义观察、语义解释、候选关系、正式关系和诊断信息。
- `GraphRetrievalService` 已能把 facade 查询结果规范化为按事实等级分桶的 `RetrievalBundle`。
- 语义缺口决策闭环已经能够评估证据充分性、freshness 和缓存处置，规划最小识别目标，并执行识别授权、成本与时延门控。
- 多模态识别执行层已经能够按精确目标调用供应商无关执行流水线，生成受约束的 observation、interpretation、candidate evidence、run/attempt、payload 和实际指标。
- `SemanticCacheService`、不可变 `payload_ref`、图谱外 `RecognitionRun`/`RecognitionAttempt`、图谱内语义证据和 interpretation 的 `stale` 机制已经存在。
- 语义识别默认 `write_back=false`；只有显式授权时，才可经既有 semantic service 和受控 repository 持久化语义证据。

但是，现有链路在识别执行之后仍缺少产品级证据融合环节。图谱中的已有事实、本次请求产生的临时识别结果、缓存命中状态、stale 证据、冲突证据和诊断信息尚不能统一组织为可供答案生成消费的 `EvidenceBundle`。系统也尚不能稳定回答“哪些证据可以支撑当前 claim”“证据之间是否冲突”“当前问题是否可回答”“新结果是否应当受控写回”。

因此，需要在产品实现层 04 多模态识别之后、06 答案生成之前增加独立的证据融合与缓存闭环：

```text
RetrievalBundle
  + SemanticGapDecision
  + RecognitionResult[]
  + WriteBackPolicy
  -> EvidenceFusionService
       -> 证据投影与规范化
       -> 去重与 provenance 聚合
       -> freshness / stale / lineage 处理
       -> 冲突检测
       -> claim 支撑能力评估
       -> answerability 计算
       -> 可选受控语义写回
  -> EvidenceBundle
  -> 后续 AnswerGenerationService
```

融合的含义是组织、比较和限定证据，不是覆盖原始记录、抹平冲突或提升事实等级。

## 2. 当前问题

当前架构支持新增证据融合闭环，但只具备底层能力，尚未形成完整产品运行时，主要问题如下：

- 当前没有问题级 `EvidenceBundle` 和统一的 `EvidenceFusionService`。
- `RetrievalBundleBuilder` 已能规范化图谱检索结果，但本次临时 `SemanticRecognitionResult`/04 执行结果尚无统一的产品层 `EvidenceItem` 投影入口。
- 现有 `EvidenceItem` 能表达事实等级、scope、value、置信度和 provenance，但缺少融合所需的规范化值、比较键、claim 支撑能力、证据家族、取代关系和确定性去重指纹。
- 当前没有统一的证据规范化规则。不同来源对文本、符号、关系方向、字段值和 scope 的表达可能不同，无法稳定判断一致、互补或冲突。
- 当前没有字段级或命题级冲突矩阵。来源事实与模型解释冲突、同区域两次 observation 不一致、正式关系与新模型解释不一致、多候选歧义等情况尚不能统一表达和追溯。
- 当前充分性判断主要服务于识别前的语义缺口决策；识别完成后，系统尚未根据新增证据重新计算每项 claim/requirement 的支撑状态。
- `Claim` 已包含 `evidence_ids`，但尚无权威规则说明某种 `fact_kind` 和字段能够支撑何种 claim。仅靠全局证据优先级容易把 observation 当作来源事实，或把 candidate 误报为 formal。
- 当前没有稳定的整体 `answerability` 计算器，无法统一输出 `answerable`、`partially_answerable`、`clarification_required` 和 `unsupported`。
- 03 已有预期缓存判断，04 已有执行前实际缓存检查，但尚无模块汇总计划状态、实际命中、本次运行、stale、持久化和逐目标缓存结果。
- 当前 interpretation 的 stale 写入主要按相同 `cache_key` 定位旧记录；而 cache key 包含图片、bbox、模型、prompt 和合同版本，这些维度变化后 key 会变化，不能完整表达同一语义槽跨 cache-key 的取代关系。
- 当前缺少稳定的 `evidence_family_key`、`supersedes_evidence_ids` 或等价 lineage 合同，无法清楚说明哪条新证据使哪条旧证据失效。
- 当前产品层没有集中表达受控写回的全部门槛，也没有逐条报告 persisted、skipped、failed 和 stale/supersede 结果的 `WriteBackResult`。
- `write_back=false` 下的 request-local 复用和跨请求持久化缓存语义尚需明确。若注入的 cache backend 具有持久性，dry-run 路径写 cache 可能与“无持久化副作用”边界冲突。
- 如果把融合逻辑直接塞入 `SemanticRecognitionService`、`DrawingGraphQAService`、HTTP/MCP adapter 或自由 LLM/Agent，会造成职责膨胀、规则漂移、不可重复裁决和写回边界失守。

## 3. 功能目标

本需求目标是在产品实现层增加一个独立、确定性、可解释、默认无副作用的证据融合与缓存闭环。

### 3.1 统一证据合同

- 复用现有 `assistant_models.EvidenceItem`，以兼容方式补充融合元数据，不建立第二套同名证据 DTO。
- 将 `RetrievalBundle` 中的已有证据与本次 `RecognitionResult[]` 投影为统一 `EvidenceItem`。
- 每条证据保留稳定 `evidence_id`、原始 `fact_kind`、scope、原始 value、置信度、来源系统、run、payload、模型与规则版本及 evidence refs。
- 规范化不得改变 `fact_kind`，不得把高置信模型结果变为来源事实或正式关系。
- 统一输出 `EvidenceBundle`，至少包含可用于当前回答的证据、冲突证据、冲突记录、claim 支撑结果、未支持 claim、缓存摘要、provenance、整体置信度、answerability、原因码、warning 和写回结果。

### 3.2 证据规范化与去重

- 原始 `value` 永久保留；另行生成仅用于比较的 `normalized_value`。
- 按目标 scope、字段或关系谓词、必要限定条件生成稳定 `comparison_key`。
- 按目标、task type、输出语义槽和规范化范围生成 `evidence_family_key`，用于 lineage 和 stale 范围判断。
- 按事实等级、比较键、规范化值和来源指纹生成确定性 `content_fingerprint`。
- 对完全重复的证据进行展示级合并，但保留全部 recognition run、payload、source call、时间和 evidence refs。
- 文本、断面符号、枚举、关系方向和结构化字段采用按任务版本化的规范化规则，不以一个通用字符串清洗器替代领域规则。

### 3.3 冲突检测与保留

- 建立以 `comparison_key` 为前提的证据冲突矩阵，区分一致、互补、冲突、取代、歧义和不可比较。
- 覆盖来源事实内部冲突、规则派生冲突、模型与来源事实冲突、同等级语义证据冲突、interpretation 缺少 observation 支撑、候选组歧义、formal 与模型冲突以及互斥 formal 关系冲突。
- 每个冲突记录保存双方 evidence IDs、冲突键、冲突类型、严重度和稳定原因码。
- 高等级证据只能决定某类 claim 当前能否成立，不能删除、覆盖或改写冲突的低等级证据。
- 同等级语义证据冲突时默认保持 ambiguous，不仅凭最高 confidence 自动选择 winner。
- 正式关系与新模型结果冲突时，正式关系保持当前正式状态；模型结果进入冲突集合并产生人工复核建议，融合模块不得撤销正式关系。
- 多个候选属于歧义而非已确认事实，不得在融合阶段强选唯一候选。

### 3.4 Claim 支撑能力

- 建立确定性的 claim capability registry，根据可信的 `fact_kind + schema field + relation type` 推导证据可支撑的命题能力。
- `claim_capabilities` 不接受模型自由声明为权威值；能力注册表应版本化并进入追溯信息。
- 至少区分对象身份与位置、正式关系、规则派生上下文、观察到的文字或符号、语义含义、可能关系和运行/缓存状态。
- `source_fact` 支撑对象身份、位置、bbox 和归属；`semantic_observation` 不得替代这些来源事实。
- `formal_relation` 和符合规格的 `derived_relation` 支撑相应确定关系；`candidate_relation` 只能支撑“候选、可能、待确认”的限定性 claim。
- `semantic_interpretation` 只能支撑语义解释类 claim，且应保留 observation 支撑、不确定性和置信度。
- diagnostic 只支撑运行、缓存和缺口说明，不支撑工程事实结论。
- 逐 requirement/claim 输出 `supported`、`supported_with_qualifier`、`conflicting`、`missing`、`stale_only`、`formal_review_required` 或 `unsupported`，并列出采用和拒绝的 evidence IDs 及原因码。

### 3.5 Answerability

- 先按 `subrequest_id` 计算 answerability，再确定性聚合到整个 request，避免多意图请求中单个失败掩盖其他可回答部分。
- scope 缺失、冲突或指代不唯一且无法安全继续时，输出 `clarification_required`。
- 问题类型或所需证据能力不受支持时，输出 `unsupported`。
- 所有 required requirement 均得到充分或允许限定表达的支撑，且无阻断性冲突时，输出 `answerable`。
- 至少一部分 required requirement 可回答，但仍存在缺失、stale-only、识别失败、预算裁剪或非阻断冲突时，输出 `partially_answerable`。
- 当问题要求当前证据或正式确定关系时，仅有 stale、冲突或 candidate 不得输出 `answerable`。
- 只有 formal review 缺口时，可回答“当前为候选、尚未正式确认”，但不能回答正式关系已经成立。
- answerability 以证据需求满足为主，不由不同事实等级的简单平均置信度决定。

### 3.6 Stale、lineage 与缓存闭环

- 保持 03、04、05 职责分离：03 判断预期复用与识别缺口；04 在供应商调用前执行实际缓存检查；05 汇总最终缓存状态、stale 和 lineage。
- 继续复用 `semantic_cache.py` 的统一 cache key 算法，不建立第二套精确复用键。
- 分离 `evidence_family_key` 与 `cache_key`：family key 定位同一语义槽的证据家族，cache key 表示特定图片、bbox、模型、prompt、预处理、规范化和合同版本下的精确可复用结果。
- 新结果成功且允许持久化时，仅对同一 evidence family 内被取代的旧语义证据执行受控 stale 标记；不可变 payload 不覆盖。
- observation 与 interpretation 的 stale 维度分别由 evidence kind 和 freshness policy 控制，不能一刀切。
- 输出总体和逐目标 cache summary，至少表达 full hit、partial hit、miss、stale、bypassed、mixed、预期 key、实际处置、evidence IDs、new run ID 和 persisted 状态。
- 缓存命中不调用供应商，不创建新的持久化 `RecognitionRun` 或 attempt。
- 明确区分 request-local memoization 和 persistent cache；`write_back=false` 下不得改变跨请求持久化 backend。
- 写回失败时，新临时结果仍可用于本次融合，但不得报告为已建立跨请求缓存。

### 3.7 受控语义写回

- 写回默认关闭，只有请求授权、模块策略、结果 schema、目标 scope、repository、证据类型、冲突状态和运行环境权限全部允许时才可执行。
- 写回前验证 payload 已脱敏、run/attempt 可审计、幂等键和 lineage 信息可用。
- 只允许写入经验证的 `semantic_observation`、`semantic_interpretation` 和任务允许的图谱外运行/payload 审计。
- 实际持久化必须委托既有 facade、semantic service 或窄的受控 application port；融合模块不得直接调用 repository、Neo4j driver 或 Cypher。
- 输出逐条 `WriteBackResult`，区分 persisted、skipped、failed、原因码、evidence IDs 和 stale/supersede 结果。
- 部分写回失败时返回 partial/failed 状态并保留临时结果，不得伪装为全量成功。
- 任何授权都不能允许覆盖来源事实、设置 `DrawingBlock.block_type`、删除历史证据；不得把 candidate 直接提升为 formal。

### 3.8 确定性与可验证性

- 相同输入、相同策略和相同规则版本必须产生稳定排序和相同融合结果。
- 融合核心使用纯逻辑组件，不依赖 Neo4j、Qwen、HTTP、MCP 或 CLI adapter。
- 证据规范化、去重、冲突、claim 支撑、answerability、cache closure 和写回门控可分别测试。
- 离线/fake、live DashScope、live Neo4j 和完整产品端到端验证分别报告；skipped 不等于 live 能力通过。

## 4. 修改范围

本需求建议包含以下修改范围：

- 扩展产品公共合同或新增 05 专用合同模块，定义 `EvidenceBundle`、`Answerability`、`ConflictRecord`、`ClaimSupportAssessment`、`EvidenceLineage`、`CacheSummary`、`WriteBackPolicy` 和 `WriteBackResult`。
- 兼容扩展现有 `EvidenceItem`，补充或通过强类型融合元数据承载 claim capabilities、normalized value、comparison key、evidence family key、supersedes evidence IDs、cache key 和 content fingerprint。
- 新增 recognition result 到 `EvidenceItem` 的产品层投影能力，统一接入临时 observation、interpretation、candidate evidence、诊断、run、payload 和实际 cache 状态。
- 新增证据规范化和领域规则注册能力，按任务/字段生成规范化值、比较键、family key 和去重指纹。
- 新增证据去重与 provenance 聚合能力，在不丢失审计字段的前提下合并重复内容。
- 新增冲突检测能力和版本化冲突矩阵，输出稳定冲突类型、严重度和原因码。
- 新增 claim capability registry 和逐 requirement/claim 支撑评估能力，并复用 03 中可共享的事实等级、scope、状态和 freshness 规则。
- 新增 answerability 评估能力，支持 subrequest 级计算和 request 级确定性聚合。
- 新增 cache closure 能力，聚合 03 cache candidates、04 实际 cache outcome、本次识别运行、stale/lineage 和持久化结果。
- 为语义服务或识别结果补充明确的逐目标 cache outcome，使 05 不需要通过 run ID 或结果内容猜测缓存命中。
- 新增 evidence family/lineage 合同，并在必要时扩展语义证据 port、查询投影和受控 Neo4j repository，以支持跨 cache-key 的 stale/supersede 记录。
- 新增受控语义写回策略和窄 application port，实际写回继续复用既有 semantic service、payload store、run/attempt log 和语义 repository。
- 新增 `EvidenceFusionService.fuse()` 作为 05 唯一产品层编排入口，固定执行“投影 -> 规范化 -> 去重 -> freshness/stale/lineage -> 冲突 -> claim 支撑 -> answerability -> 可选写回”。
- 新增工厂装配能力，注入纯规则组件和可选写回 port；模块 import 和纯工厂创建不得连接数据库、读取供应商密钥或发起网络调用。
- 增加 DTO 合同、投影、规范化、去重、冲突矩阵、claim 支撑、answerability、cache closure、dry-run、写回门控、部分失败、静态依赖和兼容性测试。
- 实施后同步 `architecture.md`、`Module.md`、产品实现层 05 文档及相关状态说明，明确实际完成范围和验证层级。

首阶段应优先完成纯 DTO、纯规则融合核心和离线/fake 验证，再接入受控持久化。完整 `DrawingAssistantService`、答案生成和反馈追溯应在 05 独立验收后作为后续阶段处理。

## 5. 不包含范围

本需求不包含以下内容：

- 不实现完整 `DrawingAssistantService` 的端到端产品编排。
- 不实现 06 最终 claim 文本生成、机器答案组装或中文答案生成。
- 不实现 07 产品级 TraceRecord 存储、用户反馈 API 或反馈状态机。
- 不新增产品级 CLI、HTTP、MCP、Web UI 或远程 adapter。
- 不改造现有六类只读 `DrawingGraphQAService`、QA CLI、HTTP 或本地 STDIO MCP 的兼容行为。
- 融合模块不执行新的图谱查询，不调用 Qwen/DashScope 或其他模型，不创建识别目标，不执行重试。
- 不建设独立 OCR 流程，不引入 OCR 引擎，不执行全量自动语义扫描。
- 不建立事件溯源平台、异步消息队列或通用规则平台；首版保持同步、确定性和 YAGNI。
- 不让 LLM/Agent 作为权威证据裁决器；任何生成式说明都不能改变 `fact_kind`、冲突结果或 claim 支撑状态。
- 不修改基础导入、扫描、标注校验、几何规范化、稳定 ID 或离线派生关系增强规则。
- 不改变 Neo4j 来源事实节点、来源关系、约束或索引，不把 `EvidenceBundle`、`Claim` 或产品运行记录默认建成业务图谱节点。
- 不把 `RecognitionRun` 或 `RecognitionAttempt` 写成 Neo4j 节点。
- 不覆盖来源事实，不修改原始 `EvidenceItem.value`，不删除历史 observation、interpretation、payload 或冲突证据。
- 不设置或推断 `DrawingBlock.block_type`。
- 不审核或提升候选关系，不绕过 `CandidateReviewService` 和硬规则建立正式关系。
- 不把 candidate、`matched_candidate`、模型高置信结果或用户确认当作 formal relation。
- 不因 `allow_recognition=true`、问题语气、模型置信度或 `write_back_recommendation` 推断 `allow_write_back=true`。
- 不在 EvidenceFusionService 中直接创建 Neo4j driver、执行 Cypher 或调用 repository 写回方法。
- 不保证多个持久化后端具有数据库级原子事务；首版通过幂等、逐步状态和明确 partial/failed 结果处理部分失败。
- 不把设计文档、单元测试或 fake 测试写成 live DashScope、live Neo4j 或完整产品闭环已经通过。

## 6. 影响模块

| 模块 | 影响 | 边界要求 |
|---|---|---|
| `src/drawing_graph/assistant_models.py` | 兼容扩展 `EvidenceItem` 的融合元数据；必要时增加共享原因码和稳定枚举。 | 保留现有字段和默认值；公共合同不依赖数据库、HTTP、MCP、Qwen 或 repository。 |
| `src/drawing_graph/assistant_evidence_fusion_models.py`（新增） | 定义 `EvidenceBundle`、answerability、冲突、claim 支撑、lineage、缓存摘要和写回结果等 05 专用 DTO。 | 只承载数据和校验，不执行查询、识别或写回。 |
| `src/drawing_graph/assistant_recognition_projection.py`（新增） | 将 04/语义识别结果投影为统一 `EvidenceItem` 和 diagnostic。 | 不改变事实等级，不通过自由文本猜测 scope 或关系等级。 |
| `src/drawing_graph/assistant_evidence_normalization.py`（新增） | 生成 normalized value、comparison key、family key 和 content fingerprint。 | 保留原始 value；规范化规则按任务/字段版本化。 |
| `src/drawing_graph/assistant_evidence_deduplication.py`（新增） | 去重内容并聚合 provenance、run、payload 和 evidence refs。 | 去重不删除审计链，不跨 fact kind 合并。 |
| `src/drawing_graph/assistant_evidence_conflicts.py`（新增） | 执行冲突矩阵并生成 `ConflictRecord`。 | 不自动撤销 formal、不以 confidence 强选 winner、不修改输入证据。 |
| `src/drawing_graph/assistant_claim_support.py`（新增） | 提供 capability registry 和逐 requirement/claim 支撑评估。 | candidate 只能产生限定性 claim；diagnostic 不支撑工程事实。 |
| `src/drawing_graph/assistant_answerability.py`（新增） | 计算 subrequest 与 request 级 answerability 和原因码。 | 不生成最终答案，不以平均置信度代替需求满足判断。 |
| `src/drawing_graph/assistant_cache_closure.py`（新增） | 汇总预期/实际缓存状态、stale、lineage、run 和 persisted 结果。 | 不复制 cache key 算法，不调用供应商。 |
| `src/drawing_graph/assistant_semantic_write_back.py`（新增） | 集中写回门控并调用受控 application port，输出逐条写回结果。 | 默认关闭；不直接依赖 Neo4j/repository/Cypher，不提升 candidate。 |
| `src/drawing_graph/assistant_evidence_fusion.py`（新增） | `EvidenceFusionService.fuse()` 固定编排 05 全流程。 | 不查询图谱、不调用模型、不生成中文答案；除显式受控写回外保持纯逻辑。 |
| `src/drawing_graph/assistant_evidence_fusion_factory.py`（新增） | 装配融合规则和可选写回 port。 | import/创建纯服务不连接数据库、不读取密钥、不发网络请求。 |
| `src/drawing_graph/assistant_retrieval_projection.py` | 补齐持久化证据的 task/cache/version/比较所需元数据。 | 只负责投影，不在检索阶段判断冲突或 answerability。 |
| `src/drawing_graph/assistant_evidence_sufficiency.py` | 与 05 共享 fact kind、scope、状态和 formal gate 等纯规则。 | 避免复制出两套充分性规则；03 仍负责识别前决策。 |
| `src/drawing_graph/assistant_evidence_freshness.py` | 继续作为 freshness 维度与 cache disposition 的权威纯规则。 | 05 消费并补充识别后结果，不在 freshness 模块写缓存或 Neo4j。 |
| `src/drawing_graph/assistant_semantic_gap_decision.py` | 为 05 提供需求 assessment、cache candidates、selected/deferred targets 和原因码。 | 保持纯决策，不吸收识别后融合逻辑。 |
| `src/drawing_graph/recognition_models.py` / `recognition_execution.py` | 必要时补充稳定适配所需的逐目标结果与 cache 来源字段。 | 不把产品融合或写回策略放入供应商执行内核。 |
| `src/drawing_graph/semantic_models.py` | observation/interpretation 可能补充 evidence family、版本或 lineage 所需字段。 | 不改变图谱内语义证据的事实等级和含义。 |
| `src/drawing_graph/semantic_cache.py` | 保持统一 cache key 规范；必要时提供明确的 request-local/persistent cache port 语义。 | 不建立第二套精确复用键；dry-run 不改变持久化 backend。 |
| `src/drawing_graph/semantic_service.py` | 暴露逐目标实际 cache outcome；承接受控 observation/interpretation 持久化。 | 继续负责执行与底层写回，不负责产品级冲突和 answerability。 |
| `src/drawing_graph/semantic_repository.py` | 必要时扩展窄的 evidence family、stale 和 supersede port。 | 不向融合模块暴露通用 repository 写接口。 |
| `src/drawing_graph/semantic_neo4j_repository.py` | 支持按 evidence family 受控标记被取代证据 stale，并返回明确结果。 | 不覆盖不可变 payload，不删除历史节点，不改变来源事实。 |
| `src/drawing_graph/semantic_query_projection.py` | 返回 stale、cache/version、family/lineage、run 和 payload 引用，供跨请求融合。 | 保持稳定 DTO，不暴露 Neo4j 内部 ID 或 Cypher。 |
| `src/drawing_graph/semantic_payload_store.py` | 继续提供不可变、可追溯 payload。 | 修订生成新 `payload_ref`，不原地覆盖旧 payload。 |
| `src/drawing_graph/recognition_run_log.py` / attempt log | 记录实际运行、attempt 和写回状态，供 provenance 与 cache closure 使用。 | 继续位于图谱外，不成为工程事实。 |
| `src/drawing_graph/tool_facade.py` / `tool_factory.py` | 必要时提供窄的受控语义持久化 application port 并完成依赖装配。 | facade 不暴露 repository、driver、session、transaction 或任意 Cypher。 |
| `CandidateReviewService` / `relation_repository.py` | 保持候选审核和 formal 提升的既有职责。 | EvidenceFusionService 不直接调用提升方法；融合结果最多提出复核建议。 |
| 后续 06 答案生成模块 | 直接消费 `EvidenceBundle`、claim support、conflict 和 answerability。 | 不重新划分事实等级，不生成融合结果中不存在的新 claim。 |
| 后续 07 追溯反馈模块 | 记录 evidence、conflict、cache、claim support、answerability 和 write-back result。 | 运行审计不混入来源事实；用户反馈不直接提升 formal。 |
| `DrawingGraphQAService`、QA CLI/HTTP/MCP | 首阶段保持兼容。 | 不接入产品写回，不在 adapter 中复制证据融合业务逻辑。 |
| `tests/test_assistant_evidence_fusion_*.py` 及相关测试（新增） | 覆盖 DTO、投影、规范化、去重、冲突、claim 支撑、answerability、缓存、dry-run、写回与边界。 | 离线/fake、live DashScope、live Neo4j 和端到端状态分别报告。 |
| `architecture.md`、`Module.md`、产品实现层文档 | 实施后同步模块职责、数据流、接口、stale/lineage 和验证边界。 | 未实现或未 live 验证的能力不得提前写成已完成。 |
