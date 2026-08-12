# Tool 层第三阶段功能分析报告

## 0. 分析范围与结论

本报告分析 Tool 层第三阶段：在已经完成的 QA 编排层和只读 HTTP API 之上，同时建设：

1. **MCP Tool adapter**：为 Codex 或其他支持 MCP 的 Agent 提供少量、稳定、可发现、默认只读的图块图谱工具。
2. **现有 Codex Skill 强化**：让 Agent 能把自然语言问题稳定映射到 MCP/QA 能力，并按项目既有边界解释来源事实、派生关系、语义证据、候选关系和正式关系。

本报告只做架构与方案分析，不修改 `src/`、`scripts/`、`.codex/skills/`、`.agents/skills/`、Neo4j Schema、测试或真实数据。

已核对的主要依据：

- `changes/tool层/第一阶段/Feature_Analysis_Report.md`
- `changes/tool层/第一阶段/design.md`
- `changes/tool层/第一阶段/proposal.md`
- `changes/tool层/第一阶段/tasks.md`
- `changes/tool层/第二阶段/Feature_Analysis_Report.md`
- `changes/tool层/第二阶段/design.md`
- `changes/tool层/第二阶段/proposal.md`
- `changes/tool层/第二阶段/tasks.md`
- `architecture.md`
- `Module.md`
- `README.md`
- 当前 `qa_models.py`、`qa_service.py`、`qa_http*.py`、`qa_serialization.py`、`tool_facade.py`、`tool_factory.py`、QA/HTTP/Skill 相关测试
- 当前 `.codex/skills/drawing-graph-operator/` 全部 Skill 资产
- OpenAI 当前 Codex Skill 与 MCP 官方文档、MCP 当前规范和 Python SDK 官方文档

当前结论：

1. **当前架构支持第三阶段，且业务支撑度高。** 第一阶段已形成稳定 `QARequest -> DrawingGraphQAService -> DrawingGraphToolFacade` 编排链，第二阶段又验证了长生命周期 runtime、JSON 序列化、错误脱敏、超时和并发边界。MCP 无需重写图谱查询或问答聚合。
2. **第三阶段仍需新增独立 MCP adapter。** 现有 HTTP API 是 REST/JSON adapter，不是 MCP server；现有 Skill 是操作指令，不是机器协议。二者都不能替代 MCP 的工具发现、输入/输出 Schema、初始化 instructions 和传输层。
3. **Skill 不是鸡肋。** MCP 解决“工具怎样被调用”，Skill 解决“何时调用哪个工具、怎样组合、怎样解释”。Skill 仍负责问题路由、证据分层、保守表述、验证状态和禁止事项；业务逻辑仍不进入 Skill。
4. **现有 `.codex/skills/drawing-graph-operator` 在当前环境中有效，但存在路径演进风险。** 当前 Codex 会话已实际发现并加载该 Skill；但当前 OpenAI 官方文档将仓库级 Skill 的标准发现位置写为 `.agents/skills`。因此不能把现有目录直接判定为废弃，也不应未经验证立即删除或复制。
5. **推荐第一版采用独立 STDIO MCP server。** 它直接调用 `DrawingGraphQAService`，默认只读、仅本机子进程可用，不复用 HTTP adapter、不开放网络。内部工具注册与传输分离，为后续 Streamable HTTP 预留扩展点。
6. **第三阶段不开放写回。** 不提供导入、增强、语义证据持久化、候选审核、候选提升、正式关系写入或任意 Cypher 工具。所有 MCP 工具都应在协议元数据中标注只读，但安全不能只依赖 annotation，仍由 QAService/facade 强制执行 `write_back=false`。
7. **不修改 Neo4j Schema。** MCP 和 Skill 都位于现有应用边界外侧，不产生新的来源事实、语义证据或图谱关系。

推荐目标架构：

```text
Codex Skill / external Agent
  -> MCP client
      -> STDIO MCP transport
          -> DrawingGraph MCP adapter
              -> MCP request model / tool registry / result mapper
              -> DrawingGraphQAService
                  -> DrawingGraphToolFacade
                      -> ports / services
                          -> controlled repository / Neo4j
```

CLI、HTTP 与 MCP 保持同级：

```text
QA CLI adapter --------|
HTTP API adapter ------|-> DrawingGraphQAService -> DrawingGraphToolFacade
MCP Tool adapter ------|
Codex Skill -----------|  负责选择、组合与解释，不承载业务逻辑
```

## 1. 当前架构是否支持

### 1.1 已具备的支撑能力

| 当前能力 | 对第三阶段的价值 | 当前状态 |
|---|---|---|
| `DrawingGraphQAService.ask()` | 已统一六类问题的 scope 校验、facade 调用和证据聚合，可作为 MCP 工具唯一业务入口 | 已实现 |
| `QARequest` / `QAScope` | 已形成显式、类型化、默认只读的输入契约 | 已实现 |
| `QAAnswer` / `AnswerFact` / `EvidenceRef` | 已保留事实类型、业务 ID、bbox、run ID、payload ref、warnings 和 unsupported parts | 已实现 |
| `QAError` / `QAErrorCode` | 可稳定映射为 MCP tool error/result，不需要暴露底层异常 | 已实现 |
| `qa_serialization.py` | 可把 QA DTO 转成 JSON-compatible 结构并统一脱敏 | 已实现 |
| `DrawingGraphToolFacade` | 统一封装来源事实、派生关系、语义证据、候选关系和断面匹配 | 已实现 |
| `create_neo4j_tool_facade(driver)` | MCP 进程可在 adapter 最外层装配真实 facade | 已实现 |
| HTTP runtime 经验 | 已验证 driver/facade/QAService 的创建、复用、关闭和初始化失败清理 | 已实现，可借鉴，不直接调用 |
| fake facade / QA 单元测试 | MCP 合约测试可不依赖真实 Neo4j | 已具备基础 |
| `drawing-graph-operator` Skill | 已定义 facade 边界、`write_back=false`、事实分层和验证规则 | 已实现，尚未包含 QA/MCP 工作流 |

### 1.2 当前缺口

| 缺口 | 具体表现 | 第三阶段影响 |
|---|---|---|
| 没有 MCP SDK 依赖 | `requirements.txt` 没有 MCP Python SDK | 无法实现标准初始化、工具发现和调用协议 |
| 没有 MCP server 入口 | 当前只有 CLI 与 HTTP 启动入口 | Codex 不能以 MCP server 方式启动本项目工具 |
| 没有 MCP 工具 Schema | 六类 QA 能力尚未映射为少量稳定工具 | Agent 无法可靠发现参数和结构化输出 |
| 没有 MCP 结果映射 | QAAnswer/QAError 尚未映射到 MCP `structuredContent` 和安全文本摘要 | 客户端处理不稳定，可能丢失事实分层 |
| 没有 MCP server instructions | 服务器初始化阶段没有声明只读、候选非事实、证据和限流边界 | Agent 仅看工具名可能错误使用 |
| 没有 MCP 生命周期模块 | STDIO 进程如何创建/关闭 driver 尚未定义 | 可能 import 即连接或退出时泄漏连接 |
| Skill 未覆盖 QA/MCP 路由 | 当前 Skill 主要指导 facade CLI，只列出底层命令 | 自然语言问题不能稳定优先走 QA/MCP |
| Skill 路径存在演进差异 | 当前仓库使用 `.codex/skills`，官方当前文档写 `.agents/skills` | 跨 Codex 版本或其他宿主的发现能力存在风险 |
| 没有端到端 MCP 验证 | 尚未验证 initialize、tools/list、tools/call、关闭和错误脱敏 | 不能把代码级测试等同于 MCP 可用 |

### 1.3 架构判断

当前架构在业务和数据契约上已经支持第三阶段，在协议与操作编排上尚未支持。

- MCP adapter 不需要新增业务查询，只需把稳定工具调用转换为 `QARequest`，再调用 `DrawingGraphQAService.ask()`。
- Skill 强化不需要复制 QAService 逻辑，只需记录工具选择、参数要求、调用顺序、降级策略和输出解释规则。
- HTTP、MCP、CLI 不应相互调用。三者共享 QA DTO、QAService、序列化和脱敏能力即可。
- 如果 MCP 实施中发现 QA 能力缺口，应返回 `partial` / `unsupported_parts` 或单独扩展窄口径 QA/facade 能力，不能在 MCP 层访问 repository 或拼写 Cypher。

## 2. 需要新增哪些模块

### 2.1 MCP 必需模块

| 建议模块 | 职责 | 设计边界 |
|---|---|---|
| `src/drawing_graph/qa_mcp_models.py` | 定义 MCP 工具输入模型、结构化结果 envelope 和 QA DTO 转换 | 不调用 QAService、不读环境变量、不包含凭据 |
| `src/drawing_graph/qa_mcp_tools.py` | 注册少量稳定 MCP tools，将参数转换为 `QARequest`，统一调用 `DrawingGraphQAService.ask()` | 不直接调用 facade、HTTP、repository 或 Cypher |
| `src/drawing_graph/qa_mcp_runtime.py` | 创建/关闭 Neo4j driver、facade、QAService，并提供可注入 fake runtime | 只在 adapter 最外层知道 driver；关闭幂等 |
| `src/drawing_graph/qa_mcp_server.py` | 创建无 import 副作用的 MCP server，声明 server instructions、工具和只读 annotations | 工具编排委托给 `qa_mcp_tools.py` |
| `scripts/serve_drawing_graph_mcp.py` | STDIO 启动入口，从环境变量装配 runtime 并启动 server | 不接受 secret 命令行参数，不输出协议外 stdout 文本 |
| `tests/test_qa_mcp_models.py` | 验证输入白名单、scope、序列化和事实分层 | 不连接 Neo4j |
| `tests/test_qa_mcp_tools.py` | 验证工具到 QARequest 的一一映射、只读和错误转换 | 使用 fake QAService |
| `tests/test_qa_mcp_runtime.py` | 验证创建顺序、失败清理、幂等关闭 | 使用 fake driver |
| `tests/test_qa_mcp_server.py` | 验证 initialize、instructions、tools/list、tools/call、structured output 和 annotations | 优先使用 SDK in-memory 测试能力 |
| `tests/test_qa_mcp_cli.py` | 验证 STDIO 入口 import 无副作用、stdout 协议纯净、stderr 脱敏和退出码 | 不连接真实 Neo4j |
| `tests/test_qa_mcp_docs.py` | 保护 MCP/Skill 当前能力、未实现范围和路径兼容边界 | 静态文档测试 |

模块是否完全拆分可在后续 design 阶段按职责大小确认，但至少要保持三条边界：

1. 工具 Schema 与业务编排分离。
2. MCP server/transport 与 Neo4j runtime 分离。
3. MCP 工具只依赖 QAService，不直接依赖 HTTP 或底层图谱模块。

### 2.2 推荐的 MCP 工具集合

第一版推荐五个显式只读工具：

| MCP 工具 | QA 问题类型 | 最小输入 | 说明 |
|---|---|---|---|
| `ask_drawing_page` | `page_summary` | `page_id` | 页面来源事实和可选语义证据摘要 |
| `ask_drawing_block` | `block_relations` | `block_id` | 图块追溯、正式派生关系和候选关系 |
| `list_drawing_candidates` | `candidate_relations` | `page_id` 或 `block_id` | 只返回候选，不允许提升 |
| `get_section_match_status` | `section_matches` | `cross_section_id` 或 `page_id` | 查询现有候选/正式匹配；不触发写回 |
| `get_drawing_diagnostics` | `diagnostic_status` | `page_id` 或 `block_id` | 导入、增强、语义证据和未验证状态 |

`table_caption_status` 可通过通用受控工具纳入，也可以作为第六个工具 `get_table_caption_status`。考虑当前 QAService 对该能力可能返回 `partial + unsupported_parts`，建议保留独立工具，但工具描述必须明确“可能只能确认来源元素存在，派生状态能力不足时返回部分回答”。

不建议第一版只暴露一个过于通用的 `ask_drawing_graph(question_type, scope)`。虽然工具数少，但 Agent 更难选择正确 scope，工具描述也更难表达各问题的证据和限制。可将通用工具作为内部调度函数，不作为首批外部工具。

### 2.3 Skill 强化模块

| 建议位置 | 职责 |
|---|---|
| `drawing-graph-operator/SKILL.md` | 更新入口选择顺序：优先 MCP QA 工具，MCP 不可用时按受控规则降级到 QA CLI/facade CLI |
| `drawing-graph-operator/references/qa-workflows.md` | 自然语言问题到 MCP 工具/`QuestionType`/scope 的映射；多问题拆分与调用顺序 |
| `drawing-graph-operator/references/mcp-boundaries.md` | MCP 工具清单、只读边界、错误/超时/不可用降级、禁止直接访问底层模块 |
| `drawing-graph-operator/references/output-contract.md` | 补充 MCP `structuredContent` 与文本摘要必须保持相同事实分层 |
| `drawing-graph-operator/references/verification.md` | 补充 MCP 合约、STDIO smoke、Skill 发现和 live Neo4j 四类独立验证状态 |
| `drawing-graph-operator/agents/openai.yaml` | 在兼容性验证后声明 MCP tool dependency，使 Skill 与 MCP 能力协同发现 |

Skill 仍应优先采用 instructions/references，不增加会复制业务逻辑的脚本。确定性的协议与数据库连接逻辑属于 MCP adapter，而不属于 Skill scripts。

### 2.4 Skill 路径处理建议

当前 `.codex/skills/drawing-graph-operator` **不是鸡肋，也不能直接删除**：

- 当前会话已经发现并使用该 Skill，证明它在当前宿主和项目配置下有效。
- 它包含当前项目特有的安全规则、输出契约和验证边界，MCP server instructions 无法完整替代这些渐进披露资料。
- OpenAI 当前官方文档把仓库级 Skill 标准位置写为 `.agents/skills`，并说明同名 Skill 不会自动合并。因此直接复制会造成重复发现，直接删除又可能破坏当前环境。

推荐迁移策略：

1. 第三阶段 design 先把 `.agents/skills/drawing-graph-operator` 设为未来规范位置，但不在分析阶段修改。
2. 实施时先在隔离分支移动而不是复制，确保仓库内只有一个同名 Skill 权威来源。
3. 分别验证桌面端、Codex CLI/IDE（如项目实际使用）能发现并显式调用 Skill。
4. 运行 Skill 静态测试、frontmatter 校验、触发/不触发提示集和 MCP 依赖发现测试。
5. 验证通过后更新文档并移除旧路径；验证失败则保留 `.codex/skills`，把路径迁移列为兼容性待办。

第三阶段功能分析不应预先断言 `.codex/skills` 已废弃，也不建议长期维护两个同名副本。

## 3. 影响哪些已有模块

### 3.1 直接影响

| 已有模块 | 影响程度 | 原因 |
|---|---:|---|
| `requirements.txt` | 中 | 新增受控 MCP Python SDK 依赖；需避免与现有 FastAPI/Pydantic/Uvicorn 版本冲突 |
| `src/drawing_graph/qa_serialization.py` | 低到中 | MCP structured result 可复用 JSON 转换和脱敏；如需 MCP 专用 envelope，应在 MCP 模块中实现而不是污染 HTTP 合同 |
| `src/drawing_graph/config.py` | 低到中 | 可新增窄口径 MCP runtime 配置；STDIO 首版只需 Neo4j 和服务级限制，不需要 HTTP host/CORS |
| `.codex/skills/drawing-graph-operator/` 或经验证后的 `.agents/skills/...` | 高 | 新增 QA/MCP 工作流、工具依赖与验证规则 |
| `tests/test_skill_docs.py` | 高 | 需更新必需文件、路径和 MCP 工作流断言 |
| `README.md` | 中 | 增加 MCP 配置、Skill 使用、只读工具和验证说明 |
| `Module.md` | 中 | 记录 MCP 模块职责、工具合同、Skill/MCP 分工和路径状态 |
| `architecture.md` | 中 | 将 MCP adapter 标为已实现；保留写回、远程 MCP 等未实现边界 |

### 3.2 间接依赖但原则上不修改

| 模块 | 影响 | 原则 |
|---|---|---|
| `qa_models.py` | MCP 输入转换和输出序列化使用 | 不加入 MCP SDK 类型或传输语义 |
| `qa_service.py` | 所有 MCP 工具的唯一业务入口 | 不加入 tool name、transport、stdio 或 MCP context |
| `qa_http.py` / `qa_http_models.py` | 与 MCP 同级，可能共享 QA DTO/serializer | MCP 不转调 HTTP，不把 MCP route 挂入 HTTP 业务函数 |
| `qa_http_runtime.py` | 可借鉴生命周期模式 | 不强行共用包含 HTTP 语义的 runtime 类型 |
| `tool_facade.py` | 被 QAService 间接调用 | 不为 MCP 暴露额外写回入口 |
| `tool_factory.py` | MCP runtime 使用生产 facade 工厂 | 当前接口已足够，原则上不改 |
| `query_service.py` / repositories | 无直接影响 | MCP 不得直接依赖 |
| `scripts/create_schema.cypher` | 无影响 | 第三阶段不改变数据模型 |

### 3.3 现有测试影响

- 第一、二阶段 QA/CLI/HTTP 测试必须保持通过。
- 当前 `test_skill_docs.py` 绑定 `.codex/skills` 路径。若后续设计批准迁移到 `.agents/skills`，必须先改测试再移动资产，并验证不是双副本。
- 文档测试中“未实现 MCP”的断言需要在第三阶段实现后改为保护真实边界，不能在分析报告阶段提前改动。
- live Neo4j 集成测试仍然独立；MCP in-memory/STDIO 测试不能代替真实数据库验证。

## 4. 技术方案

### 4.1 方案 A：独立 STDIO MCP server + Skill 强化（推荐）

```text
Codex
  -> 启动本地 STDIO MCP 子进程
      -> MCP tool registry
          -> DrawingGraphQAService
              -> DrawingGraphToolFacade
```

要点：

- MCP server import 无副作用，STDIO main 才读取环境变量、创建 driver 和启动协议循环。
- stdout 只用于 MCP 协议；诊断日志写 stderr，且必须脱敏。
- MCP 工具使用窄口径输入 Schema 和结构化输出 Schema。
- 首批工具全部 `readOnlyHint=true`、`destructiveHint=false`、`openWorldHint=false`；这些 annotation 只是客户端提示，服务端仍强制只读。
- Skill 的 `qa-workflows.md` 决定自然语言问题使用哪个工具，并按输出契约解释结果。
- 可通过项目级 Codex MCP 配置声明 command、args、cwd 和允许转发的环境变量；不把真实密码写进仓库。

适用：当前本机 Windows/Codex 使用场景，以及第三阶段最小、安全、可验证交付。

### 4.2 方案 B：Streamable HTTP MCP 挂载到现有 ASGI 服务

```text
Codex / remote Agent
  -> Streamable HTTP MCP
      -> shared ASGI host / runtime
          -> DrawingGraphQAService
```

优点：

- 可被远程客户端或多个本地客户端复用。
- 可利用现有 Uvicorn、loopback、token、并发和超时经验。
- MCP Python SDK 官方支持把 Streamable HTTP ASGI app 挂到现有 FastAPI/Starlette 服务。

缺点：

- MCP session manager 与现有 FastAPI lifespan 的组合更复杂。
- 认证模型不应简单沿用当前静态 token 后就声称满足远程生产安全。
- 网络暴露、OAuth/授权、反向代理、TLS、会话状态和并发模型会显著扩大范围。
- 当前进程内 run log、payload store 和 cache 仍不适合多 worker 一致性。

适用：明确需要远程 Agent、ChatGPT hosted plugin 或多客户端共享时的后续阶段，不建议作为本次首版默认传输。

### 4.3 方案 C：MCP server 转调第二阶段 HTTP API

```text
MCP client -> MCP adapter -> REST HTTP adapter -> QAService -> facade
```

优点：

- 可复用现有 HTTP 部署。
- MCP 进程本身不持有 Neo4j driver。

缺点：

- 形成 adapter 调 adapter，违背既有“CLI/HTTP/MCP 同级”的设计。
- 重复请求模型、序列化、错误 envelope、认证、超时、并发和健康状态。
- MCP structured content 可能被 REST envelope 二次包装。
- HTTP 不可用时 MCP 即不可用，故障定位更复杂。
- Skill、MCP、HTTP 三层都可能尝试解释同一错误或部分回答。

适用：只有在组织级网络隔离要求 MCP 进程不能直接持有数据库连接、且 HTTP 已是唯一受控服务边界时才考虑。当前项目没有该约束，因此不推荐。

### 4.4 方案 D：只强化 Skill，不实现 MCP

优点：工作量小，可继续调用 QA CLI/HTTP。

缺点：没有标准工具发现和 Schema；外部 Agent 仍依赖命令文本或自定义 HTTP；不能满足已确认的第三阶段 MCP 目标。

该方案可作为 MCP 被环境阻断时的降级交付，但不能视为第三阶段完整完成。

## 5. 优缺点比较

| 维度 | 方案 A：STDIO MCP | 方案 B：Streamable HTTP MCP | 方案 C：MCP 转 REST | 方案 D：仅 Skill |
|---|---|---|---|---|
| 与当前本机场景匹配 | **高** | 中 | 中 | 高 |
| 保持 adapter 同级 | **是** | 是 | 否 | 不涉及 MCP |
| 默认网络暴露 | **无** | 有 | REST 服务已有 | 无 |
| 复用 QAService | **直接复用** | 直接复用 | 间接复用 | 通过 CLI/HTTP |
| 生命周期复杂度 | 中 | 高 | 中 | 低 |
| 认证复杂度 | 低 | 高 | 中到高 | 低 |
| MCP 标准工具发现 | 是 | 是 | 是 | 否 |
| 远程 Agent 支持 | 否 | **是** | 取决于 REST/MCP 部署 | 否 |
| 故障链长度 | **短** | 中 | 长 | 中 |
| 当前推荐度 | **最高** | 后续可选 | 不推荐 | 不完整 |

## 6. 推荐方案

### 6.1 推荐总体方案

采用“**独立 STDIO MCP server + 传输无关工具注册层 + Skill 强化**”。

架构原则：

1. MCP 工具只调用 `DrawingGraphQAService.ask()`。
2. MCP 与 HTTP/CLI 同级，不调用 HTTP endpoint 或 CLI 子进程。
3. MCP 输入、输出与 transport 解耦，为以后增加 Streamable HTTP 保留空间。
4. 第一版所有外部 MCP 工具只读；工具 annotation 与服务端强制校验双重保护。
5. Skill 负责自然语言映射、工具选择、组合调用、降级和结果解释；不复制业务代码。
6. `.codex/skills` 当前仍保留；标准路径迁移作为带验证门槛的兼容性任务，而不是无条件删除。

### 6.2 推荐调用顺序

```text
用户问题
  -> drawing-graph-operator Skill 判断问题类型与 scope
  -> MCP 可用：调用对应窄口径 MCP 工具
  -> MCP 不可用：明确报告后，按 Skill 规则降级到 QA CLI
  -> QAAnswer / MCP structuredContent
  -> 按 fact_kind 分层解释
  -> 明确 warnings / unsupported_parts / verification status
```

不建议静默降级：若 MCP 初始化失败、工具缺失或超时，Skill 应明确说明使用了何种后备入口，避免用户误以为已验证 MCP 链路。

### 6.3 推荐 MCP 输出

每次工具调用同时提供：

- `structuredContent`：保持 QAAnswer 的完整结构，供 Agent 和程序消费。
- 简短文本摘要：只概述状态、summary、warning 数量和 unsupported 数量，不复制大段证据。
- 错误结果：稳定 category、脱敏 message、retryable 和安全 scope 字段名。

不得在 MCP mapper 中重新判定候选/正式关系。`candidate_relation`、`semantic_observation`、`semantic_interpretation` 和 `formal_relation` 必须沿用 QAAnswer。

### 6.4 推荐 Skill 定位

第三阶段后，Skill 的定位应从“主要指导 facade CLI”升级为“图块图谱 Agent 操作策略层”：

- 决定何时用 page/block/candidate/section/table/diagnostic 工具。
- 对缺失 ID、scope 冲突和 unsupported 问题进行保守处理。
- 规定 MCP、QA CLI 和底层 facade CLI 的优先级与降级规则。
- 强制事实分层和证据字段保留。
- 强制区分单元测试、MCP smoke、集成测试跳过和 live Neo4j 验证。

它不是 MCP server，不替代 MCP Schema，也不应包含真实数据和密钥。

### 6.5 不包含范围

第三阶段首版不包含：

- 不提供写回型 MCP tool。
- 不提供来源事实导入、离线增强、候选复核或关系提升工具。
- 不暴露任意 Cypher、repository、driver、session 或 transaction。
- 不让 MCP 调用 HTTP API 或 CLI 子进程。
- 不默认实现 Streamable HTTP、远程部署、OAuth、TLS、反向代理或 hosted plugin。
- 不把 Skill 打包为可发布 plugin；可在本地验证成熟后单独立项。
- 不实现 Ava 专有 adapter。
- 不接入真实云多模态供应商，不做 OCR、全量语义扫描、文件 watcher 或任务队列。
- 不修改 Neo4j Schema、节点、关系、约束或索引。
- 不自动迁移或删除 `.codex/skills`；路径迁移必须先验证。

## 7. 风险

### 7.1 高风险

| 风险 | 后果 | 缓解措施 |
|---|---|---|
| MCP 工具绕过 QAService/facade | 产生第二套查询/写回入口，破坏事实分层 | 静态依赖测试；工具只接收注入的 QAService；禁止导入 QueryService/Repository/Cypher |
| 误开放写回工具 | Agent 可持久化语义证据或提升候选关系 | 首版不注册写回工具；QARequest 固定 `write_back=false`；annotation 与服务端校验并用 |
| candidate 被输出为 formal | 产生错误工程结论 | 复用 QAAnswer；Schema/合约测试固定 fact_kind；Skill 输出契约强制保守表达 |
| STDIO stdout 被日志污染 | MCP 握手和调用协议损坏 | stdout 只写协议；日志仅 stderr；启动测试校验无额外输出 |
| Skill 双路径重复发现 | 同名 Skill 重复、触发不确定、维护漂移 | 迁移使用移动而非复制；验证后只保留一个权威路径 |
| 未验证就删除 `.codex/skills` | 当前环境失去项目操作规则 | 保留现状，先做新路径发现/触发/MCP 依赖验证再迁移 |

### 7.2 中风险

| 风险 | 后果 | 缓解措施 |
|---|---|---|
| MCP SDK 与 FastAPI/Pydantic 依赖冲突 | 第二阶段 HTTP 回归失败 | 先做依赖兼容矩阵和导入测试；声明受控版本范围；运行全量回归 |
| 工具颗粒度过粗 | Agent 传错 scope、工具说明难理解 | 暴露 5-6 个窄口径 QA 工具，内部共享统一 handler |
| 工具颗粒度过细 | 工具选择上下文膨胀、维护成本高 | 不暴露全部 facade 方法，只暴露稳定 QA 意图 |
| MCP instructions 与 Skill 重复或冲突 | Agent 收到两套不同规则 | server instructions 只放跨工具关键边界；完整流程以 Skill references 为权威；增加一致性测试 |
| STDIO 子进程继承敏感环境 | 凭据可能被不必要地传递 | Codex 配置只允许转发所需环境变量名；不把值写入仓库或日志 |
| 连接初始化或关闭失败 | MCP 启动失败、driver 泄漏 | runtime 工厂可注入、部分失败清理、close 幂等、进程退出测试 |
| 只依赖 annotation 判断安全 | 不可信客户端或实现错误仍可触发副作用 | annotation 只作提示；QAService/facade 强制只读才是权威边界 |

### 7.3 低到中风险

| 风险 | 后果 | 缓解措施 |
|---|---|---|
| MCP 协议/SDK版本演进 | Schema、transport 或测试接口变化 | 使用官方 SDK、受控版本范围、合约测试；不要依赖私有 API |
| Skill description 过长 | 初始发现被截断或触发不准 | 前置关键触发词与边界，细节放 references，遵循渐进披露 |
| MCP 文本摘要与 structuredContent 不一致 | Agent 或用户看到矛盾结论 | 文本摘要从同一 QAAnswer 生成，不独立分类事实 |
| table caption 仍是 partial | 用户误以为 MCP 能补齐底层缺口 | 工具描述明确能力边界，原样返回 unsupported parts |
| MCP smoke 被误写成 live Neo4j 通过 | 验收状态失真 | 四层报告：单元、MCP in-memory/STDIO、HTTP 回归、live Neo4j；skipped 不等于 passed |

## 8. 验证与验收建议

第三阶段实现后应分别报告：

1. **MCP 单元/合约测试**：输入 Schema、tools/list、tools/call、structuredContent、只读 annotation、错误脱敏。
2. **STDIO smoke test**：真实启动子进程，完成 initialize、工具发现、一次 fake QA 调用和正常关闭；不连接真实 Neo4j。
3. **Skill 验证**：结构/frontmatter、路径发现、显式与隐式触发、MCP 工具依赖、问题路由和事实分层提示集。
4. **全量单元回归**：第一、二阶段 QA/CLI/HTTP 和现有项目测试继续通过。
5. **live Neo4j 集成测试**：仅在 disposable 测试库变量已配置并实际运行通过时标记为 live verified。

最低验收标准：

- MCP 模块 import 无副作用，不读取环境变量、不创建 driver。
- MCP server 能被客户端初始化并发现预期工具。
- 所有外部工具只调用 `DrawingGraphQAService.ask()`，不调用 HTTP、CLI、facade 单项方法或底层 repository。
- 所有工具默认且强制只读；不存在写回、导入、增强、复核或提升工具。
- 工具输入不接受 Neo4j 凭据、Cypher、driver、session、transaction 或 repository 参数。
- structuredContent 保留 QAAnswer 完整事实分层和证据字段。
- server instructions 与 Skill 共同声明候选不是正式事实、`write_back=false` 和验证边界。
- STDIO stdout 不包含日志或非协议文本，stderr 不泄露 secret。
- Skill 在最终权威路径上只能发现一个同名版本。
- HTTP 第二阶段测试与 QA CLI 回归继续通过。
- 集成测试跳过时明确记录“live Neo4j 未验证”。

## 9. 外部技术依据

- [OpenAI Codex MCP documentation](https://developers.openai.com/codex/mcp)：Codex 当前支持本地 STDIO 和 Streamable HTTP MCP server；MCP server 可提供跨工具 instructions；项目可在受信任仓库的 `.codex/config.toml` 中配置 MCP。
- [OpenAI Codex Skill documentation](https://developers.openai.com/codex/skills)：Skill 由 `SKILL.md`、可选 references/scripts/assets 和 `agents/openai.yaml` 组成；当前仓库级标准发现位置为 `.agents/skills`；`agents/openai.yaml` 可声明 MCP tool dependency；同名 Skill 不会合并。
- [MCP specification schema](https://modelcontextprotocol.io/specification/2025-11-25/schema)：MCP tool 支持输入/输出 Schema 和 `readOnlyHint`、`destructiveHint`、`idempotentHint`、`openWorldHint` annotations；annotations 是提示而不是安全保证。
- [MCP Python SDK server documentation](https://py.sdk.modelcontextprotocol.io/server/)：官方 Python SDK 支持 STDIO 与 Streamable HTTP server，并提供工具注册和 ASGI 集成能力。
- [MCP Python SDK testing documentation](https://py.sdk.modelcontextprotocol.io/testing/)：可使用内存连接的 server/client session 进行协议级测试。

## 10. 最终推荐

当前架构支持 Tool 层第三阶段，不需要重写 QAService、Tool facade、HTTP API 或 Neo4j 数据模型。推荐把第三阶段定义为两个协同交付物：

1. 一个独立、本机优先、默认只读的 STDIO MCP adapter，直接包装 `DrawingGraphQAService` 的少量稳定问题类型。
2. 对 `drawing-graph-operator` Skill 的 QA/MCP 工作流强化，使 Agent 能正确选择工具、保守解释结果并在 MCP 不可用时透明降级。

现有 `.codex/skills/drawing-graph-operator` 不是鸡肋：它仍是当前环境已生效的项目操作策略层。真正的问题是路径标准正在演进。第三阶段应把迁移到 `.agents/skills` 作为“先验证、再移动、只保留单一权威副本”的兼容性工作，而不是直接删除旧目录或长期维护双副本。

在该方案下，MCP 提供能力，Skill 提供判断与纪律，QAService 提供统一业务编排，DrawingGraphToolFacade 继续守住图谱边界。四者职责互补，不重复实现业务逻辑。
