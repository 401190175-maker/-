# Tool 层第三阶段 MCP 与 Skill 强化提案

## 1. 背景

当前图块图谱项目已经完成 Tool 层前两个阶段。

第一阶段建立了 facade 外侧的问答编排能力：

- `DrawingGraphQAService` 作为统一 QA 入口，负责问题类型路由、scope 校验、证据聚合和结构化回答。
- `QARequest`、`QAScope`、`QAAnswer`、`AnswerFact`、`EvidenceRef` 和 `QAErrorCode` 已形成稳定领域契约。
- `scripts/drawing_graph_qa.py` 已提供默认只读的 QA CLI。
- QA 输出已经区分 `source_fact`、`derived_relation`、`semantic_observation`、`semantic_interpretation`、`candidate_relation`、`formal_relation`、`diagnostic` 和 `unsupported`。

第二阶段建立了版本化、默认本机监听、默认只读的 HTTP adapter：

- HTTP route 只构造 `QARequest` 并调用 `DrawingGraphQAService.ask()`。
- driver、`DrawingGraphToolFacade` 和 QAService 的长生命周期装配与关闭已经形成独立 runtime。
- CLI 与 HTTP 已共用框架无关 JSON 序列化和错误脱敏能力。
- HTTP 已明确 loopback、单 worker、只读、请求限制、并发、超时、认证和健康检查边界。

当前稳定依赖方向为：

```text
QA CLI / HTTP adapter
  -> DrawingGraphQAService
      -> DrawingGraphToolFacade
          -> ports / services
              -> controlled repository / Neo4j
```

项目同时已有 `.codex/skills/drawing-graph-operator/`。该 Skill 负责指导 Codex 在行动前读取当前文档和受影响源码，只通过受控 facade/CLI 使用图谱能力，默认 `write_back=false`，并区分来源事实、派生关系、语义证据、候选关系和正式关系。它是操作策略层，不是业务服务或机器协议。

当前还缺少标准 MCP Tool adapter。Codex 或其他支持 MCP 的 Agent 尚不能通过标准工具发现、输入 Schema 和结构化结果直接调用图块图谱 QA 能力；现有 Skill 也尚未包含自然语言问题到 MCP/QA 工具的完整映射、MCP 不可用时的透明降级和 MCP 验证规则。

Tool 层第三阶段因此同时包含两个互补目标：

1. 新增本机优先、默认只读的 STDIO MCP Tool adapter。
2. 强化现有 `drawing-graph-operator` Skill，使其成为 MCP/QA 工具外侧的操作策略和结果解释层。

推荐目标架构：

```text
Codex Skill / external Agent
  -> MCP client
      -> STDIO MCP adapter
          -> DrawingGraphQAService
              -> DrawingGraphToolFacade
                  -> ports / services
                      -> controlled repository / Neo4j
```

CLI、HTTP 和 MCP 是同级 adapter，不互相调用；Skill 负责选择、组合、降级和解释，不承载图谱业务逻辑。

## 2. 当前问题

当前业务层已经具备第三阶段所需的大部分能力，但协议层、Skill 工作流和兼容性验证仍存在以下问题。

1. **缺少标准 MCP 工具入口。** 当前只有 Python、CLI 和 REST/JSON 调用方式，没有 MCP initialization、`tools/list`、`tools/call`、输入/输出 Schema 和 server instructions。
2. **现有 HTTP API 不能替代 MCP。** HTTP API 是面向普通客户端的版本化 REST adapter，不提供 MCP 工具发现、工具 annotations 或 MCP structured content。让 MCP 转调 HTTP 会形成 adapter 调 adapter，重复认证、错误映射、序列化、并发和超时逻辑。
3. **现有 Skill 不能替代 MCP。** Skill 只能提供操作指令和渐进披露资料，不能向 Agent 提供标准机器接口、工具 Schema 或运行时资源生命周期。
4. **MCP 与 Skill 的职责尚未形成正式合同。** 缺少“Skill 决策，MCP 执行，QAService 编排，facade 守边界”的明确依赖方向和一致性测试。
5. **自然语言到 QA 能力的映射不完整。** 当前 Skill 主要记录 facade CLI 工作流，没有系统描述页面摘要、图块关系、候选关系、断面匹配、表格标题状态和诊断状态分别使用哪个 QA/MCP 工具、需要哪些 ID、何时返回 partial 或 unsupported。
6. **缺少 MCP 结构化输出合同。** `QAAnswer` 已经稳定，但尚未定义如何映射到 MCP `structuredContent`、简短文本摘要和 tool error，同时保持事实类型、证据字段、warnings 和 unsupported parts 不丢失。
7. **缺少 MCP 强制只读边界。** 第三阶段必须同时使用只读 tool annotations 和 QAService/facade 的服务端校验；只依赖 annotation 不能阻止错误实现或不可信客户端触发副作用。
8. **缺少 STDIO 协议运行边界。** 还没有规定 MCP server import 无副作用、stdout 只写协议、日志只写 stderr、敏感信息脱敏，以及启动失败和关闭时如何释放 driver。
9. **缺少 MCP 专项验证。** 当前测试不能证明 initialize、工具发现、工具调用、structured output、STDIO 子进程和正常关闭可用；HTTP TestClient 或 HTTP socket smoke 不能替代 MCP 验证。
10. **Skill 路径存在兼容性风险。** 当前 `.codex/skills/drawing-graph-operator` 已被本项目当前 Codex 环境实际发现和使用，但 OpenAI 当前文档把仓库级 Skill 的标准位置写为 `.agents/skills`。直接删除可能破坏当前环境，直接复制又可能造成同名 Skill 重复发现和内容漂移。
11. **依赖兼容性尚未验证。** 新增 MCP Python SDK 后，需要确认其 Pydantic、Starlette、Uvicorn、HTTPX 等依赖与第二阶段 HTTP 技术栈兼容。
12. **验证状态容易被混淆。** MCP in-memory 测试、STDIO smoke、HTTP 回归、集成测试跳过和 live Neo4j 验证是不同证据，不能互相替代。

## 3. 功能目标

本变更目标是在不重写 QAService、不改变 Tool facade、不修改 Neo4j Schema、不开启写回的前提下，提供标准 MCP 只读工具，并让现有 Skill 能稳定指导 Agent 使用这些工具。

### 3.1 MCP adapter 目标

1. 新增无 import 副作用的 MCP server 工厂和 STDIO 启动入口。
2. MCP server 通过独立 runtime 创建并关闭 Neo4j driver、`DrawingGraphToolFacade` 和 `DrawingGraphQAService`。
3. 所有 MCP 业务工具只把受控参数转换为 `QARequest`，然后调用一次 `DrawingGraphQAService.ask()`。
4. 首批提供六个窄口径只读工具：
   - `ask_drawing_page`：映射 `page_summary`。
   - `ask_drawing_block`：映射 `block_relations`。
   - `list_drawing_candidates`：映射 `candidate_relations`。
   - `get_section_match_status`：映射 `section_matches`。
   - `get_table_caption_status`：映射 `table_caption_status`。
   - `get_drawing_diagnostics`：映射 `diagnostic_status`。
5. 每个工具使用明确输入 Schema、稳定结构化输出 Schema 和最小必要描述，不暴露数据库内部 ID 或底层对象。
6. 工具输出保留 `QAAnswer` 的完整事实分层、证据、warnings、unsupported parts 和 source calls。
7. 每个工具同时返回机器可消费的 `structuredContent` 和由同一 `QAAnswer` 生成的简短文本摘要，不在 mapper 中重新分类事实。
8. 所有外部工具标注只读、非破坏、闭域；annotation 只作为提示，真正只读由固定 `write_back=false` 和 QAService/facade 校验保证。
9. server instructions 在最前部明确：默认只读、候选不是正式事实、模型证据不覆盖来源事实、禁止任意 Cypher、验证状态必须如实报告。
10. STDIO stdout 只承载 MCP 协议；诊断日志进入 stderr，并经过共享脱敏。
11. MCP runtime 初始化任一步失败时关闭已创建的 driver；正常退出和重复关闭保持幂等。
12. MCP 工具、server 和 runtime 均可注入 fake service/driver，以便在不连接真实 Neo4j 的情况下测试。

### 3.2 Skill 强化目标

1. 更新 `drawing-graph-operator` 的入口选择规则，优先使用已配置的 MCP QA 工具。
2. 新增自然语言问题到 MCP 工具、`QuestionType` 和 `QAScope` 的映射说明。
3. 规定多问题拆分、多个工具组合、缺少 ID、scope 冲突、not found、partial 和 unsupported 的保守处理方式。
4. 规定 MCP 不可用、工具缺失、初始化失败或超时时的透明降级：明确说明后再按受控规则使用 QA CLI；不得静默切换并冒充 MCP 已验证。
5. 强化输出契约，确保 MCP structured content 和最终中文回答都区分来源事实、派生关系、语义观察、语义解释、候选关系和正式关系。
6. 强化验证规则，分别报告 MCP 单元/合约测试、STDIO smoke、Skill 发现/触发测试、全量回归和 live Neo4j 集成测试。
7. 在兼容性验证通过后，通过 `agents/openai.yaml` 声明 MCP 工具依赖，提高 Skill 与工具协同发现的稳定性。
8. 保持 Skill 为 instructions/references 为主的操作层，不加入重复业务逻辑、真实数据、密钥或数据库连接脚本。

### 3.3 Skill 路径兼容目标

1. 不在未经验证的情况下删除当前有效的 `.codex/skills/drawing-graph-operator`。
2. 不长期保留 `.codex/skills` 和 `.agents/skills` 下两个同名、独立维护的副本。
3. 后续 design/实施将 `.agents/skills/drawing-graph-operator` 作为目标标准位置，但采用“先验证、再移动、只保留一个权威副本”的迁移策略。
4. 分别验证项目实际使用的 Codex 桌面端、CLI/IDE 是否能发现、显式调用并正确触发目标路径下的 Skill。
5. 若目标路径验证失败，保留当前 `.codex/skills`，将迁移记录为兼容性待办，不影响 MCP 核心交付。

### 3.4 完成后的稳定依赖方向

```text
drawing-graph-operator Skill
  -> 选择 MCP 工具 / 解释结果 / 必要时透明降级

STDIO MCP adapter
  -> DrawingGraphQAService.ask()
      -> DrawingGraphToolFacade
          -> ports / services
              -> controlled repository / Neo4j
```

禁止依赖方向：

```text
MCP tool -> HTTP API / QA CLI 子进程
MCP tool -> DrawingGraphToolFacade 单项方法
MCP tool -> QueryService / RelationRepository / Neo4j session / Cypher
Skill -> Neo4j driver / repository 写回方法 / 任意 Cypher
```

## 4. 修改范围

### 4.1 新增 MCP 模块

| 类型 | 文件或位置 | 修改内容 |
|---|---|---|
| 新增 | `src/drawing_graph/qa_mcp_models.py` | 定义六类 MCP 工具输入模型、结果模型、安全错误模型，以及到现有 `QARequest`/`QAScope` 的转换 |
| 新增 | `src/drawing_graph/qa_mcp_tools.py` | 注册六个只读工具，统一调用注入的 `DrawingGraphQAService.ask()`，生成 structured content 和简短摘要 |
| 新增 | `src/drawing_graph/qa_mcp_runtime.py` | 管理 driver、facade、QAService 的创建、复用、失败清理和幂等关闭 |
| 新增 | `src/drawing_graph/qa_mcp_server.py` | 创建无 import 副作用的 MCP server，配置 server instructions、工具 Schema、输出 Schema 和只读 annotations |
| 新增 | `scripts/serve_drawing_graph_mcp.py` | 本机 STDIO 启动入口；只在 main 中读取环境变量并启动协议循环，stdout 不输出协议外内容 |

模块是否需要进一步合并或拆分，由后续 design 按 SDK 的稳定接口和职责大小确认；不得把 Schema、工具调用、runtime、STDIO main 和业务编排全部堆入一个文件。

### 4.2 新增测试

| 类型 | 文件或位置 | 修改内容 |
|---|---|---|
| 新增 | `tests/test_qa_mcp_models.py` | 覆盖输入白名单、scope、布尔字段、ID 约束、领域转换、输出事实分层和敏感字段拒绝 |
| 新增 | `tests/test_qa_mcp_tools.py` | 覆盖六个工具到 QARequest 的一一映射、只调用一次 QAService、partial/not found/unsupported 和错误脱敏 |
| 新增 | `tests/test_qa_mcp_runtime.py` | 覆盖 runtime 创建顺序、依赖注入、初始化失败清理、正常关闭和幂等 close |
| 新增 | `tests/test_qa_mcp_server.py` | 覆盖 initialize、server instructions、tools/list、tools/call、structuredContent、输出 Schema 和 tool annotations |
| 新增 | `tests/test_qa_mcp_cli.py` | 覆盖启动脚本 import 无副作用、STDIO stdout 协议纯净、stderr 脱敏、配置失败和正常关闭 |
| 新增 | `tests/test_qa_mcp_docs.py` | 保护 MCP/Skill 分工、只读边界、STDIO 首版、远程 MCP 未实现和验证状态 |
| 新增或修改 | Skill 行为测试 | 覆盖目标路径发现、显式/隐式触发、自然语言路由、MCP 依赖与透明降级 |

### 4.3 修改已有模块

| 类型 | 文件或位置 | 修改内容 |
|---|---|---|
| 修改 | `requirements.txt` | 新增受控 MCP Python SDK 版本范围，并验证与 FastAPI、Pydantic、Starlette、Uvicorn、HTTPX 和 Neo4j driver 兼容 |
| 修改 | `src/drawing_graph/config.py` | 如确有需要，新增窄口径 MCP runtime 配置；不复用 HTTP host/CORS/docs 配置，不扩大 ImportConfig |
| 修改 | `src/drawing_graph/qa_serialization.py` | 仅复用或补充 MCP 所需的框架无关 JSON/脱敏能力；不改变现有 CLI/HTTP envelope 合同 |
| 修改 | `tests/test_skill_docs.py` | 更新 Skill 必需文件、MCP 工作流、事实分层、密钥和真实数据禁止项；路径迁移时同步权威路径 |
| 修改 | `README.md` | 增加 MCP 依赖安装、STDIO 配置、工具清单、Skill 使用、只读边界和验证说明 |
| 修改 | `Module.md` | 记录 MCP models/tools/runtime/server/CLI 职责、Skill/MCP 分工和当前 Skill 权威路径 |
| 修改 | `architecture.md` | 将 MCP adapter 加入当前同级 adapter 调用链，继续保留远程 MCP、写回和其他后续范围 |

### 4.4 Skill 资产修改

| 类型 | 文件或位置 | 修改内容 |
|---|---|---|
| 修改 | `drawing-graph-operator/SKILL.md` | 加入 MCP 优先、QA CLI 透明降级、只读和事实分层入口规则 |
| 新增 | `drawing-graph-operator/references/qa-workflows.md` | 定义自然语言问题到六类 MCP 工具/QA 问题类型/scope 的映射和组合流程 |
| 新增 | `drawing-graph-operator/references/mcp-boundaries.md` | 定义工具清单、只读边界、server/tool 错误、超时、不可用和降级规则 |
| 修改 | `drawing-graph-operator/references/output-contract.md` | 增加 structuredContent、文本摘要和最终回答的一致性规则 |
| 修改 | `drawing-graph-operator/references/verification.md` | 增加 MCP 合约、STDIO smoke、Skill 发现/触发和 live Neo4j 分层验证 |
| 修改 | `drawing-graph-operator/agents/openai.yaml` | 在宿主兼容性验证后声明 MCP 工具依赖；不嵌入凭据或真实连接值 |

上述 `drawing-graph-operator` 的最终根路径由 design 和迁移验证决定。实施过程不得在 `.codex/skills` 与 `.agents/skills` 长期维护两个同名副本。

### 4.5 原则上不修改

以下领域和底层模块当前没有第三阶段设计缺口，原则上不修改：

- `src/drawing_graph/qa_models.py`
- `src/drawing_graph/qa_service.py`
- `src/drawing_graph/qa_rendering.py`
- `src/drawing_graph/qa_http.py`
- `src/drawing_graph/qa_http_models.py`
- `src/drawing_graph/qa_http_runtime.py`
- `scripts/serve_drawing_graph_qa.py`
- `src/drawing_graph/tool_facade.py`
- `src/drawing_graph/tool_factory.py`
- `src/drawing_graph/query_service.py`
- `src/drawing_graph/relation_repository.py`
- `src/drawing_graph/candidate_review.py`
- `src/drawing_graph/semantic_*`
- `src/drawing_graph/block_relation_enrichment.py`
- `src/drawing_graph/import_service.py`
- 导入、增强、候选复核 CLI
- `scripts/create_schema.cypher`

如果后续测试发现必须修改其中任一领域契约、facade 方法集、查询行为或写回逻辑，应停止第三阶段实施并回到 design 评审，不能以“适配 MCP”为由顺带重构。

## 5. 不包含范围

本变更不包含以下内容：

1. 不提供任何写回型 MCP tool，不开放 `write_back=true`。
2. 不通过 MCP 触发来源事实导入、离线派生关系增强、语义识别持久化、候选复核、候选提升或正式关系写入。
3. 不提供任意 Cypher、通用图查询、Neo4j driver/session/transaction 或 repository 工具。
4. 不让 MCP adapter 调用 HTTP API、QA CLI、底层 CLI 子进程或离线规则函数。
5. 不让 Skill 直接创建 Neo4j driver、执行 Cypher或调用 repository 写回方法。
6. 不把 `candidate_relation`、`CANDIDATE_*`、`matched_candidate`、模型 observation 或 interpretation 表述为正式事实。
7. 不覆盖来源事实，不把 `BlockInterpretation.interpreted_type` 写入或表述为 `DrawingBlock.block_type`。
8. 不改变 `RecognitionRun` 图谱外、`TextObservation`/`Interpretation` 图谱内并通过 `recognition_run_id` 关联的边界。
9. 不新增或修改 Neo4j Schema、业务节点、关系类型、约束或索引。
10. 不在第三阶段首版实现 Streamable HTTP MCP、SSE transport、远程 MCP 服务或多 worker MCP 部署。
11. 不实现 OAuth、远程身份系统、RBAC、租户隔离、TLS 终止、反向代理或公网部署。
12. 不把现有 HTTP Bearer token 直接声明为生产级 MCP 认证方案。
13. 不将 Skill/MCP 打包成可发布 plugin，不提交到公共插件目录；分发可在本地验证成熟后单独立项。
14. 不实现 Ava 专有 adapter、SDK、账号体系或专有协议。
15. 不接入真实云多模态模型供应商，不新增供应商 API key 参数。
16. 不实现 OCR、全量自动语义扫描、文件 watcher、定时任务、后台任务队列或长任务系统。
17. 不封装真实 `data/`、PNG/JSON、Neo4j 数据、`.env`、密码、API key、token 或 secret。
18. 不未经验证直接删除 `.codex/skills/drawing-graph-operator`。
19. 不在 `.codex/skills` 和 `.agents/skills` 长期保留两个独立维护的同名 Skill 副本。
20. 不把 MCP in-memory 测试、STDIO smoke、Skill 发现或 HTTP 健康检查写成 live Neo4j 已验证。
21. 不把被跳过的 Neo4j 集成测试报告为通过；未实际连接 disposable 测试库时，live Neo4j 仍为未验证。

## 6. 影响模块

### 6.1 直接影响模块

| 模块 | 影响程度 | 说明 |
|---|---:|---|
| `src/drawing_graph/qa_mcp_models.py` | 高，新建 | MCP 输入/输出合同、字段白名单和领域转换 |
| `src/drawing_graph/qa_mcp_tools.py` | 高，新建 | 六个稳定只读工具和唯一 QAService 调用边界 |
| `src/drawing_graph/qa_mcp_runtime.py` | 高，新建 | driver/facade/QAService 的 MCP 进程生命周期 |
| `src/drawing_graph/qa_mcp_server.py` | 高，新建 | MCP 初始化、instructions、工具注册、Schema 和 annotations |
| `scripts/serve_drawing_graph_mcp.py` | 高，新建 | STDIO server 启动和协议输出边界 |
| `tests/test_qa_mcp*.py` | 高，新建 | MCP 模型、工具、runtime、server、STDIO 和文档合同 |
| `requirements.txt` | 中 | 新增 MCP SDK，并承担与第二阶段 Web 依赖兼容的风险 |
| `drawing-graph-operator` Skill 资产 | 高 | 新增 QA/MCP 工作流、工具边界、输出和验证规则，可能涉及经验证的路径迁移 |
| `tests/test_skill_docs.py` / Skill 行为测试 | 高 | 保护单一权威路径、MCP 依赖、触发规则和安全边界 |
| `README.md` / `Module.md` / `architecture.md` | 中 | 实现完成后同步 MCP/Skill 当前状态和仍未实现范围 |

### 6.2 间接影响模块

| 模块 | 影响 | 说明 |
|---|---|---|
| `src/drawing_graph/qa_models.py` | 被映射 | MCP 输入转换为现有 `QARequest`，输出沿用 `QAAnswer`；领域 DTO 不引入 MCP 类型 |
| `src/drawing_graph/qa_service.py` | 被调用 | 所有 MCP 业务工具的唯一业务入口；原则上不修改 |
| `src/drawing_graph/qa_serialization.py` | 被复用 | MCP 复用 JSON-compatible 转换和脱敏，不改变 HTTP/CLI 合同 |
| `src/drawing_graph/tool_facade.py` | 间接调用 | 继续作为唯一图谱应用门面，不直接暴露给 MCP tool handler |
| `src/drawing_graph/tool_factory.py` | runtime 使用 | 继续通过 `create_neo4j_tool_facade(driver)` 装配真实 facade |
| `src/drawing_graph/config.py` | 可能小幅修改 | 仅在需要独立 MCP 配置时新增窄口径字段，不重构导入或 HTTP 配置 |
| `src/drawing_graph/qa_http*.py` | 回归影响 | MCP SDK 依赖和共享库变更不得破坏第二阶段 HTTP 行为 |
| `scripts/drawing_graph_qa.py` | 回归影响 | Skill 降级可能调用 QA CLI，但 MCP adapter 不调用它，现有 CLI 合同保持不变 |
| `src/drawing_graph/semantic_*` | 间接读取 | 只通过 QAService/facade 返回已允许的语义证据，不新增写回 |
| `src/drawing_graph/section_match_service.py` | 间接 dry-run/查询 | MCP 不直接调用，也不触发 `write_back=true` |
| `src/drawing_graph/candidate_review.py` | 边界保护 | MCP 不调用候选审核或正式提升能力 |

### 6.3 不应受影响模块

| 模块 | 原因 |
|---|---|
| 基础导入模块及 CLI | MCP/Skill 不读取或修改原始 JSON/PNG，不改变来源事实导入流程 |
| 离线派生关系增强模块及 CLI | 第三阶段只读，不触发空间规则计算或关系写入 |
| 候选复核 CLI | MCP 不新增审核、accepted/rejected/unresolved 写回入口 |
| Neo4j repository 与 Schema | MCP 是应用层 adapter，不是新的数据层 |
| 现有 HTTP 路由 | MCP 与 HTTP 同级，不挂入 REST route，不改变 HTTP 合同 |

### 6.4 测试与验证影响

第三阶段实施后需要保持第一、二阶段全部测试继续通过，并新增以下验证：

- MCP 模块 import 不读取环境变量、不创建 driver、不启动 server。
- MCP server 可完成 initialize、工具发现和工具调用。
- 六个工具正确构造 `QARequest`，且每次只调用一次 `DrawingGraphQAService.ask()`。
- MCP 工具不导入或调用 HTTP route、CLI、facade 单项方法、QueryService、Repository 或 Cypher。
- 工具输入拒绝凭据、Cypher、driver、session、transaction、repository 和未知字段。
- 所有工具标注只读，同时固定 `write_back=false`；不存在写回工具。
- `structuredContent` 保留 `QAAnswer` 的事实类型、证据、warnings 和 unsupported parts。
- STDIO stdout 不包含日志；stderr 和客户端错误不包含 secret、URI、Cypher 或底层堆栈。
- Skill 只有一个权威副本，并能在目标宿主中被发现、显式调用和按描述触发。
- Skill 能把代表性自然语言问题稳定路由到正确 MCP 工具，并在 MCP 不可用时明确降级。
- 第一阶段 QA/CLI 和第二阶段 HTTP 合同无回归。
- live Neo4j 只有在配置 `NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD` 并实际运行 disposable 集成测试后才能标记为通过；skipped 必须记录为未验证。

本提案确认后，下一步应基于本文件与 `Feature_Analysis_Report.md` 编写第三阶段 `design.md`，进一步确定 MCP SDK 版本范围、工具输入/输出模型、server instructions、STDIO 生命周期、错误映射、配置方式、Skill 权威路径迁移和测试注入。在 design 获得确认前不进入代码实现。
