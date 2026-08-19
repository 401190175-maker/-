# Adapter 与产品级验收 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**总目标：** 新增产品级只读 HTTP/MCP adapter，并建立产品 CLI/HTTP/MCP、旧 QA 兼容、E2E、并发/超时/错误映射和文档层 live 状态分层验收。

**架构说明：** 产品 adapter 只调用 `DrawingAssistantService.answer()`；旧 QA adapter 继续只调用 `DrawingGraphQAService.ask()`。新增产品 adapter 不直接访问 Neo4j driver、repository、Cypher、Qwen provider 或离线规则函数；runtime 只负责装配 driver -> facade -> service。

## 全局约束

- 不新增 Neo4j schema、节点、关系、索引或约束。
- 默认 `write_back=false`；产品 HTTP/MCP 首版不提供写回入口。
- 不绕过 `DrawingGraphToolFacade`；adapter 不直接访问 Neo4j driver、repository、Cypher 或底层写回方法。
- 保持已有 QA CLI/HTTP/MCP/ToolFacade 兼容。
- `candidate_relation`、`matched_candidate`、`CANDIDATE_*` 不能写成 `formal_relation`。
- `allow_recognition=true` 不等于写回授权。
- fake/offline/unit/live 验证状态必须分层说明。
- skipped live 测试不能描述为 live Neo4j 已通过。
- 每个任务独立测试、独立评审、独立验收；不要合并多个独立能力。

## 文件职责表

| 文件 | 职责 |
|---|---|
| `src/drawing_graph/assistant_adapter_serialization.py` | 产品 adapter 共享 envelope、JSON-safe 转换、错误脱敏与错误类别映射。 |
| `src/drawing_graph/assistant_http_models.py` | 产品 HTTP request/response/health DTO，严格字段白名单，转换为 `AssistantRequest`。 |
| `src/drawing_graph/assistant_http_runtime.py` | 产品 HTTP driver/facade/service 装配、fake factory 注入、幂等关闭。 |
| `src/drawing_graph/assistant_http.py` | 产品 HTTP FastAPI app、路由、中间件、并发/超时/错误映射。 |
| `scripts/serve_drawing_assistant.py` | 产品 HTTP 启动入口，从环境变量加载配置并启动 Uvicorn。 |
| `src/drawing_graph/assistant_mcp_models.py` | 产品 MCP tool 输入输出模型，转换为 `AssistantRequest`。 |
| `src/drawing_graph/assistant_mcp_tools.py` | 产品 MCP tool handler，调用 `DrawingAssistantService.answer()` 并生成 structuredContent/TextContent。 |
| `src/drawing_graph/assistant_mcp_runtime.py` | 产品 MCP runtime 装配与生命周期。 |
| `src/drawing_graph/assistant_mcp_server.py` | 产品 MCP server、tool schema、只读 annotations。 |
| `scripts/serve_drawing_assistant_mcp.py` | 产品 MCP STDIO 启动入口，stdout 只承载协议帧。 |
| `docs/acceptance/PRODUCT_ADAPTER_ACCEPTANCE.md` | 产品 adapter 验收记录与 live 状态分层。 |
| `README.md` / `Module.md` / `architecture.md` | 实施完成后同步当前已实现能力和未验证边界。 |
| `tests/test_assistant_*` / `tests/test_product_adapter_e2e.py` | 产品 adapter 合同、边界、E2E、兼容和文档测试。 |

## 任务列表

### Task 1: 产品 adapter 共享序列化

**明确目标：**
新增产品 adapter 共用的成功/失败 envelope、错误类别和脱敏转换，不改变旧 QA serialization 行为。

**指定修改文件：**
- Create: `src/drawing_graph/assistant_adapter_serialization.py`
- Create: `tests/test_assistant_adapter_serialization.py`
- Modify: 无
- Test: `tests/test_assistant_adapter_serialization.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_adapter_serialization -v
```

**完成标准：**

- `AnswerPackage` 可转换为 JSON-safe 成功 envelope。
- `ReadOnlyViolationError`、`AssistantExecutionError`、参数错误、timeout 和 unexpected error 映射为稳定错误码。
- 错误消息脱敏，不包含 password、secret、token、Authorization、Cypher、traceback。
- 不导入 HTTP、MCP、Neo4j driver、repository、Qwen provider。

### Task 2: 产品 HTTP 请求与响应模型

**明确目标：**
定义产品 HTTP DTO，并把 HTTP 请求安全转换为 `AssistantRequest`。

**指定修改文件：**
- Create: `src/drawing_graph/assistant_http_models.py`
- Create: `tests/test_assistant_http_models.py`
- Modify: 无
- Test: `tests/test_assistant_http_models.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_http_models -v
```

**完成标准：**

- `question` 非空、长度受限。
- `scope_hint` 只接受稳定业务 ID 字段。
- 未知字段被拒绝。
- `write_back`、`allow_write_back`、Cypher、凭据、driver/session/repository 字段被拒绝。
- 转换后的 `AssistantRequest.allow_write_back` 固定为 false。

### Task 3: 产品 HTTP runtime 装配

**明确目标：**
新增产品 HTTP runtime，集中管理 driver -> facade -> `DrawingAssistantService` 的生命周期。

**指定修改文件：**
- Create: `src/drawing_graph/assistant_http_runtime.py`
- Create: `tests/test_assistant_http_runtime.py`
- Modify: `src/drawing_graph/config.py`
- Test: `tests/test_assistant_http_runtime.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_http_runtime -v
```

**完成标准：**

- config 可从环境变量读取产品 HTTP host/port/token/body limit/timeout/concurrency/docs/log level。
- runtime 支持 fake driver/facade/service factory 注入。
- 初始化失败会关闭已创建 driver。
- `close()` 幂等。
- route 层不接触 driver。

### Task 4: 产品 HTTP app 和 ask 路由

**明确目标：**
新增产品 HTTP app，提供 `/api/v1/drawing-assistant/ask` 只读自然语言问答路由。

**指定修改文件：**
- Create: `src/drawing_graph/assistant_http.py`
- Create: `tests/test_assistant_http.py`
- Modify: 无
- Test: `tests/test_assistant_http.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_http -v
```

**完成标准：**

- `GET /health/live` 返回 process liveness。
- `GET /health/ready` 返回 runtime 装配状态，但不声称 live Neo4j 已验证。
- `POST /api/v1/drawing-assistant/ask` 调用一次 `DrawingAssistantService.answer()`。
- answered、partial、clarification_required、unsupported、recognition_failed 均以 200 返回业务状态。
- `write_back` 请求被拒绝，且不会调用 service。

### Task 5: 产品 HTTP 并发、超时和错误映射

**明确目标：**
补齐产品 HTTP 的 body limit、认证、并发上限、请求超时和错误 envelope 映射。

**指定修改文件：**
- Modify: `src/drawing_graph/assistant_http.py`
- Modify: `tests/test_assistant_http.py`
- Test: `tests/test_assistant_http.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_http.AssistantHttpErrorMappingTests tests.test_assistant_http.AssistantHttpConcurrencyTests -v
```

**完成标准：**

- 认证失败返回 401。
- body 超限返回 413。
- 并发上限返回 429，并释放 semaphore。
- service 超时返回 504，不自动扩大 scope 或写回。
- validation、read-only、service、unexpected error 均返回稳定脱敏 envelope。

### Task 6: 产品 HTTP 启动脚本

**明确目标：**
新增产品 HTTP 启动脚本，作为 `assistant_http.create_app()` 的薄入口。

**指定修改文件：**
- Create: `scripts/serve_drawing_assistant.py`
- Create: `tests/test_assistant_http_cli.py`
- Test: `tests/test_assistant_http_cli.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_http_cli -v
```

**完成标准：**

- 脚本 import 无副作用。
- 缺少配置时返回稳定脱敏 startup error。
- 不接受 Neo4j 密码、HTTP token、DashScope API key 命令行参数。
- 只从环境变量加载 config。

### Task 7: 产品 HTTP 静态边界

**明确目标：**
用静态测试保护产品 HTTP adapter 不绕过 service/facade 边界。

**指定修改文件：**
- Create: `tests/test_assistant_http_boundaries.py`
- Modify: 无
- Test: `tests/test_assistant_http_boundaries.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_http_boundaries -v
```

**完成标准：**

- `assistant_http.py`、`assistant_http_models.py` 不导入 `neo4j`、repository、Cypher、Qwen、semantic write-back、offline rule functions。
- route handler 只依赖 service，不直接调用 `DrawingGraphToolFacade` 或 `create_neo4j_tool_facade()`。
- runtime 可导入 `create_neo4j_tool_facade()`，但测试确认它不执行查询或写回。

### Task 8: 产品 MCP 输入输出模型

**明确目标：**
定义产品 MCP tool 输入输出模型，并转换为只读 `AssistantRequest`。

**指定修改文件：**
- Create: `src/drawing_graph/assistant_mcp_models.py`
- Create: `tests/test_assistant_mcp_models.py`
- Test: `tests/test_assistant_mcp_models.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_mcp_models -v
```

**完成标准：**

- tool 输入支持 `question`、`request_id`、`language`、`scope_hint`、`allow_recognition`。
- 输入不接受 `write_back`、Cypher、凭据、path、driver/session/repository。
- 互斥/冲突 scope 返回稳定 input error。
- 转换结果 `allow_write_back=false`。

### Task 9: 产品 MCP tool handler

**明确目标：**
新增产品 MCP tool handler，只调用一次 `DrawingAssistantService.answer()` 并生成同源 MCP 输出。

**指定修改文件：**
- Create: `src/drawing_graph/assistant_mcp_tools.py`
- Create: `tests/test_assistant_mcp_tools.py`
- Test: `tests/test_assistant_mcp_tools.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_mcp_tools -v
```

**完成标准：**

- `ask_drawing_assistant` handler 调用一次 service。
- structuredContent 来自 `AnswerPackage` JSON-safe 投影。
- TextContent 只概述 status/text_answer/claim/warning/unsupported 数量。
- `partial` 不标记为 tool error。
- candidate/formal 文案不混淆。
- unexpected error 脱敏并返回稳定错误。

### Task 10: 产品 MCP runtime 和 server

**明确目标：**
新增产品 MCP runtime/server，提供本地 STDIO 只读 assistant tool。

**指定修改文件：**
- Create: `src/drawing_graph/assistant_mcp_runtime.py`
- Create: `src/drawing_graph/assistant_mcp_server.py`
- Create: `tests/test_assistant_mcp_runtime.py`
- Create: `tests/test_assistant_mcp_server.py`
- Test: `tests/test_assistant_mcp_runtime.py`, `tests/test_assistant_mcp_server.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_mcp_runtime tests.test_assistant_mcp_server -v
```

**完成标准：**

- runtime 支持 fake factory 注入和失败清理。
- server tools/list 暴露一个产品 assistant tool。
- tool annotations 标记只读。
- server instructions 明确 candidate 不是 formal，`write_back=false`。
- import server 不读取 env、不连接 Neo4j、不启动 transport。

### Task 11: 产品 MCP STDIO 启动脚本

**明确目标：**
新增产品 MCP STDIO 启动脚本，保护 stdout 协议纯净和 stderr 脱敏错误。

**指定修改文件：**
- Create: `scripts/serve_drawing_assistant_mcp.py`
- Create: `tests/test_assistant_mcp_cli.py`
- Test: `tests/test_assistant_mcp_cli.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_mcp_cli -v
```

**完成标准：**

- 脚本 import 无副作用。
- startup/config/runtime/server 错误返回稳定退出码和脱敏 stderr。
- stdout 不输出日志、traceback 或调试文本。
- 不接受 host/port/token/write-back 参数。

### Task 12: 产品 MCP 静态边界

**明确目标：**
用静态测试保护产品 MCP adapter 不调用 HTTP/CLI、不绕过 facade、不写回。

**指定修改文件：**
- Create: `tests/test_assistant_mcp_boundaries.py`
- Modify: 无
- Test: `tests/test_assistant_mcp_boundaries.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_mcp_boundaries -v
```

**完成标准：**

- MCP models/tools/server 不导入 `qa_http`、HTTP client、CLI scripts、repository、Cypher、Qwen、write-back modules。
- MCP runtime 只用于装配，不执行业务查询。
- MCP 工具不提供候选提升或写回工具。

### Task 13: 产品 CLI/HTTP/MCP fake E2E

**明确目标：**
建立产品三入口 fake E2E，证明 CLI/HTTP/MCP 对同一产品服务合同一致。

**指定修改文件：**
- Create: `tests/test_product_adapter_e2e.py`
- Modify: `tests/test_drawing_assistant_e2e.py`
- Test: `tests/test_product_adapter_e2e.py`, `tests/test_drawing_assistant_e2e.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_product_adapter_e2e tests.test_drawing_assistant_e2e -v
```

**完成标准：**

- fake service 覆盖 answered、partial、clarification_required、unsupported、recognition_failed。
- CLI/HTTP/MCP 输出都保留 request_id、status、machine_answer/text_answer、warnings、unsupported_parts。
- TextContent/文本输出不新增 structuredContent 中没有的 claim。
- 测试不连接 Neo4j、不调用 DashScope、不写文件系统业务数据。

### Task 14: 旧 QA 兼容回归

**明确目标：**
确认新增产品 adapter 不破坏旧 QA CLI/HTTP/MCP。

**指定修改文件：**
- Create: `tests/test_product_adapter_qa_compatibility.py`
- Modify: 无
- Test: `tests/test_product_adapter_qa_compatibility.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_product_adapter_qa_compatibility tests.test_qa_service tests.test_qa_http tests.test_qa_mcp_tools -v
```

**完成标准：**

- 旧六类 QA request 仍映射到 `DrawingGraphQAService.ask()`。
- 旧 HTTP 路由和 MCP 工具名未改变。
- 旧 QA `write_back=true` 仍被拒绝。
- 旧 QA structuredContent/TextContent 事实分层不变。

### Task 15: 产品 adapter 文档验收记录

**明确目标：**
新增产品 adapter 验收文档，记录实际执行过的命令和分层验证状态。

**指定修改文件：**
- Create: `docs/acceptance/PRODUCT_ADAPTER_ACCEPTANCE.md`
- Create: `tests/test_assistant_adapter_docs.py`
- Test: `tests/test_assistant_adapter_docs.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_adapter_docs -v
```

**完成标准：**

- 文档列出产品 CLI/HTTP/MCP、旧 QA 兼容、E2E、并发/超时/错误映射的命令和结果占位规范。
- 文档明确 unit/fake/offline、HTTP socket、MCP in-memory、MCP STDIO、live Neo4j、live DashScope、真实文本 provider、真实 MCP 宿主注册的状态。
- 文档包含“skipped 不等于 live Neo4j 通过”。
- 文档不把未执行 live 项写成已验证。

### Task 16: 根文档同步

**明确目标：**
实施完成后同步根文档，只描述当前已实现产品 adapter 和未验证 live 边界。

**指定修改文件：**
- Modify: `README.md`
- Modify: `Module.md`
- Modify: `architecture.md`
- Modify: `tests/test_readme.py`
- Modify: `tests/test_module_docs.py`
- Modify: `tests/test_assistant_docs.py`
- Test: `tests/test_readme.py`, `tests/test_module_docs.py`, `tests/test_assistant_docs.py`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_readme tests.test_module_docs tests.test_assistant_docs -v
```

**完成标准：**

- 根文档说明旧 QA HTTP/MCP 与产品 HTTP/MCP 的区别。
- 根文档说明产品 adapter 默认只读、`write_back=false`、candidate 不是 formal。
- 根文档说明 live Neo4j/live DashScope/真实文本 provider 若未运行则未验证。
- 不删除或改写历史 acceptance 记录。

### Task 17: 产品 adapter 完整离线回归

**明确目标：**
运行产品 adapter 相关完整离线回归，并记录与旧 QA 的兼容状态。

**指定修改文件：**
- Modify: `docs/acceptance/PRODUCT_ADAPTER_ACCEPTANCE.md`
- Test: adapter 专项、旧 QA 专项、完整离线回归

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_adapter_serialization tests.test_assistant_http_models tests.test_assistant_http_runtime tests.test_assistant_http tests.test_assistant_http_cli tests.test_assistant_http_boundaries tests.test_assistant_mcp_models tests.test_assistant_mcp_tools tests.test_assistant_mcp_runtime tests.test_assistant_mcp_server tests.test_assistant_mcp_cli tests.test_assistant_mcp_boundaries tests.test_product_adapter_e2e tests.test_product_adapter_qa_compatibility -v
```

**完成标准：**

- 产品 adapter 专项全部通过。
- 旧 QA 兼容专项通过。
- 结果写入 `PRODUCT_ADAPTER_ACCEPTANCE.md`。
- 未运行 live 项保持“未验证”。

### Task 18: 全仓离线回归与 live 状态记录

**明确目标：**
运行全仓离线回归，并把 skipped/live 状态如实写入验收文档。

**指定修改文件：**
- Modify: `docs/acceptance/PRODUCT_ADAPTER_ACCEPTANCE.md`
- Test: `tests/`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest discover tests -v
```

**完成标准：**

- 全仓离线回归结果、失败/错误/skipped 数量写入验收文档。
- 如果 `tests/integration/` 因缺少 `NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD` 跳过，明确写 skipped，不写 live 通过。
- live DashScope、真实文本 provider、真实 MCP 宿主注册未执行时标为未验证。

### Task 19: 可选 live Neo4j 产品链路验收

**明确目标：**
在用户明确提供 disposable Neo4j 测试库环境后，执行产品 adapter live Neo4j 验收并记录结果。

**指定修改文件：**
- Create: `tests/integration/test_product_adapter_live.py`
- Modify: `docs/acceptance/PRODUCT_ADAPTER_ACCEPTANCE.md`
- Test: `tests.integration.test_product_adapter_live`

**可独立测试：**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.integration.test_product_adapter_live -v
```

**完成标准：**

- 未配置 `NEO4J_TEST_*` 时测试按设计 skipped，并说明 skipped 不等于 live 通过。
- 配置 disposable 测试库时，产品 HTTP/MCP runtime 能经 `DrawingAssistantService -> DrawingGraphToolFacade` 完成只读问答。
- 验收数据可清理或使用明确测试前缀。
- 不调用 DashScope，不写业务事实。

### Task 20: 可选 live DashScope 与真实文本 provider 验收记录

**明确目标：**
在用户明确授权并配置 provider 环境后，记录产品 adapter 对真实模型调用状态的验收边界。

**指定修改文件：**
- Modify: `docs/acceptance/PRODUCT_ADAPTER_ACCEPTANCE.md`
- Test: 手动授权的 live provider smoke 或黄金集命令

**可独立测试：**

```powershell
# 仅在用户明确授权并配置真实 provider 环境后执行。
$env:PYTHONPATH='src'; python -m unittest tests.test_qwen_semantic_client -v
```

**完成标准：**

- 未授权或未配置 key 时，文档标记 live DashScope/真实文本 provider 未验证。
- 执行 live 时记录模型、prompt、运行日期、样本范围、结果状态和限制。
- live DashScope 通过不写成 live Neo4j 通过。
- provider 输出仍只能成为 observation/interpretation/candidate evidence，不能成为 source_fact/formal。

## 完成标准

整个需求完成时必须满足：

1. 产品级 HTTP adapter 可用，且只读。
2. 产品级 MCP adapter 可用，且只读。
3. 产品 CLI/HTTP/MCP 三入口 fake/offline E2E 通过。
4. 旧 QA CLI/HTTP/MCP 兼容回归通过。
5. HTTP 并发、超时、错误映射和请求体限制有测试。
6. MCP structuredContent/TextContent、STDIO 纯净和错误映射有测试。
7. 文档层验收记录真实区分 unit/fake/offline/live/skipped。
8. 不新增 Neo4j schema。
9. 不绕过 `DrawingGraphToolFacade`。
10. `write_back=false`、candidate 不等于 formal、skipped 不等于 live 通过的边界被测试和文档同时保护。

## 不包含范围

- 不实现 Web UI、Ava 专有 adapter、远程 MCP、Streamable HTTP MCP、OAuth/RBAC、多 worker 生产部署。
- 不实现 HTTP/MCP 写回入口。
- 不把 feedback 外部入口并入首批只读问答 adapter。
- 不新增 OCR 或全量自动语义扫描。
- 不把 fake/offline/health/smoke/skipped 写成 live Neo4j、live DashScope 或真实 provider 通过。

## 一致性审查

### 1. 前后状态矛盾

- `Feature_Analysis_Report.md`、`proposal.md`、`design.md` 与本文件均把旧 QA HTTP/MCP、产品 CLI、01-07 内部链路写为当前已实现。
- 四个文件均把产品级 HTTP/MCP assistant 入口写为待新增能力，没有写成已实现。
- 四个文件均明确 live Neo4j、live DashScope、真实文本 provider、真实 MCP 宿主注册需要单独验收。

### 2. proposal 目标是否都被 design 覆盖

- 产品 HTTP：proposal 目标 1 已由 design 2.2-2.5、5.1、10.2 覆盖。
- 产品 MCP：proposal 目标 2 已由 design 2.6-2.7、5.2、10.3 覆盖。
- 旧 QA 兼容：proposal 目标 3 已由 design 5.3、9、10.5 覆盖。
- 错误/超时/并发：proposal 目标 4 已由 design 6、10.2 覆盖。
- E2E 与文档 live 分层：proposal 目标 5-6 已由 design 10.4、10.6、10.7 覆盖。
- 只读边界：proposal 目标 7 已由 design 7、8 覆盖。

### 3. design 模块是否都在 tasks 里落到任务

- `assistant_adapter_serialization.py` -> Task 1。
- `assistant_http_models.py` -> Task 2。
- `assistant_http_runtime.py` -> Task 3。
- `assistant_http.py` -> Task 4、5、7。
- `scripts/serve_drawing_assistant.py` -> Task 6。
- `assistant_mcp_models.py` -> Task 8。
- `assistant_mcp_tools.py` -> Task 9。
- `assistant_mcp_runtime.py` / `assistant_mcp_server.py` -> Task 10。
- `scripts/serve_drawing_assistant_mcp.py` -> Task 11。
- `docs/acceptance/PRODUCT_ADAPTER_ACCEPTANCE.md` -> Task 15、17、18、19、20。
- 根文档同步 -> Task 16。

### 4. tasks 是否每个任务都有明确目标、指定修改文件、可独立测试、完成标准

- Task 1-20 均包含“明确目标”“指定修改文件”“可独立测试”“完成标准”。
- 每个任务只交付一个可独立评审的能力：序列化、HTTP 模型、HTTP runtime、HTTP route、HTTP 错误映射、HTTP CLI、HTTP 边界、MCP 模型、MCP tool、MCP runtime/server、MCP CLI、MCP 边界、E2E、旧 QA 兼容、文档验收、根文档同步、专项回归、全仓回归、live Neo4j、live provider。

### 5. 是否误把未实现内容写成已实现

- 未把产品级 HTTP/MCP assistant 写成当前已实现。
- 未把 Web UI、远程 MCP、Streamable HTTP MCP、OAuth/RBAC、多 worker、HTTP/MCP 写回写成已实现。
- 未把 live Neo4j、live DashScope、真实文本 provider、真实 MCP 宿主注册写成已验证。

### 6. 是否违反项目边界

- 四个文件均保持默认 `write_back=false`。
- 四个文件均禁止 adapter 直接访问 Neo4j driver、repository、Cypher 或底层写回。
- 四个文件均说明 candidate、`matched_candidate`、`CANDIDATE_*` 不等于 formal。
- 四个文件均说明 skipped live 测试不等于 live Neo4j 通过。
- 四个文件均保持旧 QA / HTTP / MCP / ToolFacade 兼容，不把旧 QAService 改造成产品总编排器。
