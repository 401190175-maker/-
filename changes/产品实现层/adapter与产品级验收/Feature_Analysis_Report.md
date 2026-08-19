# Adapter 与产品级验收功能分析报告

## 1. 当前架构是否支持

当前架构支持在不重建图谱、不绕过 facade 的前提下补齐 adapter 与产品级验收。

已支持的基础能力包括：

- `DrawingGraphToolFacade` 已作为图谱能力统一入口，负责只读查询、按需语义识别、候选关系查询和受控候选审核边界。
- 旧 QA 链路已实现：`DrawingGraphQAService`、`scripts/drawing_graph_qa.py`、只读 HTTP API（`src/drawing_graph/qa_http.py` + `scripts/serve_drawing_graph_qa.py`）和本地 STDIO MCP adapter（`src/drawing_graph/qa_mcp_*.py` + `scripts/serve_drawing_graph_mcp.py`）。
- 产品级只读链路已实现为内部服务与 CLI：`DrawingAssistantService.answer()` 固定串联 01-06，`scripts/drawing_assistant.py` 提供只读 CLI，默认 `write_back=false`，拒绝 `allow_write_back=true`。
- 07/08 追溯与反馈内部能力已实现为注入式 trace/feedback store，不新增 Neo4j schema，不写业务事实。
- HTTP QA adapter 已具备 request id、安全响应头、请求体大小限制、并发上限、请求超时、错误 envelope 与脱敏映射。
- MCP QA adapter 已具备六个窄口径只读工具、输入模型、structuredContent/TextContent 一致输出和本地 STDIO runtime。

仍不支持或尚未完成的能力包括：

- 产品级 HTTP adapter：当前 HTTP 只服务旧六类 `DrawingGraphQAService`，尚未提供 `DrawingAssistantService` 的自然语言 `/drawing-assistant/ask` 入口。
- 产品级 MCP adapter：当前 MCP 只提供六个固定 QA 工具，尚未提供产品级自然语言 assistant tool。
- 产品级 HTTP/MCP 对 07 trace 与 08 feedback 的外部入口尚未实现。
- 产品级 E2E 验收记录尚未覆盖 HTTP/MCP 产品入口、旧 QA 兼容矩阵、并发/超时/错误映射矩阵与文档层 live 状态。
- live Neo4j、live DashScope、真实文本 provider 与真实 MCP 宿主注册仍需要独立验收；skipped 测试不能写成 live 已通过。

结论：架构支持本需求，但应新增产品级 adapter 层与验收层，而不是修改旧 QA 的职责或让 adapter 直接访问 Neo4j。

## 2. 需要新增哪些模块

建议新增以下模块，均位于 `DrawingAssistantService` 外侧、`DrawingGraphToolFacade` 间接外侧：

| 模块 | 建议文件 | 目标职责 |
|---|---|---|
| 产品 HTTP 协议模型 | `src/drawing_graph/assistant_http_models.py` | 定义产品级 request/response/error/health DTO，转换为 `AssistantRequest`，拒绝未知字段和写回扩张。 |
| 产品 HTTP runtime | `src/drawing_graph/assistant_http_runtime.py` | 管理 driver、facade、`DrawingAssistantService` 的装配与关闭；只有 runtime/启动脚本知道 driver。 |
| 产品 HTTP app | `src/drawing_graph/assistant_http.py` | 提供版本化产品只读路由、并发/超时/错误映射、安全头和 health endpoint。 |
| 产品 HTTP 启动脚本 | `scripts/serve_drawing_assistant.py` | 从环境变量加载配置，启动单 worker 产品 HTTP 服务，不接受 secret 命令行参数。 |
| 产品 MCP 模型 | `src/drawing_graph/assistant_mcp_models.py` | 定义产品级自然语言 assistant tool 输入输出，并映射到 `AssistantRequest`。 |
| 产品 MCP 工具 | `src/drawing_graph/assistant_mcp_tools.py` | 调用一次 `DrawingAssistantService.answer()`，从同一个 `AnswerPackage` 生成 structuredContent 和 TextContent。 |
| 产品 MCP runtime/server | `src/drawing_graph/assistant_mcp_runtime.py`、`assistant_mcp_server.py` | 管理本地 STDIO MCP 生命周期、工具 schema 与只读 annotations。 |
| 产品 MCP 启动脚本 | `scripts/serve_drawing_assistant_mcp.py` | 本地 STDIO 产品 MCP 唯一入口，stdout 只承载协议帧。 |
| 产品 adapter 共享映射 | `src/drawing_graph/assistant_adapter_serialization.py` | 复用 `to_jsonable()` 与脱敏逻辑，统一 `AnswerPackage` envelope、错误类别、trace/validation 边界字段。 |
| 产品验收文档 | `docs/acceptance/PRODUCT_ADAPTER_ACCEPTANCE.md` | 记录产品 CLI/HTTP/MCP、旧 QA 兼容、E2E、并发/超时/错误映射、live 状态分层。 |

若当前代码已有相同职责文件，实施时应优先复用并扩展，不重复造第二套同义模块。

## 3. 影响哪些已有模块

| 已有模块 | 影响方式 |
|---|---|
| `src/drawing_graph/drawing_assistant_service.py` | 保持产品总编排唯一入口；不为 adapter 增加业务分支。 |
| `src/drawing_graph/drawing_assistant_factory.py` | 复用现有 factory 装配；必要时增加 config 参数，但不得读取 env 或创建 driver。 |
| `src/drawing_graph/assistant_models.py` | 可能补充 adapter 所需的稳定错误/输出字段；不得引入 HTTP/MCP/driver 依赖。 |
| `src/drawing_graph/qa_serialization.py` | 可复用 JSON 转换与脱敏；如需产品专用 envelope，新增 adapter serialization，避免污染 QA 合同。 |
| `src/drawing_graph/qa_http.py`、`qa_http_models.py`、`qa_http_runtime.py` | 保持旧 QA HTTP 行为不变；可参考并发/超时/错误映射模式，不把产品路由塞入旧 QA app。 |
| `src/drawing_graph/qa_mcp_*.py` | 保持旧六工具 MCP 行为不变；可参考 structuredContent/TextContent、runtime 和 server 模式。 |
| `scripts/drawing_assistant.py` | 保持产品 CLI 兼容；新增验收用例可复用 CLI smoke，不新增写回参数。 |
| `scripts/serve_drawing_graph_qa.py`、`serve_drawing_graph_mcp.py` | 保持旧 QA 启动入口不变；新增产品启动脚本并列存在。 |
| `tests/` | 新增产品 HTTP/MCP/adapter/acceptance/boundary 测试；保留旧 QA 测试矩阵。 |
| `docs/acceptance/` | 新增产品 adapter 验收记录；不改写历史验收为当前 live 证明。 |
| `README.md`、`Module.md`、`architecture.md` | 后续实施完成后同步当前状态；本规划阶段不修改。 |

## 4. 技术方案有哪些

### 方案 A：新增产品级 HTTP/MCP adapter，旧 QA adapter 保持不变

新增 `assistant_http*` 与 `assistant_mcp*`，它们只调用 `DrawingAssistantService.answer()`。旧 `qa_http*` 与 `qa_mcp*` 继续服务六类固定 QA。

优点：

- 职责边界最清楚，产品自然语言入口与旧 QA 固定工具互不污染。
- 可复用现有 HTTP/MCP 的安全、runtime、错误映射和测试风格。
- 兼容旧 QA、CLI、HTTP、MCP，不需要迁移用户。
- 便于分别验收：产品 adapter、旧 QA 兼容、live Neo4j、live DashScope 和 MCP 宿主注册可分层记录。

缺点：

- 会新增一组 adapter 文件和测试，短期文件数量增加。
- 需要维护两个对外协议族：旧 QA 协议与产品 assistant 协议。

### 方案 B：在现有 QA HTTP/MCP adapter 中追加产品路由和工具

直接修改 `qa_http.py` 和 `qa_mcp_server.py`，让它们同时暴露固定 QA 与产品 assistant。

优点：

- 启动入口少，部署路径短。
- 可以复用已有 config 和 runtime 代码。

缺点：

- QA runtime 当前装配的是 `DrawingGraphQAService`，产品 runtime 装配的是 `DrawingAssistantService`，强行合并会造成职责膨胀。
- 容易让旧 QA adapter 间接承载 01-07 产品业务，增加回归风险。
- MCP 工具清单和 server instructions 会混杂旧 QA 与产品 assistant，兼容合同更难保护。

### 方案 C：只扩展 CLI，不新增 HTTP/MCP 产品入口

继续把 `scripts/drawing_assistant.py` 作为唯一产品入口，HTTP/MCP 仍只走旧 QA。

优点：

- 实施范围最小。
- 不引入新的网络或 MCP 协议面。

缺点：

- 无法满足“HTTP/MCP 产品接口”和“产品级验收”目标。
- 用户仍无法通过 HTTP/MCP 使用自然语言产品助手。
- 无法完整验收并发、超时、错误映射等产品 adapter 行为。

### 方案 D：把产品能力塞进 `DrawingGraphQAService`

扩展 `DrawingGraphQAService` 使其直接承担自然语言理解、检索、识别、融合和答案生成。

优点：

- 外部旧 QA adapter 可以少改。

缺点：

- 违反 00 蓝图中“旧 QA 保留为六类确定性结构化问题”的边界。
- 容易破坏 QAService 的固定窄口径、只读和可解释合同。
- 会使候选/formal、write_back 和 live 验证边界更难审查。

## 5. 优缺点比较

| 方案 | 兼容旧 QA | 产品接口完整性 | 边界清晰度 | 实施风险 | 推荐度 |
|---|---|---|---|---|---|
| 方案 A：新增产品级 adapter | 高 | 高 | 高 | 中 | 推荐 |
| 方案 B：旧 adapter 追加产品路由 | 中 | 高 | 中 | 中高 | 备选 |
| 方案 C：只扩展 CLI | 高 | 低 | 高 | 低 | 不满足需求 |
| 方案 D：改造 QAService | 低 | 中 | 低 | 高 | 不推荐 |

## 6. 推荐方案

推荐采用方案 A：新增产品级 HTTP/MCP adapter 与产品验收文档，旧 QA adapter 保持不变。

推荐路线：

1. 固化产品 adapter 共享输出与错误映射：从 `AnswerPackage` 到 JSON envelope/TextContent 的转换独立于 QA。
2. 新增产品 HTTP：`POST /api/v1/drawing-assistant/ask` 和只读 health/ready，不提供写回路由。
3. 新增产品 MCP：一个窄口径自然语言 assistant tool，输入只接受 question、scope hint、recognition policy 等安全字段，不接受 Cypher、driver、path、secret 或 `write_back=true`。
4. 保留旧 QA：现有 `DrawingGraphQAService`、QA CLI、HTTP、MCP 全部原样通过兼容回归。
5. 建立产品验收：CLI/HTTP/MCP fake E2E、错误映射、并发/超时、旧 QA 兼容、文档层 live 状态分层。
6. 后续如需真实环境验收，再单独执行 live Neo4j、live DashScope、真实 MCP 宿主注册和真实文本 provider 验收，分别写明日期、环境和结果。

## 7. 风险

| 风险 | 表现 | 缓解策略 |
|---|---|---|
| 产品 adapter 绕过 facade | HTTP/MCP 直接创建 Neo4j driver 后拼 Cypher 或调用 repository | runtime 只负责装配，业务调用只到 `DrawingAssistantService.answer()`；静态边界测试禁止 driver/repository/Cypher 出现在工具层。 |
| 旧 QA 兼容被破坏 | 六类 QA HTTP/MCP 行为、schema、错误码发生漂移 | 每个任务保留旧 QA 专项回归；产品 adapter 使用新文件，不改旧 handler。 |
| 写回边界失守 | 产品 HTTP/MCP 接受 `write_back=true` 或把 allow_recognition 当成写回授权 | 协议模型不提供写回字段；若接收兼容字段必须 fail closed；service 入口继续拒绝 `allow_write_back=true`。 |
| candidate 被写成 formal | TextContent 或中文摘要把 `matched_candidate` 写成正式关系 | 产品和 MCP 渲染测试覆盖 candidate/formal 措辞；structuredContent 以 `AnswerPackage` 为权威。 |
| fake/offline 冒充 live | HTTP TestClient、MCP in-memory 或 skipped 集成测试被写成 live Neo4j 通过 | 验收文档强制分层：unit/fake/offline、HTTP socket、MCP STDIO、live Neo4j、live DashScope、真实宿主注册。 |
| HTTP 并发/超时导致后台线程泄漏或双响应 | timeout 后请求线程继续运行，adapter 状态不一致 | 继承 QA HTTP 的 semaphore + bounded worker 模式；测试 429/504、semaphore 释放和错误 envelope。 |
| MCP 输出污染 stdout | server 日志进入 stdout 破坏协议 | 启动脚本 stdout 只承载协议帧，日志走 stderr；STDIO smoke 覆盖。 |
| 文档层验收滞后 | README/Module/architecture 声称已实现但验收记录未支持 | 实施阶段把根文档更新与 acceptance 文档作为独立任务，文档测试保护旧状态。 |

## 8. 与当前 00-07 产品实现层规划的关系

| 阶段 | 当前关系 |
|---|---|
| 00 产品闭环蓝图 | 明确最终需要 CLI/HTTP/MCP/Web UI adapter 与产品级验收；本需求对应实施顺序中的 adapter 与验收收口。 |
| 01 问题理解 | 产品 adapter 输入自然语言后首先进入 01；adapter 不复制问题理解规则。 |
| 02 图谱检索 | 产品 adapter 不直接检索图谱，仍由 `DrawingAssistantService -> GraphRetrievalService -> DrawingGraphToolFacade` 完成。 |
| 03 语义缺口决策 | 产品 adapter 只传递 recognition policy，不自行决定识别目标或预算。 |
| 04 多模态识别 | 产品 adapter 不直接调用 Qwen；识别仍经 03 决策和 facade/semantic service，默认 dry-run。 |
| 05 证据融合与缓存 | 产品 adapter 不做融合、不写缓存；只序列化 05/06 产出的结果。 |
| 06 答案生成 | `AnswerPackage` 是产品 adapter 的权威输出来源，中文/文本摘要不得新增 claim。 |
| 07 追溯与反馈 | 当前内部 trace/feedback 已实现；本需求可规划外部只读 trace 查询和反馈入口，但首批 adapter 必须保持只读问答，反馈写回另设权限和任务。 |

## 9. 当前已实现能力与未实现能力边界

### 已实现

- 基础导入、离线派生关系增强、候选关系复核骨架。
- `DrawingGraphToolFacade` 与受控 facade/CLI。
- 旧 QA：`DrawingGraphQAService`、QA CLI、只读 HTTP API、本地 STDIO MCP adapter。
- 01 问题理解、02 通用检索、03 语义缺口决策、04 多模态识别执行、05 证据融合、06 答案生成、07 只读总编排。
- 产品级只读 CLI：`scripts/drawing_assistant.py`。
- 内部 trace/feedback store、状态机、候选审核适配。
- 大量 unit/fake/offline/静态边界测试。

### 未实现或不得写成已实现

- 产品级 HTTP natural-language assistant route。
- 产品级 MCP assistant tool。
- 产品级 Web UI 或 Ava 专有 adapter。
- 外部产品级 feedback HTTP/MCP/Web UI 入口。
- 外部持久化 trace/feedback store 与真实多用户账号集成。
- 远程 MCP、Streamable HTTP MCP、OAuth/RBAC、多 worker 生产部署。
- HTTP/MCP 写回入口。
- OCR、全量自动语义扫描、默认真实云模型调用。
- 新 Neo4j schema；本需求不应新增 Neo4j 节点、关系、索引或约束。
- live DashScope、真实文本 provider、真实 MCP 宿主注册、本轮 live Neo4j 产品链路验收。

### 必须持续保持的边界

- 默认 `write_back=false`。
- adapter 不直接访问 Neo4j driver、repository 或 Cypher。
- candidate、`matched_candidate`、`CANDIDATE_*` 不能写成 `formal_relation`。
- skipped live 测试不能描述为 live Neo4j 已通过。
- fake/offline/unit/live 验证状态必须分层说明。

## 10. 验证建议

建议按以下层级验收：

| 验证层 | 建议内容 | 可证明 | 不可证明 |
|---|---|---|---|
| 静态边界 | 产品 HTTP/MCP/serialization 不导入 repository、Cypher、底层 write-back | 依赖方向 | 真实协议可用性 |
| 单元/合同 | request/response DTO、错误 envelope、candidate/formal 渲染、write_back 拒绝 | 合同和安全规则 | 真实数据库可用性 |
| fake E2E | `DrawingAssistantService` fake facade 经过 CLI/HTTP/MCP 返回五类状态 | 产品 adapter 编排接缝 | live Neo4j、live DashScope |
| HTTP socket/TestClient | 429、504、413、401/403、request id、安全头、health | HTTP 协议行为 | MCP 可用性 |
| MCP in-memory | tools/list、tools/call、structuredContent/TextContent、isError | MCP 工具合同 | STDIO 子进程、真实宿主注册 |
| MCP STDIO smoke | 子进程协议帧、stderr 日志、一次 fake 调用 | STDIO adapter 生命周期 | live Neo4j 数据正确性 |
| 旧 QA 兼容回归 | `tests.test_qa_*`、旧 QA HTTP/MCP 测试 | 未破坏旧 QA | 产品 assistant 已正确 |
| live Neo4j | disposable 测试库、真实 service/facade 产品问答 | 真实数据库链路 | DashScope 质量 |
| live DashScope / 黄金集 | 真实图片 dry-run、结构化输出、人工黄金集 | 模型调用和质量样本 | Neo4j 写回 |
| 文档层验收 | `docs/acceptance/PRODUCT_ADAPTER_ACCEPTANCE.md` 与根文档合同 | 状态如实记录 | 未运行项已完成 |

首轮实施完成标准不应要求 live 环境必然存在，但必须在验收文档中把 live 项标为“已验证 / 未验证 / skipped，并说明原因”。
