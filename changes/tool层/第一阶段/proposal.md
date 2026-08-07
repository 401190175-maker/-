# Tool 层 QA 编排提案

## 1. 背景

当前图块图谱项目已经形成较完整的底层能力：基础导入负责把 XAnyLabeling JSON/PNG 写入 Neo4j 来源事实层，离线派生关系增强负责补写表格标题、图块标题、基础信息上下文、注释和断面标记关系，候选关系复核骨架负责处理 `accepted`、`rejected`、`unresolved` 三态结果，`DrawingGraphToolFacade` 已经作为稳定应用门面统一封装只读查询、按需语义证据、候选关系查询、候选复核和断面匹配能力。

现有 facade 和薄 CLI adapter 已经解决了“如何安全调用图谱能力”的问题，但还没有解决“如何面向用户问题组织答案”的问题。用户现在想问的不是底层接口名，而是更接近自然语言或业务问题的问答，例如“这页有什么”“这个 block 有哪些关系”“有没有候选关系”“断面有没有匹配”“表格标题状态如何”。这类问题需要一个介于 Codex Skill / CLI / HTTP / MCP 和 `DrawingGraphToolFacade` 之间的问答编排层。

本变更的目标是新增 Tool 层中的 QA 编排能力，第一阶段重点建设 `DrawingGraphQAService` 与薄 QA CLI。它不重做图谱、不重写 facade、不直接访问 Neo4j，而是在现有 facade 之上识别问题类型、调用已有能力、聚合证据并返回结构化 answer。

## 2. 当前问题

当前系统的主要问题不是底层图谱能力不足，而是缺少面向问答场景的稳定编排和适配层。

具体问题如下：

1. 用户问题与 facade 方法之间缺少映射层。`DrawingGraphToolFacade` 已经提供 `get_page_source_facts()`、`get_block_trace()`、`get_block_relations()`、`list_candidate_relations()`、`list_section_matches()` 等能力，但用户仍需要知道底层 ID、命令和接口组合方式。
2. 当前薄 CLI adapter 偏底层工具调用。`scripts/drawing_graph_tool.py` 更适合列页面、查 block 关系、查 observation 等原子能力，不适合直接回答“这页整体有什么”或“这个 block 当前关系状态如何”这类聚合问题。
3. 答案输出缺少统一结构。现有 facade 返回 DTO，但还没有面向 QA 的 `QAAnswer` 契约来统一表达 `source_fact`、`derived_relation`、`semantic_observation`、`semantic_interpretation`、`candidate_relation` 和 `formal_relation`。
4. 候选关系容易被误读。用户问“有没有匹配”或“有没有关系”时，如果没有 QA 层统一标注事实类型，`CANDIDATE_*`、`matched_candidate` 或模型观察容易被误表述为正式事实。
5. HTTP、MCP、Codex Skill 强化缺少共同业务入口。如果后续 Ava、网页、Codex Skill 或 MCP adapter 分别直接调用 facade 并各自组织答案，会产生重复逻辑和输出不一致。
6. 部分业务问题仍是能力缺口。比如 `table_caption_status` 可以基于现有表格标题关系和页面来源事实推导，但当前 facade 没有一个专门面向 QA 的表格标题状态查询；第一版需要通过 QA 层显式记录支持程度和缺口，而不是绕过 facade 直接写 Cypher。

## 3. 功能目标

本变更的功能目标是建立一个默认只读、可追溯、可被 CLI/HTTP/Skill/MCP 复用的 QA 编排层。

第一阶段目标：

1. 新增 `DrawingGraphQAService`，作为 `DrawingGraphToolFacade` 外侧的问答编排服务。
2. 定义稳定的 QA 数据契约，包括问题类型、请求范围、结构化 answer、事实条目、证据引用、warning 和 unsupported 部分。
3. 支持最小问题类型：
   - `page_summary`：回答页面包含哪些来源事实、元素、语义证据状态。
   - `block_relations`：回答单个 `DrawingBlock` 的追溯链路、正式派生关系、候选关系和增强状态。
   - `candidate_relations`：回答指定页面或 block 下有哪些候选关系，以及候选状态、证据和冲突原因。
   - `section_matches`：回答断面与标题的候选/正式匹配状态，并保留逻辑键、符号体系和 evidence。
   - `table_caption_status`：回答页面或表格标题的派生状态；当前 facade 能力不足时明确返回缺口，不直接绕过 facade。
4. 增加保守问题类型：
   - `unknown_or_unsupported`：无法安全映射的问题，返回不支持原因。
   - `diagnostic_status`：回答页面或 block 是否导入、是否增强、是否存在语义证据、哪些验证未执行。
5. 新增薄 QA CLI，例如 `scripts/drawing_graph_qa.py`，支持 `ask-page`、`ask-block`、`ask-candidates` 等命令。
6. 支持 JSON 输出和简短中文输出；业务核心输出以结构化 answer 为准，不把自然语言渲染写死在服务层。
7. 默认 `write_back=false`，QA 查询不写数据库、不持久化语义证据、不提升候选关系。

第二阶段目标：

1. 基于 QAService 增加 HTTP API，供 Ava、网页或其他本地软件调用。
2. HTTP 层只做请求校验、连接生命周期、错误脱敏和 JSON 序列化，不实现重复业务逻辑。
3. 环境变量仍由运行环境提供，Neo4j 密码和模型密钥不进入请求体或文档。

第三阶段目标：

1. 强化 `.codex/skills/drawing-graph-operator/`，增加自然语言问题到 QA 能力的映射说明。
2. 可选新增 MCP Tool adapter，只暴露少量稳定 QA 工具，不暴露任意 Cypher、repository 或内部 facade 细节。

## 4. 修改范围

第一阶段建议修改范围：

| 类型 | 文件或位置 | 修改内容 |
|---|---|---|
| 新增 | `src/drawing_graph/qa_models.py` | 定义 `QuestionType`、`QARequest`、`QAAnswer`、`AnswerFact`、`EvidenceRef`、QA 错误分类和输出状态 |
| 新增 | `src/drawing_graph/qa_service.py` | 实现 `DrawingGraphQAService`，负责问题类型路由、调用 `DrawingGraphToolFacade`、聚合证据和生成结构化 answer |
| 新增 | `scripts/drawing_graph_qa.py` | 提供薄 QA CLI，读取环境变量、创建 facade、调用 QAService、输出 JSON 或简短中文 |
| 新增 | `tests/test_qa_models.py` | 覆盖 QA DTO、非法问题类型、空 ID、事实类型和证据字段校验 |
| 新增 | `tests/test_qa_service.py` | 使用 fake facade 覆盖 `page_summary`、`block_relations`、`candidate_relations`、`section_matches`、`table_caption_status` 和 unsupported 场景 |
| 新增 | `tests/test_qa_cli.py` | 覆盖 CLI 参数、错误输出、JSON 输出和简短中文输出 |
| 修改 | `README.md` | 实现后补充 QA CLI 的最短使用说明，并声明不是 HTTP/MCP |
| 修改 | `Module.md` | 实现后记录 QA 模块职责、新接口、新依赖和边界 |
| 修改 | `architecture.md` | 实现后把 QAService 描述为 facade 外侧的编排层，不写成底层图谱能力 |
| 可选修改 | `.codex/skills/drawing-graph-operator/references/qa-workflows.md` | 第三阶段强化 Skill 时新增自然语言到 QA 工具的映射说明 |

第二阶段建议修改范围：

| 类型 | 文件或位置 | 修改内容 |
|---|---|---|
| 新增 | `src/drawing_graph/qa_http.py` 或独立 `api/drawing_qa.py` | 基于 QAService 暴露最小 HTTP API |
| 新增 | `tests/test_qa_http.py` | 覆盖 HTTP 请求校验、错误脱敏、只读边界和响应结构 |
| 修改 | `requirements.txt` | 如采用 FastAPI 或其他 HTTP 框架，新增必要依赖 |
| 修改 | `README.md` / `Module.md` / `architecture.md` | 实现后同步 HTTP 当前状态 |

第三阶段建议修改范围：

| 类型 | 文件或位置 | 修改内容 |
|---|---|---|
| 修改 | `.codex/skills/drawing-graph-operator/SKILL.md` | 加入 QAService / QA CLI 的推荐使用边界 |
| 新增或修改 | `.codex/skills/drawing-graph-operator/references/qa-workflows.md` | 描述自然语言问题到 `question_type` 的映射 |
| 可选新增 | MCP Tool adapter 相关文件 | 仅在单独确认 MCP 方案后新增 |

## 5. 不包含范围

本变更不包含以下内容：

1. 不重做 Neo4j 数据库设计，不新增第一阶段 schema。
2. 不修改基础导入流程，不让 `scripts/import_json.py` 自动触发离线增强、语义识别或 QA。
3. 不修改离线派生关系增强流程，不让 `scripts/enrich_block_relations.py` 默认触发候选关系 AI 复核或多模态识别。
4. 不直接创建 Neo4j driver、不直接写 Cypher、不直接调用 repository 写回方法。
5. 不绕过 `DrawingGraphToolFacade` 调用底层 `QueryService`、`RelationRepository` 或 `block_relation_enrichment.py` 规则函数。
6. 不把 `CANDIDATE_*`、`matched_candidate`、模型 observation 或 interpretation 表述为正式事实。
7. 不覆盖来源事实节点，不把模型输出写入 `DrawingBlock.block_type`。
8. 不把 `RecognitionRun` 建成 Neo4j 节点；它仍是图谱外运行日志。
9. 不实现全量自动语义扫描。
10. 不实现 OCR；未来 OCR 应作为独立离线 enrichment 另行设计。
11. 不默认接入真实云多模态模型供应商；第一阶段测试仍使用 fake facade、fake port 或 fake client。
12. 不封装真实 `data/`、PNG/JSON、Neo4j 数据、`.env`、Neo4j 密码、供应商 API key、token 或 secret。
13. 第一阶段不实现 HTTP API、MCP Tool adapter 或 Ava 对接；这些属于后续阶段。
14. 不把 Codex Skill 当作业务逻辑本体；Skill 只负责工作流和操作约束。

## 6. 影响模块

### 6.1 直接影响模块

| 模块 | 影响 | 说明 |
|---|---|---|
| `src/drawing_graph/qa_models.py` | 新增 | QA 层对外契约，定义问题类型、请求、结构化 answer 和证据字段 |
| `src/drawing_graph/qa_service.py` | 新增 | QA 编排核心，只依赖 `DrawingGraphToolFacade` 和 QA DTO |
| `scripts/drawing_graph_qa.py` | 新增 | QA CLI adapter，负责参数解析、facade 创建、QAService 调用和输出渲染 |
| `tests/test_qa_models.py` | 新增 | 保证 QA DTO 稳定、事实类型明确、非法输入有分类错误 |
| `tests/test_qa_service.py` | 新增 | 保证 QAService 对五类问题的聚合逻辑和只读边界 |
| `tests/test_qa_cli.py` | 新增 | 保证 CLI 参数和输出契约稳定 |

### 6.2 间接影响模块

| 模块 | 影响 | 说明 |
|---|---|---|
| `src/drawing_graph/tool_facade.py` | 间接依赖 | QAService 通过它调用已有图谱能力；原则上第一阶段不修改，除非发现缺少只读查询能力 |
| `src/drawing_graph/tool_models.py` | 间接依赖 | QAService 会消费 facade DTO，并转换为 QA answer；不应破坏既有 Tool DTO |
| `src/drawing_graph/tool_factory.py` | 间接依赖 | QA CLI 需要通过现有工厂创建 Neo4j-backed facade |
| `scripts/drawing_graph_tool.py` | 参考 | QA CLI 可参考其参数、错误脱敏和 JSON 输出方式，但不应复用其底层命令分发逻辑 |
| `src/drawing_graph/query_ports.py` / `query_port_adapter.py` | 间接依赖 | 仍由 facade 使用，QAService 不直接依赖这些 port |
| `src/drawing_graph/source_fact_query.py` | 间接依赖 | 页面来源事实通过 facade 进入 QA 输出 |
| `src/drawing_graph/semantic_query_projection.py` | 间接依赖 | QA 输出需要沿用事实分层思想，避免混淆语义证据和正式关系 |
| `src/drawing_graph/candidate_review.py` | 间接依赖 | 第一阶段只读 QA 不直接调用写回审核；后续审核型 QA 必须保留硬规则 |
| `src/drawing_graph/relation_repository.py` | 间接依赖 | 只应被 facade 和 port 适配器间接使用，QAService 不直接调用 |
| `.codex/skills/drawing-graph-operator/` | 后续影响 | Skill 强化阶段需要补充 QA 工作流说明 |
| `README.md` | 文档影响 | 实现后补充 QA CLI 使用方式和边界 |
| `Module.md` | 文档影响 | 实现后记录新增 QA 模块职责和依赖方向 |
| `architecture.md` | 文档影响 | 实现后记录 QAService 位于 facade 外侧，属于编排层 |

### 6.3 不应受影响模块

| 模块 | 原因 |
|---|---|
| `src/drawing_graph/import_service.py` | QA 层不负责导入 |
| `src/drawing_graph/neo4j_repository.py` | QA 层不写来源事实 |
| `src/drawing_graph/block_relation_enrichment.py` | QA 层不计算或改写空间规则 |
| `src/drawing_graph/relation_service.py` | QA 层不触发离线增强 |
| `scripts/import_json.py` | QA 层不改变基础导入 CLI |
| `scripts/enrich_block_relations.py` | QA 层不改变离线增强 CLI |
| `scripts/review_candidate_relations.py` | QA 层不替代显式候选复核 CLI |
| `scripts/create_schema.cypher` | 第一阶段不新增数据库 schema |

## 7. 验收判断

本 proposal 对应的第一阶段完成后，应满足：

1. `DrawingGraphQAService` 能通过 fake facade 在单元测试中回答五类核心问题。
2. QA answer 明确区分来源事实、派生关系、语义观察、语义解释、候选关系和正式关系。
3. QA CLI 能输出 JSON 和简短中文。
4. 默认不写数据库，不触发语义证据持久化，不提升候选关系。
5. 所有新增能力都通过 `DrawingGraphToolFacade` 获取图谱信息。
6. 文档明确 HTTP API、MCP Tool adapter、Ava 对接、真实模型供应商和 OCR 仍是后续范围。
