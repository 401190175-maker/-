# Tool 层第三阶段 MCP 与 Skill 强化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 在不改变现有 QA 领域契约、Tool facade、HTTP/CLI 行为和 Neo4j Schema 的前提下，新增本机 STDIO、默认只读的 MCP adapter，并强化 `drawing-graph-operator` Skill 的工具选择、透明降级、事实分层和验证规则。

**架构：** MCP 与 QA CLI、HTTP adapter 同级，只把白名单参数转换为 `QARequest(write_back=false)`，并调用一次 `DrawingGraphQAService.ask()`。Skill 位于 MCP 外侧，负责自然语言路由和结果解释；MCP 不调用 HTTP/CLI，Skill 和 MCP 都不得绕过 QAService/facade 访问 QueryService、repository、Neo4j session 或 Cypher。

**技术栈：** Python 3.11+、标准库 `unittest`、官方 MCP Python SDK、Pydantic、Neo4j Python driver；现有 FastAPI、Starlette、Uvicorn、HTTPX 仅作为兼容回归对象，不作为 STDIO MCP 的调用链。

## 全局约束

- 默认且强制 `write_back=false`；首版不注册任何导入、增强、语义持久化、候选复核、正式关系提升或任意 Cypher 工具。
- 六个外部工具固定映射六个现有 `QuestionType`，不暴露通用 `ask_drawing_graph(question_type, scope)`。
- 所有 MCP handler 只调用一次 `DrawingGraphQAService.ask()`，不得直接调用 facade 单项方法、HTTP endpoint、CLI 子进程、QueryService 或 repository。
- `source_fact`、`derived_relation`、`semantic_observation`、`semantic_interpretation`、`candidate_relation`、`formal_relation`、`diagnostic` 和 `unsupported` 必须保持原分类；candidate 和 `matched_candidate` 不是正式事实。
- MCP 模块 import 不读取环境变量、不创建 driver、不连接 Neo4j、不启动 transport；只有 STDIO 启动脚本的 `main()` 负责读取环境和运行协议。
- stdout 只承载 MCP 协议；日志和脱敏错误只进入 stderr。
- 首版不实现 Streamable HTTP MCP、远程监听、多 worker、OAuth、RBAC、TLS、plugin 发布、云模型、OCR、文件 watcher 或任务队列。
- 不修改 `qa_models.py`、`qa_service.py`、`qa_rendering.py`、HTTP adapter、Tool facade、repository、语义证据领域模块或 `scripts/create_schema.cypher`；如测试证明必须修改，先停止实施并重新评审 design。
- 不创建通用 adapter/runtime 基类，不把同步 QAService 改为 async，不为未来能力预置未使用抽象。
- 每个 Task 严格执行：先写或调整失败测试，运行并确认因当前目标缺失而失败，完成最小实现，再运行该任务的独立测试。
- 每个 Task 独立通过后单独提交；不得跨 Task 提前实现后续能力。
- 单元测试、MCP in-memory 合约、STDIO smoke、Skill 验证、HTTP 回归和 live Neo4j 验证分别报告；skipped 不等于 passed。

## 固定接口与文件职责

以下名称是任务间合同，实施时不得在后续任务中任意改名：

- `src/drawing_graph/qa_mcp_models.py`
  - 输入模型：`AskDrawingPageInput`、`AskDrawingBlockInput`、`ListDrawingCandidatesInput`、`GetSectionMatchStatusInput`、`GetTableCaptionStatusInput`、`GetDrawingDiagnosticsInput`。
  - 输出模型：`McpResultMeta`、`McpQAError`、`McpQASuccess`、`McpQAFailure`、`McpToolOutcome`。
  - 合同版本：`MCP_CONTRACT_VERSION = "drawing-qa-mcp-v1"`。
  - 每个输入模型提供 `to_qa_request() -> QARequest`，内部固定 `write_back=False`、`include_payload=False`。
- `src/drawing_graph/qa_mcp_tools.py`
  - `DrawingGraphMCPTools(service)` 仅接收 QAService。
  - 公开方法名与六个 MCP tool name 相同，输入对应模型，返回 `McpToolOutcome`。
  - 私有公共流程负责单次 `ask()`、call ID、成功/错误映射和同源文本摘要。
- `src/drawing_graph/qa_mcp_runtime.py`
  - `QAMcpRuntime` 保存 driver、facade、service，并提供幂等 `close()`。
  - `create_qa_mcp_runtime(config, ...) -> QAMcpRuntime` 支持 fake factory 注入。
- `src/drawing_graph/qa_mcp_server.py`
  - `create_mcp_server(tools: DrawingGraphMCPTools)` 返回未启动的 `drawing-graph-qa` server。
- `scripts/serve_drawing_graph_mcp.py`
  - `main() -> int` 是唯一 STDIO 进程入口。

---

## Task 1: 增加 MCP SDK 依赖并验证依赖兼容性

**明确目标：** 为第三阶段选择一段有上下界的官方 MCP Python SDK 兼容版本范围，同时保持现有 Web 和 Neo4j 依赖可共同安装。

**指定修改文件：**

- 修改：`requirements.txt`

**可独立测试：**

- `python -m pip install -r requirements.txt`
- `python -m pip check`
- `python -c "import mcp, fastapi, pydantic, starlette, uvicorn, httpx, neo4j; print('dependency-import-ok')"`

**完成标准：**

- `requirements.txt` 中 MCP SDK 具有明确下界和排他上界，不使用无界依赖或私有 Git revision。
- 依赖解析、`pip check` 和联合 import 均成功。
- 未无理由升级或删除现有 FastAPI、Pydantic、Starlette、Uvicorn、HTTPX、Neo4j 依赖。
- 未增加第二套 MCP SDK、Web 框架、任务队列、ORM 或云模型 SDK。

## Task 2: 实现 `QAMcpConfig`

**明确目标：** 提供只包含 STDIO MCP runtime 必需连接信息和日志级别的不可变配置。

**指定修改文件：**

- 修改：`src/drawing_graph/config.py`
- 修改：`tests/test_config.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_config.QAMcpConfigTests -v`

**完成标准：**

- 定义不可变 `QAMcpConfig`，包含 `neo4j_uri`、`neo4j_user`、`neo4j_password` 和 `log_level`。
- `from_env()` 读取 `NEO4J_URI`、`NEO4J_USER`、`NEO4J_PASSWORD` 和可选 `DRAWING_GRAPH_QA_MCP_LOG_LEVEL`。
- 缺少必需变量或日志级别非法时抛出既有 `ConfigError`，消息不包含 secret 值。
- 不复用 HTTP host、port、CORS、token、docs、并发或 timeout 配置，不扩大 `ImportConfig`。

## Task 3: 定义 MCP 输入公共校验规则

**明确目标：** 为六类输入模型建立统一但窄口径的语言、ID 和额外字段拒绝规则。

**指定修改文件：**

- 新增：`src/drawing_graph/qa_mcp_models.py`
- 新增：`tests/test_qa_mcp_models.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_models.McpInputCommonTests -v`

**完成标准：**

- 语言只允许 `zh`、`en`，默认 `zh`。
- scope ID 去除首尾空白后必须非空，最大长度固定为 512 个字符。
- 模型统一拒绝额外字段，且验证错误不回显完整输入对象。
- 公共规则不包含 `write_back`、`include_payload`、Cypher、credentials、路径、driver 或 repository 字段。

## Task 4: 实现 `AskDrawingPageInput`

**明确目标：** 将页面摘要 MCP 输入稳定转换为只读 `page_summary` 请求。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_mcp_models.py`
- 修改：`tests/test_qa_mcp_models.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_models.AskDrawingPageInputTests -v`

**完成标准：**

- 输入只包含必填 `page_id`、可选 `language` 和 `include_semantics`。
- `to_qa_request()` 固定生成 `QuestionType.PAGE_SUMMARY` 和仅含 `page_id` 的 `QAScope`。
- 请求固定 `write_back=False`、`include_payload=False`，并保留 `include_semantics`。
- 非法 ID、非法语言、额外字段和任何写回字段均被拒绝。

## Task 5: 实现 `AskDrawingBlockInput`

**明确目标：** 将图块关系 MCP 输入稳定转换为只读 `block_relations` 请求。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_mcp_models.py`
- 修改：`tests/test_qa_mcp_models.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_models.AskDrawingBlockInputTests -v`

**完成标准：**

- 输入只包含必填 `block_id`、可选 `language` 和 `include_candidates`。
- `to_qa_request()` 固定生成 `QuestionType.BLOCK_RELATIONS` 和仅含 `block_id` 的 scope。
- 请求固定只读且不含 payload，并保留 `include_candidates`。
- 不接受 page scope、任意 question type 或写回相关字段。

## Task 6: 实现 `ListDrawingCandidatesInput`

**明确目标：** 将候选关系 MCP 输入转换为页面或图块二选一的只读请求。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_mcp_models.py`
- 修改：`tests/test_qa_mcp_models.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_models.ListDrawingCandidatesInputTests -v`

**完成标准：**

- `page_id` 与 `block_id` 必须且只能提供一个。
- `to_qa_request()` 固定生成 `QuestionType.CANDIDATE_RELATIONS` 和相应单一 scope。
- 输入不提供 relation type、status、写回或候选提升参数。
- 两个 ID 同时提供、均未提供、空 ID 和额外字段均被测试拒绝。

## Task 7: 实现 `GetSectionMatchStatusInput`

**明确目标：** 将断面匹配 MCP 输入转换为断面或页面二选一的只读请求。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_mcp_models.py`
- 修改：`tests/test_qa_mcp_models.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_models.GetSectionMatchStatusInputTests -v`

**完成标准：**

- `cross_section_id` 与 `page_id` 必须且只能提供一个。
- `to_qa_request()` 固定生成 `QuestionType.SECTION_MATCHES`。
- 请求始终 `write_back=False`，不接受 `rule_version`、status 更新或持久化参数。
- 测试覆盖两种合法 scope、互斥冲突、缺失 scope 和额外字段。

## Task 8: 实现 `GetTableCaptionStatusInput`

**明确目标：** 将表格标题状态 MCP 输入转换为三个受支持 scope 之一的只读请求。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_mcp_models.py`
- 修改：`tests/test_qa_mcp_models.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_models.GetTableCaptionStatusInputTests -v`

**完成标准：**

- `table_id`、`table_caption_id`、`page_id` 必须且只能提供一个。
- `to_qa_request()` 固定生成 `QuestionType.TABLE_CAPTION_STATUS`。
- table/table-caption 单 ID 能被表示，以便 QAService 原样返回当前 `partial + unsupported_parts`。
- 不接受 block scope、任意关系推断或写回字段。

## Task 9: 实现 `GetDrawingDiagnosticsInput`

**明确目标：** 将诊断 MCP 输入转换为页面或图块二选一的只读诊断请求。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_mcp_models.py`
- 修改：`tests/test_qa_mcp_models.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_models.GetDrawingDiagnosticsInputTests -v`

**完成标准：**

- `page_id` 与 `block_id` 必须且只能提供一个。
- 可选字段只包含 `language`、`include_semantics`、`include_candidates`。
- `to_qa_request()` 固定生成 `QuestionType.DIAGNOSTIC_STATUS`、`write_back=False`、`include_payload=False`。
- 诊断输入不包含自动修复、导入、增强、识别或候选复核参数。

## Task 10: 定义 MCP 结构化结果合同

**明确目标：** 建立成功、失败、meta 和协议呈现结果的稳定类型，不改变现有 QA DTO。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_mcp_models.py`
- 修改：`tests/test_qa_mcp_models.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_models.McpResultModelTests -v`

**完成标准：**

- 定义 `MCP_CONTRACT_VERSION="drawing-qa-mcp-v1"`、`McpResultMeta`、`McpQAError`、`McpQASuccess`、`McpQAFailure` 和 `McpToolOutcome`。
- 成功根对象固定 `status="ok"`、`data`、`meta`；失败根对象固定 `status="error"`、`error`、`meta`。
- meta 固定包含 `contract_version`、六选一 `tool_name` 和非空 `call_id`。
- 模型能产生 JSON-safe 根级 object Schema，不包含 SDK、Neo4j 或 Python 异常对象。

## Task 11: 实现 MCP 成功结果与同源文本摘要

**明确目标：** 把一个现有 `QAAnswer` 无损转换为成功 structured content 和简短 TextContent。

**指定修改文件：**

- 新增：`src/drawing_graph/qa_mcp_tools.py`
- 新增：`tests/test_qa_mcp_tools.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_tools.McpSuccessMappingTests -v`

**完成标准：**

- 使用现有 `to_jsonable()` 转换 QAAnswer，不复制 CLI/HTTP envelope。
- structured content 完整保留 status、summary、facts、evidence、warnings、unsupported_parts 和 source_calls。
- TextContent 只概述 QA 状态、summary、facts/warnings/unsupported 数量，并由同一 structured content 生成。
- `partial` 保持 `is_error=False`，且文本明确为部分回答。

## Task 12: 实现 MCP 安全错误映射

**明确目标：** 将 QAError、失败 QAAnswer 和未预期异常转换为稳定、脱敏的 MCP tool error。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_mcp_tools.py`
- 修改：`tests/test_qa_mcp_tools.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_tools.McpErrorMappingTests -v`

**完成标准：**

- 显式映射 design 中九个稳定小写错误类别，不根据异常文本生成新类别。
- not found、unsupported 和领域拒绝返回 `is_error=True`；partial 不进入错误映射。
- 复用 `sanitize_error_message()`，输出不含 stack trace、凭据 URI、密码、token、Cypher 或本地敏感路径。
- 未预期异常只返回 `internal_error`、安全短消息和 call ID，详细诊断只允许进入 stderr 日志。

## Task 13: 实现 `ask_drawing_page` 工具 handler

**明确目标：** 提供页面摘要工具的传输无关 handler。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_mcp_tools.py`
- 修改：`tests/test_qa_mcp_tools.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_tools.AskDrawingPageToolTests -v`

**完成标准：**

- `DrawingGraphMCPTools.ask_drawing_page()` 接收 `AskDrawingPageInput` 并返回 `McpToolOutcome`。
- handler 只调用一次 `service.ask()`，请求严格等于 Task 4 的领域转换结果。
- fake service 的 answered、partial、not_found 和异常路径均有测试。
- handler 不导入或调用 HTTP、CLI、facade、repository 或 Neo4j。

## Task 14: 实现 `ask_drawing_block` 工具 handler

**明确目标：** 提供图块关系工具的传输无关 handler。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_mcp_tools.py`
- 修改：`tests/test_qa_mcp_tools.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_tools.AskDrawingBlockToolTests -v`

**完成标准：**

- handler 只调用一次 `service.ask()`，并传入 Task 5 生成的 block request。
- structured content 保留 derived、candidate 和 formal 的原有 `fact_kind`。
- 文本摘要不把 candidate 或 `matched_candidate` 表述为正式关系。
- `include_candidates=False` 原样进入请求，不由 handler 二次过滤结果。

## Task 15: 实现 `list_drawing_candidates` 工具 handler

**明确目标：** 提供候选关系列表工具的传输无关 handler。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_mcp_tools.py`
- 修改：`tests/test_qa_mcp_tools.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_tools.ListDrawingCandidatesToolTests -v`

**完成标准：**

- page 和 block 两种合法 scope 都只调用一次 `service.ask()`。
- 输出中的候选事实继续为 `candidate_relation`，不生成 `formal_relation`。
- handler 不提供审核、提升、status 更新或 write-back 能力。
- scope 校验失败时不调用 service。

## Task 16: 实现 `get_section_match_status` 工具 handler

**明确目标：** 提供断面匹配状态工具的传输无关 handler。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_mcp_tools.py`
- 修改：`tests/test_qa_mcp_tools.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_tools.GetSectionMatchStatusToolTests -v`

**完成标准：**

- cross-section 和 page 两种 scope 均映射到 `section_matches`。
- handler 不调用 `match_section_caption()` 或 facade 单项方法，只调用一次 QAService。
- `matched_candidate` 保持候选语义，dry-run 结果不持久化。
- not found、partial 和 unsupported 原样进入统一结果映射。

## Task 17: 实现 `get_table_caption_status` 工具 handler

**明确目标：** 提供表格标题状态工具的传输无关 handler。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_mcp_tools.py`
- 修改：`tests/test_qa_mcp_tools.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_tools.GetTableCaptionStatusToolTests -v`

**完成标准：**

- page、table 和 table-caption 三种 scope 都调用一次 QAService。
- table/table-caption 单 ID 返回的 `partial + unsupported_parts` 保持成功但不完整。
- MCP handler 不通过底层查询补齐 QAService 当前不支持的反向页面查找。
- 输出不把来源元素存在描述为已确认的派生表题关系。

## Task 18: 实现 `get_drawing_diagnostics` 工具 handler

**明确目标：** 提供页面或图块诊断工具的传输无关 handler。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_mcp_tools.py`
- 修改：`tests/test_qa_mcp_tools.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_tools.GetDrawingDiagnosticsToolTests -v`

**完成标准：**

- page 和 block scope 都只调用一次 QAService。
- include_semantics/include_candidates 开关原样进入 QARequest。
- 诊断结果不触发导入、增强、识别、修复、候选审核或写回。
- 输出继续使用 `diagnostic` 和现有其他事实类别，不重分类。

## Task 19: 实现 MCP runtime 生产装配

**明确目标：** 创建一个长生命周期 driver、facade 和 QAService 的 MCP runtime。

**指定修改文件：**

- 新增：`src/drawing_graph/qa_mcp_runtime.py`
- 新增：`tests/test_qa_mcp_runtime.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_runtime.QAMcpRuntimeConstructionTests -v`

**完成标准：**

- `create_qa_mcp_runtime()` 按 driver -> `create_neo4j_tool_facade(driver)` -> `DrawingGraphQAService(facade)` 顺序装配。
- 工厂支持注入 fake driver/facade/service，单元测试不连接真实 Neo4j。
- runtime 复用一个 service，不为每次 tool call 重建 driver。
- 模块 import 无环境读取和连接副作用，不继承或调用 HTTP runtime。

## Task 20: 实现 MCP runtime 失败清理和幂等关闭

**明确目标：** 保证 runtime 在部分初始化失败、正常退出和重复关闭时正确释放 driver。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_mcp_runtime.py`
- 修改：`tests/test_qa_mcp_runtime.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_runtime.QAMcpRuntimeCleanupTests -v`

**完成标准：**

- driver 创建后 facade 或 service 构造失败时，driver 恰好关闭一次。
- 正常 `close()` 关闭 driver；重复 `close()` 不重复释放、不抛新异常。
- close 失败不会把连接 URI、用户名或密码写入异常消息。
- 未增加后台线程、全局 singleton、通用 runtime 基类或多 worker 状态。

## Task 21: 实现无副作用 MCP server 工厂与 instructions

**明确目标：** 创建只提供 Tools capability、尚未运行 transport 的 `drawing-graph-qa` server。

**指定修改文件：**

- 新增：`src/drawing_graph/qa_mcp_server.py`
- 新增：`tests/test_qa_mcp_server.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_server.QAMcpServerFactoryTests -v`

**完成标准：**

- `create_mcp_server(tools)` 不读取环境、不创建 driver、不启动 STDIO。
- server name 固定为 `drawing-graph-qa`。
- instructions 前 512 个字符内自包含声明只读、候选非正式事实、模型证据不覆盖来源事实、禁止任意 Cypher 和验证状态诚实报告。
- 首版不注册 Resources、Prompts、Sampling、Completion、Streamable HTTP 或长任务能力。

## Task 22: 注册 `ask_drawing_page` MCP 工具

**明确目标：** 让 MCP 客户端可发现并调用页面摘要工具。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_mcp_server.py`
- 修改：`tests/test_qa_mcp_server.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_server.AskDrawingPageContractTests -v`

**完成标准：**

- `tools/list` 只新增 `ask_drawing_page`，inputSchema 与 Task 4 一致。
- 工具调用委托 `DrawingGraphMCPTools.ask_drawing_page()`，返回 structuredContent、TextContent 和正确 isError。
- outputSchema 接受 `drawing-qa-mcp-v1` 成功/错误根对象。
- annotations 为 read-only true、destructive false、open-world false。

## Task 23: 注册 `ask_drawing_block` MCP 工具

**明确目标：** 让 MCP 客户端可发现并调用图块关系工具。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_mcp_server.py`
- 修改：`tests/test_qa_mcp_server.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_server.AskDrawingBlockContractTests -v`

**完成标准：**

- 工具名称、描述、inputSchema、outputSchema 和 annotations 与 design 一致。
- 协议调用只委托对应 handler，不绕过工具层。
- include_candidates 能通过 Schema 和协议调用传递。
- 候选关系在协议结果中保持 candidate 分类。

## Task 24: 注册 `list_drawing_candidates` MCP 工具

**明确目标：** 让 MCP 客户端可发现并调用候选关系列表工具。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_mcp_server.py`
- 修改：`tests/test_qa_mcp_server.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_server.ListDrawingCandidatesContractTests -v`

**完成标准：**

- Schema 强制 page/block scope 二选一，且不出现审核、提升或写回字段。
- 工具描述明确“候选不是正式关系”。
- answered 和输入错误分别产生正确 isError。
- tools/list 不出现通用问答或候选写回工具。

## Task 25: 注册 `get_section_match_status` MCP 工具

**明确目标：** 让 MCP 客户端可发现并调用断面匹配状态工具。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_mcp_server.py`
- 修改：`tests/test_qa_mcp_server.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_server.GetSectionMatchStatusContractTests -v`

**完成标准：**

- Schema 强制 cross-section/page scope 二选一。
- 描述明确匹配状态只读、`matched_candidate` 不是正式事实。
- 协议调用不接受 `write_back` 或 `rule_version`。
- partial 与 not found 的 isError 语义符合 design。

## Task 26: 注册 `get_table_caption_status` MCP 工具

**明确目标：** 让 MCP 客户端可发现并调用表格标题状态工具。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_mcp_server.py`
- 修改：`tests/test_qa_mcp_server.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_server.GetTableCaptionStatusContractTests -v`

**完成标准：**

- Schema 强制 table/table-caption/page scope 三选一。
- 描述明确底层能力不足时可能返回 partial 和 unsupported parts。
- partial 返回 `isError=false` 并保留完整 unsupported_parts。
- 工具不暴露反向查询或关系补算参数。

## Task 27: 注册 `get_drawing_diagnostics` MCP 工具

**明确目标：** 让 MCP 客户端可发现并调用诊断状态工具。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_mcp_server.py`
- 修改：`tests/test_qa_mcp_server.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_server.GetDrawingDiagnosticsContractTests -v`

**完成标准：**

- Schema 强制 page/block scope 二选一，并只允许语义/候选读取开关。
- 描述明确诊断不会自动修复或写回。
- 协议输出保留 diagnostic、warnings 和 unsupported parts。
- annotations 与其他只读工具一致。

## Task 28: 验证完整 MCP 工具发现合同

**明确目标：** 锁定 server 恰好发现六个设计内只读工具及其稳定 Schema。

**指定修改文件：**

- 修改：`tests/test_qa_mcp_server.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_server.QAMcpToolDiscoveryTests -v`

**完成标准：**

- initialize 和 tools/list 通过官方 SDK 的内存 client/server session 执行。
- 工具集合恰好为 design 中六个名称，不包含通用问答、写回、导入、增强、复核或 Cypher 工具。
- 每个 inputSchema、outputSchema 和 annotations 均通过稳定断言。
- 测试不连接真实 Neo4j，不使用 HTTP TestClient 代替 MCP session。

## Task 29: 验证 MCP 协议错误与工具错误边界

**明确目标：** 锁定协议级错误和可归因于单次工具执行的结构化错误不会相互混用。

**指定修改文件：**

- 修改：`tests/test_qa_mcp_server.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_server.QAMcpErrorBoundaryTests -v`

**完成标准：**

- 未知 tool、无法解析的 MCP 消息、未支持 method 和 initialize 失败保持官方 SDK 协议错误。
- 输入模型校验、QA not found/unsupported 和 handler 内异常返回 `isError=true` 的安全 tool result。
- partial 返回 `isError=false`，warnings 和 unsupported_parts 不丢失。
- 测试不捕获并重写 SDK 在 handler 前产生的标准协议错误。

## Task 30: 实现 STDIO 启动脚本的配置与装配入口

**明确目标：** 提供只在 `main()` 内读取配置并创建 runtime/server 的启动入口。

**指定修改文件：**

- 新增：`scripts/serve_drawing_graph_mcp.py`
- 新增：`tests/test_qa_mcp_cli.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_cli.QAMcpCliImportTests -v`

**完成标准：**

- import 脚本不读取环境、不创建 driver、不启动 server、不输出 stdout/stderr。
- `main()` 依次加载 `QAMcpConfig`、创建 runtime、创建 tools/server。
- 所有生产依赖均可在测试中注入 fake，不连接真实 Neo4j。
- 脚本不接受 host、port、worker、HTTP token 或远程 transport 参数。

## Task 31: 实现 STDIO 协议运行与正常关闭

**明确目标：** 让启动脚本运行官方 STDIO transport，并在正常结束时关闭 runtime。

**指定修改文件：**

- 修改：`scripts/serve_drawing_graph_mcp.py`
- 修改：`tests/test_qa_mcp_cli.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_cli.QAMcpCliLifecycleTests -v`

**完成标准：**

- `main()` 运行 STDIO transport，正常结束返回 0。
- runtime 在协议结束后恰好关闭一次。
- stdout 不出现 banner、日志、帮助文本、Python repr 或协议外字符。
- 未启动 Uvicorn、FastAPI app、HTTP socket 或后台 worker。

## Task 32: 实现 STDIO 启动失败与日志脱敏

**明确目标：** 对配置、装配和协议循环失败提供非零退出、资源清理和安全 stderr。

**指定修改文件：**

- 修改：`scripts/serve_drawing_graph_mcp.py`
- 修改：`tests/test_qa_mcp_cli.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_cli.QAMcpCliFailureTests -v`

**完成标准：**

- 配置或 runtime 创建失败返回非零退出码；已创建 runtime 在协议异常时关闭。
- stderr 仅输出脱敏错误和必要 call ID，不输出 stack trace、密码、token、凭据 URI 或完整输入。
- stdout 在所有失败路径仍不包含协议外日志。
- close 失败被记录并保持非零退出，不掩盖首个启动/协议错误。

## Task 33: 增加 MCP 静态依赖与只读边界测试

**明确目标：** 用静态测试锁定 MCP adapter 只能通过 QAService 使用业务能力。

**指定修改文件：**

- 新增：`tests/test_qa_mcp_boundaries.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_boundaries -v`

**完成标准：**

- 检查 `qa_mcp_models.py`、`qa_mcp_tools.py`、`qa_mcp_server.py` 不导入 HTTP/CLI、QueryService、repository、Neo4j session/transaction 或规则函数。
- 检查所有外部 Schema 不含 `write_back`、`include_payload`、Cypher、credentials、路径或底层对象字段。
- 检查六个 handler 的唯一业务调用是 `DrawingGraphQAService.ask()`。
- 检查领域 DTO、QAService、facade、HTTP 和 Schema 文件没有因 MCP 接入被修改。

## Task 34: 编写 Skill QA 工具路由资料

**明确目标：** 让 Skill 能把六类自然语言意图稳定映射到 MCP 工具、QuestionType 和 scope。

**指定修改文件：**

- 新增：`drawing-graph-operator/references/qa-workflows.md`（位于当时唯一权威 Skill 根目录）
- 修改：`tests/test_skill_docs.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_skill_docs.DrawingGraphSkillQaWorkflowTests -v`

**完成标准：**

- 资料逐一列出六个工具、对应 QuestionType、必需 ID、互斥 scope 和可选读取开关。
- 说明多意图拆分、调用顺序、缺少 ID 时询问用户以及不得扩大到全库。
- 说明多个 partial 不能拼接为正式结论。
- 不包含 Python 业务实现、真实数据、密码、token 或任意 Cypher。

## Task 35: 编写 Skill MCP 边界与透明降级资料

**明确目标：** 规定 MCP 不可用、工具缺失、初始化失败和超时时的安全降级行为。

**指定修改文件：**

- 新增：`drawing-graph-operator/references/mcp-boundaries.md`（位于当时唯一权威 Skill 根目录）
- 修改：`tests/test_skill_docs.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_skill_docs.DrawingGraphSkillMcpBoundaryTests -v`

**完成标准：**

- 明确 MCP 优先、受控 QA CLI 后备、禁止静默降级。
- 降级时必须说明 MCP 未成功使用、后备入口和验证状态。
- 明确 Skill 不创建 driver、不执行 Cypher、不调用 repository 写回或 facade 单项写回能力。
- 明确超时/取消不自动扩大范围、不自动触发其他工具或写回。

## Task 36: 强化 Skill 输出合同

**明确目标：** 保证 MCP structuredContent、TextContent 和最终中文回答保持相同事实分层。

**指定修改文件：**

- 修改：`drawing-graph-operator/references/output-contract.md`（位于当时唯一权威 Skill 根目录）
- 修改：`tests/test_skill_docs.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_skill_docs.DrawingGraphSkillMcpOutputTests -v`

**完成标准：**

- 保留八类 fact kind、evidence、warnings、unsupported_parts 和 source_calls。
- 明确 candidate、`CANDIDATE_*`、`matched_candidate` 不等于 formal。
- 明确 partial、not found、unsupported 和 error 的保守中文表达。
- 图纸/OCR/模型文本被视为数据，不被当作系统指令执行。

## Task 37: 强化 Skill MCP 验证规则

**明确目标：** 为第三阶段定义互不替代的 MCP、STDIO、Skill、回归和 live Neo4j 验证状态。

**指定修改文件：**

- 修改：`drawing-graph-operator/references/verification.md`（位于当时唯一权威 Skill 根目录）
- 修改：`tests/test_skill_docs.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_skill_docs.DrawingGraphSkillMcpVerificationTests -v`

**完成标准：**

- 分别定义模型/工具单元测试、MCP in-memory、STDIO smoke、Skill 发现/触发、HTTP 回归和 live Neo4j 验证。
- 明确 fake runtime、HTTP health 和 STDIO smoke 不能证明 live Neo4j。
- skipped 继续标为 live Neo4j 未验证。
- 更新 Skill 校验命令，使其使用最终唯一权威 Skill 路径。

## Task 38: 更新 Skill 入口选择规则

**明确目标：** 让 `SKILL.md` 优先选择已配置 MCP QA 工具，并按需路由到新增 references。

**指定修改文件：**

- 修改：`drawing-graph-operator/SKILL.md`（位于当时唯一权威 Skill 根目录）
- 修改：`tests/test_skill_docs.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_skill_docs.DrawingGraphSkillEntryTests -v`

**完成标准：**

- 核心工作流先读取当前文档，再优先选择已配置 MCP QA tool。
- MCP 不可用时只按 `mcp-boundaries.md` 透明降级到 QA CLI。
- 按需读取表包含 `qa-workflows.md` 和 `mcp-boundaries.md`，保持渐进披露。
- Skill 仍是操作策略层，不声称自己是 MCP server、业务服务或数据库接口。

## Task 39: 验证并确定 Skill 唯一权威路径

**明确目标：** 在实际宿主验证后，让仓库只保留一个可发现的 `drawing-graph-operator` Skill 副本。

**指定修改文件：**

- 条件移动：`.codex/skills/drawing-graph-operator/` -> `.agents/skills/drawing-graph-operator/`
- 修改：`tests/test_skill_docs.py`
- 修改：`changes/tool层/第三阶段/tasks.md`，仅追加本任务实际路径验证记录

**可独立测试：**

- `python C:\Users\40119\.codex\skills\.system\skill-creator\scripts\quick_validate.py .agents\skills\drawing-graph-operator`
- 若目标路径发现验证失败并恢复旧路径：`python C:\Users\40119\.codex\skills\.system\skill-creator\scripts\quick_validate.py .codex\skills\drawing-graph-operator`
- 在项目实际使用的 Codex 桌面端及 CLI/IDE 中分别验证发现、显式调用和相关隐式触发。

**完成标准：**

- 优先以移动而非复制方式测试 `.agents/skills/drawing-graph-operator`。
- 若所有实际宿主验证通过，`.agents/skills` 成为唯一权威路径，旧 `.codex/skills` 不再保留同名副本。
- 若任一必要宿主验证失败，恢复 `.codex/skills` 为唯一权威路径，并记录失败环境和原因；不得为了路径迁移阻断 MCP 核心交付。
- 静态测试确认仓库内不存在两个独立维护的同名 Skill。

## Task 40: 声明 Skill 的 MCP 工具依赖

**明确目标：** 在已验证的权威 Skill 中声明对 `drawing-graph-qa` 六个只读工具的依赖。

**指定修改文件：**

- 修改：`drawing-graph-operator/agents/openai.yaml`（使用 Task 39 确定的唯一权威根目录）
- 修改：`tests/test_skill_docs.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_skill_docs.DrawingGraphSkillMcpDependencyTests -v`

**完成标准：**

- dependency 使用稳定 server 名 `drawing-graph-qa` 和六个准确 tool name。
- 声明通过当前宿主 Schema/frontmatter 校验，并能触发依赖发现。
- 文件不包含本机绝对路径、Neo4j 凭据、环境变量值或未实现的写工具。
- 若宿主不支持该依赖声明，保留无依赖 metadata 的有效 Skill 并记录兼容性未验证，不伪造成功状态。

## Task 41: 增加 Skill 路由与降级行为测试

**明确目标：** 用固定提示集验证 Skill 的工具选择、缺失 ID、透明降级和事实分层行为。

**指定修改文件：**

- 新增：`tests/test_qa_mcp_skill_behavior.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_skill_behavior -v`

**完成标准：**

- 提示集分别覆盖页面、图块、候选、断面、表格标题和诊断六类意图。
- 缺少必需 ID 时结果要求询问用户，不猜测 ID 或扩大 scope。
- MCP 不可用时要求明确说明并降级到只读 QA CLI，不冒充 MCP 已验证。
- 输出断言保护 candidate/formal、partial/complete、smoke/live verified 的区别。

## Task 42: 更新 README 的 MCP 使用说明

**明确目标：** 在 MCP 实现完成后记录安装、环境、STDIO 配置、工具清单和只读使用边界。

**指定修改文件：**

- 修改：`README.md`
- 修改：`tests/test_readme.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_readme -v`

**完成标准：**

- README 给出 MCP 依赖安装、必需环境变量名、STDIO 启动命令和六个工具用途。
- 配置示例只写环境变量名，不写真实值或不可移植本机绝对路径。
- 明确只读、无 Streamable HTTP、无写回、MCP/CLI 降级和验证状态边界。
- 只有已实现和已验证能力写为当前能力；live Neo4j 未执行时明确未验证。

## Task 43: 更新 Module 的 MCP 模块职责

**明确目标：** 记录 MCP models、tools、runtime、server、CLI 和 Skill 的单一职责及依赖接口。

**指定修改文件：**

- 修改：`Module.md`
- 修改：`tests/test_module_docs.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_module_docs -v`

**完成标准：**

- Module 分别记录五个新增 MCP 文件及六个工具的职责。
- 依赖方向明确为 MCP -> QAService -> facade，不出现 MCP -> HTTP/CLI/repository。
- 记录 MCP SDK 新依赖、数据模型不变、Skill 与 MCP 分工和权威 Skill 路径状态。
- 不把 Streamable HTTP、远程认证、写回或 plugin 发布写成已实现。

## Task 44: 更新 architecture 的第三阶段架构

**明确目标：** 将 STDIO MCP 作为 CLI/HTTP 的同级 adapter 纳入当前架构说明。

**指定修改文件：**

- 修改：`architecture.md`
- 修改：`tests/test_qa_docs.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_docs -v`

**完成标准：**

- 架构图和数据流包含 Skill -> MCP client -> STDIO MCP -> QAService -> facade。
- 明确 CLI、HTTP、MCP 同级，MCP 不调用 HTTP 或 CLI。
- 当前边界更新为已实现本地只读 MCP；远程 MCP、写回、OAuth、多 worker 仍为未实现。
- Neo4j 节点、关系、约束、索引和 RecognitionRun/TextObservation 边界不变。

## Task 45: 更新 Skill 项目边界资料的当前状态

**明确目标：** 移除 Skill 边界资料中“Skill、HTTP、MCP 尚未实现”的过期状态，同时保留禁止依赖方向。

**指定修改文件：**

- 修改：`drawing-graph-operator/references/project-boundaries.md`（使用唯一权威 Skill 根目录）
- 修改：`tests/test_skill_docs.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_skill_docs.DrawingGraphSkillProjectBoundaryTests -v`

**完成标准：**

- 当前能力准确列出已实现 Skill、QA CLI、HTTP 和本地只读 MCP。
- 未实现范围继续包含远程 MCP、MCP 写回、云模型、OCR、文件 watcher 和全量自动扫描。
- 依赖方向更新为 Skill -> MCP/受控 QA CLI -> QAService -> facade。
- 不改变来源事实、派生关系、语义证据、候选/正式关系和 write-back 边界。

## Task 46: 增加第三阶段文档合同测试

**明确目标：** 用独立文档测试保护 MCP/Skill 分工、首版范围和验证表述。

**指定修改文件：**

- 新增：`tests/test_qa_mcp_docs.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_mcp_docs -v`

**完成标准：**

- 检查 README、Module、architecture、Skill references 对六个工具和稳定依赖方向表述一致。
- 检查所有文档明确 read-only、STDIO 首版、candidate 非 formal、skipped 非 live verified。
- 检查 Streamable HTTP、远程部署、OAuth、写回和 plugin 仍标为未实现。
- 检查 Skill 只有一个权威路径，文档不含真实密钥或本机敏感绝对路径。

## Task 47: 执行第三阶段全量单元回归

**明确目标：** 证明 MCP/Skill 接入没有破坏既有 QA、CLI、HTTP、facade、语义证据、候选关系和导入增强单元行为。

**指定修改文件：**

- 修改：`changes/tool层/第三阶段/tasks.md`，仅在执行后追加本任务实际验收记录
- 不修改业务代码

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest discover tests -v`

**完成标准：**

- 命令退出码为 0，并记录新鲜的运行数、通过数、失败数和跳过数。
- 第一、二阶段 QA/CLI/HTTP 及现有项目测试继续通过。
- skipped 测试逐项记录原因，不计入 passed。
- 不沿用历史测试数量，不把单元回归写成 live Neo4j 或真实 STDIO 验证。

## Task 48: 执行真实 STDIO MCP smoke test

**明确目标：** 通过真实子进程 STDIO 完成 MCP 握手、工具发现、一次 fake QA 调用和正常关闭。

**指定修改文件：**

- 修改：`changes/tool层/第三阶段/tasks.md`，仅在执行后追加本任务实际验收记录
- 不修改业务代码

**可独立测试：**

- 使用官方 MCP client 以子进程方式启动 `scripts/serve_drawing_graph_mcp.py` 的 fake-runtime 测试入口，完成 initialize、tools/list、一次 `tools/call` 和正常关闭。

**完成标准：**

- 真实 STDIO 子进程完成 initialize，并恰好发现六个工具。
- 一次工具调用返回符合 outputSchema 的 structuredContent、同源 TextContent 和正确 isError。
- stdout 无协议外文本，stderr 不含注入的测试 secret，runtime 只关闭一次。
- 记录明确说明使用 fake runtime，因此不能证明 live Neo4j 查询通过。

## Task 49: 增加可跳过的 MCP live Neo4j 集成测试

**明确目标：** 建立一条仅在 disposable Neo4j 凭据齐全时运行的真实 MCP 只读调用链测试。

**指定修改文件：**

- 新增：`tests/integration/test_qa_mcp_integration.py`

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest tests.integration.test_qa_mcp_integration -v`

**完成标准：**

- 未配置 `NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD` 时，测试以明确原因跳过。
- 配置 disposable 测试库时，测试通过 MCP -> QAService -> facade 读取一个受控 scope，并验证 structuredContent。
- 测试不直接执行 Cypher，不修改 Schema，不触发任何 write-back。
- 测试隔离真实凭据，不将值写入日志、失败快照或仓库文件。

## Task 50: 执行 disposable Neo4j 的 MCP 集成验证

**明确目标：** 运行真实 MCP 集成测试并如实记录 live Neo4j 状态。

**指定修改文件：**

- 修改：`changes/tool层/第三阶段/tasks.md`，仅在执行后追加本任务实际验收记录
- 不修改业务代码或 Neo4j Schema

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest discover tests.integration -v`

**完成标准：**

- 只有三个 `NEO4J_TEST_*` 变量指向 disposable 测试库且 MCP 集成测试实际运行通过，才能记录 live Neo4j verified。
- 未配置环境时记录 skipped 和“live Neo4j 未验证”，不得记录 passed。
- MCP in-memory、STDIO fake smoke、HTTP health、HTTP TestClient 和全量单元回归均不能替代本验证。
- 验收记录包含执行时间、命令、退出码、运行/通过/失败/跳过数量和数据安全说明。

---

## 验收记录（实施时填写）

本节只在相应验证 Task 实际执行后追加新鲜证据。不得提前填写计划值，也不得复制第一、二阶段历史测试数量。

### Task 39：Skill 唯一权威路径

- 状态：目标路径迁移验证不通过，已恢复 `.codex/skills` 为唯一权威路径；迁移记为兼容性待办。
- 执行时间：2026-08-11。
- 执行内容：
  1. 以 `git mv` 将 `.codex/skills/drawing-graph-operator/` 移动到 `.agents/skills/drawing-graph-operator/`（移动而非复制）。
  2. 目标路径结构存在，`tests/test_skill_docs.py` 单一权威副本测试通过。
  3. `quick_validate.py` 不可用：本机 Python 环境缺少 `yaml` 模块（`ModuleNotFoundError: No module named 'yaml'`），按设计以等价静态检查（frontmatter、必需文件、密钥/真实数据禁止项）替代，检查通过。
  4. 宿主验证失败/无法完成：当前 Codex 桌面会话的 Skill 注册路径仍指向 `.codex/skills/drawing-graph-operator`，移动后该路径消失，本会话无法发现和显式调用目标路径 Skill；`.agents/` 同时被仓库 `.gitignore` 排除，移动会破坏仓库级 Skill 交付。
- 回退动作：`git mv` 将 Skill 恢复回 `.codex/skills/drawing-graph-operator/`，移除临时空 `.agents` 目录；恢复后 `git status` 无 Skill 文件差异，`tests/test_skill_docs.py` 全量通过。
- 结论：`.codex/skills/drawing-graph-operator` 保持唯一权威路径；`.agents/skills` 迁移需在宿主重启验证、`.gitignore` 策略确认后单独立项，不影响 MCP 核心交付。

### Task 40：Skill 声明 MCP 工具依赖

- 状态：按回退条款保留无依赖 metadata；宿主兼容性未验证，不伪造成功状态。
- 执行时间：2026-08-11。
- 执行内容：
  1. 读取 skill-creator 的 `references/openai_yaml.md` 与 `scripts/generate_openai_yaml.py`，确认官方字段仅支持 `dependencies.tools[].{type, value, description, transport, url}`；`value` 是 MCP server 标识，不支持在同一 entry 内声明六个精确 tool name。
  2. 检查本机已安装插件/Skill 的 `agents/openai.yaml` 实际实例：`dependencies.tools` 均用于 streamable_http + url（如 neon、openaiDeveloperDocs），未发现 stdio 依赖声明先例；`quick_validate.py` 只校验 `SKILL.md` frontmatter，不解析 `agents/openai.yaml`。
  3. 官方 Codex Skills/MCP 文档页面本次不可达（HTTP 403），无法由官方 schema 确认 `transport: "stdio"` 且无 `url` 的声明在当前宿主可被接受并触发依赖发现。
  4. 当前 Codex 会话未配置 `drawing-graph-qa` MCP server；本机系统 Python 与捆绑 Python 均缺少 `yaml` 模块，无法运行宿主侧 schema 校验脚本。
  5. 按 design 5.6 与 Task 40 完成标准中的回退条款：保留 `.codex/skills/drawing-graph-operator/agents/openai.yaml` 为无依赖的有效 interface-only metadata；不添加未经宿主验证的 `dependencies` 声明。
- 等价静态检查：openai.yaml 结构有效（仅顶层 `interface:`）、无本机绝对路径、无凭据值、无写回/导入/增强/复核/提升工具名；`tests/test_skill_docs.py` 新增 `DrawingGraphSkillMcpDependencyTests` 独立测试通过。
- 结论：`drawing-graph-qa` 依赖发现未验证；待宿主支持按 tool name 声明或确认 stdio server 依赖可被发现后，再单独立项补充 `dependencies.tools`，不影响 MCP 核心交付。

### Task 47：第三阶段全量单元回归

- 状态：执行完成，退出码 0；1031 个测试通过，0 失败，3 个跳过（live Neo4j 未验证）。
- 执行时间：2026-08-11。
- 执行命令：`$env:PYTHONPATH='src'; python -m unittest discover tests -v`
- 运行结果：`Ran 1031 tests in 5.451s`，`OK (skipped=3)`。
- 跳过原因：`NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD` 未配置，`tests/integration/test_neo4j_import.py`、`tests/integration/test_neo4j_relation_enrichment.py`、`tests/integration/test_neo4j_semantic_evidence.py` 三个真实 Neo4j 集成测试按设计跳过。
- 回归说明：第一、二阶段 QA/CLI/HTTP 测试继续通过；MCP/Skill 文档合同测试通过。首次全量运行时发现 `tests/test_cross_section_docs.py` 仍断言旧措辞“不提供 MCP Tool adapter”，已同步为“不提供远程 MCP、本地只读 MCP Tool adapter 已实现”后重新通过。
- 结论：单元回归通过；live Neo4j 未验证，skipped 不计入 passed。

### Task 48：真实 STDIO MCP smoke test

- 状态：执行完成，退出码 0；STDIO 握手、六工具发现、成功/错误调用、正常关闭均通过。
- 执行时间：2026-08-11。
- 执行方式：官方 `mcp.client.stdio.stdio_client` + `ClientSession` 以子进程方式启动 `scripts/serve_drawing_graph_mcp.py` 的 fake-runtime 包装入口（临时 UTF-8 runner，未新增仓库文件）。
- 验证内容：
  1. initialize 成功；`tools/list` 恰好发现六个工具。
  2. `ask_drawing_page` 返回 `isError=false`，structuredContent.status=ok、contract_version=`drawing-qa-mcp-v1`、tool_name 正确，TextContent 同源包含摘要。
  3. `list_drawing_candidates` 双 ID 输入返回 `isError=true` + `invalid_argument`。
  4. fake service 注入 `bolt://user:SMOKE_SECRET_9f8a@host:7687` 异常时返回 `internal_error`；stderr 只含脱敏日志和 call ID，不含 secret/traceback；runtime 只关闭一次（`fake-runtime-close-calls=1`）。
  5. stdout 无协议外文本（协议帧由官方 client 消费并成功解析）。
- 发现并修复：smoke 首次执行发现未预期异常时 `logger.exception()` 会把含原始异常的完整 traceback 写入 stderr（泄漏注入的 secret），已改为 `logger.error()` 仅记录脱敏消息和 call ID，并新增单测断言日志不含 secret/traceback。
- 结论：STDIO fake smoke 通过；使用 fake runtime，不能证明 live Neo4j 查询通过。

### Task 50：disposable Neo4j MCP 集成验证

- 状态：执行完成，退出码 0；4 个集成测试全部跳过，live Neo4j 未验证。
- 执行时间：2026-08-11。
- 执行命令：`$env:PYTHONPATH='src'; python -m unittest discover tests.integration -v`
- 运行结果：`Ran 4 tests in 0.000s`，`OK (skipped=4)`。
- 跳过原因：`NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD` 未配置；`test_neo4j_import`、`test_neo4j_relation_enrichment`、`test_neo4j_semantic_evidence` 与新增 `test_qa_mcp_integration` 均按设计跳过。
- 数据安全说明：未连接任何真实或 disposable 数据库；未创建、修改或删除测试数据；无凭据写入仓库文件。
- 结论：MCP live Neo4j 集成验证未执行，不得记录为 passed；只有三个 `NEO4J_TEST_*` 指向 disposable 测试库并实际运行通过后才能标记 live verified。
