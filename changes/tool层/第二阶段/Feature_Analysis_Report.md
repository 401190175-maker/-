# Tool 层第二阶段功能分析报告

## 0. 分析范围与结论

本报告依据以下当前文件分析 Tool 层第二阶段需求：

- `changes/tool层/第一阶段/Feature_Analysis_Report.md`
- `changes/tool层/第一阶段/design.md`
- `changes/tool层/第一阶段/proposal.md`
- `changes/tool层/第一阶段/tasks.md`
- `architecture.md`
- `Module.md`
- `README.md`
- 当前 `qa_models.py`、`qa_service.py`、`qa_rendering.py`、`tool_factory.py`、`config.py`、`scripts/drawing_graph_qa.py` 及相关测试

需求中写作 `feature_analysis_report.md` 和 `task.md`，第一阶段目录中的实际文件名分别为 `Feature_Analysis_Report.md` 和 `tasks.md`，本报告按实际文件读取。

第一阶段文档已经把第二阶段定义为：在现有 `DrawingGraphQAService` 之上增加 HTTP API，供 Ava、网页或其他本地软件调用。因此，本报告按“只读 HTTP API 阶段”分析，不把 MCP Tool adapter、Ava 专有协议、OCR、真实云模型接入、全量语义扫描或写回型 HTTP 接口纳入第二阶段。

结论如下：

1. **当前架构支持第二阶段，且支持度较高。** 第一阶段已经建立 `QA adapter -> DrawingGraphQAService -> DrawingGraphToolFacade -> ports/services -> repository/Neo4j` 的依赖方向，HTTP 只需作为新的同级 adapter 接入。
2. **不需要修改 Neo4j Schema，也不需要重写 QAService 或 Tool facade。** 当前 `QARequest`、`QAAnswer`、错误分类和六类问题编排已经具备稳定的 HTTP 输入/输出基础。
3. **不能只加几个路由就算完成。** 当前 DTO 序列化、错误脱敏和运行时资源生命周期仍封装在 CLI 私有函数中；HTTP 阶段需要把这些能力抽成可复用模块，并建立应用启动/关闭、访问控制、超时、并发和测试边界。
4. **推荐使用 FastAPI + Uvicorn 的应用工厂方案。** 路由函数保持同步 `def`，复用当前同步 Neo4j driver 和同步 QAService；driver、facade、QAService 在应用 lifespan 中创建一次并在关闭时释放。
5. **第二阶段默认仍然只读。** HTTP 请求不得接收 Neo4j 密码、供应商密钥、Cypher 或 repository 参数；`write_back=true` 必须拒绝；候选关系、语义观察和正式关系继续分层返回。
6. **默认只监听 `127.0.0.1`。** 未配置认证、TLS、反向代理和明确来源白名单前，不应绑定公网或局域网地址。

推荐目标架构：

```text
Ava / local web client / local application
  -> HTTP API adapter
      -> request validation / access control / error mapping / JSON serialization
      -> DrawingGraphQAService
          -> DrawingGraphToolFacade
              -> read ports / semantic services / candidate and section services
                  -> controlled repository / Neo4j
```

## 1. 当前架构是否支持

### 1.1 已具备的支撑能力

| 当前能力 | 支持第二阶段的原因 | 当前状态 |
|---|---|---|
| `DrawingGraphQAService.ask()` | HTTP 层可以把请求转换为 `QARequest`，无需重新编排 page/block/candidate/section/table/diagnostic 逻辑 | 已实现 |
| `QARequest` / `QAScope` | 已定义稳定问题类型、范围 ID、include 选项、语言和 `write_back` | 已实现 |
| `QAAnswer` / `AnswerFact` / `EvidenceRef` | 已提供结构化输出，可直接映射为 JSON；事实层级不会因换成 HTTP 而丢失 | 已实现 |
| `QAErrorCode` | 已有参数、scope、not found、write-back、Neo4j 和内部错误分类，可映射为 HTTP 状态码 | 已实现 |
| `DrawingGraphToolFacade` | 统一封装来源事实、派生关系、语义证据、候选关系和断面匹配 | 已实现 |
| `create_neo4j_tool_facade(driver)` | HTTP 应用可在启动时用外部 driver 装配 facade，不需要直接操作 repository | 已实现 |
| QA CLI | 已验证参数映射、driver 关闭、JSON 输出和错误脱敏，可作为 HTTP adapter 的行为参考 | 已实现 |
| fake facade / 单元测试 | HTTP 测试可以注入 fake QAService，不依赖真实 Neo4j | 已实现基础 |

### 1.2 当前缺口

| 缺口 | 具体表现 | 第二阶段影响 |
|---|---|---|
| 没有 HTTP 框架依赖 | `requirements.txt` 当前只有 Neo4j driver | 需要新增 HTTP 运行与测试依赖 |
| 没有应用工厂 | 当前没有可注入 QAService 的 `create_app()` | 难以隔离配置、测试和运行时资源 |
| 生命周期只存在于 CLI | CLI 每次命令创建并关闭 driver；HTTP 是长生命周期进程 | 必须在 startup/shutdown 或 lifespan 中统一管理 |
| 序列化是 CLI 私有实现 | `_jsonable()` 位于 `scripts/drawing_graph_qa.py` | HTTP 若复制会产生两套输出契约 |
| 脱敏是 CLI 私有实现 | `_sanitize_message()` 位于 CLI 脚本 | HTTP 错误容易泄露 driver、密码或底层异常 |
| 没有 HTTP 配置契约 | 缺少 host、port、origin、token、请求限制等配置 | 无法安全区分本机与网络部署 |
| 没有 HTTP 状态映射 | `QAAnswerStatus`、`QAErrorCode` 尚未映射到 HTTP | 客户端处理会不稳定 |
| 没有并发与超时约束 | 当前测试主要是单调用 | HTTP 场景可能放大同步阻塞和内存状态问题 |
| 没有健康检查语义 | 不能区分“进程存活”“运行时已装配”“live Neo4j 已验证” | 容易产生错误健康声明 |

### 1.3 架构判断

当前架构在业务边界上已经支持 HTTP，但在运行时和协议边界上尚未支持。也就是说：

- `DrawingGraphQAService` 已经解决“问什么、调用哪些 facade、如何聚合证据”。
- 第二阶段需要解决“如何安全接收 HTTP 请求、如何管理长生命周期资源、如何稳定返回 JSON”。
- HTTP adapter 不得重新实现 `_answer_page_summary()`、`_answer_block_relations()` 等问答逻辑。
- 若 HTTP 层发现 QA 能力缺口，应扩展窄口径 facade/QA 接口或返回 `partial` / `unsupported`，不能直接写 Cypher。

## 2. 需要新增的模块

### 2.1 必需模块

| 建议模块 | 职责 | 设计边界 |
|---|---|---|
| `src/drawing_graph/qa_serialization.py` | 把 dataclass、Enum、tuple、Path、只读 mapping 转为 JSON-compatible 数据；提供统一成功/错误 envelope | 不调用 facade，不读取环境变量，不做 HTTP 路由 |
| `src/drawing_graph/qa_http_models.py` | 定义 HTTP 请求/响应模型、字段校验、extra field 拒绝和 `write_back=false` 约束 | HTTP DTO 只负责协议，不替代领域 `QARequest` / `QAAnswer` |
| `src/drawing_graph/qa_http.py` | 提供 `create_app()`，注册路由、异常处理器、request ID、访问控制和 lifespan | 只调用注入的 QAService，不直接访问 Neo4j、Cypher 或 repository |
| `src/drawing_graph/qa_http_runtime.py` | 从受控配置创建 driver、facade、QAService，并负责关闭资源 | driver 只在 adapter/runtime 最外层可见 |
| `scripts/serve_drawing_graph_qa.py` | HTTP 服务启动入口，读取配置并启动 ASGI server | 不注册业务规则，不包含 QA 聚合逻辑 |
| `tests/test_qa_serialization.py` | 验证 CLI 与 HTTP 使用同一 JSON 语义 | 不连接真实 Neo4j |
| `tests/test_qa_http.py` | 覆盖路由、校验、状态码、脱敏、只读、注入和响应分层 | 使用 fake QAService / fake runtime |
| `tests/test_qa_http_runtime.py` | 覆盖 driver/facade/QAService 创建与关闭，初始化失败时释放资源 | 使用 fake driver，不使用真实密码 |

`qa_http_runtime.py` 可以在实现时并入 `qa_http.py`，但只有在文件仍保持职责清晰时才建议合并。若路由、配置、生命周期、错误处理全部堆入同一文件，后续 Ava 或 MCP adapter 会再次复制运行时逻辑。

### 2.2 配置模块

建议在 `config.py` 中新增窄口径 `QAHttpConfig`，至少包含：

| 配置 | 推荐默认值或规则 |
|---|---|
| Neo4j URI / user / password | 只从环境变量读取，password 在 `repr` 中屏蔽 |
| host | 默认 `127.0.0.1` |
| port | 明确正整数范围，避免与 Neo4j Browser/Bolt 端口混淆 |
| allowed origins | 默认空，不自动开启 CORS |
| API token | 本机单用户阶段可选；绑定非 loopback 地址时必须显式配置认证方案 |
| request body limit | 设置合理上限，拒绝大请求 |
| request timeout | 设置查询超时或服务级超时策略 |
| docs enabled | 开发环境可开启；受控部署可关闭或限制访问 |

不建议让 HTTP 服务直接复用 `ImportConfig.from_env()`。`ImportConfig` 还要求数据根目录、项目 slug、批量大小等导入配置，而只读 HTTP QA 服务不应被无关导入参数阻断。第二阶段可以新增独立 `QAHttpConfig`，共享已有私有校验函数；不要为了抽取三个 Neo4j 字段而大范围重构所有导入配置。

### 2.3 最小 HTTP 接口

建议使用版本化前缀 `/api/v1`，避免后续 Ava 合同变化时破坏已有客户端。

| 方法 | 路径 | 作用 |
|---|---|---|
| `POST` | `/api/v1/drawing-qa/ask` | 通用入口，接收受控 question type 和 scope |
| `GET` | `/api/v1/drawing-qa/pages/{page_id}/summary` | `page_summary` 便捷入口 |
| `GET` | `/api/v1/drawing-qa/blocks/{block_id}/relations` | `block_relations` 便捷入口 |
| `GET` | `/api/v1/drawing-qa/candidates` | `candidate_relations`，要求 page ID 或 block ID |
| `GET` | `/api/v1/drawing-qa/section-matches` | `section_matches`，要求 cross-section ID 或 page ID |
| `GET` | `/api/v1/drawing-qa/table-captions/status` | `table_caption_status` |
| `GET` | `/api/v1/drawing-qa/diagnostics` | `diagnostic_status` |
| `GET` | `/health/live` | 仅表示 HTTP 进程存活 |
| `GET` | `/health/ready` | 表示应用运行时已装配；不能在未查询 live Neo4j 时声称数据库已验证 |

通用 `POST /ask` 是权威接口，GET 路由只是稳定、易用的请求映射。两者最终都必须构造同一 `QARequest` 并调用 `DrawingGraphQAService.ask()`。

### 2.4 响应与错误契约

成功响应建议保留 CLI 已有 envelope 方向：

```text
status: ok
data: QAAnswer 的 JSON-compatible 表示
meta: request_id / contract_version
```

错误响应建议统一为：

```text
status: failed
error: category / message / retryable
meta: request_id / contract_version
```

推荐状态码映射：

| QA 结果或错误 | HTTP 状态码 | 说明 |
|---|---:|---|
| `answered` / `partial` | 200 | `partial` 仍返回可用事实，缺口保留在 answer 中 |
| `INVALID_ARGUMENT` / `UNSUPPORTED_SCOPE` | 422 | 请求结构合法但业务参数不可处理 |
| `WRITE_BACK_FORBIDDEN` | 403 | 当前 HTTP API 明确只读 |
| `NOT_FOUND` | 404 | 请求对象不存在 |
| `UNSUPPORTED_QUESTION` | 422 | 不把尚未实现的问题伪装成服务器错误 |
| `NEO4J_UNAVAILABLE` / `FACADE_UNAVAILABLE` | 503 | 临时依赖不可用，可按 `retryable` 决定重试 |
| `INTERNAL_ERROR` | 500 | 返回脱敏消息和 request ID，不返回堆栈 |

## 3. 影响哪些已有模块

### 3.1 直接修改

| 已有模块 | 影响 | 原因 |
|---|---|---|
| `requirements.txt` | 中 | 增加 FastAPI、ASGI server 和 HTTP 测试客户端依赖 |
| `src/drawing_graph/config.py` | 中 | 新增 HTTP 专用配置与脱敏校验 |
| `scripts/drawing_graph_qa.py` | 低 | 改用共享序列化和脱敏函数，CLI 行为保持兼容 |
| `README.md` | 中 | 增加启动、接口、默认本机监听和只读边界说明；删除“HTTP 未实现”的过期现状描述 |
| `Module.md` | 中 | 记录 HTTP 模块职责、接口、依赖和当前能力 |
| `architecture.md` | 中 | 将 HTTP adapter 加入已实现调用链，同时保留 MCP/Ava 专有集成未实现边界 |
| `tests/test_qa_docs.py` | 中 | 原测试保护“HTTP 未完成”描述；第二阶段实现后需改为保护 HTTP 的真实边界 |

### 3.2 间接依赖但原则上不修改

| 模块 | 影响 | 原则 |
|---|---|---|
| `qa_models.py` | 被 HTTP request/response 映射使用 | 不让 Pydantic/HTTP 细节进入领域 DTO |
| `qa_service.py` | 被 HTTP 调用 | 不加入 request、response、header、status code 或 driver 逻辑 |
| `qa_rendering.py` | 基本不受影响 | HTTP 权威输出为 JSON，不默认返回 `zh-brief` 文本 |
| `tool_facade.py` | 被 QAService 间接调用 | 不为 HTTP 暴露额外写回入口，不直接增加 Web 语义 |
| `tool_factory.py` | 被 runtime 使用 | 当前工厂已满足装配；除非需要可测试的依赖注入，否则不改 |
| `query_service.py` | 无直接影响 | HTTP 层不得绕过 facade 调用它 |
| `relation_repository.py` | 无直接影响 | HTTP 层不得直接读写 repository |
| `scripts/create_schema.cypher` | 无影响 | 第二阶段不新增图谱数据类型或索引 |

### 3.3 现有测试影响

第一阶段 QA 模型、服务、渲染和 CLI 测试应保持通过。HTTP 阶段新增测试至少覆盖：

- 应用 import 不创建 driver、不连接 Neo4j。
- `create_app()` 可以注入 fake QAService。
- lifespan 只创建一次 runtime，关闭时只关闭一次 driver。
- 每条路由正确构造 `QuestionType` 和 `QAScope`。
- `write_back=true`、未知字段、非法 scope、敏感字段进入请求体时被拒绝。
- `candidate_relation` 不会序列化成 `formal_relation`。
- `partial` 保留 facts、warnings 和 unsupported parts。
- 所有错误消息脱敏，不包含 password、secret、token、Cypher、driver/session/transaction 细节。
- 默认 CORS 不开放，默认 host 为 loopback。
- 健康检查不把“进程已启动”写成“live Neo4j 已验证”。
- 如果真实 Neo4j 集成测试未运行，报告为未验证，不写成通过。

## 4. 技术方案

### 4.1 方案 A：FastAPI + Uvicorn + 应用工厂（推荐）

结构：

```text
serve_drawing_graph_qa.py
  -> create_app(runtime_factory=...)
      -> FastAPI lifespan
          -> driver -> facade -> QAService
      -> versioned routes
          -> QARequest -> QAService.ask() -> QAAnswer -> shared serializer
```

要点：

- 使用 `create_app()`，避免 import 时连接 Neo4j，便于注入 fake service。
- 使用 FastAPI lifespan 在服务启动前创建共享资源，在关闭后释放 driver。FastAPI 官方文档也把 lifespan 作为 startup/shutdown 资源管理的推荐方式。
- 路由使用同步 `def`，因为当前 QAService 和 Neo4j driver 是同步调用；FastAPI 会把同步 path operation 放到线程池，避免直接阻塞事件循环。
- 第一版使用单进程、受控并发；在内存 run log、payload store、cache 尚未替换为跨进程存储前，不建议直接开启多个 worker。
- 使用 TestClient/HTTPX 做无真实 socket 的 HTTP 测试，并继续用项目现有 `unittest` 组织测试。

### 4.2 方案 B：Flask + WSGI + 应用工厂

结构与方案 A 类似，但使用 Flask app factory、同步路由和 WSGI server。

适用情形：

- 团队明确偏好 WSGI/Flask。
- API 很小，不需要自动 OpenAPI、强类型请求模型或后续异步能力。
- 部署环境已有成熟 Flask 运维方案。

Flask 官方同样推荐应用工厂以支持测试和多实例配置，因此该方案在架构上可行，但项目当前没有 Flask 既有惯例，选择它主要是团队偏好，而不是代码库带来的优势。

### 4.3 方案 C：Python 标准库 `http.server` 自建

结构最少，但需要自行实现路由、JSON 校验、错误处理、请求大小限制、并发、生命周期和接口文档。

该方案只适合临时演示或一次性本机调试，不适合作为第二阶段正式 Tool 层接口。Python 官方安全说明明确指出 `http.server` 不适合生产使用，只提供基础安全检查。

### 4.4 方案 D：直接做 MCP 或 Ava 专有 adapter

该方案跳过通用 HTTP API，直接围绕外部 Agent 协议或 Ava SDK 建接口。

它不符合第一阶段文档对第二阶段的定义，也会过早绑定尚未确认的外部协议。若 Ava 最终只支持特定协议，可以在 HTTP API 稳定后新增一个同级 adapter；不能让 Ava adapter 直接访问 facade 或 Neo4j。

## 5. 优缺点比较

| 维度 | 方案 A：FastAPI | 方案 B：Flask | 方案 C：标准库 HTTP | 方案 D：MCP/Ava 专有 |
|---|---|---|---|---|
| 与当前类型化 DTO 的匹配 | 高 | 中 | 低 | 取决于协议 |
| 请求校验与 OpenAPI | 内建能力强 | 需要额外组织 | 基本自建 | 由外部协议决定 |
| 同步 QAService 兼容 | 高，使用同步路由 | 高 | 高 | 不确定 |
| 生命周期管理 | lifespan 清晰 | app factory + server hooks | 需自建 | 取决于 SDK |
| 测试注入 | 高 | 高 | 中 | 中 |
| 新依赖数量 | 中 | 中 | 低 | 可能高 |
| 安全默认值实现成本 | 中 | 中 | 高 | 中到高 |
| 后续网页/Ava 复用 | 高 | 高 | 低 | 低，容易锁定 |
| 后续异步/流式扩展 | 高 | 中 | 低 | 取决于协议 |
| 当前推荐度 | **最高** | 可选 | 不推荐 | 不属于本阶段 |

### 5.1 FastAPI 的主要优点

- 与当前 dataclass/Enum 驱动的稳定契约思路一致。
- 输入校验、OpenAPI、异常处理和测试客户端成熟，减少自建协议代码。
- lifespan 适合管理长生命周期 driver/facade/QAService。
- 同步路由可直接复用现有同步业务层，不需要为了“看起来异步”重写 Neo4j 访问。

### 5.2 FastAPI 的主要缺点

- 增加 FastAPI、Pydantic、Starlette、Uvicorn 和测试客户端依赖链，需要固定兼容范围并纳入依赖更新测试。
- 自动文档和详细校验错误如果直接暴露，可能泄露过多内部字段；需要统一错误 envelope 和部署配置。
- 多 worker 会复制内存 run log、payload store 和 cache；不能把进程内状态误认为全局一致。

### 5.3 Flask 的主要优缺点

- 优点：同步模型直观、生态成熟、应用工厂清晰。
- 缺点：当前项目没有 Flask 基础；请求模型、OpenAPI 和类型化响应需要更多自定义或额外扩展，最终代码量不一定比 FastAPI 少。

### 5.4 标准库方案的主要优缺点

- 优点：无第三方 HTTP 框架依赖，短期启动快。
- 缺点：安全、校验、路由、文档、测试和生命周期都要自行维护，第二阶段会把精力从图谱 QA 边界转移到低层 Web 基础设施。

## 6. 推荐方案

推荐采用“**FastAPI 应用工厂 + 同步只读路由 + 共享序列化/脱敏 + lifespan runtime**”。

### 6.1 推荐边界

第二阶段包含：

- 通用 `POST /api/v1/drawing-qa/ask` 和少量便捷 GET 路由。
- JSON request/response 契约和稳定 HTTP 错误映射。
- driver/facade/QAService 的启动、复用和关闭。
- 默认 loopback、默认无 CORS、默认只读。
- 可选静态 token 或等价本机访问控制，但不把 token 放入请求 DTO 或日志。
- 单元级 HTTP 测试、runtime 生命周期测试和文档边界测试。
- CLI 改用共享序列化/脱敏，保证 CLI 与 HTTP 输出语义一致。

第二阶段不包含：

- 不实现任意 Cypher HTTP 接口。
- 不实现导入、增强、候选复核写回或语义证据写回接口。
- 不开放 `write_back=true`。
- 不实现 MCP Tool adapter。
- 不实现 Ava 专有插件、SDK 或账号协议。
- 不接入真实云多模态供应商。
- 不实现 OCR、全量语义扫描、文件 watcher 或任务队列。
- 不新增 Neo4j Schema、业务节点或图谱关系。
- 不建设生产级用户体系、RBAC、计费或完整审计平台。

### 6.2 推荐实施顺序

1. 抽取共享 JSON 序列化、错误 envelope 和脱敏函数，保持 QA CLI 回归通过。
2. 新增 HTTP request/response 模型，明确字段白名单、scope 规则和 `write_back=false`。
3. 新增 `create_app()`，先以注入 fake QAService 完成路由与错误映射测试。
4. 新增 runtime factory 和 lifespan，装配 Neo4j driver、facade、QAService，并验证关闭行为。
5. 新增启动脚本和 `QAHttpConfig`，默认监听 `127.0.0.1`。
6. 增加访问控制、CORS allowlist、请求大小、超时和 request ID。
7. 更新 README、Module、architecture 和文档测试。
8. 运行 QA 专项测试与全量回归；live Neo4j 只在配置 disposable 测试库后单独验证。

### 6.3 关键设计决定

- **HTTP 模型与领域模型分离。** Pydantic 请求模型转换为 `QARequest`，`QAService` 不导入 FastAPI/Pydantic。
- **同步到底。** 第一版不把现有同步 QAService 包装成伪异步业务代码；同步 path operation 交由框架线程池执行。
- **单进程起步。** 当前 `InMemoryRecognitionRunLog`、`InMemorySemanticPayloadStore` 和部分缓存是进程内状态；多 worker 之前先明确哪些状态需要持久化或外置。
- **部分回答仍是成功响应。** `partial` 使用 HTTP 200，并通过 `warnings` / `unsupported_parts` 告诉客户端缺口。
- **健康检查分级。** `/health/live` 只检查进程，`/health/ready` 只说明 runtime 已构造；没有独立 facade 健康接口或 live 查询证据时，不声称 Neo4j 已通过。
- **本机优先。** Uvicorn 默认可使用 `127.0.0.1`；只有明确部署方案后才绑定 `0.0.0.0`。Uvicorn 官方设置文档也说明 `0.0.0.0` 会使服务可被本地网络访问。

## 7. 风险

### 7.1 高风险

| 风险 | 后果 | 缓解措施 |
|---|---|---|
| HTTP 层绕过 QAService/facade | 形成第二套查询与写回入口，破坏事实分层和安全边界 | 架构测试静态检查 HTTP 模块不导入 QueryService、Repository、Neo4j session/Cypher |
| 默认绑定非本机地址且无认证 | 图谱数据和内部 ID 可能被局域网或公网访问 | 默认 `127.0.0.1`；非 loopback 启动必须显式配置认证、来源策略和部署说明 |
| 错误消息泄露底层信息 | 泄露密码、URI、Cypher、driver 堆栈或数据路径 | 共享脱敏函数、统一异常处理器、服务端详细日志与客户端消息分离 |
| 无限制并发压垮 Neo4j | 大量同步查询占满线程池和连接池 | 单进程、并发上限、超时、连接池配置、请求速率限制和压测后再放宽 |
| 把候选或模型证据表述为正式事实 | 产生错误工程结论 | HTTP 响应完整保留 `fact_kind`、status、evidence；契约测试固定 candidate/formal 边界 |

### 7.2 中风险

| 风险 | 后果 | 缓解措施 |
|---|---|---|
| CLI 与 HTTP 各自序列化 | 字段、枚举、MappingProxyType 的输出不一致 | 先抽取 `qa_serialization.py`，两种 adapter 共用 |
| 多 worker 复制内存状态 | run log、payload、cache 在不同进程不一致 | 第二阶段默认单 worker；生产扩展前改为持久化/共享 store |
| 自动 OpenAPI 暴露不应出现的字段 | 客户端误以为支持 secret、Cypher、write-back | HTTP request model 采用明确字段白名单并拒绝 extra fields；按部署配置文档入口 |
| `ImportConfig` 被错误复用 | HTTP 启动被 data root/project slug 等无关配置阻断 | 新增 `QAHttpConfig`，不把导入配置当服务配置 |
| HTTP 状态码与 QA 状态冲突 | 客户端重复判断或误重试 | 固定映射表；`partial` 为 200，依赖不可用才是 503 |
| readiness 被解释成 live Neo4j 验证 | 运维和验收产生虚假结论 | 健康响应明确 scope；live Neo4j 单独用 disposable 集成测试验证 |

### 7.3 低到中风险

| 风险 | 后果 | 缓解措施 |
|---|---|---|
| API 路径过早冻结 | 后续 Ava 需求变化造成破坏性变更 | 使用 `/api/v1` 和 contract version；便捷路由保持薄映射 |
| 依赖版本漂移 | FastAPI/Pydantic/TestClient 兼容性变化 | 声明受控版本范围、锁定 CI 环境并保留 HTTP 合约测试 |
| 请求日志记录完整 payload | 暴露图纸 ID、路径、证据或未来敏感文本 | 默认只记录 request ID、路由、状态码、耗时；不记录完整 request/answer |
| CORS 配置过宽 | 浏览器跨源滥用本机 API | 默认关闭；只允许显式 origin 白名单，不使用凭据模式下的通配符 |
| 停机时资源未释放 | driver 连接泄漏、测试挂起 | lifespan `try/finally` 关闭 driver，覆盖启动失败和重复关闭测试 |

## 8. 验证与验收建议

第二阶段实现后，建议分三层报告验证状态：

1. **单元/HTTP 合约测试：** fake QAService 下验证路由、模型、状态码、序列化、脱敏和只读边界。
2. **本机服务 smoke test：** 启动 Uvicorn 后调用 `/health/live`、`/health/ready` 和一个 fake/受控请求；验证关闭后 driver 被释放。
3. **live Neo4j 集成测试：** 只有配置 `NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD` 并实际运行 disposable 数据库测试后才能声称通过。测试被跳过时必须写“live Neo4j 未验证”。

最低验收标准：

- HTTP 模块 import 无副作用，不创建 driver、不连接 Neo4j。
- 所有业务请求只调用 `DrawingGraphQAService.ask()`。
- 请求体不接受 Neo4j 凭据、供应商 key、token、Cypher、driver、session、transaction 或 repository 参数。
- `write_back=true` 被拒绝，HTTP API 不触发语义持久化、候选复核或正式关系提升。
- `candidate_relation`、`semantic_observation`、`semantic_interpretation` 和 `formal_relation` 在 JSON 中保持不同类型。
- 默认 host 为 `127.0.0.1`，默认不开放 CORS。
- CLI 与 HTTP 对同一 `QAAnswer` 生成一致的 JSON 数据结构。
- 全量单元测试保持通过；集成测试状态如实报告。

## 9. 外部技术依据

- [FastAPI Lifespan Events](https://fastapi.tiangolo.com/advanced/events/)：应用启动/关闭资源管理推荐使用 lifespan。
- [FastAPI Concurrency and async/await](https://fastapi.tiangolo.com/async/)：同步 path operation 会在线程池中执行，适合当前同步 QAService/Neo4j 调用边界。
- [FastAPI Testing](https://fastapi.tiangolo.com/tutorial/testing/)：可使用 TestClient/HTTPX 在不启动真实 socket 的情况下测试 API。
- [Uvicorn Settings](https://www.uvicorn.org/settings/)：说明 app factory、host、port、worker 等运行设置；`0.0.0.0` 会使服务对本地网络可用。
- [Flask Application Factories](https://flask.palletsprojects.com/en/stable/patterns/appfactories/)：方案 B 的应用工厂与测试隔离依据。
- [Python Security Considerations](https://docs.python.org/3/library/security_warnings.html)：标准库 `http.server` 不适合作为生产服务。

## 10. 最终推荐

当前架构支持 Tool 层第二阶段。推荐在不改变图谱 Schema、不重写 QAService、不开放写回的前提下，实现一个版本化、默认本机监听的 FastAPI HTTP adapter，并优先抽取 CLI 与 HTTP 共用的序列化、错误 envelope 和脱敏能力。

第二阶段真正的工程重点不是增加路由数量，而是守住四个边界：

1. HTTP 只做协议适配，业务编排仍在 `DrawingGraphQAService`。
2. 图谱能力仍只通过 `DrawingGraphToolFacade`。
3. 默认 `write_back=false`，候选和正式事实严格分层。
4. 长生命周期服务必须明确资源释放、访问控制、并发限制和验证状态。

在这些边界下，第二阶段属于中等规模、低数据库侵入的扩展，可以为后续 Ava 或 MCP adapter 提供稳定机器接口，同时不把外部协议耦合进图谱业务层。
