# 04 多模态识别模块需求与设计

## 1. 模块目标

根据语义缺口判断产生的最小目标集合，调用 Qwen 对页面图像、局部 bbox、元素类型和图谱上下文进行联合理解，输出受约束的文字观察、语义解释和运行指标。

本模块不建设独立 OCR 流程。文字读取只是多模态理解结果的一部分，模型还需要理解图形、构件、表格、断面标记及其上下文。

## 2. 当前架构现状

当前工作区已经具备：

- `MultimodalRecognitionClient` 协议和 fake client。
- 可选 `QwenMultimodalRecognitionClient`，通过 DashScope OpenAI-compatible chat completions 调用。
- `SemanticRecognitionService`、图像输入构造、语义缓存、payload 和 run log 边界。
- `DrawingGraphToolFacade.recognize_page_semantics()`。
- `scripts/drawing_graph_tool.py recognize-page-semantics` 受控入口。
- `DASHSCOPE_API_KEY` 仅从运行环境读取，默认不启用 Qwen。

当前 Qwen 客户端已完成离线合同测试；live DashScope 识别效果与 live Neo4j 写回仍需分别验收。

## 3. 输入契约

`RecognitionRequest`：

```text
recognition_run_id
page_id
target_element_id
target_type
image_path
bbox
normalized_bbox
context_elements[]
task_type
model_profile
prompt_version
output_contract_version
write_back
```

`task_type` 首版至少支持：

```text
page_summary
element_text_observation
block_semantic_identification
basic_info_interpretation
table_interpretation
section_label_observation
relation_evidence_extraction
```

约束：

- 请求不得包含 API key。
- `image_path` 必须来自已验证来源事实，不接受模型生成路径。
- bbox 必须在图片范围内；页面任务可使用全页范围。
- `write_back` 缺省为 `false`。
- `write_back` 必须等于请求授权、模块策略和运行环境权限的逻辑与；任一条件为 false 都不得写回。
- 每个请求绑定明确的 prompt 和输出契约版本。

## 4. 输出契约

`RecognitionResult`：

```text
recognition_run_id
status
observations[]
interpretations[]
payload_ref
confidence
uncertainty[]
model_profile
prompt_version
output_contract_version
token_usage
cost
latency_ms
cache_key
warnings[]
```

`status` 至少包括：

```text
confirmed
partial
ambiguous
not_found
recognition_failed
```

完整供应商响应或结构化解析结果进入不可变 payload；常用字段投影到 observation/interpretation，避免把大嵌套 JSON 直接写入 Neo4j 属性。

## 5. Prompt 与输出 Schema

Prompt 不采用一个覆盖所有任务的通用模板。每个 `task_type` 对应：

- 明确的系统任务说明。
- 页面、目标元素和上下文说明。
- 允许输出的字段和枚举。
- 不确定性表达规则。
- 禁止把猜测写成来源事实的约束。
- JSON Schema 或等价的严格结构化输出合同。

模型输出必须先经过以下校验：

1. 响应是否为合法 JSON。
2. 是否符合任务对应的字段白名单和类型。
3. 状态、置信度和枚举是否合法。
4. observation/interpretation 是否绑定请求目标。
5. 是否包含不允许的正式关系或来源事实声明。

校验失败不得以成功结果进入后续融合。

## 6. 图像与上下文策略

- block/element 任务优先使用目标 bbox，并可附带有限周边上下文。
- 页面摘要使用整页图像，同时提供图谱中已有元素类型和 bbox 摘要。
- 断面匹配任务分别识别 `CrossSection` 与候选 `BlockCaption`，不把两个对象裁成无法追溯的合成事实。
- 图片编码、尺寸限制和压缩不得改变 bbox 坐标语义；如缩放，必须保存坐标变换。
- 上下文只提供当前任务必需信息，避免把候选关系描述成已确认关系诱导模型。

## 7. 执行与重试

建议重试策略：

- 参数或 Schema 错误：不重试。
- 认证失败：不重试，并输出脱敏配置错误。
- 429、暂时性 5xx、连接重置：指数退避并限制次数。
- 超时：允许有限重试；总时延受请求策略约束。
- 非法 JSON：最多进行一次结构修复重试，仍失败则 `recognition_failed`。

所有重试归属于同一个产品请求，但每次供应商调用应有可观测的 attempt 信息。不得在错误或日志中输出 API key、完整 Authorization header 或本地敏感路径。

## 8. 缓存与写回

缓存键至少包含：

```text
image_hash
bbox
target_type
task_type
model_profile
prompt_version
output_contract_version
```

语义缺口模块已确认缓存未命中后，本模块才发起真实调用。

- `write_back=false`：返回临时 observation/interpretation，不持久化 run log、Neo4j 证据或正式关系。
- `write_back=true`：仅通过既有 semantic service 和受控 repository 写入 run log 与语义证据。
- 无论是否写回，模型结果都不能覆盖来源节点字段或直接提升候选关系。

## 9. 不负责的内容

- 不决定是否应该识别。
- 不执行自然语言问题分类。
- 不从 Neo4j 自行查询目标。
- 不融合图谱事实与模型结果。
- 不生成最终用户答案。
- 不直接建立正式图谱关系。

## 10. 测试与验证

### 10.1 离线测试

- 使用 `httpx.MockTransport` 验证请求构造和结构化解析。
- 覆盖各 task type 的 prompt 版本和输出 Schema。
- 覆盖 4xx、5xx、429、超时、非法 JSON、字段缺失和敏感信息脱敏。
- 验证 dry-run 无持久化副作用。
- 验证 cache key 对图片、bbox、模型、prompt 和合同版本敏感。

### 10.2 Live DashScope 验收

- 使用明确授权的测试页面执行单页 dry-run。
- 不在命令或输出中暴露 `DASHSCOPE_API_KEY`。
- 记录模型、延迟、token、成本和结构化输出有效性。
- 以人工标注的小型黄金集评估字段准确率、漏识别和幻觉。
- live DashScope 通过不等于 live Neo4j 写回通过。

### 10.3 Live Neo4j 验收

- 仅在独立测试库和显式 `write_back=true` 下执行。
- 验证 `RecognitionRun` 图谱外、语义证据图谱内及其 ID 关联。
- 验证幂等、stale 标记、payload_ref 和查询投影。

## 11. 验收标准

- 支持首版全部 `task_type` 并输出严格结构化结果。
- 不引入独立 OCR 引擎。
- 模型失败、非法输出和超时均转换为稳定错误状态。
- dry-run 不产生持久化副作用。
- API key 不进入领域 DTO、命令参数、日志或输出。
- 模型输出只能成为语义 observation、interpretation 或 candidate evidence。
- 离线、live DashScope 和 live Neo4j 验证状态分开报告。

## 12. 实施状态与落地（2026-08-13）

本阶段文档对应的 04 执行层已实现并通过离线合同测试，落地内容包括：

- 新增执行模块：`recognition_models.py`、`recognition_tasks.py`、`recognition_input_validation.py`、`recognition_image_preprocessing.py`、`recognition_prompting.py`、`recognition_output_validation.py`、`recognition_retry.py`、`recognition_metrics.py`、`recognition_redaction.py`、`recognition_attempt_log.py`、`recognition_execution.py`。
- 七类 task 均注册到不可变 `RecognitionTaskRegistry`，每个任务绑定目标白名单、prompt/输入/输出合同版本、crop policy、必需输出与写回声明。
- 请求合同由 `RecognitionExecutionRequest` 表达：run/page/targets、model、prompt、输入/输出合同、preprocessing、deadline、`write_back`；provider port 只接收已渲染 prompt 与内存图。
- 输出合同由 `RecognitionOutputValidator` 强制：JSON object、字段白名单、类型/枚举/置信度、目标归属、事实等级；`ambiguous`/`not_found`/`contract_failed` 不产生可写语义证据。
- 重试与 attempt：429/暂时性 5xx/超时有限重试，认证/权限/永久错误不重试，非法 JSON/schema 最多一次结构修复；每次供应商调用生成独立 attempt，deadline 与预算门控在每次调用前执行。
- 计量与脱敏：实际 usage/成本/分阶段延迟汇总（缺失为 `unavailable`，不写 0）；统一 fail-closed 脱敏覆盖 error/payload/trace。
- 编排与接入：`MultimodalRecognitionExecutionService.execute()` 为唯一执行入口；`SemanticRecognitionService` 负责缓存二次校验、执行兼容分组、语义 DTO 投影与受控写回；Factory 装配完整流水线，默认 Fake provider。
- 写回边界：默认 `write_back=false`；`write_back=true` 仅保存脱敏 run/attempt/payload 与允许矩阵中的语义证据；page summary 与 relation evidence 只保留图谱外审计，不建节点/边。
- 验证分层：全量离线单元/合同测试 1808 通过、4 跳过；live DashScope、黄金集、live Neo4j、Codex/MCP 未声称通过。
