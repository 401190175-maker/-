# 语义证据层实施任务

> 本文件依据 `changes/语义证据层/proposal.md`、`design.md` 和 `Feature_Analysis_Report.md` 生成。每个任务只交付一个明确能力，均要求可独立测试。实施时禁止无意义重构，优先复用现有 Tool Facade、read port、semantic service/repository port、run log port、候选审核和受控 repository 边界。

## 全局约束

- 不重写基础导入、离线派生关系增强、`QueryService`、候选复核 CLI 或 Neo4j repository 主体结构。
- 不把语义识别放进 `block_relation_enrichment.py`。
- 不让 `scripts/import_json.py` 自动触发语义识别。
- 不让 `scripts/enrich_block_relations.py` 默认触发多模态识别或候选复核。
- `RecognitionRun` 保持图谱外，不作为 Neo4j 节点。
- `TextObservation` 和各类 `Interpretation` 位于图谱内，并通过 `recognition_run_id` 回查运行日志。
- `write_back=false` 默认不持久化；只有显式 `write_back=true` 才写入 run log、语义证据或候选/正式语义边。
- 候选关系不是正式事实；`matched_candidate` 不是正式关系。
- 没有双方可比较 `TextObservation`、规范化逻辑键和唯一证据时，不写入 `MATCHES_SECTION_CAPTION`。
- 不实现 HTTP API、Agent Skill、MCP Tool adapter、全量自动语义扫描或全量离线 OCR。

## Task 1: 扩展 TextObservation 数据契约

**目标：** 完整定义图谱内通用文字观察模型，确保模型输出只作为可追溯 observation，不覆盖来源事实。

**修改文件：**

- 修改：`src/drawing_graph/semantic_models.py`
- 新增或修改：`tests/test_semantic_models.py`

**可独立测试：**

- `python -m unittest tests.test_semantic_models -v`

**完成标准：**

- `TextObservation` 包含 `observation_id`、`recognition_run_id`、`target_element_id`、`target_element_type`、`page_id`、`raw_text`、`normalized_text`、`bbox`、`normalized_bbox`、`confidence`、`status`、`image_hash`、`cache_key`、`model_profile`、`prompt_version`、`created_at`。
- 状态限制至少包含 `confirmed`、`matched_candidate`、`partial`、`ambiguous`、`not_found`、`recognition_failed`。
- `matched_candidate` 在模型或 DTO 注释中明确不是正式事实。
- 非法 bbox、非法 confidence、空来源元素 ID、非法状态会抛出稳定模型异常。

## Task 2: 定义 Interpretation 数据契约

**目标：** 定义 `BlockInterpretation`、`BasicInfoInterpretation` 和 `TableInterpretation`，使结构化解析与来源节点分离。

**修改文件：**

- 修改：`src/drawing_graph/semantic_models.py`
- 修改：`tests/test_semantic_models.py`

**可独立测试：**

- `python -m unittest tests.test_semantic_models -v`

**完成标准：**

- 定义 `BlockInterpretation`，包含 `interpretation_id`、`recognition_run_id`、`block_id`、`summary`、`interpreted_type`、`components`、`materials`、`dimensions`、`construction_features`、`spatial_relations`、`analysis_status`、`uncertainties`、`payload_ref`、`cache_key`、`contract_version`。
- 定义 `BasicInfoInterpretation`，包含基础信息字段、字段级不确定性、`payload_ref`、`analysis_status` 和版本字段。
- 定义 `TableInterpretation`，包含表格摘要、标题引用、`payload_ref`、`analysis_status` 和版本字段。
- `interpreted_type` 只存在于 `BlockInterpretation`，测试明确禁止其投影为 `DrawingBlock.block_type`。

## Task 3: 实现语义缓存键生成

**目标：** 为 observation、interpretation 和关系匹配提供稳定 cache key，支持按输入和版本判断复用。

**修改文件：**

- 新增：`src/drawing_graph/semantic_cache.py`
- 新增：`tests/test_semantic_cache.py`

**可独立测试：**

- `python -m unittest tests.test_semantic_cache -v`

**完成标准：**

- cache key 至少包含 `image_hash`、`bbox`、`target_element_id`、`task_type`、`model_profile`、`model_version`、`prompt_version`、`preprocessing_version`、`normalization_rule_version`、`contract_version`。
- 相同输入生成相同 key；任一关键输入变化生成不同 key。
- `TextObservation` cache key 不包含 `alias_rule_version`。
- 关系匹配 cache key 可以包含双方 observation、候选范围、匹配规则版本和别名规则版本。

## Task 4: 定义语义 payload 存储接口

**目标：** 为完整结构化解析 JSON 提供不可变外部 payload 存储边界，避免 Neo4j 节点属性承载大嵌套结构。

**修改文件：**

- 新增：`src/drawing_graph/semantic_payload_store.py`
- 新增：`tests/test_semantic_payload_store.py`

**可独立测试：**

- `python -m unittest tests.test_semantic_payload_store -v`

**完成标准：**

- 定义 `SemanticPayloadStore` port，支持 `put_payload(payload, content_hash)` 和 `get_payload(payload_ref)`。
- 提供 in-memory 或文件型测试实现。
- `payload_ref` 稳定引用不可变 payload；同一 content hash 可复用同一引用。
- 查询不存在的 `payload_ref` 返回稳定 `NOT_FOUND` 或等价错误。

## Task 5: 实现语义图像输入构造

**目标：** 根据来源事实构造模型输入所需的图片、bbox、元素和上下文引用，不调用模型、不写图谱。

**修改文件：**

- 新增：`src/drawing_graph/semantic_image_inputs.py`
- 修改：`src/drawing_graph/source_fact_query.py`
- 新增：`tests/test_semantic_image_inputs.py`

**可独立测试：**

- `python -m unittest tests.test_semantic_image_inputs -v`

**完成标准：**

- 可从 `PageSourceFacts` 生成单个目标元素的 `image_path`、`page_id`、`element_id`、`element_type`、`bbox`、`normalized_bbox`、`image_hash` 和上下文元素引用。
- 找不到元素时返回 `NOT_FOUND`。
- 无效 bbox 或缺失图片引用返回稳定错误。
- 模块不依赖 Neo4j driver，不调用 `MultimodalRecognitionClient`。

## Task 6: 扩展多模态客户端协议

**目标：** 让语义识别服务通过可替换协议调用 fake 或后续真实多模态客户端，并稳定分类响应错误。

**修改文件：**

- 修改：`src/drawing_graph/semantic_client.py`
- 修改：`tests/test_semantic_client.py`

**可独立测试：**

- `python -m unittest tests.test_semantic_client -v`

**完成标准：**

- 客户端协议输入包含图像引用、目标元素 bbox、`target_type`、`model_profile`、`prompt_version` 和最小页面上下文。
- fake client 支持成功、部分成功、失败、超时、不可解析输出。
- 客户端协议不接收 API key 自由文本。
- 不可解析输出被映射为 `RECOGNITION_FAILED` 或等价分类错误。

## Task 7: 扩展图谱外 RecognitionRun 日志

**目标：** 完整记录真实模型调用和候选复核运行过程，保持 `RecognitionRun` 不进入核心图谱。

**修改文件：**

- 修改：`src/drawing_graph/recognition_run_log.py`
- 修改：`tests/test_recognition_run_log.py`

**可独立测试：**

- `python -m unittest tests.test_recognition_run_log -v`

**完成标准：**

- run log 支持 `run_type=recognition`、`interpretation`、`candidate_review`。
- 记录 `target_scope`、`model_profile`、`model_name`、`model_version`、`prompt_version`、`input_refs`、`status`、`error_summary`、`started_at`、`finished_at`、`write_back` 和可选 `cost_summary`。
- 缓存命中和普通查询不创建新 run。
- 测试验证实现不创建 Neo4j driver，也不写入 `RecognitionRun` 图谱节点。

## Task 8: 扩展语义证据 repository port

**目标：** 定义图谱内语义证据读写边界，为后续 Neo4j 实现和 facade 查询提供稳定接口。

**修改文件：**

- 修改：`src/drawing_graph/semantic_repository.py`
- 修改：`tests/test_semantic_repository.py`

**可独立测试：**

- `python -m unittest tests.test_semantic_repository -v`

**完成标准：**

- port 支持写入和查询 `TextObservation`。
- port 支持写入和查询三类 `Interpretation`。
- port 支持按 `page_id`、`element_id`、`recognition_run_id` 和状态过滤查询。
- port 保存 `recognition_run_id` 字段，但不创建 `RecognitionRun` 节点。

## Task 9: 定义语义 Schema 静态规格

**目标：** 明确 Neo4j 中新增语义节点、关系、约束、索引和白名单，防止随意写图谱。

**修改文件：**

- 新增：`src/drawing_graph/semantic_schema.py`
- 修改：`scripts/create_schema.cypher`
- 新增：`tests/test_semantic_schema.py`

**可独立测试：**

- `python -m unittest tests.test_semantic_schema -v`

**完成标准：**

- 定义允许的语义节点标签：`TextObservation`、`BlockInterpretation`、`BasicInfoInterpretation`、`TableInterpretation`。
- 定义允许的语义关系：`HAS_OBSERVATION`、`HAS_INTERPRETATION`、`SUPPORTED_BY`、`CANDIDATE_MATCHES_SECTION_CAPTION`、`MATCHES_SECTION_CAPTION`。
- `scripts/create_schema.cypher` 使用 `IF NOT EXISTS` 增加必要约束和索引。
- 静态测试确认没有创建 `RecognitionRun` 节点约束。

## Task 10: 实现 TextObservation Neo4j 写入

**目标：** 将 `TextObservation` 作为图谱内证据节点幂等写入 Neo4j，并连接来源元素。

**修改文件：**

- 新增或修改：`src/drawing_graph/semantic_neo4j_repository.py`
- 修改：`src/drawing_graph/semantic_repository.py`
- 新增：`tests/test_semantic_neo4j_observations.py`

**可独立测试：**

- `python -m unittest tests.test_semantic_neo4j_observations -v`

**完成标准：**

- 写入 `TextObservation` 节点时使用稳定 `observation_id` 幂等 MERGE。
- 写入 `来源元素 -[:HAS_OBSERVATION]-> TextObservation`，来源元素标签来自受控白名单。
- 所有 Cypher 属性值参数化。
- 写入不创建 `RecognitionRun` 节点。

## Task 11: 实现 Interpretation Neo4j 写入

**目标：** 将三类结构化解释作为图谱内证据节点写入，并建立 `HAS_INTERPRETATION` 与 `SUPPORTED_BY`。

**修改文件：**

- 修改：`src/drawing_graph/semantic_neo4j_repository.py`
- 新增：`tests/test_semantic_neo4j_interpretations.py`

**可独立测试：**

- `python -m unittest tests.test_semantic_neo4j_interpretations -v`

**完成标准：**

- 可写入 `BlockInterpretation`、`BasicInfoInterpretation`、`TableInterpretation`。
- 来源节点分别只允许为 `DrawingBlock`、`DrawingBasicInfo`、`Table`。
- 可写入 `HAS_INTERPRETATION` 和 `SUPPORTED_BY`。
- 旧 interpretation 不被静默覆盖；新版本使用新节点或显式 `stale` 状态。

## Task 12: 扩展语义识别 dry-run 编排

**目标：** 在 `write_back=false` 下完成识别、缓存检查和临时结果返回，同时保证无持久化副作用。

**修改文件：**

- 修改：`src/drawing_graph/semantic_service.py`
- 修改：`src/drawing_graph/tool_facade.py`
- 修改：`tests/test_semantic_service_dry_run.py`

**可独立测试：**

- `python -m unittest tests.test_semantic_service_dry_run -v`

**完成标准：**

- dry-run 使用 `SemanticImageInputBuilder` 构造输入。
- dry-run 可以复用有效缓存或调用 fake client 生成临时 observation/interpretation。
- dry-run 返回 `persisted=false`。
- spy run log 和 spy repository 验证没有创建 run、没有写 observation、没有写 interpretation、没有写候选或正式关系。

## Task 13: 实现语义识别 write-back 编排

**目标：** 在 `write_back=true` 下持久化 run log、observation 和 interpretation，并正确处理失败状态。

**修改文件：**

- 修改：`src/drawing_graph/semantic_service.py`
- 修改：`src/drawing_graph/tool_facade.py`
- 修改：`tests/test_semantic_service_write_back.py`

**可独立测试：**

- `python -m unittest tests.test_semantic_service_write_back -v`

**完成标准：**

- `write_back=true` 先创建图谱外 run log，再调用模型或缓存，再写入图谱内语义证据。
- 识别失败时，如果 run 已创建，run 状态更新为 failed。
- 语义证据写入失败返回 `SEMANTIC_EVIDENCE_UNAVAILABLE` 或等价错误，不能伪装成 dry-run 成功。
- 不写入 `MATCHES_SECTION_CAPTION` 或其他正式关系。

## Task 14: 扩展 Tool 语义 DTO

**目标：** 为 Tool Facade 输出语义观察、解释、payload、候选关系和正式关系提供稳定 DTO。

**修改文件：**

- 修改：`src/drawing_graph/tool_models.py`
- 修改：`tests/test_tool_models.py`

**可独立测试：**

- `python -m unittest tests.test_tool_models -v`

**完成标准：**

- 增加 `SemanticObservationSummary`、`SemanticInterpretationSummary`、`SemanticPayloadSummary`、`SectionMatchSummary`、`SemanticCandidateRelationSummary`。
- DTO 包含 `fact_kind`、`status`、`evidence`、`persisted`、`warnings`。
- 候选关系 DTO 的 `fact_kind` 固定为 `candidate_relation`。
- DTO 不包含 Neo4j driver、session、transaction、Cypher 或内部节点 ID。

## Task 15: 实现语义查询投影

**目标：** 把来源事实、空间关系、observation、interpretation、候选/正式关系和 run log 摘要组合成统一只读输出。

**修改文件：**

- 新增：`src/drawing_graph/semantic_query_projection.py`
- 新增：`tests/test_semantic_query_projection.py`

**可独立测试：**

- `python -m unittest tests.test_semantic_query_projection -v`

**完成标准：**

- 输入可包含来源事实 DTO、关系 DTO、observation、interpretation、run log 摘要和候选/正式关系。
- 输出明确区分 `source_fact`、`derived_relation`、`semantic_observation`、`semantic_interpretation`、`candidate_relation`、`formal_relation`。
- 没有语义证据时返回 `not_recognized` 或 `not_interpreted`。
- 不把候选关系投影为正式关系。

## Task 16: 扩展 Tool Facade 语义查询 API

**目标：** 通过 `DrawingGraphToolFacade` 暴露只读语义查询能力，不让调用端直接访问 repository。

**修改文件：**

- 修改：`src/drawing_graph/tool_facade.py`
- 修改：`tests/test_tool_facade_semantic_queries.py`

**可独立测试：**

- `python -m unittest tests.test_tool_facade_semantic_queries -v`

**完成标准：**

- facade 支持按 `recognition_run_id` 查询 run log。
- facade 支持按 `page_id`、`element_id`、`recognition_run_id` 和状态过滤查询 observation。
- facade 支持按元素查询 interpretation 摘要。
- 查询结果通过 `SemanticQueryProjection` 返回，不暴露 repository 内部对象。

## Task 17: 实现完整 payload 查询 API

**目标：** 允许调用端通过 `payload_ref` 读取完整不可变结构化解析 JSON。

**修改文件：**

- 修改：`src/drawing_graph/tool_facade.py`
- 修改：`src/drawing_graph/tool_models.py`
- 修改：`tests/test_tool_facade_semantic_queries.py`

**可独立测试：**

- `python -m unittest tests.test_tool_facade_semantic_queries -v`

**完成标准：**

- facade 提供 `get_semantic_payload(payload_ref)` 或等价方法。
- 找不到 payload 返回稳定 `NOT_FOUND`。
- payload 查询只读，不触发模型调用或写回。
- 响应保留 `payload_ref`、`contract_version` 和内容 hash。

## Task 18: 实现断面标签规范化

**目标：** 将 `CrossSection` 端点标签和 `BlockCaption` 标题标签规范化为符号体系和逻辑键。

**修改文件：**

- 新增：`src/drawing_graph/section_label_normalization.py`
- 新增：`tests/test_section_label_normalization.py`

**可独立测试：**

- `python -m unittest tests.test_section_label_normalization -v`

**完成标准：**

- 支持 `alphabetic`、`roman`、`numeric`、`alphanumeric`、`unknown`。
- `A-A` 可生成 `SECTION_ALPHA_A`，`Ⅰ-Ⅰ` 可生成罗马体系逻辑键，`1-1` 可生成数字体系逻辑键。
- 默认不合并 `I-I`、`Ⅰ-Ⅰ` 和 `1-1`。
- `A-B` 或两个端点不一致时返回非确定状态，不生成确定逻辑键。

## Task 19: 实现图谱外断面别名规则配置

**目标：** 管理跨符号体系别名规则，使别名匹配有作用域、版本、确认状态和审计依据。

**修改文件：**

- 新增：`src/drawing_graph/section_alias_rules.py`
- 新增：`tests/test_section_alias_rules.py`

**可独立测试：**

- `python -m unittest tests.test_section_alias_rules -v`

**完成标准：**

- 定义 `SectionLabelAliasRule`，包含 `alias_rule_id`、`alias_rule_version`、`scope`、`from_symbol_system`、`to_symbol_system`、`mapping`、`status`、`evidence_ref`。
- 只有 `confirmed` 且 scope 命中的规则可参与匹配。
- `revoked`、`ambiguous` 或 scope 不匹配的规则不参与确定匹配。
- 模块不创建 Neo4j 节点。

## Task 20: 实现断面候选匹配服务

**目标：** 在双方已有可比较 `TextObservation` 时生成 `CANDIDATE_MATCHES_SECTION_CAPTION` 候选判断。

**修改文件：**

- 新增：`src/drawing_graph/section_match_service.py`
- 新增：`tests/test_section_match_service_candidates.py`

**可独立测试：**

- `python -m unittest tests.test_section_match_service_candidates -v`

**完成标准：**

- 没有 `CrossSection` observation 或 `BlockCaption` observation 时，不生成候选边。
- 同页存在多个同逻辑键标题时，为每个合理候选生成 candidate summary。
- 候选 summary 包含 `candidate_group_id`、`status`、`candidate_count`、`score`、`conflict_reason`、`observation_ids`、`rule_version`。
- 空间接近不能替代文本相等证据。

## Task 21: 实现断面正式匹配硬规则

**目标：** 仅在唯一、同页、逻辑键一致且无冲突时生成正式 `MATCHES_SECTION_CAPTION` 判断。

**修改文件：**

- 修改：`src/drawing_graph/section_match_service.py`
- 新增：`tests/test_section_match_service_formal.py`

**可独立测试：**

- `python -m unittest tests.test_section_match_service_formal -v`

**完成标准：**

- 双方必须存在可追溯 `TextObservation`。
- 双方必须能规范化为非 `unknown` 的逻辑键。
- 符号体系不同时必须命中 confirmed alias rule。
- 候选必须唯一，且目标 `BlockCaption` 与目标 `DrawingBlock` 关系不冲突。
- 任一条件不满足时返回 candidate 或 ambiguous，不返回 formal。

## Task 22: 写入断面候选与正式关系

**目标：** 通过受控 relation spec 将断面候选或正式语义关系写入 Neo4j。

**修改文件：**

- 修改：`src/drawing_graph/relation_repository.py`
- 修改：`src/drawing_graph/semantic_repository.py`
- 新增：`tests/test_semantic_section_relation_writes.py`

**可独立测试：**

- `python -m unittest tests.test_semantic_section_relation_writes -v`

**完成标准：**

- 只允许写入 `CrossSection -[:CANDIDATE_MATCHES_SECTION_CAPTION]-> BlockCaption`。
- 只允许写入 `CrossSection -[:MATCHES_SECTION_CAPTION]-> BlockCaption`。
- 写入使用受控 relation spec、稳定业务 ID 和参数化 Cypher。
- 不能开放任意起点、终点或关系类型。

## Task 23: 扩展语义候选审核

**目标：** 支持对 `CANDIDATE_MATCHES_SECTION_CAPTION` 进行显式三态审核，并保留硬规则校验。

**修改文件：**

- 修改：`src/drawing_graph/candidate_review.py`
- 修改：`src/drawing_graph/tool_facade.py`
- 新增：`tests/test_semantic_candidate_review.py`

**可独立测试：**

- `python -m unittest tests.test_semantic_candidate_review -v`

**完成标准：**

- 审核支持 `accepted`、`rejected`、`unresolved`。
- 复核请求必须包含完整候选集合、原始裁剪引用、页面上下文、空间证据和已有 observation。
- `accepted` 仍需通过 Task 21 的硬规则才能提升为正式关系。
- `write_back=false` 审核只返回 dry-run 结果，不更新候选状态。

## Task 24: 扩展 Tool Facade 断面匹配 API

**目标：** 通过 facade 暴露断面匹配和断面匹配查询能力。

**修改文件：**

- 修改：`src/drawing_graph/tool_facade.py`
- 修改：`src/drawing_graph/tool_models.py`
- 新增：`tests/test_tool_facade_section_matching.py`

**可独立测试：**

- `python -m unittest tests.test_tool_facade_section_matching -v`

**完成标准：**

- facade 支持 `match_section_caption(cross_section_id, page_id=None, write_back=False)` 或等价方法。
- `write_back=false` 返回匹配判断但不写候选或正式关系。
- `write_back=true` 只在服务判断允许时写入候选或正式关系。
- facade 支持查询 `CANDIDATE_MATCHES_SECTION_CAPTION` 和 `MATCHES_SECTION_CAPTION` 投影。

## Task 25: 扩展配置工厂

**目标：** 集中创建语义证据层依赖，保证 import 无副作用且敏感字段不从 Tool 请求进入。

**修改文件：**

- 修改：`src/drawing_graph/config.py`
- 修改：`src/drawing_graph/tool_factory.py`
- 修改：`tests/test_tool_factory.py`

**可独立测试：**

- `python -m unittest tests.test_tool_factory -v`

**完成标准：**

- 工厂支持受控配置：`default_write_back=false`、`model_profile`、`prompt_version`、`run_log_store`、`payload_store`、语义 repository 类型。
- Tool 请求不能覆盖 Neo4j URI、Neo4j 密码、供应商 API key、token 或 secret。
- 模块 import 时不连接 Neo4j、不扫描数据目录、不调用模型。
- 缺失必需配置时返回稳定配置错误。

## Task 26: 更新语义证据层文档

**目标：** 实现后同步当前真实状态，避免目标方案和已完成能力混写。

**修改文件：**

- 修改：`architecture.md`
- 修改：`README.md`
- 修改：`Module.md`
- 修改：`changes/语义证据层/design.md`
- 新增：`tests/test_semantic_docs.py`

**可独立测试：**

- `python -m unittest tests.test_semantic_docs -v`

**完成标准：**

- 文档明确 `RecognitionRun` 图谱外、`TextObservation` 图谱内。
- 文档明确 `write_back=false` 不持久化。
- 文档明确候选关系不是正式事实。
- 文档不声称 HTTP API、Agent Skill、MCP Tool adapter、全量自动扫描或真实云模型默认调用已完成。
- 文档明确真实 Neo4j 集成测试跳过不等于通过。

## Task 27: 全量回归与一致性验收

**目标：** 验证语义证据层没有破坏既有导入、离线增强、查询、候选复核和文档边界。

**修改文件：**

- 修改：`changes/语义证据层/tasks.md`
- 不修改业务代码；仅记录最终验收状态。

**可独立测试：**

- `python -m unittest discover tests -v`
- 如配置 disposable Neo4j：`python -m unittest discover tests.integration -v`

**完成标准：**

- 单元测试全量通过。
- 如果未配置 `NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD`，必须明确报告集成测试跳过且未验证 live Neo4j。
- 确认基础导入仍不自动触发离线增强或语义识别。
- 确认离线增强仍不默认触发多模态识别或候选复核。
- 确认没有新增 HTTP API、Agent Skill、MCP Tool adapter、全量自动语义扫描或默认真实云模型调用。

## 一致性检查

### 与 `proposal.md` 的一致性

- `proposal.md` 要求补齐语义证据层、图谱外 `RecognitionRun`、图谱内 observation/interpretation、`write_back` 边界、缓存、断面匹配和统一查询输出；本任务拆分覆盖 Task 1 到 Task 27。
- `proposal.md` 的不包含范围已进入全局约束和 Task 26、Task 27 的文档/回归验收。
- `proposal.md` 强调不覆盖来源事实、不写 `DrawingBlock.block_type`；Task 2、Task 15、Task 26 均设置了对应测试和完成标准。

### 与 `design.md` 的一致性

- `design.md` 的新增模块在 Task 3、Task 4、Task 5、Task 9、Task 18、Task 19、Task 20、Task 15 中分别落到独立任务。
- `design.md` 的修改模块在 Task 1、Task 2、Task 6、Task 7、Task 8、Task 12、Task 13、Task 14、Task 16、Task 22、Task 23、Task 25、Task 26 中覆盖。
- `design.md` 的 API 设计在 Task 14、Task 16、Task 17、Task 24 中覆盖。
- `design.md` 的前后端流程和异常/安全方案在 Task 12、Task 13、Task 20、Task 21、Task 23、Task 24、Task 26、Task 27 中覆盖。

### 与 `Feature_Analysis_Report.md` 的一致性

- 分析报告推荐“契约优先 + 持久化补齐 + 断面专项闭环 + 后续图块/基础信息/表格解释”；本任务顺序按同一主线组织。
- 分析报告强调不要把规划能力写成已实现；Task 26 和 Task 27 要求每阶段文档与回归验收区分真实实现状态。
- 分析报告列出的高风险，包括模型输出污染来源事实、`RecognitionRun` 被建成节点、候选关系被当事实、语义层塞进空间规则模块、`write_back` 失效，均在全局约束和具体任务完成标准中体现。

### 一致性结论

当前 `proposal.md`、`design.md`、`Feature_Analysis_Report.md` 与本 `tasks.md` 保持一致：三者都采用“复用现有架构、按需语义识别、逐步缓存、图谱外运行日志、图谱内语义证据、候选与正式关系分离”的主线。未发现互相冲突的目标或边界。需要注意的唯一执行风险是：当前文档将部分语义应用层文件描述为已有边界，但完整 Neo4j 持久化、断面正式匹配和生产级 run log 仍应按本任务文件逐步实现，不能提前写成已完成。

## 最终验收状态（Task 27 完成）

实施方式：按本文件 Task 1-27 顺序就地实施，每个 Task 完成后运行其“可独立测试”命令；未使用 Git 分支（当前目录不是有效 Git 仓库）。

验收结果：

- 全量回归（未临时注入 Neo4j env）：`python -m unittest discover tests -v` -> **512 tests OK, 3 skipped**；跳过项为 `tests/integration/test_neo4j_import.py`、`tests/integration/test_neo4j_relation_enrichment.py`、`tests/integration/test_neo4j_semantic_evidence.py`，原因是该命令未配置 `NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD`。
- 全量回归（单条命令临时注入 live Neo4j env，未写入文件）：`python -m unittest discover tests -v` -> **512 tests OK**，其中 3 个 `tests/integration/` 用例均真实执行并通过。
- live Neo4j 已验证基础导入、离线派生关系增强、语义证据写入、断面候选/正式关系写入、幂等和查询投影闭环；本轮使用 Browser 确认的 Bolt 地址 `bolt://127.0.0.1:7687`。
- 基础导入仍不自动触发离线派生关系增强或语义识别；离线派生关系增强仍不默认触发多模态识别或候选关系 AI 复核。
- 未新增 HTTP API、Agent Skill、MCP Tool adapter、全量自动语义扫描或默认真实云模型调用。
- `RecognitionRun` 保持图谱外，`TextObservation` 与三类 `Interpretation` 图谱内；`write_back=false` 不持久化；候选关系不是正式事实。
- 断面正式匹配只在双方存在可比较 `TextObservation`、规范化逻辑键一致、候选唯一且无规则冲突时写入 `MATCHES_SECTION_CAPTION`，否则只保留 `CANDIDATE_MATCHES_SECTION_CAPTION`。

文档同步说明：Task 26 更新 `architecture.md`、`README.md`、`Module.md` 与 `design.md`，并同步调整 `tests/test_cross_section_docs.py` 中与已实现断面匹配相冲突的旧断言（“MATCHES_SECTION_CAPTION 仍待支持/不建立”改为“受控条件下建立，证据不足时只保留候选”）。

## 追加验证记录（2026-08-06）

本轮先运行已有集成测试：

- `python -m unittest discover tests.integration -v` -> **3 skipped**。跳过项为 `test_neo4j_import.py`、`test_neo4j_relation_enrichment.py` 和新增的 `test_neo4j_semantic_evidence.py`，原因均为未配置 `NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD`。

覆盖缺口确认与补测：

- 原有 `tests/integration/` 只覆盖真实 Neo4j 的基础导入和离线派生关系增强，没有覆盖语义证据层 live Neo4j。
- 已新增 `tests/integration/test_neo4j_semantic_evidence.py`，用于在配置 disposable Neo4j 测试库后验证 `TextObservation`、`BlockInterpretation`、`BasicInfoInterpretation`、`TableInterpretation`、`HAS_OBSERVATION`、`HAS_INTERPRETATION`、`SUPPORTED_BY`、`CANDIDATE_MATCHES_SECTION_CAPTION`、`MATCHES_SECTION_CAPTION` 的真实写入、幂等和 Cypher 查询投影，并确认不创建 `RecognitionRun` 图谱节点。
- 用户启动 Neo4j 后，Neo4j Browser 显示 HTTP Browser 位于 `localhost:7474`，Bolt connector 位于 `127.0.0.1:7687`；因此测试命令使用 `bolt://127.0.0.1:7687`。
- `python -m unittest discover tests.integration -v`（单条命令临时注入 `NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD`，未写入文件）-> **3 tests OK**。
- `python -m unittest discover tests -v`（同样临时注入 live Neo4j env）-> **512 tests OK**。
- 本轮修复了 live Neo4j 暴露的兼容性问题：Neo4j 属性不接受 map 型 `bbox`，语义证据写入改为 `[x_min, y_min, x_max, y_max]` 列表；`BlockInterpretation` 写入 Cypher 在 `MERGE` 与 `OPTIONAL MATCH` 之间补齐 `WITH`；`table_caption` 特殊写入改用标量参数，避免 relation map 子属性在 live Neo4j 中写入失败。
