# Adapter 与产品级验收 Proposal

## 1. 背景

当前项目已经具备图块图谱基础导入、离线派生关系增强、候选关系复核、语义证据层、旧 QA CLI/HTTP/MCP、产品 01-07 只读问答编排和产品级 CLI。用户已经可以通过 `scripts/drawing_assistant.py` 进行产品级自然语言问答，也可以通过旧 QA HTTP/MCP 使用六类固定问题。

下一步需要把产品级自然语言问答从 CLI 扩展到 HTTP/MCP 产品接口，并形成产品级验收记录，使“产品可以被外部调用、旧 QA 仍兼容、错误/超时/并发行为可验收、live 状态如实分层”成为可审查的交付物。

## 2. 当前问题

当前缺口不是底层图谱能力，而是产品 adapter 与验收收口：

- 产品级 HTTP 入口尚未实现；现有 HTTP API 只服务旧六类 QA。
- 产品级 MCP 工具尚未实现；现有 MCP server 只提供六个固定 QA 工具。
- 产品级 HTTP/MCP 的并发、超时、请求体限制、错误映射、TextContent/structuredContent 一致性尚无专门验收。
- 产品级 adapter 与旧 QA adapter 的兼容关系尚未形成回归矩阵。
- 文档层尚无 `PRODUCT_ADAPTER_ACCEPTANCE.md` 记录产品 CLI/HTTP/MCP、旧 QA 兼容、fake/offline/live 验证状态。
- 历史验收中存在不同阶段的测试数字和 skipped 记录；需要避免把 skipped 或历史 offline 结果误写成当前 live 验证通过。

## 3. 功能目标

本需求要完成：

1. 新增产品级只读 HTTP 接口，让外部调用方可以通过自然语言请求调用 `DrawingAssistantService.answer()`。
2. 新增产品级只读 MCP 工具，让本地 MCP client 可以通过自然语言请求调用同一产品服务。
3. 保持现有旧 QA CLI、HTTP、MCP 与 `DrawingGraphQAService` 的行为兼容。
4. 建立产品 adapter 的统一输出、错误映射、超时、并发和脱敏验收。
5. 建立产品级 fake/offline E2E 验收，覆盖 CLI/HTTP/MCP 三种入口。
6. 建立文档层 live 验收记录，明确区分 unit、fake/offline、HTTP socket、MCP in-memory、MCP STDIO、live Neo4j、live DashScope、真实文本 provider 和真实 MCP 宿主注册。
7. 持续保持默认只读边界：`write_back=false`，candidate 不等于 formal，adapter 不绕过 `DrawingGraphToolFacade`。

## 4. 修改范围

本需求允许规划的修改范围包括：

- 新增产品级 HTTP adapter 模块、协议模型、runtime 和启动脚本。
- 新增产品级 MCP adapter 模块、协议模型、工具、runtime/server 和启动脚本。
- 新增产品 adapter 共享 serialization/envelope/error mapping 模块。
- 新增产品 adapter 单元、合同、静态边界、fake E2E、HTTP/MCP smoke 和旧 QA 兼容测试。
- 新增 `docs/acceptance/PRODUCT_ADAPTER_ACCEPTANCE.md`。
- 在实施完成后同步 `README.md`、`Module.md`、`architecture.md` 中的当前能力和验证状态。
- 必要时小幅扩展 `assistant_models.py` 或 `drawing_assistant_factory.py` 的稳定配置/输出字段，但不得改变已有默认行为。

## 5. 不包含范围

本需求不包含：

- 不新增 Neo4j schema、节点、关系、索引或约束。
- 不实现 HTTP/MCP 写回接口。
- 不把用户反馈外部入口和候选正式提升合并进首批只读问答 adapter。
- 不实现 Web UI、Ava 专有 adapter、公共插件市场发布、远程 MCP、Streamable HTTP MCP、OAuth/RBAC 或多 worker 生产部署。
- 不实现 OCR、全量自动语义扫描或默认真实云模型调用。
- 不重构基础导入、离线派生关系增强、候选审核、语义证据 repository、旧 QAService 或旧 QA adapter。
- 不把 live Neo4j、live DashScope 或真实文本 provider 作为离线完成的默认前置条件。
- 不把 skipped 集成测试、HTTP health、MCP fake smoke 或历史数字写成当前 live 验证通过。

## 6. 影响模块

| 模块 | 影响 |
|---|---|
| `DrawingAssistantService` | 作为产品 adapter 唯一业务入口被复用；不增加 adapter 专属业务逻辑。 |
| `drawing_assistant_factory.py` | 被 HTTP/MCP runtime 复用；保持无副作用和注入式装配。 |
| `assistant_models.py` | 作为产品请求/答案合同基础；默认只读，不依赖协议层。 |
| 新产品 HTTP 模块 | 提供版本化自然语言问答 HTTP 入口。 |
| 新产品 MCP 模块 | 提供本地 STDIO 自然语言 assistant tool。 |
| `qa_http*` / `qa_mcp*` | 保持旧 QA 行为；只作为模式参考，不改造成产品编排器。 |
| `qa_serialization.py` | 复用 JSON-safe 转换和脱敏；产品 envelope 可在新模块中独立定义。 |
| `scripts/drawing_assistant.py` | 保持产品 CLI 兼容，并纳入三入口验收。 |
| `docs/acceptance/` | 新增产品 adapter 验收记录。 |

## 7. 兼容性要求

- 现有 QA CLI、HTTP 和 MCP 的路由、工具名、输入 schema、输出 envelope、错误类别和只读行为保持兼容。
- 产品级 HTTP/MCP 是新增入口，不替换旧 QA，不要求旧 QA 用户迁移。
- 产品 adapter 必须只调用 `DrawingAssistantService.answer()`，不得直接访问 `DrawingGraphToolFacade` 以外的底层能力，更不得创建 Neo4j driver 后自行查询或写 Cypher。
- HTTP 默认 loopback、只读；远程绑定、token、TLS 等仍按安全策略显式配置，不因产品入口自动放宽。
- MCP 首版为本地 STDIO，只读，不提供远程 transport、OAuth 或写回工具。
- `allow_recognition=true` 只表示允许按需识别，不等于允许写数据库。
- 默认 `write_back=false`；任何产品 adapter 不提供 `write_back=true` 路径。
- candidate、`matched_candidate`、`CANDIDATE_*` 必须保持候选语义，不得渲染成正式事实。
- fake/offline/unit/live 验证状态必须分层报告；skipped 不得报告为 live 通过。

## 8. 验收标准

本需求完成时应满足：

- 产品 HTTP 能通过自然语言请求返回稳定 `AnswerPackage` envelope，覆盖 answered、partial、clarification_required、unsupported、recognition_failed 和错误路径。
- 产品 MCP 能通过一个只读 assistant tool 返回同源 structuredContent 与 TextContent，TextContent 不新增事实。
- 产品 CLI、HTTP、MCP 三入口在 fake/offline E2E 中对同一 fake 服务保持核心状态与证据字段一致。
- HTTP 并发上限、请求超时、请求体过大、认证失败、参数错误、service 错误和未处理异常均映射为稳定错误 envelope，并脱敏。
- MCP 输入校验、工具错误、service 错误、unexpected error、stdout/stderr 边界均有测试。
- 旧 QA CLI、HTTP、MCP 兼容回归通过，且没有反向依赖产品 adapter。
- 静态边界测试证明产品 adapter 不导入 repository、Cypher、底层写回模块、离线增强规则或真实 provider。
- 文档层 `PRODUCT_ADAPTER_ACCEPTANCE.md` 记录实际执行命令、结果和验证分层；未执行 live 项明确标为未验证或 skipped。
- 根文档在实施完成后只描述已实现能力，不把计划项或未验证 live 能力写成已完成。
