# Tool Facade 模块边界

本文记录当前代码已经落地的模块职责、新接口、新依赖、数据变化和架构变化。它只描述当前 Python 应用层实现和薄 CLI/HTTP/MCP adapter，不把未实现的 OCR、Ava 专有 adapter 或全量自动语义扫描写成已完成能力；HTTP API 与本地只读 MCP adapter 已实现并记录于本文件。

单页端到端 CLI 验收证据记录在 `docs/acceptance/E2E_CLI_ACCEPTANCE.md`；333 页全量数据导入、离线派生关系增强、Neo4j 计数、CLI 抽样和 live Neo4j 回归验收证据记录在 `docs/acceptance/FULL_DATA_ACCEPTANCE.md`；答案生成与只读总编排验收记录在 `docs/acceptance/ANSWER_GENERATION_MVP_ACCEPTANCE.md`；追溯与反馈专项验收记录在 `docs/acceptance/TRACE_FEEDBACK_ACCEPTANCE.md`；产品 adapter 验收记录在 `docs/acceptance/PRODUCT_ADAPTER_ACCEPTANCE.md`；面向使用者的最短运行流程记录在 `docs/acceptance/USER_RUNBOOK.md`。

## 1. 新模块职责

- `src/drawing_graph/tool_models.py`：定义 Tool facade 使用的稳定 DTO 和错误契约，包括 `DrawingSetSummary`、`PageSummary`、`PageSourceFacts`、`ElementEvidence`、`BlockTrace`、`BlockRelations`、`CandidateRelationSummary`、`CandidateReviewSummary`、`SemanticObservationSummary`、`SemanticInterpretationSummary`、`SemanticPayloadSummary`、`SectionMatchSummary` 和 `SemanticCandidateRelationSummary`。DTO 不暴露 Neo4j driver、session、transaction 或 Cypher。
- `src/drawing_graph/query_ports.py`：定义只读 `DrawingGraphReadPort`，并提供 fake port。facade 通过这个业务 port 查询图纸册、页面、页面来源事实、图块追溯和图块关系。
- `src/drawing_graph/query_port_adapter.py`：把现有 `QueryService` 的 dict 输出投影为 Tool DTO，保留 `QueryService` 当前 Neo4j 查询实现，不重写查询层。
- `src/drawing_graph/source_fact_query.py`：把单页图片、尺寸、元素 bbox 和 source label 投影为 `PageSourceFacts`；`Neo4jPageSourceFactReader` 为 `create_neo4j_tool_facade()` 提供默认真实 Neo4j 页面来源事实读取。
- `src/drawing_graph/tool_facade.py`：实现 `DrawingGraphToolFacade`，作为后续 Tool adapter 或 Skill 前面的应用门面；它统一 `write_back=false` 默认策略、dry-run 识别、只读查询、候选关系查询和候选审核写回入口。
- `src/drawing_graph/semantic_models.py`：定义 `TextObservation`、`BlockInterpretation`、`BasicInfoInterpretation`、`TableInterpretation`、`RecognitionRunSummary` 和语义状态。`RecognitionRun` 图谱外，`TextObservation` 图谱内，三类 `Interpretation` 同样图谱内，二者仅通过 `recognition_run_id` 关联。
- `src/drawing_graph/semantic_client.py`：定义多模态识别客户端协议和 fake client；当前不默认调用真实外部模型供应商。
- `src/drawing_graph/qwen_semantic_client.py`：实现可选 Qwen/DashScope 多模态识别客户端，使用 OpenAI-compatible chat completions 接口，API key 只从环境变量读取，不进入 facade 请求、命令参数或输出。
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
- `src/drawing_graph/assistant_models.py`：产品公共合同模块，定义 `AssistantRequest`、`AssistantScope`、`QuestionUnderstandingResult`、`AssistantSubrequest`、`EvidenceRequirement`、`RetrievalPlan/RetrievalStep`、`SourceCallRecord`、`EvidenceItem`、`EvidenceRef`、`MissingEvidence`、`RetrievalBundle`、`RawRetrievalResult`、`AnswerPackage`、`Claim`、`Citation`、`TraceRecord`、`FeedbackEvent` 与稳定枚举/原因码；默认只读、`write_back=false`，不依赖数据库驱动/仓储/HTTP/MCP/Qwen。
- `src/drawing_graph/assistant_retrieval_planner.py`：`RetrievalPlanner.plan()` 校验 scope，把 `EvidenceRequirement` 映射为 facade 白名单只读步骤，并做同请求去重、payload 默认关闭和 limit 上限；只做规划，不访问 facade。
- `src/drawing_graph/assistant_retrieval_executor.py`：`RetrievalExecutor.execute()` 只调用 facade 白名单只读方法，记录 `SourceCallRecord`，同一 `dedupe_key` 只执行一次；把异常映射为稳定原因码并脱敏，不调用识别、审核或写回能力。
- `src/drawing_graph/assistant_retrieval_projection.py`：`RetrievalBundleBuilder.build()` 把 facade DTO 归一化为 `EvidenceItem` 并按事实层级放入 `RetrievalBundle`，汇总 `missing_evidence`、warning 与整体状态。
- `src/drawing_graph/assistant_retrieval_service.py`：`GraphRetrievalService.retrieve()` 串联 planner、executor、bundle builder，是通用检索闭环的唯一产品层入口。
- `src/drawing_graph/assistant_qa_mapping.py`：`qa_request_to_question_result()` 把六类固定 `QARequest` 单向映射为 `QuestionUnderstandingResult` 与 `EvidenceRequirement`；不修改 `DrawingGraphQAService` 行为，QAService 不反向依赖产品模块。
- `src/drawing_graph/assistant_question_text.py`：`QuestionTextNormalizer.normalize()` 去首尾空白、统一全角标点、折叠重复空白，保留大小写敏感业务 ID；空输入直接报错。
- `src/drawing_graph/assistant_scope_resolution.py`：`ScopeResolver.resolve()` 提取 `page:/block:/element:/cross_section:/table:/table_caption:/claim:` 稳定 ID，合并 `scope_hint` 并在有限对话上下文中消解“这张图/这个图块”；冲突与指代不唯一返回稳定原因码，不访问图谱。
- `src/drawing_graph/assistant_question_rules.py`：`RuleQuestionRouter.route()` 用“关键词组合 + 排除词”做确定性中文路由；无命中返回 `unknown_or_unsupported`，多命中返回 `clarification_required` + `ambiguous_question_type`。
- `src/drawing_graph/assistant_intent_splitter.py`：`IntentSplitter.split()` 把明确列举式/连接式多意图拆分为稳定 `AssistantSubrequest`，不确定时保留 `multi_intent_ambiguous`，不丢弃子问题。
- `src/drawing_graph/assistant_evidence_templates.py`：`EvidenceRequirementFactory.build()` 按 `question_type + scope` 生成只读 `EvidenceRequirement`；`allow_model_generation` 只在语义解释类需求中为 true，且不触发模型调用。
- `src/drawing_graph/assistant_clarification.py`：`ClarificationPolicy.evaluate()` 根据 scope 缺失/冲突、指代不唯一和问题类型歧义生成 `ClarificationDecision` 与 `ClarificationItem`。
- `src/drawing_graph/assistant_question_trace.py`：`QuestionUnderstandingTraceBuilder.build_event()` 生成可放入 `TraceRecord.module_events` 的 `QuestionUnderstandingEvent`，details 自动脱敏。
- `src/drawing_graph/assistant_question_llm.py`：`QuestionUnderstandingModelClient` 协议、`FakeQuestionUnderstandingModelClient` 与 `validate_model_output()`；只返回受约束候选，非法输出返回 `model_output_invalid`，不读取密钥、不发起网络请求。
- `src/drawing_graph/assistant_question_understanding.py`：`QuestionUnderstandingService.understand()` 编排规范化、scope 解析、规则路由、多意图拆分、证据需求与澄清策略，输出 `QuestionUnderstandingResult`。
- `src/drawing_graph/assistant_evidence_sufficiency.py`：`EvidenceSufficiencyEvaluator.evaluate()` 逐需求评估充分性，实现 scope 匹配、fact kind 层级门控、formal gate、状态/冲突判断与模型生成许可。
- `src/drawing_graph/assistant_evidence_freshness.py`：`EvidenceFreshnessEvaluator.evaluate()` 判断图片/bbox/模型/prompt/预处理/规范化/合同 freshness，`cache_candidates()` 复用 `semantic_cache.build_semantic_cache_key()` 输出 `CacheCandidate`；只读，不写缓存。
- `src/drawing_graph/assistant_recognition_target_planner.py`：`RecognitionTargetPlanner.plan()` 从 `RetrievalBundle` 来源事实定位并生成最小 `RecognitionTarget`，支持合并去重、稳定排序与缺定位 blocked。
- `src/drawing_graph/assistant_recognition_budget.py`：`RecognitionCostProfile`/`RecognitionEstimator` 提供保守估算，`RecognitionBudgetEvaluator.evaluate()` 执行授权、max targets、预算与时延硬门控。
- `src/drawing_graph/assistant_semantic_gap_decision.py`：`SemanticGapDecisionService.decide()` 校验输入并编排充分性、freshness/cache、目标规划与预算门控，输出唯一 `SemanticGapDecision`。
- `src/drawing_graph/assistant_trace_models.py`、`assistant_trace_store.py`、`assistant_trace_builder.py`、`assistant_claim_trace.py`、`assistant_traceability_service.py`：定义产品运行追溯 DTO、内存 store port、`TraceRecord` 构造、claim 追溯投影及记录/回查服务；trace 只进入 `TraceStorePort`，不进入 Neo4j 业务图谱。
- `src/drawing_graph/assistant_feedback_models.py`、`assistant_feedback_store.py`、`assistant_feedback_permissions.py`、`assistant_feedback_state_machine.py`、`assistant_feedback_service.py`：定义反馈 DTO、append-only 内存 store、fail-closed 权限、状态迁移、审计和反馈服务；`confirm/reject/correct` 只记录反馈与审计。
- `src/drawing_graph/assistant_candidate_review_adapter.py`：只把满足权限、候选完整性、同页、方向和 evidence refs 要求的 `request_review` 转交注入的 `CandidateReviewService.review_candidate_group()`；不直接访问 repository、driver 或 Cypher。
- `src/drawing_graph/assistant_adapter_serialization.py`：产品 adapter 共享 envelope、`AnswerPackage` JSON-safe 投影、稳定错误类别与脱敏；复用 `qa_serialization.to_jsonable`/`sanitize_error_message`，不依赖 FastAPI/Pydantic/MCP/Neo4j/Qwen。
- `src/drawing_graph/assistant_http_models.py`：产品 HTTP request/response/health DTO，严格字段白名单，转换为只读 `AssistantRequest`（固定 `allow_write_back=False`）。
- `src/drawing_graph/assistant_http_runtime.py`：产品 HTTP driver -> facade -> `DrawingAssistantService` 装配与幂等关闭；只有 runtime 与启动脚本知道 Neo4j driver。
- `src/drawing_graph/assistant_http.py`：产品 HTTP FastAPI 应用工厂 `create_app(config, runtime_factory)`；路由 `POST /api/v1/drawing-assistant/ask`、`/health/live`、`/health/ready`，含并发上限、请求超时、请求体限制、认证与稳定错误映射；模块 import 无副作用。
- `scripts/serve_drawing_assistant.py`：产品 HTTP 单 worker Uvicorn 启动入口，只从环境变量读取 `AssistantHttpConfig`；不接受密码、token 或 API key 命令行参数。
- `src/drawing_graph/assistant_mcp_models.py`：产品 MCP 输入输出模型，转换为只读 `AssistantRequest`；只接受 question/request_id/language/scope_hint/allow_recognition/answer_format，拒绝写回/Cypher/凭据/路径/底层对象。
- `src/drawing_graph/assistant_mcp_tools.py`：`DrawingAssistantMCPTools(service)` 与只读 `ask_drawing_assistant` handler，只调用一次 `DrawingAssistantService.answer()`，生成同源 structuredContent 与 TextContent。
- `src/drawing_graph/assistant_mcp_runtime.py`：`AssistantMcpRuntime` 与 `create_assistant_mcp_runtime(config, ...)`，管理 driver -> facade -> `DrawingAssistantService` 装配、失败清理与幂等关闭；支持 fake factory 注入。
- `src/drawing_graph/assistant_mcp_server.py`：无 import 副作用的 `create_mcp_server(tools)`，配置 `drawing-assistant` server instructions、只读工具 Schema 与只读 annotations；只提供 Tools capability。
- `scripts/serve_drawing_assistant_mcp.py`：产品 MCP 本地 STDIO 唯一进程入口；`main()` 加载 `AssistantMcpConfig`、装配 runtime/tools/server、运行官方 STDIO transport；stdout 只承载协议帧，不接受 host/port/token/write-back 参数。

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
- `scripts\drawing_graph_tool.py list-drawing-sets|list-pages|page-source-facts|block-trace|block-relations|recognize-page-semantics|list-text-observations|list-interpretations|list-candidate-relations|list-section-matches`：当前已落地的 CLI 调用入口，参数映射到 facade 查询或按需语义识别方法并输出 JSON；`recognize-page-semantics` 默认 `write_back=false`，只有显式 `--write-back` 才触发受控语义证据写回；命令失败时返回结构化错误 category，低层 Neo4j/Cypher/密钥细节会被清洗。
- `DrawingGraphQAService(facade)` 与 `DrawingGraphQAService.ask(request) -> QAAnswer`：QA 编排唯一入口；`request` 必须是 `QARequest`，`write_back=true` 会被 `WRITE_BACK_FORBIDDEN` 拒绝，第一阶段只读。
- `scripts\drawing_graph_qa.py ask-page|ask-block|ask-candidates|ask-section|ask-table-caption|diagnose`：QA CLI 子命令，映射到 `page_summary`、`block_relations`、`candidate_relations`、`section_matches`、`table_caption_status`、`diagnostic_status`；`--format json` 为默认输出，`--format zh-brief` 输出简短中文。
- `QAHttpConfig`（`src/drawing_graph/config.py`）：HTTP 专用不可变配置；默认 `127.0.0.1:8000`、`allow_remote=false`、空 CORS、65536 bytes、30 秒、8 并发、docs 关闭；非 loopback 必须 `allow_remote=true` 且配置 token；password 与 token 在 `repr` 中屏蔽。
- `create_app(config, runtime_factory=create_qa_http_runtime)`：创建无 import 副作用的 FastAPI 应用；lifespan 启动时创建一次 runtime、关闭时关闭一次 driver。
- `POST /api/v1/drawing-qa/ask` 与六个便捷 GET 路由（页面摘要、图块关系、候选关系、断面匹配、表格标题状态、诊断状态）：只构造 `QARequest` 并调用 `DrawingGraphQAService.ask()`，不直接调用 facade 方法。
- `GET /health/live` 与 `GET /health/ready`：健康检查；ready 在 runtime 已装配时返回 `neo4j_status="not_checked"`，未装配返回 503。
- `RelationRepository.update_candidate_review` 与 `RelationRepository.promote_candidate_relation` 仍是底层受控写回接口，不由 Tool adapter 直接调用。
- `QAMcpConfig`（`src/drawing_graph/config.py`）：MCP 专用不可变配置，只包含 `neo4j_uri`、`neo4j_user`、`neo4j_password` 和 `log_level`；`from_env()` 读取 `NEO4J_URI`、`NEO4J_USER`、`NEO4J_PASSWORD` 与可选 `DRAWING_GRAPH_QA_MCP_LOG_LEVEL`，不复用 HTTP host/port/CORS/docs 配置。
- `AssistantHttpConfig`（`src/drawing_graph/config.py`）：产品 HTTP 专用不可变配置；默认 `127.0.0.1:8001`、`allow_remote=false`、空 CORS、65536 bytes、30 秒、8 并发、docs 关闭；`from_env()` 读取 `NEO4J_*` 与 `DRAWING_GRAPH_ASSISTANT_HTTP_*`；password 与 token 在 `repr` 中屏蔽。
- `AssistantMcpConfig`（`src/drawing_graph/config.py`）：产品 MCP 专用不可变配置，只包含 `neo4j_uri`、`neo4j_user`、`neo4j_password` 和 `log_level`；`from_env()` 读取 `NEO4J_*` 与可选 `DRAWING_GRAPH_ASSISTANT_MCP_LOG_LEVEL`。
- `create_qa_mcp_runtime(config, driver_factory=None, facade_factory=None, service_factory=None)`：按 driver -> facade -> QAService 顺序装配，支持 fake 注入，初始化失败时逆序清理，`close()` 幂等。
- `create_mcp_server(tools: DrawingGraphMCPTools)`：返回未启动的 `drawing-graph-qa` server；只注册六个只读工具，不注册 Resources/Prompts/Sampling。
- `DrawingGraphMCPTools.ask_drawing_page|ask_drawing_block|list_drawing_candidates|get_section_match_status|get_table_caption_status|get_drawing_diagnostics`：六个只读 handler，固定 `write_back=false` 且 `include_payload=false`，只调用一次 QAService。
- `scripts\serve_drawing_graph_mcp.py main() -> int`：唯一 STDIO 入口；正常结束返回 0，配置/装配失败返回 2，transport 失败返回 3，close 失败返回 4；stderr 只输出脱敏错误。
- `RetrievalPlanner.plan(question_result, policy=None) -> RetrievalPlan`：只读检索规划；scope 缺失/冲突返回 `scope_missing`/`scope_conflict` warning，相同 facade 查询合并为一个 step。
- `RetrievalExecutor.execute(plan, facade) -> (RawRetrievalResult, tuple[SourceCallRecord, ...])`：按白名单调用 facade 只读方法，同一 `dedupe_key` 只调用一次；异常映射为稳定原因码并脱敏。
- `RetrievalBundleBuilder.build(question_result, plan, raw_result, source_calls) -> RetrievalBundle`：按 `fact_kind` 分层归一化，汇总缺失证据、warning 与整体状态。
- `GraphRetrievalService.retrieve(question_result, policy=None) -> RetrievalBundle`：通用检索闭环入口，编排 plan -> execute -> build，默认只读。
- `qa_request_to_question_result(request: QARequest) -> QuestionUnderstandingResult`：六类固定 QA 到产品检索需求的单向兼容映射。
- `QuestionUnderstandingService.understand(request: AssistantRequest) -> QuestionUnderstandingResult`：01 问题理解闭环入口，把请求稳定转换为可交给 `GraphRetrievalService` 的结果；clarification/unsupported 不进入检索。
- `QuestionTextNormalizer.normalize(question: str) -> str`、`ScopeResolver.resolve(question, scope_hint, conversation_context) -> ScopeResolutionResult`、`RuleQuestionRouter.route(question, scope) -> QuestionRouteResult`、`IntentSplitter.split(question, route_result, scope) -> tuple[AssistantSubrequest, ...]`、`EvidenceRequirementFactory.build(question_type, scope, request) -> tuple[EvidenceRequirement, ...]`、`ClarificationPolicy.evaluate(...) -> ClarificationDecision`、`QuestionUnderstandingTraceBuilder.build_event(...) -> QuestionUnderstandingEvent`、`validate_model_output(raw) -> ModelOutputValidation`：问题理解闭环的模块级接口，全部只读、无外部调用。
- `EvidenceSufficiencyEvaluator.evaluate(question_result, retrieval_bundle) -> tuple[RequirementAssessment, ...]`：逐需求充分性评估。
- `EvidenceFreshnessEvaluator.evaluate(assessments, retrieval_bundle, recognition_policy, requirements=None) -> tuple[RequirementAssessment, ...]` 与 `cache_candidates(...) -> tuple[CacheCandidate, ...]`：freshness 与缓存处置判断。
- `RecognitionTargetPlanner.plan(assessments, retrieval_bundle, recognition_policy, requirements=None) -> tuple[RecognitionTarget, ...]`：最小识别目标规划。
- `RecognitionBudgetEvaluator.evaluate(targets, policy) -> (selected, deferred, RecognitionEstimate)`：授权与预算/时延硬门控。
- `SemanticGapDecisionService.decide(question_result, retrieval_bundle, recognition_policy=None) -> SemanticGapDecision`：03 决策编排入口，`write_back_recommendation` 恒为建议。
- `DrawingGraphToolFacade.recognize_semantic_targets(targets, model_profile, prompt_version, contract_version, write_back=False)`：精确目标识别预留入口，默认 `write_back=false`。
- `SemanticRecognitionService.recognize_targets(page_facts, targets, ...)`：执行前按统一 cache key 二次校验，缓存命中不调用供应商、不创建持久化 run log。
- `create_semantic_gap_decision_service() -> SemanticGapDecisionService`：工厂装配纯决策服务，不连接数据库、不读取供应商凭据。
- `TraceabilityService.record_answer_trace(...) -> TraceWriteResult`、`get_trace(request_id, actor=None) -> TraceQueryResult`、`get_claim_trace(claim_id, actor=None) -> ClaimTrace | None`：产品运行追溯记录与只读回查；store 失败返回稳定 warning，不改变答案业务状态。
- `create_drawing_assistant_service(..., traceability_service=None, trace_store=None) -> DrawingAssistantService`：可选装配追溯服务；未注入时与原有只读问答行为兼容。
- `FeedbackService.submit_feedback(event, actor) -> FeedbackResult`、`get_feedback(feedback_id, actor=None)`、`list_feedback_for_request(request_id, actor=None)`：产品内部反馈 API；默认权限策略 fail closed，未提供外部 HTTP/MCP/Web UI adapter。
- `CandidateReviewAdapter.build_review_request(feedback_event, claim_trace) -> CandidateReviewRequest` 与 `request_review(...) -> CandidateReviewResult`：只处理候选关系 claim，并只调用注入的 `CandidateReviewService.review_candidate_group()`。
- `answer_package_to_data(package) -> dict`、`build_success_envelope(data, meta)`、`build_error_envelope(code, message, retryable, meta)`、`map_exception_to_error(error) -> (code, retryable)`：产品 adapter 共享序列化/错误映射接口。
- `create_app(config, runtime_factory=create_assistant_http_runtime)`：产品 HTTP 应用工厂；`POST /api/v1/drawing-assistant/ask` 只构造 `AssistantRequest` 并调用 `DrawingAssistantService.answer()`。
- `create_assistant_http_runtime(config, driver_factory=None, facade_factory=None, service_factory=None)`：按 driver -> facade -> `DrawingAssistantService` 顺序装配，支持 fake 注入，初始化失败逆序清理，`close()` 幂等。
- `create_assistant_mcp_runtime(config, ...)` 与 `create_mcp_server(tools: DrawingAssistantMCPTools)`：产品 MCP runtime 与 `drawing-assistant` server；`ask_drawing_assistant` 是唯一只读工具。
- `DrawingAssistantMCPTools.ask_drawing_assistant(tool_input)`：只调用一次 `DrawingAssistantService.answer()`，structuredContent 来自 `AnswerPackage` JSON-safe 投影，TextContent 只概述状态与数量。

## 3. 新依赖

新增依赖都是项目内 Python port、fake 实现、Python 标准库 CLI/JSON 支撑，以及 HTTP adapter/Qwen OpenAI-compatible 调用共用的 HTTPX：`DrawingGraphReadPort`、`MultimodalRecognitionClient`、`RecognitionRunLogPort`、`SemanticEvidenceRepositoryPort`、`SectionMatchWritePort`、`SectionMatchQueryPort`、`SemanticCacheService`、`SemanticPayloadStore`，以及 QA 层的 `QARequest`、`QAAnswer`、`AnswerFact`、`EvidenceRef` 等 QA DTO。第三阶段新增官方 MCP Python SDK（`requirements.txt`：`mcp>=1.29.0,<2.0`）作为本地 STDIO MCP adapter 依赖；产品公共合同与通用检索模块新增项目内依赖：`assistant_models.py` 的公共 DTO、`RetrievalPlanner`/`RetrievalExecutor`/`RetrievalBundleBuilder`、`GraphRetrievalService`，以及 `assistant_qa_mapping.py` 对 `qa_models.py` 的单向导入；追溯与反馈新增的 `TraceStorePort`、`FeedbackStorePort`、内存实现、权限策略和状态机仍只依赖项目内合同与 Python 标准库，未新增外部依赖。

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
- `TraceRecord`、`ClaimTrace`、`FeedbackEvent`、`FeedbackAuditEvent` 与 `FeedbackResult` 属于产品运行审计数据；首版只存于注入的 trace/feedback store，不新增 Neo4j 节点、关系、索引、约束或迁移。

## 5. 架构变化

当前依赖方向是：薄 CLI adapter 或项目级 Skill（`.codex\skills\drawing-graph-operator\`）-> `DrawingGraphToolFacade` -> read port / semantic service / run log port / semantic repository / section match service / candidate review service -> 受控 repository。facade 不写 Cypher，不创建 Neo4j driver，不调用 CLI 脚本，不直接调用 `block_relation_enrichment.py` 的规则函数。Neo4j 生产装配由 `create_neo4j_tool_facade()` 完成；`scripts\drawing_graph_tool.py` 只在最外层读取环境变量、创建 driver、关闭 driver 并输出 JSON，driver 和 secret 仍由外部运行环境提供。

QA 编排层位于 facade 外侧，CLI、HTTP 与 MCP 是同级 adapter，依赖方向固定为 `QA adapter -> DrawingGraphQAService -> DrawingGraphToolFacade -> ports/services -> repository/Neo4j`（HTTP 对应 `HTTP adapter -> DrawingGraphQAService -> DrawingGraphToolFacade -> ports/services -> repository/Neo4j`，MCP 对应 `MCP adapter -> DrawingGraphQAService -> DrawingGraphToolFacade -> ports/services -> repository/Neo4j`）。`scripts\drawing_graph_qa.py`、`scripts\serve_drawing_graph_qa.py` 与 `scripts\serve_drawing_graph_mcp.py` 是最外层 adapter，`DrawingGraphQAService` 只通过 `DrawingGraphToolFacade` 获取图谱信息，默认 `write_back=false`，不写 Cypher、不持久化语义证据、不提升候选关系。HTTP 默认 loopback、单 worker、只读，CORS 与 OpenAPI docs 默认关闭；`/health/ready` 的 `neo4j_status="not_checked"` 不等于 live Neo4j 验证。本地只读 STDIO MCP adapter 已实现；首版不实现 Streamable HTTP，远程认证、OAuth、RBAC、TLS、多 worker、HTTP 写回与 plugin 发布仍未实现。当前已有可选 Qwen/DashScope 多模态客户端，但不默认调用，live DashScope 验证需单独执行；Ava 专有 adapter、OCR 和数据库 schema 变更仍未实现。

产品公共合同与通用检索闭环本身不调用 Qwen、不创建 RecognitionRun、不写 Neo4j。产品实现层只读问答链路为：`QuestionUnderstandingService（01 已实现）-> GraphRetrievalService -> RetrievalBundle -> SemanticGapDecisionService（03 已实现）-> MultimodalRecognitionExecutionService（04 已实现）-> EvidenceFusionService（05 已实现）-> EvidenceBundle -> AnswerGenerationService（06 已实现）-> DrawingAssistantService（07 已实现）-> Product CLI/HTTP/MCP`。`DrawingAssistantService.answer()` 已把 01—06 装配成产品级只读总编排入口，并可选调用 `TraceabilityService -> TraceStorePort` 记录产品运行追溯；反馈是独立内部链路：`FeedbackService -> FeedbackPermissionPolicy / FeedbackStateMachine / FeedbackStorePort -> CandidateReviewAdapter（仅 request_review）-> CandidateReviewService`。图谱读取和既有语义执行仍只经 `DrawingGraphToolFacade -> ports/services -> repository/Neo4j`，反馈也不能绕过 `CandidateReviewService`。07 固定问答链路只读，传给 05 的 `write_back_policy=None`，识别调用固定 `write_back=false`；追溯只写审计 store，`confirm/reject/correct` 只写反馈 store 与审计，均不写业务事实。候选关系不是正式事实，`matched_candidate` 不能当作正式图谱关系。外部产品级 Web UI、外部持久化 store、多用户账号集成、真实文本 provider、live Neo4j 与 live DashScope 验证仍未完成（外部反馈 HTTP API 已实现）；未配置 live 环境导致集成测试 skipped 时，跳过不等于 live Neo4j 通过。

Skill 与 MCP 分工：`drawing-graph-operator` Skill 是 facade 外侧的操作策略层，负责自然语言路由、多问题拆分、工具选择、透明降级和结果解释；MCP adapter 负责协议初始化、工具 Schema、annotations 与 STDIO 生命周期。Skill 不创建 driver、不执行 Cypher、不调用 repository 写回，也不承载图谱业务逻辑。

`write_back=false` 是默认安全边界。dry-run 识别可以返回临时 `recognition_run_id`、observation 和 interpretation，但不保证之后可查询。`write_back=true` 时才写入图谱外 run log、图谱内语义证据或受控语义边；候选关系即使 accepted，也必须通过 `CandidateReviewService.review_candidate_group` 的硬规则后才可能调用 `RelationRepository.promote_candidate_relation`。断面匹配的正式边同样只在逻辑键一致、候选唯一且无冲突时写入。

## 6. Skill 资产职责

`.codex/skills/drawing-graph-operator/` 是项目级 Codex Skill（操作层），位于 `DrawingGraphToolFacade` 外侧，包含 `SKILL.md`、`agents/openai.yaml` 和六个 references：`project-boundaries.md`、`facade-workflows.md`、`verification.md`、`output-contract.md`、`qa-workflows.md`、`mcp-boundaries.md`。权威路径由 Task 39 验证后仍为 `.codex/skills/drawing-graph-operator`；Task 40 的 MCP 工具依赖声明为宿主兼容性待办，未验证前不宣称依赖发现已通过。

- 职责：指导 Codex 先读当前项目文档和受影响源码、只经 facade 或薄 CLI adapter 使用图谱能力、默认 `write_back=false`、分层输出事实、如实报告验证状态。
- 它不属于 `src/drawing_graph/` 业务模块，不改变运行时图谱能力，也不是 Agent Skill、MCP Tool adapter、HTTP API 或文件 watcher。
- 静态边界由 `tests/test_skill_docs.py` 保护，运行 `python -m unittest tests.test_skill_docs -v`。

## 6. 04 多模态识别执行层模块

`changes/产品实现层/多模态识别产品化/tasks.md` 的 Task 1-43 已全部实现。产品实现层 04 形成供应商无关、同步优先的多模态识别执行流水线，模块清单与职责如下：

- `src/drawing_graph/recognition_models.py`：执行层枚举与纯 DTO（任务、状态、attempt、usage、成本、延迟、执行结果）。
- `src/drawing_graph/recognition_tasks.py`：七类任务的不可变 Task Registry 与合同规格。
- `src/drawing_graph/recognition_input_validation.py`：调用前目标/bbox/context/安全/策略校验。
- `src/drawing_graph/recognition_image_preprocessing.py`：Pillow 内存局部 bbox 裁剪、EXIF 规范化、受控缩放与资源上限。
- `src/drawing_graph/recognition_prompting.py`：task-specific prompt 渲染与稳定 fingerprint。
- `src/drawing_graph/recognition_output_validation.py`：task schema 输出校验与事实等级拦截。
- `src/drawing_graph/recognition_retry.py`：provider 错误分类、有界重试、deadline/预算门控。
- `src/drawing_graph/recognition_metrics.py`：usage/实际成本/分阶段延迟汇总。
- `src/drawing_graph/recognition_redaction.py`：统一 fail-closed 脱敏。
- `src/drawing_graph/recognition_attempt_log.py`：图谱外 append-only attempt log。
- `src/drawing_graph/recognition_execution.py`：`MultimodalRecognitionExecutionService` 唯一执行编排入口。

依赖方向：`DrawingGraphToolFacade -> SemanticRecognitionService -> MultimodalRecognitionExecutionService -> provider port（Qwen adapter / Fake）`。执行层禁止导入 Neo4j、repository、Cypher、QA/HTTP/MCP/CLI adapter 与持久化内部实现。

边界保持：默认 `write_back=false`；`RecognitionRun`/`RecognitionAttempt` 图谱外；`TextObservation` 与三类 `Interpretation` 图谱内；relation 输出只能为 `candidate_relation`，候选不等于正式事实；不引入 OCR；不改变 Neo4j 来源事实 schema。

专项验收入口为 `python -m unittest tests.test_multimodal_recognition_docs tests.test_multimodal_recognition_acceptance tests.test_multimodal_recognition_contracts tests.test_multimodal_recognition_boundaries tests.test_tool_facade tests.test_semantic_service tests.test_qwen_semantic_client -v`。2026-08-13 当前回归快照：专项 73 项通过；完整 `python -m unittest discover tests -v` 为 1823 项运行、4 项因缺少 live Neo4j 测试配置而跳过，其余通过。以上属于离线/fake 验证；live DashScope、黄金集、live Neo4j、Codex/MCP 均未声称通过，本次文档同步也未执行这些 live 验证。

## 7. 05 证据融合与缓存闭环模块

`changes/产品实现层/证据融合与缓存闭环/tasks.md` 的 Task 1-56 已全部实现。产品实现层 05 位于 04 之后、06 之前，是独立、确定性、默认只读的证据融合与缓存闭环，模块清单与职责如下：

- `src/drawing_graph/assistant_evidence_fusion_models.py`：05 稳定枚举与不可变 DTO（`EvidenceBundle`、冲突、claim 支撑、answerability、lineage、缓存汇总、写回合同）。
- `src/drawing_graph/assistant_recognition_projection.py`：04 结果到统一 `EvidenceItem` 的安全投影（observation/interpretation/candidate/diagnostic）与 scope 校验。
- `src/drawing_graph/assistant_evidence_normalization.py`：规范化规则注册、comparison/family/fingerprint 构造、claim capability 注册与断面标签复用。
- `src/drawing_graph/assistant_evidence_deduplication.py`：四条件全同合并与 provenance 保留。
- `src/drawing_graph/assistant_evidence_rules.py`：03/05 共用的 scope/fact-kind/status/formal 纯规则。
- `src/drawing_graph/assistant_evidence_lineage.py`：stale 策略注册与 supersede 计划。
- `src/drawing_graph/assistant_evidence_conflicts.py`：确定性冲突矩阵与稳定冲突 ID。
- `src/drawing_graph/assistant_claim_support.py`：requirement 到 claim capability 的映射与支撑评估。
- `src/drawing_graph/assistant_answerability.py`：subrequest/request answerability 聚合。
- `src/drawing_graph/assistant_cache_closure.py`：expected/actual/lineage/write-back 缓存汇总。
- `src/drawing_graph/assistant_semantic_write_back.py`：受控写回 fail-closed 门控与固定顺序状态机。
- `src/drawing_graph/assistant_evidence_fusion.py`：`EvidenceFusionService.fuse()` 唯一编排入口。
- `src/drawing_graph/assistant_evidence_fusion_factory.py`：`create_evidence_fusion_service()` 无副作用装配。

边界保持：默认 `write_back=false`；dry-run 零持久化；persistent cache 仅在受控写回授权通过后提交；`candidate` 不等于 formal，融合/置信度/写回授权均不提升 `fact_kind`；05 不调用模型、不查询 Neo4j、不执行 Cypher、不新增外部 API；06/07 已消费 05 的 `EvidenceBundle` 生成答案并完成只读总编排，但不新增 schema、不写回、不提升候选关系。产品级 HTTP/MCP 问答 adapter 由“产品级 HTTP/MCP adapter”独立实现。

验证分层：2026-08-14 的 05 专项回归运行 280 项，0 失败、0 错误、0 跳过；05 当时的完整离线回归运行 2150 项，0 失败、0 错误、4 项因缺少 live Neo4j 测试环境变量而跳过。06/07 完成后新增的产品答案与只读总编排离线验证见第 8 节。以上仅证明离线/fake、合同与静态边界；live Neo4j、live DashScope、黄金集和真实文本 provider 均未验证。

## 8. 06 答案生成与 07 只读总编排模块

`changes/产品实现层/答案生成与只读总编排MVP/tasks.md` 的 Task 1-65 已实现产品级答案生成与只读总编排。模块清单与职责如下：

- `src/drawing_graph/assistant_claim_builder.py`：`ClaimBuilder.build()` 把 `ClaimSupportAssessment` 确定性投影为 `Claim`，`build_claim_id()` 生成稳定 claim ID；candidate/interpretation/conflict 不被提升为 formal/source fact。
- `src/drawing_graph/assistant_citation_builder.py`：`CitationBuilder.build()` 从 claim evidence 投影最小 citation 并稳定排序、去重，`bind_claim_citations()` 建立 claim/citation 双向一致；不复制 payload、不输出 image_path/URI。
- `src/drawing_graph/assistant_answer_generation.py`：06 唯一入口 `AnswerGenerationService.generate()`，内部组合 `AnswerStatusResolver`、`MachineAnswerBuilder`、`CanonicalAnswerSerializer`、`AnswerPackageValidator`；`machine_answer` 是权威输出，文本生成只是表现层。
- `src/drawing_graph/assistant_answer_templates.py`：`ChineseAnswerTemplateRenderer.render()` 按五章节渲染确定性中文模板，`fact_kind_wording()`/`claim_status_wording()` 提供不提升事实等级的措辞。
- `src/drawing_graph/assistant_answer_text.py`：受约束文本生成 port、`FakeConstrainedTextGenerator`、`ConstrainedTextValidator` 与 `render_text_with_fallback()` 模板回退。
- `src/drawing_graph/drawing_assistant_service.py`：07 唯一入口 `DrawingAssistantService.answer()`，内部组合 `SubrequestProjector`、`RecognitionTargetGrouper`、`AnswerPackageAggregator`；固定 01→02→03→04→05→06 顺序，按页 dry-run 识别，全链路 `write_back=false`。
- `src/drawing_graph/drawing_assistant_factory.py`：`create_drawing_assistant_service(facade, text_generator=None)` 无副作用装配 01—07。
- `scripts/drawing_assistant.py`：产品级只读 CLI adapter，负责参数、配置、driver 生命周期、service 调用、输出与退出码；不提供 write-back 参数。

边界保持：默认 `write_back=false`；`machine_answer`/claims/citations/status 是权威输出，受约束文本生成只是表现层；candidate/interpretation 不被提升为 formal/source fact；非诊断 claim 必须有 citation；产品 CLI 是现有 QA CLI/HTTP/MCP 的同级 adapter，不替换也不反向依赖它们。产品公共合同仍不新增 schema、业务写回或候选提升；产品运行审计的内存 trace/feedback store 已实现，但不等于外部持久化或业务图谱写入。

验证分层：2026-08-14 的完整离线回归 `python -m unittest discover tests -v` 运行 2428 项，0 失败、0 错误、4 项因缺少 live Neo4j 测试环境变量而跳过。以上仅证明离线/fake、合同与静态边界；live Neo4j、live DashScope、真实文本 provider 均未验证，skipped 不等于 live 通过。

## 9. 产品级 HTTP/MCP adapter 模块

`changes/产品实现层/adapter与产品级验收/tasks.md` 的 Task 1-20 已完成产品级只读 HTTP/MCP adapter 与产品 CLI/HTTP/MCP 三入口验收。产品 adapter 与旧 QA adapter 是同级外部入口：旧 QA CLI/HTTP/MCP 继续调用 `DrawingGraphQAService.ask()` 和六类固定 QA 问题；产品 CLI/HTTP/MCP 只调用 `DrawingAssistantService.answer()`，接收自然语言问题并返回 `AnswerPackage` 结构化答案。

- `src/drawing_graph/assistant_adapter_serialization.py`：产品 adapter 共享 envelope、`AnswerPackage` JSON-safe 投影、稳定错误类别与脱敏。
- `src/drawing_graph/assistant_http_models.py`、`assistant_http_runtime.py`、`assistant_http.py`、`scripts/serve_drawing_assistant.py`：产品 HTTP request/response/health DTO、driver -> facade -> service 装配、`POST /api/v1/drawing-assistant/ask`、health、认证、body limit、并发上限、超时与稳定错误映射。
- `src/drawing_graph/assistant_mcp_models.py`、`assistant_mcp_tools.py`、`assistant_mcp_runtime.py`、`assistant_mcp_server.py`、`scripts/serve_drawing_assistant_mcp.py`：产品 MCP 输入输出模型、本地 STDIO runtime/server、只读工具 `ask_drawing_assistant`、同源 structuredContent/TextContent 输出与 stdout 协议纯净。
- 配置接口：`AssistantHttpConfig` 读取 `NEO4J_*` 与 `DRAWING_GRAPH_ASSISTANT_HTTP_*`；`AssistantMcpConfig` 读取 `NEO4J_*` 与 `DRAWING_GRAPH_ASSISTANT_MCP_LOG_LEVEL`；password/token 的表示和错误输出均脱敏。

边界保持：产品 HTTP/MCP adapter 不直接访问 Neo4j driver、repository、Cypher、Qwen provider 或离线增强规则；runtime 只负责装配 driver -> facade -> `DrawingAssistantService`。默认 `write_back=false`，HTTP/MCP 首版不提供写回入口；`allow_recognition=true` 只允许按需识别，不等于写回授权；`candidate_relation`、`matched_candidate` 与 `CANDIDATE_*` 均保持候选语义。Web UI、远程 MCP、Streamable HTTP MCP、OAuth/RBAC、多 worker 生产部署、HTTP/MCP 写回、外部产品级 Web UI 仍未实现（外部反馈 HTTP API 已实现）。

验证分层：2026-08-17 产品 adapter 专项回归运行 127 项，0 失败、0 错误、0 跳过；根文档契约 `tests.test_readme tests.test_module_docs tests.test_assistant_docs tests.test_assistant_adapter_docs` 共 42 项 OK；全仓离线回归 `python -m unittest discover tests` 运行 2717 项，`OK (skipped=5)`。这些结果属于 unit/fake/offline、HTTP TestClient 与 MCP in-memory client session 验证；HTTP 真实 socket、MCP STDIO 子进程、live Neo4j、live DashScope、真实文本 provider 与真实 MCP 宿主注册均未验证。skipped 不等于 live Neo4j 通过，详见 `docs/acceptance/PRODUCT_ADAPTER_ACCEPTANCE.md`。

## 10. 07 追溯闭环模块

`changes/产品实现层/追溯与反馈闭环/tasks.md` 的第 7 次追溯闭环已实现。产品运行审计层新增追溯模块，位于 `DrawingAssistantService` 外侧，只写产品运行审计 store，不写 Neo4j 业务图谱：

- `src/drawing_graph/assistant_trace_models.py`：追溯 DTO，定义 `TraceModuleEvent`、`TraceCostSummary`、`TraceLatencySummary`、富版 `TraceRecord`（`assistant_models.TraceRecord` 薄版字段的超集）、`TraceWriteResult`、`ClaimTrace`、`TraceQueryResult`；不含 Neo4j driver、repository、Cypher、完整 payload、完整 prompt 或 traceback 字段。
- `src/drawing_graph/assistant_trace_store.py`：`TraceStorePort` 与 `InMemoryTraceStore`，支持 `append_trace()`、`get_trace()`、`append_claim_trace()`、`get_claim_trace()`；重复 request_id 不静默覆盖；不访问 Neo4j。
- `src/drawing_graph/assistant_trace_builder.py`：`TraceRecordBuilder.build()` 从 `AssistantRequest`、问题理解、检索、语义决策、识别、融合与答案结果构造单条 `TraceRecord`；只做数据最小化，不读取图谱、不调用模型、不写 store。
- `src/drawing_graph/assistant_claim_trace.py`：`ClaimTraceProjector.project()` 从 `TraceRecord` 与 `AnswerPackage` 构造 `ClaimTrace`，支持 claim 到 evidence/citation/run 回查；candidate 关系保持 candidate，不使用 Neo4j 内部 ID。
- `src/drawing_graph/assistant_traceability_service.py`：`TraceabilityService.record_answer_trace()` / `get_trace()` / `get_claim_trace()`；存储不可用时返回 trace warning，不把答案业务状态改成失败，无业务写回能力。
- `src/drawing_graph/drawing_assistant_service.py`（可选修改）：构造注入 `traceability_service=None`，`answer()` 生成答案后尝试记录 trace；`allow_write_back=true` 仍被拒绝。
- `src/drawing_graph/drawing_assistant_factory.py`（可选修改）：`create_drawing_assistant_service(..., traceability_service=None, trace_store=None)` 可选装配；默认行为与未注入时兼容。

边界：trace 只写 `TraceStorePort`，不新增 Neo4j schema，不写业务事实，不把 `candidate_relation`/`matched_candidate` 写成 `formal_relation`；trace 输出脱敏。本节只描述追溯职责；第 8 次反馈状态机、权限、审计与 `CandidateReviewService` 受控对接已在下一节独立实现，外部反馈 HTTP API 已实现（默认 in-memory store）。

## 11. 08 反馈闭环模块

`changes/产品实现层/追溯与反馈闭环/tasks.md` 的第 8 次反馈闭环已实现。反馈模块位于 trace 模块外侧，只写反馈 store 与审计事件，仅在 `request_review` 且权限允许时受控调用注入的 `CandidateReviewService`：

- `src/drawing_graph/assistant_feedback_models.py`：`FeedbackAction`（confirm/reject/correct/request_review）、`FeedbackStatus`（received/validated/recorded/review_required/accepted/rejected/unresolved/forbidden/invalid）、`FeedbackPermission`（read_trace/record_feedback/request_candidate_review/promote_formal_relation）、`FeedbackAuditEvent`、`FeedbackResult`；不含 repository、Cypher、driver 或未脱敏异常字段。
- `src/drawing_graph/assistant_feedback_store.py`：`FeedbackStorePort` 与 append-only `InMemoryFeedbackStore`，支持追加 feedback/audit、按 feedback_id/request_id 查询、状态记录；重复 feedback_id 不静默覆盖；不访问 Neo4j。
- `src/drawing_graph/assistant_feedback_permissions.py`：`FeedbackPermissionPolicy.authorize()` 默认 fail-closed；`allow_write_back=false` 阻断候选审核与 formal 提升；`promote_formal_relation` 永远不会由反馈 action 授予。
- `src/drawing_graph/assistant_feedback_state_machine.py`：`FeedbackStateMachine` 线性推进 received -> validated -> recorded -> review_required -> accepted/rejected/unresolved；confirm/reject/correct 终止于 recorded，不进入 formal promotion；非法跳转被拒绝且每次迁移产生记录。
- `src/drawing_graph/assistant_candidate_review_adapter.py`：`CandidateReviewAdapter.build_review_request()` / `request_review()` 只处理候选关系 claim，候选集合不完整、跨页、方向不明、缺 evidence refs 时返回稳定错误，仅通过注入的 `CandidateReviewService.review_candidate_group()`；不直接调用 repository、不拼 Cypher。
- `src/drawing_graph/assistant_feedback_service.py`：`FeedbackService.submit_feedback()` / `get_feedback()` / `list_feedback_for_request()`；串联校验、claim trace 读取、权限、状态机、store 与审计；confirm/reject/correct 只记录反馈，request_review 仅在权限与候选条件满足时调用 adapter；store 写入失败 fail closed。
- `src/drawing_graph/assistant_feedback_http*.py` + `scripts/serve_feedback_http.py`：外部反馈 HTTP API（`POST /api/v1/drawing-assistant/feedback`，confirm/reject/correct/request_review；Bearer token 认证；默认 in-memory store；`FEEDBACK_HTTP_*` 环境变量配置）。
- `src/drawing_graph/page_search_*.py` + `page_search_matcher.py` + `hybrid_search_scorer.py` + `text_embedding_client.py`：全册页内容检索（`page_content_search` 意图与 CLI `search-pages`），词面 + 域内同义词 + 可选向量语义（余弦 top-k）混合；向量缓存 `.search_cache/page_embeddings.sqlite` 在图谱外，embedding 不可用时自动降级词面。
- `src/drawing_graph/question_understanding_client.py`：LLM 问题理解兜底客户端（qwen chat completions + 约束 JSON 校验）；规则未命中且配置 `DASHSCOPE_API_KEY` 时启用，无 key 保持纯规则。

边界：用户 `confirm` 不改变任何 evidence 的 `fact_kind`，`correct` 不生成来源事实、只形成反馈事件或待审核新证据请求；用户反馈不会直接覆盖来源事实、语义证据、候选关系或正式关系；`candidate_relation`/`matched_candidate` 不等于 `formal_relation`；不新增 Neo4j schema；外部反馈 HTTP API 已实现（默认 in-memory store），外部产品级 Web UI 与外部持久化 store 仍未实现。2026-08-17 追溯与反馈专项验收快照中，专项合并回归运行 107 项且全部通过，详见 `docs/acceptance/TRACE_FEEDBACK_ACCEPTANCE.md`；后续产品 adapter 验收已补齐当时过期的根文档契约断言，并记录全仓离线回归 2717 项 `OK (skipped=5)`。live Neo4j、live DashScope 与真实文本 provider 均未验证。
