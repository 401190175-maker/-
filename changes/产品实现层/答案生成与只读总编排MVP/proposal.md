# 答案生成与只读总编排 MVP Proposal

**文档状态：** 已实现（Task 1-65 完成；66-74 文档与验收见 tasks.md 状态）  
**日期：** 2026-08-14  
**实施验证：** 离线/fake 回归 2428 项通过；live Neo4j、live DashScope、真实文本 provider 均未验证。  
**依据文档：** `changes/产品实现层/答案生成与只读总编排MVP/Feature_Analysis_Report.md`  
**适用范围：** 产品实现层 06 答案生成、`DrawingAssistantService` 只读总编排和产品级只读 CLI 端到端 MVP  
**推荐方向：** 确定性 claim/citation/JSON 为权威输出，中文模板默认可用，受约束文本生成仅作为可选表现层

## 1. 背景

当前图块图谱构建项目已经形成从来源事实、派生关系到按需语义证据的分层能力。基础导入负责写入可追溯的项目、图纸册、页面、图块、页面元素、图片路径和 bbox；离线增强负责生成规则可确认的正式派生关系和需要复核的空间候选关系；语义证据层负责保存或临时返回 `TextObservation`、三类 `Interpretation`、缓存状态、不可变 payload 引用和识别运行信息。

项目已建立稳定的事实分层：

- `source_fact`：来源标注、稳定业务 ID、页面归属、图片路径和 bbox。
- `derived_relation`：由确定性规则生成的正式派生关系。
- `semantic_observation`：模型对图纸局部或整页内容的观察。
- `semantic_interpretation`：模型基于观察形成的结构化解释。
- `candidate_relation`：尚未经过完整复核和硬规则确认的候选关系。
- `formal_relation`：经过受控复核和规则确认的正式关系。
- `diagnostic`：检索、识别、缓存、冲突和运行状态。

上述层级不能互相替代。模型观察或解释不能覆盖来源事实，候选关系不能写成正式关系，`matched_candidate` 也不等于图谱中已经存在正式边。

产品实现层 00—07 已规划从自然语言提问到可追溯答案的完整产品闭环。当前工作区已经具备并可复用以下内部能力：

```text
AssistantRequest
  -> QuestionUnderstandingService
  -> GraphRetrievalService
  -> SemanticGapDecisionService
  -> [必要时] DrawingGraphToolFacade.recognize_semantic_targets()
  -> EvidenceFusionService
  -> EvidenceBundle
```

具体而言：

- 01 问题理解可以把自然语言问题转换为结构化问题类型、scope、证据需求、澄清和多意图子请求。
- 02 通用检索可以只通过 `DrawingGraphToolFacade` 白名单接口获取 `RetrievalBundle`。
- 03 语义缺口决策可以判断复用现有证据、执行识别、要求澄清或返回不支持。
- 04 多模态执行已经形成供应商无关、同步优先、默认 fake、可选 Qwen/DashScope 的受控识别路径。
- 05 证据融合可以输出规范化证据、冲突、claim 支撑、answerability、provenance 和缓存闭环信息。
- 产品公共合同中已预留 `Claim`、`Citation`、`AnswerPackage`、`TraceRecord` 和 `FeedbackEvent` 等 DTO。

但是，当前链路停止在 `EvidenceBundle`。系统尚不能把融合后的证据稳定转换为用户答案，也没有完整的 `DrawingAssistantService` 把 01—06 串联为一次只读产品请求；现有 QA CLI 仍要求调用者预先选择固定问题类型，不能作为面向自然语言产品闭环的总入口。

因此，本需求提出增加答案生成与只读总编排 MVP，在不改变现有图谱事实层、不新增写回能力、不破坏 QA/HTTP/MCP 兼容链路的前提下，完成从自然语言问题到确定性 JSON 和简短中文答案的首个产品级端到端闭环。

## 2. 当前问题

### 2.1 缺少从证据到 claim 的确定性转换

05 已经能够判断证据对某项 requirement 或 claim capability 的支撑状态，但 `ClaimSupportAssessment` 不是最终用户 claim。当前没有统一模块负责：

- 根据证据需求、支撑状态、冲突和 answerability 生成稳定 claim。
- 为 claim 分配稳定 `claim_id`、状态、类型、置信度和限定语。
- 拒绝生成没有证据支撑的非诊断 claim。
- 将 candidate、interpretation、formal 和 source fact 映射为不同确定性措辞。
- 在 `formal_review_required`、冲突、过期或低置信度场景中保留限制条件。

如果直接让文本模型读取 `EvidenceBundle` 并自由生成答案，即使输出符合 JSON Schema，也可能产生没有证据支撑的陈述，或把“候选、可能、待确认”改写成确定性关系。

### 2.2 Claim 与 citation 尚未形成完整引用闭环

公共合同已经预留 `Claim` 和 `Citation`，但当前仍缺少：

- claim 到 evidence ID 的确定性绑定规则。
- claim 到 citation 的稳定关联和排序。
- citation 对 page、block、element、bbox、observation、interpretation、candidate group、recognition run、payload 和 rule version 的最小字段投影。
- 引用去重和数据最小化规则。
- 非诊断 claim 必须至少有一个有效 citation 的强制校验。

没有这一闭环，机器答案和中文答案无法证明“这条结论来自哪里”，也无法稳定区分来源事实、语义解释和候选关系。

### 2.3 缺少权威且可重复的确定性 JSON

现有 `qa_serialization.to_jsonable()` 可以把 dataclass、枚举和容器转换为 JSON-safe 值，现有 CLI 也可以稳定输出 JSON envelope；但产品答案尚未定义独立的 answer contract 和 canonical 规则。

当前缺少：

- 明确的答案合同版本。
- 严格字段白名单和状态枚举。
- claim、citation、warning、unsupported 和 follow-up 的稳定排序。
- 并发查询或跨页识别完成顺序与最终输出顺序的隔离。
- 对浮点数、空值、路径和大 payload 的统一处理。
- 相同结构化输入在相同合同版本下产生相同机器答案的验证规则。

如果只依赖通用序列化器，输出虽然可以被 JSON 编码，却不一定具有稳定的产品语义、字段集合和字节表示。

### 2.4 中文回答缺少统一模板和事实等级措辞

现有 `qa_rendering.py` 可以把固定 `QAAnswer` 渲染为简短中文，但它不消费产品级 `EvidenceBundle`、claim、citation 或多意图结果，也不覆盖完整答案状态。

当前没有统一规则保证：

- `source_fact` 使用来源和定位措辞。
- `semantic_observation` 明确表达“模型观察到”。
- `semantic_interpretation` 明确表达“模型解释为”，不冒充标注原文。
- `candidate_relation` 必须包含“候选、可能、待确认”等限定语。
- `formal_relation` 只有在正式事实存在时才使用确定性表述。
- `partial`、`clarification_required`、`unsupported` 和 `recognition_failed` 在文本中清晰可见。

缺少统一模板会使不同问题类型、不同 adapter 或不同文本模型产生不一致表达。

### 2.5 受约束文本生成缺少安全边界

自然中文可以提高复杂、多意图答案的可读性，但自由文本模型不应成为新的事实源。当前尚无产品层文本生成 port 和校验器来限制模型只能表达已批准 claim。

需要明确解决：

- 文本模型只能接收脱敏后的 approved claims、公开 citation 标签和允许的章节结构。
- 文本模型不能新增、删除或改绑 claim/citation。
- 文本模型不能新增数字、业务 ID、关系状态或工程实体名称。
- candidate、interpretation、conflict 的限定语不能被删除。
- 模型输出非法、超时、不可用或校验失败时必须回退确定性中文模板。
- `machine_answer` 和结构化 claim/citation 始终是权威输出，生成文本只是表现层。

### 2.6 缺少 `DrawingAssistantService` 只读总编排

当前 01—05 均有独立入口，但尚无服务统一负责：

- 请求 ID 和父子请求关联。
- clarification/unsupported 的早停。
- 单意图与多意图子请求 fan-out。
- 02、03、04、05 的固定执行顺序。
- 识别目标按 `page_id` 分组。
- 单页识别失败、可选检索失败和文本生成失败的部分降级。
- 多子请求答案的稳定聚合。
- 全链路 `allow_write_back=false` 和 `write_back=false` 强制执行。
- 统一错误分类、warning、unsupported、follow-up 和阶段诊断。

特别是现有 `GraphRetrievalService`、03 和 05 主要消费顶层 `required_evidence`，而多意图结果将证据需求放在各 `subrequest` 中；现有 facade 的精确识别入口又要求一次调用中的全部目标属于同一页面。总编排不能把这些模块简单串起来，必须显式处理子请求投影和按页分组。

### 2.7 缺少产品级自然语言只读 CLI

现有 `scripts/drawing_graph_qa.py` 服务于六类固定问题，调用者需要选择 `ask-page`、`ask-block` 等命令，并提供准确 scope。它应继续作为兼容 QA adapter，而不是被扩展为完整自然语言产品编排器。

当前缺少一个独立 CLI，使用户只提供自然语言问题、可选 scope 和识别策略即可获得：

- 权威机器可读 JSON。
- 简短中文回答。
- claim/citation 和状态。
- 缺失证据、识别失败或澄清建议。
- 可验证的只读行为和稳定退出码。

### 2.8 “只读”边界需要产品级固化

项目已有默认 `write_back=false`，但 04 和 05 仍保留受控写回能力，03 也有 `write_back_recommendation`。如果总编排只依赖各模块默认值，而不在产品服务和 CLI 明确拒绝写回，后续扩展可能错误地把建议、配置或问题文本当成授权。

本 MVP 必须把“只读”定义为零持久化副作用：

- 不写 Neo4j。
- 不提交持久化语义缓存。
- 不写持久化 run/attempt/payload/trace/feedback 存储。
- 不审核、删除或提升候选关系。
- 临时识别只能使用 `write_back=false`。
- 临时 `recognition_run_id` 仅用于本次回答关联，不声明其可跨请求查询。

## 3. 功能目标

### 3.1 建立产品级答案合同

补齐或兼容性扩展现有 `Claim`、`Citation` 和 `AnswerPackage`，形成版本化、稳定、可校验的答案合同。

首版应覆盖：

- 答案状态：`answered`、`partial`、`clarification_required`、`unsupported`、`recognition_failed`。
- claim ID、类型、状态、statement、confidence、fact kinds、scope、evidence IDs 和 qualifiers。
- citation ID、claim 关联、稳定业务 ID、bbox、语义证据引用、候选组、识别 run、payload 和规则版本。
- 权威 `machine_answer`、`text_answer`、warnings、unsupported parts、recognition run IDs 和 follow-up actions。
- answer contract version 和确定性排序规则。

合同扩展必须保持 01—05 和现有公共 DTO 的兼容性；若直接加严现有 DTO 会破坏已有消费者，应使用版本化的新答案合同或兼容性 re-export，而不是复制出含义冲突的另一套 `Claim`/`Citation`。

### 3.2 建立确定性 claim 生成能力

建立从 `QuestionUnderstandingResult + EvidenceBundle` 到 claim 集合的确定性转换。

claim 生成必须满足：

- 每条非诊断 claim 至少绑定一个受支持 evidence ID。
- `supported` 可以生成正常 claim。
- `supported_with_qualifier` 必须携带限定语。
- `formal_review_required` 只能生成候选或待复核 claim。
- `conflicting` 只能生成冲突或部分结论，不静默选择一方。
- `missing`、`stale_only`、`unsupported` 不生成工程事实 claim，转为 warning、unsupported 或 follow-up。
- 置信度不能提升 `fact_kind`，高置信度 candidate 仍然是 candidate。
- diagnostic 只描述运行或能力状态，不冒充工程事实。

### 3.3 建立确定性 citation 生成能力

建立从 evidence、provenance 和 claim 支撑结果到最小 citation 的投影、去重和关联规则。

citation 生成必须满足：

- claim 可以反查其全部 evidence 和必要定位字段。
- 只包含当前 claim 所需的最小字段，不复制完整 payload。
- stable ID、bbox、observation、interpretation、candidate group、recognition run、payload ref 和 rule version 保持原始语义。
- 引用集合按固定规则排序，不依赖 dict、set、并发或 provider 返回顺序。
- 路径是否公开由 adapter 数据最小化策略控制，中文文本默认不输出完整本地图片路径。

### 3.4 建立权威确定性 JSON

建立 `AnswerPackage core -> machine_answer -> canonical JSON` 的固定生成链路。

确定性 JSON 必须满足：

- 相同结构化输入与相同合同版本产生相同语义输出。
- 使用字段白名单、稳定枚举和固定合同版本。
- claim、citation、warning、unsupported、run ID 和 follow-up 在构造阶段稳定排序。
- 输出使用 UTF-8 中文，不依赖对象地址、异常 traceback、当前时间或并发完成顺序。
- 不暴露 Neo4j 内部 ID、Cypher、driver/session/transaction、secret、Authorization header 或低层类名。
- 大 payload 只返回 `payload_ref`，不进入权威答案主体。
- JSON 与中文回答来自同一个 `AnswerPackage core`，不得各自重新解释证据。

### 3.5 建立默认中文模板

建立始终可用的确定性中文模板渲染器。默认结构应包括：

```text
直接结论

依据：
1. 来源事实或定位证据
2. 语义观察或解释
3. 候选或正式关系状态

注意：不确定性、缺失证据、识别失败或验证边界
```

模板需要按 fact kind、claim status、qualifier 和答案状态选择不同措辞，并保证：

- 中文文本不包含 machine answer 中不存在的新 claim。
- candidate、interpretation、conflict 和 partial 的限制条件不可省略。
- clarification 和 unsupported 可以在未运行后续检索时直接生成。
- 文本生成器不可用时仍能返回完整、准确的答案。

### 3.6 建立可选受约束文本生成

定义供应商无关的文本生成 port、fake 实现、受约束输出合同、验证器和模板回退。

受约束文本生成器只允许：

- 调整已批准 claim 的表达顺序和连接方式。
- 在固定章节结构中生成自然中文。
- 使用输入 allowlist 中的 claim ID、公开 citation 标签和限定语。

受约束文本生成器禁止：

- 新增、删除或改绑 claim/citation。
- 修改 fact kind、claim status、confidence 或 formal/candidate 状态。
- 新增输入中不存在的数字、业务 ID、工程实体、关系或原因。
- 删除 candidate、interpretation、冲突和不确定性限定语。
- 访问图谱、调用视觉识别、执行写回或读取 secret。

任一输出校验失败、provider 不可用、超时或异常都必须回退中文模板。生成文本不是权威事实源，客户端仍应以结构化 claim/citation 和 `machine_answer` 为准。

### 3.7 建立 `DrawingAssistantService` 只读总编排

新增产品级唯一总编排入口，固定执行：

```text
AssistantRequest
  -> QuestionUnderstandingService
  -> clarification / unsupported early return
  -> per subrequest:
       -> GraphRetrievalService
       -> SemanticGapDecisionService
       -> optional recognition grouped by page_id
       -> EvidenceFusionService
       -> AnswerGenerationService
  -> deterministic aggregation
  -> AnswerPackage
```

总编排必须：

- 保留父 `request_id` 和稳定 `subrequest_id`。
- 将多意图拆成现有 02—05 可消费的单子请求上下文。
- 按 `page_id` 对识别目标稳定分组，单页独立调用 facade。
- 临时识别固定传入 `write_back=false`。
- 不向 05 传入任何可扩大写回授权的 policy。
- 在 Qwen、单页识别、可选检索或文本生成失败时保留已有证据并返回 partial。
- 对必需识别失败且无其他语义 claim 的场景返回 `recognition_failed`。
- 确定性聚合子请求状态、claim、citation、warning 和 follow-up。
- 只依赖注入的 01—06 服务和 `DrawingGraphToolFacade`，不直接访问 driver、repository、Cypher、CLI 脚本或离线规则函数。

### 3.8 建立产品级只读 CLI 端到端入口

新增独立产品级 CLI，而不是修改现有固定 QA CLI 的职责。

CLI 应支持：

- 自然语言问题。
- 可选 page、block、element、cross section、table、table caption 或其他受支持 scope hint。
- 显式 `allow_recognition` 控制；未显式允许时只复用已有证据。
- `json`、`zh-brief` 或 `json-and-text` 输出格式。
- 稳定成功/部分成功/澄清/不支持/调用失败退出语义。
- stdout 输出成功结果，stderr 输出脱敏错误。

CLI 不提供任何 `write-back` 参数。Neo4j 凭据、provider 配置和 API key 只从运行环境读取，不进入命令参数、请求 DTO 或输出。

### 3.9 保持现有兼容链路

现有 `DrawingGraphQAService`、QA CLI、只读 HTTP API 和本地 STDIO MCP adapter 继续保留。新增产品总编排不替换、不反向依赖、不绕过现有 QA 层，也不要求现有六类 QA 问题改用产品服务。

新增依赖方向固定为：

```text
Product CLI
  -> DrawingAssistantService
  -> AnswerGenerationService / 01—05 services
  -> DrawingGraphToolFacade
  -> ports / services / controlled repositories
  -> Neo4j / optional provider
```

## 4. 修改范围

### 4.1 答案合同范围

规划并后续实现产品级答案合同的兼容性扩展或独立版本化模块，覆盖：

- Answer、Claim、Citation 的稳定枚举和字段。
- claim-citation-evidence 关联。
- answer contract version。
- 状态、warning、unsupported 和 follow-up 合同。
- canonical machine answer 和 JSON 输出约束。

该合同不得依赖 Neo4j driver、repository、Cypher、HTTP/MCP 框架或真实模型客户端。

### 4.2 Claim 与 citation 构造范围

规划并后续实现独立、确定性的 claim/citation 构造能力：

- 消费 `QuestionUnderstandingResult` 与 `EvidenceBundle`。
- 映射 requirement、claim capability 和 claim support status。
- 按事实等级选择 statement 和 qualifier。
- 从 evidence refs/provenance 构造最小 citation。
- 强制非诊断 claim 的证据引用。
- 对冲突、过期、候选和正式审核要求执行安全门控。

### 4.3 Machine answer 与序列化范围

规划并后续实现权威机器答案和 canonical JSON：

- 构造固定字段的 machine answer。
- 稳定排序全部集合。
- 统一 answer status 映射。
- 复用通用 JSON-safe 转换和脱敏能力，但保持产品业务规则在产品层。
- 为相同输入输出一致性提供独立测试。

### 4.4 中文模板和受约束文本范围

规划并后续实现：

- 按 claim/fact kind/status 渲染的确定性中文模板。
- 供应商无关文本生成 port 和 fake。
- 输入 allowlist、受约束输出 Schema 和安全校验。
- 模板回退。
- machine answer 与 text answer 一致性验证。

本范围不引入默认真实文本模型调用；真实 provider 只作为显式配置的可选 adapter。

### 4.5 只读总编排范围

规划并后续实现 `DrawingAssistantService` 及其无副作用 factory：

- 01—06 固定顺序编排。
- clarification/unsupported 早停。
- 多意图子请求投影、独立执行和稳定聚合。
- 识别目标按页分组。
- partial、recognition_failed、unsupported 和内部错误的稳定映射。
- 全链路 `write_back=false`。
- driver 和 provider 生命周期继续由最外层 adapter 管理。

### 4.6 产品级只读 CLI 范围

规划并后续实现独立 CLI：

- 参数解析和 scope hint 构造。
- 环境配置读取。
- driver/facade/service 生命周期。
- JSON、中文和组合输出。
- 稳定退出码与错误脱敏。
- 不提供写回、候选审核或正式关系提升入口。

### 4.7 测试与验证范围

后续实施需要覆盖：

- 答案合同、claim/citation 和 canonical JSON 单元测试。
- 各 fact kind 的模板措辞和 candidate/formal 负向测试。
- 受约束文本非法输出、超时和 provider 不可用的模板回退测试。
- 01→02→03→05→06 无识别闭环。
- 01→02→03→04→05→06 fake 识别闭环。
- clarification/unsupported 早停和零下游调用。
- 多意图 fan-out、跨页分组和部分失败隔离。
- CLI 参数、输出、退出码、stdout/stderr 和确定性重复运行测试。
- 静态边界：答案/总编排/CLI 不得直接导入 repository、Cypher、离线规则或写回内部实现。
- `write_back=false` 下 run log、Neo4j、payload、persistent cache、feedback 和 candidate promotion 均无持久化调用。

验证必须分层报告：单元/合同、fake runtime、CLI smoke、live Neo4j 和 live DashScope 不能互相替代。历史测试数字和 skipped 集成测试不能作为本需求实施完成的证据。

### 4.8 文档同步范围

只有在实施完成并取得新鲜验证证据后，才同步：

- `README.md`
- `architecture.md`
- `Module.md`
- 本 change 目录内后续 `design.md`、`tasks.md` 和验收记录

本 proposal 阶段只修改本文件，不把规划中的能力写成已实现。

## 5. 不包含范围

本需求不包含以下内容：

- 不实现 07 的反馈状态机、反馈 API、反馈持久化或正式关系提升流程。
- 不实现持久化产品级 `TraceRecord`；MVP 仅可返回请求内 trace/diagnostic 摘要。
- 不新增产品级 HTTP API、远程 MCP、Streamable HTTP MCP、Web UI 或 App UI。
- 不修改现有 QA HTTP/MCP 路由和六类固定 QA 行为。
- 不新增异步任务队列、流式输出、多 worker 或跨请求会话存储。
- 不新增 OCR 或独立 OCR 引擎。
- 不执行全量自动语义扫描。
- 不默认调用真实 Qwen/DashScope 或真实文本生成模型。
- 不把 live DashScope 或 live Neo4j 作为离线 MVP 验收的前置条件。
- 不写 Neo4j、持久化语义缓存、run log、attempt log、payload、trace 或 feedback。
- 不提供 `allow_write_back=true`、`--write-back`、HTTP 写回或 MCP 写回入口。
- 不执行候选关系审核、删除、提升或正式关系创建。
- 不把 candidate、`matched_candidate`、模型观察或模型解释写成来源事实或正式关系。
- 不覆盖来源事实，不设置或推断 `DrawingBlock.block_type`。
- 不新增或修改 Neo4j 节点、关系、约束、索引或 schema。
- 不直接创建 Neo4j driver，不直接写 Cypher，不直接调用 repository 写回方法或离线增强规则函数。
- 不重构与答案生成、总编排和只读 CLI 无关的基础导入、关系增强、候选审核、HTTP 或 MCP 模块。
- 本 proposal 不包含代码实现，不代表后续 design、tasks 或实施已经批准。

## 6. 影响模块

### 6.1 产品公共合同模块

影响模块：

- `src/drawing_graph/assistant_models.py`
- 可能新增的版本化答案合同模块

影响类型：兼容性扩展或职责拆分。

需要补齐 `Claim`、`Citation`、`AnswerPackage` 的稳定枚举、引用关联、合同版本和确定性字段约束。修改必须保持现有 01—05 DTO 与合同测试兼容；不得形成两套同名但语义不同的公共模型。

### 6.2 证据融合合同与服务

影响模块：

- `src/drawing_graph/assistant_evidence_fusion_models.py`
- `src/drawing_graph/assistant_evidence_fusion.py`
- `src/drawing_graph/assistant_claim_support.py`
- `src/drawing_graph/assistant_answerability.py`

影响类型：下游消费，必要时先独立加固 05 接口。

06 将消费 `accepted_evidence`、`conflicts`、`claim_support`、`answerability`、`provenance`、`reason_codes` 和 `cache_summary`。如果当前 accepted/conflicting 分桶无法让 06 无歧义消费，应在 05 自身范围内先修正合同并独立验证，而不是让答案生成器猜测冲突 winner 或重新定义 fact kind。

### 6.3 新增答案生成模块

影响类型：新增。

建议按单一职责新增或等价实现：

- claim builder。
- citation builder。
- machine answer/canonical JSON builder。
- 中文模板 renderer。
- 受约束文本生成 port、fake、validator 和 fallback。
- `AnswerGenerationService` 唯一 06 编排入口。

这些模块只消费 DTO，不查询 Neo4j、不调用视觉识别、不执行写回、不提升候选关系。

### 6.4 问题理解模块

影响模块：

- `src/drawing_graph/assistant_question_understanding.py`
- `src/drawing_graph/assistant_models.py` 中的 `AssistantSubrequest`、`QuestionUnderstandingResult`

影响类型：被总编排消费，原则上保持原职责。

总编排需要处理 clarification、unsupported 和 subrequests，但问题理解模块仍不访问 facade、不检索图谱、不执行识别、不生成最终答案。

### 6.5 通用检索模块

影响模块：

- `src/drawing_graph/assistant_retrieval_service.py`
- `src/drawing_graph/assistant_retrieval_planner.py`
- `src/drawing_graph/assistant_retrieval_executor.py`
- `src/drawing_graph/assistant_retrieval_projection.py`

影响类型：按单子请求复用。

总编排应将多意图子请求投影为独立、可消费的检索上下文，不让检索模块自行解释多意图，也不改变其 facade 白名单和只读边界。

### 6.6 语义缺口决策模块

影响模块：

- `src/drawing_graph/assistant_semantic_gap_decision.py`
- `src/drawing_graph/assistant_recognition_target_planner.py`
- `src/drawing_graph/assistant_recognition_budget.py`

影响类型：被总编排调用。

总编排消费 selected/deferred/blocked targets、reason codes 和估算结果。`write_back_recommendation` 只作为诊断信息，不能修改请求授权。

### 6.7 多模态识别与 facade

影响模块：

- `src/drawing_graph/tool_facade.py`
- `src/drawing_graph/semantic_service.py`
- `src/drawing_graph/recognition_execution.py`
- 04 的 provider port 与 fake/Qwen adapter

影响类型：复用现有精确识别入口。

总编排按 `page_id` 对目标分组，并只通过 `DrawingGraphToolFacade.recognize_semantic_targets(..., write_back=false)` 执行临时识别。总编排不得直接调用 provider、semantic repository、run log、payload store 或 execution service 内部方法。

### 6.8 新增总编排与 factory

影响类型：新增。

建议新增或等价实现：

- `DrawingAssistantService`。
- 子请求投影/执行结果等内部编排 DTO。
- 无副作用的产品 service factory。

factory 可以接收已经装配的 facade 和可选文本 renderer，但模块 import 和 factory 创建不得主动创建 driver、连接 Neo4j、扫描数据目录或发起 provider 请求。

### 6.9 JSON 转换、中文渲染与脱敏模块

影响模块：

- `src/drawing_graph/qa_serialization.py`
- `src/drawing_graph/qa_rendering.py`
- 可能新增的产品答案序列化和渲染模块

影响类型：基础能力复用或产品层独立扩展。

`to_jsonable()`、错误 envelope 和共享脱敏规则可以复用；现有 `qa_rendering.py` 继续服务 `QAAnswer`。产品级 canonical JSON 和中文模板应在产品层实现，避免把 QA 渲染器变成第二个产品编排器。

### 6.10 Tool factory 与配置

影响模块：

- `src/drawing_graph/tool_factory.py`
- `src/drawing_graph/config.py`
- 可能新增的 `drawing_assistant_factory.py`

影响类型：装配扩展。

现有 facade 工厂继续管理 facade 内部依赖；产品 factory 负责装配 01—06。真实 Neo4j driver 和 provider secret 仍由最外层运行环境管理，不能进入领域 DTO、日志或输出。

### 6.11 新增产品级 CLI

影响模块：

- 计划新增的 `scripts/drawing_assistant.py`
- CLI 相关配置、序列化、错误映射和测试

影响类型：新增 adapter。

CLI 只负责参数、配置、driver 生命周期、service 调用、输出和退出码，不直接访问 `QueryService`、repository、Cypher、provider 或离线增强规则。

### 6.12 现有 QA/HTTP/MCP adapter

影响模块：

- `src/drawing_graph/qa_service.py`
- `scripts/drawing_graph_qa.py`
- `src/drawing_graph/qa_http.py`
- `src/drawing_graph/qa_mcp_*.py`
- `scripts/serve_drawing_graph_qa.py`
- `scripts/serve_drawing_graph_mcp.py`

影响类型：兼容保留，原则上不修改。

现有链路继续固定为：

```text
QA adapter
  -> DrawingGraphQAService
  -> DrawingGraphToolFacade
  -> ports / services / repository / Neo4j
```

产品级 CLI 与现有 QA CLI 是同级 adapter，不通过 QA CLI 子进程或 HTTP API 间接调用产品能力，也不要求现有 MCP 注册产品级工具。

### 6.13 测试与文档

影响模块：

- 新增答案合同、claim/citation、JSON、模板、文本约束、总编排、factory 和 CLI 测试。
- 实施完成后更新 `README.md`、`architecture.md` 和 `Module.md`。

影响类型：新增覆盖与实施后同步。

测试必须分别证明合同、确定性、只读边界、fake 端到端和 adapter 行为；未实际运行的 live Neo4j、live DashScope 或真实文本模型验证必须标记为未验证，skipped 不等于通过。
