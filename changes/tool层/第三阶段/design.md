# Tool 层第三阶段 MCP 与 Skill 强化技术设计

## 设计依据与约束

本设计以同目录 `proposal.md` 和 `Feature_Analysis_Report.md` 为需求基线。第三阶段只增加标准 MCP 只读适配能力并强化现有 `drawing-graph-operator` Skill，不重写已经稳定的 QAService、Tool facade、HTTP adapter 或 Neo4j 数据模型。

设计遵循以下原则：

1. **复用已有业务入口。** 所有 MCP 业务工具只构造现有 `QARequest`，并调用一次 `DrawingGraphQAService.ask()`。
2. **adapter 保持同级。** CLI、HTTP 和 MCP 分别适配同一 QAService；MCP 不转调 HTTP endpoint 或 CLI 子进程。
3. **传输语义不进入领域层。** MCP SDK 类型、tool name、context、structured content 和 transport 状态不得进入 `qa_models.py`、`qa_service.py` 或 facade。
4. **默认且强制只读。** 外部输入中不提供 `write_back`，内部请求固定 `write_back=false`；tool annotation 只作客户端提示，服务端校验才是权威边界。
5. **保持事实分层。** MCP 只映射现有 `QAAnswer`，不得重新判断候选关系、语义解释或正式关系。
6. **最小新增，不做形式化重构。** 不为 CLI、HTTP、MCP 创建通用 adapter 基类，不把同步 QA 链路改为异步，不拆分现有稳定模块。
7. **验证状态分层。** 单元测试、MCP 协议测试、STDIO smoke、HTTP 回归和 live Neo4j 验证分别报告，跳过不等于通过。

---

## 1. 系统架构变化

### 1.1 当前架构

```text
QA CLI                         HTTP client
   |                               |
   v                               v
scripts/drawing_graph_qa.py   FastAPI QA adapter
             \                 /
              v               v
              DrawingGraphQAService
                       |
                       v
              DrawingGraphToolFacade
                       |
                       v
              ports / services
                       |
                       v
          controlled repository / Neo4j
```

现有 `drawing-graph-operator` Skill 位于调用链外侧，负责操作纪律、入口选择、事实分层和验证说明，不承担运行时业务处理。

### 1.2 目标架构

```text
User / Codex / external Agent
              |
              v
 drawing-graph-operator Skill
  - 识别问题类型和 scope
  - 选择或组合工具
  - 保守解释结果
  - MCP 不可用时透明降级
              |
              v
         MCP client
              |
       local STDIO transport
              |
              v
        MCP server adapter
  - server instructions
  - tools/list 与 tools/call
  - 输入/输出 Schema
  - tool annotations
              |
              v
       MCP tool registry
  - 参数白名单与领域转换
  - structuredContent / TextContent
  - 安全错误映射
              |
              v
      DrawingGraphQAService.ask()
              |
              v
      DrawingGraphToolFacade
              |
              v
       ports / services
              |
              v
 controlled repository / Neo4j
```

CLI、HTTP、MCP 仍是三个同级 adapter：

```text
QA CLI -------+
HTTP adapter -+-> DrawingGraphQAService -> DrawingGraphToolFacade
MCP adapter --+
```

禁止形成以下调用链：

```text
MCP -> HTTP -> QAService
MCP -> QA CLI 子进程
MCP -> facade 单项方法 / QueryService / repository / Cypher
Skill -> Neo4j driver / repository / 写回方法
```

### 1.3 MCP 进程生命周期

STDIO MCP server 采用单进程、单本地客户端的首版边界：

1. 启动脚本进入 `main` 后读取 MCP 所需环境变量。
2. runtime 创建 Neo4j driver。
3. runtime 复用 `create_neo4j_tool_facade(driver)` 创建生产 facade。
4. runtime 创建一个长生命周期 `DrawingGraphQAService`。
5. server 注册六个只读工具并进入 STDIO 协议循环。
6. 客户端关闭、进程收到终止信号或启动失败时，runtime 关闭已创建资源。
7. `close()` 必须幂等；部分初始化失败也必须释放已创建的 driver。

模块 import 不读取环境变量、不创建 driver、不连接 Neo4j、不启动协议循环。第三阶段不额外引入 worker、后台队列、跨进程状态或自定义调度器。

### 1.4 单次工具调用数据流

```text
MCP input
  -> MCP 输入模型校验
  -> 固定 QuestionType + 构造 QAScope
  -> QARequest(write_back=false)
  -> DrawingGraphQAService.ask()
  -> QAAnswer
  -> 共享 JSON-safe 序列化
  -> MCP structuredContent
  -> 从同一 QAAnswer 生成简短 TextContent
```

每个外部工具只能调用一次 `ask()`。不得在 MCP mapper 中再次查询图谱、补算关系或改变 `fact_kind`。

### 1.5 Skill 与 MCP 的职责边界

| 层 | 负责 | 不负责 |
|---|---|---|
| Skill | 自然语言路由、多问题拆分、工具选择、降级、事实分层解释、验证说明 | Schema 校验、数据库连接、业务查询、关系推断、写回 |
| MCP server | 协议初始化、工具发现、Schema、annotations、STDIO 生命周期 | 图谱业务规则、自然语言自由问答、HTTP 代理 |
| MCP tools | 窄口径参数转换、调用 QAService、结果和错误映射 | 直接调用 facade/repository、重新分类事实 |
| QAService | 问题路由、scope 校验、证据聚合、结构化回答 | MCP transport、环境变量、driver 生命周期 |
| Tool facade | 受控图谱能力边界 | MCP/Skill 语义 |

### 1.6 Skill 路径迁移

`.agents/skills/drawing-graph-operator` 是目标标准位置，但路径迁移不是 MCP 核心运行链的前置条件。实施时按以下状态推进：

```text
当前 .codex/skills 生效
  -> 在隔离变更中移动到 .agents/skills（不是复制）
  -> 验证桌面端及项目实际使用的 CLI/IDE 能发现和触发
     -> 通过：保留 .agents/skills 为唯一权威副本
     -> 失败：恢复 .codex/skills，记录兼容性待办
```

任何时刻都不长期维护两个同名、内容独立的 Skill 副本。路径验证失败不阻断 MCP server 本身的交付，但必须如实报告 Skill 仍使用旧路径。

---

## 2. 新增模块

### 2.1 `src/drawing_graph/qa_mcp_models.py`

职责：定义 MCP adapter 自有的输入/输出合同，以及到现有 QA 领域 DTO 的单向转换。

包含：

- 六个工具的窄口径输入模型。
- 公共语言、ID、布尔开关的白名单校验。
- `McpQAResult`、`McpQAError`、`McpResultMeta` 等传输层输出模型。
- 工具输入到 `QARequest`/`QAScope` 的转换。
- MCP `outputSchema` 所需的稳定根对象定义。

不包含：

- Neo4j、driver、facade 或 QAService 实例。
- MCP server 注册逻辑。
- 问题类型自由输入。
- `write_back`、Cypher、credentials、任意 payload 或底层查询参数。

### 2.2 `src/drawing_graph/qa_mcp_tools.py`

职责：实现传输无关的六个 MCP 工具 handler，并把现有 QAAnswer 转换为 MCP 结果。

核心设计：

- 构造时仅注入 `DrawingGraphQAService` 或满足相同窄接口的 fake service。
- 每个公开 handler 固定一个 `QuestionType`，不接受客户端传入任意问题类型。
- 内部可复用一个私有 dispatcher 处理“输入转换、调用一次 `ask()`、结果映射、错误脱敏”的公共流程。
- structuredContent 与简短文本摘要都由同一个已序列化 QAAnswer 生成。
- `partial` 是成功但不完整的回答，不转换为 tool error。

不建立通用公开 `ask_drawing_graph` 工具，避免把 scope 和问题类型组合错误交给 Agent。

### 2.3 `src/drawing_graph/qa_mcp_runtime.py`

职责：管理 MCP 进程内 driver、facade 和 QAService 的长生命周期。

设计与 `qa_http_runtime.py` 保持同一生命周期思想，但不继承 HTTP runtime，也不抽取新的通用 runtime 基类。原因是 HTTP lifespan、并发和请求状态与 STDIO server 生命周期不同，当前共享内容不足以支撑稳定抽象。

runtime 提供：

- 生产装配工厂。
- driver/facade/service 的只读访问。
- 依赖注入点，支持 fake driver 和 fake service。
- 初始化失败的逆序清理。
- 幂等关闭。

### 2.4 `src/drawing_graph/qa_mcp_server.py`

职责：通过官方 MCP Python SDK 的公开高层 server API 创建 server，注册 instructions、六个工具、Schema 和 annotations。

设计要求：

- `create_mcp_server(...)` 本身不读取环境变量、不连接数据库、不运行 transport。
- server instructions 的开头在有限长度内自包含地声明：只读、候选不是正式事实、模型证据不覆盖来源事实、不得执行任意 Cypher、必须如实报告验证状态。
- 工具描述短而明确，优先说明适用 scope、事实边界和可能的 `partial`。
- 仅提供 Tools capability；首版不新增 Resources、Prompts、Sampling、Completion 或长任务能力。
- 具体 SDK import 和版本范围在实施前通过依赖兼容测试确认，只依赖官方公开 API，不依赖私有模块。

### 2.5 `scripts/serve_drawing_graph_mcp.py`

职责：本地 STDIO MCP 的唯一进程入口。

设计要求：

- 仅在 `main` 中读取环境变量、创建 runtime 和运行 STDIO。
- stdout 只承载 MCP 协议帧；帮助信息、启动信息、警告和错误全部进入 stderr。
- 配置错误或初始化错误返回非零退出码，错误信息经过脱敏。
- 正常退出和异常退出都关闭 runtime。
- 不提供 HTTP 参数、远程监听参数或 worker 参数。

### 2.6 Skill 新增资料

目标权威 Skill 根目录下新增：

| 文件 | 职责 |
|---|---|
| `references/qa-workflows.md` | 自然语言问题到六个 MCP 工具、QuestionType 和 scope 的映射；多问题拆分与组合顺序 |
| `references/mcp-boundaries.md` | 工具清单、只读边界、不可用/超时/错误处理、透明降级和禁止调用链 |

这些文件只包含操作规则，不复制 Python 业务逻辑，不持有真实数据或凭据。

### 2.7 新增测试模块

| 文件 | 独立验证目标 |
|---|---|
| `tests/test_qa_mcp_models.py` | 输入白名单、scope、ID、领域转换、输出合同 |
| `tests/test_qa_mcp_tools.py` | 六个工具映射、单次 `ask()`、事实分层、partial/error |
| `tests/test_qa_mcp_runtime.py` | 创建顺序、注入、失败清理、幂等关闭 |
| `tests/test_qa_mcp_server.py` | initialize、tools/list、tools/call、Schema、annotations、instructions |
| `tests/test_qa_mcp_cli.py` | import 无副作用、STDIO 协议纯净、stderr 脱敏、退出行为 |
| `tests/test_qa_mcp_docs.py` | MCP/Skill 分工、只读边界、未实现范围和验证表述 |

---

## 3. 修改模块

### 3.1 必须修改

| 模块 | 修改内容 | 复用/兼容要求 |
|---|---|---|
| `requirements.txt` | 增加受控 MCP Python SDK 版本范围 | 与现有 FastAPI、Pydantic、Starlette、Uvicorn、HTTPX、Neo4j driver 做兼容测试；不无条件升级现有依赖 |
| `src/drawing_graph/config.py` | 增加窄口径 `QAMcpConfig` 及所需环境变量读取 | 复用现有安全解析小函数；不继承 HTTP host/CORS/docs 配置，不扩大 `ImportConfig` |
| Skill 的 `SKILL.md` | 增加 MCP 优先、受控降级和资料路由 | 保留现有 facade/事实分层/只读规则 |
| Skill 的 `references/output-contract.md` | 增加 structuredContent、TextContent 和最终回答一致性规则 | 沿用现有事实类别，不发明 MCP 专用事实分类 |
| Skill 的 `references/verification.md` | 增加 MCP 合约、STDIO、Skill 发现和 live Neo4j 分层验证 | skipped 必须继续标为未验证 |
| Skill 的 `agents/openai.yaml` | 在宿主验证通过后声明 MCP tool dependency | 不写 command 中的真实凭据，不把未验证依赖声明为可用 |
| `tests/test_skill_docs.py` | 更新必需资料、路径、MCP 工作流和单一权威副本断言 | 路径迁移时与资产移动同一变更完成 |
| `README.md` | 增加安装、STDIO 配置、工具清单、Skill 使用和验证说明 | 只在实现与验证后把能力标为当前能力 |
| `Module.md` | 登记 MCP models/tools/runtime/server/CLI 及 Skill 分工 | 保持当前/规划状态分开 |
| `architecture.md` | 将 MCP adapter 加入同级 adapter 架构 | 远程 MCP、写回、OAuth 仍明确为未实现 |

### 3.2 条件修改

`src/drawing_graph/qa_serialization.py` 原则上直接复用现有 JSON-safe 序列化与 `sanitize_error_message`。只有在以下任一条件成立时才修改：

- 现有公共函数不能稳定处理 `QAAnswer` 中已有字段；
- MCP 与 CLI/HTTP 确实需要完全相同的框架无关脱敏逻辑；
- 修改不会改变现有 CLI/HTTP envelope 和回归结果。

MCP 特有的 `structuredContent` 根对象、tool error 和 TextContent 格式必须留在 MCP 模块，不能写入共享 serializer。

### 3.3 原则上不修改

以下模块已有能力足够，第三阶段不修改：

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
- repositories、candidate review、semantic evidence、import/enrichment 模块
- `scripts/create_schema.cypher`

如果实施发现必须改变上述任一领域契约、facade 方法集、查询语义、写回逻辑或 Neo4j Schema，应暂停实施并重新评审 design，而不是以适配 MCP 为由顺带修改。

### 3.4 明确不做的重构

- 不创建 `BaseAdapter`、`BaseRuntime`、`TransportManager` 等当前只有两个或三个调用方、且语义不同的抽象。
- 不把 HTTP、CLI 和 MCP 输入模型合并成一个万能请求模型。
- 不把现有同步 QAService 改为 async。
- 不移动 Tool facade、repository 或 semantic 模块。
- 不把六个稳定 QA 意图拆成 facade 级几十个工具。
- 不为未来 Streamable HTTP、OAuth 或 plugin 提前加入未使用的配置和类。

---

## 4. 数据模型变化

### 4.1 Neo4j 和领域模型

第三阶段**不改变 Neo4j 数据模型**：

- 不新增节点、关系、属性、索引或约束。
- 不修改 `scripts/create_schema.cypher`。
- 不改变 `RecognitionRun` 图谱外、`TextObservation`/Interpretation 图谱内的现有边界。
- 不改变 candidate、formal、source fact、derived relation 和 semantic evidence 的语义。

第三阶段也**不改变现有 QA 领域 DTO**。`QARequest`、`QAScope`、`QAAnswer`、`AnswerFact`、`EvidenceRef`、状态和错误码仍是业务合同；MCP 模型只存在于 adapter 层。

### 4.2 MCP 输入模型

所有输入模型采用额外字段拒绝策略，只接受工具实际需要的字段。ID 为去除首尾空白后的非空字符串，并设置合理长度上限；语言仅允许现有 QAService 支持的值。

| 工具 | 必填字段 | 可选字段 | 固定领域映射 |
|---|---|---|---|
| `ask_drawing_page` | `page_id` | `language`、`include_semantics` | `page_summary`，scope.page_id，`write_back=false` |
| `ask_drawing_block` | `block_id` | `language`、`include_candidates` | `block_relations`，scope.block_id，`write_back=false` |
| `list_drawing_candidates` | `page_id` 或 `block_id`，且只能选一个 | `language` | `candidate_relations`，对应单一 scope，`write_back=false` |
| `get_section_match_status` | `cross_section_id` 或 `page_id`，且只能选一个 | `language` | `section_matches`，对应单一 scope，`write_back=false` |
| `get_table_caption_status` | `table_id`、`table_caption_id` 或 `page_id`，且只能选一个 | `language` | `table_caption_status`，对应单一 scope，`write_back=false` |
| `get_drawing_diagnostics` | `page_id` 或 `block_id`，且只能选一个 | `language`、`include_semantics`、`include_candidates` | `diagnostic_status`，对应单一 scope，`write_back=false` |

首版不暴露 `include_payload`。这避免通过新协议扩大原始 payload 或本地路径信息的输出面；若未来确有受控需求，应单独评审数据最小化、大小限制和敏感内容。

### 4.3 MCP 成功结果

MCP structuredContent 使用稳定根对象，不直接裸露 transport 或 SDK 内部对象：

| 字段 | 类型 | 含义 |
|---|---|---|
| `status` | 固定值 `ok` | 表示工具执行完成；QAAnswer 仍可为 answered 或 partial |
| `data` | QAAnswer 的 JSON-safe 对象 | 完整保留 summary、facts、evidence、warnings、unsupported_parts、source_calls 等现有字段 |
| `meta.contract_version` | 字符串 | 首版固定为 `drawing-qa-mcp-v1` |
| `meta.tool_name` | 字符串 | 实际调用的六个工具之一 |
| `meta.call_id` | 字符串 | 本地生成的非敏感调用关联 ID，用于 stderr 日志定位 |

`data` 内仍以现有 QAAnswer 状态表达 `answered` 和 `partial`。MCP 外层的 `status=ok` 不把 partial 伪装为完整成功；TextContent 必须明确指出 partial、warnings 和 unsupported parts。

### 4.4 MCP 错误结果

可归因于一次工具执行的错误使用稳定安全对象：

| 字段 | 类型 | 含义 |
|---|---|---|
| `status` | 固定值 `error` | 工具执行失败 |
| `error.category` | 枚举字符串 | 稳定错误类别，不暴露 Python 异常类 |
| `error.message` | 字符串 | 已脱敏、面向调用方的短消息 |
| `error.retryable` | 布尔 | 当前条件下重试是否可能成功 |
| `error.field` | 可选字符串 | 仅允许安全的输入字段名 |
| `meta.contract_version` | 字符串 | `drawing-qa-mcp-v1` |
| `meta.tool_name` | 字符串 | 调用工具名 |
| `meta.call_id` | 字符串 | 与 stderr 诊断日志关联 |

成功对象和错误对象都定义根级 object `outputSchema`。不得返回 stack trace、Cypher、数据库地址、用户名、密码、token、环境变量值或本地敏感绝对路径。

### 4.5 TextContent

每次工具调用同时提供一条简短 TextContent，内容仅包含：

- QA 状态与 summary；
- facts 数量；
- warnings 数量；
- unsupported parts 数量；
- partial 或 error 时的明确提示。

TextContent 从 structuredContent 对应的同一结果生成，不独立查询、不重排事实等级、不用自然语言把 candidate 表述为 formal。

---

## 5. API 设计

### 5.1 Server API

| 项 | 设计 |
|---|---|
| server name | `drawing-graph-qa` |
| 首版 transport | 本地 STDIO |
| 对外 capability | Tools |
| 业务入口 | `DrawingGraphQAService.ask()` |
| server instructions | 只读、事实分层、禁止任意 Cypher、验证状态诚实报告 |
| import 行为 | 无环境读取、无连接、无进程启动 |
| 运行模式 | 单本地进程、单客户端；不宣称远程/多租户能力 |

Server factory 接收已装配的工具对象或 runtime provider，方便协议测试注入 fake service。生产启动脚本负责环境读取和资源装配，server 工厂不承担配置职责。

### 5.2 Tool API

#### `ask_drawing_page`

- 用途：获取指定图纸页的摘要、相关事实和可用语义信息。
- 映射：`QuestionType.PAGE_SUMMARY`。
- scope：仅 `page_id`。
- 注意：`include_semantics=true` 只读取现有语义证据，不触发识别或持久化。

#### `ask_drawing_block`

- 用途：获取指定图块及其关系。
- 映射：`QuestionType.BLOCK_RELATIONS`。
- scope：仅 `block_id`。
- 注意：候选关系继续标记为 candidate，不因 MCP 输出成为 formal。

#### `list_drawing_candidates`

- 用途：列出页面或图块范围内的候选关系。
- 映射：`QuestionType.CANDIDATE_RELATIONS`。
- scope：`page_id` 与 `block_id` 二选一。
- 注意：工具名、描述和结果文本都必须使用“候选”，不得使用“已确认关系”。

#### `get_section_match_status`

- 用途：查询断面匹配状态和相应证据。
- 映射：`QuestionType.SECTION_MATCHES`。
- scope：`cross_section_id` 与 `page_id` 二选一。
- 注意：`matched_candidate` 仍是候选结果，不是正式关系；调用固定只读。

#### `get_table_caption_status`

- 用途：查询表格与表题相关状态。
- 映射：`QuestionType.TABLE_CAPTION_STATUS`。
- scope：`table_id`、`table_caption_id`、`page_id` 三选一。
- 注意：当前底层能力不足时允许返回 `partial + unsupported_parts`，MCP 层不补造结论。

#### `get_drawing_diagnostics`

- 用途：查询页面或图块范围内的诊断状态。
- 映射：`QuestionType.DIAGNOSTIC_STATUS`。
- scope：`page_id` 与 `block_id` 二选一。
- 注意：诊断结果不是自动修复指令，不触发导入、增强、识别或写回。

### 5.3 Tool annotations

六个工具统一声明：

| annotation | 值 | 说明 |
|---|---:|---|
| `readOnlyHint` | `true` | 工具设计为只读 |
| `destructiveHint` | `false` | 不删除、不覆盖、不持久化 |
| `openWorldHint` | `false` | 只访问已配置的本地图块图谱能力，不访问开放互联网 |

`idempotentHint` 对只读工具没有额外安全价值，首版可省略，避免把提示字段误当成执行保证。annotations 不替代内部固定 `write_back=false`、QAService 拒绝写回和 facade 边界。

### 5.4 MCP 返回语义

- `answered`：返回 `isError=false`，structuredContent.status 为 `ok`。
- `partial`：返回 `isError=false`，structuredContent.status 为 `ok`；TextContent 明确“部分回答”，并保留 warnings/unsupported_parts。
- not found、unsupported 或领域拒绝：返回 `isError=true` 的安全工具结果。
- 未知 tool、无法解析的 MCP 消息、未支持的方法或 initialize 失败：由 SDK 按协议级错误处理，不伪装成 QA 业务错误。

`tools/list` 返回的 inputSchema、outputSchema、描述和 annotations 必须稳定并纳入快照/合约测试。

### 5.5 Skill 调用策略

| 用户意图 | 首选工具 | 缺少必要 ID 时 |
|---|---|---|
| 看某页整体信息 | `ask_drawing_page` | 请求 page_id，不猜测 |
| 看某图块关系 | `ask_drawing_block` | 请求 block_id，不扩大到全库 |
| 看候选关系 | `list_drawing_candidates` | 请求 page_id 或 block_id |
| 看断面匹配 | `get_section_match_status` | 请求 cross_section_id 或 page_id |
| 看表格/表题状态 | `get_table_caption_status` | 请求一个受支持 scope ID |
| 排查页面或图块 | `get_drawing_diagnostics` | 请求 page_id 或 block_id |

一个问题包含多个独立意图时，Skill 拆分调用并在最终回答中保持每个工具的证据边界；不得将两个 partial 拼接成一个已确认结论。

MCP 不可用、工具缺失、初始化失败或超时时，Skill 可以透明降级到现有 QA CLI，但必须：

1. 明确说明 MCP 未成功使用及原因类别；
2. 只使用受控 QA CLI，不直接执行 Cypher；
3. 保持 `write_back=false`；
4. 不把 CLI 结果标记为 MCP 已验证。

### 5.6 Codex 配置与依赖声明

- 项目级 MCP 配置只记录 command、args、工作目录和允许转发的环境变量名，不记录真实凭据值。
- MCP server 的稳定名称与 Skill dependency 声明保持一致。
- `agents/openai.yaml` 只在目标宿主确认能发现 server/tool 后加入依赖。
- 建议客户端对这六个工具使用显式 allowlist；若未来新增写工具，客户端 approval 策略必须重新评审。
- 第三阶段不自动修改用户级 Codex 配置，不把本机绝对路径硬编码为可移植项目合同。

---

## 6. 异常处理

### 6.1 异常分层

| 层级 | 示例 | 处理方式 |
|---|---|---|
| MCP 协议层 | 未知 method、未知 tool、消息结构损坏、initialize 失败 | 交由官方 SDK 生成协议错误；必要时进程非零退出 |
| 输入合同层 | 缺少 ID、ID 为空、互斥 scope 同时出现、额外字段、非法语言 | 返回安全 tool error；指出允许的字段名，不回显完整输入 |
| QA 领域层 | unsupported、not found、write-back forbidden、scope 不支持 | 映射为稳定 error.category；保留安全业务说明 |
| 部分回答 | 数据可用但能力不完整、table caption 派生状态不足 | `isError=false`；保留 partial、warnings、unsupported_parts |
| 基础设施层 | Neo4j 不可用、facade 初始化失败、driver 关闭失败 | 脱敏、标记 retryable；初始化失败清理资源，启动进程非零退出 |
| 未预期内部异常 | Python/SDK 未分类异常 | 记录 call_id 和脱敏诊断；调用方只得到 `internal_error` |

### 6.2 稳定错误类别

MCP adapter 优先复用现有 QA 错误语义，外部错误类别限定为：

- `invalid_argument`
- `unsupported_question`
- `unsupported_scope`
- `not_found`
- `write_back_forbidden`
- `facade_unavailable`
- `neo4j_unavailable`
- `semantic_evidence_unavailable`
- `internal_error`

如现有 `QAErrorCode` 名称不同，实施时建立显式一一映射，不直接序列化 Python 枚举实现细节。不得根据异常文本动态生成新的公开类别。

### 6.3 输入校验错误

- SDK 能在 handler 边界内返回结构化验证结果时，使用 `isError=true` 的 tool result。
- 对 SDK 在 handler 前拦截的 JSON Schema/协议结构错误，保留 SDK 标准协议错误，不强行捕获并二次包装。
- 错误消息只说明哪个公开字段不合法和预期规则，不回显 secrets、完整 payload 或内部模型 repr。

### 6.4 QA 状态映射

| QA 结果 | MCP 处理 |
|---|---|
| `answered` | 正常成功结果 |
| `partial` | 正常成功结果，同时明显提示不完整 |
| `not_found` | `isError=true`，通常不可通过原参数重试 |
| `unsupported` | `isError=true`，提示受支持工具/scope，不自动换成任意查询 |
| `failed` | 按已有 error code 映射；未知原因归入 `internal_error` |

warnings 和 unsupported_parts 不得因为 `isError=false` 被丢弃。

### 6.5 超时、取消与并发

第三阶段首版不引入独立任务队列或自定义长任务协议：

- 工具定位为本地短查询；客户端通过 MCP 的工具超时配置控制等待上限。
- server 收到取消时尽快停止结果交付并释放本次调用上下文；不承诺底层同步数据库调用可被强制中断。
- STDIO 首版按单本地客户端设计，不对多客户端或多 worker 做一致性承诺。
- 不因未来并发需求提前把 QAService 改为 async；若压测证明需要 server 侧并发上限，另行增加局部容量保护。

超时或取消后不得自动重试可能扩大查询范围的其他工具，也不得静默降级。是否降级由 Skill 在明确告知后决定。

### 6.6 启动与关闭异常

- 配置缺失：driver 创建前失败，stderr 输出脱敏配置错误，退出码非零。
- driver 已创建但 facade/service 创建失败：立即关闭 driver，再返回启动失败。
- 协议循环异常：记录脱敏信息，进入 finally 关闭 runtime。
- close 重复调用：不抛出新的业务异常。
- driver close 失败：记录但不把 secrets 或连接 URI 输出到 stdout；进程仍以失败状态结束。

---

## 7. 安全方案

### 7.1 只读纵深防御

只读边界采用四层控制：

1. **工具面控制：** 只注册六个查询工具，不注册导入、增强、识别持久化、候选复核、提升或任意 Cypher 工具。
2. **Schema 控制：** 输入不包含 `write_back`、Cypher、driver、session、transaction、repository、credentials 或任意 payload。
3. **请求控制：** MCP mapper 内部固定构造 `write_back=false`。
4. **业务控制：** `DrawingGraphQAService` 和 facade 继续拒绝越界或写回请求。

tool annotations 是第五层提示，但不能作为安全控制的唯一依据。

### 7.2 凭据和配置

- Neo4j URI、用户名、密码只从运行环境注入，不出现在工具参数、structuredContent、Skill、仓库配置示例或日志中。
- Codex MCP 配置只声明允许转发的环境变量名。
- 不把 `.env`、token、password、API key 或真实数据库信息纳入 Skill assets。
- server instructions 和 tool descriptions 不包含内部连接拓扑。
- 错误脱敏复用现有安全逻辑；新增测试覆盖 URI 凭据、token、password 和常见 secret 形式。

### 7.3 STDIO 协议隔离

- stdout 只写 MCP 协议，禁止使用普通 print 输出日志、banner、调试对象或异常栈。
- 所有日志进入 stderr，并使用 call_id 关联。
- 日志默认不记录完整输入、完整 structuredContent、数据库返回 payload 或本地图片内容。
- 启动脚本不启动网络监听端口；第三阶段不提供 Streamable HTTP。

### 7.4 最小权限和闭域访问

- MCP 进程只需连接已配置 Neo4j；不访问互联网、不下载模型、不调用云多模态服务。
- 推荐 Neo4j 运行账号使用只读权限。应用层只读不能替代数据库最小权限。
- 工具不读取任意用户文件，不接受路径参数；QAAnswer 中已有证据路径只作为数据引用返回，不由 MCP adapter 打开或执行。
- 不允许客户端指定数据库名、Cypher、procedure 或 APOC 调用。

### 7.5 数据最小化与输出安全

- 首版不暴露 `include_payload`，只返回现有 QA 回答所需的结构化事实和证据引用。
- 沿用 QAService 的查询范围和结果限制，不新增全库无 scope 查询。
- 工具描述和 Skill 要求缺少 ID 时询问用户，不猜测、不扩大范围。
- 图纸文字、OCR 文本、模型解释和 Neo4j 字符串都视为不可信数据；Agent 不应把其中的命令式文本当成系统指令或执行请求。
- structuredContent 只做 JSON-safe 转换，不拼接可执行 shell、Cypher 或配置片段。

### 7.6 事实完整性

- `source_fact`、`derived_relation`、`semantic_observation`、`semantic_interpretation`、`candidate_relation`、`formal_relation`、`diagnostic` 和 `unsupported` 原样保留。
- candidate、`CANDIDATE_*`、`matched_candidate` 不得标为正式事实。
- 模型 observation/interpretation 不覆盖来源事实。
- `partial`、warnings 和 unsupported_parts 必须同时出现在 structuredContent 和人类可见摘要中。
- Skill 输出契约、server instructions 和 MCP 合约测试共同保护上述规则。

### 7.7 供应链与 SDK 风险

- 使用官方 MCP Python SDK，声明受控兼容版本范围并保留 lock/安装解析证据。
- 在引入依赖前验证与现有 FastAPI、Pydantic、Starlette、Uvicorn、HTTPX 和 Neo4j driver 的解析与导入兼容性。
- 不依赖 SDK 私有模块或未稳定接口。
- SDK 升级必须运行 MCP 合约、STDIO、HTTP 与全量回归测试，不只验证 import 成功。

### 7.8 Skill 安全与唯一来源

- Skill 只保留 instructions、references 和声明性 metadata，不加入带凭据的连接脚本。
- `.codex/skills` 到 `.agents/skills` 的迁移必须先验证发现和触发，再确定唯一权威位置。
- 同名双副本视为验收失败，避免规则漂移和不确定触发。
- MCP 不可用时降级必须显式说明；禁止冒充 MCP 已调用或 live Neo4j 已验证。

---

## 8. 验证设计

### 8.1 测试层级

1. **模型单元测试**：字段白名单、互斥 scope、非法 ID、固定 `write_back=false`、输出 Schema。
2. **工具单元测试**：六个工具分别生成正确 QARequest，仅调用一次 fake QAService，并保留事实分层。
3. **runtime 单元测试**：生产装配顺序、fake 注入、部分失败清理、正常与重复关闭。
4. **MCP in-memory 合约测试**：initialize、tools/list、tools/call、structuredContent、TextContent、isError、annotations、instructions。
5. **STDIO 子进程 smoke**：真实启动 server，完成握手、发现、一次 fake 调用和关闭；验证 stdout 无协议外输出。
6. **Skill 验证**：frontmatter/资料完整性、单一权威路径、显式和隐式触发、工具选择、透明降级、事实分层。
7. **现有回归**：第一阶段 QA/CLI、第二阶段 HTTP 和项目全量测试继续通过。
8. **live Neo4j 集成**：只有实际连接 disposable 测试库并执行成功时标记为 live verified。

### 8.2 架构保护测试

测试或静态扫描应保护：

- `qa_mcp_*` 不导入 HTTP adapter、CLI 脚本、QueryService、repository 或 Neo4j session/Cypher 执行入口。
- MCP server import 不读取环境、不创建 driver。
- 六个工具外部 Schema 不出现 `write_back`、Cypher、credentials 或 payload。
- 所有 handler 只通过 QAService 执行业务。
- 同一仓库不存在两个同名 `drawing-graph-operator` Skill 权威副本。

### 8.3 验收状态报告

最终报告必须分别列出：

| 证据 | 可证明 | 不可证明 |
|---|---|---|
| 单元/合约测试 | 模型、映射和协议合同 | 真实数据库可用性 |
| STDIO smoke | 子进程协议链路和输出纯净 | live Neo4j 数据正确性 |
| Skill 验证 | 发现、触发和操作规则 | MCP server 已连接真实库 |
| HTTP 回归 | 第二阶段兼容性 | MCP transport 可用性 |
| live Neo4j 集成 | 真实测试库链路 | 生产环境安全与容量 |

被跳过的集成测试必须写为“未验证”，不能计入通过数。

---

## 9. 设计决策摘要

| 决策 | 选择 | 原因 |
|---|---|---|
| 首版传输 | STDIO | 符合本机 Codex 场景，无新增网络暴露 |
| MCP 业务入口 | `DrawingGraphQAService.ask()` | 复用现有问题路由、证据聚合和只读控制 |
| 工具颗粒度 | 六个窄口径工具 | 比万能问答工具更易选择、更易约束 scope |
| MCP 与 HTTP | 同级 adapter | 避免 adapter 调 adapter 和双重错误/认证/序列化 |
| 输出 | structuredContent + 同源简短 TextContent | 同时满足机器消费和人类可读，并避免事实漂移 |
| 写回 | 首版完全不提供 | 降低 Agent 误操作风险，保持第三阶段范围 |
| Skill 定位 | 操作策略和解释层 | 与 MCP 的机器协议职责互补，不复制业务逻辑 |
| Skill 路径 | 验证后迁移到 `.agents/skills`，单一权威副本 | 兼顾当前环境兼容性和新标准位置 |
| 共享重构 | 不新增通用 adapter/runtime 基类 | 当前复用收益不足，容易耦合不同生命周期 |
| 数据模型 | 不变 | 第三阶段是适配与操作层增强，不是图谱领域变更 |

本设计的关键结论是：第三阶段只在 QAService 外增加一个薄的、默认只读的 MCP adapter，并强化 Skill 的选择与解释能力。现有领域、facade、HTTP、CLI 和 Neo4j Schema 均保持原设计，不为未来功能提前重构。

---

## 10. 技术依据

- [OpenAI Codex MCP documentation](https://developers.openai.com/codex/mcp)：Codex 支持本地 STDIO 和 Streamable HTTP MCP server，项目可配置 MCP，server 可提供跨工具 instructions。
- [OpenAI Codex Skills documentation](https://developers.openai.com/codex/skills)：Skill 使用渐进披露资料，仓库级标准位置为 `.agents/skills`，并可声明 MCP tool dependency；同名 Skill 不自动合并。
- [MCP specification schema](https://modelcontextprotocol.io/specification/2025-11-25/schema)：Tool 支持 inputSchema、outputSchema、structuredContent、isError 和只读/破坏性/开放世界 annotations；annotations 是提示而非安全保证。
- [MCP Python SDK server documentation](https://py.sdk.modelcontextprotocol.io/server/)：官方 SDK 提供 STDIO、工具注册及 server 生命周期能力。
- [MCP Python SDK testing documentation](https://py.sdk.modelcontextprotocol.io/testing/)：可通过内存连接的 server/client session 做协议级测试。
