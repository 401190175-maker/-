# 多模态识别产品化 Feature Analysis Report

**文档状态：** 需求分析与架构决策建议，尚未实施  
**日期：** 2026-08-12  
**分析范围：** task-specific prompt、严格输入合同、局部 bbox、重试、attempt、成本、延迟、脱敏和离线合同测试  
**目标位置：** 产品实现层 03 语义缺口决策之后、05 证据融合与缓存之前的 04 多模态识别执行层  
**非目标：** 不写代码，不改变 Neo4j 来源事实，不建设独立 OCR，不自动提升候选关系，不声明 live DashScope 或 live Neo4j 已通过

## 0. 结论摘要

当前架构对本需求是**架构方向支持、执行产品化部分支持**。

现有系统已经具备稳定业务 ID、来源图片与 bbox、语义证据分层、可选 Qwen/DashScope 客户端、按需识别服务、确定性缓存键、图谱外 `RecognitionRun`、默认 `write_back=false`，以及产品实现层 03 已落地的最小识别目标、成本/时延估算和预算门控。因此，不需要重建图谱或另建 OCR 管线。

但现有 04 执行能力还不是稳定的产品调用层：Qwen 客户端仍使用单一通用 prompt；bbox 只出现在文本提示中，实际上传的仍是整页图像；输入和输出只有基础校验，没有按任务冻结的严格合同；没有重试策略和 attempt 审计；没有采集实际 token、实际费用和实际延迟；脱敏未贯穿请求、日志、payload 与对外响应；离线测试也未形成 task × contract × provider × error 的合同矩阵。

推荐新增一个**供应商无关、同步执行优先的多模态识别执行流水线**。它由任务合同注册、输入验证、临时 bbox 裁剪、prompt 渲染、attempt/retry 执行、严格输出校验、实际用量与时延计量、统一脱敏和离线合同测试组成。Qwen adapter 只负责 HTTP 传输和供应商响应映射；`SemanticRecognitionService` 继续负责缓存、语义 DTO 投影与受控写回。

推荐依赖方向：

```text
SemanticGapDecisionService
  -> MultimodalRecognitionExecutionService
       -> RecognitionTaskRegistry
       -> RecognitionInputValidator
       -> RegionImagePreprocessor
       -> PromptRenderer
       -> RetryPolicy / AttemptExecutor
       -> MultimodalProviderPort
            -> QwenProviderAdapter
       -> RecognitionOutputValidator
       -> UsageCostLatencyMeter
       -> RecognitionRedactor
  -> SemanticRecognitionService
       -> SemanticCacheService / SemanticPayloadStore
       -> RecognitionRunLogPort
       -> SemanticEvidenceRepositoryPort
  -> EvidenceFusionService
```

## 1. 分析依据与事实边界

### 1.1 已读取材料

- `architecture.md`
- `Module.md`（用户口述为 `modules.md`，仓库实际文件名为 `Module.md`）
- `changes/产品实现层/00-product-closure-blueprint.md`
- `changes/产品实现层/01-question-understanding.md`
- `changes/产品实现层/02-graph-retrieval.md`
- `changes/产品实现层/03-semantic-gap-decision.md`
- `changes/产品实现层/04-multimodal-recognition.md`
- `changes/产品实现层/05-evidence-fusion-and-cache.md`
- `changes/产品实现层/06-answer-generation.md`
- `changes/产品实现层/07-traceability-and-feedback.md`

为避免把设计文档误当成实现证据，同时核对了当前多模态客户端、语义服务、图像输入、运行日志、预算决策和相关离线测试。

### 1.2 状态表达

| 状态 | 含义 |
|---|---|
| 已实现 | 当前源码已有明确模块或测试证据 |
| 可复用 | 可作为新模块输入或依赖，但不能直接满足完整需求 |
| 部分实现 | 已有基础能力，关键产品合同仍缺失 |
| 未实现 | 当前没有完整运行闭环 |
| 待验证 | 需要 live DashScope、真实图片黄金集或 live Neo4j 才能确认 |

本文中的“推荐”“应新增”“建议合同”都是设计结论，不代表代码已经存在。

## 2. 当前架构是否支持？

### 2.1 支持结论

支持，但只支持在现有分层中增量建设，不支持把现有客户端直接当作完整产品化实现。

系统已经形成正确的上下游边界：03 负责决定是否识别、识别哪些最小目标以及调用前预算；04 负责执行模型调用；05 负责融合已有证据与本次结果。来源事实、派生关系、语义观察、语义解释、候选关系和正式关系已有分层，模型结果具备安全落点。

### 2.2 已有基础

| 能力 | 当前状态 | 对本需求的价值 |
|---|---|---|
| 稳定 page/block/element ID | 已实现 | 请求、attempt 和结果可绑定明确目标 |
| 图片路径、bbox、normalized bbox | 已实现 | 可构造全页或局部区域并保留坐标追溯 |
| `SemanticGapDecisionService` | 已实现首阶段 | 已能产生最小 `RecognitionTarget` 并执行预算/时延门控 |
| `SemanticTargetInput` | 已实现预留 | 可作为严格识别输入合同的基础 |
| `recognize_targets()` | 已实现预留 | 支持精确目标、调用前二次缓存检查和 dry-run/write-back 边界 |
| `MultimodalRecognitionClient` | 已实现协议 | 供应商实现可替换 |
| Qwen/DashScope 客户端 | 部分实现 | 能构造兼容请求并解析基础 JSON |
| 语义缓存键 | 已实现 | 已覆盖图片、bbox、task、模型、prompt、预处理、规范化和合同版本 |
| `RecognitionRun` | 已实现 | 可作为一次逻辑识别运行的图谱外审计主体 |
| 语义 observation/interpretation | 已实现 | 模型结果不会污染来源事实 |
| 不可变 payload | 已实现 | 可保存合规后的响应或解析结果引用 |
| 默认 `write_back=false` | 已实现 | 可先做无持久化副作用验收 |

### 2.3 关键缺口

| 需求 | 当前实际状态 | 缺口判断 |
|---|---|---|
| task-specific prompt | 单一通用 prompt | 没有任务注册、独立模板和版本演进 |
| 严格输入合同 | 校验基础字段和 bbox 类型 | 未校验 task/target 兼容性、上下文白名单、图片范围和版本兼容 |
| 严格输出合同 | 解析 JSON 和顶层数组 | 未按 task 校验字段、枚举、目标绑定、未知字段和越权事实 |
| 局部 bbox | bbox 进入 prompt；上传整页 Base64 | 未实际裁剪，视觉噪声、图片体积和泄露范围没有降低 |
| retry | 超时、HTTP 错误直接失败 | 未实现错误分类、退避、Retry-After 和总 deadline |
| attempt | 只有逻辑 run | 未记录每次供应商调用的编号、原因、结果、耗时和用量 |
| 成本 | 03 有调用前估算 | 未采集实际 usage，未按费率快照核算实际费用 |
| 延迟 | 03 有调用前估算 | 未测量预处理、供应商、退避、解析和总耗时 |
| 脱敏 | key 来自环境、repr 隐藏、粗粒度错误 | 未覆盖路径、header、错误体、Base64、prompt、payload 和日志链 |
| 离线合同测试 | 基本成功、429、非法 JSON | 未形成按 task、版本和错误类型冻结的合同矩阵 |

### 2.4 保持不变的边界

- 不新增独立 OCR；文字读取仍是多模态任务的一部分。
- 04 不决定是否应该识别，该职责继续属于 03。
- Qwen adapter 不访问 Neo4j、facade、repository 或 run log。
- 模型结果不能覆盖来源事实或写入 `DrawingBlock.block_type`。
- 识别不能直接建立正式关系；候选提升仍经 `CandidateReviewService` 和硬规则。
- `RecognitionRun` 保持图谱外运行审计，不建成业务节点。
- 不永久保存 Base64 或局部裁剪图，只保存 hash、bbox、变换和必要 payload 引用。
- `write_back=false` 继续是默认值。

## 3. 需要新增哪些模块？

### 3.1 核心模块

| 模块 | 职责 |
|---|---|
| `RecognitionTaskRegistry` | 注册 task、目标类型、prompt、输入/输出合同、crop 与 retry 策略 |
| `RecognitionInputValidator` | 验证请求身份、来源图片、bbox、task/target 兼容性、上下文白名单和版本 |
| `RegionImagePreprocessor` | 临时裁剪、padding、缩放/压缩、坐标变换与派生 hash |
| `PromptRenderer` | 仅从任务规格和已验证输入渲染 prompt，禁止自由拼接事实等级 |
| `RecognitionRetryPolicy` | 分类可重试错误，限制 attempts、deadline 和退避 |
| `RecognitionAttemptExecutor` | 执行每次供应商调用并生成 attempt 记录 |
| `RecognitionOutputValidator` | 按任务合同校验 JSON、字段、枚举、目标绑定和禁止声明 |
| `RecognitionUsageMeter` | 提取 usage、测量分段延迟、计算估算/实际费用 |
| `RecognitionRedactor` | 对错误、日志、trace、payload 和 adapter 输出统一脱敏 |
| `MultimodalRecognitionExecutionService` | 编排上述步骤，输出稳定执行结果 |

这些是建议的职责边界；实施时可以合并很小的纯函数模块，但不能把职责重新堆回 provider adapter。

### 3.2 任务合同

建议定义版本化 `RecognitionTaskSpec`，至少包含：

```text
task_type
supported_target_types
prompt_template_id
prompt_version
input_contract_version
output_contract_version
required_outputs
allowed_context_fields
crop_policy
retry_policy_id
provider_capabilities
```

首版 task 沿用 04 文档：

- `page_summary`
- `element_text_observation`
- `block_semantic_identification`
- `basic_info_interpretation`
- `table_interpretation`
- `section_label_observation`
- `relation_evidence_extraction`

不同 task 可以共享 schema 片段，但不能使用一个覆盖全部场景的超级 prompt。

### 3.3 严格输入合同

建议的已验证请求至少包含：

```text
request_id
recognition_run_id
page_id
target_id
target_element_id
target_type
task_type
source_image_ref
source_image_hash
bbox
normalized_bbox
context_elements
model_profile
prompt_version
input_contract_version
output_contract_version
write_back
deadline
```

强制约束：

- 不包含 API key、token、密码或 Authorization。
- 图片引用必须来自来源事实读取路径。
- element/block 任务必须有合法 bbox；page 任务使用显式全页范围。
- bbox 满足 `x_min < x_max`、`y_min < y_max`，并位于图片尺寸内。
- `target_type` 必须被当前 `task_type` 允许。
- 上下文只携带白名单字段，candidate 不得描述成 formal。
- `write_back` 只能继承显式授权逻辑与，不能由 prompt 或模型输出改变。
- 未知字段、错误合同版本和目标串线在 provider 调用前 fail closed。

### 3.4 严格输出合同

每个 task 都应有独立的输出 schema 和白名单。共同校验至少包括：

1. 只接受 JSON object，不接受自由文本作为权威结果。
2. 未声明字段按合同策略拒绝，不能静默进入 payload 或图谱属性。
3. 状态、置信度和枚举必须合法。
4. observation/interpretation 必须绑定本次请求中的目标。
5. 返回目标数和 ID 必须与请求允许范围一致。
6. 不允许生成 `source_fact`、`derived_relation` 或 `formal_relation`。
7. candidate 只能保持候选语义。
8. 合同失败不能进入 05 融合，也不能产生图谱内语义证据。

### 3.5 局部 bbox 策略

推荐“局部主图 + 最小上下文”：

1. block/element 任务以目标 bbox 为主。
2. 按 task 配置有限 padding，并裁剪到页面边界。
3. 需要空间上下文时，可附低分辨率页面上下文图或结构化邻接摘要；不默认用整页高分辨率输入。
4. 页面摘要明确使用整页。
5. 记录原始 bbox、裁剪 bbox、padding、原图/裁剪尺寸、缩放比例和坐标变换。
6. crop hash 由来源图片 hash、bbox、padding 和 preprocessing version 决定。
7. 裁剪图只存在于内存或受控临时文件，成功、失败和取消路径均清理。
8. 不保存 Base64；日志只记录字节数、mime type、hash 和尺寸。

### 3.6 Run 与 attempt 合同

一次逻辑 `RecognitionRun` 可以包含多个 `RecognitionAttempt`。建议 attempt 字段：

```text
attempt_id
recognition_run_id
attempt_number
provider
model_name
request_fingerprint
prompt_version
output_contract_version
started_at
finished_at
latency_ms
status
retry_reason
provider_request_id
input_usage
output_usage
estimated_cost
actual_cost
currency
rate_card_version
error_category
safe_error_summary
```

关键规则：

- attempt 是运行审计，不是图谱语义证据。
- 输入校验失败发生在供应商调用前，不创建 provider attempt。
- 失败 attempt 不生成 observation/interpretation。
- 只有最终通过合同校验的结果可以投影为语义证据。
- attempt 重试不得偷偷更换 task、目标、bbox 或 prompt version。
- 显式模型 fallback 若未来支持，必须形成新的 attempt 并保留原因。

### 3.7 重试策略

| 情况 | 是否重试 | 处理 |
|---|---|---|
| 输入合同错误、bbox 越界 | 否 | 调用前失败 |
| 认证、权限、不支持模型 | 否 | 脱敏配置或能力错误 |
| 429 | 是 | 优先遵守 `Retry-After`，否则指数退避加抖动 |
| 暂时性 5xx、连接重置 | 是 | 有限重试，受 deadline 和最大 attempts 约束 |
| 供应商超时 | 可重试 | 仅剩余时延预算足够时 |
| JSON 非法 | 最多一次 | 使用同 task 的“按原合同重新输出”attempt |
| JSON 合法但 schema 失败 | 默认不重试或最多一次 | 只修复结构问题；越权事实直接失败 |
| `ambiguous`、`not_found` | 否 | 属于业务结果，不是传输故障 |

建议首版同步执行，默认最大 3 次 attempt，其中结构修复最多 1 次。具体值由策略注入，不写死在 Qwen adapter。03 按最坏 attempts 估算；04 每次重试前再次检查剩余 deadline。

### 3.8 成本与延迟

必须区分：

- **预计成本/延迟：** 03 调用前估算，用于门控。
- **实际 usage：** 04 从供应商响应提取，不可得时标记 `unavailable`。
- **核算成本：** 按实际 usage 和版本化费率快照计算，不能把估算写成账单。
- **端到端延迟：** 包括验证、预处理、所有 attempts、退避和输出校验。

建议延迟摘要：

```text
input_validation_ms
preprocessing_ms
provider_ms_by_attempt
backoff_ms
output_validation_ms
total_ms
```

建议成本摘要：

```text
estimate_status
estimated_cost
actual_usage_status
input_tokens_or_units
output_tokens_or_units
image_units
actual_cost
currency
rate_card_version
```

费率通过版本化 profile 注入，不能散落在 prompt 或业务代码。没有官方 usage 或适用费率时，`actual_cost` 必须为空并解释原因，不能填 0。

### 3.9 脱敏与数据最小化

统一脱敏至少覆盖：

- Authorization、API key、token、密码和 cookie。
- 供应商请求/响应 header。
- 本地绝对 `image_path` 和用户目录。
- 原图、crop、Base64 和 data URL。
- prompt 中非任务必需的页面文本、候选解释和个人信息。
- 供应商错误体中的请求回显、header、路径和 payload。
- traceback、Neo4j/Cypher 内部细节和环境变量。
- 不属于任务输出合同的未知字段。

建议三种安全投影：

1. **执行内投影：** provider adapter 完成调用所需的最小数据。
2. **审计投影：** hash、版本、目标 ID、attempt、usage、分类错误和安全摘要。
3. **对外投影：** 回答和排障所需字段，不含原始请求、完整 prompt、路径或内部错误。

脱敏必须在日志、异常、run/attempt 存储、payload 保存和 adapter 响应每个出口执行，不能只依赖 `repr=False`。

### 3.10 离线合同测试

使用固定图像 fixture、fake clock、fake sleeper、fake provider 和 `httpx.MockTransport`，不访问网络、不使用真实 key、不连接 Neo4j。

| 测试组 | 必测内容 |
|---|---|
| Task registry | 每个 task 有唯一 prompt/input/output 版本，目标类型和输出一致 |
| 输入合同 | 缺 ID、错误类型、bbox 越界、图片不可读、未知上下文、secret 字段 |
| Prompt 快照 | prompt 不漂移，不包含 secret、绝对路径或错误事实等级 |
| 局部裁剪 | 像素范围、padding、边界、坐标变换、hash、临时文件清理 |
| Provider 请求 | URL、模型、消息、mime、超时和字段最小化 |
| 输出合同 | success、partial、ambiguous、not_found、未知字段、错误枚举、串目标、事实越权 |
| Retry | 429、Retry-After、5xx、连接重置、超时、不可重试 4xx、deadline |
| Attempt | 编号递增，耗时/状态/原因独立，最终汇总正确 |
| Usage/成本 | usage 完整、缺失、异常数值、费率版本、估算与实际分离 |
| 脱敏 | key/header/path/Base64/error/traceback 不出现在输出与日志 |
| dry-run | 不保存 run log、Neo4j 证据或持久化 crop |
| cache | 命中不调用 provider、不创建 attempt、不重复计费 |
| 架构边界 | 不导入 Neo4j driver、repository、Cypher、QA adapter 或 CLI |

离线合同通过只证明本地请求、解析、重试和安全合同成立，不证明真实 Qwen 识别质量，也不证明 live Neo4j 写回成立。

## 4. 影响哪些已有模块？

### 4.1 高影响

| 模块 | 影响 | 保持边界 |
|---|---|---|
| `semantic_client.py` | 请求/结果需携带 task、合同、预处理引用、usage 与 provider metadata | 不读环境、不访问图谱、不决定 retry |
| `qwen_semantic_client.py` | 收窄为 Qwen provider adapter | key 仍只在 provider config，不承担写回 |
| `semantic_service.py` | 缓存 miss 后调用执行流水线，消费合同有效结果 | 继续负责缓存、语义 DTO、run/payload 和写回 |
| `recognition_run_log.py` | run 关联 attempts、实际成本和延迟摘要 | run 仍在图谱外 |
| `semantic_payload_store.py` | 保存最小化、不可变 provider/validated payload | 不保存图片、Base64、secret 或 header |
| `tool_models.py` / `assistant_models.py` | 补 task、策略、usage、cost、latency、safe error 和版本合同 | 默认 dry-run 和事实分层不变 |

### 4.2 中影响

| 模块 | 影响 |
|---|---|
| `assistant_recognition_budget.py` | 估算考虑最大 attempts、裁剪面积、模型 profile 和 deadline |
| `assistant_semantic_gap_decision.py` | 把 selected targets、deadline 和执行策略传给 04 |
| `semantic_image_inputs.py` | 从 bbox 引用衔接真实裁剪预处理 |
| `semantic_cache.py` | 继续包含 task、prompt、合同、preprocessing、bbox 和 image hash |
| `tool_facade.py` | 返回产品化运行摘要，不暴露 provider 请求或路径 |
| `tool_factory.py` | 注入 registry、preprocessor、retry、meter、redactor 和 provider |
| 05 证据融合 | 只接收合同有效结果，保留失败和实际指标 |
| 07 追溯反馈 | 关联 request、run、attempt、evidence、cost 和 latency |

### 4.3 低影响或不应直接修改

- 基础导入、geometry、mapping 和 Neo4j 来源事实 schema 不需要改变。
- 离线派生关系增强和 `CandidateReviewService` 不应被绕过。
- 现有 `DrawingGraphQAService`、只读 HTTP 和 MCP 保持兼容。
- 01 问题理解和 02 检索不承担 prompt、retry 或 provider 逻辑。

## 5. 技术方案

### 方案 A：直接增强现有 Qwen 客户端

把任务 prompt、裁剪、重试、输出校验、计量和脱敏全部加入 Qwen client。

优点：改动小，最快形成单供应商演示。  
缺点：传输、业务合同、图像处理和运行治理耦合；客户端会成为大杂烩；供应商替换和离线分层测试困难。

### 方案 B：独立供应商无关执行流水线

任务合同、预处理、prompt、retry/attempt、校验、计量和脱敏形成独立执行层；Qwen 只是 provider adapter。

优点：职责清晰、task 可版本化、bbox 可独立测试、run/attempt 边界稳定、易替换供应商、最符合现有 03/04/05 分层。  
缺点：初始模块和合同较多，需要控制首版范围，避免过度抽象。

### 方案 C：异步队列化识别作业平台

在方案 B 上增加 durable job、worker、队列、租约、取消、回调和独立运行数据库。

优点：适合批量、高并发、长任务和跨进程恢复。  
缺点：运维、一致性、幂等和测试成本最高；当前按需、小目标识别阶段没有足够收益。

## 6. 优缺点比较

| 维度 | A：增强 Qwen Client | B：独立执行流水线 | C：异步作业平台 |
|---|---|---|---|
| 初始改动 | 小 | 中 | 大 |
| 与现有分层一致性 | 一般 | 高 | 高，但增加基础设施 |
| task prompt | 易堆积分支 | 注册表隔离 | 同 B |
| 严格合同 | 供应商耦合 | 可复用、可版本化 | 可复用、可版本化 |
| bbox | 易混入 HTTP adapter | 独立可测 | 独立可测 |
| retry/attempt | 审计边界弱 | run/attempt 清晰 | 最完整 |
| 成本/延迟 | 单次统计为主 | 逐 attempt 和总计 | 含队列等待全链路 |
| 脱敏 | 多出口易漏 | 统一复用 | 还需覆盖队列存储 |
| 离线测试 | 供应商强耦合 | task/provider 分层 | 测试面最大 |
| 供应商替换 | 差 | 好 | 好 |
| 当前阶段复杂度 | 低 | 合理 | 过高 |

## 7. 推荐方案

### 7.1 推荐结论

推荐**方案 B：独立供应商无关识别执行流水线**。首版保持同步执行，预留异步 job port，但不引入队列、worker 或分布式调度。

理由：

1. 与现有 03 决策、04 执行、05 融合边界一致。
2. task-specific prompt 与输出合同可以共同版本化。
3. 能真正实施 bbox crop，而不是只把坐标写入 prompt。
4. 能清晰区分一个逻辑 run 与多个 provider attempts。
5. 能区分估算成本/时延与实际 usage/费用/端到端延迟。
6. 能把脱敏做成跨 provider、run、payload 和 adapter 的统一能力。
7. 可用 fake clock、fake sleeper、MockTransport 和固定图像完成完全离线的合同测试。
8. 不承担当前阶段不必要的异步运维复杂度。

### 7.2 推荐数据流

```text
RecognitionTarget[]
  -> 任务规格解析
  -> 严格输入校验
  -> 缓存二次检查
  -> 临时 bbox 裁剪与坐标变换
  -> task-specific prompt 渲染
  -> attempt 1
       -> provider transport
       -> usage/latency 采集
       -> 严格输出校验
  -> [仅可重试且预算允许] attempt 2..N
  -> 最终合同有效结果或稳定失败
  -> 最小化 payload + run/attempt 摘要
  -> TextObservation / Interpretation 投影
  -> write_back=false 临时返回
  -> write_back=true 受控保存
  -> EvidenceFusionService
```

### 7.3 推荐分阶段落地

1. **合同与离线骨架：** task registry、输入/输出合同、prompt renderer、provider port、固定 fixture。
2. **bbox 与安全：** 临时 crop、坐标变换、crop hash、统一 redactor。
3. **retry 与计量：** error taxonomy、deadline、attempt、usage、成本和分段延迟。
4. **语义服务衔接：** 缓存 miss 执行，只投影合同有效结果，回归 dry-run/payload/write-back。
5. **分层 live 验收：** DashScope 单页 dry-run、人工黄金集、独立测试库 Neo4j 写回。

每阶段独立验证；live DashScope 成功不等于 live Neo4j 写回成功。

## 8. 风险

| 风险 | 后果 | 缓解 |
|---|---|---|
| task/prompt 膨胀 | 版本难管理 | 首版限定七类 task，registry 管理，共享 schema 片段 |
| 输入合同过松 | 串目标、secret、候选诱导 | 未知字段拒绝、上下文白名单、调用前 fail closed |
| 输入合同过严 | 供应商小变化导致失败 | provider 格式与领域合同分层，兼容映射显式版本化 |
| bbox 过紧 | 丢失标题、引线和上下文 | task-specific padding，必要时附低分辨率上下文，黄金集比较 |
| bbox 过大 | 成本、延迟、幻觉和隐私上升 | 最小目标、面积上限、记录实际 crop |
| 坐标变换错误 | 结果无法映射原图 | 保存变换，像素级 fixture 测试，不改来源 bbox |
| retry 放大成本 | 费用和延迟失控 | max attempts、deadline、预算余量、逐 attempt 计量 |
| 误重试业务结果 | ambiguous/not_found 重复付费 | 明确区分业务结果与传输/结构失败 |
| run/attempt 混淆 | 重复证据或错误计费 | 一个 run 多个 attempts，仅最终有效输出生成证据 |
| 超时后重复扣费 | 供应商状态未知 | provider request ID；支持时使用幂等键；成本允许 unknown |
| usage 缺失或费率变化 | 成本数字失真 | 费率版本化，actual/estimated/unavailable 三态 |
| 图纸泄露 | 合规与商业风险 | 最小 bbox、内存裁剪、禁止永久 crop/Base64、授权测试页 |
| prompt 注入 | 图中文字被当作指令 | 固定 system 约束、结构化上下文、输出事实等级校验 |
| 输出越权 | semantic 冒充 source/formal | schema 禁止，05/06 再次保护 |
| 缓存污染 | 不同任务复用错误结果 | key 包含 task、模型、prompt、合同、预处理、bbox、image hash |
| payload 过量 | 泄露与存储负担 | 白名单最小化、不可变引用、访问和保留策略 |
| 同步超时 | adapter 用户体验差 | 首版限制目标数/deadline，达到阈值后再演进 C |
| 供应商漂移 | 离线通过、live 失败 | provider 合同测试 + 小型 live smoke，记录模型版本 |
| 验证误报 | 高估可用性 | 离线、live DashScope、黄金集、live Neo4j 分开报告 |

## 9. 推荐验收标准

### 9.1 功能合同

- 七类首版 task 均有独立、版本化任务规格。
- provider 调用前完成严格输入校验。
- element/block 实际发送局部 crop；page summary 明确发送整页。
- 每次供应商调用有唯一 attempt，全部关联同一个逻辑 run。
- 只有最终通过输出合同的结果能生成 observation/interpretation。
- 模型不能生成或提升 source、derived 或 formal 事实。

### 9.2 成本与性能

- 03 的预计成本/时延与 04 的实际 usage/费用/延迟分别记录。
- 重试计入总延迟和 attempt 统计；实际费用不可得时不填 0。
- 超过 deadline、最大 attempts 或预算时停止并返回稳定原因码。
- cache 命中不发 provider attempt、不产生新费用、不创建持久化 run。

### 9.3 安全

- key、Authorization、密码、绝对路径、Base64、原图和 crop 不出现在日志、错误、trace 或对外响应。
- crop 不持久化，所有退出路径均清理临时资源。
- `write_back=false` 下不保存 run log、Neo4j 证据或跨请求持久化结果。
- candidate 始终保持 candidate，`matched_candidate` 不等于 formal。

### 9.4 验证分层

- 单元测试：任务、校验、裁剪、重试、计量和脱敏纯逻辑。
- 离线合同测试：固定响应、请求快照和错误矩阵，无网络、密钥和 Neo4j。
- live DashScope：授权测试图的单页 dry-run、usage、延迟和输出有效性。
- 黄金集：按 task 评估准确率、漏识别、幻觉和 bbox 策略。
- live Neo4j：独立测试库、显式 `write_back=true`、幂等、stale、payload_ref 和查询投影。

## 10. 最终决策

1. 当前架构支持本需求增量落地，但现有 Qwen 客户端不能视为产品化完成。
2. 新增模块集中在 04 多模态执行层，不重建图谱、不引入独立 OCR、不侵入 03 或 05 的职责。
3. 推荐独立供应商无关执行流水线，首版同步执行，Qwen 只作 provider adapter。
4. task-specific prompt 与严格输出合同共同版本化；局部 bbox 必须真实裁剪并保留坐标变换。
5. 一个 `RecognitionRun` 包含多个 `RecognitionAttempt`；重试、实际用量、成本和延迟按 attempt 记录并在 run 汇总。
6. 脱敏覆盖输入、prompt、HTTP、错误、payload、trace 和对外响应的所有出口。
7. 离线合同测试是首要验收门，但不能替代 live DashScope、黄金集和 live Neo4j 的分层验证。

本报告最初只形成产品化架构分析与推荐方案；后续已按 proposal/design/tasks 实施 Task 1-43 对应的执行层与接入（见下方实施状态），未改变任何来源事实、候选关系、正式关系或数据库数据。

## 实施状态（2026-08-13）

- 已实现：七类 task 注册表、严格输入/输出合同、局部 bbox 内存裁剪、task-specific prompt、provider port（Fake/Qwen adapter）、有界重试与 attempt、usage/成本/延迟计量、统一脱敏、图谱外 attempt log、`MultimodalRecognitionExecutionService` 执行编排。
- 已接入：`SemanticRecognitionService` 缓存二次校验/执行兼容分组/语义 DTO 投影/受控写回、Facade 兼容入口（`execution_policy`）、产品化配置与 Factory 装配。
- 边界保持：默认 `write_back=false`；`RecognitionRun`/`RecognitionAttempt` 图谱外；`TextObservation` 与三类 `Interpretation` 图谱内；relation 输出只能为 `candidate_relation`，候选不等于正式事实；无 OCR；不改变 Neo4j 来源事实 schema。
- 验证分层：全量离线单元/合同测试 1808 通过、4 跳过；live DashScope、黄金集、live Neo4j、Codex/MCP 未声称通过。
