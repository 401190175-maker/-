# Tool 层 QA 编排实施任务

> 本文件依据 `changes/tool层/design.md` 生成。每个任务只交付一个明确能力，均要求先写测试、再实现；真实 Neo4j、真实云模型、HTTP API、MCP Tool adapter、Ava 对接和 OCR 不作为第一阶段任务前提。所有 QA 能力必须通过 `DrawingGraphToolFacade` 获取图谱信息，不得直接访问 Neo4j、Cypher、Repository 写回方法或离线规则函数。

## Task 1: 定义 QA DTO 与错误契约

**目标：** 建立 QA 层稳定数据契约，支持后续 QAService、CLI、HTTP 和 MCP adapter 复用同一套结构化 answer。

**修改文件：**
- 新增：`src/drawing_graph/qa_models.py`
- 新增：`tests/test_qa_models.py`

**独立测试：**
- `python -m unittest tests.test_qa_models -v`

**完成标准：**
- 定义 `QuestionType`，包含 `page_summary`、`block_relations`、`candidate_relations`、`section_matches`、`table_caption_status`、`diagnostic_status`、`unknown_or_unsupported`。
- 定义不可变 DTO：`QAScope`、`QARequest`、`EvidenceRef`、`AnswerFact`、`QAAnswer`。
- 定义 QA 错误类型和错误码，至少包含 `INVALID_ARGUMENT`、`UNSUPPORTED_QUESTION`、`UNSUPPORTED_SCOPE`、`NOT_FOUND`、`WRITE_BACK_FORBIDDEN`、`FACADE_UNAVAILABLE`、`NEO4J_UNAVAILABLE`、`SEMANTIC_EVIDENCE_UNAVAILABLE`、`INTERNAL_ERROR`。
- `AnswerFact.fact_kind` 只允许 `source_fact`、`derived_relation`、`semantic_observation`、`semantic_interpretation`、`candidate_relation`、`formal_relation`、`diagnostic`、`unsupported`。
- `QARequest.write_back=True` 在模型层或服务层能被识别为第一阶段禁止状态。
- 测试覆盖正常构造、非法 question type、空 ID、非法 fact kind、候选关系不能伪装为 formal、DTO 不包含 Neo4j driver/session/transaction/Cypher。

## Task 2: 实现 QAService 基础入口与请求校验

**目标：** 建立 `DrawingGraphQAService.ask()` 统一入口，完成问题类型路由、scope 校验、write-back 禁止和 unsupported 返回。

**修改文件：**
- 新增：`src/drawing_graph/qa_service.py`
- 新增：`tests/test_qa_service.py`

**独立测试：**
- `python -m unittest tests.test_qa_service -v`

**完成标准：**
- `DrawingGraphQAService` 只接收注入的 `facade`，不创建 Neo4j driver，不读取环境变量。
- `ask(request: QARequest) -> QAAnswer` 作为唯一公开问答入口。
- `write_back=True` 返回或抛出 `WRITE_BACK_FORBIDDEN`，不调用 facade。
- `unknown_or_unsupported` 返回 `status="unsupported"`，并填充 `unsupported_parts`。
- 每种问题类型执行最小 scope 校验：`page_summary` 需要 `page_id`，`block_relations` 需要 `block_id`，`candidate_relations` 需要 `page_id` 或 `block_id`，`section_matches` 需要 `cross_section_id` 或 `page_id`，`table_caption_status` 需要 `page_id`、`table_id` 或 `table_caption_id`，`diagnostic_status` 需要 `page_id` 或 `block_id`。
- 测试使用 fake facade，验证非法 scope 不调用 facade，合法请求能进入对应处理分支。

## Task 3: 实现 `page_summary` 问答

**目标：** 支持按 `page_id` 回答页面来源事实、元素统计和可选语义证据状态。

**修改文件：**
- 修改：`src/drawing_graph/qa_service.py`
- 修改：`tests/test_qa_service.py`

**独立测试：**
- `python -m unittest tests.test_qa_service -v`

**完成标准：**
- `page_summary` 调用 `facade.get_page_source_facts(page_id)`。
- 当 `include_semantics=True` 时，尝试调用 `facade.list_text_observations(page_id=page_id)` 和 `facade.list_interpretations(page_id=page_id)`；语义查询 `NOT_FOUND` 或 `SEMANTIC_EVIDENCE_UNAVAILABLE` 不应阻断来源事实回答，只写入 warning。
- 输出 `QAAnswer.status`：来源事实存在且语义可选缺失时为 `answered` 或 `partial`，页面不存在时为 `not_found`。
- `facts` 中至少包含页面图片、页面元素、元素类型统计，事实类型为 `source_fact`；语义 observation 和 interpretation 分别标为 `semantic_observation`、`semantic_interpretation`。
- `EvidenceRef` 保留 `page_id`、`image_path`、元素 ID、bbox 或 normalized bbox。
- 测试覆盖页面存在、页面不存在、无语义证据、语义仓储不可用、`include_semantics=False` 不调用语义查询。

## Task 4: 实现 `block_relations` 问答

**目标：** 支持按 `block_id` 回答图块追溯链路、正式派生关系、候选关系和增强状态。

**修改文件：**
- 修改：`src/drawing_graph/qa_service.py`
- 修改：`tests/test_qa_service.py`

**独立测试：**
- `python -m unittest tests.test_qa_service -v`

**完成标准：**
- `block_relations` 调用 `facade.get_block_trace(block_id)` 和 `facade.get_block_relations(block_id)`。
- 当 `include_candidates=True` 时，尝试调用 `facade.list_candidate_relations(block_id=block_id)`；候选为空不应导致整个回答失败。
- `BlockTrace` 投影为 `source_fact`，保留 `project_id`、`drawing_set_id`、`page_id`、`image_path`、`bbox`。
- `BlockRelations.caption_ids`、`basic_info_ids`、`annotation_ids`、`section_mark_ids` 投影为 `derived_relation`。
- `candidate_caption_ids`、`candidate_section_mark_ids` 和 `list_candidate_relations()` 返回值投影为 `candidate_relation`，不得投影为 `formal_relation`。
- 输出 summary 包含 `relation_status`，保留 `not_enhanced`、`partial`、`candidate`、`enhanced` 等原始状态语义。
- 测试覆盖 enhanced、partial、candidate、not_enhanced、block 不存在、候选查询不可用降级。

## Task 5: 实现 `candidate_relations` 问答

**目标：** 支持按页面或 block 汇总候选关系，并明确候选关系不是正式事实。

**修改文件：**
- 修改：`src/drawing_graph/qa_service.py`
- 修改：`tests/test_qa_service.py`

**独立测试：**
- `python -m unittest tests.test_qa_service -v`

**完成标准：**
- `candidate_relations` 支持 `page_id` 和 `block_id` 两种 scope。
- 调用 `facade.list_candidate_relations(page_id=..., block_id=...)`。
- 如果 scope 包含 `page_id`，额外尝试调用 `facade.list_section_matches(page_id=page_id, statuses=("candidate",))`，将断面候选也纳入输出。
- 所有候选输出的 `AnswerFact.fact_kind` 必须为 `candidate_relation`。
- 输出保留 `candidate_group_id`、`relation_type`、`status`、`score`、`conflict_reason`、`rule_version` 等可用证据字段。
- 候选为空时返回可读 summary，例如没有找到候选关系；不得伪造 formal relation。
- 测试覆盖 page scope、block scope、候选为空、断面候选存在、候选查询不可用、`matched_candidate` 不被写成正式事实。

## Task 6: 实现 `section_matches` 问答

**目标：** 支持按 `cross_section_id` 或 `page_id` 查询断面候选/正式匹配，并在需要时执行只读 dry-run 匹配判断。

**修改文件：**
- 修改：`src/drawing_graph/qa_service.py`
- 修改：`tests/test_qa_service.py`

**独立测试：**
- `python -m unittest tests.test_qa_service -v`

**完成标准：**
- `section_matches` 调用 `facade.list_section_matches(cross_section_id=..., page_id=...)`。
- 当 scope 包含 `cross_section_id` 且需要补充 dry-run 判断时，可以调用 `facade.match_section_caption(cross_section_id, page_id=..., write_back=False)`。
- 严禁传入 `write_back=True`。
- `SectionMatchSummary.fact_kind="candidate_relation"` 的结果保持候选输出，`fact_kind="formal_relation"` 的结果才可作为正式关系输出。
- 输出保留 `logical_key`、`symbol_system`、`candidate_count`、`conflict_reason`、`observation_ids`、`rule_version`、`alias_rule_id`。
- 多候选、无匹配、歧义状态要保守表达，不补猜。
- 测试覆盖 formal、candidate、ambiguous、match_not_found、dry-run 不写回、断面匹配查询不可用。

## Task 7: 实现 `table_caption_status` 问答

**目标：** 支持表格标题状态问答的 MVP：能确认页面来源元素存在性，并在缺少 facade 专用状态查询时返回明确 partial 和 unsupported 部分。

**修改文件：**
- 修改：`src/drawing_graph/qa_service.py`
- 修改：`tests/test_qa_service.py`

**独立测试：**
- `python -m unittest tests.test_qa_service -v`

**完成标准：**
- `table_caption_status` 支持 `page_id`、`table_id`、`table_caption_id` scope。
- 第一阶段只通过 `facade.get_page_source_facts(page_id)` 获取页面中的 `Table` 与 `TableCaption` 来源事实；如果只有 `table_id` 或 `table_caption_id` 且无法反查页面，返回 `partial` 或 `unsupported`，不直接查询 Neo4j。
- 输出页面内表格数量、表格标题数量、相关来源元素 ID 和 bbox，事实类型为 `source_fact`。
- 对“表格标题是否已派生为 `Table -[:HAS_CAPTION]-> TableCaption`”这类当前 facade 无专用方法的问题，必须写入 `unsupported_parts`，并设置 `status="partial"`。
- 不得在 QAService 中拼写 Cypher 或直接调用 `RelationRepository`。
- 测试覆盖页面有表格和标题、页面无表格、仅 table ID 缺少 page scope、缺少 facade 状态能力时返回 partial、不得调用底层 repository。

## Task 8: 实现 `diagnostic_status` 问答

**目标：** 支持按页面或 block 给出导入、增强、语义证据和候选状态的只读诊断。

**修改文件：**
- 修改：`src/drawing_graph/qa_service.py`
- 修改：`tests/test_qa_service.py`

**独立测试：**
- `python -m unittest tests.test_qa_service -v`

**完成标准：**
- `diagnostic_status` 支持 `page_id` 或 `block_id`。
- page scope 调用 `get_page_source_facts()`，并可选查询 observation、interpretation、candidate relation、section matches。
- block scope 调用 `get_block_trace()`、`get_block_relations()`，并可选查询 candidate relation。
- 输出 `diagnostic` fact，用于描述导入可见性、增强状态、候选状态、语义证据是否存在。
- 如果集成测试或 live Neo4j 状态未在本次运行中验证，诊断回答不得声称 live Neo4j 已通过；只描述当前查询结果。
- 测试覆盖 page 诊断、block 诊断、语义不可用降级、候选不可用降级、not_found。

## Task 9: 实现 QA 中文简短渲染

**目标：** 将结构化 `QAAnswer` 渲染为简短中文文本，供 CLI `--format zh-brief` 使用，同时保持 JSON 为权威输出。

**修改文件：**
- 新增：`src/drawing_graph/qa_rendering.py`
- 新增：`tests/test_qa_rendering.py`

**独立测试：**
- `python -m unittest tests.test_qa_rendering -v`

**完成标准：**
- 提供 `render_qa_answer_zh_brief(answer: QAAnswer) -> str` 或等价函数。
- 渲染内容包含 summary、主要 facts、warnings、unsupported_parts。
- 候选关系渲染必须出现“候选”或等价保守表述，不能写成“已确认”。
- `formal_relation` 才能渲染为“正式关系”或“已确认关系”。
- `partial`、`ambiguous`、`not_found`、`not_recognized`、`recognition_failed` 等状态要保守表达。
- 渲染层只读取 `QAAnswer`，不调用 facade、不读取环境变量、不访问 Neo4j。

## Task 10: 实现 QA CLI adapter

**目标：** 提供 `scripts/drawing_graph_qa.py`，通过命令行调用 QAService，并支持 JSON 与简短中文输出。

**修改文件：**
- 新增：`scripts/drawing_graph_qa.py`
- 新增：`tests/test_qa_cli.py`

**独立测试：**
- `python -m unittest tests.test_qa_cli -v`

**完成标准：**
- CLI 支持 `ask-page`、`ask-block`、`ask-candidates`、`ask-section`、`ask-table-caption`、`diagnose` 子命令。
- CLI 支持 `--format json` 和 `--format zh-brief`，默认建议为 `json`。
- CLI 从 `ImportConfig.from_env()` 读取 Neo4j 配置，使用 `create_neo4j_tool_facade(driver)` 创建 facade，再创建 `DrawingGraphQAService`。
- CLI 只在最外层创建和关闭 Neo4j driver；不直接调用 `QueryService`、`RelationRepository`、Cypher 或底层导入/增强脚本。
- 成功时 stdout 输出，已知业务错误返回退出码 `1`，配置或依赖初始化失败返回退出码 `2`。
- stderr 错误输出脱敏，不暴露 password、secret、token、Cypher、driver 栈。
- 测试使用 fake config、fake driver、fake facade 或 fake QAService，不连接真实 Neo4j。

## Task 11: 更新 QA 文档与边界测试

**目标：** 在实现后同步当前真实状态，明确 QAService 是 facade 外侧编排层，并保护不写 Cypher、默认只读、HTTP/MCP 未完成等文档边界。

**修改文件：**
- 修改：`README.md`
- 修改：`Module.md`
- 修改：`architecture.md`
- 新增：`tests/test_qa_docs.py`

**独立测试：**
- `python -m unittest tests.test_qa_docs -v`
- `python -m unittest tests.test_readme -v`
- `python -m unittest tests.test_module_docs -v`

**完成标准：**
- `README.md` 增加 QA CLI 的最短使用示例，至少包含 `ask-page`、`ask-block`、`ask-candidates`。
- `Module.md` 记录 `qa_models.py`、`qa_service.py`、`qa_rendering.py`（如创建）和 `scripts/drawing_graph_qa.py` 的职责。
- `architecture.md` 记录依赖方向：`QA adapter -> DrawingGraphQAService -> DrawingGraphToolFacade -> ports/services -> repository/Neo4j`。
- 文档明确第一阶段不实现 HTTP API、MCP Tool adapter、Ava 对接、OCR、真实模型供应商和数据库 schema 变更。
- 文档明确 QA 默认只读、`write_back=false`、候选关系不是正式事实、QAService 不直接写 Cypher。
- 文档测试检查上述关键边界词，防止规划能力被写成已完成能力。

## Task 12: 全量回归与 QA 边界验收

**目标：** 验证 Tool 层 QA 编排不破坏既有导入、离线增强、语义证据、候选复核和 facade 能力，并明确 live Neo4j 验证边界。

**修改文件：**
- 修改：`changes/tool层/tasks.md`
- 不修改业务代码；仅在完成实现后追加验收记录。

**独立测试：**
- `python -m unittest discover tests -v`
- 如配置了 disposable Neo4j：`python -m unittest discover tests.integration -v`

**完成标准：**
- 单元测试全量通过。
- 如果未配置 `NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD`，明确报告集成测试跳过且 live Neo4j 未验证。
- 确认 QAService 不直接依赖 Neo4j driver、Cypher、`QueryService`、`RelationRepository` 或 `block_relation_enrichment.py`。
- 确认 QA CLI 不触发导入、离线增强、候选复核写回、语义证据持久化或正式关系提升。
- 确认没有新增 HTTP API、MCP Tool adapter、Ava 对接、真实模型供应商、OCR 或 schema 变更。

### Task 12 验收记录

- 回归命令：`python -m unittest discover tests` 已运行，635 个单元测试全部通过，3 个集成测试跳过。
- 独立测试：`tests.test_qa_models` 28 个、`tests.test_qa_service` 49 个、`tests.test_qa_rendering` 6 个、`tests.test_qa_cli` 10 个、`tests.test_qa_docs` 6 个均通过；`tests.test_readme`、`tests.test_module_docs`、`tests.test_planning_docs` 保持通过。
- live Neo4j 边界：未配置 `NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD`，`tests/integration/` 按设计跳过；集成测试跳过不等于 live Neo4j 已验证，live Neo4j 未验证。
- 依赖边界确认：`DrawingGraphQAService` 只依赖 `qa_models` 与 `tool_models.ToolModelError`，不创建 Neo4j driver、不写 Cypher、不直接依赖 `QueryService`、`RelationRepository` 或 `block_relation_enrichment.py`；QA CLI 只在最外层创建和关闭 driver。
- 行为边界确认：QA CLI 不触发导入、离线增强、候选复核写回、语义证据持久化或正式关系提升；`match_section_caption` 只以 `write_back=False` dry-run 方式调用。
- 范围确认：本阶段已实现 QAService、QA CLI 与 QA DTO；未新增 HTTP API、MCP Tool adapter、Ava 对接、OCR、真实模型供应商或数据库 schema 变更。
