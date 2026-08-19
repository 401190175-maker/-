# 答案生成与只读总编排 MVP 技术设计

**文档状态：** 已实现（Task 1-65 完成）；live Neo4j、live DashScope、真实文本 provider 未验证  
**依据文档：** `proposal.md`、`Feature_Analysis_Report.md`  
**适用范围：** 06 答案生成、`DrawingAssistantService` 只读总编排、产品级只读 CLI  
**推荐方案：** 确定性内核 + 默认中文模板 + 可选受约束文本生成  
**核心约束：** 优先复用 01—05、`DrawingGraphToolFacade` 和现有序列化/脱敏能力；禁止无意义重构；不改变图谱 schema；不新增写回入口

## 0. 设计结论与约束

本设计采用分析报告中的方案 B，但把职责边界进一步收敛为：

1. `machine_answer`、`claims`、`citations` 和 `status` 只由确定性代码产生，是权威输出。
2. 中文模板始终可用，是默认 `text_answer`。
3. 可选文本生成器只能重排或连接已批准 claim，不能生成或修改 claim/citation；任何异常或校验失败都回退模板。
4. `DrawingAssistantService` 只编排 01—06，不直接访问 Neo4j driver、repository、Cypher、provider 内部实现或离线增强规则。
5. 产品 CLI 是现有 QA CLI 的同级 adapter，不替换 `DrawingGraphQAService`、HTTP 或 MCP 链路。
6. `AssistantRequest.allow_write_back=true` 在产品服务入口立即拒绝；识别固定传 `write_back=false`；05 固定不传可写 `WriteBackPolicy`。
7. 只对 06 无歧义消费所必需的 02/05 接缝做兼容性修正，不重构既有业务模块。

“确定性 JSON”在本文中的精确定义是：给定相同的结构化输入（包括 `request_id`）、相同合同版本、相同策略和相同依赖返回值，输出的语义与 UTF-8 JSON 字节均一致。CLI 若未显式提供 `request_id` 可以生成新的请求 ID；重复性验收必须显式传入同一个 `request_id`。

---

## 1. 系统架构变化

### 1.1 变化前

当前产品链路已经具备 01—05，但停止在 `EvidenceBundle`：

```text
AssistantRequest
  -> 01 QuestionUnderstandingService
  -> 02 GraphRetrievalService
  -> 03 SemanticGapDecisionService
  -> 04 DrawingGraphToolFacade.recognize_semantic_targets(...)
  -> 05 EvidenceFusionService
  -> EvidenceBundle
```

现有 QA 链路独立存在：

```text
QA CLI / HTTP / MCP
  -> DrawingGraphQAService
  -> DrawingGraphToolFacade
```

### 1.2 变化后

新增产品级 06、07 与 CLI adapter：

```text
Product Read-only CLI
  -> DrawingAssistantService                         # 07，总编排
       -> QuestionUnderstandingService               # 01，复用
       -> [按 subrequest 独立执行]
            -> GraphRetrievalService                 # 02，复用
            -> SemanticGapDecisionService            # 03，复用
            -> DrawingGraphToolFacade                # 04，复用且 write_back=false
            -> EvidenceFusionService                 # 05，复用且无写回 policy
            -> AnswerGenerationService               # 06，新增
       -> AnswerPackageAggregator                     # 确定性聚合
  -> CanonicalAnswerSerializer / Chinese renderer
```

现有 QA 链路保持原状，不经过 `DrawingAssistantService`，产品服务也不反向调用 QA CLI、HTTP 或 MCP。

### 1.3 依赖方向

允许的依赖方向为：

```text
scripts/drawing_assistant.py
  -> drawing_assistant_factory.py
  -> drawing_assistant_service.py
  -> assistant_answer_generation.py
  -> assistant_models.py / assistant_evidence_fusion_models.py

drawing_assistant_service.py
  -> 01/02/03/05 service public APIs
  -> DrawingGraphToolFacade public recognition API
```

禁止的依赖包括：

- 答案生成、总编排或 CLI 直接导入 repository、Neo4j session/driver、Cypher 字符串或查询内部实现。
- 06 直接调用识别 provider、Qwen client、证据写回 port 或候选提升逻辑。
- 产品服务依赖 CLI、HTTP、MCP adapter 或 `DrawingGraphQAService`。
- 01—05 反向依赖 06/07。
- 文本生成器读取图谱、完整 payload、本地文件或环境凭据。

### 1.4 单意图执行时序

1. 服务校验请求只读授权和资源限制。
2. 01 生成 `QuestionUnderstandingResult`。
3. 若结果没有子请求且为 `clarification_required` 或 `unknown_or_unsupported`，不执行 02—05，直接调用 06 生成终止态答案；若仍携带多个子请求，则逐个判断和执行，不能因其中一个子请求需澄清而丢弃其他可回答子请求。
4. 02 执行只读检索。
5. 03 判断语义证据是否充分、是否需要识别。
6. 若允许且需要识别，按 `page_id` 分组调用 facade；每组调用固定 `write_back=false`。
7. 05 融合检索与识别结果；总编排不传可写 policy。
8. 06 依次构造 claim、citation、状态、machine answer、中文模板，并按需尝试受约束文本生成。
9. 答案一致性校验通过后返回 `AnswerPackage`。

### 1.5 多意图执行时序

顶层 `QuestionUnderstandingResult.subrequests` 非空时，不允许把顶层空 `required_evidence` 直接交给 02：

1. `SubrequestProjector` 将每个 `AssistantSubrequest` 投影为独立的 `QuestionUnderstandingResult`，保留父 `request_id`，把当前 `subrequest_id` 写入新增的可选字段，并在内部 `SubrequestExecutionContext` 中保存原始顺序。
2. 每个子请求独立执行 02—06；02/03/05 输出必须携带相同 `subrequest_id`。
3. MVP 按稳定的 `subrequests` 顺序串行执行。并发不属于本次范围，避免引入共享生命周期、输出乱序和 provider 限流问题。
4. `AnswerPackageAggregator` 按原始子请求顺序聚合 `Subanswer`、claim、citation、warning、unsupported、run ID 和 follow-up。
5. 聚合不得跨子请求合并语义不同的 claim；只允许按稳定 ID 去重完全相同的 citation 和 warning。

### 1.6 跨页识别

`DrawingGraphToolFacade.recognize_semantic_targets()` 当前要求一次调用内的目标属于同一页面，因此 07 必须：

- 先拒绝缺少 `page_id` 的必需识别目标，并转为结构化 warning/unsupported。
- 按 `page_id` 排序和分组。
- 每页调用一次 facade，并显式传 `write_back=false`。
- 保留每页的成功结果和失败记录；单页失败不丢弃其他页的结果。
- 所有必需识别均失败且没有可用语义 claim 时，答案状态为 `recognition_failed`；部分页面成功时为 `partial`。

---

## 2. 新增模块

为保持职责清晰且避免过度拆文件，MVP 新增以下模块。claim/citation 分离是因为二者规则、负向约束和测试维度不同；machine answer、canonical JSON 与一致性校验集中在答案生成模块的纯协作者中，不再额外拆成大量微型模块。

### 2.1 `src/drawing_graph/assistant_claim_builder.py`

新增 `ClaimBuilder`，职责是把 `QuestionUnderstandingResult + EvidenceBundle` 确定性投影为 `Claim[]`。

主要规则：

- 每个 `ClaimSupportAssessment` 最多产生一个主 claim；相同 capability、scope、statement 模板和支撑状态可合并，但必须合并全部 evidence ID。
- `supported` 生成正常 claim。
- `supported_with_qualifier` 生成带不可删除限定语的 claim。
- `conflicting` 只生成冲突说明或受限 claim，不选择 winner。
- `formal_review_required` 只能生成“候选/待复核”claim。
- `missing`、`stale_only`、`unsupported` 不生成工程事实 claim，进入 warning、unsupported 或 follow-up。
- 诊断 claim 可以没有工程 evidence，但必须绑定稳定 reason code，并明确其为运行状态。
- statement 使用按 `ClaimCapability + FactKind + ClaimStatus` 注册的确定性中文短句模板，不调用文本模型。
- claim ID 使用稳定摘要：`answer_contract_version + request_id + subrequest_id + capability + scope key + sorted evidence_ids + status`。摘要采用固定算法和固定编码，不使用时间戳或随机数。

### 2.2 `src/drawing_graph/assistant_citation_builder.py`

新增 `CitationBuilder`，从 claim 的 evidence IDs、`FusionEvidence`、lineage 和 provenance 构造最小引用。

主要规则：

- 每条非诊断 claim 至少关联一个 citation；否则答案校验失败，不允许发布该 claim。
- citation 必须包含 `citation_id`、`evidence_id` 和 `claim_ids`。
- 定位字段从现有 evidence refs/provenance 投影，只在存在时输出：project、drawing set、page、block、element、bbox、observation、interpretation、candidate group、recognition run、payload ref、rule version。
- 不复制完整 payload，不输出本地 `image_path`、数据库 URI、Cypher、密钥或内部 traceback。
- citation ID 基于合同版本、evidence ID 和公开定位字段生成稳定摘要。
- 稳定排序为：首次引用 claim 顺序 → fact kind 固定顺序 → page/block/element → evidence ID → citation ID。

### 2.3 `src/drawing_graph/assistant_answer_templates.py`

新增 `ChineseAnswerTemplateRenderer`，输入已经通过校验的答案 core，输出确定性中文文本。

默认章节顺序：

1. 结论。
2. 依据与引用标签。
3. 候选/冲突/限定语。
4. 缺失证据、识别失败与验证边界。
5. 后续动作。

渲染规则必须区分：

- `source_fact` / `derived_relation`：仅在支撑充分时使用确定性表述。
- `semantic_observation`：使用“图中观察到/识别到”。
- `semantic_interpretation`：使用“语义解释为”，不得写成来源事实。
- `candidate_relation`：使用“候选/可能/待复核”。
- `formal_relation`：仅正式事实可使用“已确认/正式关系”。
- `diagnostic`：明确为运行状态，不作为工程结论。

### 2.4 `src/drawing_graph/assistant_answer_text.py`

新增供应商无关的 `ConstrainedAnswerTextGenerator` port、请求/结果 DTO、fake 和 `ConstrainedTextValidator`。

MVP 默认不装配真实文本 provider；默认路径直接使用中文模板。显式注入生成器并启用策略时，流程为：

1. 先生成确定性模板。
2. 将脱敏后的 approved claims、不可删除 qualifiers、公开 citation 标签和允许章节列表传给生成器。
3. 生成器返回受约束 JSON，而不是无结构自由文本；结果至少包含 `sections`、`used_claim_ids`、`used_citation_ids`。
4. validator 检查 claim ID 集合完全一致、citation 只来自 allowlist、限定语未丢失、数字/业务 ID/实体词未超出 allowlist、长度与章节满足限制。
5. 超时、异常、无效 JSON、缺 claim、增 claim、越权 citation 或语义门禁失败均回退模板，并加入稳定 warning。

文本生成结果只替换 `text_answer`，无权修改 `machine_answer`、claim、citation、status、confidence 或 follow-up。

### 2.5 `src/drawing_graph/assistant_answer_generation.py`

新增 06 唯一入口 `AnswerGenerationService`，内部组合：

- `ClaimBuilder`
- `CitationBuilder`
- `AnswerStatusResolver`
- `MachineAnswerBuilder`
- `AnswerPackageValidator`
- `CanonicalAnswerSerializer`
- `ChineseAnswerTemplateRenderer`
- 可选 `ConstrainedAnswerTextGenerator`

服务顺序固定为：

```text
validate input
  -> build claims
  -> build citations
  -> resolve status
  -> build authoritative machine answer
  -> validate claim/citation/status consistency
  -> render deterministic Chinese template
  -> optional constrained generation + validation + fallback
  -> build AnswerPackage
  -> final consistency validation
```

`CanonicalAnswerSerializer` 复用 `qa_serialization.to_jsonable()` 的 JSON-safe 转换规则，但负责产品答案自己的字段顺序、集合排序和紧凑 UTF-8 输出；不会修改现有 QA envelope 语义。

### 2.6 `src/drawing_graph/drawing_assistant_service.py`

新增 07 只读总编排入口 `DrawingAssistantService`，内部协作者包括：

- `SubrequestProjector`
- `RecognitionTargetGrouper`
- `AnswerPackageAggregator`
- 01—06 服务实例

这些协作者先放在同一模块，避免为简单投影和排序额外创建模块；若后续职责或测试规模显著增长，再通过独立变更评审拆分。

服务不创建 driver，不读取环境变量，不直接实例化 provider，不持久化 trace，也不包含 CLI 参数解析。

### 2.7 `src/drawing_graph/drawing_assistant_factory.py`

新增无副作用 factory：

- 接收已构造的 `DrawingGraphToolFacade` 和可选文本生成 port。
- 装配 01—07 默认协作者。
- factory 调用本身不打开 Neo4j 连接、不读取密钥、不执行查询、不调用模型。
- 不把产品装配塞入现有 `tool_factory.py`，避免扩大工具层 factory 的职责和影响现有调用者。

### 2.8 `scripts/drawing_assistant.py`

新增产品级只读 CLI adapter，仅负责：

- 参数解析和 `AssistantRequest` 构造。
- 从运行环境加载既有 Neo4j/provider 配置。
- driver/facade 生命周期。
- 调用 `DrawingAssistantService.answer()`。
- JSON/中文输出、脱敏错误和退出码。

CLI 不包含问题路由、检索规划、识别分组、claim/citation 构造或文本生成规则。

---

## 3. 修改模块

### 3.1 `src/drawing_graph/assistant_models.py`

采用兼容性扩展，不新建第二套同名答案 DTO：

- 新增答案状态、claim 状态、文本渲染模式等稳定枚举。
- 新增 `MachineAnswer`、`Subanswer`、`AnswerGenerationRequest`、`AssistantExecutionPolicy` 等产品 DTO。
- 对 `Claim`、`Citation`、`AnswerPackage` 只新增带默认值的字段，保留现有构造方式。
- 对 `QuestionUnderstandingResult` 新增可选 `subrequest_id`，用于子请求投影；顶层结果保持 `None`。
- 仅新增 06/07 所需的稳定 reason code，不重命名既有枚举值。

不把 `machine_answer` 立即收紧为完全不兼容的类型。公共注解可接受 `MachineAnswer | Mapping | None`，但 06 自身只产生 `MachineAnswer`，以避免破坏当前占位 DTO 的使用者。

### 3.2 02 通用检索最小接缝修正

影响：

- `assistant_retrieval_planner.py`
- `assistant_retrieval_projection.py`
- 对应合同/服务测试

只做 `subrequest_id` 透传：

- `QuestionUnderstandingResult.subrequest_id -> RetrievalPlan.subrequest_id`
- `RetrievalPlan.subrequest_id -> RetrievalBundle.subrequest_id`

不改变检索白名单、facade 方法、证据分层、limit 或错误策略。

### 3.3 03 语义缺口决策最小接缝修正

影响：

- `assistant_semantic_gap_decision.py`
- 对应合同测试

只增加 projected `QuestionUnderstandingResult.subrequest_id` 与 `RetrievalBundle.subrequest_id` 的一致性校验，并继续把该值投影到 `SemanticGapDecision.subrequest_id`。不改变缺口评估、缓存、目标规划、预算或识别决策规则。

### 3.4 05 证据融合最小接缝修正

影响：

- `assistant_evidence_fusion.py`
- 必要时 `assistant_evidence_fusion_models.py`
- 05 自身测试

06 不应猜测冲突 winner 或重建 provenance，因此 05 在交付给 06 前必须满足：

- `EvidenceBundle.subrequest_id` 从检索/决策上下文透传。
- `ClaimSupportAssessment` 和 `AnswerabilityResult` 在单个 projected 子请求中携带同一 `subrequest_id`。
- `accepted_evidence` 只含允许支撑当前答案的证据。
- `conflicting_evidence` 只含冲突成员，不与 accepted 全量重复。
- `provenance`、`overall_confidence`、`unsupported_claims` 和 warnings 按现有 05 规则填充，不保留为无意义默认值。
- `write_back_result=not_requested` 仅是运行信息，不能被 06 表述为工程事实。

这属于 05 合同闭合，不在 06 内复制冲突检测、fact kind 判断或 lineage 规则。

### 3.5 复用但原则上不修改的模块

以下模块通过现有 public API 复用；除非实施阶段出现被合同测试证明的必要接缝，否则不修改：

- 01 `QuestionUnderstandingService` 及其规则、scope、澄清模块。
- 03 `SemanticGapDecisionService` 除上述 ID 一致性校验外的缺口评估与识别策略。
- 04 `DrawingGraphToolFacade` 和受控识别执行链。
- `qa_serialization.py` 的 `to_jsonable()` 和错误脱敏能力。
- `tool_factory.py`、现有 QA service、QA CLI、HTTP、MCP。
- repository、Neo4j port、导入、关系增强、候选审核和写回模块。

### 3.6 文档模块

代码实施并验证后才同步 `README.md`、`architecture.md`、`Module.md` 和对应 change 文档。当前 design 阶段不把文档声明当作实现完成证据。

---

## 4. 数据模型变化

### 4.1 持久化模型

本需求不改变 Neo4j 节点、关系、索引、约束、payload schema 或迁移脚本；不新增答案、trace、反馈或文本生成结果的持久化。

所有变化均为进程内产品 DTO 和公开 JSON 合同。

### 4.2 新增枚举

`AnswerStatus`：

| 值 | 含义 |
|---|---|
| `answered` | 所有必需 claim 均得到允许等级的证据支撑 |
| `partial` | 至少有一个有效工程 claim，但存在必需缺失、冲突、子请求失败或页级失败 |
| `clarification_required` | 需要用户补充 scope/歧义信息，未执行不必要下游调用 |
| `unsupported` | 当前问题类型或证据模板不支持，且没有可发布工程 claim |
| `recognition_failed` | 必需语义识别失败且没有其他可发布语义 claim |

`ClaimStatus`：

| 值 | 允许语义 |
|---|---|
| `supported` | 正常支撑 |
| `qualified` | 有支撑但必须保留限定语 |
| `conflicting` | 存在冲突，不选 winner |
| `formal_review_required` | 只能作为候选/待复核 |
| `diagnostic` | 运行状态，不是工程事实 |

claim 类型不重复定义另一套事实层枚举：优先复用 05 的 `ClaimCapability` 值；事实等级继续由现有 `FactKind` 表达。

### 4.3 `Claim` 兼容性扩展

保留现有字段，新增可选/默认字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `subrequest_id` | `str | None` | 多意图归属 |
| `reason_codes` | `tuple[str, ...]` | 诊断或受限状态原因 |
| `citation_ids` | `tuple[str, ...]` | claim 到公开 citation 的稳定关联 |

约束：

- 非诊断 claim：`evidence_ids` 和 `citation_ids` 均不能为空。
- `formal_review_required` 至少包含候选/待复核限定语。
- `conflicting` 不得使用正式确定性 statement 模板。
- `confidence` 只能来自 05 聚合结果，不由文本模型修改。

### 4.4 `Citation` 兼容性扩展

新增字段均提供默认值：

| 字段 | 类型 | 说明 |
|---|---|---|
| `citation_id` | `str | None` | 新答案中的稳定 citation ID；旧占位构造仍可为空 |
| `evidence_id` | `str | None` | 回指 05 证据 |
| `claim_ids` | `tuple[str, ...]` | 反向关联 claim |
| `project_id` | `str | None` | 最小业务定位 |
| `drawing_set_id` | `str | None` | 最小业务定位 |

现有 page/block/element/bbox/observation/interpretation/candidate group/run/payload/rule 字段继续复用。06 生成的新 citation 必须有 `citation_id`、`evidence_id` 和至少一个 `claim_id`；旧调用者的兼容性占位对象不因此失效。

### 4.5 `Subanswer`

用于多意图的稳定聚合：

| 字段 | 类型 |
|---|---|
| `subrequest_id` | `str` |
| `question_type` | `str` |
| `scope` | `AssistantScope | None` |
| `status` | `AnswerStatus` |
| `claim_ids` | `tuple[str, ...]` |
| `citation_ids` | `tuple[str, ...]` |
| `warnings` | `tuple[object, ...]` |
| `unsupported_parts` | `tuple[str, ...]` |

### 4.6 `MachineAnswer`

权威机器答案使用固定字段顺序：

```text
answer_contract_version
request_id
question_type
scope
status
subanswers
claims
citations
warnings
unsupported_parts
recognition_run_ids
follow_up_actions
reason_codes
```

`answer_contract_version` 固定为 `drawing-assistant-answer-v1`。JSON 不输出未声明的动态字段；`None` 的处理由合同统一规定，MVP 建议保留顶层稳定字段、对 citation 的不存在定位字段省略，避免产生含义不清的空引用。

### 4.7 `AnswerPackage` 兼容性扩展

新增：

- `answer_contract_version`
- `subanswers`
- `reason_codes`
- `render_mode`：`template` 或 `constrained_text`

`machine_answer` 是权威投影；顶层 `claims/citations/status` 是便于现有消费者访问的同源字段。validator 必须证明两者一致，禁止两套数据分别构造。

### 4.8 `AnswerGenerationRequest`

```text
assistant_request: AssistantRequest
question_result: QuestionUnderstandingResult
evidence_bundle: EvidenceBundle | None
subrequest_id: str | None
stage_warnings: tuple[object, ...]
recognition_failures: tuple[RecognitionFailure, ...]
```

`evidence_bundle=None` 仅允许用于 `clarification_required` 或 `unsupported` 终止态；其他状态缺少 bundle 视为合同错误。

`RecognitionFailure` 是只读的阶段记录，至少包含 `page_id`、目标 IDs、稳定 reason code 和已脱敏 message；它不保存 traceback、provider 原始响应或凭据。

`AnswerGenerationPolicy` 是 06 的资源/表现策略，至少包含 `enable_constrained_text`、最大 claim/citation 数、最大文本长度和文本生成超时；它不包含任何写回、事实等级或状态覆写字段。

### 4.9 稳定排序与 canonical JSON

- scope 字段按模型声明顺序。
- subanswer 按 01 输出顺序。
- claim 按 subrequest 顺序、capability 固定顺序、scope key、claim ID。
- citation 按首次引用 claim、fact kind、page/block/element、evidence ID、citation ID。
- warning、unsupported、run ID、follow-up 和 reason code 先去重，再按定义的稳定业务键排序；不按对象内存地址或异常文本排序。
- JSON 使用 UTF-8、`ensure_ascii=false`、固定 separators、禁止 NaN/Infinity，不含时间戳和随机排序因素。
- 相同输入的 byte-level 测试必须比较完整字符串，而不只比较反序列化对象。

---

## 5. API 设计

### 5.1 06 服务 API

```text
AnswerGenerationService.generate(
    request: AnswerGenerationRequest,
    policy: AnswerGenerationPolicy | None = None,
) -> AnswerPackage
```

`AnswerGenerationPolicy` 只控制表现层和资源限制，例如：是否启用受约束文本、最大 claim/citation/文本长度；它不包含写回选项，也不能改变事实等级或答案状态规则。

### 5.2 Claim/Citation API

```text
ClaimBuilder.build(
    question_result: QuestionUnderstandingResult,
    evidence_bundle: EvidenceBundle,
) -> tuple[Claim, ...]

CitationBuilder.build(
    claims: tuple[Claim, ...],
    evidence_bundle: EvidenceBundle,
) -> tuple[Citation, ...]
```

builder 是纯函数式协作者：不访问 facade、repository、环境变量或模型。

### 5.3 模板与受约束文本 API

```text
ChineseAnswerTemplateRenderer.render(
    answer_core: MachineAnswer,
) -> str

ConstrainedAnswerTextGenerator.generate(
    request: ConstrainedTextRequest,
) -> ConstrainedTextResult

ConstrainedTextValidator.validate(
    request: ConstrainedTextRequest,
    result: ConstrainedTextResult,
) -> ValidatedTextResult
```

生成器是 port；fake 用于单元/fake runtime 测试。默认 factory 的生成器为 `None`，不会发生外部文本模型调用。

### 5.4 07 服务 API

```text
DrawingAssistantService.answer(
    request: AssistantRequest,
    policy: AssistantExecutionPolicy | None = None,
) -> AnswerPackage
```

`AssistantExecutionPolicy` 包含：

- 现有 `RetrievalPolicy`。
- 现有 `RecognitionPolicy`。
- `enable_constrained_text`，默认 `false`。
- `max_subrequests`、`max_page_groups`、`max_claims`、`max_citations` 等资源上限。

它不包含写回授权。`AssistantRequest.allow_recognition=false` 优先于 recognition policy；不得由 policy 重新开启请求已禁止的识别。

### 5.5 Factory API

```text
create_drawing_assistant_service(
    facade: DrawingGraphToolFacade,
    text_generator: ConstrainedAnswerTextGenerator | None = None,
    ...optional collaborators
) -> DrawingAssistantService
```

Neo4j 生命周期仍由 adapter 管理：CLI 创建 driver/facade，传给 factory，调用完成后关闭。factory 不接收裸 repository 或 session。

### 5.6 CLI API

建议命令：

```text
python scripts/drawing_assistant.py \
  --question <自然语言问题> \
  [--request-id <稳定请求ID>] \
  [--project-id <ID>] \
  [--drawing-set-id <ID>] \
  [--page-id <ID>] \
  [--block-id <ID>] \
  [--element-id <ID>] \
  [--cross-section-id <ID>] \
  [--allow-recognition | --no-recognition] \
  [--text-generation] \
  [--output json | text]
```

约束：

- 不提供 `--write-back` 或任何同义参数。
- 默认 `--output json`；JSON stdout 只输出一个成功或失败 envelope。
- `--output text` 只输出 `text_answer`；warning 可进入结构化答案，不混入 stdout 调试信息。
- API key、Neo4j URI/用户名/密码和 provider 配置只从环境/既有配置读取，不作为命令参数或答案字段。
- `--text-generation` 只在 factory 显式装配生成器时生效；未装配时模板回退并给出稳定 warning，不隐式访问网络。

### 5.7 CLI 输出与退出码

成功 envelope：

```json
{
  "ok": true,
  "data": {
    "answer_contract_version": "drawing-assistant-answer-v1",
    "request_id": "...",
    "status": "answered",
    "machine_answer": {},
    "text_answer": "..."
  }
}
```

失败 envelope：

```json
{
  "ok": false,
  "error": {
    "code": "invalid_request",
    "message": "已脱敏的稳定错误信息"
  }
}
```

退出码：

| 退出码 | 含义 |
|---|---|
| `0` | 得到合法 `AnswerPackage`，包括 partial/clarification/unsupported/recognition_failed 业务状态 |
| `1` | 运行时基础设施或必需阶段完全失败，未得到合法答案包 |
| `2` | CLI 参数、配置、合同或只读授权错误 |

业务状态与进程失败分离，避免把“需要澄清”误判成基础设施错误。

---

## 6. 异常处理

### 6.1 异常分类

| 分类 | 示例 | 服务行为 | CLI 行为 |
|---|---|---|---|
| 输入/授权错误 | 空问题、非法 scope、`allow_write_back=true` | 立即抛出稳定领域异常，不调用下游 | 脱敏失败 envelope，退出 2 |
| 合同一致性错误 | request/subrequest ID 不一致、非诊断 claim 无 citation | fail closed，不输出猜测答案 | 脱敏失败 envelope，退出 2 或 1，按来源区分 |
| 业务终止态 | 澄清、unsupported | 生成合法终止态 `AnswerPackage` | 退出 0 |
| 必需检索完全失败 | 必需 facade 调用全部 error，无法形成答案 | 抛 `AssistantExecutionError(retrieval_failed)` | 退出 1 |
| 可选检索失败 | 可选步骤失败但有有效 claim | `partial` + warning | 退出 0 |
| 识别失败 | 单页失败 | 保留其他页结果，`partial` | 退出 0 |
| 识别完全失败 | 必需识别全部失败且无语义 claim | `recognition_failed` | 退出 0 |
| 05 冲突/缺失 | 有冲突或不充分证据 | 不选 winner，`partial/unsupported` | 退出 0 |
| 文本生成失败 | 超时、provider 不可用、非法输出 | 回退中文模板，不改变机器状态 | 退出 0 |
| adapter 初始化失败 | Neo4j 配置/driver 创建失败 | 服务未调用 | 脱敏失败 envelope，退出 1/2 |

### 6.2 Fail-closed 条件

以下情况禁止“尽量生成一个看起来合理的答案”：

- 非诊断 claim 没有 accepted evidence。
- claim evidence ID 无法在 `EvidenceBundle` 中解析。
- citation 无法回指 evidence，或 claim-citation 双向关联不一致。
- candidate/interpretation 被渲染为 formal/source fact。
- request、subrequest、retrieval、decision、fusion 的 ID 不一致。
- 05 accepted/conflicting 分桶语义不明确。
- canonical serializer 遇到非有限数字、不可序列化对象或未知动态字段。

### 6.3 Partial 聚合规则

整体状态按固定优先级推导，不按异常消息字符串判断：

1. 入口需澄清且没有已完成子请求：`clarification_required`。
2. 所有子请求 unsupported 且无工程 claim：`unsupported`。
3. 所有必需识别失败且无可用语义 claim：`recognition_failed`。
4. 任一子请求 partial/failed/unsupported/clarification，或存在必需缺失/冲突，但至少有一个有效工程 claim：`partial`。
5. 所有必需子请求均 answered：`answered`。

### 6.4 错误脱敏

- 复用现有稳定错误 envelope 和 `sanitize_error_message()` 思路。
- stdout 不输出 traceback、Cypher、URI、用户名、密码、API key、本地绝对路径或完整 provider 响应。
- 调试信息只进入 stderr；STDIO 路径不使用会直接泄露堆栈的异常日志方式。
- provider 错误映射为稳定 reason code；原始响应不进入 `AnswerPackage`。

---

## 7. 安全方案

### 7.1 只读强制

采用三层约束：

1. **请求层：** `DrawingAssistantService.answer()` 首行校验 `allow_write_back`，为 true 立即拒绝。
2. **编排层：** 04 始终显式 `write_back=false`；05 始终 `write_back_policy=None`；03 的 `write_back_recommendation` 仅作为诊断数据，永不转换为授权。
3. **adapter 层：** CLI 不暴露 write-back 参数；静态测试禁止导入写回 port、repository 和 Cypher 内部实现。

“候选提升建议”“用户问题中要求写回”“配置默认值”均不构成授权。

### 7.2 事实等级安全

- source fact、derived relation、semantic observation、semantic interpretation、candidate relation、formal relation、diagnostic 全程保留，不折叠为单一“事实”。
- claim builder 以 `FactKind + ClaimCapability + ClaimSupportStatus` 三重门控 statement 和 status。
- candidate 和 interpretation 的限定语是结构化字段，renderer 和受约束文本 validator 都不得删除。
- 冲突证据不选择 winner；过期/缺失/unsupported 不生成工程事实 claim。

### 7.3 Claim/Citation 完整性

- 非诊断 claim 必须同时有 evidence ID 和 citation ID。
- citation 必须回指当前 bundle 中的 evidence，且 claim/citation 双向集合一致。
- stable ID 摘要输入采用规范化字段；任何字段顺序变化不应改变语义相同对象的 ID。
- 最终 `AnswerPackageValidator` 在 adapter 输出前再次校验。

### 7.4 文本生成隔离

- 模型输入使用 allowlist，仅含 approved claim statement/status/qualifier、公开 citation 标签和章节结构。
- 不发送完整 evidence payload、图像路径、Neo4j 配置、provider 密钥、内部 warning 对象或 traceback。
- 图纸 OCR/识别文字视为不可信数据，不允许其内容改变系统指令、schema 或 allowlist；提示词注入文本只作为 claim 引用的数据片段处理。
- 输出为受约束 JSON，并进行 ID、数字、实体、限定语、章节和长度校验。
- 模型不可用或校验不通过时模板回退；不重试到突破资源上限。

### 7.5 数据最小化

- citation 只输出当前 claim 所需的最小定位字段。
- 默认不公开 `image_path`、本地绝对路径和完整 payload。
- `payload_ref` 只是稳定引用，不自动解引用到答案。
- JSON 中不包含凭据、驱动配置、底层查询文本或 provider 原始响应。

### 7.6 资源限制

`AssistantExecutionPolicy` 和答案生成 policy 需提供可测试的正整数上限：

- 最大 subrequest 数。
- 最大 page group 和每页 recognition target 数。
- 最大 accepted/conflicting evidence、claim、citation、warning 数。
- 最大文本生成输入/输出长度和单次超时。

超过上限时采用稳定的拒绝或截断策略，并输出 `result_truncated` 等 reason code；不得静默丢弃必需 claim 或引用。

### 7.7 供应链与配置

- MVP 不新增默认真实文本模型依赖。
- Neo4j、识别 provider 和文本 provider 凭据只通过既有环境配置读取。
- factory 无副作用，便于用 fake facade/fake generator 验证只读边界。
- 真实 Neo4j、DashScope 或文本 provider 验证必须单独报告，不能用 fake/skip 结果替代。

---

## 8. 验证设计

本节用于约束后续实施计划，不代表当前已经运行测试。

### 8.1 06 单元与合同测试

- 每种 `ClaimSupportStatus` 到 claim/status/warning 的映射。
- 每种 fact kind 的中文措辞，特别是 candidate/interpretation 不得提升为 formal。
- 非诊断 claim 无 evidence/citation 时 fail closed。
- citation 最小字段、双向关联、去重和稳定排序。
- 同输入、同 `request_id`、同合同版本的 byte-identical JSON。
- 中文模板不引入 machine answer 外的新 claim、数字或实体。
- fake 文本生成合法输出被接受；缺 claim、增 claim、越权 citation、丢限定语、超时和异常全部回退模板。

### 8.2 05 接缝测试

- accepted 与 conflicting 分桶不再无条件全量重复。
- subrequest ID、provenance、overall confidence、unsupported 和 warnings 正确投影。
- 05 自己完成冲突/lineage/fact-kind 规则，06 不重新实现。

### 8.3 07 总编排测试

- clarification/unsupported 早停且不调用 02—05。
- 单意图 01—06 顺序和参数正确。
- 多意图逐子请求执行并保持稳定顺序。
- 跨页目标按 page 分组，每次 facade 调用均 `write_back=false`。
- 单页失败为 partial；全部必需识别失败且无语义 claim 为 recognition_failed。
- `allow_recognition=false` 时不调用识别。
- `allow_write_back=true` 在任何下游调用前被拒绝。
- 静态边界禁止 repository/driver/Cypher/写回内部实现导入。

### 8.4 Factory 与 CLI 测试

- factory 创建时不打开连接、不查询、不调用 provider。
- CLI 参数到 `AssistantRequest`/policy 的映射。
- CLI 不存在 write-back 参数。
- stdout 只有一个 JSON envelope 或纯文本答案，stderr 与退出码符合合同。
- 错误消息不包含 URI、密钥、绝对路径、Cypher 或 traceback。
- fake facade 的离线端到端覆盖 answered、partial、clarification、unsupported、recognition_failed。

### 8.5 分层验证声明

后续实施必须分别报告：

1. 合同/单元测试。
2. fake runtime 端到端。
3. CLI smoke。
4. live Neo4j。
5. live DashScope/真实文本 provider。

未运行的层级明确写“未验证”；skipped 不等于通过，历史回归数字也不等于本需求已验收。

---

## 9. 兼容性与非重构清单

### 9.1 必须保持兼容

- 现有 `DrawingGraphQAService` 六类 QA 行为和 DTO。
- 现有 QA CLI、HTTP 和 MCP 的入口、输出和错误语义。
- `DrawingGraphToolFacade` 的公开只读方法和识别入口。
- 01—05 现有 DTO 的构造方式；新增字段使用默认值。
- 现有图谱事实层、候选审核和写回授权边界。

### 9.2 明确不做

- 不把所有产品 DTO 搬到新的 contracts 包。
- 不把 `tool_factory.py` 改造成全项目依赖注入容器。
- 不统一或重命名 01—05 的所有枚举、warning、reason code。
- 不将 QA/HTTP/MCP 改为调用产品总编排。
- 不新增产品 HTTP/MCP/Web API。
- 不增加答案持久化、反馈写回、候选提升或 Neo4j schema。
- 不为未来并发、流式响应、多轮记忆或多语言预先重构。
- 不修改与 02 subrequest 透传、05 输出闭合、06/07/CLI 无关的导入、关系增强、OCR 和审核模块。

---

## 10. 推荐实施顺序与评审门

1. 先闭合公共答案合同和 02/05 必需接缝，并各自独立验证。
2. 实现纯确定性的 claim/citation、machine answer、canonical JSON 和中文模板，独立验收 06。
3. 增加可选受约束文本 port、fake、validator 和模板回退，不接默认真实 provider。
4. 实现 `DrawingAssistantService` 的早停、子请求 fan-out、page grouping、partial 聚合和只读门禁。
5. 实现无副作用 factory 与独立产品 CLI，完成 fake 端到端。
6. 最后同步架构/模块/README，并分别记录 offline 与 live 验证边界。

本 design 通过评审后，下一步才应生成实施计划。实施任务应按单能力拆分，每项具备一个明确目标、指定修改文件、可独立测试和完成标准；在用户批准实施计划前不进入代码实现。
