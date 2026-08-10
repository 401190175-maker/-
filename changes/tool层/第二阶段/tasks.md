# Tool 层第二阶段 HTTP API 实施任务

> **执行要求：** 使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 按任务顺序实施。每个任务均先写失败测试、确认失败原因、完成最小实现，再运行该任务列出的独立测试；不要跨任务提前实现后续能力。

**目标：** 在现有 `DrawingGraphQAService -> DrawingGraphToolFacade` 边界外增加版本化、默认本机监听、默认只读的 HTTP API，同时保持第一阶段 QA CLI 兼容。

**架构：** HTTP 是与 QA CLI 同级的协议 adapter。所有业务路由只能构造 `QARequest` 并调用 `DrawingGraphQAService.ask()`；只有 HTTP runtime 和启动脚本可以知道 Neo4j driver，route 不得直接调用 facade、repository、Cypher、导入、增强或候选复核写回能力。

**技术栈：** Python 3.11+、标准库 `unittest`、FastAPI、Pydantic、Uvicorn、HTTPX、Neo4j Python driver。

## 全局约束

- 默认 `write_back=false`；HTTP 不提供持久化、候选复核写回或正式关系提升入口。
- 来源事实、派生关系、语义观察、语义解释、候选关系和正式关系必须保持分层；`matched_candidate` 不是正式关系。
- 模块 import 不读取环境变量、不创建 driver、不连接 Neo4j、不启动 Uvicorn。
- 默认监听 `127.0.0.1`、单 worker、关闭 CORS、关闭 OpenAPI/docs。
- 非 loopback 绑定必须同时显式允许远程访问并配置 Bearer token；TLS 由外部反向代理提供。
- `RecognitionRun` 保持图谱外运行日志；本阶段不修改 Neo4j Schema、QA 领域 DTO、facade 方法集或查询行为。
- 单元测试、HTTP socket smoke test、Neo4j 集成测试和 live Neo4j 验证状态分别报告；skipped 不等于 passed。
- 新增代码为非显然的生命周期、并发、超时和安全边界添加简洁注释，不做无关重构。

---

## Task 1: 增加 HTTP 运行与测试依赖

**明确目标：** 为第二阶段提供唯一一套 FastAPI、Uvicorn 和 HTTPX 依赖，不引入其他 Web 框架或 SDK。

**指定修改文件：**

- 修改：`requirements.txt`

**可独立测试：**

- `python -m pip install -r requirements.txt`
- `python -c "import fastapi, httpx, pydantic, uvicorn; print(fastapi.__version__, httpx.__version__, pydantic.__version__, uvicorn.__version__)"`

**完成标准：**

- Python 3.11 环境可以同时导入 FastAPI、Pydantic、Uvicorn 和 HTTPX。
- 依赖范围彼此兼容，并保留现有 Neo4j 及测试依赖。
- 未新增 Flask、Django、MCP SDK、Ava SDK、云模型 SDK、任务队列或 ORM。

## Task 2: 实现框架无关的 JSON 转换

**明确目标：** 提供 `to_jsonable(value)`，统一递归转换 QA DTO 和现有 CLI 输出。

**指定修改文件：**

- 新增：`src/drawing_graph/qa_serialization.py`
- 新增：`tests/test_qa_serialization.py`

**可独立测试：**

- `python -m unittest tests.test_qa_serialization.QaJsonableTests -v`

**完成标准：**

- `to_jsonable()` 支持 dataclass、Enum、tuple/list、`Path`、普通 dict 和只读 mapping。
- 转换结果只包含 JSON 可编码值，且不改变 `fact_kind`、status、relation type 或 evidence。
- 模块不依赖 FastAPI、Pydantic、Uvicorn、Neo4j、QAService 或 facade，也不读取环境变量。
- 测试包含 `MappingProxyType`、嵌套 DTO、Path、候选关系和空值。

## Task 3: 实现稳定响应 envelope

**明确目标：** 提供 CLI 和 HTTP 共用的成功与失败 envelope 构造函数。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_serialization.py`
- 修改：`tests/test_qa_serialization.py`

**可独立测试：**

- `python -m unittest tests.test_qa_serialization.QaEnvelopeTests -v`

**完成标准：**

- `build_success_envelope(data, meta=None)` 固定返回 `status="ok"` 和 `data`。
- `build_error_envelope(category, message, retryable, meta=None, details=None)` 固定返回 `status="failed"` 和结构化 `error`。
- 未传 `meta` 时保持第一阶段 CLI 的 `status`、`data`/`error` 顶层兼容；HTTP 可以传入 request ID 和 contract version。
- `details=None` 时不生成含敏感占位信息的字段。

## Task 4: 实现共享错误脱敏

**明确目标：** 提供 `sanitize_error_message(message)`，阻止密钥和底层实现细节进入 CLI 或 HTTP 客户端响应。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_serialization.py`
- 修改：`tests/test_qa_serialization.py`

**可独立测试：**

- `python -m unittest tests.test_qa_serialization.QaSanitizationTests -v`

**完成标准：**

- 清洗 password、secret、token、Bolt/Neo4j 连接细节、Cypher、driver、session、transaction 和 traceback 片段。
- 普通业务错误码和安全短消息仍可辨识。
- 测试使用虚构密钥并断言原值及敏感低层词不出现在输出中。
- 脱敏函数不记录日志、不访问环境变量、不改变异常对象。

## Task 5: 迁移 QA CLI 到共享序列化

**明确目标：** 让现有 QA CLI 使用共享 JSON 转换、envelope 和脱敏实现，同时保持第一阶段命令行合同不变。

**指定修改文件：**

- 修改：`scripts/drawing_graph_qa.py`
- 修改：`tests/test_qa_cli.py`

**可独立测试：**

- `python -m unittest tests.test_qa_cli -v`

**完成标准：**

- 删除脚本私有 `_jsonable()` 和重复脱敏逻辑，改用 `qa_serialization` 公共函数。
- 六个现有子命令、参数、默认 `--format json`、`zh-brief` 路径和退出码保持不变。
- JSON 成功输出仍包含 `status="ok"` 与 `data`，已知业务错误和初始化错误的退出码保持 1/2。
- driver 仍只由 CLI 最外层创建和关闭，CLI 不调用 HTTP。

## Task 6: 实现 `QAHttpConfig`

**明确目标：** 建立只服务 HTTP 的不可变配置模型和安全环境变量校验。

**指定修改文件：**

- 修改：`src/drawing_graph/config.py`
- 修改：`tests/test_config.py`

**可独立测试：**

- `python -m unittest tests.test_config.QAHttpConfigTests -v`

**完成标准：**

- `QAHttpConfig` 包含设计指定的 Neo4j、host、port、remote、origins、token、body size、timeout、concurrency、docs 和 log level 字段。
- 默认值为 `127.0.0.1:8000`、`allow_remote=false`、空 CORS、65536 bytes、30 seconds、8 并发、docs disabled、INFO。
- 非 loopback 必须同时满足 `allow_remote=true` 和非空 token；docs 只允许 loopback；origin 不接受 `*`。
- port、请求大小、超时和并发值执行边界校验；布尔和 origin 环境变量解析明确。
- password 和 token 的 dataclass 字段使用 `repr=False`，repr、错误文本和测试失败输出不包含虚构密钥。
- 不修改 `ImportConfig` 和 `ToolFacadeConfig` 的现有字段或调用方式。

## Task 7: 实现 HTTP 请求模型与领域转换

**明确目标：** 用严格 HTTP 白名单模型接收请求，并一一转换为现有 `QARequest`。

**指定修改文件：**

- 新增：`src/drawing_graph/qa_http_models.py`
- 新增：`tests/test_qa_http_models.py`

**可独立测试：**

- `python -m unittest tests.test_qa_http_models.HttpQARequestTests -v`

**完成标准：**

- 定义 `HttpQAScope` 和 `HttpQARequest`，字段与设计一致，Pydantic 配置拒绝 extra fields。
- 只开放六个已实现 question type；不开放 `unknown_or_unsupported`。
- `language` 只允许 `zh`/`en`，include flags 与 `write_back` 只接受布尔值，业务 ID 有非空和长度约束。
- 转换结果复用现有 `QAScope`/`QARequest`，固定 `format_hint="json"`，不复制 QAService 的完整 scope 业务规则。
- `write_back=true` 可通过协议解析，以便后续由 QAService 拒绝；模型中不存在 URI、凭据、Cypher 或底层对象字段。

## Task 8: 实现 HTTP 响应模型

**明确目标：** 用 HTTP 响应模型验证序列化后的 `QAAnswer`，不重新解释或提升事实类型。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_http_models.py`
- 修改：`tests/test_qa_http_models.py`

**可独立测试：**

- `python -m unittest tests.test_qa_http_models.HttpQAResponseTests -v`

**完成标准：**

- 定义 `HttpEvidenceRef`、`HttpAnswerFact`、`HttpQAAnswer`、`HttpResponseMeta`、成功/错误 envelope 和 health response 模型。
- `HttpQAAnswer` 保留 question type、scope、status、summary、facts、warnings、unsupported parts 和 source calls。
- evidence 保留设计列出的业务追溯字段，但不允许 Neo4j 内部 ID 或 Python 底层对象。
- `CANDIDATE_` 关系和 `matched_candidate` 不能通过模型验证为 `formal_relation`。
- 模型以 `to_jsonable(QAAnswer)` 为输入，不调用 QAService 或 facade。

## Task 9: 实现 HTTP runtime

**明确目标：** 用可注入工厂创建并可靠释放 driver、facade 和 QAService 的进程内 runtime。

**指定修改文件：**

- 新增：`src/drawing_graph/qa_http_runtime.py`
- 新增：`tests/test_qa_http_runtime.py`

**可独立测试：**

- `python -m unittest tests.test_qa_http_runtime -v`

**完成标准：**

- `QAHttpRuntime` 保存 driver、facade、service、ready/closed 状态。
- `create_qa_http_runtime()` 默认依次使用 Neo4j driver factory、`create_neo4j_tool_facade(driver)` 和 `DrawingGraphQAService(facade)`。
- 工厂全部可注入；测试不读取环境变量、不连接真实 Neo4j。
- facade 或 service 初始化失败时关闭已创建 driver，并重新抛出原内部异常供应用层处理。
- `close()` 幂等，首次关闭后 ready=false；重复关闭不重复释放，也不向调用方泄露低层异常。
- runtime 不执行 Cypher、不调用 repository、不运行导入、增强或复核脚本。

## Task 10: 实现无 import 副作用的 FastAPI 应用工厂

**明确目标：** 建立 `create_app(config, runtime_factory)` 和 lifespan，使 runtime 只在应用生命周期内创建一次并关闭一次。

**指定修改文件：**

- 新增：`src/drawing_graph/qa_http.py`
- 新增：`tests/test_qa_http.py`

**可独立测试：**

- `python -m unittest tests.test_qa_http.QAHttpApplicationFactoryTests -v`

**完成标准：**

- import `qa_http.py` 不调用配置 loader、driver factory、runtime factory 或 Uvicorn。
- `create_app()` 接收已构造 config 和可注入 runtime factory。
- TestClient 进入 lifespan 时创建一个 runtime，多个请求复用同一 service，退出时关闭一次。
- startup 任一步失败时应用启动失败，不产生缺少 facade 的“部分可用”业务服务。
- route 只能从 `app.state.qa_runtime` 取得 service，不创建 driver、facade 或 QAService。

## Task 11: 实现请求 ID 与统一安全响应头

**明确目标：** 为每个响应生成服务端 request ID，并统一设置契约元数据和无缓存安全头。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_http.py`
- 修改：`tests/test_qa_http.py`

**可独立测试：**

- `python -m unittest tests.test_qa_http.QAHttpResponseMetadataTests -v`

**完成标准：**

- 每个请求由服务端生成 UUID request ID，不信任客户端同名 header。
- 响应包含 `X-Request-ID`；JSON envelope meta 包含同一 request ID 和固定 `drawing-qa-http-v1`。
- 所有业务响应包含 `Cache-Control: no-store` 与 `X-Content-Type-Options: nosniff`。
- request ID 不写入 `QARequest` 或 `QAAnswer`。

## Task 12: 实现 `QAAnswer` 到 HTTP 的状态映射

**明确目标：** 把结构化 `QAAnswer` 映射为设计规定的 HTTP 状态和 envelope。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_http.py`
- 修改：`tests/test_qa_http.py`

**可独立测试：**

- `python -m unittest tests.test_qa_http.QAAnswerHttpMappingTests -v`

**完成标准：**

- answered/partial 返回 200 success envelope，并完整保留 partial 的 facts、warnings 和 unsupported parts。
- not_found 返回 404 `NOT_FOUND` error envelope；unsupported 返回 422 `UNSUPPORTED_QUESTION`。
- failed 返回脱敏的 500 `INTERNAL_ERROR`。
- error details 只保留安全 question type、scope 字段名和 source calls，不回显完整原始请求值。
- 映射只解释 answer status，不重新分类 candidate/formal 或 semantic/source facts。

## Task 13: 实现 `QAError` 到 HTTP 的状态映射

**明确目标：** 把现有全部 `QAErrorCode` 映射为稳定 HTTP 状态、category 和 retryable。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_http.py`
- 修改：`tests/test_qa_http.py`

**可独立测试：**

- `python -m unittest tests.test_qa_http.QAErrorHttpMappingTests -v`

**完成标准：**

- 422：`INVALID_ARGUMENT`、`UNSUPPORTED_QUESTION`、`UNSUPPORTED_SCOPE`、`PARTIAL_ANSWER`。
- 404：`NOT_FOUND`；403：`WRITE_BACK_FORBIDDEN`；503：facade、Neo4j、semantic evidence unavailable；500：`INTERNAL_ERROR`。
- retryable 只对设计指定的三类依赖不可用错误为 true。
- 所有消息先经共享脱敏；响应不包含 traceback、URI、用户、密码、Cypher 或底层类名。

## Task 14: 实现通用 POST 问答入口

**明确目标：** 提供 `/api/v1/drawing-qa/ask`，让 HTTP 客户端通过唯一权威入口调用 QAService。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_http.py`
- 修改：`tests/test_qa_http.py`

**可独立测试：**

- `python -m unittest tests.test_qa_http.QAHttpPostAskTests -v`

**完成标准：**

- POST 验证 `HttpQARequest`、转换成 `QARequest(format_hint="json")`，只调用一次 `DrawingGraphQAService.ask()`。
- 六类 question type 都能通过 fake QAService 合约测试。
- `write_back=true` 由 QAService 在 facade 调用前拒绝，并映射为 403。
- route 不直接调用任何 facade 方法，不执行 Cypher，不调用 repository。
- success/error envelope 和 contract version 符合任务 11-13 的公共映射。

## Task 15: 实现页面摘要便捷路由

**明确目标：** 提供页面来源事实与可选语义证据的只读 GET adapter。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_http.py`
- 修改：`tests/test_qa_http.py`

**可独立测试：**

- `python -m unittest tests.test_qa_http.QAHttpPageSummaryRouteTests -v`

**完成标准：**

- `GET /api/v1/drawing-qa/pages/{page_id}/summary` 构造 `question_type=page_summary`。
- path ID 原样进入 `QAScope.page_id`；`include_semantics` 可控，其余标志采用设计默认值。
- route 不提供 `write_back`，`include_payload` 固定 false。
- 只调用统一 handler/`QAService.ask()`，不复制 page fact 聚合逻辑。

## Task 16: 实现图块关系便捷路由

**明确目标：** 提供图块追溯、派生关系与可选候选关系的只读 GET adapter。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_http.py`
- 修改：`tests/test_qa_http.py`

**可独立测试：**

- `python -m unittest tests.test_qa_http.QAHttpBlockRelationsRouteTests -v`

**完成标准：**

- `GET /api/v1/drawing-qa/blocks/{block_id}/relations` 构造 `question_type=block_relations`。
- path ID 进入 `QAScope.block_id`，`include_candidates` 可控。
- route 不提供 `write_back`，`include_payload` 固定 false。
- 候选输出仍由 QAService 标为 `candidate_relation`，route 不进行关系提升。

## Task 17: 实现候选关系便捷路由

**明确目标：** 提供 page/block scope 的候选关系列表 GET adapter。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_http.py`
- 修改：`tests/test_qa_http.py`

**可独立测试：**

- `python -m unittest tests.test_qa_http.QAHttpCandidateRelationsRouteTests -v`

**完成标准：**

- `GET /api/v1/drawing-qa/candidates` 构造 `question_type=candidate_relations`。
- `page_id` 或 `block_id` 至少一个存在，两者同时存在时均传给 scope。
- route 不提供 `write_back` 或候选审核参数。
- `matched_candidate` 和 `CANDIDATE_*` 输出不被映射成正式关系。

## Task 18: 实现断面匹配便捷路由

**明确目标：** 提供 cross-section/page scope 的断面候选与正式匹配查询 GET adapter。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_http.py`
- 修改：`tests/test_qa_http.py`

**可独立测试：**

- `python -m unittest tests.test_qa_http.QAHttpSectionMatchesRouteTests -v`

**完成标准：**

- `GET /api/v1/drawing-qa/section-matches` 构造 `question_type=section_matches`。
- `cross_section_id` 或 `page_id` 至少一个存在，两者同时存在时均传给 scope。
- route 不提供 write-back 参数，也不直接调用 `match_section_caption()`。
- formal、candidate、ambiguous、not-found 语义完全由 QAService answer 保留。

## Task 19: 实现表格标题状态便捷路由

**明确目标：** 提供 page/table/table-caption scope 的保守状态查询 GET adapter。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_http.py`
- 修改：`tests/test_qa_http.py`

**可独立测试：**

- `python -m unittest tests.test_qa_http.QAHttpTableCaptionRouteTests -v`

**完成标准：**

- `GET /api/v1/drawing-qa/table-captions/status` 构造 `question_type=table_caption_status`。
- `page_id`、`table_id` 或 `table_caption_id` 至少一个存在，组合 scope 原样传递。
- QAService 返回 partial 和 unsupported parts 时，HTTP 保持 200 success data。
- route 不直接查询 `RelationRepository` 或 Neo4j 来补齐当前未支持状态。

## Task 20: 实现诊断状态便捷路由

**明确目标：** 提供 page/block scope 的只读诊断 GET adapter。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_http.py`
- 修改：`tests/test_qa_http.py`

**可独立测试：**

- `python -m unittest tests.test_qa_http.QAHttpDiagnosticRouteTests -v`

**完成标准：**

- `GET /api/v1/drawing-qa/diagnostics` 构造 `question_type=diagnostic_status`。
- `page_id` 或 `block_id` 至少一个存在，支持 `include_semantics` 和 `include_candidates`。
- route 不把 ready、单元测试或当前查询结果表述为 live Neo4j 已验证。
- route 只调用统一 handler/`QAService.ask()`。

## Task 21: 实现存活健康接口

**明确目标：** 提供不依赖 QA runtime 的最小 ASGI 存活检查。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_http.py`
- 修改：`tests/test_qa_http.py`

**可独立测试：**

- `python -m unittest tests.test_qa_http.QAHttpLiveHealthTests -v`

**完成标准：**

- `GET /health/live` 返回 `status="live"`、service name 和 contract version。
- endpoint 不访问 runtime、QAService、facade 或 Neo4j，无需 Bearer token。
- 响应不包含 host、Neo4j URI、用户、图谱计数、数据路径或环境变量。
- 文案明确仅表示 ASGI 进程能够响应。

## Task 22: 实现就绪健康接口

**明确目标：** 提供只检查 runtime 装配状态、绝不冒充数据库验证的 readiness endpoint。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_http.py`
- 修改：`tests/test_qa_http.py`

**可独立测试：**

- `python -m unittest tests.test_qa_http.QAHttpReadyHealthTests -v`

**完成标准：**

- `GET /health/ready` 在 runtime ready 且未关闭时返回 200、`status="ready"`、`neo4j_status="not_checked"`。
- runtime 不存在、未 ready 或正在关闭时返回 503。
- endpoint 不调用 `driver.verify_connectivity()`、session、Cypher 或 facade 查询。
- 配置 token 时 readiness 进入认证保护；`/health/live` 仍匿名。

## Task 23: 实现 Bearer token 认证

**明确目标：** 为业务 route 和可配置的 readiness 提供固定消息、恒定时间比较的可选 Bearer token 认证。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_http.py`
- 修改：`tests/test_qa_http.py`

**可独立测试：**

- `python -m unittest tests.test_qa_http.QAHttpAuthenticationTests -v`

**完成标准：**

- 未配置 token 且为 loopback 时允许业务请求；配置 token 后要求标准 `Authorization: Bearer <token>`。
- 缺失凭据返回 401 `AUTHENTICATION_REQUIRED`，错误凭据返回 401 `AUTHENTICATION_FAILED`。
- 使用恒定时间比较；响应和日志不暴露 token 长度、前缀、匹配位置或原值。
- token 不进入 URL、query、HTTP DTO、response 或 request ID。
- `/health/live` 始终不要求认证。

## Task 24: 实现显式 CORS allowlist

**明确目标：** 只在配置非空 origin allowlist 时启用最小 CORS 行为。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_http.py`
- 修改：`tests/test_qa_http.py`

**可独立测试：**

- `python -m unittest tests.test_qa_http.QAHttpCorsTests -v`

**完成标准：**

- allowed origins 为空时不安装 CORS middleware。
- 只允许显式 http/https origins，禁止 `*`，不自动从 host 推导 origin。
- 仅允许 GET、POST、OPTIONS 和必要的 Authorization/Content-Type headers。
- `allow_credentials=false`，不使用 cookie 或服务端 session。

## Task 25: 实现请求体大小限制

**明确目标：** 按实际接收字节限制请求体，超限时在进入模型校验和 QAService 前返回 413。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_http.py`
- 修改：`tests/test_qa_http.py`

**可独立测试：**

- `python -m unittest tests.test_qa_http.QAHttpRequestSizeTests -v`

**完成标准：**

- 限制采用 `config.max_request_bytes`，不只信任 `Content-Length`。
- 超限返回 413 `REQUEST_TOO_LARGE` 的标准错误 envelope。
- 超限请求不调用 QAService，不把完整 body 写入日志或响应。
- 普通小请求和缺失/错误 Content-Length 不绕过实际字节计数。

## Task 26: 实现应用级并发上限

**明确目标：** 限制同时执行 `QAService.ask()` 的同步调用数，容量用尽时快速返回 429。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_http.py`
- 修改：`tests/test_qa_http.py`

**可独立测试：**

- `python -m unittest tests.test_qa_http.QAHttpConcurrencyLimitTests -v`

**完成标准：**

- 并发容量来自 `config.max_concurrent_requests`。
- semaphore 由实际执行同步 `QAService.ask()` 的调用获取，并在该调用真正结束后的 `finally` 释放。
- 容量已满时快速返回 429 `TOO_MANY_REQUESTS`，不无限排队，也不调用 service。
- 测试用阻塞 fake service 证明容量在调用结束前不会提前释放。

## Task 27: 实现 HTTP 等待超时

**明确目标：** 限制客户端等待 QA 回答的时间，并诚实保留同步底层调用不可硬取消的语义。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_http.py`
- 修改：`tests/test_qa_http.py`

**可独立测试：**

- `python -m unittest tests.test_qa_http.QAHttpTimeoutTests -v`

**完成标准：**

- 等待超过 `config.request_timeout_seconds` 返回 504 `REQUEST_TIMEOUT`。
- timeout 不伪装成 Neo4j 硬取消；已启动的同步调用结果被丢弃，但允许其安全完成。
- 超时响应不会提前释放任务 26 的并发容量；实际调用结束后容量才释放。
- timeout 消息和日志不包含完整请求、answer、secret 或 traceback。

## Task 28: 统一 HTTP 协议错误响应

**明确目标：** 将框架校验、未知路由、错误 method 和未分类异常转换为统一且脱敏的错误 envelope。

**指定修改文件：**

- 修改：`src/drawing_graph/qa_http.py`
- 修改：`tests/test_qa_http.py`

**可独立测试：**

- `python -m unittest tests.test_qa_http.QAHttpProtocolErrorTests -v`

**完成标准：**

- Pydantic/FastAPI 校验失败返回 422 `INVALID_ARGUMENT`，details 只含安全字段路径和错误类型。
- 未知 route 返回 404 `ROUTE_NOT_FOUND`；不允许的 method 返回 405 `METHOD_NOT_ALLOWED`。
- 未分类异常返回 500 `HTTP_INTERNAL_ERROR`，客户端无 traceback 和低层对象信息。
- 所有错误响应包含 request ID、contract version 和安全响应头。
- HTTP adapter 自有类别不加入 `QAErrorCode`。

## Task 29: 实现单 worker 服务启动脚本

**明确目标：** 提供只从环境变量启动 HTTP 服务的薄 Uvicorn 入口。

**指定修改文件：**

- 新增：`scripts/serve_drawing_graph_qa.py`
- 新增：`tests/test_qa_http_cli.py`

**可独立测试：**

- `python -m unittest tests.test_qa_http_cli -v`

**完成标准：**

- `main()` 执行 `QAHttpConfig.from_env() -> create_app(config) -> uvicorn.run(...)`。
- 固定 `workers=1`，使用配置 host、port 和 log level；不暴露绕过单 worker 的 CLI 参数。
- 脚本 import 不读取环境变量、不启动 server、不创建 driver。
- 不接受 Neo4j password、API token 或其他 secret 命令行参数。
- 配置/初始化错误输出脱敏并返回非零退出码；启动摘要不包含 token、password 或完整 URI query。

## Task 30: 更新 HTTP 当前实现文档

**明确目标：** 在实现完成后同步 HTTP 使用方法、模块职责、架构边界和仍未实现范围。

**指定修改文件：**

- 修改：`README.md`
- 修改：`Module.md`
- 修改：`architecture.md`
- 修改：`tests/test_qa_docs.py`
- 新增：`tests/test_qa_http_docs.py`

**可独立测试：**

- `python -m unittest tests.test_qa_docs tests.test_qa_http_docs tests.test_readme tests.test_module_docs -v`

**完成标准：**

- README 给出启动环境变量、`python scripts/serve_drawing_graph_qa.py`、health 和一个最小只读请求示例。
- Module 记录 serialization、HTTP models、runtime、app、启动脚本、新依赖和 lifecycle。
- architecture 记录 `HTTP adapter -> DrawingGraphQAService -> DrawingGraphToolFacade -> ports/services -> repository/Neo4j`。
- 文档明确 loopback、single worker、read-only、CORS/docs 默认关闭、外部 TLS 要求和 health 不等于 live Neo4j 验证。
- 文档继续把 MCP、Ava 专有 adapter、OCR、全量扫描和 HTTP 写回标为未实现。
- 删除第一阶段“HTTP 尚未实现”的过期断言，但不把目标设计提前写成已完成现状。

## Task 31: 增加 HTTP 静态依赖边界测试

**明确目标：** 用静态测试锁定 HTTP route 只能调用 QAService 的架构边界。

**指定修改文件：**

- 修改：`tests/test_qa_http.py`

**可独立测试：**

- `python -m unittest tests.test_qa_http.QAHttpStaticBoundaryTests -v`

**完成标准：**

- 检查 `qa_http.py` 不导入或引用 `QueryService`、`RelationRepository`、`block_relation_enrichment.py`、Cypher、Neo4j session/transaction。
- 检查业务 route 不直接调用 facade 的 page/block/candidate/section/recognition/review 方法。
- 检查 HTTP 代码不触发导入、离线增强、候选审核写回、语义证据持久化或正式关系提升。
- 检查原则上不修改模块列表未因 HTTP 接入发生领域契约变化；若确有变化，实施必须先回到设计评审。

## Task 32: 执行第二阶段全量单元回归

**明确目标：** 证明 HTTP adapter 没有破坏第一阶段 QA/CLI、facade、语义证据、候选关系和既有导入增强单元行为。

**指定修改文件：**

- 修改：`changes/tool层/第二阶段/tasks.md`，仅在实施完成后追加本任务的实际验收记录。
- 不修改业务代码。

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest discover tests -v`

**完成标准：**

- 全量单元测试命令退出码为 0，并记录实际运行数、通过数、失败数和跳过数。
- 第一阶段 `test_qa_models`、`test_qa_service`、`test_qa_rendering`、`test_qa_cli` 和文档边界测试继续通过。
- skipped 测试单独列出原因，不写成通过。
- 验收记录只引用本次新鲜命令输出，不沿用历史测试数字。

## Task 33: 执行本机 HTTP socket smoke test

**明确目标：** 通过真实单 worker Uvicorn socket 验证 HTTP 协议和正常关闭，不把 TestClient 结果冒充真实服务验证。

**指定修改文件：**

- 修改：`changes/tool层/第二阶段/tasks.md`，仅在实施完成后追加本任务的实际验收记录。
- 不修改业务代码。

**可独立测试：**

- 使用 loopback、临时端口和 fake runtime 启动单 worker Uvicorn，依次请求 `/health/live`、`/health/ready`、一个受控 QA endpoint、Bearer token 开关，然后正常终止服务。

**完成标准：**

- 真实 socket 返回预期状态、envelope、request ID、contract version 和安全响应头。
- token 关闭/开启行为分别符合任务 23；服务关闭时 fake driver/runtime 只关闭一次。
- 测试使用 `127.0.0.1` 和临时端口，不开放远程绑定，不写真实密钥。
- 验收记录明确这是 HTTP socket smoke test；使用 fake runtime 时不声称真实 Neo4j 查询通过。

## Task 34: 执行 disposable Neo4j 集成验证

**明确目标：** 在明确配置 disposable Neo4j 时验证一条真实只读 QA HTTP 调用链，并如实记录 live Neo4j 状态。

**指定修改文件：**

- 修改：`changes/tool层/第二阶段/tasks.md`，仅在实施完成后追加本任务的实际验收记录。
- 不修改业务代码或 Neo4j Schema。

**可独立测试：**

- `$env:PYTHONPATH='src'; python -m unittest discover tests.integration -v`

**完成标准：**

- 只有 `NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD` 指向 disposable 测试库且集成测试实际运行通过，才能记录 live Neo4j verified。
- 未配置环境时记录测试 skipped 和“live Neo4j 未验证”，不得记录为 passed。
- `/health/live`、`/health/ready`、TestClient 或 fake runtime 结果均不能替代此验证。
- 验证只走 HTTP -> QAService -> facade 受控链路，不直接执行 Cypher，也不触发写回或正式关系提升。

## 验收记录（Task 31–34）

### Task 32：第二阶段全量单元回归

- 执行时间：2026-08-10（Asia/Shanghai）。
- 命令：`$env:PYTHONPATH='src'; python -m unittest discover tests`
- 新鲜输出：`Ran 784 tests in 2.516s`，`OK (skipped=3)`，退出码 0。
- 统计：通过 781，失败 0，跳过 3（`tests/integration/` 因未配置 `NEO4J_TEST_URI`/`NEO4J_TEST_USER`/`NEO4J_TEST_PASSWORD` 按设计跳过）。
- 第一阶段 `test_qa_models`、`test_qa_service`、`test_qa_rendering`、`test_qa_cli` 与文档边界测试继续通过。
- skipped 不等于 live Neo4j 通过；live Neo4j 状态以 Task 34 记录为准。

### Task 33：本机 HTTP socket smoke test

- 执行时间：2026-08-10（Asia/Shanghai）。
- 方式：`127.0.0.1` + 临时端口，单 worker Uvicorn，fake driver/facade/service 装配的 `create_app()`；使用真实 socket（httpx）请求后正常关闭服务。
- 无 token 场景：`/health/live` 200（`status=live`）；`/health/ready` 200（`neo4j_status="not_checked"`）；`GET /api/v1/drawing-qa/pages/page:1/summary` 200（`question_type=page_summary`）；响应含 `X-Request-ID` 且与 envelope `meta.request_id` 一致；`Cache-Control: no-store`、`X-Content-Type-Options: nosniff`；`ask_calls=1`；关闭后 fake driver `close_calls=1`。
- 带 token 场景：`/health/live` 匿名 200；业务路由无 token 401（`AUTHENTICATION_REQUIRED`）；带 `Bearer smoke-token-abc` 200；`ask_calls=1`；关闭后 fake driver `close_calls=1`。
- 本记录是 HTTP socket smoke test，使用 fake runtime，**不代表真实 Neo4j 查询通过**；live Neo4j 状态见 Task 34。

### Task 34：disposable Neo4j 集成验证

- 执行时间：2026-08-10（Asia/Shanghai）。
- 环境检查：`NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD` 均未配置。
- 命令与新鲜输出：`$env:PYTHONPATH='src'; python -m unittest discover tests.integration -v` → `Ran 3 tests in 0.000s`，`OK (skipped=3)`，退出码 0；跳过原因均为 `NEO4J_TEST_URI, NEO4J_TEST_USER, and NEO4J_TEST_PASSWORD are required`。
- 结论：live Neo4j **未验证**（skipped 不等于 passed）；HTTP -> QAService -> facade 受控链路的真实 Neo4j 只读验证未执行，`/health/live`、`/health/ready`、TestClient 与 Task 33 的 fake runtime smoke 均不能替代此项验证。
