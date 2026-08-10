# Tool 层第二阶段 HTTP API 提案

## 1. 背景

当前图块图谱项目已经完成 Tool 层第一阶段。现有能力包括：

- `DrawingGraphToolFacade` 作为稳定应用门面，统一封装来源事实查询、派生关系查询、语义证据查询、候选关系查询、候选复核和断面匹配。
- `DrawingGraphQAService` 作为 facade 外侧的问答编排层，支持 `page_summary`、`block_relations`、`candidate_relations`、`section_matches`、`table_caption_status` 和 `diagnostic_status`。
- `QARequest`、`QAScope`、`QAAnswer`、`AnswerFact`、`EvidenceRef` 和 `QAErrorCode` 已形成稳定结构化契约。
- `scripts/drawing_graph_qa.py` 已提供 JSON 和简短中文两种命令行输出，并保持默认只读、`write_back=false`。
- QA 输出已经区分 `source_fact`、`derived_relation`、`semantic_observation`、`semantic_interpretation`、`candidate_relation` 和 `formal_relation`。

第一阶段解决了“如何把图谱能力组织成可追溯问答”的问题，但当前调用方式仍以 Python 内部接口和本机 CLI 为主。Ava、网页或其他本地软件还没有稳定的机器接口，无法通过标准 HTTP 请求复用同一套 QA 编排逻辑。

Tool 层第二阶段的目标是在现有 QAService 外侧增加一个薄 HTTP API adapter。HTTP 层负责请求校验、协议转换、访问控制、资源生命周期、错误脱敏和 JSON 响应；业务编排继续由 `DrawingGraphQAService` 完成，图谱能力继续只通过 `DrawingGraphToolFacade` 获取。

推荐依赖方向：

```text
Ava / local web client / local application
  -> HTTP API adapter
      -> DrawingGraphQAService
          -> DrawingGraphToolFacade
              -> ports / services
                  -> controlled repository / Neo4j
```

本阶段采用 `FastAPI + Uvicorn + 应用工厂 + lifespan runtime` 方案。HTTP 路由保持同步只读，复用当前同步 QAService 和 Neo4j driver；driver、facade 和 QAService 在应用启动时创建，在应用关闭时释放。

## 2. 当前问题

当前架构已经具备 HTTP API 所需的业务服务和数据契约，但仍缺少正式的 HTTP 协议层和长生命周期运行边界。

具体问题如下：

1. **缺少稳定机器接口。** 当前 Ava、网页或其他本地软件只能间接调用 CLI 或嵌入 Python，缺少版本化 HTTP endpoint。
2. **HTTP 客户端无法直接复用 QA 契约。** `QARequest` 和 `QAAnswer` 已存在，但尚无受控 HTTP request/response 模型、字段白名单和状态码映射。
3. **资源生命周期仅适配短命令。** QA CLI 每次调用都会创建和关闭 Neo4j driver；HTTP 服务是长生命周期进程，需要在应用启动和关闭阶段统一管理 driver、facade 和 QAService。
4. **序列化逻辑仍是 CLI 私有能力。** `_jsonable()` 位于 `scripts/drawing_graph_qa.py`，如果 HTTP 层复制该逻辑，会形成两套 JSON 输出契约。
5. **错误脱敏逻辑仍是 CLI 私有能力。** `_sanitize_message()` 没有成为 adapter 共用能力，HTTP 异常可能暴露密码、URI、Cypher、driver 或内部堆栈。
6. **缺少 HTTP 专用配置。** 当前没有 host、port、allowed origins、访问令牌、请求大小、超时和文档开关等受控配置。
7. **缺少访问边界。** 如果服务默认绑定局域网或公网地址且未配置认证，图纸 ID、图片路径、bbox、语义证据和候选关系可能被未授权访问。
8. **缺少 HTTP 并发约束。** 当前 QAService 和 Neo4j 调用是同步的，HTTP 场景下需要明确线程池、连接池、并发上限和超时策略。
9. **缺少健康检查语义。** 当前无法区分 HTTP 进程存活、运行时已装配和 live Neo4j 已验证，容易产生错误的运行状态声明。
10. **文档仍把 HTTP API 写成未实现能力。** 第二阶段完成后需要同步 README、Module、architecture 和文档测试，避免规划状态与实现状态漂移。

## 3. 功能目标

本变更的功能目标是建立一个版本化、默认本机监听、默认只读、可追溯并可测试的 HTTP API，使外部本地客户端能够复用第一阶段的 QA 编排能力。

### 3.1 核心目标

1. 新增 FastAPI 应用工厂 `create_app()`，模块 import 时不创建 Neo4j driver、不连接数据库、不读取真实数据。
2. 通过应用 lifespan 创建并复用 driver、`DrawingGraphToolFacade` 和 `DrawingGraphQAService`，关闭应用时可靠释放 driver。
3. 新增通用 HTTP 问答入口，把受控 JSON 请求转换为 `QARequest`，调用 `DrawingGraphQAService.ask()` 并返回结构化 `QAAnswer`。
4. 新增少量稳定便捷路由，覆盖页面摘要、图块关系、候选关系、断面匹配、表格标题状态和诊断状态。
5. 使用版本化 API 前缀 `/api/v1`，为后续兼容演进保留空间。
6. 抽取 CLI 与 HTTP 共用的 JSON 序列化、成功/错误 envelope 和错误脱敏能力，保证同一 `QAAnswer` 在不同 adapter 中保持一致语义。
7. 建立稳定 HTTP 状态码映射：正常和部分回答、非法参数、禁止写回、对象不存在、能力不支持、依赖不可用和内部错误分别处理。
8. 新增 HTTP 专用配置，默认监听 `127.0.0.1`，默认不开放 CORS，凭据只来自环境变量或受控运行配置。
9. 所有 HTTP QA 请求保持默认 `write_back=false`；`write_back=true` 必须被拒绝。
10. 保留事实分层：候选关系不是正式事实，语义观察和解释不能覆盖来源事实，`matched_candidate` 不能表述为正式图谱关系。
11. 新增存活和就绪检查，但健康响应必须明确自身范围，不能把进程存活或 runtime 已装配写成 live Neo4j 已验证。
12. 使用 fake QAService、fake runtime 和 fake driver 完成 HTTP 合约、生命周期和安全边界测试，不把真实 Neo4j 作为单元测试前提。

### 3.2 最小接口目标

| 方法 | 路径 | 对应能力 |
|---|---|---|
| `POST` | `/api/v1/drawing-qa/ask` | 通用 `QARequest` 问答入口 |
| `GET` | `/api/v1/drawing-qa/pages/{page_id}/summary` | `page_summary` |
| `GET` | `/api/v1/drawing-qa/blocks/{block_id}/relations` | `block_relations` |
| `GET` | `/api/v1/drawing-qa/candidates` | `candidate_relations` |
| `GET` | `/api/v1/drawing-qa/section-matches` | `section_matches` |
| `GET` | `/api/v1/drawing-qa/table-captions/status` | `table_caption_status` |
| `GET` | `/api/v1/drawing-qa/diagnostics` | `diagnostic_status` |
| `GET` | `/health/live` | 仅表示 HTTP 进程存活 |
| `GET` | `/health/ready` | 表示 HTTP runtime 已完成装配 |

通用 `POST /ask` 是权威接口。便捷 GET 路由只负责把路径参数和查询参数转换为同一 `QARequest`，不得分别实现 page、block、candidate 或 section 的业务聚合逻辑。

### 3.3 输出目标

成功响应应包含：

- `status="ok"`。
- `data`：`QAAnswer` 的 JSON-compatible 表示。
- `meta`：至少包含 `request_id` 和契约版本。

错误响应应包含：

- `status="failed"`。
- `error`：稳定的 `category`、脱敏 `message` 和 `retryable`。
- `meta`：至少包含 `request_id` 和契约版本。

`partial` 是可用回答，应返回 HTTP 200，并在 `warnings` 和 `unsupported_parts` 中保留缺口。依赖不可用才映射为可重试的服务错误，不用空值或猜测补全缺失事实。

### 3.4 安全目标

- 默认 host 为 `127.0.0.1`。
- 默认 CORS 关闭；需要浏览器跨域调用时只允许显式 origin 白名单。
- HTTP 请求体不接受 Neo4j URI、用户名、密码、供应商 API key、token、Cypher、driver、session、transaction 或 repository 参数。
- 如使用静态 API token，只能通过受控环境配置和请求 header 传递，不进入 QA DTO、响应或日志。
- 默认日志只记录 request ID、路由、状态码和耗时，不记录完整请求、完整答案、密钥或底层堆栈。
- 第一版采用单进程、受控并发；在进程内 run log、payload store 和 cache 未外置前，不默认开启多 worker。

## 4. 修改范围

### 4.1 新增模块

| 类型 | 文件或位置 | 修改内容 |
|---|---|---|
| 新增 | `src/drawing_graph/qa_serialization.py` | 提供 QA DTO 到 JSON-compatible 数据的统一转换、成功/错误 envelope 和共享脱敏能力 |
| 新增 | `src/drawing_graph/qa_http_models.py` | 定义 HTTP request/response 模型、字段白名单、scope 映射和只读校验 |
| 新增 | `src/drawing_graph/qa_http.py` | 提供 FastAPI `create_app()`、版本化路由、异常处理器、request ID、访问控制和 health endpoint |
| 新增 | `src/drawing_graph/qa_http_runtime.py` | 管理 driver、facade、QAService 的创建、复用和关闭 |
| 新增 | `scripts/serve_drawing_graph_qa.py` | 提供 Uvicorn 服务启动入口，只负责配置加载和 server 启动 |
| 新增 | `tests/test_qa_serialization.py` | 覆盖 DTO、Enum、tuple、Path、只读 mapping、envelope 和脱敏转换 |
| 新增 | `tests/test_qa_http_models.py` | 覆盖请求模型、未知字段、非法 scope、敏感字段和 write-back 拒绝 |
| 新增 | `tests/test_qa_http.py` | 覆盖路由映射、响应结构、状态码、异常脱敏、事实分层和默认访问边界 |
| 新增 | `tests/test_qa_http_runtime.py` | 覆盖 runtime 初始化、单次复用、启动失败清理和 shutdown 关闭 driver |
| 新增 | `tests/test_qa_http_docs.py` | 保护 HTTP 当前能力、只读边界、默认本机监听和未实现范围 |

`qa_http_runtime.py` 是否独立保留，可在 design 阶段依据职责大小最终确认；但路由注册、配置读取、runtime 装配和业务编排不能全部混入一个模块。

### 4.2 修改已有模块

| 类型 | 文件或位置 | 修改内容 |
|---|---|---|
| 修改 | `requirements.txt` | 增加 FastAPI、Uvicorn 和 HTTP 测试所需依赖，并声明受控兼容范围 |
| 修改 | `src/drawing_graph/config.py` | 新增 `QAHttpConfig`，读取 Neo4j 连接、host、port、origin、访问控制和服务限制配置；敏感字段在 `repr` 中屏蔽 |
| 修改 | `scripts/drawing_graph_qa.py` | 改用共享序列化和脱敏能力，保持现有 CLI 参数、退出码和 JSON 语义兼容 |
| 修改 | `tests/test_qa_cli.py` | 验证抽取公共能力后 CLI 行为不回退 |
| 修改 | `tests/test_qa_docs.py` | 第二阶段实现后更新“HTTP 未实现”断言，改为保护 HTTP 当前边界 |
| 修改 | `README.md` | 增加 HTTP 服务启动、最小调用、配置、安全默认值和验证说明 |
| 修改 | `Module.md` | 记录 HTTP 模块职责、新接口、新依赖和 runtime 边界 |
| 修改 | `architecture.md` | 将 HTTP adapter 加入当前架构，同时保留 MCP、Ava 专有集成等未实现范围 |

### 4.3 原则上不修改的模块

| 模块 | 原因 |
|---|---|
| `src/drawing_graph/qa_models.py` | 领域 QA 契约已经稳定；HTTP/Pydantic 细节不应进入领域模型 |
| `src/drawing_graph/qa_service.py` | 业务编排已经完成；不应加入 HTTP request、response、header、状态码、driver 或环境变量逻辑 |
| `src/drawing_graph/qa_rendering.py` | HTTP 权威输出为 JSON，简短中文仍属于 CLI/展示层 |
| `src/drawing_graph/tool_facade.py` | 当前 facade 已支持第二阶段问答，不为 HTTP 增加写回入口或 Web 语义 |
| `src/drawing_graph/tool_factory.py` | 当前 `create_neo4j_tool_facade(driver)` 已满足 runtime 装配需求；除非 design 阶段发现必要的测试注入缺口，否则不改 |
| `src/drawing_graph/query_service.py` | HTTP 层不直接访问查询服务 |
| `src/drawing_graph/relation_repository.py` | HTTP 层不直接访问 repository，也不提供候选提升或关系写回 |
| `src/drawing_graph/block_relation_enrichment.py` | HTTP QA 不计算或修改离线空间规则 |
| `src/drawing_graph/import_service.py` | HTTP QA 不导入数据 |
| `scripts/import_json.py` | HTTP 服务不改变基础导入入口 |
| `scripts/enrich_block_relations.py` | HTTP 服务不触发离线派生关系增强 |
| `scripts/review_candidate_relations.py` | HTTP 服务不替代显式候选关系复核流程 |
| `scripts/create_schema.cypher` | 第二阶段不新增 Neo4j 节点、关系、约束或索引 |

### 4.4 数据与数据库范围

- 不新增 Neo4j Schema。
- 不新增图谱业务节点或关系。
- 不改变来源事实、派生关系、语义证据、候选关系和正式关系的现有语义。
- `RecognitionRun` 继续位于图谱外，`TextObservation` 和各类 `Interpretation` 继续位于图谱内，二者只通过 `recognition_run_id` 关联。
- HTTP request ID 和访问日志属于 adapter 运行信息，不写入来源事实层或语义证据层。
- 第二阶段不引入生产级问答审计数据库；如后续需要跨进程审计，应单独立项。

## 5. 不包含范围

本变更不包含以下内容：

1. 不实现任意 Cypher HTTP 接口，不接受客户端提供的 Cypher。
2. 不让 HTTP 层直接访问 `QueryService`、`RelationRepository`、Neo4j session/transaction 或离线规则函数。
3. 不实现来源事实导入、离线派生关系增强、候选复核写回、语义证据写回或正式关系提升 HTTP endpoint。
4. 不开放 `write_back=true`；所有第二阶段 QA HTTP 请求保持只读。
5. 不把 `candidate_relation`、`CANDIDATE_*`、`matched_candidate`、模型 observation 或 interpretation 表述为正式事实。
6. 不覆盖来源事实节点，不设置或推断 `DrawingBlock.block_type`。
7. 不新增或修改 Neo4j Schema、约束、索引、业务节点或关系类型。
8. 不实现 MCP Tool adapter。
9. 不实现 Ava 专有插件、SDK、账号体系或专有协议适配；Ava 可先作为通用 HTTP 客户端使用。
10. 不实现 Agent Skill；现有项目级 Codex Skill 仍只是 facade 外侧的操作工作流。
11. 不实现 OCR、全量自动语义扫描、文件 watcher、定时任务或后台任务队列。
12. 不默认接入真实云多模态模型供应商，不新增供应商 API key 请求字段。
13. 不建设生产级用户体系、RBAC、租户隔离、计费、完整审计平台或管理后台。
14. 不默认提供公网部署、TLS 终止、反向代理或互联网级防护；这些需要单独部署方案。
15. 不默认开启 CORS 通配符，不在未配置认证时监听非 loopback 地址。
16. 不封装真实 `data/`、PNG/JSON、Neo4j 数据、`.env`、密码、API key、token 或 secret。
17. 不把 `/health/live` 或 `/health/ready` 的成功响应写成 live Neo4j 集成验证通过。
18. 不把被跳过的集成测试报告为通过；未实际连接 disposable Neo4j 时，live Neo4j 状态仍为未验证。

## 6. 影响模块

### 6.1 直接影响模块

| 模块 | 影响程度 | 说明 |
|---|---|---|
| `src/drawing_graph/qa_serialization.py` | 高，新建 | CLI 与 HTTP 共用的稳定 JSON、envelope 和脱敏边界 |
| `src/drawing_graph/qa_http_models.py` | 高，新建 | HTTP 输入输出契约和非法字段拒绝入口 |
| `src/drawing_graph/qa_http.py` | 高，新建 | HTTP 路由、应用工厂、异常映射、health 和访问控制核心 |
| `src/drawing_graph/qa_http_runtime.py` | 高，新建 | 长生命周期 driver/facade/QAService 装配和释放 |
| `scripts/serve_drawing_graph_qa.py` | 高，新建 | HTTP 服务启动入口 |
| `src/drawing_graph/config.py` | 中 | 新增 HTTP 专用配置，不复用无关导入参数 |
| `requirements.txt` | 中 | 新增 HTTP 框架、ASGI server 和测试依赖 |
| `scripts/drawing_graph_qa.py` | 低 | 改用公共序列化与脱敏，保持现有 CLI 行为兼容 |
| `tests/test_qa_http*.py` | 高，新建 | HTTP 合约、runtime、安全和文档边界测试 |
| `README.md` / `Module.md` / `architecture.md` | 中 | 第二阶段完成后同步真实实现状态和边界 |

### 6.2 间接影响模块

| 模块 | 影响 | 说明 |
|---|---|---|
| `src/drawing_graph/qa_models.py` | 被映射 | HTTP request model 转换为领域 `QARequest`，领域 DTO 保持框架无关 |
| `src/drawing_graph/qa_service.py` | 被调用 | 所有 HTTP 业务请求最终只调用 `DrawingGraphQAService.ask()` |
| `src/drawing_graph/tool_facade.py` | 间接调用 | 继续作为唯一图谱应用门面，不暴露给 HTTP route 直接组合 |
| `src/drawing_graph/tool_factory.py` | runtime 使用 | 通过 `create_neo4j_tool_facade(driver)` 装配受控图谱能力 |
| `src/drawing_graph/tool_models.py` | 间接投影 | facade 错误和 DTO 经 QAService 转换后进入 HTTP 输出 |
| `src/drawing_graph/semantic_*` | 间接读取 | HTTP 只读取 QAService 已允许的语义证据，不新增写回行为 |
| `src/drawing_graph/section_match_service.py` | 间接 dry-run | 断面匹配仍只允许 `write_back=false` |
| `src/drawing_graph/candidate_review.py` | 边界保护 | 第二阶段 HTTP 不调用候选复核或正式关系提升 |

### 6.3 不应受影响模块

| 模块 | 原因 |
|---|---|
| 基础导入模块 | HTTP QA 不读取或修改原始 JSON/PNG，不改变来源事实入库流程 |
| 离线增强模块 | HTTP QA 不触发空间关系计算或批次增强 |
| 候选复核 CLI | HTTP QA 不新增审核写回入口 |
| Neo4j Schema | HTTP 是协议 adapter，不是新的图谱数据层 |
| 项目级 Codex Skill | 本阶段不把 Skill 改造成 HTTP/MCP 业务实现 |

### 6.4 测试与验证影响

第二阶段实现后需要保持第一阶段 QA 模型、服务、渲染和 CLI 测试继续通过，并新增以下验证：

- HTTP 模块 import 无副作用。
- 应用工厂可注入 fake QAService。
- lifespan 只创建一次 runtime，关闭时只关闭一次 driver。
- 所有路由只调用 `DrawingGraphQAService.ask()`。
- 请求体未知字段和敏感字段被拒绝。
- `write_back=true` 返回禁止写回错误。
- `partial` 回答保留可用 facts、warnings 和 unsupported parts。
- 候选关系、语义观察、语义解释和正式关系在 JSON 中保持不同事实类型。
- 所有客户端错误消息经过脱敏。
- 默认 host 为 `127.0.0.1`，默认 CORS 关闭。
- 健康检查不虚构 live Neo4j 验证状态。
- 全量单元测试无回归。
- live Neo4j 集成测试只有在配置 disposable 测试库并实际运行后才能标记为通过。

本提案完成后，下一步应基于本文件和 `Feature_Analysis_Report.md` 编写第二阶段 `design.md`，进一步确定 HTTP 数据模型、状态码映射、配置字段、应用生命周期、测试注入和模块接口；在 design 获得确认前不进入代码实现。
