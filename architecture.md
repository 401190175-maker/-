# 图块图谱构建架构说明

## 1. 架构目标

本项目面向 XAnyLabeling 标注数据，在 Neo4j 中构建图块级可追溯知识图谱。系统采用分层图块图谱方案，基础追溯链路为：

```text
Project -> DrawingSet -> DrawingPage -> DrawingBlock
```

`DrawingSet` 用来区分不同图纸册目录，避免两个目录中出现同名页面时发生 ID 冲突。当前架构由基础导入、离线派生关系增强、候选关系复核和按需语义证据服务组成；这些流程相互独立，但可以通过稳定业务 ID、bbox、页面上下文和 facade 查询结果串联。

- 基础导入流程：扫描 JSON/PNG，建立项目、图纸册、页面、图块、页面元素、页面级来源关系和导入批次，只写原始标注可以直接确定的来源事实。
- 离线派生关系增强流程：在页面级图谱已经入库后显式运行，为 `Table` 补写表格标题关系，为 `DrawingPage` 补写基础信息上下文关系，并为 `DrawingBlock` 补写标题、注释、cross section 几何归属正式关系或空间候选关系。
- 候选关系复核流程：显式读取完整候选集合，经过独立复核和硬性规则校验后，只在满足规则时提升正式关系。
- 按需语义证据流程：通过 `DrawingGraphToolFacade` 调用语义服务、缓存、图谱外运行日志和语义 repository；默认 dry-run，只在显式 `write_back=true` 时写入语义证据或受控语义边。

当前阶段仍不包含 OCR、Ava 专有 adapter、全量自动语义扫描、默认真实云模型调用、`NEAR` 空间关系网络，也不设置或推断 `DrawingBlock.block_type`；本地只读 MCP adapter 与只读 HTTP API 已实现，见 QA 编排入口。
`MATCHES_SECTION_CAPTION`（`CrossSection -[:MATCHES_SECTION_CAPTION]-> BlockCaption`）不是默认生成关系；只有在双方存在可比较 `TextObservation`、规范化逻辑键一致、同页候选唯一且无规则冲突时才可作为正式语义关系写入。证据不足、多候选、跨页或规则边界不明确时，只返回或写入 `CANDIDATE_MATCHES_SECTION_CAPTION`，不得把候选判断投影为正式事实。

模块职责、新接口、新依赖、数据变化和架构变化同步记录在 `Module.md`，单页端到端 CLI 验收见 `docs/acceptance/E2E_CLI_ACCEPTANCE.md`，333 页全量数据导入验收见 `docs/acceptance/FULL_DATA_ACCEPTANCE.md`。当前已新增 Python 应用层 `DrawingGraphToolFacade`：它通过只读 port 包装 `QueryService` 能力，通过 `SemanticRecognitionService` 编排按需语义识别，并通过 `RecognitionRunLogPort` 与 `SemanticEvidenceRepositoryPort` 管理语义证据边界。语义证据层已落地：`TextObservation` 与三类 `Interpretation` 数据契约、确定性缓存键与内存缓存、不可变 payload 存储、基于来源事实的图像输入构造、图谱内语义节点幂等写入（`TextObservation`、`BlockInterpretation`、`BasicInfoInterpretation`、`TableInterpretation`，以及 `HAS_OBSERVATION`、`HAS_INTERPRETATION`、`SUPPORTED_BY`）、图谱外 `RecognitionRun` 日志（recognition/interpretation/candidate_review 三类 run）、稳定查询投影和 facade 语义查询。断面专项已落地：`SectionLabelNormalizer` 区分 alphabetic/roman/numeric/alphanumeric/unknown，`SectionAliasRuleStore` 管理图谱外已确认别名规则，`SectionMatchService` 仅在双方存在可比较 `TextObservation`、逻辑键一致、候选唯一且无冲突时给出正式匹配，否则只保留 `CANDIDATE_MATCHES_SECTION_CAPTION`。默认 `write_back=false`，语义识别与断面匹配以 dry-run 返回临时结果；只有显式 `write_back=true` 才写入图谱外 run log、图谱内证据或受控语义边。`RecognitionRun` 图谱外，`TextObservation` 图谱内，二者只通过 `recognition_run_id` 关联。候选关系不是正式事实，`matched_candidate` 也不等于正式图谱关系；候选审核仍必须经过 `CandidateReviewService` 和硬规则。当前已实现只读 HTTP API（`src/drawing_graph/qa_http.py` + `scripts\serve_drawing_graph_qa.py`）与本地只读 STDIO MCP adapter（`src/drawing_graph/qa_mcp_*.py` + `scripts\serve_drawing_graph_mcp.py`），仍未实现 Ava 专有 adapter、全量自动语义扫描、默认真实云模型调用、远程 MCP、OAuth、多 worker 或 HTTP 写回；真实 Neo4j 语义写入的 live 验证仍以独立 disposable 测试库为准。MCP 接入保持 Neo4j 节点、关系、约束、索引保持不变，`RecognitionRun` 图谱外与 `TextObservation`/`Interpretation` 图谱内的边界不变。

当前实现状态：基础 Neo4j 导入闭环、离线派生关系增强闭环和候选关系复核骨架已经完成。基础导入负责来源事实层的稳定入库与追溯；离线增强负责 `Table -[:HAS_CAPTION]-> TableCaption`、`DrawingPage -[:USES_BASIC_INFO]-> DrawingBasicInfo`、`DrawingBlock` 起点的 `HAS_CAPTION`、`HAS_ANNOTATION`、`HAS_SECTION_MARK` 正式派生关系，以及 `CANDIDATE_CAPTION_OF`、`CANDIDATE_HAS_SECTION_MARK` 空间候选关系。候选关系 AI 复核是独立显式流程，不挂到基础导入或默认离线增强；查询侧通过 `get_block_trace()` 和 `get_block_relations()` 返回可复核的业务 ID、图片路径、bbox、候选 ID 和增强状态。

QA 编排层已落地：`DrawingGraphQAService`（`src/drawing_graph/qa_service.py`）与薄 QA CLI（`scripts\drawing_graph_qa.py`）、HTTP adapter（`src/drawing_graph/qa_http.py` + `scripts\serve_drawing_graph_qa.py`）、本地 MCP adapter（`src/drawing_graph/qa_mcp_*.py` + `scripts\serve_drawing_graph_mcp.py`）位于 `DrawingGraphToolFacade` 外侧，默认只读（`write_back=false`），只通过 facade 获取图谱信息，不直接访问 Neo4j driver、Cypher、repository 写回方法或离线规则函数；结构化 `QAAnswer` 按 `source_fact`、`derived_relation`、`semantic_observation`、`semantic_interpretation`、`candidate_relation`、`formal_relation`、`diagnostic`、`unsupported` 分层输出。CLI、HTTP 与 MCP 是同级 adapter：HTTP 依赖方向固定为 `HTTP adapter -> DrawingGraphQAService -> DrawingGraphToolFacade -> ports/services -> repository/Neo4j`，MCP 依赖方向固定为 `MCP adapter -> DrawingGraphQAService -> DrawingGraphToolFacade -> ports/services -> repository/Neo4j`，MCP 不调用 HTTP API 或 QA CLI 子进程；HTTP 默认 loopback、单 worker、只读，MCP 默认本机 STDIO、单进程、只读。

## 2. 整体分层

系统采用模块化 ETL、离线增强、显式候选复核和按需语义证据架构：

```text
基础导入入口
  -> 配置读取
  -> 数据扫描
  -> JSON 校验
  -> 路径 / 页码 / 几何 / ID 规范化
  -> 图谱映射
  -> Neo4j 基础持久化
  -> 导入审计与查询验证

离线派生关系增强入口
  -> 配置读取
  -> 增强范围与批次创建
  -> Neo4j 读取已入库页面快照
  -> table caption、页面基础信息上下文、block 级正式关系和空间候选规则计算
  -> Neo4j 派生关系幂等写入
  -> 补关系审计与查询验证

候选关系 AI 复核入口
  -> 显式读取完整 CANDIDATE_* 候选集合
  -> 注入复核客户端
  -> accepted / rejected / unresolved 结构化结果
  -> 硬性规则校验
  -> 写回复核状态并在 accepted 时提升正式关系

按需语义证据入口
  -> DrawingGraphToolFacade
  -> 来源事实读取与图像输入构造
  -> 缓存检查 / fake 或后续可替换多模态客户端
  -> TextObservation / Interpretation / payload_ref
  -> write_back=false 返回临时证据
  -> write_back=true 写入图谱外 RecognitionRun 日志和图谱内语义证据

断面语义匹配入口
  -> CrossSection 与 BlockCaption 的 TextObservation
  -> 符号体系与逻辑键规范化
  -> 同页候选比较和别名规则检查
  -> CANDIDATE_MATCHES_SECTION_CAPTION 或 MATCHES_SECTION_CAPTION

QA 编排入口
  -> QA adapter（scripts\drawing_graph_qa.py）
  -> HTTP adapter（scripts\serve_drawing_graph_qa.py + src/drawing_graph/qa_http.py）
  -> DrawingGraphQAService
  -> DrawingGraphToolFacade
  -> ports / services / repository / Neo4j

Skill -> MCP client -> STDIO MCP adapter -> DrawingGraphQAService
  -> DrawingGraphToolFacade -> ports / services / repository / Neo4j
```

分层原则：

- `scripts/import_json.py` 只负责基础导入的命令行参数、配置加载和服务编排，不自动触发表格标题或 block 级派生关系增强。
- `scripts/enrich_block_relations.py` 作为兼容入口名称保留，只负责离线派生关系增强的命令行参数、配置加载、增强范围创建和服务调用，不包含匹配规则或 Cypher 细节，也不自动运行 AI 候选复核。
- `scripts/review_candidate_relations.py` 是候选关系 AI 复核的显式入口，只通过注入客户端和服务接口处理 `accepted`、`rejected`、`unresolved` 三态结果。
- QA 层依赖方向固定为 `QA adapter -> DrawingGraphQAService -> DrawingGraphToolFacade -> ports/services -> repository/Neo4j`（CLI、HTTP 与 MCP adapter 同级）；QAService 不创建 Neo4j driver、不写 Cypher、不读取环境变量，adapter 只在最外层管理 driver 生命周期。
- 业务逻辑集中在 `src/drawing_graph/`，按扫描、校验、规范化、映射、持久化、审计、查询和关系增强拆分。
- Schema 初始化和数据导入分离，导入过程不隐式修改数据库结构。
- Neo4j 写入使用稳定业务 ID、固定标签/关系白名单和参数化 Cypher。
- 查询服务本身只提供预定义 Python 内部接口；HTTP 只能经由 QA adapter 的版本化只读路由使用，不开放任意 Cypher。

## 3. 数据流

### 3.1 基础导入流程

1. `scripts/import_json.py all` 从环境变量加载 `ImportConfig`。
2. CLI 创建 `Neo4jRepository`，再创建 `ImportService`。
3. `ImportService.import_all()` 创建 `ImportBatch`。
4. `scanner.scan_drawing_sets()` 按确定顺序扫描 `data` 下的图纸册目录和 JSON 文件。
5. 每个图纸册由 `ImportService.import_drawing_set()` 顺序导入。
6. 每个页面由 `ImportService.import_page()` 完成校验、规范化、映射和持久化。
7. 单页失败不阻断同一图纸册内其他页面；数据库级失败会终止后续写入。
8. 批次结束后调用 `Neo4jRepository.finish_batch()` 写入终态统计。

单页导入流程：

```text
JSON 文件
  -> 读取 JSON
  -> validate_document()
  -> normalize_image_path()
  -> parse_page_number()
  -> normalize_geometry()
  -> make_shape_hash() / make_element_id()
  -> ElementRecord
  -> map_element()
  -> merge_nodes()
  -> merge_relations()
  -> link_page_to_batch()
```

单页导入时，`imagePath` 是唯一允许写回原始 JSON 的字段。写回采用临时文件加原子替换；除路径规范化外，不修改原始标注内容。

### 3.2 离线派生关系增强流程

1. `scripts/enrich_block_relations.py` 从命令行接收 `project`、`drawing-set` 或 `page` 运行范围，并要求传入 `--rule-version`。
2. CLI 从环境变量加载 `ImportConfig`，创建 `RelationRepository` 和 `RelationEnrichmentService`。
3. CLI 生成 `relation_batch_id`，并构造 `EnrichmentScope`。
4. `RelationEnrichmentService` 根据范围调用 `enrich_project()`、`enrich_drawing_set()` 或 `enrich_page()`。
5. `RelationRepository.read_pages()` 从 Neo4j 读取已入库的 `DrawingPage`、`Table`、`TableCaption`、`DrawingBlock`、`BlockCaption`、`DrawingBasicInfo`、`DrawingAnnotation`、`CrossSection` 页面快照。
6. `block_relation_enrichment.enrich_page_relations()` 在单页内组合 table caption、block caption、页面级 basic info、annotation 和 cross section 几何归属规则，生成正式派生关系或带 `relation_spec` 的候选关系。
7. `RelationRepository.write_relations()` 根据固定关系规格选择合法端点标签和关系类型，幂等写回 Neo4j；`table_caption` 候选逐条写入，以隔离 legacy 冲突。
8. `RelationBatchAudit` 记录补关系批次、规则版本、输入范围、统计结果和分类 warning/error。
9. `QueryService.get_block_relations()` 可查询单个 block 的派生关系 ID 和增强状态。

导入完成到补关系完成之间，图谱允许处于 `not_enhanced` 状态：来源事实追溯链路可用，`DrawingPage -[:HAS_ELEMENT]-> TableCaption` 这类页面来源关系可用，但 `Table -[:HAS_CAPTION]-> TableCaption`、`DrawingPage -[:USES_BASIC_INFO]-> DrawingBasicInfo`、单个 `DrawingBlock` 的标题、注释和 section mark 派生关系以及候选边尚未生成。显式运行离线派生关系增强后，图谱进入 `enhanced`、`partial` 或 `candidate` 状态；候选关系 AI 复核是独立显式流程。

## 4. 图谱模型

### 4.1 节点层级

- `Project`：项目根节点，ID 格式为 `project:<project_slug>`。
- `DrawingSet`：图纸册或数据目录，ID 格式为 `set:<project_slug>:<drawing_set_name>`。
- `DrawingPage`：单个 JSON/PNG 页面，ID 格式为 `page:<project_slug>:<drawing_set_name>:<file_stem>`。
- `DrawingBlock`：核心图块，ID 格式为 `block:<project_slug>:<drawing_set_name>:<file_stem>:<shape_hash>`。
- 页面元素：`Table`、`TableCaption`、`BlockCaption`、`CrossSection`、`DrawingBasicInfo`、`DrawingAnnotation`、`PlainText`、`Title`、`IgnoredElement`。
- `ImportBatch`：基础导入批次及统计节点。

本阶段不新增业务节点类型。补关系批次由内存审计结构记录，不替代 `ImportBatch` 节点。

### 4.2 来源事实层

- `Project -[:HAS_SET]-> DrawingSet`
- `DrawingSet -[:HAS_PAGE]-> DrawingPage`
- `DrawingPage -[:HAS_BLOCK]-> DrawingBlock`
- `DrawingPage -[:HAS_TABLE]-> Table`
- `DrawingPage -[:HAS_BASIC_INFO]-> DrawingBasicInfo`
- `DrawingPage -[:HAS_ANNOTATION]-> DrawingAnnotation`
- `DrawingPage -[:HAS_TEXT]-> PlainText`
- `DrawingPage -[:HAS_TEXT]-> Title`
- `DrawingPage -[:HAS_ELEMENT]-> BlockCaption / TableCaption / CrossSection / IgnoredElement`
- `DrawingPage -[:IMPORTED_IN]-> ImportBatch`

基础导入流程只负责来源节点、页面归属关系、稳定 ID、图片路径、bbox 和 `ImportBatch` 审计，不自动创建任何依赖几何匹配或上下文推断的派生关系。

### 4.3 离线派生关系层

离线增强流程写入需要规则计算的派生关系：

- `Table -[:HAS_CAPTION]-> TableCaption`
- `DrawingBlock -[:HAS_CAPTION]-> BlockCaption`
- `DrawingBlock -[:HAS_ANNOTATION]-> DrawingAnnotation`
- `DrawingBlock -[:HAS_SECTION_MARK]-> CrossSection`
- `DrawingPage -[:USES_BASIC_INFO]-> DrawingBasicInfo`
- `BlockCaption -[:CANDIDATE_CAPTION_OF]-> DrawingBlock`
- `DrawingBlock -[:CANDIDATE_HAS_SECTION_MARK]-> CrossSection`

历史 `DrawingBlock -[:HAS_BASIC_INFO]-> DrawingBasicInfo` 只作为旧数据兼容和迁移对象，不再作为目标派生关系。

关系属性包含：

- `relation_batch_id`
- `rule_version`
- `link_rule`
- `distance`，仅标题匹配规则使用
- `match_direction`，例如 `below`、`above`、`same_page_shared`
- `status`、`source`、`candidate_count`、`score`、`conflict_reason`
- `overlap_area`、`overlap_ratio`、`containment_status`，仅 cross section 几何归属规则使用
- `review_run_id`、复核模型版本、提示词版本、复核分数、复核理由和复核时间，候选关系 AI 复核写回时使用

派生关系按起点 ID、终点 ID、关系类型和规则版本幂等写入；页面级来源关系不因增强流程被删除或替换。

## 5. 目录和文件职责

### 5.1 文档目录

| 文件 | 作用 |
|---|---|
| `docs/planning/proposal.md` | 描述业务背景、当前问题、功能目标、修改范围和不包含范围，是需求来源。 |
| `docs/planning/design.md` | 描述技术设计、模块拆分、数据模型、关系模型、接口、安全和异常处理策略，是架构依据。 |
| `docs/planning/tasks.md` | 将设计拆成可独立验证的实施任务，定义每个任务的修改文件、接口和独立测试命令。 |
| `docs/acceptance/E2E_CLI_ACCEPTANCE.md` | 记录单页真实 Neo4j CLI 链路验收。 |
| `docs/acceptance/FULL_DATA_ACCEPTANCE.md` | 记录 333 页全量数据导入、离线增强、Neo4j 计数和 live 集成测试验收。 |
| `docs/acceptance/USER_RUNBOOK.md` | 面向普通使用者的最短运行流程。 |
| `README.md` | 面向使用者的操作说明，覆盖环境变量、Schema 初始化、基础导入、离线派生关系增强、查询验证、测试和常见错误。 |
| `architecture.md` | 本文件，描述整体架构、模块划分、数据流和关键设计边界。 |
| `Module.md` | 面向维护者的模块记录，按新模块职责、新接口、新依赖、数据变化和架构变化同步当前代码实现。 |
| `requirements.txt` | Python 运行依赖，目前用于 Neo4j Python Driver。 |

### 5.2 数据目录

| 路径 | 作用 |
|---|---|
| `data/` | XAnyLabeling JSON 和同名 PNG 的数据根目录。 |
| `data/<drawing_set>/` | 一个图纸册目录，目录名作为 `DrawingSet.name` 和稳定 ID 的组成部分。 |
| `data/<drawing_set>/road_<数字>.json` | 单页标注 JSON，文件名中的数字是当前阶段唯一有效页码来源。 |
| `data/<drawing_set>/road_<数字>.png` | 与 JSON 同目录、同名的可信图片文件。 |

### 5.3 脚本目录

| 文件 | 作用 |
|---|---|
| `scripts/create_schema.cypher` | Neo4j Schema 初始化脚本，创建节点唯一约束和索引；使用 `IF NOT EXISTS`，可重复执行。 |
| `scripts/import_json.py` | 基础导入 CLI，支持 `all`、`drawing-set`、`page` 三种模式；只负责参数解析、配置加载、仓储创建和服务调用。 |
| `scripts/enrich_block_relations.py` | 离线派生关系增强 CLI，支持 `project`、`drawing-set`、`page` 三种范围；只负责参数解析、配置加载、增强范围创建和服务调用，不自动运行 AI 候选复核。 |
| `scripts/review_candidate_relations.py` | 候选关系 AI 复核 CLI，显式复核一个完整候选组，输出 `review_run_id`、复核状态和候选提升结果。 |

### 5.4 Python 包入口

| 文件 | 作用 |
|---|---|
| `src/drawing_graph/__init__.py` | 包入口；导入时不读取数据、不连接 Neo4j、不修改文件，避免副作用。 |

### 5.5 配置模块

| 文件 | 作用 |
|---|---|
| `src/drawing_graph/config.py` | 定义 `ImportConfig` 和 `ConfigError`；从环境变量读取数据根目录、项目标识、Neo4j 连接信息、批量大小和日志级别；`repr` 中屏蔽密码。 |

### 5.6 数据扫描与校验模块

| 文件 | 作用 |
|---|---|
| `src/drawing_graph/scanner.py` | 定义 `scan_drawing_sets(data_root)`、`DrawingSetScan`、`JsonAnnotationFile`；只扫描数据根目录内的图纸册和 JSON，按名称稳定排序，并记录同名 PNG 是否存在。 |
| `src/drawing_graph/validation.py` | 定义 `validate_document(document)`、`ValidationResult`、`ValidationIssue`、`ValidationStatus`；检查页级字段和 shape 字段，将输入划分为 `IMPORTABLE`、`REPAIRABLE` 或 `INVALID`。 |

### 5.7 规范化模块

| 文件 | 作用 |
|---|---|
| `src/drawing_graph/image_paths.py` | 定义 `normalize_image_path(json_path, document, data_root)`；检查同目录同名 PNG，必要时仅修正 JSON 的 `imagePath`，并保留 `original_image_path`。 |
| `src/drawing_graph/page_number.py` | 定义 `parse_page_number(json_path)`；只接受 `road_<数字>.json`，返回整数页码，其他格式抛出分类异常。 |
| `src/drawing_graph/geometry.py` | 定义 `normalize_geometry(points, image_width, image_height)`；将 rectangle、polygon、rotation 等点集统一转为外接 bbox、中心点、宽高和归一化 bbox。 |
| `src/drawing_graph/identifiers.py` | 定义 `make_project_id()`、`make_set_id()`、`make_page_id()`、`make_element_id()`、`make_shape_hash()`；使用 project、drawing set、页面名和 shape 内容哈希生成稳定业务 ID。 |

### 5.8 领域模型、映射与表格标题匹配规则

| 文件 | 作用 |
|---|---|
| `src/drawing_graph/models.py` | 定义不可变领域数据结构，包括 `BBox`、`NormalizedBBox`、`PageRecord`、`ElementRecord`、`GraphNode`、`GraphRelation`、`ImportResult`。 |
| `src/drawing_graph/mapping.py` | 定义 `map_element(element_record)` 和固定标签白名单；将标注标签映射为 Neo4j Label 和页面关系。 |
| `src/drawing_graph/caption_matching.py` | 定义 `match_table_captions(tables, captions)`；为每个 `TableCaption` 选择同页 bbox 距离最近的 `Table`，输出可复用的匹配结果，不负责 Neo4j 写入。 |

关键约束：

- `DrawingPage` 不包含单值 `import_batch_id`。
- `DrawingBlock` 不生成或推断 `block_type`。
- `TableCaption` 使用 bbox 几何距离，该结果只在离线派生关系增强阶段转换为 `Table -[:HAS_CAPTION]-> TableCaption`。
- `BlockCaption` 使用独立的中心点距离和上下方向优先规则。

### 5.9 导入审计与 Neo4j 基础持久化

| 文件 | 作用 |
|---|---|
| `src/drawing_graph/audit.py` | 定义基础导入审计 `ImportAudit`，以及补关系审计 `RelationBatchAudit`、`RelationAuditStore`、`RelationAuditIssue`；统一提供脱敏工具。 |
| `src/drawing_graph/neo4j_repository.py` | 定义 `Neo4jRepository`；提供 `merge_nodes()`、`merge_relations()`、`create_batch()`、`finish_batch()`、`link_page_to_batch()`。 |

持久化约束：

- 节点 Label 来自 `ALLOWED_NODE_LABELS`。
- 关系类型来自固定白名单。
- 属性值使用参数化查询。
- 节点按稳定 `id` 合并。
- 页面和批次历史通过 `DrawingPage -[:IMPORTED_IN]-> ImportBatch` 表达，不在页面上写单值批次字段。

### 5.10 基础导入服务

| 文件 | 作用 |
|---|---|
| `src/drawing_graph/import_service.py` | 定义 `ImportService`、`DrawingSetImportResult`、`AllImportResult`；编排单页、单图纸册、全量数据导入。 |

主要接口：

- `ImportService.import_page(batch_id, json_path)`：完成单页校验、路径修正、页码解析、几何规范化、ID 生成、元素映射和 Neo4j 来源事实写入。
- `ImportService.import_drawing_set(batch_id, drawing_set_path)`：顺序导入一个图纸册内全部 JSON，并隔离单页失败。
- `ImportService.import_all()`：创建批次，扫描全部图纸册，导入全数据，最终写入批次状态。

### 5.11 离线派生关系增强模块

| 文件 | 作用 |
|---|---|
| `src/drawing_graph/block_relation_enrichment.py` | 定义 `EnrichmentScope`、`PageElementSnapshot`、`PageRelationSnapshot`、`RelationCandidate`、`EnrichmentResult`、`EnrichmentIssue`、`EnrichmentStats`，并实现 table caption、block caption、页面级 basic info、annotation、cross section 正式关系和候选关系单页增强规则。 |
| `src/drawing_graph/relation_repository.py` | 定义 `RelationRepository` 和 `RelationRepositoryError`；读取已入库页面快照，按固定关系规格幂等写入正式派生关系、页面级基础信息上下文关系和候选关系，并提供候选复核状态更新及提升接口。 |
| `src/drawing_graph/relation_service.py` | 定义 `RelationEnrichmentService` 和 `RelationServiceError`；按页面、图纸册、项目范围编排读取、规则计算、写入和审计汇总。 |
| `src/drawing_graph/candidate_review.py` | 定义 `CandidateReviewRequest`、`CandidateReviewResult` 和 `CandidateReviewService`；通过注入客户端执行候选关系 AI 复核、硬性规则校验、状态写回和 accepted 候选提升。 |

主要接口：

- `enrich_table_captions(scope, page)`：同页 `TableCaption` 到 `Table` 的表格标题匹配，生成 `table_caption` 规格的 `HAS_CAPTION` 正式关系。
- `enrich_block_captions(scope, page)`：同页 `BlockCaption` 到 `DrawingBlock` 的标题匹配；唯一明确时生成 `HAS_CAPTION`，歧义时生成 `BlockCaption -[:CANDIDATE_CAPTION_OF]-> DrawingBlock`。
- `enrich_current_page_basic_infos(scope, page)`：当前页存在基础信息时生成 `DrawingPage -[:USES_BASIC_INFO]-> DrawingBasicInfo`。
- `enrich_previous_page_basic_infos(scope, page, previous_page, previous_page_context_available=True)`：当前页缺失基础信息时返回 `basic_info_partial`、`basic_info_not_evaluated` 或 `basic_info_ambiguous`，不生成 block 级基础信息正式关系。
- `enrich_page_annotations(scope, page)`：同页注释共享。
- `enrich_cross_sections(scope, page)`：同页 `CrossSection` 到 `DrawingBlock` 的几何归属规则，唯一明确时生成 `HAS_SECTION_MARK`，歧义时生成 `DrawingBlock -[:CANDIDATE_HAS_SECTION_MARK]-> CrossSection`。
- `enrich_page_relations(scope, page, previous_page=None, previous_page_context_available=True)`：汇总单页表格标题、页面级基础信息上下文、block 级正式关系和空间候选关系。
- `RelationRepository.read_pages(scope, limit=100)`：按项目、图纸册或页面范围读取页面快照。
- `RelationRepository.write_relations(relations)`：按固定关系规格和白名单关系类型幂等写入派生关系。
- `RelationRepository.update_candidate_review(...)`：按固定候选规格写回复核状态、`review_run_id`、模型版本、提示词版本、分数、理由和时间。
- `RelationRepository.promote_candidate_relation(...)`：仅将已 accepted 且通过硬性规则的候选提升为正式 `HAS_CAPTION` 或 `HAS_SECTION_MARK`，不删除候选边。
- `RelationEnrichmentService.enrich_page(scope)`：处理单页范围。
- `RelationEnrichmentService.enrich_drawing_set(scope)`：处理图纸册范围并隔离单页失败。
- `RelationEnrichmentService.enrich_project(scope)`：处理项目范围并隔离图纸册/页面失败。
- `RelationEnrichmentService.get_batch_summary(relation_batch_id)`：读取补关系批次摘要。

### 5.12 查询服务模块

| 文件 | 作用 |
|---|---|
| `src/drawing_graph/query_service.py` | 定义 `QueryService` 和 `QueryError`；提供只读、预定义、参数化查询接口。 |

主要接口：

- `get_project_sets(project_id, limit)`：查询项目下的图纸册。
- `get_set_pages(drawing_set_id, limit)`：查询图纸册下的页面，按页码排序。
- `get_page_blocks(page_id, limit)`：查询页面内全部 `DrawingBlock`。
- `get_block_trace(block_id)`：查询单个图块的项目、图纸册、页面、图片路径和 bbox 追溯链。
- `get_block_relations(block_id)`：查询单个图块的 `caption_ids`、`basic_info_ids`、`basic_info_status`、`basic_info_source`、`annotation_ids`、`section_mark_ids`、`candidate_caption_ids`、`candidate_section_mark_ids` 和 `relation_status`。
- `get_batch_status(import_batch_id)`：查询导入批次状态和统计。

查询结果不暴露 Neo4j 内部节点 ID，也不返回依赖 OCR 或 Agent 推理的 `caption_text`、`reason`。

### 5.13 Codex Skill 操作层

| 路径 | 作用 |
|---|---|
| `.codex/skills/drawing-graph-operator/` | 项目级 Codex Skill，位于 facade 外侧的操作层：`SKILL.md` 定义核心流程与禁止事项，`agents/openai.yaml` 提供 UI 元数据，`references/` 记录项目边界、facade 工作流、QA 工具路由、MCP 边界、验证规则和输出契约。 |

该 Skill 只指导 Codex 如何使用本项目能力，不包含 `data/` 真实数据、Neo4j 数据或密钥，不直接创建 Neo4j driver、不写 Cypher、不调用 repository 写回方法，也不是 Agent Skill、MCP Tool adapter、HTTP/REST API 或文件 watcher。

## 6. 测试结构

`tests/` 使用标准库 `unittest`，按模块一一对应：

| 测试文件 | 覆盖模块 |
|---|---|
| `tests/test_package_import.py` | 包导入无副作用。 |
| `tests/test_schema.py` | Schema 约束和索引静态检查。 |
| `tests/test_config.py` | 环境配置读取和密码脱敏。 |
| `tests/test_scanner.py` | 数据根目录扫描和越界拒绝。 |
| `tests/test_validation.py` | JSON 结构校验。 |
| `tests/test_page_number.py` | `road_<数字>.json` 页码解析。 |
| `tests/test_image_paths.py` | 图片路径规范化和原子写回。 |
| `tests/test_geometry.py` | bbox 和归一化 bbox 计算。 |
| `tests/test_identifiers.py` | 稳定业务 ID 和 shape hash。 |
| `tests/test_models.py` | 领域模型字段和不可变约束。 |
| `tests/test_mapping.py` | 标注标签到节点和关系的映射。 |
| `tests/test_caption_matching.py` | 表格标题最近表格匹配纯规则。 |
| `tests/test_audit.py` | 导入审计统计、错误分类和脱敏。 |
| `tests/test_relation_audit.py` | 补关系审计批次、统计、分类和脱敏。 |
| `tests/test_neo4j_nodes.py` | 节点参数化、白名单和幂等写入。 |
| `tests/test_neo4j_relations.py` | 基础关系参数化、白名单和幂等写入。 |
| `tests/test_neo4j_batches.py` | `ImportBatch` 状态和 `IMPORTED_IN` 历史关系。 |
| `tests/test_import_page.py` | 单页面导入闭环。 |
| `tests/test_import_drawing_set.py` | 单图纸册导入和失败隔离。 |
| `tests/test_import_all.py` | 全量导入、批次终态和数据库级失败处理。 |
| `tests/test_import_cli.py` | 基础导入 CLI 三种模式、参数错误和退出码。 |
| `tests/test_block_relation_models.py` | 补关系数据契约。 |
| `tests/test_block_caption_enrichment.py` | 图块标题匹配规则。 |
| `tests/test_basic_info_current_page_enrichment.py` | 当前页基础信息关联规则。 |
| `tests/test_basic_info_previous_page_enrichment.py` | 上一页基础信息继承规则。 |
| `tests/test_annotation_enrichment.py` | 同页注释共享规则。 |
| `tests/test_table_caption_enrichment.py` | 表格标题派生关系候选生成。 |
| `tests/test_enrich_page_relations.py` | 单页表格标题和 block 级规则汇总、统计和去重。 |
| `tests/test_relation_repository_reads.py` | 补关系仓储读取和范围限制。 |
| `tests/test_relation_repository_writes.py` | 补关系仓储写入、白名单、参数化和幂等。 |
| `tests/test_relation_service_page.py` | 单页补关系服务。 |
| `tests/test_relation_service_set.py` | 图纸册补关系服务。 |
| `tests/test_relation_service_project.py` | 项目补关系服务。 |
| `tests/test_relation_cli.py` | 离线派生关系增强 CLI。 |
| `tests/test_query_*.py` | 查询服务的参数化查询、返回字段和异常分类。 |
| `tests/test_readme.py` | README 基础使用说明完整性和凭据检查。 |
| `tests/test_relation_readme.py` | README 离线补关系说明完整性和边界检查。 |
| `tests/test_qa_mcp_*.py` | MCP 模型、工具、runtime、server、STDIO 与静态边界测试。 |
| `tests/test_qa_mcp_skill_behavior.py` | Skill 固定提示集的路由、缺 ID 与透明降级文档合同。 |
| `tests/integration/test_neo4j_import.py` | 真实 Neo4j 中的 Schema、导入、幂等和查询闭环。 |
| `tests/integration/test_neo4j_relation_enrichment.py` | 真实 Neo4j 中的离线补关系、查询和幂等验证。 |
| `tests/integration/test_neo4j_semantic_evidence.py` | 真实 Neo4j 中的语义证据节点、语义关系、断面候选/正式关系、幂等和查询投影验证。 |

真实 Neo4j 集成测试入口已经覆盖导入、补关系和语义证据写入闭环；运行时需要设置独立测试库的 `NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD`。未设置这些变量时，集成测试会按测试设计跳过，不能作为真实数据库已验证的证据。

## 7. 当前阶段边界

明确不包含：

- 不做 OCR。
- 不做全量自动语义扫描，不默认调用真实外部多模态模型供应商。
- 不实现 Agent Skill。
- 项目级 Codex Skill `.codex/skills/drawing-graph-operator/` 只是 facade 外侧的操作层，不属于 Agent Skill、MCP Tool adapter、HTTP/REST API 或文件 watcher。
- 不提供 HTTP 写回、任意 Cypher HTTP 接口或远程 MCP；HTTP 只读 QA 与本地只读 MCP Tool adapter 已实现（STDIO）。
- 不生成或推断 `block_type`。
- 只有在双方存在可比较 `TextObservation`、规范化逻辑键一致、同页候选唯一且无规则冲突时才建立 `CrossSection -[:MATCHES_SECTION_CAPTION]-> BlockCaption`；多候选、证据冲突或规则边界不明确时只保留 `CANDIDATE_MATCHES_SECTION_CAPTION`，不跨页面自动匹配。
- 不建立 `NEAR` 空间关系网络。
- 不把 `abandon` 作为核心问答可检索业务节点。
- 不让基础导入流程自动触发离线派生关系增强。
- 不让离线派生关系增强默认触发候选关系 AI 复核；复核必须通过显式命令或服务调用执行。
- 不把 `CANDIDATE_*` 候选关系当作正式事实；只有 accepted 且通过硬性规则校验的候选才能提升为正式关系。
- QA 编排默认只读、`write_back=false`；候选关系不是正式事实，`matched_candidate` 不写成正式图谱关系；QAService 不直接写 Cypher。HTTP API 默认 loopback、单 worker，`/health/live` 与 `/health/ready` 不等于 live Neo4j 验证；本地只读 MCP adapter 已实现，但远程 MCP、Streamable HTTP MCP、OAuth、RBAC、TLS、多 worker、Ava 专有 adapter、OCR、真实模型供应商、数据库 schema 变更和 HTTP 写回仍未实现。

这些边界使当前阶段聚焦在可重复导入、稳定 ID、图谱层级、位置证据、离线可审计关系增强和查询追溯闭环上。

## 8. 关键设计约束

- 页码只来自 `road_<数字>.json` 文件名。
- 同名 PNG 存在时才导入页面；不存在时跳过页面并记录异常。
- JSON 原始内容只允许修改 `imagePath`，并采用原子替换。
- shape 几何统一转为外接 bbox，同时保留原始 points 和 shape type。
- 稳定 ID 不依赖 shapes 数组顺序，依赖规范化 label、shape_type 和 points 的内容哈希。
- Neo4j Label 和关系类型必须来自白名单。
- 所有 Cypher 属性值必须参数化。
- 批次历史通过 `IMPORTED_IN` 关系表达。
- 补关系批次通过 `relation_batch_id`、`rule_version`、输入范围和分类 issue 审计。
- `DrawingBasicInfo` 上下文通过页面级 `USES_BASIC_INFO` 表达；上下文不足时保留 `not_evaluated`、`partial` 或 `ambiguous`，不靠连续页码强行写成 block 级事实。
- `BlockCaption` 只在同一页面内匹配，且不复用 `TableCaption` 的业务匹配规则；多候选或冲突保留 `CANDIDATE_CAPTION_OF`。
- `CrossSection` 几何归属在多个包含候选或重叠证据接近时保留 `CANDIDATE_HAS_SECTION_MARK`。
- 候选关系 AI 复核必须保存 `review_run_id`，并使用 `accepted`、`rejected`、`unresolved` 三态输出。
- 查询服务只返回稳定业务 ID 和定位证据，不暴露内部数据库 ID。
