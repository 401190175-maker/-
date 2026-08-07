# 最小 Tool Facade 实施任务

> 本文件依据 `changes/tool-facade/design.md` 生成。每个任务只交付一个明确能力，均要求先写测试、再实现；真实 Neo4j 和真实云模型不作为单元测试前提。未实现的 Tool adapter、Skill、HTTP API、完整语义证据层不能在文档中写成已完成。

## Task 1: 定义 Tool DTO 与统一错误契约

**目标：** 建立 facade 对外请求、响应、分页、证据定位和错误 envelope 的稳定数据模型，避免 Tool 消费 Neo4j 内部 dict。

**修改文件：**
- 新增：`src/drawing_graph/tool_models.py`
- 新增：`tests/test_tool_models.py`

**独立测试：**
- `python -m unittest tests.test_tool_models -v`

**完成标准：**
- 定义图纸册摘要、页面摘要、来源事实、元素证据、分页信息、Tool 错误 envelope 的不可变 DTO。
- DTO 字段使用业务 ID 和证据定位字段，不包含 Neo4j driver、session、transaction、Cypher 字符串。
- 非法 `limit`、空 ID、非法 bbox、非法错误码会抛出稳定模型异常。
- 测试覆盖正常构造、非法输入、DTO 不暴露 Neo4j 内部对象。

## Task 2: 定义只读查询 port

**目标：** 为 facade 定义最小只读查询接口，使 facade 依赖业务 port，而不是直接依赖 Neo4j driver 或 `QueryService` 内部实现。

**修改文件：**
- 新增：`src/drawing_graph/query_ports.py`
- 新增：`tests/test_query_ports.py`

**独立测试：**
- `python -m unittest tests.test_query_ports -v`

**完成标准：**
- 定义 `DrawingGraphReadPort` 或等价协议，至少包含列图纸册、列页面、获取页面来源事实、查询图块追溯、查询图块关系。
- port 方法签名只接收稳定业务参数和 DTO，不接收 driver、session、transaction 或 Cypher。
- 提供 fake port 用于测试 facade；fake port 不连接 Neo4j。
- 测试验证 facade 可通过 fake port 类型契约完成只读调用。

## Task 3: 实现 QueryService 到只读 port 的适配器

**目标：** 复用现有 `QueryService` 查询能力，输出 Tool DTO 投影，屏蔽内部 dict 字段和底层查询异常。

**修改文件：**
- 新增：`src/drawing_graph/query_port_adapter.py`
- 修改：`src/drawing_graph/query_service.py`
- 新增：`tests/test_query_port_adapter.py`

**独立测试：**
- `python -m unittest tests.test_query_port_adapter -v`

**完成标准：**
- 适配器调用 `QueryService.get_project_sets()`、`get_set_pages()`、`get_block_trace()`、`get_block_relations()` 并转换为 Tool DTO。
- `QueryError` 被转换为 Tool 层可识别错误，不泄露 Cypher 或 driver 栈。
- 不重写 `QueryService` 的 Neo4j 查询结构；只做必要的小扩展或投影。
- 测试使用 fake `QueryService` 返回 dict，验证输出 DTO 字段稳定。

## Task 4: 实现单页来源事实查询投影

**目标：** 支持通过 `page_id` 获取页面图片、尺寸、来源元素、bbox 和 source label，为后续单页识别提供只读事实。

**修改文件：**
- 新增：`src/drawing_graph/source_fact_query.py`
- 修改：`src/drawing_graph/query_port_adapter.py`
- 新增：`tests/test_source_fact_query.py`

**独立测试：**
- `python -m unittest tests.test_source_fact_query -v`

**完成标准：**
- 返回 `page_id`、`image_path`、可选 `image_size`、`elements[]`。
- 元素覆盖 `DrawingBlock`、`BlockCaption`、`Table`、`TableCaption`、`DrawingBasicInfo`、`DrawingAnnotation`、`CrossSection` 的稳定类型投影。
- 支持 `element_types` 过滤和 `include_image_meta` 开关。
- 找不到页面返回 `NOT_FOUND` 语义错误；不连接真实云模型，不写图谱。

## Task 5: 实现只读 DrawingGraphToolFacade

**目标：** 暴露最小只读 facade 方法：列图纸册、列页面、获取单页来源事实、查询图块追溯、查询图块关系。

**修改文件：**
- 新增：`src/drawing_graph/tool_facade.py`
- 新增：`tests/test_tool_facade_read_only.py`

**独立测试：**
- `python -m unittest tests.test_tool_facade_read_only -v`

**完成标准：**
- `DrawingGraphToolFacade` 只依赖只读 port，不依赖 Neo4j driver、Repository、CLI 脚本或 Cypher。
- 所有只读方法忽略或拒绝写回意图，保持查询无副作用。
- 底层异常统一转换为 Tool 错误 envelope 或统一应用异常。
- 测试验证 facade 使用 fake port 可独立运行，并验证返回值不包含内部 dict。

## Task 6: 定义语义识别模型

**目标：** 定义 `RecognitionRun` 引用 DTO、`TextObservation`、识别状态和候选语义关系的数据模型，不把 `RecognitionRun` 建成图谱节点。

**修改文件：**
- 新增：`src/drawing_graph/semantic_models.py`
- 新增：`tests/test_semantic_models.py`

**独立测试：**
- `python -m unittest tests.test_semantic_models -v`

**完成标准：**
- `TextObservation` 包含 `observation_id`、`recognition_run_id`、`target_element_id`、`target_element_type`、`page_id`、`raw_text`、`normalized_text`、bbox、confidence、status、`image_hash`、`cache_key`。
- 状态限定为 `confirmed`、`matched_candidate`、`partial`、`ambiguous`、`not_found`、`recognition_failed`。
- `RecognitionRun` 只作为运行日志摘要或引用 DTO 出现，不进入 Neo4j 节点模型。
- 测试覆盖非法状态、缺少来源元素、非法置信度和 bbox。

## Task 7: 定义多模态识别客户端协议与 fake client

**目标：** 建立云端多模态识别的可替换协议，并提供单元测试用 fake client；第一版不默认调用真实外部供应商。

**修改文件：**
- 新增：`src/drawing_graph/semantic_client.py`
- 新增：`tests/test_semantic_client.py`

**独立测试：**
- `python -m unittest tests.test_semantic_client -v`

**完成标准：**
- 定义客户端协议，输入包含页面图片引用、目标元素 bbox、`model_profile`、`prompt_version` 和最小上下文。
- fake client 可返回成功、部分成功、失败和不可解析输出。
- 客户端协议不接收 API key 自由文本；真实供应商实现不在本任务内。
- 测试验证 fake client 可驱动后续 service，且失败会保留可分类错误。

## Task 8: 实现语义识别 dry-run service

**目标：** 根据页面来源事实和 fake/注入式客户端生成临时 observation；`write_back=false` 时不产生任何持久化副作用。

**修改文件：**
- 新增：`src/drawing_graph/semantic_service.py`
- 修改：`src/drawing_graph/tool_facade.py`
- 新增：`tests/test_semantic_service_dry_run.py`

**独立测试：**
- `python -m unittest tests.test_semantic_service_dry_run -v`

**完成标准：**
- 输入 `page_id`、`target_types`、`model_profile`、`prompt_version`、`write_back`。
- `write_back` 默认按 `false` 处理，并返回 `persisted=false`。
- dry-run 可返回临时 `recognition_run_id` 和 observation 摘要，但不调用 run log repository 或 semantic repository。
- 测试用 spy repository 验证无写入调用。

## Task 9: 实现图谱外 RecognitionRun 日志 port

**目标：** 建立图谱外运行日志的持久化与查询边界，确保 `RecognitionRun` 不作为 Neo4j 节点。

**修改文件：**
- 新增：`src/drawing_graph/recognition_run_log.py`
- 新增：`tests/test_recognition_run_log.py`

**独立测试：**
- `python -m unittest tests.test_recognition_run_log -v`

**完成标准：**
- 定义创建、完成、失败、按 `recognition_run_id` 查询运行日志的 port。
- 实现一个文件或内存型测试实现，记录模型、prompt、输入范围、状态、错误、开始/结束时间、`write_back`。
- 查询不存在的 run 返回 `NOT_FOUND` 语义错误。
- 测试验证日志实现不创建 Neo4j driver，也不写入图谱节点。

## Task 10: 实现语义证据 repository port

**目标：** 定义并实现 `TextObservation` 的图谱内语义证据写入/查询边界，保持与图谱外 run log 仅通过 ID 关联。

**修改文件：**
- 新增：`src/drawing_graph/semantic_repository.py`
- 新增：`tests/test_semantic_repository.py`

**独立测试：**
- `python -m unittest tests.test_semantic_repository -v`

**完成标准：**
- 定义写入 observation、按 `page_id` 查询、按 `element_id` 查询、按 `recognition_run_id` 查询的方法。
- repository 保存 `TextObservation`，并保留 `recognition_run_id` 字段，不创建 `RecognitionRun` 图谱节点。
- 写入失败返回 `SEMANTIC_EVIDENCE_UNAVAILABLE` 或等价分类错误。
- 测试使用 fake transaction 或 in-memory implementation 验证写入和查询契约。

## Task 11: 接入 `write_back=true` 的语义识别持久化

**目标：** 在 facade/service 中实现显式写回：只有 `write_back=true` 才写入 run log 和 `TextObservation`。

**修改文件：**
- 修改：`src/drawing_graph/semantic_service.py`
- 修改：`src/drawing_graph/tool_facade.py`
- 新增：`tests/test_semantic_service_write_back.py`

**独立测试：**
- `python -m unittest tests.test_semantic_service_write_back -v`

**完成标准：**
- `write_back=true` 时先创建图谱外 run log，再调用识别客户端，再写入 `TextObservation`。
- 识别失败时，如果 run log 已创建，记录 failed 状态。
- 语义证据写入失败不能创建正式关系，也不能返回 dry-run 成功。
- 测试覆盖默认 false、显式 true、run log 不可用、语义仓储不可用、识别失败。

## Task 12: 实现 RecognitionRun 与 TextObservation 查询 facade

**目标：** facade 暴露只读查询运行日志和语义观察结果的方法，返回稳定 Tool DTO。

**修改文件：**
- 修改：`src/drawing_graph/tool_facade.py`
- 修改：`src/drawing_graph/tool_models.py`
- 新增：`tests/test_tool_facade_semantic_queries.py`

**独立测试：**
- `python -m unittest tests.test_tool_facade_semantic_queries -v`

**完成标准：**
- 支持按 `recognition_run_id` 查询 run log 摘要。
- 支持按 `page_id`、`element_id` 或 `recognition_run_id` 查询 observation，并支持状态过滤。
- 查询结果包含证据定位，不返回 Neo4j 内部 label 组合或 Cypher。
- 测试验证找不到 run/observation 时返回稳定 `NOT_FOUND`。

## Task 13: 定义候选语义关系 facade DTO 与只读查询

**目标：** 让 Tool 能查看候选语义关系，但不把候选关系当作正式事实。

**修改文件：**
- 修改：`src/drawing_graph/tool_models.py`
- 修改：`src/drawing_graph/tool_facade.py`
- 新增：`tests/test_tool_facade_candidate_queries.py`

**独立测试：**
- `python -m unittest tests.test_tool_facade_candidate_queries -v`

**完成标准：**
- 候选关系 DTO 包含 `candidate_group_id`、`relation_type`、`status`、`score`、`conflict_reason`、`evidence_ids`、`recognition_run_id`。
- 支持按 `page_id`、`block_id`、`relation_type`、`status` 过滤。
- 返回中明确区分 candidate 与 formal relation。
- 测试验证 `matched_candidate` 和候选边不会被投影成正式事实。

## Task 14: 实现候选关系审核 dry-run

**目标：** 支持调用候选审核 facade 时在 `write_back=false` 下返回将如何处理的结果，但不更新候选状态。

**修改文件：**
- 修改：`src/drawing_graph/tool_facade.py`
- 修改：`src/drawing_graph/candidate_review.py`
- 新增：`tests/test_tool_facade_candidate_review_dry_run.py`

**独立测试：**
- `python -m unittest tests.test_tool_facade_candidate_review_dry_run -v`

**完成标准：**
- 审核请求包含 `candidate_group_id`、`decision`、`reviewer`、`reason`、`write_back`。
- `write_back=false` 返回 `persisted=false` 和预计审核状态。
- dry-run 不调用 `RelationRepository.update_candidate_review()` 或 `promote_candidate_relation()`。
- 测试用 spy repository 验证候选状态未写回。

## Task 15: 实现候选关系审核 `write_back=true`

**目标：** 显式写回候选审核结果，并确保 accepted 仍经过 `CandidateReviewService` 和硬规则校验。

**修改文件：**
- 修改：`src/drawing_graph/tool_facade.py`
- 修改：`src/drawing_graph/candidate_review.py`
- 修改：`src/drawing_graph/relation_repository.py`
- 新增：`tests/test_tool_facade_candidate_review_write_back.py`

**独立测试：**
- `python -m unittest tests.test_tool_facade_candidate_review_write_back -v`

**完成标准：**
- `write_back=true` 时才允许更新候选审核状态或触发候选提升。
- accepted 候选必须通过现有硬规则；失败返回 `CANDIDATE_REVIEW_REJECTED` 或等价分类错误。
- 不开放任意 relation spec；只允许受控候选关系规格。
- 测试覆盖 accepted、rejected、unresolved、重复审核冲突、硬规则失败。

## Task 16: 增加 facade 配置工厂

**目标：** 集中创建 facade 依赖，保证 Tool 请求不能传入 Neo4j 密码或供应商密钥。

**修改文件：**
- 修改：`src/drawing_graph/config.py`
- 新增：`src/drawing_graph/tool_factory.py`
- 新增：`tests/test_tool_factory.py`

**独立测试：**
- `python -m unittest tests.test_tool_factory -v`

**完成标准：**
- 工厂从受控配置读取默认 `write_back=false`、模型 profile、run log 路径等配置。
- Tool 请求不能覆盖 Neo4j URI、Neo4j 密码或供应商 API key。
- 工厂不会在模块 import 时连接 Neo4j 或扫描数据目录。
- 测试验证缺失配置、默认值、安全字段隔离和 package import 无副作用。

## Task 17: 更新架构与使用文档

**目标：** 在实现后同步真实状态，清楚区分已实现 facade 能力、阶段性语义证据能力和尚未实现的 Tool adapter/Skill/HTTP API。

**修改文件：**
- 修改：`architecture.md`
- 修改：`README.md`
- 修改：`Module.md`
- 新增或修改：`tests/test_tool_facade_docs.py`

**独立测试：**
- `python -m unittest tests.test_tool_facade_docs -v`
- `python -m unittest tests.test_cross_section_docs -v`

**完成标准：**
- 文档说明 facade、DTO、port、`write_back`、dry-run、run log 和 `TextObservation` 的真实实现状态。
- 文档不声称 HTTP API、Agent Skill、MCP Tool adapter 或全量自动语义扫描已完成。
- 明确真实 Neo4j 集成测试需要单独配置测试库；跳过不等于通过。
- 文档测试覆盖关键边界词：`write_back=false`、`RecognitionRun` 图谱外、`TextObservation` 图谱内、候选关系不是正式事实。

## Task 18: 全量回归与边界验收

**目标：** 验证最小 Tool facade 不破坏既有导入、离线增强、候选复核和查询能力，并确认 live Neo4j 边界。

**修改文件：**
- 修改：`changes/tool-facade/tasks.md`
- 不修改业务代码；仅在必要时更新测试说明或验收记录。

**独立测试：**
- `python -m unittest discover tests -v`
- 如配置了 disposable Neo4j：`python -m unittest discover tests.integration -v`

**完成标准：**
- 单元测试全量通过。
- 如果未配置 `NEO4J_TEST_URI` 或 disposable Neo4j，明确报告集成测试跳过且未验证。
- 确认 `ImportService`、`RelationEnrichmentService` 和 CLI 仍保持显式运行边界。
- 确认没有新增 HTTP API、Agent Skill、真实云模型默认调用或全量自动语义扫描。

### Task 18 验收记录

- 回归命令：`python -m unittest discover tests -v`。
- live Neo4j 边界：如果未配置 `NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD`，集成测试会跳过；跳过不等于通过，不能声称真实 Neo4j 已验证。
- 现有流程边界：`ImportService`、`RelationEnrichmentService` 和 CLI 继续保持显式运行方式，Tool facade 不自动触发导入或离线增强。
- 范围确认：没有新增 HTTP API，没有新增 Agent Skill，没有默认调用真实云模型，没有新增全量自动语义扫描。
