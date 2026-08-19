# Adapter 与产品级验收 Design

## 1. 系统架构变化

新增产品级 adapter 层，位于外部协议和 `DrawingAssistantService` 之间：

```text
Product CLI / Product HTTP / Product MCP
  -> DrawingAssistantService.answer()
       -> 01 QuestionUnderstandingService
       -> 02 GraphRetrievalService
       -> 03 SemanticGapDecisionService
       -> 04 facade recognize_semantic_targets(write_back=false)
       -> 05 EvidenceFusionService(write_back_policy=None)
       -> 06 AnswerGenerationService
       -> optional 07 TraceabilityService
  -> DrawingGraphToolFacade
  -> ports / services / controlled repositories
  -> Neo4j / run log / payload store / optional provider
```

旧 QA 链路保持不变：

```text
QA CLI / QA HTTP / QA MCP
  -> DrawingGraphQAService.ask()
  -> DrawingGraphToolFacade
  -> ports / services / controlled repositories
  -> Neo4j
```

两条链路并列存在：

- 旧 QA adapter 负责六类固定、窄口径、只读查询。
- 产品 adapter 负责自然语言产品问答。
- 产品 adapter 不调用旧 QA HTTP/MCP/CLI 子进程。
- 旧 QA adapter 不反向依赖产品 adapter。

## 2. 新增模块

### 2.1 产品 adapter 共享序列化

建议新增 `src/drawing_graph/assistant_adapter_serialization.py`。

职责：

- 将 `AnswerPackage` 转换为 JSON-safe dict。
- 生成产品 HTTP/CLI/MCP 可复用的成功/失败 envelope。
- 复用或包装 `qa_serialization.to_jsonable()` 与 `sanitize_error_message()`。
- 统一错误类别，例如 `invalid_argument`、`read_only_violation`、`timeout`、`concurrency_limit_reached`、`configuration_failed`、`initialization_failed`、`assistant_call_failed`、`internal_error`。
- 保证错误不输出 traceback、Neo4j URI、密码、token、Authorization、完整 prompt、完整 payload 或本地绝对敏感路径。

### 2.2 产品 HTTP 协议模型

建议新增 `src/drawing_graph/assistant_http_models.py`。

职责：

- 定义 `HttpAssistantRequest`、`HttpAssistantScopeHint`、`HttpAssistantAnswer`、`HttpAssistantSuccessEnvelope`、`HttpAssistantErrorEnvelope`、`HttpAssistantHealthResponse`。
- 使用严格字段白名单，拒绝未知字段。
- 将 HTTP 请求转换为 `AssistantRequest`。
- 不提供 `write_back` 字段；如为了兼容错误提示而检测到 `write_back=true`，必须返回 403 或稳定只读拒绝错误。
- 限制 question、context、scope ids、request_id 等字段长度。

### 2.3 产品 HTTP runtime

建议新增 `src/drawing_graph/assistant_http_runtime.py`。

职责：

- 从调用方传入的 config 创建 Neo4j driver。
- 调用 `create_neo4j_tool_facade(driver)`。
- 调用 `create_drawing_assistant_service(facade, ...)`。
- 管理 driver/facade/service 生命周期和幂等关闭。
- 支持 fake factory 注入，便于不连接 Neo4j 的测试。

只有 runtime 和启动脚本可以知道 driver；HTTP route handler 只能拿到 service。

### 2.4 产品 HTTP app

建议新增 `src/drawing_graph/assistant_http.py`。

职责：

- 提供 `create_app(config, runtime_factory)`。
- 路由：
  - `GET /health/live`
  - `GET /health/ready`
  - `POST /api/v1/drawing-assistant/ask`
- 复用 QA HTTP 的 request id、安全响应头、请求体大小限制、认证、并发上限和请求超时模式。
- 将 `AnswerPackage` 映射为稳定 HTTP envelope。
- `ready` 只说明 runtime 是否装配，不声称 live Neo4j 查询已通过。

### 2.5 产品 HTTP 启动脚本

建议新增 `scripts/serve_drawing_assistant.py`。

职责：

- 从环境变量加载产品 HTTP config。
- 启动单 worker Uvicorn。
- 不接受 Neo4j 密码、HTTP token、DashScope API key 作为命令行参数。
- startup error 输出脱敏 stderr。

### 2.6 产品 MCP 模型

建议新增 `src/drawing_graph/assistant_mcp_models.py`。

职责：

- 定义一个产品级只读 tool 的输入模型，例如 `AskDrawingAssistantInput`。
- 支持字段：`question`、`request_id`、`language`、`scope_hint`、`allow_recognition`、`answer_format`。
- 不接受 `write_back`、Cypher、Neo4j URI、credentials、file path、driver/session 或底层对象字段。
- 转换为 `AssistantRequest`，固定 `allow_write_back=false`。

### 2.7 产品 MCP tools/runtime/server

建议新增：

- `src/drawing_graph/assistant_mcp_tools.py`
- `src/drawing_graph/assistant_mcp_runtime.py`
- `src/drawing_graph/assistant_mcp_server.py`
- `scripts/serve_drawing_assistant_mcp.py`

职责：

- server 暴露一个本地 STDIO 只读 tool，例如 `ask_drawing_assistant`。
- tool handler 只调用一次 `DrawingAssistantService.answer()`。
- structuredContent 来自 `AnswerPackage` JSON-safe 投影。
- TextContent 只概述状态、简短回答、claim/warning/unsupported 数量，不新增事实，不重排 fact kind。
- stdout 只承载 MCP 协议帧，日志和错误走 stderr。

### 2.8 产品验收文档

建议新增 `docs/acceptance/PRODUCT_ADAPTER_ACCEPTANCE.md`。

职责：

- 记录本轮产品 adapter 的命令、结果、时间和范围。
- 分层列出 unit/fake/offline、HTTP TestClient/socket、MCP in-memory、MCP STDIO、旧 QA 兼容、live Neo4j、live DashScope、真实文本 provider、真实 MCP 宿主注册。
- 明确 skipped 不等于 live 通过。

## 3. 修改模块

| 模块 | 修改原则 |
|---|---|
| `drawing_assistant_factory.py` | 可增加产品 adapter 所需的注入参数，但不得读取 env、创建 driver 或连接 Neo4j。 |
| `assistant_models.py` | 只做向后兼容字段/枚举扩展；不得导入 HTTP/MCP/Neo4j/provider。 |
| `qa_serialization.py` | 如复用不足，新增产品 adapter serialization，不破坏旧 QA envelope。 |
| `README.md`、`Module.md`、`architecture.md` | 实施完成后同步已实现产品 HTTP/MCP 和验收状态；未 live 验证必须写未验证。 |
| `docs/acceptance/ANSWER_GENERATION_MVP_ACCEPTANCE.md`、`TRACE_FEEDBACK_ACCEPTANCE.md` | 不改写历史结果；新验收写入独立产品 adapter 文档。 |
| 旧 QA HTTP/MCP | 默认不修改；如果必须抽取共享测试工具，只做无行为变化的辅助改动。 |

## 4. 数据模型变化

本需求不新增 Neo4j schema。

明确说明：

- 不新增 Neo4j 节点、关系、索引、约束或迁移。
- 不新增 `RecognitionRun` Neo4j 节点；`RecognitionRun` 仍为图谱外运行日志。
- `TextObservation` 与 `Interpretation` 的图谱内语义证据模型不因 adapter 改变。
- 产品 adapter 只序列化 `AnswerPackage`、trace warning 和诊断字段，不把产品运行记录写入业务图谱。
- trace/feedback 若未来需要外部持久化，应继续通过 `TraceStorePort` / `FeedbackStorePort`，不在本需求中改 Neo4j 业务 schema。

## 5. API 设计

### 5.1 产品 HTTP

建议首版 HTTP endpoint：

```text
POST /api/v1/drawing-assistant/ask
```

请求字段：

| 字段 | 说明 |
|---|---|
| `request_id` | 可选；未提供时生成。 |
| `question` | 必填自然语言问题。 |
| `language` | 默认 `zh-CN`。 |
| `scope_hint` | 可选 page/block/element/cross_section/table/table_caption/claim 等稳定业务 ID。 |
| `conversation_context` | 可选有限上下文。 |
| `allow_recognition` | 默认 true；只表示可按需识别。 |
| `answer_format` | 默认 `json_and_text`。 |

禁止字段：

- `write_back`
- `allow_write_back`
- `cypher`
- `neo4j_uri`
- `password`
- `token`
- `api_key`
- `driver`
- `session`
- `repository`

成功响应：

```text
{
  "ok": true,
  "data": {
    "answer_contract_version": "...",
    "request_id": "...",
    "status": "...",
    "machine_answer": {},
    "text_answer": "...",
    "claims": [],
    "citations": [],
    "warnings": [],
    "unsupported_parts": []
  },
  "meta": {
    "request_id": "...",
    "adapter": "drawing-assistant-http",
    "contract_version": "drawing-assistant-http-v1"
  }
}
```

错误响应：

```text
{
  "ok": false,
  "error": {
    "code": "invalid_argument",
    "message": "sanitized message",
    "retryable": false
  },
  "meta": {
    "request_id": "...",
    "adapter": "drawing-assistant-http"
  }
}
```

HTTP 状态建议：

| 情况 | HTTP |
|---|---|
| 成功业务状态，包括 partial/unsupported/clarification_required | 200 |
| 参数错误 | 400 |
| 认证失败 | 401 |
| 写回请求被拒绝 | 403 |
| 请求体过大 | 413 |
| 并发上限 | 429 |
| 请求超时 | 504 |
| 初始化或内部错误 | 500/503 |

### 5.2 产品 MCP

建议首版工具：

```text
ask_drawing_assistant
```

输入：

| 字段 | 说明 |
|---|---|
| `question` | 必填自然语言问题。 |
| `request_id` | 可选。 |
| `language` | 默认 `zh-CN`。 |
| `scope_hint` | 可选稳定业务 ID。 |
| `allow_recognition` | 默认 true。 |

输出：

- `structuredContent`：产品 `AnswerPackage` JSON-safe 投影，含 status、machine_answer、text_answer、claims、citations、warnings、unsupported_parts、recognition_run_ids。
- `content`：简短 TextContent，只概述状态、`text_answer`、claim/warning/unsupported 数量。
- `isError=true`：仅用于输入错误、只读拒绝、service 异常或 adapter 异常；业务 `partial` 不等于 tool error。

### 5.3 旧 QA 兼容

旧 QA 接口继续保留：

- `POST /api/v1/drawing-qa/ask`
- `GET /api/v1/drawing-qa/pages/{page_id}/summary`
- `GET /api/v1/drawing-qa/blocks/{block_id}/relations`
- `ask_drawing_page`
- `ask_drawing_block`
- `list_drawing_candidates`
- `get_section_match_status`
- `get_table_caption_status`
- `get_drawing_diagnostics`

本需求不改变这些路径、工具名和只读语义。

## 6. 异常处理

### 6.1 稳定错误类别

产品 adapter 使用稳定错误类别，不透出底层异常类：

| 类别 | 来源 |
|---|---|
| `invalid_argument` | 请求字段错误、scope 冲突、未知字段。 |
| `read_only_violation` | 写回字段或 `allow_write_back=true`。 |
| `configuration_failed` | env/config 缺失或不合法。 |
| `initialization_failed` | driver/facade/service 装配失败。 |
| `assistant_call_failed` | service 调用失败。 |
| `timeout` | HTTP 请求超时或 MCP adapter timeout。 |
| `concurrency_limit_reached` | HTTP 并发容量不足。 |
| `request_too_large` | HTTP body 超限。 |
| `unauthorized` / `forbidden` | HTTP 认证或权限失败。 |
| `internal_error` | 未分类异常，脱敏。 |

### 6.2 HTTP 超时与并发

- 使用显式并发上限，超出返回 429。
- 每个请求有 adapter 级等待超时，超时返回 504。
- 超时不自动扩大 scope、不自动写回、不自动调用其他工具。
- 无论成功、失败或超时，必须释放并发容量。

### 6.3 MCP 错误

- 输入模型校验失败返回稳定 `invalid_argument`。
- tool unexpected error 返回 `internal_error` 并脱敏。
- `partial`、`unsupported`、`clarification_required` 是业务状态，不默认标记 `isError=true`。
- stdout 不输出日志、traceback 或调试文本。

## 7. 安全方案

### 7.1 只读边界

只读模块：

- 产品 HTTP route handler。
- 产品 MCP tool handler。
- 产品 adapter serialization。
- 产品 HTTP/MCP 协议模型。
- 产品 HTTP/MCP server。
- `DrawingAssistantService.answer()` 的问答路径。
- 旧 QA CLI/HTTP/MCP。

可写或潜在可写模块：

- `SemanticRecognitionService` 在显式 `write_back=true` 且授权通过时可写 run log/语义证据。
- `CandidateReviewService` 在显式审核和硬规则通过时可提升候选。
- `TraceStorePort` / `FeedbackStorePort` 可写产品运行审计/反馈 store，不写 Neo4j 业务事实。

本需求新增的产品 HTTP/MCP 问答 adapter 不提供写回授权。写回授权控制点：

- `AssistantRequest.allow_write_back` 在 adapter 层固定 false 或禁止输入。
- `DrawingAssistantService._validate_read_only()` 在下游调用前拒绝 `allow_write_back=true`。
- 04 识别调用固定 `write_back=false`。
- 05 融合调用固定 `write_back_policy=None`。
- 反馈正式提升只能通过 `FeedbackService -> CandidateReviewAdapter -> CandidateReviewService` 的独立授权路径，不属于本需求首批只读问答 adapter。

### 7.2 禁止依赖

产品 adapter 禁止：

- 直接创建 Neo4j driver 并执行查询逻辑。
- 拼写或执行 Cypher。
- 调用 repository 写回方法。
- 调用 `block_relation_enrichment.py` 规则函数。
- 调用 Qwen/DashScope provider。
- 调用旧 QA HTTP/MCP/CLI 子进程作为中间层。
- 把 `candidate_relation` 或 `matched_candidate` 写成 `formal_relation`。

runtime 可以创建 driver，但只能用于装配 `create_neo4j_tool_facade(driver)` 和 service，不能在 route/tool 中直接使用。

### 7.3 数据最小化与脱敏

- 不在请求、响应、日志或错误中输出 Neo4j 密码、API key、token、Authorization、完整 prompt、完整 payload 或底层 traceback。
- `image_path`、bbox、payload_ref 等证据字段按 `AnswerPackage` 最小引用输出，不由 adapter 额外补查。
- 图纸文字、OCR 文本、模型解释都视为数据，不作为系统指令、shell、Cypher 或配置执行。

## 8. 依赖方向

允许方向：

```text
assistant_http / assistant_mcp
  -> assistant_adapter_serialization
  -> drawing_assistant_service / drawing_assistant_factory
  -> assistant_* product modules
  -> DrawingGraphToolFacade
  -> ports/services/repository
```

runtime 允许：

```text
assistant_http_runtime / assistant_mcp_runtime
  -> create_neo4j_tool_facade(driver)
  -> create_drawing_assistant_service(facade)
```

禁止方向：

```text
assistant_http / assistant_mcp
  -> Neo4j driver / repository / Cypher / Qwen client / offline rule functions

qa_http / qa_mcp
  -> assistant_http / assistant_mcp
```

## 9. 与现有模块的兼容策略

- 旧 QA 和产品 assistant 分离命名、分离路径、分离 MCP 工具，避免工具合同漂移。
- 旧 QA HTTP/MCP 回归测试必须在产品 adapter 任务中运行。
- 产品 adapter 复用模式，不复用旧 QA 业务对象；不把 `QAAnswer` 和 `AnswerPackage` 混成一个输出合同。
- 产品 CLI 作为已有同级 adapter 保持兼容，不新增 `--write-back`。
- 若抽取共享 middleware 或测试 helper，应保持旧 QA 行为逐字节或字段级兼容。
- 文档同步时必须写清：旧 QA HTTP/MCP 已实现，产品 HTTP/MCP 是新增能力；未运行 live 项仍是未验证。

## 10. 验证方案

### 10.1 单元与合同

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_http_models tests.test_assistant_adapter_serialization tests.test_assistant_mcp_models -v
```

验证：

- request 到 `AssistantRequest` 的转换。
- unknown/sensitive/write-back 字段拒绝。
- `AnswerPackage` envelope 稳定。
- candidate/formal 文案和结构不混淆。
- 错误脱敏。

### 10.2 HTTP adapter

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_http tests.test_assistant_http_runtime tests.test_assistant_http_cli tests.test_assistant_http_boundaries -v
```

验证：

- `/health/live`、`/health/ready`、`/api/v1/drawing-assistant/ask`。
- 200/400/401/403/413/429/504/500/503 映射。
- request id、安全头、body limit、concurrency、timeout。
- route 不导入 forbidden backends。

### 10.3 MCP adapter

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_mcp_models tests.test_assistant_mcp_tools tests.test_assistant_mcp_runtime tests.test_assistant_mcp_server tests.test_assistant_mcp_cli tests.test_assistant_mcp_boundaries -v
```

验证：

- tools/list、tools/call、input schema。
- structuredContent/TextContent 同源。
- `partial` 不等于 tool error。
- STDIO stdout 纯净、stderr 脱敏。
- MCP 不调用 HTTP/CLI 子进程。

### 10.4 产品三入口 fake E2E

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_drawing_assistant_cli tests.test_drawing_assistant_e2e tests.test_product_adapter_e2e -v
```

验证：

- CLI/HTTP/MCP 对 fake service 的 answered、partial、clarification_required、unsupported、recognition_failed。
- 结构化答案和文本摘要不新增事实。
- `write_back=false` 下无持久化副作用。

### 10.5 旧 QA 兼容回归

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_qa_service tests.test_qa_http tests.test_qa_http_models tests.test_qa_http_runtime tests.test_qa_mcp_models tests.test_qa_mcp_tools tests.test_qa_mcp_runtime tests.test_qa_mcp_server tests.test_qa_cli tests.test_qa_mcp_cli -v
```

验证旧 QA 未被产品 adapter 破坏。

### 10.6 文档与验收

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_adapter_docs tests.test_readme tests.test_module_docs -v
```

文档必须说明：

- 产品 HTTP/MCP 已实现或未实现的当前状态。
- 旧 QA 兼容状态。
- fake/offline、live Neo4j、live DashScope、真实文本 provider、真实 MCP 宿主注册分层。
- skipped 不等于 live 通过。

### 10.7 live 验证

live Neo4j：

```powershell
$env:NEO4J_TEST_URI = "<neo4j-test-uri>"
$env:NEO4J_TEST_USER = "<neo4j-test-user>"
$env:NEO4J_TEST_PASSWORD = "<neo4j-test-password>"
$env:PYTHONPATH='src'; python -m unittest tests.integration.test_qa_mcp_integration tests.integration.test_product_adapter_live -v
```

live DashScope / 真实文本 provider：

- 需要用户明确授权和 API key 环境变量。
- 使用小型黄金集和 dry-run。
- 结果单独写入 acceptance 文档。

若这些环境不存在，验收文档必须写“未验证”或“skipped”，不得写“通过”。
