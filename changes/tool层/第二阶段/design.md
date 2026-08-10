# Tool 层第二阶段 HTTP API 技术设计

本设计依据：

- `changes/tool层/第二阶段/Feature_Analysis_Report.md`
- `changes/tool层/第二阶段/proposal.md`
- 当前 `README.md`、`Module.md`、`architecture.md`
- 当前 `qa_models.py`、`qa_service.py`、`qa_rendering.py`、`tool_factory.py`、`config.py`、`scripts/drawing_graph_qa.py` 及相关测试

目标是在现有 Tool 层第一阶段之上增加版本化、默认本机监听、默认只读的 HTTP API。设计优先复用 `DrawingGraphQAService`、`DrawingGraphToolFacade`、现有 QA DTO、现有工厂和 CLI 已验证行为，不重写业务编排，不修改 Neo4j Schema，不做无意义重构。

核心原则：

- HTTP 是新的协议 adapter，不是新的业务逻辑层。
- 所有 HTTP 业务请求只调用 `DrawingGraphQAService.ask()`。
- `DrawingGraphQAService` 继续只通过 `DrawingGraphToolFacade` 使用图谱能力。
- 默认 `write_back=false`；第二阶段 HTTP 不提供任何持久化或正式关系提升入口。
- 来源事实、派生关系、语义观察、语义解释、候选关系和正式关系必须保持分层。
- 模块 import 不读取环境变量、不创建 driver、不连接 Neo4j。
- 第一版单进程、受控并发；进程内 run log、payload store 和 cache 不被描述为跨进程共享状态。

## 1. 系统架构变化

### 1.1 当前架构

当前已实现调用链：

```text
QA CLI
  -> DrawingGraphQAService
      -> DrawingGraphToolFacade
          -> read ports / semantic services / section match service / candidate review service
              -> controlled repository / Neo4j
```

当前职责已经清晰：

- `DrawingGraphQAService` 负责问题类型路由、scope 校验、证据聚合和结构化 `QAAnswer`。
- `DrawingGraphToolFacade` 负责稳定图谱能力边界和 `write_back` 策略。
- QA CLI 负责参数解析、driver 生命周期、JSON/中文输出和错误脱敏。
- repository 和 Neo4j 只位于 facade 下游，QAService 不直接访问。

因此第二阶段不新增第二套 QAService，不让 HTTP route 直接组合 facade 方法，也不把 FastAPI/Pydantic 类型放入现有领域 DTO。

### 1.2 目标架构

新增 HTTP 调用链：

```text
Ava / local web client / local application
  -> Uvicorn
      -> FastAPI application
          -> request size / request ID / CORS / authentication / concurrency middleware
          -> HTTP request model
          -> QARequest
          -> DrawingGraphQAService.ask()
          -> QAAnswer
          -> shared serialization / HTTP response model
          -> JSON response
```

完整依赖方向：

```text
scripts/serve_drawing_graph_qa.py
  -> QAHttpConfig
  -> create_app(config, runtime_factory)
      -> application lifespan
          -> create_qa_http_runtime(config)
              -> Neo4j driver
              -> create_neo4j_tool_facade(driver)
              -> DrawingGraphQAService(facade)
      -> HTTP routes
          -> DrawingGraphQAService.ask(QARequest)
              -> DrawingGraphToolFacade
                  -> ports / services
                      -> controlled repository / Neo4j
```

### 1.3 adapter 同级关系

CLI、HTTP 和未来 MCP/Ava 专有 adapter 是同级入口：

```text
QA CLI adapter -----|
HTTP API adapter ---|-> DrawingGraphQAService -> DrawingGraphToolFacade
future MCP adapter -|
```

禁止 adapter 相互调用：

- HTTP route 不执行 `scripts/drawing_graph_qa.py` 子进程。
- QA CLI 不通过 localhost HTTP 反调服务。
- 未来 MCP adapter 不抓取 HTTP 输出再转换。

三者可以复用序列化、错误 envelope、脱敏和领域 DTO，但业务编排只有一份，位于 `DrawingGraphQAService`。

### 1.4 应用生命周期

采用 FastAPI lifespan 管理长生命周期资源：

```text
application import
  -> 只定义类、函数和常量
  -> 不读环境变量
  -> 不创建 driver

server main
  -> QAHttpConfig.from_env()
  -> create_app(config, runtime_factory)

lifespan startup
  -> runtime_factory(config)
  -> driver_factory(uri, auth)
  -> create_neo4j_tool_facade(driver)
  -> DrawingGraphQAService(facade)
  -> app.state.qa_runtime = runtime
  -> ready = true

request handling
  -> 从 app.state 取 service
  -> service.ask(request)

lifespan shutdown
  -> ready = false
  -> runtime.close()
  -> driver.close()
```

生命周期规则：

- startup 任一步失败时，关闭已经创建的 driver，并让应用启动失败，不进入“部分可用”服务状态。
- `QAHttpRuntime.close()` 必须幂等，重复调用不重复释放资源或抛出低层异常。
- route 不创建 driver、facade 或 QAService。
- 测试可以注入 fake runtime factory，不需要环境变量和真实 Neo4j。

FastAPI 官方推荐通过 lifespan 管理启动和关闭资源；当前同步 QAService/Neo4j 调用保持同步 path operation，由框架在线程池中运行，不为第二阶段重写成异步数据访问层。

### 1.5 并发与进程模型

第二阶段采用：

- Uvicorn 单 worker。
- 同步 route 调用同步 QAService。
- 应用级并发上限，超过上限时快速返回，不无限排队。
- 请求等待超时只限制客户端等待时间；超时后底层同步线程可能仍完成当前调用，因此必须同时设置并发上限，避免超时请求无限累积。
- 并发 semaphore 由执行 `QAService.ask()` 的同步调用在进入时获取，并在该调用真正结束后的 `finally` 中释放；HTTP timeout middleware 不负责提前释放该容量。

本阶段不修改 `QueryService` 事务模型来实现硬取消。真正的数据库查询取消、跨进程共享缓存和多 worker 一致性属于后续独立优化，不能借 HTTP 阶段重构底层查询层。

### 1.6 健康状态语义

健康状态分为：

| 状态 | 含义 | 不代表 |
|---|---|---|
| live | ASGI 进程能够返回响应 | runtime 已创建、Neo4j 可用、图谱数据正确 |
| ready | runtime 已创建且 QAService 已放入 app state | 已执行 live Neo4j 查询、集成测试已通过 |
| live Neo4j verified | disposable Neo4j 集成测试实际运行并通过 | 不能由 health endpoint 自动推断 |

`/health/ready` 返回中必须显式包含 `neo4j_status="not_checked"`，除非未来新增经过 facade 的专用健康能力并单独设计。第二阶段不直接调用 driver `verify_connectivity()` 作为图谱业务验证，也不把 runtime 构造成功写成数据库通过。

## 2. 新增模块

### 2.1 `src/drawing_graph/qa_serialization.py`

职责：提供 CLI 和 HTTP 共用的框架无关 JSON 序列化、响应 envelope 和错误脱敏。

建议公开接口：

| 接口 | 职责 |
|---|---|
| `to_jsonable(value)` | 递归转换 dataclass、Enum、tuple/list、Path、dict 和只读 mapping |
| `build_success_envelope(data, meta=None)` | 构造 `status="ok"` 的稳定 envelope |
| `build_error_envelope(category, message, retryable, meta=None, details=None)` | 构造 `status="failed"` 的稳定 envelope |
| `sanitize_error_message(message)` | 清洗密码、token、secret、Cypher、driver/session/transaction 和低层连接细节 |

设计边界：

- 只使用 Python 标准库和 QA DTO，不依赖 FastAPI、Pydantic、Uvicorn 或 Neo4j。
- 不调用 QAService 或 facade。
- 不读取环境变量。
- 不改变 `fact_kind`、status、relation type 或 evidence。
- CLI 调用 `build_success_envelope(data)` 时可以不带 `meta`，保持现有 JSON 兼容；HTTP 必须带 request ID 和 contract version。

### 2.2 `src/drawing_graph/qa_http_models.py`

职责：定义 HTTP 协议模型，并在 HTTP 模型和现有领域 DTO 之间转换。

建议模型：

| 模型 | 作用 |
|---|---|
| `HttpQAScope` | HTTP scope 字段白名单，与 `QAScope` 一一映射 |
| `HttpQARequest` | 通用 POST 请求模型 |
| `HttpEvidenceRef` | HTTP 证据响应模型 |
| `HttpAnswerFact` | HTTP fact 响应模型 |
| `HttpQAAnswer` | HTTP QA answer 响应模型 |
| `HttpResponseMeta` | request ID、contract version |
| `HttpSuccessEnvelope` | 成功响应模型 |
| `HttpErrorBody` | category、message、retryable、可选 details |
| `HttpErrorEnvelope` | 错误响应模型 |
| `HttpHealthResponse` | live/ready 响应模型 |

请求模型规则：

- 使用明确字段白名单并拒绝未知字段。
- `question_type` 只允许六个已实现业务类型：`page_summary`、`block_relations`、`candidate_relations`、`section_matches`、`table_caption_status`、`diagnostic_status`。
- `unknown_or_unsupported` 是 QA 内部保守结果，不作为 HTTP 客户端可主动调用的 question type。
- `scope` 字段只允许现有稳定业务 ID，不包含数据库内部 ID。
- `language` 只允许 `zh` 或 `en`。
- `include_semantics`、`include_candidates`、`include_payload` 和 `write_back` 必须是布尔值。
- `write_back` 默认 `false`；`true` 可以完成协议解析，但转换到 QAService 后必须被 `WRITE_BACK_FORBIDDEN` 拒绝并返回 403，不能调用 facade。
- HTTP 不暴露 `format_hint`；adapter 固定构造 `format_hint="json"`。
- 请求模型不包含 URI、用户名、密码、API key、token、Cypher、driver、session、transaction 或 repository 字段。

响应模型规则：

- HTTP 响应模型验证 `qa_serialization.to_jsonable(QAAnswer)` 的结果，不重新解释事实。
- `relation_type` 以 `CANDIDATE_` 开头时，`fact_kind` 必须仍为 `candidate_relation`。
- `source_calls` 可返回，用于追踪 QAService 使用的稳定 facade 能力；不得包含 Cypher 或 repository 方法。
- 响应不返回 Python 类型名、堆栈、driver/session 对象或 Neo4j 内部节点 ID。

### 2.3 `src/drawing_graph/qa_http_runtime.py`

职责：管理 HTTP 服务的外层运行资源。

建议模型与接口：

| 模型或接口 | 职责 |
|---|---|
| `QAHttpRuntime` | 保存 driver、facade、service 和 ready 状态 |
| `QAHttpRuntime.close()` | 幂等关闭 driver 并清理引用 |
| `create_qa_http_runtime(config, driver_factory, facade_factory, service_factory)` | 以可注入工厂创建完整 runtime |

默认工厂映射：

```text
driver_factory -> neo4j.GraphDatabase.driver
facade_factory -> create_neo4j_tool_facade
service_factory -> DrawingGraphQAService
```

设计边界：

- 只有该 runtime 和服务启动脚本知道 Neo4j driver。
- runtime 不执行 Cypher，不调用 repository，不运行导入或增强脚本。
- `create_neo4j_tool_facade(driver)` 仍是唯一生产 facade 装配入口。
- facade 和 QAService 的业务实现不因 HTTP 改变。
- 初始化异常时关闭已创建 driver，再抛出脱敏前的内部异常给应用层统一处理。

### 2.4 `src/drawing_graph/qa_http.py`

职责：提供 FastAPI 应用工厂、middleware、路由和异常处理器。

建议公开接口：

| 接口 | 职责 |
|---|---|
| `create_app(config, runtime_factory=create_qa_http_runtime)` | 创建无 import 副作用、可注入 runtime 的 FastAPI app |
| `get_qa_service(request)` | 从 `request.app.state.qa_runtime` 读取 service |
| `map_answer_to_http(answer, request_id)` | 把 QAAnswerStatus 映射为 HTTP 状态和 envelope |
| `map_error_to_http(error, request_id)` | 把 QAError 映射为 HTTP 状态和脱敏错误 envelope |

内部职责：

- application lifespan。
- request ID 生成和响应 header。
- 请求大小限制。
- 可选 Bearer token 校验。
- 可选显式 CORS allowlist。
- 并发上限和请求等待超时。
- 安全响应 header。
- 版本化路由注册。
- FastAPI request validation、QAError、HTTPException 和未分类异常的统一 envelope。

禁止：

- 不导入 `QueryService`、`RelationRepository` 或 `block_relation_enrichment.py`。
- 不创建 Cypher 字符串。
- 不直接调用 facade 的 page/block/candidate 方法。
- 不调用候选复核、语义写回或正式关系提升。

### 2.5 `scripts/serve_drawing_graph_qa.py`

职责：提供服务启动入口。

流程：

```text
main
  -> QAHttpConfig.from_env()
  -> create_app(config)
  -> uvicorn.run(app, host=config.host, port=config.port, workers=1)
```

边界：

- 只在 `main()` 中读取环境变量和启动 server。
- 模块 import 不启动 server、不连接 Neo4j。
- 固定单 worker；第二阶段不暴露可绕过该限制的默认配置。
- 配置错误在启动前输出脱敏消息并返回非零退出码。
- 不接受 Neo4j 凭据作为命令行参数，避免进入进程列表和 shell 历史。

### 2.6 新增测试模块

| 测试文件 | 覆盖内容 |
|---|---|
| `tests/test_qa_serialization.py` | JSON 转换、envelope、CLI 兼容、脱敏 |
| `tests/test_qa_http_models.py` | 字段白名单、scope、question type、write-back、响应事实分层 |
| `tests/test_qa_http_runtime.py` | runtime 创建、注入、初始化失败清理、幂等关闭 |
| `tests/test_qa_http.py` | route、status code、middleware、auth、CORS、health、异常 envelope |
| `tests/test_qa_http_cli.py` | 启动脚本配置、单 worker、退出码和脱敏 |
| `tests/test_qa_http_docs.py` | 当前实现边界和未实现范围 |

测试继续使用标准库 `unittest`；FastAPI TestClient/HTTPX 只作为 HTTP 调用工具，不要求把整个测试体系迁移为 pytest。

## 3. 修改模块

### 3.1 `src/drawing_graph/config.py`

新增不可变 `QAHttpConfig`，不改动 `ImportConfig` 和 `ToolFacadeConfig` 的现有字段或调用方式。

建议字段：

| 字段 | 来源 | 默认或约束 |
|---|---|---|
| `neo4j_uri` | `NEO4J_URI` | 必需，repr 可显示 URI 但错误输出需脱敏连接细节 |
| `neo4j_user` | `NEO4J_USER` | 必需 |
| `neo4j_password` | `NEO4J_PASSWORD` | 必需，`repr=False` |
| `host` | `DRAWING_GRAPH_QA_HTTP_HOST` | 默认 `127.0.0.1` |
| `port` | `DRAWING_GRAPH_QA_HTTP_PORT` | 默认 `8000`，1-65535 |
| `allow_remote` | `DRAWING_GRAPH_QA_HTTP_ALLOW_REMOTE` | 默认 `false` |
| `allowed_origins` | `DRAWING_GRAPH_QA_HTTP_ALLOWED_ORIGINS` | 默认空；只允许明确 http/https origin，不允许 `*` |
| `api_token` | `DRAWING_GRAPH_QA_HTTP_API_TOKEN` | 可选，`repr=False`；非 loopback 时必需 |
| `max_request_bytes` | `DRAWING_GRAPH_QA_HTTP_MAX_REQUEST_BYTES` | 默认 65536，必须为正整数 |
| `request_timeout_seconds` | `DRAWING_GRAPH_QA_HTTP_REQUEST_TIMEOUT_SECONDS` | 默认 30，必须为正数 |
| `max_concurrent_requests` | `DRAWING_GRAPH_QA_HTTP_MAX_CONCURRENT_REQUESTS` | 默认 8，必须为正整数 |
| `docs_enabled` | `DRAWING_GRAPH_QA_HTTP_DOCS_ENABLED` | 默认 `false` |
| `log_level` | `DRAWING_GRAPH_QA_HTTP_LOG_LEVEL` | 默认 `INFO` |

配置校验：

- loopback 只允许 `127.0.0.1`、`::1` 或 `localhost` 等明确本机地址。
- 非 loopback host 必须同时满足 `allow_remote=true` 和非空 `api_token`；否则启动失败。
- 非 loopback 部署还必须由部署文档要求外部 TLS/反向代理，本阶段应用自身不实现 TLS 证书管理。
- `allowed_origins` 不接受通配符，不自动等于 host。
- `docs_enabled=true` 只允许 loopback；远程部署不开放自动文档。
- API token、Neo4j password 不出现在 `repr`、错误输出或日志中。

不重构 `ImportConfig` 的理由：HTTP 只读服务不需要 data root、project slug 和 batch size。直接复用 `ImportConfig.from_env()` 会让无关导入配置阻断 HTTP 启动；为抽取三个 Neo4j 字段重构所有现有 CLI 则扩大影响面。新增窄口径配置是本阶段最小改动。

### 3.2 `scripts/drawing_graph_qa.py`

只做以下兼容性修改：

- 删除脚本私有 `_jsonable()` 实现，改用 `qa_serialization.to_jsonable()`。
- 成功 JSON 改用共享 `build_success_envelope()`，但保持现有 `status` 和 `data` 字段不变。
- 错误输出改用共享 `build_error_envelope()` 和 `sanitize_error_message()`，保持退出码规则不变。
- `zh-brief` 渲染继续使用 `qa_rendering.py`，不经过 HTTP 模型。

禁止改变现有子命令、参数、默认 format、退出码和 driver 生命周期。

### 3.3 `requirements.txt`

新增受控兼容范围：

- FastAPI：HTTP 应用、Pydantic request/response model 和 TestClient 集成。
- Uvicorn：ASGI server。
- HTTPX：HTTP adapter 单元测试的显式测试依赖。

不新增 Flask、Django、MCP SDK、Ava SDK、云模型 SDK、任务队列或 ORM。实际版本范围在实施时以 Python 3.11 和专项测试验证结果确定，不在设计文档中锁死未经验证的精确补丁版本。

### 3.4 文档与文档测试

实现后修改：

- `README.md`：增加 HTTP 启动、环境变量、最小请求、安全默认值和验证说明。
- `Module.md`：记录新模块、新接口、新依赖和 runtime 生命周期。
- `architecture.md`：将 HTTP adapter 标为已实现，同时继续把 MCP、Ava 专有 adapter、OCR、全量扫描和写回 HTTP 标为未实现。
- `tests/test_qa_docs.py`：移除“第二阶段 HTTP 未实现”的旧断言。
- `tests/test_qa_http_docs.py`：保护版本化 API、loopback 默认值、只读、candidate/formal 分层和 live Neo4j 验证边界。

### 3.5 原则上不修改

以下模块在第二阶段没有设计缺口，原则上不修改：

- `qa_models.py`
- `qa_service.py`
- `qa_rendering.py`
- `tool_facade.py`
- `tool_factory.py`
- `query_service.py`
- `relation_repository.py`
- `semantic_*`
- `candidate_review.py`
- `block_relation_enrichment.py`
- `import_service.py`
- 导入、增强和候选复核 CLI
- `scripts/create_schema.cypher`

如果实施测试发现必须修改这些模块，应先确认是否属于窄口径兼容修复；若需要改变领域契约、查询行为或写回逻辑，应停止当前任务并回到设计评审，不以 HTTP 适配为由顺带重构。

## 4. 数据模型变化

### 4.1 Neo4j 数据模型

第二阶段不新增或修改：

- Neo4j 节点标签。
- Neo4j 关系类型。
- 约束和索引。
- 来源事实字段。
- 派生关系属性。
- 语义证据节点和边。
- 候选关系和正式关系提升规则。

`RecognitionRun` 继续是图谱外运行日志；`TextObservation` 与三类 `Interpretation` 继续是图谱内语义证据；二者只通过 `recognition_run_id` 关联。

### 4.2 领域 QA 数据模型

现有 `QuestionType`、`QAScope`、`QARequest`、`EvidenceRef`、`AnswerFact`、`QAAnswer`、`QAError` 和 `QAErrorCode` 保持不变。

HTTP 层复用规则：

- `HttpQAScope -> QAScope` 一一映射。
- `HttpQARequest -> QARequest` 时固定 `format_hint="json"`。
- `QAAnswer -> to_jsonable() -> HttpQAAnswer`，不重新分类 fact。
- HTTP request ID 不写入 `QARequest` 或 `QAAnswer`，只位于 response meta 和日志上下文。

### 4.3 HTTP 请求模型

`HttpQARequest` 字段：

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `question_type` | 受控字符串枚举 | 无 | 只允许六类外部问题 |
| `scope` | `HttpQAScope` | 无 | 业务 ID 范围 |
| `language` | `zh` / `en` | `zh` | 传给 QARequest |
| `include_semantics` | bool | `true` | 是否包含可用语义证据 |
| `include_candidates` | bool | `true` | 是否包含候选关系 |
| `include_payload` | bool | `false` | 是否包含 QAService 已允许的 payload；不新增独立 payload endpoint |
| `write_back` | bool | `false` | `true` 时由 QAService 拒绝，HTTP 映射为 403 |

`HttpQAScope` 字段与 `QAScope` 相同：

- `project_id`
- `drawing_set_id`
- `page_id`
- `block_id`
- `cross_section_id`
- `table_id`
- `table_caption_id`
- `element_id`

HTTP model 先做类型、长度和未知字段校验；问题类型所需的 scope 规则继续由 `DrawingGraphQAService` 作为权威校验。HTTP 层可以提前拒绝明显缺失，但不能复制全部业务校验并形成第二套规则。

### 4.4 HTTP 响应模型

`HttpQAAnswer` 保持以下字段：

- `question_type`
- `scope`
- `status`
- `summary`
- `facts`
- `warnings`
- `unsupported_parts`
- `source_calls`

`HttpAnswerFact` 保持：

- `fact_kind`
- `label`
- `status`
- `ids`
- `relation_type`
- `value`
- `evidence`
- `payload`

`HttpEvidenceRef` 保持现有可追溯字段，包括业务 ID、page ID、image path、bbox、normalized bbox、recognition run ID、observation/interpretation ID、payload ref、candidate group ID、rule version 和 review run ID。

事实类型固定：

```text
source_fact
derived_relation
semantic_observation
semantic_interpretation
candidate_relation
formal_relation
diagnostic
unsupported
```

HTTP serializer 不允许把 `candidate_relation`、`matched_candidate` 或模型解释提升为 `formal_relation`。

### 4.5 HTTP envelope

成功 envelope：

| 字段 | 内容 |
|---|---|
| `status` | 固定 `ok` |
| `data` | `HttpQAAnswer` |
| `meta.request_id` | 服务端生成 UUID 字符串 |
| `meta.contract_version` | 固定 `drawing-qa-http-v1` |

错误 envelope：

| 字段 | 内容 |
|---|---|
| `status` | 固定 `failed` |
| `error.category` | QA 错误码或 HTTP adapter 错误类别 |
| `error.message` | 脱敏后的短消息 |
| `error.retryable` | 布尔值 |
| `error.details` | 可选，只包含安全字段名、scope 摘要或验证位置，不含输入值、密钥或堆栈 |
| `meta.request_id` | 服务端生成 UUID 字符串 |
| `meta.contract_version` | 固定 `drawing-qa-http-v1` |

HTTP adapter 自有错误类别：

- `AUTHENTICATION_REQUIRED`
- `AUTHENTICATION_FAILED`
- `REQUEST_TOO_LARGE`
- `TOO_MANY_REQUESTS`
- `REQUEST_TIMEOUT`
- `ROUTE_NOT_FOUND`
- `METHOD_NOT_ALLOWED`
- `HTTP_INTERNAL_ERROR`

这些错误类别只存在于 HTTP response，不进入 `QAErrorCode`，避免把协议错误污染领域层。

### 4.6 运行时数据

以下数据只存在于 HTTP 进程内：

- request ID。
- runtime ready flag。
- 并发计数或 semaphore。
- 配置的 allowed origins。
- 已屏蔽的 token 配置引用。

第二阶段不新增 QARun、HTTPRequestLog 或审计数据库。访问日志默认不写入 Neo4j，也不与来源事实、语义证据或 RecognitionRun 混合。

## 5. API 设计

### 5.1 通用约定

- API 前缀：`/api/v1`。
- 内容类型：`application/json`。
- 字符编码：UTF-8。
- 契约版本：`drawing-qa-http-v1`。
- 所有业务接口默认只读。
- 所有响应返回 `X-Request-ID`。
- 所有业务响应设置 `Cache-Control: no-store` 和 `X-Content-Type-Options: nosniff`。
- 不使用 cookie 或服务端 session；可选认证使用 `Authorization: Bearer <token>`。

### 5.2 `POST /api/v1/drawing-qa/ask`

用途：通用权威问答入口。

请求：`HttpQARequest`。

处理：

```text
validate HTTP model
  -> convert to QARequest(format_hint="json")
  -> DrawingGraphQAService.ask()
  -> map QAAnswer or QAError
  -> serialize envelope
```

支持的 question type 与 scope：

| question type | 最小 scope |
|---|---|
| `page_summary` | `page_id` |
| `block_relations` | `block_id` |
| `candidate_relations` | `page_id` 或 `block_id` |
| `section_matches` | `cross_section_id` 或 `page_id` |
| `table_caption_status` | `page_id`、`table_id` 或 `table_caption_id` |
| `diagnostic_status` | `page_id` 或 `block_id` |

### 5.3 便捷 GET 路由

| 路径 | 必需参数 | 可选参数 | 构造的 QARequest |
|---|---|---|---|
| `/api/v1/drawing-qa/pages/{page_id}/summary` | path `page_id` | `include_semantics` | `page_summary` |
| `/api/v1/drawing-qa/blocks/{block_id}/relations` | path `block_id` | `include_candidates` | `block_relations` |
| `/api/v1/drawing-qa/candidates` | query `page_id` 或 `block_id` | 两者可同时提供 | `candidate_relations` |
| `/api/v1/drawing-qa/section-matches` | query `cross_section_id` 或 `page_id` | 两者可同时提供 | `section_matches` |
| `/api/v1/drawing-qa/table-captions/status` | query `page_id`、`table_id` 或 `table_caption_id` | 可组合 | `table_caption_status` |
| `/api/v1/drawing-qa/diagnostics` | query `page_id` 或 `block_id` | `include_semantics`、`include_candidates` | `diagnostic_status` |

便捷 GET 路由规则：

- 只负责构造 `QARequest` 并调用统一 handler。
- 不复制 QAService 的 fact 聚合、warning 或 unsupported 逻辑。
- 不提供 `write_back` 参数。
- `include_payload` 仅在通用 POST 中可设置，便捷 GET 固定为 `false`。

### 5.4 健康接口

`GET /health/live`：

- 不依赖 QA runtime。
- 返回 `status="live"`、service name 和 contract version。
- 不返回环境变量、host、Neo4j URI、用户、图谱计数或数据路径。
- 无需 Bearer token。

`GET /health/ready`：

- 检查 runtime 是否已装配且未关闭。
- ready 时返回 `status="ready"` 和 `neo4j_status="not_checked"`。
- runtime 不存在或正在关闭时返回 503。
- 配置 API token 时，该 endpoint 需要认证；未配置 token 且仅 loopback 时允许本机访问。
- 不直接执行 Cypher，不直接创建 Neo4j session，不声称 live Neo4j 已通过。

### 5.5 QAAnswer 到 HTTP 的映射

| QAAnswerStatus | HTTP 状态 | envelope | 说明 |
|---|---:|---|---|
| `answered` | 200 | success | 完整回答 |
| `partial` | 200 | success | 保留 facts、warnings、unsupported parts |
| `not_found` | 404 | error | category=`NOT_FOUND`，details 仅保留安全 scope 和 source calls |
| `unsupported` | 422 | error | category=`UNSUPPORTED_QUESTION` |
| `failed` | 500 | error | category=`INTERNAL_ERROR`，消息脱敏 |

把 `not_found`/`unsupported` 转为错误 envelope 的原因：HTTP 客户端可以依据状态码统一处理失败，而 `answered`/`partial` 始终具有稳定 success data。错误 details 可以保留 question type、非敏感 scope 字段名和 source calls，但不回显完整原始请求。

### 5.6 QAError 到 HTTP 的映射

| QAErrorCode | HTTP 状态 | retryable |
|---|---:|---|
| `INVALID_ARGUMENT` | 422 | false |
| `UNSUPPORTED_QUESTION` | 422 | false |
| `UNSUPPORTED_SCOPE` | 422 | false |
| `NOT_FOUND` | 404 | false |
| `PARTIAL_ANSWER` | 422 | false |
| `WRITE_BACK_FORBIDDEN` | 403 | false |
| `FACADE_UNAVAILABLE` | 503 | true |
| `NEO4J_UNAVAILABLE` | 503 | true |
| `SEMANTIC_EVIDENCE_UNAVAILABLE` | 503 | true |
| `INTERNAL_ERROR` | 500 | false |

`PARTIAL_ANSWER` 异常与 `QAAnswerStatus.PARTIAL` 不同：前者没有可返回的结构化 answer，因此作为错误；后者包含可用事实，因此为 HTTP 200。

### 5.7 请求校验错误

FastAPI/Pydantic 校验错误统一转换为：

- HTTP 422。
- category=`INVALID_ARGUMENT`。
- message 为固定短语，不回显完整请求值。
- details 只包含安全字段路径和错误类型。
- 不使用 FastAPI 默认的完整 validation body 直接返回客户端。

### 5.8 启动入口

建议命令语义：

```text
python scripts/serve_drawing_graph_qa.py
```

配置全部来自环境变量。脚本不接受 password、token 或 API key 命令行参数。启动成功后输出 host、port、contract version、docs 是否启用和认证是否启用，但不输出 token、Neo4j password、完整 URI query 或其他 secret。

## 6. 异常处理

### 6.1 异常层次

```text
HTTP validation / auth / middleware error
  -> HTTP adapter error envelope

QAError
  -> QAErrorCode to HTTP mapping

ToolModelError
  -> 由 DrawingGraphQAService 转为 QAError 或降级为 QAAnswer warning

Neo4j / repository / semantic lower-level error
  -> facade / QAService 分类
  -> HTTP adapter 只处理 QAError

unknown exception
  -> server log with request ID
  -> sanitized HTTP 500
```

HTTP 层不捕获并重新分类 repository 细节，也不从异常文本猜测候选关系或事实状态。

### 6.2 初始化异常

| 阶段 | 行为 |
|---|---|
| 配置读取失败 | 启动脚本输出脱敏配置错误并返回非零退出码 |
| driver 创建失败 | runtime 创建失败，应用不进入 ready |
| facade 创建失败 | 关闭已创建 driver，应用启动失败 |
| QAService 创建失败 | 关闭已创建 driver，应用启动失败 |
| shutdown close 失败 | 服务端记录脱敏错误，ready=false，不向客户端暴露堆栈 |

不提供“没有 facade 但仍启动业务路由”的降级模式。health/live 可用与否由 ASGI server 启动状态决定；runtime startup 失败时整个应用启动失败，避免误导客户端。

### 6.3 请求异常

| 场景 | HTTP 状态 | category |
|---|---:|---|
| JSON 格式错误或字段类型错误 | 422 | `INVALID_ARGUMENT` |
| 请求体超过上限 | 413 | `REQUEST_TOO_LARGE` |
| 缺少/错误 Bearer token | 401 | `AUTHENTICATION_REQUIRED` / `AUTHENTICATION_FAILED` |
| 并发上限已满 | 429 | `TOO_MANY_REQUESTS` |
| 请求等待超时 | 504 | `REQUEST_TIMEOUT` |
| route 不存在 | 404 | `ROUTE_NOT_FOUND` |
| HTTP method 不允许 | 405 | `METHOD_NOT_ALLOWED` |
| QA scope 不合法 | 422 | `INVALID_ARGUMENT` / `UNSUPPORTED_SCOPE` |
| 请求 write-back | 403 | `WRITE_BACK_FORBIDDEN` |
| 请求对象不存在 | 404 | `NOT_FOUND` |
| Neo4j/facade 暂不可用 | 503 | `NEO4J_UNAVAILABLE` / `FACADE_UNAVAILABLE` |
| 未分类异常 | 500 | `HTTP_INTERNAL_ERROR` |

### 6.4 降级规则

- QAService 已经把可选语义证据或候选查询失败降级为 `partial` 时，HTTP 层不得重新升级为 503。
- `partial` 的 facts、warnings、unsupported parts 必须完整返回。
- 候选为空不是服务错误；以 QAService 返回的 answered/not_found 语义为准。
- table caption 当前能力不足时，继续返回 `partial` 和 unsupported parts，不让 HTTP 层直接查 repository。
- section match 多候选、歧义或证据不足时保留 candidate/ambiguous 状态，不补猜正式关系。

### 6.5 日志与客户端错误分离

服务端日志：

- 记录 request ID、route、method、HTTP status、duration、error category。
- 可记录异常类型名，但不记录完整 request/answer 和 secret。
- 低层 traceback 只允许进入受控服务端日志，且先进行敏感值过滤。

客户端响应：

- 只返回脱敏短消息、retryable 和安全 details。
- 不返回 traceback、Neo4j URI、用户、密码、Cypher、driver/session/transaction、repository 类名或真实数据路径。

### 6.6 超时限制

第二阶段请求超时是 HTTP 等待边界，不是 Neo4j 硬取消：

- 超时后客户端收到 504。
- 已在线程池执行的同步调用可能继续完成，其结果被丢弃。
- 并发 semaphore 只有在该调用真正结束后释放，防止超时请求不断绕过上限。
- 若后续需要数据库级硬取消，应在 `QueryService`/transaction 层单独设计，不在本阶段顺带重构。

## 7. 安全方案

### 7.1 默认只读

- 所有便捷 GET route 不提供 `write_back` 参数。
- 通用 POST 的 `write_back=true` 由 QAService 在调用 facade 前拒绝。
- HTTP adapter 不调用 `recognize_page_semantics(write_back=true)`。
- HTTP adapter 不调用 `match_section_caption(write_back=true)`。
- HTTP adapter 不调用 `review_candidate_relation(write_back=true)`。
- HTTP adapter 不触发导入、离线增强、候选审核状态写回或正式关系提升。

### 7.2 依赖边界

允许：

```text
HTTP adapter -> DrawingGraphQAService.ask()
runtime -> create_neo4j_tool_facade(driver)
```

禁止：

```text
HTTP route -> DrawingGraphToolFacade individual methods
HTTP route -> QueryService
HTTP route -> RelationRepository
HTTP route -> Neo4j session / transaction / Cypher
HTTP route -> import / enrichment / review CLI
```

通过静态测试检查 `qa_http.py` 不导入禁止模块和敏感低层类型。

### 7.3 网络边界

- 默认监听 `127.0.0.1`。
- `localhost`、`::1` 视为 loopback；其他地址视为远程绑定。
- 远程绑定必须显式 `allow_remote=true`、配置强 API token，并由外部反向代理提供 TLS。
- 第二阶段不声称静态 token 等同于生产级身份系统。
- Uvicorn 固定单 worker，不默认绑定 `0.0.0.0`。

### 7.4 认证

- 使用标准 `Authorization: Bearer <token>`。
- token 使用恒定时间比较。
- token 不进入 URL、query string、请求 DTO、响应、异常消息或访问日志。
- 未配置 token 且仅 loopback 时允许本机访问。
- 配置 token 后，所有业务 route 和 `/health/ready` 需要认证；`/health/live` 保持最小匿名存活检查。
- 认证失败统一返回固定消息，不说明 token 长度、前缀或匹配位置。

### 7.5 CORS

- 默认不安装 CORS middleware。
- 只有 `allowed_origins` 非空时启用。
- 不允许 `*`。
- 只允许 GET、POST、OPTIONS。
- 只允许 `Authorization`、`Content-Type` 等必要 header。
- 不使用 cookie credential；`allow_credentials=false`。

### 7.6 输入安全

- Pydantic model 拒绝 extra fields。
- 对业务 ID、language 和 enum 设置长度/值约束。
- 请求体由 ASGI middleware 按实际接收字节计数，不能只依赖 `Content-Length`。
- 超限立即返回 413，不把完整 body 写入日志。
- 不接受文件上传、图片上传、URL 抓取、multipart、表单或任意 JSON payload endpoint。
- `include_payload=true` 只允许返回 QAService 已经包含在 `QAAnswer` 中的 payload，不提供按引用任意读取的新 route。

### 7.7 输出安全

- 所有输出先经过共享 serializer 和响应模型验证。
- `Cache-Control: no-store` 防止中间缓存图纸证据。
- `X-Content-Type-Options: nosniff` 防止内容类型猜测。
- JSON 响应不包含 HTML，不渲染用户输入。
- request ID 由服务端生成，不直接信任客户端传入值。
- OpenAPI/docs 默认关闭；只允许 loopback 显式开启。

### 7.8 敏感配置

- Neo4j password 和 API token 使用 dataclass `repr=False` 或等价遮蔽。
- 不把 secret 写入代码、文档、测试 fixture、`.env.example` 的真实值或异常消息。
- 启动脚本不接受 secret 命令行参数。
- HTTP request body 不允许覆盖服务器端配置。
- `ToolFacadeConfig` 继续拒绝 Neo4j 和供应商 secret，不因 HTTP 接入改变。

### 7.9 事实分层安全

| fact kind | HTTP 表述 |
|---|---|
| `source_fact` | 来源标注或导入可确定事实 |
| `derived_relation` | 离线规则生成的正式派生关系 |
| `semantic_observation` | 模型/OCR 类观察证据，不覆盖来源事实 |
| `semantic_interpretation` | 结构化解释，不等于来源字段 |
| `candidate_relation` | 候选关系，不能写成已确认 |
| `formal_relation` | 已满足正式关系规则的关系 |

`matched_candidate` 继续保持候选语义。`BlockInterpretation.interpreted_type` 不写入或表述为 `DrawingBlock.block_type`。

### 7.10 验证状态安全

- 单元测试通过只证明 fake/in-memory 和 HTTP 合同通过。
- TestClient 测试不等于真实 socket/Uvicorn smoke test。
- `/health/live` 和 `/health/ready` 不等于 live Neo4j 验证。
- 只有实际配置 disposable Neo4j 并运行集成测试后，才能报告 live Neo4j 通过。
- 集成测试跳过必须报告为“live Neo4j 未验证”。

## 8. 测试设计

### 8.1 单元测试

按模块独立验证：

- serialization：领域 DTO 到 JSON、MappingProxyType、Enum、Path、候选事实不变、脱敏。
- HTTP models：extra forbid、scope、六类 question type、unknown 不开放、write-back true 可被 service 拒绝。
- runtime：创建顺序、依赖注入、部分失败清理、幂等 close。
- app：import 无副作用、lifespan、route 映射、状态码、request ID、headers、health。
- security：token、remote config、CORS allowlist、body size、日志不含 secret。
- compatibility：QA CLI JSON 和退出码不变。

### 8.2 HTTP 合约测试

使用 fake QAService 覆盖：

- 六类 question type。
- answered、partial、not_found、unsupported、failed。
- QAError 全部错误码。
- validation、auth、413、429、504、404 route、405 method。
- success/error envelope 和 contract version。
- candidate/formal、observation/source fact 分层。

### 8.3 生命周期测试

- import `qa_http.py` 不调用 config loader、driver factory 或 runtime factory。
- TestClient 进入 lifespan 后 runtime 创建一次。
- 多个请求复用同一 QAService。
- TestClient 退出时 close 一次。
- facade/service 初始化失败时已创建 driver 被关闭。
- close 自身异常不把 secret 返回客户端。

### 8.4 本机 smoke test

实现后启动单 worker Uvicorn，验证：

- `/health/live`。
- `/health/ready` 返回 `neo4j_status=not_checked`。
- 一个受控 QA 请求。
- Bearer token 开关。
- Ctrl+C/正常关闭后 driver 释放。

如果没有可用 Neo4j，smoke test 只能使用 fake runtime 或确认服务启动失败边界，不能声称 live 图谱查询通过。

### 8.5 全量回归

实施任务最终运行：

```text
python -m unittest discover tests -v
```

如配置 disposable Neo4j，再运行：

```text
python -m unittest discover tests.integration -v
```

测试报告必须分别记录：单元测试、HTTP smoke test、集成测试和 live Neo4j 状态。

## 9. 设计取舍与非重构声明

### 9.1 采用的方案

```text
FastAPI application factory
  + lifespan runtime
  + synchronous read-only QA routes
  + shared serialization/sanitization
  + dedicated HTTP models
```

选择原因：

- 复用第一阶段 QAService 和 facade。
- HTTP/Pydantic 不进入领域层。
- driver 生命周期集中且可测试。
- CLI 与 HTTP JSON 语义一致。
- 可为后续 Ava/MCP adapter 提供稳定合同，但不提前实现它们。

### 9.2 明确不做的重构

- 不把所有 config 重构成新的配置框架。
- 不把同步 Neo4j/query service 重写为异步实现。
- 不拆分或重写 `DrawingGraphQAService` 的六类 handler。
- 不把 dataclass QA DTO 全部替换为 Pydantic。
- 不改变 `DrawingGraphToolFacade` 方法集。
- 不重命名现有导入、增强或候选复核模块。
- 不新增 repository 抽象来服务 HTTP。
- 不修改 Schema 或迁移已有数据。
- 不建设通用 Web 平台、插件系统或任务调度系统。

### 9.3 允许的最小兼容修改

- 把 CLI 私有序列化和脱敏移动到共享模块。
- 为 HTTP 新增独立配置，不改变 ImportConfig 现有调用。
- 更新文档中“HTTP 未实现”的过期描述。
- 若 TestClient/框架版本要求微调响应模型，只在 HTTP 模块内处理，不改变 QA 领域契约。

## 10. 第二阶段完成标准

设计落地后应满足：

1. HTTP 应用 import 无副作用。
2. 版本化通用 POST 和六个便捷 GET route 可通过 fake QAService 测试。
3. 所有业务 route 只调用 `DrawingGraphQAService.ask()`。
4. runtime 通过 `create_neo4j_tool_facade(driver)` 装配 facade，并可靠关闭 driver。
5. CLI 与 HTTP 共用序列化和脱敏，CLI 行为兼容。
6. HTTP request model 拒绝未知和敏感字段。
7. `write_back=true` 返回 403，且不调用 facade。
8. partial 为 200；not found、unsupported、依赖不可用和内部错误按设计映射。
9. 候选关系、语义证据和正式关系保持分层。
10. 默认监听 `127.0.0.1`，默认关闭 CORS 和 OpenAPI docs。
11. 非 loopback 配置缺少显式远程授权或 token 时启动失败。
12. `/health/ready` 不声称 live Neo4j 已验证。
13. 第一阶段 QA/CLI 测试保持通过。
14. 根文档同步 HTTP 当前实现，MCP、Ava 专有 adapter、OCR、全量扫描和写回 HTTP 仍标为未实现。
15. live Neo4j 只有在 disposable 集成测试实际运行后才报告为通过；跳过时明确未验证。

本设计确认后，下一步再把实现拆分为可独立验证的 `tasks.md`；在用户确认设计前不进入代码实现。

## 11. 外部技术依据

- [FastAPI Lifespan Events](https://fastapi.tiangolo.com/advanced/events/)：应用级共享资源应在 lifespan 中创建和清理。
- [FastAPI Concurrency and async/await](https://fastapi.tiangolo.com/async/)：普通同步 path operation 会在线程池中执行，适配当前同步 QAService 和 Neo4j driver。
- [FastAPI Handling Errors](https://fastapi.tiangolo.com/tutorial/handling-errors/)：支持统一异常处理和自定义错误响应。
- [Pydantic Model Config](https://docs.pydantic.dev/latest/api/config/)：HTTP request model 可通过受控配置拒绝未知字段。
