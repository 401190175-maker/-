# 答案生成与只读总编排 MVP——功能分析报告

**文档状态：** 待评审的需求分析与推荐方案，不代表实施授权  
**日期：** 2026-08-14  
**分析范围：** claim/citation、确定性 JSON、中文模板、受约束文本生成、`DrawingAssistantService`、只读 CLI 端到端  
**明确不包含：** 代码实现、产品级 HTTP/MCP/Web UI、反馈写回、候选提升、Neo4j schema 变更、OCR、默认真实云模型调用

## 1. 执行摘要

当前架构**支持该需求，且已经具备大部分上游基础，但不支持“直接拼接即可完成”**。

已落地的 01—05 能力已经形成：

```text
AssistantRequest
  -> QuestionUnderstandingService
  -> GraphRetrievalService
  -> SemanticGapDecisionService
  -> [必要时] DrawingGraphToolFacade.recognize_semantic_targets()
  -> EvidenceFusionService
  -> EvidenceBundle
```

公共合同中也已经预留 `Claim`、`Citation`、`AnswerPackage`、`TraceRecord` 与 `FeedbackEvent`。因此，不需要重建问题理解、检索、语义缺口判断、多模态执行或证据融合，也不需要改变 Neo4j 图谱模型。

真正缺失的是三段产品能力：

1. **06 答案生成闭环**：把 `EvidenceBundle` 确定性转换为 claim、citation、状态、机器答案和中文文本。
2. **只读总编排**：由 `DrawingAssistantService` 统一串联 01—06，处理澄清、unsupported、识别失败、跨页识别、多意图和部分成功。
3. **产品级 CLI**：只接收自然语言问题与 scope/策略参数，通过总编排服务输出权威 JSON 或中文文本。

推荐采用**确定性内核 + 双渲染器 + 可选受约束文本生成**：claim/citation/状态/JSON 全部由确定性代码生成；中文模板为默认且始终可用；文本模型只能改写已批准 claim 的表达，不能新增 claim、citation、ID、数字或事实等级，失败时回退模板。

## 2. 分析依据与当前状态

### 2.1 已读取的权威文档

- `architecture.md`
- `Module.md`（用户所述 `modules.md` 在当前仓库中的实际文件名）
- `changes/产品实现层/00-product-closure-blueprint.md`
- `changes/产品实现层/01-question-understanding.md`
- `changes/产品实现层/02-graph-retrieval.md`
- `changes/产品实现层/03-semantic-gap-decision.md`
- `changes/产品实现层/04-multimodal-recognition.md`
- `changes/产品实现层/05-evidence-fusion-and-cache.md`
- `changes/产品实现层/06-answer-generation.md`
- `changes/产品实现层/07-traceability-and-feedback.md`

同时核对了当前相关源码、测试文件、`README.md`、项目输出契约和验证规则。当前工作区含有未提交的 05 模块及文档修改；本报告将这些内容视为“当前工作区状态”，不将其冒充已提交基线。

### 2.2 能力状态矩阵

| 能力 | 当前状态 | 对本需求的意义 |
|---|---|---|
| 公共 DTO | 已有 | 已预留 `Claim`、`Citation`、`AnswerPackage`，但约束仍偏宽松，需要补齐稳定枚举、引用关联和版本字段 |
| 01 问题理解 | 已实现 | 可将自然语言问题变为 `QuestionUnderstandingResult` |
| 02 通用检索 | 已实现 | 可经 facade 白名单只读获取 `RetrievalBundle` |
| 03 语义缺口决策 | 已实现 | 可决定复用、识别、澄清或 unsupported |
| 04 多模态执行 | 已实现、离线验证 | 可按页执行最小目标识别；默认 fake，live DashScope 未由本分析验证 |
| 05 证据融合 | 当前工作区已实现、离线验证记录存在 | 可产生 claim 支撑、冲突、answerability、缓存与 provenance |
| 06 答案生成 | 未实现 | 本需求核心新增能力 |
| 07 追溯与反馈 | 仅公共 DTO 预留 | MVP 可返回请求内 trace 摘要，但不应实现持久化反馈闭环 |
| `DrawingAssistantService` | 未实现 | 本需求核心新增能力 |
| 产品级 CLI | 未实现 | 本需求核心新增 adapter |
| 现有 QA CLI/HTTP/MCP | 已实现 | 保持兼容，不应改造成产品总编排入口 |

## 3. 关键假设与范围边界

### 3.1 “只读”的定义

本报告将“只读总编排”定义为：

- `AssistantRequest.allow_write_back` 必须为 `false`；CLI 不提供将其设为 `true` 的参数。
- 所有 facade 查询固定只读。
- 临时多模态识别可以在 `allow_recognition=true` 且策略允许时执行，但必须调用 `write_back=false`。
- 不写 Neo4j、图谱外持久化 run log、payload store、持久化缓存、反馈存储或正式关系。
- 临时 `recognition_run_id` 只用于本次回答关联，不宣称之后可查询。

因此，“只读”约束的是**持久化副作用**，并不自动禁止外部模型调用。外部模型调用仍受显式识别授权、预算、时延和 provider 配置控制。

### 3.2 MVP 范围

MVP 包含：

- 单意图与可安全拆分的多意图问题。
- 01—06 的同步只读编排。
- 识别目标按页面分组、逐组执行、部分失败保留。
- claim/citation、确定性 JSON、中文模板。
- 可选受约束文本生成器及模板回退。
- 产品级只读 CLI 的 fake/离线端到端验收。

MVP 不包含：

- 07 的反馈状态机、反馈 API、持久化 `TraceRecord`。
- 产品级 HTTP/MCP/Web UI。
- 自动写回、缓存提交、候选审核或 formal 提升。
- 异步队列、流式输出、跨请求会话存储。
- 以 live DashScope 或 live Neo4j 作为 MVP 离线验收的前置条件。

## 4. 问题 1：当前架构是否支持？

### 4.1 支持点

当前依赖方向已经为该需求预留了正确位置：

```text
Product CLI
  -> DrawingAssistantService
       -> 01 QuestionUnderstandingService
       -> 02 GraphRetrievalService
       -> 03 SemanticGapDecisionService
       -> 04 facade 受控识别入口
       -> 05 EvidenceFusionService
       -> 06 AnswerGenerationService
  -> DrawingGraphToolFacade
  -> ports / services / repositories / Neo4j / optional provider
```

新增总编排位于 adapter 内侧、facade 外侧，不需要让 adapter 访问 Cypher、repository 或业务规则，也不需要改动现有 `DrawingGraphQAService`。

现有数据契约已经提供关键输入：

- `EvidenceBundle.accepted_evidence`
- `EvidenceBundle.conflicts`
- `EvidenceBundle.claim_support`
- `EvidenceBundle.answerability`
- `EvidenceBundle.provenance`
- `EvidenceBundle.reason_codes`、`warnings`、`cache_summary`

这些信息足以构造受证据约束的 claim、引用、状态和后续动作。

### 4.2 不足点

当前架构存在以下接缝，必须由新模块显式解决：

1. `Claim`、`Citation`、`AnswerPackage` 目前主要是占位 DTO，部分字段使用自由字符串，缺少严格状态枚举、claim 与 citation 的稳定关联、answer contract version 和机器答案 Schema。
2. 05 的 `ClaimSupportAssessment` 只说明某项证据需求是否得到支撑，并不直接生成面向用户的 claim statement。
3. `GraphRetrievalService`、03 和 05 的主路径主要消费顶层 `required_evidence`；多意图结果把证据需求放在各 `subrequest` 中，不能把整个多意图结果直接一次性传入现有单请求链路。
4. `DrawingGraphToolFacade.recognize_semantic_targets()` 要求一次调用内的全部目标属于同一页面；总编排必须先按 `page_id` 稳定分组。
5. 现有 `qa_serialization.to_jsonable()` 可以复用递归 DTO 转换，但它本身不负责字段白名单、稳定集合排序、Schema 版本和答案语义一致性。
6. 当前没有统一的产品级异常映射、阶段事件、降级状态和 CLI 生命周期装配。

### 4.3 结论

结论为：**架构方向支持，01—05 能力可复用，06/总编排/CLI 需要新增；现有 DTO 需要兼容性加固，且必须补一个明确的“05 → 06 投影层”。**

## 5. 问题 2：需要新增哪些模块？

以下为推荐的职责拆分。文件名是分析建议，最终以评审后的设计和实施计划为准。

### 5.1 必需模块

| 建议模块 | 单一职责 | 主要输入/输出 |
|---|---|---|
| `assistant_answer_contracts.py` 或对 `assistant_models.py` 的兼容性扩展 | 补齐答案状态、claim 状态/类型、citation ID、claim-citation 关联、answer contract version、确定性机器答案 DTO | 公共枚举与 DTO |
| `assistant_claim_builder.py` | 按 `required_evidence + claim_support + accepted_evidence + conflicts` 确定性生成 claim；拒绝无证据的非诊断 claim | `QuestionUnderstandingResult + EvidenceBundle -> Claim[]` |
| `assistant_citation_builder.py` | 从 evidence refs/provenance 生成最小引用，去重、稳定排序并建立 claim 关联 | `Claim[] + EvidenceBundle -> Citation[]` |
| `assistant_machine_answer.py` | 生成权威机器答案对象；固定字段顺序语义、集合排序、状态、warning、unsupported、follow-up | `AnswerDraft -> machine_answer` |
| `assistant_answer_templates.py` | 按 fact kind、claim status、qualifier 和整体状态渲染简短中文 | `AnswerPackage core -> text_answer` |
| `assistant_answer_text.py` | 定义受约束文本生成 port、fake、输出校验和模板回退；不得访问图谱或新增 claim | approved claims/citations -> 可选文本 |
| `assistant_answer_generation.py` | 06 唯一编排入口：claim -> citation -> 状态 -> machine JSON -> 中文文本 -> 一致性校验 | `AssistantRequest + QuestionUnderstandingResult + EvidenceBundle -> AnswerPackage` |
| `drawing_assistant_service.py` | 只读总编排；负责早停、按子请求执行、跨页识别分组、部分失败聚合和阶段错误映射 | `AssistantRequest -> AnswerPackage` |
| `drawing_assistant_factory.py` | 无副作用装配 01—06；driver/provider 生命周期仍由 adapter 管理 | facade/config -> service |
| `scripts/drawing_assistant.py` | 产品级只读 CLI：参数、配置、driver 生命周期、输出和退出码 | CLI -> JSON/中文 |

### 5.2 建议但可并入其他模块的辅助模块

| 建议模块 | 用途 |
|---|---|
| `assistant_answer_validation.py` | 集中检查 claim-evidence、citation、JSON-text 一致性、敏感字段与 candidate/formal 边界 |
| `assistant_orchestration_models.py` | 阶段事件、子请求执行结果、降级诊断；避免把总编排内部状态塞进公共答案 DTO |
| `assistant_subrequest_projection.py` | 把多意图子请求投影为 02—05 可消费的单子请求上下文，再稳定聚合 |

为控制 MVP 规模，前三个答案构造模块可以先作为 `assistant_answer_generation.py` 的内部协作者；但总编排、答案生成、文本 port、factory 和 CLI 不建议合并成一个大文件。

## 6. 问题 3：影响哪些已有模块？

### 6.1 需要修改或兼容性扩展

| 已有模块 | 影响 | 原则 |
|---|---|---|
| `assistant_models.py` | 补齐现有 `Claim`、`Citation`、`AnswerPackage` 的稳定合同，或兼容性 re-export 新合同 | 只做向后兼容的增量；避免破坏 01—05 DTO |
| `assistant_evidence_fusion_models.py` | 06 消费其稳定输出；如发现 accepted/conflicting 分桶语义不足，应先在 05 修正并独立验证 | 06 不自行重解释冲突 |
| `assistant_question_understanding.py` | 总编排消费其 early return 与 subrequests | 不让其访问 facade 或生成答案 |
| `assistant_retrieval_service.py` | 按单子请求调用 | 保持只读、白名单 facade 调用 |
| `assistant_semantic_gap_decision.py` | 总编排消费 selected/deferred targets 与原因码 | 不扩大识别或写回授权 |
| `tool_facade.py` | 复用 `recognize_semantic_targets(..., write_back=False)` | 不增加 adapter 侧底层访问 |
| `assistant_evidence_fusion.py` | 由总编排构造 `EvidenceFusionRequest`；只读 MVP 不提供写回 policy | `write_back_result=not_requested` |
| `qa_serialization.py` | 可复用 DTO 到 JSON-safe 值的基础转换 | 产品答案的 canonical 规则放在产品层，不把 QA 序列化器变成业务生成器 |
| `tool_factory.py` | 可复用 facade 与 03 工厂；新增产品 service factory 时应保持 import 无副作用 | 工厂不创建 driver、不主动连库 |
| `README.md`、`architecture.md`、`Module.md` | 实施完成后同步当前能力、CLI 和验证边界 | 本分析阶段不修改 |

### 6.2 必须保持不变

- `DrawingGraphQAService` 及现有 QA CLI/HTTP/MCP 行为保持兼容。
- `DrawingGraphToolFacade` 仍是所有图谱与语义执行能力的唯一应用入口。
- `RelationRepository`、`CandidateReviewService`、schema 和来源事实模型不因答案生成改变。
- `candidate_relation` 永不由 06 或总编排提升为 `formal_relation`。
- `RecognitionRun` 与 `RecognitionAttempt` 仍在图谱外；临时 dry-run ID 不冒充持久化记录。

## 7. 问题 4：技术方案有哪些？

### 7.1 方案 A：纯确定性模板

流程：确定性构造 claim/citation/状态/JSON，并用固定中文模板渲染，不接文本模型。

```text
EvidenceBundle
  -> deterministic claims/citations
  -> canonical machine answer
  -> Chinese template
```

适合最小、最高可控的首版。

### 7.2 方案 B：混合式确定性内核 + 受约束文本生成（推荐）

流程：机器答案和 claim/citation 由确定性代码生成；中文模板始终先生成；若启用文本生成器，则只对已批准 claim 做受约束表达，校验失败立即回退模板。

```text
EvidenceBundle
  -> deterministic claims/citations/status
  -> canonical machine answer (authoritative)
  -> Chinese template (always available)
  -> optional constrained renderer
  -> validator
       -> valid: constrained text
       -> invalid/unavailable: template text
```

### 7.3 方案 C：LLM 直接生成结构化答案

流程：将融合证据交给文本模型，让模型直接输出 claim、citation、JSON 和中文答案，再做 Schema 校验。

该方案开发表面速度快，但模型仍可能生成 Schema 合法却证据不成立的 claim，难以满足本项目的事实分层和候选/正式关系安全要求。

## 8. 问题 5：优缺点比较

| 维度 | 方案 A：纯模板 | 方案 B：混合式 | 方案 C：LLM 直接生成 |
|---|---|---|---|
| 事实安全 | 最强 | 强，前提是模型不拥有 claim 权限 | 最弱 |
| JSON 确定性 | 最强 | 最强 | 中等，Schema 合法不等于语义确定 |
| 中文自然度 | 中等 | 高 | 高 |
| 无模型可用性 | 完整 | 完整，可回退 | 差 |
| candidate/formal 边界 | 易保证 | 易保证 | 风险高 |
| 测试复杂度 | 低 | 中高 | 高 |
| 运行成本/时延 | 最低 | 可控 | 最高 |
| 扩展多种表达风格 | 较弱 | 强 | 强 |
| MVP 交付风险 | 低 | 中等 | 高 |

方案 A 的主要缺点是模板容易僵硬，复杂多意图答案可能可读性不足。方案 B 增加了文本校验和回退的实现成本，但不会牺牲机器答案权威性。方案 C 与“每条 claim 必须被证据绑定、模型不得提升事实等级”的项目核心原则冲突，不建议用于首版。

## 9. 问题 6：推荐方案

### 9.1 推荐结论

推荐**方案 B：确定性内核 + 中文模板默认 + 可选受约束文本生成**。

核心原则：

1. `machine_answer`、`claims`、`citations`、`status` 是权威事实层。
2. claim statement 由规则和模板从已批准证据生成，不由文本模型发明。
3. citation 由 evidence/provenance 确定性投影，模型无权新增、删除或改绑。
4. `text_answer` 是同一答案的表现层；模板是基线，文本模型只是可选 renderer。
5. JSON 与文本不分别“回答一次”，而是从同一 `AnswerPackage core` 派生。

### 9.2 推荐的数据流

```text
AssistantRequest (allow_write_back=false)
  -> QuestionUnderstandingService
       -> clarification/unsupported: 直接生成对应 AnswerPackage
       -> 单意图或可拆分子请求
  -> per subrequest:
       -> GraphRetrievalService
       -> SemanticGapDecisionService
       -> if recognize_required:
            group targets by page_id
            -> DrawingGraphToolFacade.recognize_semantic_targets(
                 write_back=false
               )
       -> EvidenceFusionService (no write-back policy)
       -> AnswerGenerationService
  -> deterministic multi-answer aggregation
  -> AnswerPackage
  -> CLI JSON / Chinese output
```

### 9.3 Claim 生成规则

- 每个 required evidence/claim capability 产生零或一个主 claim；重复能力可合并，但必须保留全部 evidence ID。
- `supported` 可生成正常 claim。
- `supported_with_qualifier` 必须携带限定语。
- `formal_review_required` 只能生成“候选/待复核”claim，不能生成正式结论。
- `conflicting` 生成冲突说明或 partial claim，不选择 winner。
- `missing`、`stale_only`、`unsupported` 不生成工程事实 claim，转入 warning、unsupported 或 follow-up。
- diagnostic claim 可以无工程 evidence，但必须绑定稳定 reason code/阶段事件，并明确是运行状态而非工程事实。

### 9.4 Citation 规则

- 每条非诊断 claim 至少绑定一个 citation。
- citation 必须可回指到 `evidence_id`，并只携带该 claim 需要的最小字段。
- 稳定排序建议为：claim 顺序 -> fact kind 固定顺序 -> page/block/element ID -> evidence ID。
- `image_path` 默认不进入公开文本；是否进入 JSON 由 CLI 数据最小化策略控制。
- `payload_ref` 只作为引用，不展开大 payload。
- `candidate_group_id`、`recognition_run_id`、`rule_version` 必须保留其语义，不改写成 formal/review 成功。

### 9.5 确定性 JSON 规则

“确定性 JSON”应定义为相同的结构化输入在相同合同版本下产生语义和字节均稳定的 JSON：

- 固定 `answer_contract_version`。
- 只使用字段白名单和稳定枚举。
- 所有集合在构造阶段稳定排序，不能依赖 set/dict/并发完成顺序。
- JSON 输出使用 UTF-8、`ensure_ascii=false`、固定 separators、`sort_keys=true`。
- 浮点数应在领域构造阶段规范化，不依赖序列化器临时舍入。
- 不把当前时间、随机 UUID、对象地址或 traceback 放进权威机器答案；`request_id` 由请求显式提供或按单独约定生成。
- 同一个 `AnswerPackage core` 同时驱动 JSON 与中文文本。

### 9.6 受约束文本生成规则

首版文本生成器只能接收脱敏后的：

- 已批准 claim ID、statement、status、qualifier。
- citation 的公开标签，不含底层密钥、Cypher、traceback 或完整本地路径。
- 允许的章节结构和语言 `zh-CN`。

输出必须是受约束 JSON，而不是任意自由文本；至少检查：

- claim ID 集合完全一致，不得新增或遗漏。
- citation 引用只能来自输入 allowlist。
- 不得新增数字、稳定业务 ID、关系状态或工程实体名称。
- candidate/interpretation/conflict 的限定语不得删除。
- 不得输出来源事实层中不存在的确定性陈述。
- 任一校验失败、超时或 provider 不可用，立即使用中文模板。

自动校验无法完全证明“语义上没有幻觉”，因此模型文本永远不是权威输出；客户端应以 `machine_answer` 和 claim/citation 为准。

### 9.7 CLI 建议

建议新增独立产品入口，而不是修改现有固定 QA CLI：

```text
scripts/drawing_assistant.py ask
  --question <自然语言问题>
  [--page-id / --block-id / --element-id / ...]
  [--allow-recognition]
  [--format json|zh-brief|json-and-text]
```

CLI 边界：

- 不提供 `--write-back`。
- 默认 JSON 或 `json-and-text`；JSON 是权威输出。
- `--allow-recognition` 为显式模型调用授权；未提供时只复用已有证据。
- provider、Neo4j 凭据和模型 key 只从环境配置读取，不进入命令参数或输出。
- CLI 只管理参数、driver 生命周期、service factory、输出和退出码，不承载编排逻辑。
- fake facade/provider 的端到端测试与 live Neo4j/live DashScope 分开报告。

## 10. 问题 7：风险

### 10.1 高风险

| 风险 | 表现 | 缓解措施 |
|---|---|---|
| claim 幻觉或无证据 claim | 中文自然但无法追溯 | claim 只能由确定性 builder 生成；非诊断 claim 无 evidence 直接拒绝 |
| candidate 被写成 formal | “候选匹配”被渲染为“已匹配” | fact kind + claim capability + qualifier 三重门控；专门负向测试 |
| 多意图直接穿透 02—05 | 顶层 `required_evidence` 为空，得到空检索/错误 answerability | 每个 subrequest 独立投影和执行，再确定性聚合 |
| 跨页识别一次调用 | facade 拒绝多页 targets | 总编排按 `page_id` 稳定分组；每页独立失败隔离 |
| 只读授权被下游建议扩大 | `write_back_recommendation` 或 policy 被误当授权 | service/CLI 双层强制 false；不给 05 传可写 policy；静态边界测试 |
| 文本与 JSON 不一致 | 两套逻辑各自生成答案 | 共享 `AnswerPackage core`；文本只做渲染；一致性测试 |

### 10.2 中风险

| 风险 | 表现 | 缓解措施 |
|---|---|---|
| 05 输出分桶语义接缝 | 冲突证据可能同时进入可用集合，06 难以判断 | 以 `conflicts`、claim support 和 evidence ID 明确过滤；若 05 合同不足，先在 05 独立修正，不在 06 猜测 |
| DTO 兼容性 | 加严 `Claim/Citation/AnswerPackage` 破坏现有合同测试 | 向后兼容扩展、版本化；必要时新建 answer contract 并 re-export |
| 状态映射不统一 | recognition failed、partial、unsupported 相互覆盖 | 建立单一状态优先级表和组合测试矩阵 |
| 并发导致非确定顺序 | 多查询/多页识别完成顺序影响 JSON | 执行可并发，聚合必须按稳定 key 排序 |
| 受约束文本仍可能语义漂移 | Schema 合法但措辞引入暗示 | 模板默认；数字/ID/实体 allowlist；限定语不可删除；模型文本标记为非权威 |
| 路径与敏感信息泄漏 | citation/error 暴露本地路径、URI、traceback | adapter 数据最小化和共享脱敏；默认不在文本输出 image path |

### 10.3 验证风险

- 单元测试/fake 端到端通过不等于 live Neo4j 通过。
- fake/provider 合同通过不等于 live DashScope 效果通过。
- live DashScope dry-run 通过不等于任何写回链路通过；本 MVP 本身不应验证写回。
- 文档中的历史测试数字不能替代实施后的新鲜回归。
- 当前工作区存在未提交修改，后续实施必须先确认 05 基线并避免覆盖用户改动。

## 11. 推荐的验收分层

本节仅定义未来验收，不表示本分析阶段已经执行这些验证。

### 11.1 06 独立验收

- claim/citation 合同、稳定 ID、证据必需性。
- 各 fact kind 的表达规则与 candidate/formal 负向测试。
- answerability 到 answer status 的全矩阵。
- canonical JSON 重复运行字节一致。
- 中文模板与 machine answer 一致。
- 受约束文本生成非法输出时回退模板。
- 敏感字段和低层错误不泄漏。

### 11.2 总编排独立验收

- 01→02→03→05→06 的无识别路径。
- 01→02→03→04→05→06 的 fake 识别路径。
- clarification/unsupported 早停，不调用 facade/识别。
- 多意图按子请求执行和聚合。
- 多页 target 分组、单页失败不抹掉其他页结果。
- Qwen/facade/融合/文本生成失败的 partial 降级。
- 全路径 `write_back=false`，无持久化 port 调用。

### 11.3 CLI 端到端验收

- 参数、scope、格式、退出码和 stderr/stdout 分离。
- 相同 fake 输入产生相同 JSON。
- 不存在 `--write-back`，问题文本不能注入写回授权。
- fake runtime smoke 与 live Neo4j/live DashScope 分层报告。

## 12. 最终建议与评审门

建议按以下设计边界进入后续规格与实施计划：

1. 先完成 06 的确定性 claim/citation/AnswerPackage core 和模板，不依赖总编排。
2. 再增加可选受约束文本 renderer，并确保模板回退始终成立。
3. 再实现 `DrawingAssistantService`，显式处理 subrequest fan-out、page grouping、早停与 partial。
4. 最后增加独立只读 CLI，并做 fake 端到端验收。
5. 07 仅保留请求内 trace 数据；反馈与持久化追溯另立需求，不混入本 MVP。

本报告是需求分析与推荐方案，不是代码实施批准。评审通过后，下一步应按 Superpowers 流程另行形成可执行实施计划，并把任务拆成“一个明确目标、指定修改文件、可独立测试、有完成标准”的单能力任务。
