# Tool Facade 模块边界

本文记录当前代码已经落地的模块职责、新接口、新依赖、数据变化和架构变化。它只描述当前 Python 应用层实现和薄 CLI/HTTP/MCP adapter，不把未实现的 OCR、Ava 专有 adapter 或全量自动语义扫描写成已完成能力；HTTP API 与本地只读 MCP adapter 已实现并记录于本文件。

单页端到端 CLI 验收证据记录在 `docs/acceptance/E2E_CLI_ACCEPTANCE.md`；333 页全量数据导入、离线派生关系增强、Neo4j 计数、CLI 抽样和 live Neo4j 回归验收证据记录在 `docs/acceptance/FULL_DATA_ACCEPTANCE.md`；面向使用者的最短运行流程记录在 `docs/acceptance/USER_RUNBOOK.md`。

## 1. 新模块职责

- `src/drawing_graph/tool_models.py`：定义 Tool facade 使用的稳定 DTO 和错误契约，包括 `DrawingSetSummary`、`PageSummary`、`PageSourceFacts`、`ElementEvidence`、`BlockTrace`、`BlockRelations`、`CandidateRelationSummary`、`CandidateReviewSummary`、`SemanticObservationSummary`、`SemanticInterpretationSummary`、`SemanticPayloadSummary`、`SectionMatchSummary` 和 `SemanticCandidateRelationSummary`。DTO 不暴露 Neo4j driver、session、transaction 或 Cypher。
- `src/drawing_graph/query_ports.py`：定义只读 `DrawingGraphReadPort`，并提供 fake port。facade 通过这个业务 port 查询图纸册、页面、页面来源事实、图块追溯和图块关系。
- `src/drawing_graph/query_port_adapter.py`：把现有 `QueryService` 的 dict 输出投影为 Tool DTO，保留 `QueryService` 当前 Neo4j 查询实现，不重写查询层。
- `src/drawing_graph/source_fact_query.py`：把单页图片、尺寸、元素 bbox 和 source label 投影为 `PageSourceFacts`；`Neo4jPageSourceFactReader` 为 `create_neo4j_tool_facade()` 提供默认真实 Neo4j 页面来源事实读取。
- `src/drawing_graph/tool_facade.py`：实现 `DrawingGraphToolFacade`，作为后续 Tool adapter 或 Skill 前面的应用门面；它统一 `write_back=false` 默认策略、dry-run 识别、只读查询、候选关系查询和候选审核写回入口。
- `src/drawing_graph/semantic_models.py`：定义 `TextObservation`、`BlockInterpretation`、`BasicInfoInterpretation`、`TableInterpretation`、`RecognitionRunSummary` 和语义状态。`RecognitionRun` 图谱外，`TextObservation` 图谱内，三类 `Interpretation` 同样图谱内，二者仅通过 `recognition_run_id` 关联。
- `src/drawing_graph/semantic_client.py`：定义多模态识别客户端协议和 fake client；当前不默认调用真实外部模型供应商。
- `src/drawing_graph/semantic_service.py`：编排按需语义识别、图像输入构造、缓存复用和写回。`write_back=false` 时返回 dry-run 临时结果，`write_back=true` 时才写入 run log 和 semantic repository；识别失败会记录 failed run。
- `src/drawing_graph/recognition_run_log.py`：定义图谱外 `RecognitionRun` 日志 port 和内存实现，支持 `recognition`、`interpretation`、`candidate_review` 三类 run。
- `src/drawing_graph/semantic_repository.py`：定义 `TextObservation` 与三类 `Interpretation` 的语义证据 repository port、受控断面匹配读写 port，并提供内存实现。
- `src/drawing_graph/semantic_neo4j_repository.py`：以稳定 ID 幂等写入图谱内语义节点和 `HAS_OBSERVATION`、`HAS_INTERPRETATION`、`SUPPORTED_BY` 边；旧 interpretation 按 cache key 标记 `stale`，不静默覆盖；不创建 `RecognitionRun` 节点。
- `src/drawing_graph/semantic_cache.py`：生成 observation/interpretation/断面匹配的确定性 cache key，并提供内存缓存服务。
- `src/drawing_graph/semantic_payload_store.py`：提供不可变 payload 存储和 `payload_ref`，避免把大嵌套 JSON 塞进 Neo4j 节点属性。
- `src/drawing_graph/semantic_image_inputs.py`：根据 `PageSourceFacts` 构造单个元素的图片、bbox、图片 hash 和上下文引用；不调用模型、不写图谱。
- `src/drawing_graph/semantic_schema.py`：定义语义节点标签、关系类型、约束、索引和来源标签白名单的静态规格。
- `src/drawing_graph/semantic_query_projection.py`：组合来源事实、派生关系、observation、interpretation、run log 和候选/正式关系，输出明确区分 `fact_kind` 的稳定查询结果。
- `src/drawing_graph/section_label_normalization.py`：把断面端点标签规范化为 `alphabetic`、`roman`、`numeric`、`alphanumeric` 或 `unknown`，生成逻辑键；默认不合并 `I-I`、`Ⅰ-Ⅰ`、`1-1`。
- `src/drawing_graph/section_alias_rules.py`：管理图谱外 `SectionLabelAliasRule`，只有 `confirmed` 且 scope 命中的规则参与确定匹配。
- `src/drawing_graph/section_match_service.py`：基于双方可比较 `TextObservation` 生成 `CANDIDATE_MATCHES_SECTION_CAPTION` 候选；仅在逻辑键一致、候选唯一且无冲突时给出正式匹配判断。
- `src/drawing_graph/tool_factory.py`：集中创建 facade 依赖；`create_tool_facade()` 装配内存语义依赖用于本地/单元测试，`create_neo4j_tool_facade(driver, source_fact_reader=None, config=None)` 用外部注入的 driver 装配 `QueryServiceReadPortAdapter`、`SemanticNeo4jRepository`、`RelationRepositoryCandidateRelationPort`、`RelationRepositorySectionMatchPort`、`RelationRepositorySectionMatchQueryPort` 和候选复核写回服务；模块 import 和工厂创建时不创建 Neo4j driver、不主动连接数据库、不扫描数据目录。
- `scripts/drawing_graph_tool.py`：薄 CLI adapter；它从 `ImportConfig.from_env()` 读取 Neo4j 连接配置，创建 driver 后调用 `create_neo4j_tool_facade()`，再把 facade DTO 输出为 JSON。它不保存 Neo4j 密码，不写 Cypher，不直接调用 repository、import CLI 或离线增强规则，不提供 HTTP API。
- `src/drawing_graph/qa_models.py`：定义 QA 层稳定数据契约，包括 `QuestionType`、`QAScope`、`QARequest`、`EvidenceRef`、`AnswerFact`、`QAAnswer`、`QAError` 和 `QAErrorCode`；DTO 不暴露 Neo4j driver、session、transaction 或 Cypher，`fact_kind` 严格区分来源事实、派生关系、语义观察、语义解释、候选关系、正式关系和诊断/未支持条目。
- `src/drawing_graph/qa_service.py`：实现 `DrawingGraphQAService`，作为 facade 外侧的问答编排层；只接收注入的 facade，负责问题类型路由、scope 校验、write-back 禁止、调用 facade 聚合证据并返回结构化 `QAAnswer`。
- `src/drawing_graph/qa_rendering.py`：将结构化 `QAAnswer` 渲染为简短中文文本，供 CLI `--format zh-brief` 使用；只读取 `QAAnswer`，不调用 facade、不访问 Neo4j，JSON 仍是权威输出。
- `src/drawing_graph/qa_serialization.py`：提供 CLI 与 HTTP 共用的框架无关 JSON 转换（`to_jsonable`）、成功/失败 envelope 和共享错误脱敏（`sanitize_error_message`）；不依赖 FastAPI、Pydantic 或 Neo4j，不读取环境变量。
- `src/drawing_graph/qa_http_models.py`：定义 HTTP 协议模型（`HttpQARequest`、`HttpQAScope`、响应模型和 health 模型），使用严格字段白名单拒绝未知与敏感字段，并把请求转换为领域 `QARequest`（固定 `format_hint="json"`）。
- `src/drawing_graph/qa_http_runtime.py`：管理 driver、`DrawingGraphToolFacade` 与 `DrawingGraphQAService` 的进程内装配和幂等关闭；只有 runtime 与启动脚本知道 Neo4j driver。
- `src/drawing_graph/qa_http.py`：FastAPI 应用工厂 `create_app(config, runtime_factory)`；负责 request ID 与安全响应头、可选 Bearer 认证、显式 CORS、请求体大小限制、并发上限与等待超时、统一错误 envelope、版本化只读路由和 health endpoint；模块 import 无副作用。
- `scripts/serve_drawing_graph_qa.py`：单 worker Uvicorn 启动入口，只从环境变量读取 `QAHttpConfig` 并启动 `create_app()` 应用；不接受密码、token 或 API key 命令行参数。
- `scripts/drawing_graph_qa.py`：薄 QA CLI adapter；从环境变量读取 Neo4j 配置，创建 driver 和 facade，再调用 `DrawingGraphQAService.ask()`，支持 JSON 与简短中文输出。它只做参数解析、连接生命周期、错误脱敏和输出渲染，不直接调用 `QueryService`、`RelationRepository`、Cypher 或底层导入/增强脚本。
- `src/drawing_graph/qa_mcp_models.py`：定义 MCP adapter 自有的六个输入模型、`McpResultMeta`/`McpQAError`/`McpQASuccess`/`McpQAFailure`/`McpToolOutcome` 输出模型和到 `QARequest` 的单向转换；传输语义不进入领域层。
- `src/drawing_graph/qa_mcp_tools.py`：实现 `DrawingGraphMCPTools(service)` 与六个只读工具 handler；每个 handler 只调用一次 `DrawingGraphQAService.ask()`，并从同一 `QAAnswer` 生成 structuredContent 与简短 TextContent。
- `src/drawing_graph/qa_mcp_runtime.py`：实现 `QAMcpRuntime` 与 `create_qa_mcp_runtime(config, ...)`，管理 driver、`DrawingGraphToolFacade`、`DrawingGraphQAService` 的装配、失败清理和幂等关闭；支持 fake factory 注入。
- `src/drawing_graph/qa_mcp_server.py`：实现无 import 副作用的 `create_mcp_server(tools)`，配置 `drawing-graph-qa` server instructions、六个工具 Schema 和只读 annotations；只提供 Tools capability。
- `scripts/serve_drawing_graph_mcp.py`：本地 STDIO MCP 唯一进程入口；`main()` 负责加载 `QAMcpConfig`、装配 runtime/tools/server、运行官方 STDIO transport，stdout 只承载协议帧；不接受 host、port、worker、HTTP token 或远程 transport 参数。

既有模块仍保持原职责：`src/drawing_graph/block_relation_enrichment.py` 负责离线派生关系计算，`src/drawing_graph/relation_repository.py` 负责受控关系写入、候选提升、候选关系读取、断面匹配读取和 `RelationRepositorySectionMatchPort` 适配，`src/drawing_graph/relation_service.py` 负责编排显式离线增强，`src/drawing_graph/candidate_review.py` 保留 `CandidateReviewService.review_candidate_group`、三态审核和硬规则。`scripts/review_candidate_relations.py` 仍是显式候选关系 AI 复核 CLI 入口；复核记录使用 `review_run_id` 回查一次复核运行。

## 2. 新接口

- `DrawingGraphToolFacade.list_drawing_sets(project_id, limit=100)`：只读列图纸册。
- `DrawingGraphToolFacade.list_pages(drawing_set_id, limit=100)`：只读列页面。
- `DrawingGraphToolFacade.get_page_source_facts(page_id, element_types=None, include_image_meta=True)`：只读返回单页来源事实。
- `DrawingGraphToolFacade.get_block_trace(block_id)` 和 `DrawingGraphToolFacade.get_block_relations(block_id)`：只读返回图块证据链和关系 ID。
- `DrawingGraphToolFacade.recognize_page_semantics(page_id, target_types, model_profile, prompt_version, write_back=False)`：默认 `write_back=false` dry-run；只有显式 `write_back=true` 才持久化。
- `DrawingGraphToolFacade.get_recognition_run(recognition_run_id)`：查询图谱外 `RecognitionRun` 日志。
- `DrawingGraphToolFacade.list_text_observations(page_id|element_id|recognition_run_id, statuses=None)`：查询图谱内 `TextObservation`，经 `SemanticQueryProjection` 返回 `SemanticObservationSummary`。
- `DrawingGraphToolFacade.list_interpretations(page_id|element_id|recognition_run_id, statuses=None)`：查询三类结构化解释，经投影返回 `SemanticInterpretationSummary`。
- `DrawingGraphToolFacade.get_semantic_payload(payload_ref)`：只读返回不可变解析 JSON，包含 `payload_ref`、content hash 和契约版本。
- `DrawingGraphToolFacade.match_section_caption(cross_section_id, page_id=None, write_back=False)`：dry-run 返回候选/正式匹配判断；`write_back=true` 且服务判断允许时，才写入 `CANDIDATE_MATCHES_SECTION_CAPTION` 或 `MATCHES_SECTION_CAPTION`。
- `DrawingGraphToolFacade.list_section_matches(cross_section_id=None, page_id=None, statuses=None)`：只读查询断面候选/正式匹配投影。
- `DrawingGraphToolFacade.list_candidate_relations(page_id=None, block_id=None, relation_type=None, status=None)`：只读查看候选关系，候选关系不是正式事实。
- `DrawingGraphToolFacade.review_candidate_relation(...)`：显式审核候选关系；`write_back=false` 只返回 dry-run 结果，`write_back=true` 才通过 `CandidateReviewService` 和硬规则写回。
- `create_neo4j_tool_facade(driver, source_fact_reader=None, config=None)`：用调用方提供的 Neo4j driver 创建真实端口装配的 facade；它不接收 Neo4j URI、用户、密码或供应商密钥，连接生命周期仍由调用方管理。
- `scripts\drawing_graph_tool.py list-drawing-sets|list-pages|page-source-facts|block-trace|block-relations|list-text-observations|list-interpretations|list-candidate-relations|list-section-matches`：当前已落地的 CLI 调用入口，参数映射到 facade 只读查询方法并输出 JSON；命令失败时返回结构化错误 category，低层 Neo4j/Cypher/密钥细节会被清洗。
- `DrawingGraphQAService(facade)` 与 `DrawingGraphQAService.ask(request) -> QAAnswer`：QA 编排唯一入口；`request` 必须是 `QARequest`，`write_back=true` 会被 `WRITE_BACK_FORBIDDEN` 拒绝，第一阶段只读。
- `scripts\drawing_graph_qa.py ask-page|ask-block|ask-candidates|ask-section|ask-table-caption|diagnose`：QA CLI 子命令，映射到 `page_summary`、`block_relations`、`candidate_relations`、`section_matches`、`table_caption_status`、`diagnostic_status`；`--format json` 为默认输出，`--format zh-brief` 输出简短中文。
- `QAHttpConfig`（`src/drawing_graph/config.py`）：HTTP 专用不可变配置；默认 `127.0.0.1:8000`、`allow_remote=false`、空 CORS、65536 bytes、30 秒、8 并发、docs 关闭；非 loopback 必须 `allow_remote=true` 且配置 token；password 与 token 在 `repr` 中屏蔽。
- `create_app(config, runtime_factory=create_qa_http_runtime)`：创建无 import 副作用的 FastAPI 应用；lifespan 启动时创建一次 runtime、关闭时关闭一次 driver。
- `POST /api/v1/drawing-qa/ask` 与六个便捷 GET 路由（页面摘要、图块关系、候选关系、断面匹配、表格标题状态、诊断状态）：只构造 `QARequest` 并调用 `DrawingGraphQAService.ask()`，不直接调用 facade 方法。
- `GET /health/live` 与 `GET /health/ready`：健康检查；ready 在 runtime 已装配时返回 `neo4j_status="not_checked"`，未装配返回 503。
- `RelationRepository.update_candidate_review` 与 `RelationRepository.promote_candidate_relation` 仍是底层受控写回接口，不由 Tool adapter 直接调用。
- `QAMcpConfig`（`src/drawing_graph/config.py`）：MCP 专用不可变配置，只包含 `neo4j_uri`、`neo4j_user`、`neo4j_password` 和 `log_level`；`from_env()` 读取 `NEO4J_URI`、`NEO4J_USER`、`NEO4J_PASSWORD` 与可选 `DRAWING_GRAPH_QA_MCP_LOG_LEVEL`，不复用 HTTP host/port/CORS/docs 配置。
- `create_qa_mcp_runtime(config, driver_factory=None, facade_factory=None, service_factory=None)`：按 driver -> facade -> QAService 顺序装配，支持 fake 注入，初始化失败时逆序清理，`close()` 幂等。
- `create_mcp_server(tools: DrawingGraphMCPTools)`：返回未启动的 `drawing-graph-qa` server；只注册六个只读工具，不注册 Resources/Prompts/Sampling。
- `DrawingGraphMCPTools.ask_drawing_page|ask_drawing_block|list_drawing_candidates|get_section_match_status|get_table_caption_status|get_drawing_diagnostics`：六个只读 handler，固定 `write_back=false` 且 `include_payload=false`，只调用一次 QAService。
- `scripts\serve_drawing_graph_mcp.py main() -> int`：唯一 STDIO 入口；正常结束返回 0，配置/装配失败返回 2，transport 失败返回 3，close 失败返回 4；stderr 只输出脱敏错误。

## 3. 新依赖

新增依赖都是项目内 Python port、fake 实现、Python 标准库 CLI/JSON 支撑，以及 HTTP adapter 所需的 FastAPI、Uvicorn 和 HTTPX：`DrawingGraphReadPort`、`MultimodalRecognitionClient`、`RecognitionRunLogPort`、`SemanticEvidenceRepositoryPort`、`SectionMatchWritePort`、`SectionMatchQueryPort`、`SemanticCacheService`、`SemanticPayloadStore`，以及 QA 层的 `QARequest`、`QAAnswer`、`AnswerFact`、`EvidenceRef` 等 QA DTO。第三阶段新增官方 MCP Python SDK（`requirements.txt`：`mcp>=1.29.0,<2.0`）作为本地 STDIO MCP adapter 依赖；未新增真实云模型 SDK、Ava 专有 SDK 或第二套 Web/任务队列依赖。

`ToolFacadeConfig` 只接收 `default_write_back`、`model_profile`、`prompt_version`、`run_log_path`、`run_log_store`、`payload_store`、`semantic_repository`、`cache_store`、`section_match_rule_version` 等受控配置，不接收 Neo4j 密码、供应商 API key、token 或 secret。真实 Neo4j 集成测试仍需要单独配置 `NEO4J_TEST_URI`、`NEO4J_TEST_USER` 和 `NEO4J_TEST_PASSWORD`；跳过不等于通过。

## 4. 数据变化

- 新增 Tool DTO，不改变既有 Neo4j 基础导入 schema。
- `TextObservation` 表示图谱内语义证据，记录来源元素、bbox、原文、规范化文本、置信度、状态、`recognition_run_id`、模型 profile、prompt version、图片 hash、cache key 和创建时间。
- `BlockInterpretation`、`BasicInfoInterpretation`、`TableInterpretation` 表示图谱内结构化解释，记录摘要、字段、不确定性、`payload_ref`、cache key 和契约版本；`interpreted_type` 只存在于 `BlockInterpretation`，不会写入 `DrawingBlock.block_type`。
- `RecognitionRun` 图谱外，不作为 Neo4j 节点；它记录 run type、目标范围、模型 profile、prompt version、输入范围、状态、错误、时间和可选成本摘要。
- 新增语义关系白名单：`HAS_OBSERVATION`、`HAS_INTERPRETATION`、`SUPPORTED_BY`、`CANDIDATE_MATCHES_SECTION_CAPTION`、`MATCHES_SECTION_CAPTION`；Schema 脚本使用 `IF NOT EXISTS` 创建约束和索引。
- 断面匹配：`SectionLabelNormalizer` 生成 `SECTION_ALPHA_*`、`SECTION_ROMAN_*`、`SECTION_NUMERIC_*`、`SECTION_ALPHANUMERIC_*` 逻辑键；跨符号体系必须命中已确认别名规则；没有双方可比较 observation 或候选不唯一时不建立正式边。
- 候选关系保持 candidate 语义，`CandidateRelationSummary.fact_kind` 固定为 `candidate`。`matched_candidate` 和候选边不是正式事实。
- 既有 `DrawingPage -[:USES_BASIC_INFO]-> DrawingBasicInfo`、`BlockCaption -[:CANDIDATE_CAPTION_OF]-> DrawingBlock`、`DrawingBlock -[:CANDIDATE_HAS_SECTION_MARK]-> CrossSection` 语义保持不变，候选关系 AI 复核是独立显式流程，不自动触发候选关系 AI 复核。
- MCP 接入不改变 Neo4j 数据模型，也不改变 QA 领域 DTO（`QARequest`/`QAAnswer`）；MCP 输入/输出模型只存在于 adapter 层，不写入领域模块。

## 5. 架构变化

当前依赖方向是：薄 CLI adapter 或项目级 Skill（`.codex\skills\drawing-graph-operator\`）-> `DrawingGraphToolFacade` -> read port / semantic service / run log port / semantic repository / section match service / candidate review service -> 受控 repository。facade 不写 Cypher，不创建 Neo4j driver，不调用 CLI 脚本，不直接调用 `block_relation_enrichment.py` 的规则函数。Neo4j 生产装配由 `create_neo4j_tool_facade()` 完成；`scripts\drawing_graph_tool.py` 只在最外层读取环境变量、创建 driver、关闭 driver 并输出 JSON，driver 和 secret 仍由外部运行环境提供。

QA 编排层位于 facade 外侧，CLI、HTTP 与 MCP 是同级 adapter，依赖方向固定为 `QA adapter -> DrawingGraphQAService -> DrawingGraphToolFacade -> ports/services -> repository/Neo4j`（HTTP 对应 `HTTP adapter -> DrawingGraphQAService -> DrawingGraphToolFacade -> ports/services -> repository/Neo4j`，MCP 对应 `MCP adapter -> DrawingGraphQAService -> DrawingGraphToolFacade -> ports/services -> repository/Neo4j`）。`scripts\drawing_graph_qa.py`、`scripts\serve_drawing_graph_qa.py` 与 `scripts\serve_drawing_graph_mcp.py` 是最外层 adapter，`DrawingGraphQAService` 只通过 `DrawingGraphToolFacade` 获取图谱信息，默认 `write_back=false`，不写 Cypher、不持久化语义证据、不提升候选关系。HTTP 默认 loopback、单 worker、只读，CORS 与 OpenAPI docs 默认关闭；`/health/ready` 的 `neo4j_status="not_checked"` 不等于 live Neo4j 验证。本地只读 STDIO MCP adapter 已实现；首版不实现 Streamable HTTP，远程认证、OAuth、RBAC、TLS、多 worker、HTTP 写回与 plugin 发布仍未实现。Ava 专有 adapter、OCR、真实模型供应商和数据库 schema 变更也仍未实现。

Skill 与 MCP 分工：`drawing-graph-operator` Skill 是 facade 外侧的操作策略层，负责自然语言路由、多问题拆分、工具选择、透明降级和结果解释；MCP adapter 负责协议初始化、工具 Schema、annotations 与 STDIO 生命周期。Skill 不创建 driver、不执行 Cypher、不调用 repository 写回，也不承载图谱业务逻辑。

`write_back=false` 是默认安全边界。dry-run 识别可以返回临时 `recognition_run_id`、observation 和 interpretation，但不保证之后可查询。`write_back=true` 时才写入图谱外 run log、图谱内语义证据或受控语义边；候选关系即使 accepted，也必须通过 `CandidateReviewService.review_candidate_group` 的硬规则后才可能调用 `RelationRepository.promote_candidate_relation`。断面匹配的正式边同样只在逻辑键一致、候选唯一且无冲突时写入。

## 6. Skill 资产职责

`.codex/skills/drawing-graph-operator/` 是项目级 Codex Skill（操作层），位于 `DrawingGraphToolFacade` 外侧，包含 `SKILL.md`、`agents/openai.yaml` 和六个 references：`project-boundaries.md`、`facade-workflows.md`、`verification.md`、`output-contract.md`、`qa-workflows.md`、`mcp-boundaries.md`。权威路径由 Task 39 验证后仍为 `.codex/skills/drawing-graph-operator`；Task 40 的 MCP 工具依赖声明为宿主兼容性待办，未验证前不宣称依赖发现已通过。

- 职责：指导 Codex 先读当前项目文档和受影响源码、只经 facade 或薄 CLI adapter 使用图谱能力、默认 `write_back=false`、分层输出事实、如实报告验证状态。
- 它不属于 `src/drawing_graph/` 业务模块，不改变运行时图谱能力，也不是 Agent Skill、MCP Tool adapter、HTTP API 或文件 watcher。
- 静态边界由 `tests/test_skill_docs.py` 保护，运行 `python -m unittest tests.test_skill_docs -v`。
