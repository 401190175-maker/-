# 多模态识别产品化 Proposal

**文档状态：** 需求提案  
**日期：** 2026-08-12  
**依据文档：** `changes/产品实现层/多模态识别产品化/Feature_Analysis_Report.md`  
**适用范围：** 产品实现层 04 多模态识别执行模块  
**推荐方向：** 供应商无关、同步执行优先的多模态识别执行流水线；Qwen/DashScope 仅作为 provider adapter

## 1. 背景

当前图块图谱构建项目已经形成从来源事实到产品级语义缺口决策的基础链路。XAnyLabeling JSON/PNG 可以导入为稳定的项目、图纸册、页面、图块和页面元素来源事实；离线增强可以形成正式派生关系和空间候选关系；语义证据层已经具备图谱内 `TextObservation`、三类 `Interpretation`、确定性缓存键、不可变 payload、图谱外 `RecognitionRun` 和默认 `write_back=false` 的安全边界。

产品实现层已经落地公共合同、问题理解闭环、通用只读检索闭环和语义缺口决策首阶段。当前链路能够：

- 把自然语言问题转换为稳定的证据需求。
- 通过 `DrawingGraphToolFacade` 白名单接口只读获取现有来源事实、派生关系、语义证据、候选关系和正式关系。
- 判断证据是否充分、是否过期、缓存是否可复用。
- 规划精确到 page、block、element 或 bbox 的最小 `RecognitionTarget`。
- 在调用模型前执行目标数、预计成本和预计时延门控。
- 在语义执行前按统一 cache key 二次检查缓存，避免缓存命中时重复调用供应商或创建无意义的持久化 run。

现有语义执行层也已经具备可复用基础：

- `MultimodalRecognitionClient` 协议及 fake client。
- 可选 `QwenMultimodalRecognitionClient`，使用 DashScope OpenAI-compatible 接口。
- `SemanticRecognitionService.recognize_targets()` 精确目标入口。
- 基于来源事实构造图片、bbox、image hash 和上下文引用的能力。
- `SemanticCacheService`、`SemanticPayloadStore`、`RecognitionRunLogPort` 和 `SemanticEvidenceRepositoryPort`。
- dry-run 与受控写回分离；模型输出只能进入语义观察、语义解释或候选证据，不能覆盖来源事实。

但是，现有 Qwen 客户端和语义服务主要用于证明供应商可替换、缓存和语义证据写回边界，尚未形成可运营、可观测、可审计的产品化多模态执行层。产品实现层 03 已经能够回答“是否需要识别、识别哪些目标”，下一步需要由产品实现层 04 稳定回答“如何按任务调用、实际发送什么图像、每次调用发生了什么、输出是否可信、实际成本和延迟是多少、发生错误时如何重试和脱敏”。

本需求在 03 语义缺口决策之后、05 证据融合之前增加独立的多模态识别产品化闭环：

```text
SemanticGapDecision
  -> MultimodalRecognitionExecutionService
       -> 任务合同
       -> 严格输入校验
       -> 局部 bbox 预处理
       -> task-specific prompt
       -> provider attempt / retry
       -> 严格输出校验
       -> usage / 成本 / 延迟
       -> 统一脱敏
  -> 合同有效的 RecognitionExecutionResult
  -> SemanticRecognitionService
  -> EvidenceFusionService
```

该闭环采用供应商无关设计，首版保持同步执行。Qwen/DashScope 只作为 provider adapter，不承担产品决策、语义证据写回、候选审核或正式关系提升。

## 2. 当前问题

当前架构支持多模态识别的基本调用和语义落点，但距离产品化仍存在以下问题。

### 2.1 Prompt 没有按任务隔离

当前 Qwen 客户端使用一个通用系统提示和一个通用用户提示处理不同目标。虽然请求包含 `prompt_version` 和目标类型，但尚未形成 task type、目标类型、允许上下文、必需输出、prompt template、输入合同和输出合同的一体化任务规格。

这会导致：

- 页面摘要、文本读取、图块语义识别、基础信息解析、表格解释、断面标记和关系证据提取混用同一提示边界。
- prompt 变化与输出 schema 变化不能被稳定关联。
- 不同任务可能错误共享缓存或输出字段。
- 离线测试无法按任务冻结 prompt 和合同。
- 供应商模型容易返回当前任务不需要的字段或越权事实声明。

### 2.2 输入合同不够严格

当前请求会校验页面 ID、图片路径、目标 tuple、bbox 类型、模型 profile 和 prompt version，但还没有完整校验：

- task type 是否支持当前 target type。
- 目标 ID、page ID、bbox 和来源事实是否一致。
- bbox 是否位于真实图片范围内。
- page task 与 element/block task 的图像范围是否符合任务策略。
- context 是否只包含任务允许的最小字段。
- input/output contract version 是否与任务规格兼容。
- 请求是否夹带 secret、未知字段或把 candidate 描述成 formal。
- deadline、最大 attempts 和运行策略是否完整且合法。

输入合同不足时，错误会延迟到供应商调用后才暴露，增加费用、时延、串目标和数据泄露风险。

### 2.3 bbox 尚未真正用于局部图像输入

现有客户端把 bbox 和 normalized bbox 写入文字提示，但仍把整页图片编码为 Base64 上传。也就是说，系统具备局部目标坐标，却没有真正执行局部裁剪。

这会造成：

- 单个元素问题仍携带整页图纸，视觉噪声和幻觉风险较高。
- 图片体积、token 或视觉计费单位和网络时延无法有效降低。
- 暴露给外部供应商的图纸范围大于当前问题需要。
- bbox、padding、缩放与模型输入之间没有坐标变换审计。
- 当前缓存键虽包含 bbox 和预处理版本，但真实发送图像尚未与这些维度完全对应。

### 2.4 缺少 retry 和 attempt 运行语义

当前供应商超时、HTTP 错误、429 或非法输出会直接映射为识别失败，没有稳定的错误分类、退避、`Retry-After`、总 deadline、结构修复重试和最大 attempts 策略。

同时，现有 `RecognitionRun` 表示一次逻辑识别运行，但没有独立记录每一次供应商调用。缺少 attempt 后，系统无法回答：

- 一次 run 实际调用了供应商几次。
- 每次调用使用了什么模型和合同版本。
- 哪次调用遇到 429、5xx、超时或结构错误。
- 每次调用耗时、usage 和费用是多少。
- 最终成功结果来自哪次 attempt。
- 是否因为 deadline、预算或不可重试错误而停止。

如果直接把每次重试都建成新的语义 run，会破坏一次逻辑识别的审计边界，并可能重复生成语义证据。

### 2.5 成本与延迟只有调用前估算

产品实现层 03 已经具备调用前预计成本和预计时延，用于是否允许识别。但是 04 尚未稳定采集：

- 供应商返回的实际 input/output usage。
- 图片单位或其他供应商计量字段。
- 每个 attempt 的供应商耗时。
- 退避等待、预处理、输出校验和端到端总耗时。
- 带版本的费率快照。
- 预计成本与实际成本之间的差异。
- usage 或适用费率不可得时的明确状态。

如果把 03 的估算当成实际账单，会造成成本审计失真；如果把不可得值填为 0，又会低估真实费用。

### 2.6 脱敏没有覆盖完整数据链路

当前已具备 API key 环境读取、配置 repr 隐藏和部分错误概括，但还没有统一覆盖以下出口：

- HTTP Authorization 和供应商 header。
- 供应商错误体中的请求回显。
- 本地绝对图片路径和用户目录。
- 原图、局部 crop、Base64 和 data URL。
- prompt 中非当前任务必需的页面上下文。
- run、attempt、payload、trace 和 adapter 输出。
- traceback、Neo4j/Cypher 内部细节和环境变量值。
- 供应商返回但不属于输出合同的未知字段。

只在配置对象中隐藏 key 不能替代端到端数据最小化和脱敏。

### 2.7 离线合同测试覆盖不足

当前 Qwen 离线测试能够验证基本请求构造、成功响应、429 和非法 JSON，但尚未形成完整的产品合同矩阵。缺少：

- 七类 task 的 prompt 和 schema 快照。
- task 与 target type 兼容性测试。
- bbox 像素裁剪、padding、边界、坐标变换和临时资源清理测试。
- retry、deadline、最大 attempts、`Retry-After` 和不可重试错误测试。
- run/attempt 关联与汇总测试。
- usage、实际成本、费率版本和延迟分段测试。
- 输出串目标、未知字段、错误枚举和事实等级越权测试。
- key、path、Base64、供应商 error 和 traceback 的脱敏测试。
- cache hit 不创建 attempt、不重复计费的合同测试。
- 新执行层禁止访问 Neo4j、repository、Cypher 和 QA adapter 的静态边界测试。

离线合同测试通过也只能证明请求、解析、重试和安全合同成立，不能替代真实 Qwen 识别效果或 live Neo4j 写回验收。

## 3. 功能目标

本需求目标是把现有可选多模态客户端和语义服务升级为供应商无关、严格受约束、可重试、可计量、可脱敏、可离线验证的产品执行闭环。

### 3.1 建立 task-specific 任务规格

- 为首版七类 task 建立稳定任务注册表：
  - `page_summary`
  - `element_text_observation`
  - `block_semantic_identification`
  - `basic_info_interpretation`
  - `table_interpretation`
  - `section_label_observation`
  - `relation_evidence_extraction`
- 每个 task 明确支持的目标类型、prompt template、prompt version、input/output contract version、允许上下文字段、必需输出、crop policy、retry policy 和 provider capability。
- task-specific prompt 与输出合同共同版本化，任一方变化都能使缓存和审计可追溯。
- 允许不同 task 共享稳定 schema 片段，但不采用覆盖全部任务的超级 prompt。
- prompt 明确禁止把模型猜测写成来源事实、派生正式关系或 formal relation。

### 3.2 建立严格输入合同

- 在任何 provider 调用前验证 request、run、page、target、task、图片、bbox、上下文、模型、prompt、合同版本、deadline 和写回授权。
- 图片引用必须来自可信来源事实路径，不能接受模型生成或自由文本路径。
- element/block 任务必须携带合法 bbox；page summary 必须显式声明全页范围。
- bbox 必须满足坐标顺序和图片边界要求，并与 target ID 和 page ID 一致。
- target type 必须被 task 允许；未知 task、未知字段、错误版本和目标串线 fail closed。
- context 只允许任务白名单字段；候选关系不能作为已确认关系注入 prompt。
- 请求合同不得包含 API key、token、密码、Authorization 或其他 provider secret。
- `write_back` 只能由请求授权、模块策略和环境权限逻辑与得到，任何 prompt、模型结果或 retry 都不能提升权限。

### 3.3 实现真正的局部 bbox 输入

- block/element 任务优先发送目标 bbox 的局部 crop，而不是仅把 bbox 写入提示后上传整页。
- 每个 task 可以配置有限 padding，padding 后范围必须裁剪到页面边界。
- 需要空间上下文时，可附加低分辨率页面上下文图或结构化邻接摘要；不默认发送整页高分辨率图。
- 页面摘要继续使用整页输入，并与局部任务明确区分。
- 记录原始 bbox、crop bbox、padding、原图尺寸、crop 尺寸、缩放比例、坐标变换、image hash 和 crop hash。
- crop hash 与 preprocessing version 参与统一 cache key，保证真实模型输入与缓存身份一致。
- crop 仅存在于内存或受控临时文件；成功、失败、超时和取消路径均清理。
- 不把原图、crop、Base64 或 data URL 写入 Neo4j、run log、普通日志或对外响应。

### 3.4 建立 run、attempt 和 retry 闭环

- 保持一个逻辑 `RecognitionRun` 对应一次产品识别运行。
- 每次真实供应商调用生成独立 `RecognitionAttempt`，并关联同一个 run。
- attempt 至少记录编号、provider、模型、请求 fingerprint、prompt/合同版本、开始/结束时间、延迟、状态、retry reason、provider request ID、usage、成本和安全错误摘要。
- 输入合同失败发生在调用前，不生成 provider attempt。
- 失败 attempt 不生成 observation/interpretation；只有最终通过输出合同的结果才能进入语义投影。
- 对 429、暂时性 5xx、连接重置和有预算的超时执行有限重试。
- 优先遵守 `Retry-After`，否则使用指数退避和抖动。
- 非法 JSON 最多进行一次同任务、同合同的结构修复 attempt。
- 认证、权限、输入合同、能力不支持、事实等级越权、`ambiguous` 和 `not_found` 不进行传输重试。
- 每次重试前检查剩余 deadline、最大 attempts 和策略预算；不允许重试无限放大成本和时延。
- 首版同步执行，默认策略可支持最多三次 attempt，其中结构修复最多一次；具体值由策略注入，不硬编码在 Qwen adapter。

### 3.5 建立严格输出合同

- 每个 task 使用独立输出 schema 和字段白名单。
- 只接受符合合同的 JSON object，不把自由文本作为权威结果。
- 验证状态、枚举、置信度、目标 ID、目标类型、返回目标数和字段类型。
- observation/interpretation 必须绑定当前请求允许的目标，禁止跨目标串线。
- 未声明字段按合同策略拒绝，不能静默进入 Neo4j 属性或权威 payload。
- 禁止 provider 输出 `source_fact`、`derived_relation` 或 `formal_relation`。
- candidate 只能保持候选语义，`matched_candidate` 不等于 formal。
- 合同失败不得进入 05 证据融合，不得写入语义 repository。
- 输出校验后再生成领域层 observation/interpretation，provider 原始格式不直接污染领域 DTO。

### 3.6 建立实际成本和延迟计量

- 保持 03 的预计成本/预计时延用于调用前决策。
- 04 从 provider 响应提取实际 usage；不可取得时明确标记 unavailable。
- 每个 attempt 独立记录供应商耗时、input/output usage、图片单位、估算成本、实际核算成本、币种和 rate card version。
- run 汇总所有 attempts 的 provider 时间、退避时间、预处理时间、校验时间和端到端总时延。
- 费率通过版本化 profile 注入，不硬编码在 prompt、Qwen adapter 或语义领域 DTO 中。
- 没有适用 usage 或费率时，actual cost 为空并记录原因，不能按 0 处理。
- 实际成本是运行审计，不作为图谱来源事实或工程结论。
- 07 追溯模块后续可以比较估算和实际值，但不得把估算冒充供应商账单。

### 3.7 建立统一脱敏和数据最小化

- 对 header、secret、绝对路径、Base64、data URL、provider error、traceback、环境变量和内部数据库细节建立统一 redactor。
- provider adapter 只接收完成调用所需的执行内最小投影。
- run/attempt 只保存 hash、版本、目标 ID、usage、成本、延迟、错误类别和安全摘要。
- payload store 只保存经过白名单最小化和脱敏的不可变响应或验证结果，不保存图片、crop、Authorization 或完整 header。
- 对外只返回回答和排障所需字段，不返回原始 provider 请求、完整 prompt、本地路径或内部 traceback。
- prompt 只注入当前任务必需的上下文，不把完整候选集合、无关页面文本或敏感信息默认交给供应商。
- 图中文字视为待识别内容，不视为系统指令；输出合同再次拦截事实等级越权。

### 3.8 建立离线合同测试

- 使用固定图像 fixture、fake provider、fake clock、fake sleeper 和 `httpx.MockTransport`，不访问网络、不需要真实 key、不连接 Neo4j。
- 覆盖 task registry、输入合同、prompt 快照、bbox 裁剪、provider 请求、输出合同、retry、attempt、usage、成本、延迟和脱敏。
- 验证 cache hit 不调用 provider、不创建 attempt、不重复计费，也不创建持久化 run。
- 验证 `write_back=false` 不保存 run log、图谱内语义证据、Neo4j 数据或持久化 crop。
- 增加静态架构测试，禁止执行层导入 Neo4j driver、repository、Cypher、QA adapter 和 CLI 脚本。
- 分开报告单元测试、离线 provider 合同、live DashScope、黄金集和 live Neo4j；skipped 不等于通过。

## 4. 修改范围

本需求建议包含以下修改范围。

### 4.1 产品运行合同

- 扩展或新增 task spec、已验证识别请求、执行策略、attempt、usage、成本、延迟、安全错误和执行结果合同。
- 保持公共字段使用稳定业务 ID、bbox、模型、prompt、预处理和合同版本。
- 明确 `RecognitionRun` 与 `RecognitionAttempt` 的一对多关系。
- 明确预计值、实际 usage、实际核算费用和 unavailable 状态的区别。
- 保持 `write_back=false` 默认值以及事实等级不可提升约束。

### 4.2 任务注册与 Prompt

- 新增 task registry 和 prompt renderer。
- 为七类 task 提供独立的任务说明、输入约束、输出字段、枚举、不确定性规则和事实等级禁止项。
- prompt template、input contract 和 output contract 采用显式版本。
- prompt 不直接读取环境变量、数据库或 provider secret。
- 增加 prompt 快照和 task-to-contract 一致性测试。

### 4.3 输入校验与图像预处理

- 新增严格输入校验，覆盖目标、task、图片、bbox、上下文、版本、deadline 和 secret 字段。
- 新增局部 bbox crop、padding、边界裁剪、缩放/压缩和坐标变换。
- 生成 crop hash 和 preprocessing metadata，并与缓存键保持一致。
- 实现内存或临时文件生命周期管理，确保所有退出路径清理。
- 不修改来源图片、来源 bbox、JSON 标注或 Neo4j 来源节点。

### 4.4 Provider adapter 与执行编排

- 将现有 Qwen 客户端收窄为 provider adapter，负责授权 header、HTTP 请求和供应商格式映射。
- 新增供应商无关执行服务，编排输入验证、预处理、prompt、attempt、retry、输出校验、计量和脱敏。
- retry policy 位于执行层，不硬编码在 Qwen adapter。
- provider 原始响应必须先经过适配和合同校验，再进入领域结果。
- 首版保持同步执行，并保留未来异步 job port 的演进空间。

### 4.5 Run、Attempt、Payload 与语义服务衔接

- 扩展图谱外运行审计能力，使 run 可以关联 attempts 和成本/延迟汇总。
- 必要时新增独立 attempt log port；attempt 不进入 Neo4j 业务图谱。
- 调整 `SemanticRecognitionService` 的 cache miss 路径，调用新的执行服务。
- 保持执行前二次缓存校验；cache hit 不调用 provider、不创建 attempt 或持久化 run。
- 只把最终合同有效的输出投影为 `TextObservation` 或 Interpretation。
- payload store 保存最小化、脱敏、不可变的 provider/validated payload 引用。
- `write_back=true` 仍只能通过现有 semantic service 和受控 repository 写回。

### 4.6 成本、延迟与脱敏

- 新增 usage 提取、分阶段计时、费率 profile 和 run 级汇总。
- 记录 validation、preprocessing、每次 provider、backoff、output validation 和 total latency。
- 对 provider header、请求、响应、错误、payload、run、attempt、trace 和 adapter 输出使用统一脱敏策略。
- 增加 secret、绝对路径、Base64、data URL、traceback 和 provider error 泄露测试。
- 实际 cost/latency 作为运行审计，不写入来源事实或正式关系。

### 4.7 测试与文档

- 新增任务合同、输入合同、裁剪、provider、retry、attempt、usage、cost、latency、脱敏、cache 和 dry-run 离线测试。
- 增加架构边界测试，保护 provider/execution 与 Neo4j/QA adapter 的依赖方向。
- 在实施后同步 `architecture.md`、`Module.md`、README 和产品实现层 04 文档。
- 文档必须区分已实现、离线验证、live DashScope、黄金集和 live Neo4j 状态。
- 首阶段优先完成纯合同和 fake/离线闭环，不要求同时完成完整产品助手或真实写回验收。

## 5. 不包含范围

本需求不包含以下内容：

- 不实现完整 `DrawingAssistantService` 端到端编排。
- 不实现 05 证据融合、06 最终答案生成或 07 用户反馈状态机。
- 不新增产品级 CLI、HTTP、MCP、Web UI 或远程服务入口。
- 不改造现有六类只读 QA 工具为可写多模态产品接口。
- 不建设独立 OCR 流程，不引入 PaddleOCR、Tesseract 或其他传统 OCR 引擎。
- 不执行全量自动语义扫描或批量离线识别；只处理 03 选出的当前请求最小目标。
- 首版不引入消息队列、worker、分布式调度、durable job、回调或跨进程恢复。
- 首版不实现自动模型切换或多供应商路由；未来 fallback 必须显式设计和审计。
- 不修改 Neo4j 来源事实 schema、来源节点、来源关系、稳定业务 ID 或原始标注数据。
- 不修改或推断 `DrawingBlock.block_type`。
- 不把 `RecognitionRun` 或 `RecognitionAttempt` 建成 Neo4j 业务节点。
- 不覆盖、删除或静默替换历史 observation/interpretation。
- 不让模型输出成为 `source_fact`、`derived_relation` 或 `formal_relation`。
- 不审核或提升候选关系，不绕过 `CandidateReviewService` 和硬规则。
- 不把 candidate、`matched_candidate`、模型高置信度或用户确认当作 formal。
- 不从 retry、prompt 或模型输出推断 `write_back=true`。
- 不永久保存局部 crop、整页 Base64、data URL、Authorization 或 provider secret。
- 不把 03 的预计成本当成实际账单，不把 usage 不可得写成零成本。
- 不把离线合同测试通过写成真实 Qwen 识别质量、live DashScope 或 live Neo4j 已通过。
- 不在本需求中完成真实生产凭据管理、远程认证、RBAC、TLS、多租户配额或供应商合同采购。

## 6. 影响模块

| 模块 | 影响 | 边界要求 |
|---|---|---|
| `src/drawing_graph/assistant_models.py` / `tool_models.py` | 增加或扩展 task、执行策略、attempt、usage、cost、latency、safe error 和执行结果合同。 | 默认 `write_back=false`；不把运行指标混入来源事实。 |
| `src/drawing_graph/assistant_recognition_budget.py` | 估算考虑裁剪范围、最大 attempts、模型 profile 和 deadline。 | 仍只做调用前估算，不冒充实际账单。 |
| `src/drawing_graph/assistant_semantic_gap_decision.py` | 向 04 传递 selected targets、deferred targets、deadline 和执行策略。 | 不执行 provider 调用，不创建 run/attempt。 |
| `src/drawing_graph/semantic_client.py` | 协议承载 provider 请求/结果、task、版本、usage 和 provider metadata。 | 不读环境变量、不访问图谱、不决定 retry 或写回。 |
| `src/drawing_graph/qwen_semantic_client.py` | 收窄为 Qwen provider adapter，负责 HTTP 与供应商格式映射。 | API key 只存在于 provider config；不承担 task 决策、重试编排或语义写回。 |
| 新增 task registry / prompt renderer | 管理七类 task、prompt、输入/输出合同、crop/retry policy。 | 不访问 Neo4j、facade、repository 或 provider secret。 |
| 新增 input validator | 调用前验证来源、目标、task、bbox、上下文、版本和授权。 | 失败时不创建 provider attempt。 |
| 新增 image preprocessor | 执行 crop、padding、缩放、坐标变换、hash 和临时资源管理。 | 不修改来源图片/bbox，不持久化 crop/Base64。 |
| 新增 retry policy / attempt executor | 分类错误、执行有限重试、记录逐次供应商调用。 | 一个逻辑 run 多个 attempts；业务 `ambiguous/not_found` 不重试。 |
| 新增 output validator | 按 task schema 验证字段、枚举、目标和事实等级。 | 合同失败不进入语义证据或 05 融合。 |
| 新增 usage/cost/latency meter | 提取 usage、计时、费率核算和汇总。 | 预计、实际和 unavailable 分开；费率版本化注入。 |
| 新增 recognition redactor | 清洗 header、secret、路径、Base64、错误、payload 和 trace。 | 所有日志、存储和对外出口统一使用。 |
| 新增 execution service | 编排验证、预处理、prompt、provider、attempt/retry、校验、计量和脱敏。 | 不决定是否需要识别，不直接写 Neo4j。 |
| `src/drawing_graph/semantic_image_inputs.py` | 从 bbox/image hash 引用衔接真实局部预处理和上下文最小化。 | 图片与 bbox 仍来自来源事实。 |
| `src/drawing_graph/semantic_cache.py` | cache key 与真实 crop、task、prompt、合同和 preprocessing version 保持一致。 | attempt 编号和重试次数不进入语义内容 cache key。 |
| `src/drawing_graph/semantic_service.py` | cache miss 后调用执行服务，只投影最终合同有效结果。 | 继续负责 cache、语义 DTO、run/payload 和受控写回；不承担 03 决策。 |
| `src/drawing_graph/recognition_run_log.py` | run 关联 attempt IDs 和成本/延迟汇总，或衔接独立 attempt log port。 | `RecognitionRun` 和 attempt 继续位于图谱外。 |
| `src/drawing_graph/semantic_payload_store.py` | 保存最小化、脱敏、不可变 provider/validated payload。 | 不保存图片、crop、Base64、secret 或完整 header。 |
| `src/drawing_graph/semantic_repository.py` / `semantic_neo4j_repository.py` | 接收已通过合同的 observation/interpretation。 | 不接受失败 attempt、未知字段或 formal/source 越权结果。 |
| `src/drawing_graph/tool_facade.py` | 精确目标识别入口返回安全的产品化执行摘要。 | 不暴露 provider 原始请求、secret、本地路径或 repository 捷径。 |
| `src/drawing_graph/tool_factory.py` | 注入 task registry、preprocessor、retry、meter、redactor 和 provider。 | import/工厂创建不主动发网络请求或连接数据库。 |
| 05 证据融合模块 | 消费合同有效识别结果、失败状态和实际指标。 | 不重新重试，不改变 fact kind，不把 candidate 变 formal。 |
| 07 追溯反馈模块 | 后续记录 request -> run -> attempt -> evidence -> claim，以及成本/延迟。 | 运行审计不成为来源事实，反馈不直接提升 formal。 |
| `DrawingGraphQAService`、QA CLI/HTTP/MCP | 首阶段保持兼容。 | 不在 adapter 或 QAService 中复制执行流水线，不增加默认写回。 |
| 测试模块 | 新增 task、输入、crop、provider、retry、attempt、计量、脱敏、cache、dry-run 和边界测试。 | 离线、live DashScope、黄金集、live Neo4j 分开报告。 |
| `architecture.md`、`Module.md`、README、产品实现层 04 文档 | 实施后同步依赖方向、合同、状态和验证边界。 | 未实现或未 live 验证的能力不得提前写成已完成。 |

