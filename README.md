# 图块图谱构建使用说明

本项目将 XAnyLabeling 标注 JSON 和同目录同名 PNG 导入 Neo4j，形成 `Project -> DrawingSet -> DrawingPage -> DrawingBlock` 及页面元素的可追溯图谱。当前阶段只做来源事实导入、离线派生关系增强、显式候选关系 AI 复核骨架、批次审计和只读查询，不做 OCR、Agent Skill、MCP Tool adapter 或完整图纸语义推理；已提供默认本机监听、默认只读的 HTTP API（见第 9 节）。

当前闭环状态：基础导入、离线派生关系增强、候选关系复核服务骨架和查询验证已经形成流程。推荐运行顺序是初始化 Schema，执行 `scripts\import_json.py all` 写入来源事实，再显式执行 `scripts\enrich_block_relations.py project --rule-version <version>` 写入表格标题、页面级基础信息上下文、block 级正式派生关系和空间候选边；如需复核候选关系，再显式执行 `scripts\review_candidate_relations.py candidate-group ...`。最后用 `QueryService.get_block_trace()` 和 `QueryService.get_block_relations()` 验证单个图块的位置证据、候选 ID 与派生关系状态。

模块职责、新接口、新依赖、数据变化和架构变化见 `Module.md`；该文档按当前代码实现记录维护边界，不把未实现的 OCR、Agent Skill、MCP Tool adapter 或全量自动语义扫描当作已完成能力；HTTP API 当前实现见第 9 节。单页端到端 CLI 验收证据见 `docs/acceptance/E2E_CLI_ACCEPTANCE.md`，333 页全量数据导入验收证据见 `docs/acceptance/FULL_DATA_ACCEPTANCE.md`，面向普通用户的最短运行流程见 `docs/acceptance/USER_RUNBOOK.md`。

当前还新增了 Python 应用层 `DrawingGraphToolFacade`，以及 `scripts\drawing_graph_tool.py` 这个薄 CLI adapter。CLI adapter 只负责从环境变量读取 Neo4j 连接配置、创建 driver、调用 facade 并输出 JSON；它不保存 Neo4j 密码，不暴露 Cypher，不提供 HTTP API，也不是 Agent Skill 或 MCP Tool adapter。facade 默认 `write_back=false`：查询为只读，语义识别为 dry-run，只返回临时 `recognition_run_id`、observation 和 interpretation；只有显式 `write_back=true` 才写入图谱外 run log 和图谱内语义证据。`RecognitionRun` 图谱外，`TextObservation` 图谱内，候选关系不是正式事实，`matched_candidate` 也不能当作正式图谱关系。

Codex 会话可通过项目级 Skill `.codex\skills\drawing-graph-operator\` 稳定遵守本项目的操作规则：行动前先读取当前项目文档和受影响源码，只经 `DrawingGraphToolFacade`、`create_neo4j_tool_facade()` 或 `scripts\drawing_graph_tool.py` 使用图谱能力，默认 `write_back=false`，并区分来源事实、派生关系、语义证据、候选关系与正式关系。该 Skill 是 facade 外侧的操作层：不封装 `data/` 真实数据，不保存 Neo4j 密码、供应商 API key 或 `.env` 密钥，不自动监听文件（不是文件 watcher），不替代 HTTP API 或 MCP Tool adapter，也不修改 Python 业务源码或运行时图谱能力。

当前语义证据层能力（按需识别，非全量自动扫描）：

- 数据契约：`TextObservation`、`BlockInterpretation`、`BasicInfoInterpretation`、`TableInterpretation`、语义状态、缓存键和 `payload_ref`。
- 图谱外运行日志：`RecognitionRun` 支持 `recognition`、`interpretation`、`candidate_review` 三类 run，记录模型 profile、prompt version、输入范围、状态、错误和可选成本摘要；缓存命中与普通查询不创建新 run。
- 图谱内证据：`TextObservation` 和三类 `Interpretation` 以稳定 ID 幂等写入，`HAS_OBSERVATION`、`HAS_INTERPRETATION`、`SUPPORTED_BY` 使用受控白名单；`RecognitionRun` 不作为 Neo4j 节点。
- 缓存与 payload：相同图片、bbox、任务类型和版本生成确定性 cache key；完整解析 JSON 存入不可变 payload 存储，按 `payload_ref` 只读查询。
- 断面匹配：`SectionLabelNormalizer` 区分 `alphabetic`、`roman`、`numeric`、`alphanumeric`、`unknown`；默认不合并 `I-I`、`Ⅰ-Ⅰ` 和 `1-1`；跨符号体系匹配必须命中已确认的图谱外 `SectionAliasRule`。只有在双方存在可比较 `TextObservation`、逻辑键一致、候选唯一且无规则冲突时才建立 `CrossSection -[:MATCHES_SECTION_CAPTION]-> BlockCaption`，否则只保留 `CANDIDATE_MATCHES_SECTION_CAPTION`。
- 统一输出：facade 通过 `SemanticQueryProjection` 返回 observation、interpretation、payload、候选和正式关系的稳定 DTO，明确区分 `source_fact`、`derived_relation`、`semantic_observation`、`semantic_interpretation`、`candidate_relation`、`formal_relation`；不暴露 Neo4j driver、session、transaction、Cypher 或内部节点 ID。
- 写回安全：`write_back=false` 不持久化；`write_back=true` 才写入 run log、图谱内证据或受控语义边。模型输出不覆盖来源事实节点，`BlockInterpretation.interpreted_type` 不会写入 `DrawingBlock.block_type`。

## 1. 环境要求

- Python 3.11 或更高版本。
- Neo4j 5.x，建议使用单独测试库或专用数据库。
- 依赖安装：

```powershell
python -m pip install -r requirements.txt
```

如果只运行不连接 Neo4j 的单元测试，通常不需要启动数据库；真实导入和集成测试需要 Neo4j 可访问。

## 2. 环境变量

导入配置全部来自环境变量，数据库密码不会写入代码、文档或日志。

```powershell
$env:DRAWING_GRAPH_DATA_ROOT = "C:\Users\40119\Desktop\图块图谱构建\data"
$env:DRAWING_GRAPH_PROJECT_SLUG = "road-project"
$env:NEO4J_URI = "bolt://127.0.0.1:7687"
$env:NEO4J_USER = "neo4j"
$env:NEO4J_PASSWORD = "<your-password>"
$env:DRAWING_GRAPH_BATCH_SIZE = "500"
$env:DRAWING_GRAPH_LOG_LEVEL = "INFO"
```

必需变量：

- `DRAWING_GRAPH_DATA_ROOT`：数据根目录，下面每个子目录视为一个 `DrawingSet`。
- `DRAWING_GRAPH_PROJECT_SLUG`：项目稳定标识，用于生成 `project:<slug>`、`set:<slug>:...`、`page:<slug>:...` 等业务 ID。
- `NEO4J_URI`、`NEO4J_USER`、`NEO4J_PASSWORD`：Neo4j 连接信息。

可选变量：

- `DRAWING_GRAPH_BATCH_SIZE`：批量写入大小，必须是正整数，默认 `500`。
- `DRAWING_GRAPH_LOG_LEVEL`：日志级别，默认 `INFO`。

仓库提供 `.env.example` 作为本机和 CI 配置模板，只包含占位符，不包含真实密码。真实 `.env`、`.env.local` 等本机密钥文件已加入 `.gitignore`，不要提交真实 Neo4j 密码、供应商 API key、token 或 secret。

Neo4j Browser 常见地址是 `http://localhost:7474/browser/`，它只用于浏览器管理界面；Python driver、导入脚本和集成测试需要 Bolt 地址，常见为 `bolt://127.0.0.1:7687`。如果 Browser 中 `CALL dbms.listConnections()` 显示 Bolt connector 为 `127.0.0.1:7687`，则测试和导入配置也应使用这个 Bolt 地址，而不是 `localhost:7474`。

## 3. 数据目录规则

数据目录应采用以下结构：

```text
data/
  lslq_yhd_2_1/
    road_24.json
    road_24.png
  lslq_yhd_2_2/
    road_24.json
    road_24.png
```

路径规则：

- 扫描只处理 `DRAWING_GRAPH_DATA_ROOT` 内部的 JSON。
- 每个 JSON 必须存在同目录同名 PNG，例如 `road_24.json` 对应 `road_24.png`。
- 如果 JSON 内部 `imagePath` 不是同目录同名 PNG，但 PNG 存在，导入前只修正 `imagePath` 字段，并保留原始值作为 `original_image_path`。
- 如果同名 PNG 不存在，该页面不导入，原 JSON 不修改，并在审计中记录路径异常。

页码规则：

- 只接受 `road_<数字>.json`。
- `road_24.json` 的 `page_number` 固定为 `24`。
- `road_2_rev_1.json`、`road_x.json` 或其他格式不会进入正式图谱。

## 4. 初始化 Schema

先初始化 Neo4j Schema，再执行导入。可以在 Neo4j Browser 或 `cypher-shell` 中运行：

```powershell
Get-Content -Encoding UTF8 scripts\create_schema.cypher | cypher-shell -a $env:NEO4J_URI -u $env:NEO4J_USER -p $env:NEO4J_PASSWORD
```

Schema 文件使用 `IF NOT EXISTS`，可重复执行。它会创建 `Project`、`DrawingSet`、`DrawingPage`、`DrawingBlock`、`Title`、`ImportBatch` 等节点约束和必要索引，不使用旧的 `Block` 节点，也不创建 `block_type` 索引。

## 5. 导入数据

命令行入口是 `scripts/import_json.py`。运行前确认上面的环境变量已经设置。

导入全部数据：

```powershell
python scripts\import_json.py all
```

导入单个图纸册：

```powershell
python scripts\import_json.py drawing-set batch:manual-001 data\lslq_yhd_2_1
```

导入单个页面：

```powershell
python scripts\import_json.py page batch:manual-001 data\lslq_yhd_2_1\road_24.json
```

返回结果会包含 `status`、`batch_id`、`page_id` 或 `drawing_set_id`、成功数、跳过数、失败数和错误摘要。`success` 或 `skipped` 返回退出码 `0`，配置错误或批次级失败返回非零退出码。

基础导入只写来源节点、页面归属关系、稳定 ID、图片路径、bbox 和 ImportBatch 审计。`Table` 和 `TableCaption` 节点仍会被导入，`DrawingPage -[:HAS_TABLE]-> Table` 与 `DrawingPage -[:HAS_ELEMENT]-> TableCaption` 仍属于来源事实层；但基础导入不会自动写入 `Table -[:HAS_CAPTION]-> TableCaption`，因为该关系依赖 bbox 距离匹配，需要显式执行离线派生关系增强。基础导入不会自动运行候选关系 AI 复核。

## 6. 离线派生关系增强

基础导入只建立来源事实层和追溯链路，基础导入不会自动触发离线派生关系增强。导入完成后，图谱处于合法中间状态：页面级来源事实可追溯，`Table`、`TableCaption`、`DrawingBlock` 等节点和页面归属关系已经存在，但 `Table -[:HAS_CAPTION]-> TableCaption`、`DrawingPage -[:USES_BASIC_INFO]-> DrawingBasicInfo`、block 级标题、注释、断面标记正式关系和 `CANDIDATE_*` 候选边可能尚未增强。只有显式运行 `scripts\enrich_block_relations.py` 后，这些离线派生关系才会写入。离线派生关系增强不会自动触发候选关系 AI 复核。

按项目范围增强派生关系：

```powershell
python scripts\enrich_block_relations.py project --rule-version block-rel-v1
```

按图纸册范围增强派生关系：

```powershell
python scripts\enrich_block_relations.py drawing-set set:road-project:lslq_yhd_2_1 --rule-version block-rel-v1
```

按单页范围增强派生关系：

```powershell
python scripts\enrich_block_relations.py page page:road-project:lslq_yhd_2_1:road_24 --rule-version block-rel-v1
```

`--rule-version` 是必需参数，会写入每条派生关系的 `rule_version` 属性，并进入增强批次审计。每次运行会生成一个 `relation_batch_id`，用于查看该次增强的输入范围、统计结果和 warning/error 摘要。同一规则版本重复运行应保持幂等；不同规则版本可以回放并保留可审计结果。

离线派生关系增强会复用现有节点类型，不新增业务节点类型：

- `Table -[:HAS_CAPTION]-> TableCaption`：只在同一 `DrawingPage` 内匹配，复用 `table_caption_bbox_distance_v1` 的 bbox 几何距离规则，为每个 `TableCaption` 选择最近的 `Table`。关系由 `table_caption` 固定规格写入；如果发现同一标题已有无版本 legacy 关系，只有起点为同一个 `Table` 时才接管并补充审计属性，不会覆盖或重绑到不同表格。
- `DrawingBlock -[:HAS_CAPTION]-> BlockCaption`：只在同一 `DrawingPage` 内匹配，使用中心点距离和上下方向规则；唯一明确时写正式关系，多个距离接近或多个标题争同一图块时不强行确定，而是写入 `BlockCaption -[:CANDIDATE_CAPTION_OF]-> DrawingBlock`。
- `DrawingPage -[:USES_BASIC_INFO]-> DrawingBasicInfo`：当前页有基础信息且页面存在图块时，生成页面级基础信息上下文关系。历史 `DrawingBlock -[:HAS_BASIC_INFO]-> DrawingBasicInfo` 只作为旧数据兼容对象，不再作为目标派生关系。
- `DrawingBlock -[:HAS_ANNOTATION]-> DrawingAnnotation`：同一页面内所有图块共享该页所有注释，不做中心点距离判断。
- `DrawingBlock -[:HAS_SECTION_MARK]-> CrossSection`：只在同一 `DrawingPage` 内根据 bbox 几何关系匹配。唯一包含或显著领先重叠候选写正式关系；多个包含候选或重叠证据接近时写入 `DrawingBlock -[:CANDIDATE_HAS_SECTION_MARK]-> CrossSection`。关系写入会携带 `relation_batch_id`、`rule_version`、`link_rule`、`overlap_area`、`overlap_ratio` 和 `containment_status` 等证据属性。

增强摘要会包含通用统计、表格增强统计、页面级基础信息和候选统计。表格相关字段包括：`table_count`、`table_caption_count`、`table_caption_relation_count`；基础信息和候选相关字段包括：`uses_basic_info_count`、`candidate_count`、`ambiguous_count`、`not_evaluated_count`、`reviewing_count`、`accepted_count`、`rejected_count`、`unresolved_count`；总 `relation_count` 统计本次生成或处理的全部派生关系和候选关系。

候选关系 AI 复核必须显式触发，不由离线增强自动调用。复核命令示例：

```powershell
python scripts\review_candidate_relations.py candidate-group --relation-spec candidate_caption_of --group-key caption:1 --source-element-id caption:1 --page-id page:road-project:lslq_yhd_2_1:road_24 --rule-version block-rel-v1 --review-run-id review-run:manual-001 --candidate candidate:caption:1:block:1,caption:1,block:1 --evidence-ref crop:caption:1
```

复核结果只允许 `accepted`、`rejected`、`unresolved`。`accepted` 仍需通过同页范围、候选集合完整性和关系方向等硬性规则校验，才能提升为正式关系；`rejected` 和 `unresolved` 只更新候选边状态与原因。候选边和由复核提升的正式边会保存 `review_run_id`、模型版本、提示词版本、复核分数、理由和复核时间。

常见离线派生关系增强 warning/error 分类：

- `table_caption_missing_table`：页面有 `TableCaption` 但没有可匹配的同页 `Table`。
- `table_caption_invalid_input`：表格标题快照 ID、bbox 或输入集合不合法，当前页面表格规则失败。
- `table_caption_legacy_conflict`：某个 `TableCaption` 已有无版本 legacy `HAS_CAPTION`，且起点不是本次匹配到的 `Table`；不覆盖旧关系，不写入该候选，批次进入 `partial`。
- `table_caption_write_failed`：`Table -[:HAS_CAPTION]-> TableCaption` 写入 Neo4j 失败。
- `caption_candidate_not_found`：某个 `BlockCaption` 没有可匹配的同页图块。
- `caption_candidate_ambiguous`：标题空间证据存在多个合理候选，写入 `CANDIDATE_CAPTION_OF` 而不是正式 `HAS_CAPTION`。
- `basic_info_not_evaluated`：当前页缺少基础信息且上下文不足，不能写成正式基础信息事实。
- `basic_info_partial`：发现可能的基础信息上下文，但语义证据不足以确认。
- `basic_info_ambiguous`：基础信息锚点或候选组证据冲突，不能确认唯一上下文。
- `annotation_not_found`：页面没有可共享的注释。
- `cross_section_unmatched`：同页没有可接受的 `DrawingBlock` 候选。
- `section_candidate_ambiguous`：多个包含候选或重叠证据接近，写入 `CANDIDATE_HAS_SECTION_MARK` 而不是正式 `HAS_SECTION_MARK`。
- `section_candidate_low_evidence`：最大重叠比例低于规则阈值，不写入候选或正式关系。
- `section_mark_write_failed`：`HAS_SECTION_MARK` 写入 Neo4j 失败。
- `candidate_review_unavailable`：复核客户端不可用，候选保持 `unresolved`。
- `candidate_review_invalid_output`：复核客户端输出不符合 `accepted/rejected/unresolved` 结构化契约。
- `candidate_promotion_rule_failed`：AI accepted 结果未通过同页范围、方向或候选集合完整性硬性校验。
- `candidate_review_write_failed`：复核状态或正式提升写回失败。
- `relation_write_failed`：block 级派生关系写入 Neo4j 失败。

边界约束：离线派生关系增强不修改 `scripts\import_json.py` 的导入闭环，不删除或替换 `DrawingPage` 起点的页面级来源关系，不做 OCR、不跨页面自动匹配断面、不在证据不足或候选不唯一时建立 `CrossSection -[:MATCHES_SECTION_CAPTION]-> BlockCaption`，不开发 Agent Skill、不新增 HTTP 写回或 `NEAR` 空间关系，也不设置或推断 `DrawingBlock.block_type`；离线派生关系增强不会自动触发多模态识别或候选关系 AI 复核。

## 7. 查询验证

查询服务本身仍是 Python 内部接口，不直接开放 HTTP；对外 HTTP 入口见第 9 节。可以用下面的方式做最小验证：

```powershell
@'
import os
from neo4j import GraphDatabase
from drawing_graph.query_service import QueryService

driver = GraphDatabase.driver(
    os.environ["NEO4J_URI"],
    auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
)

service = QueryService(driver)
project_id = "project:" + os.environ["DRAWING_GRAPH_PROJECT_SLUG"]

print(service.get_project_sets(project_id, limit=10))
print(service.get_set_pages("set:road-project:lslq_yhd_2_1", limit=5))
print(service.get_page_blocks("page:road-project:lslq_yhd_2_1:road_24", limit=5))
print(service.get_block_trace("block:road-project:lslq_yhd_2_1:road_24:<shape_hash>"))
print(service.get_block_relations("block:road-project:lslq_yhd_2_1:road_24:<shape_hash>"))
print(service.get_batch_status("batch:manual-001"))
driver.close()
'@ | $env:PYTHONPATH="src"; python -
```

也可以使用薄 CLI adapter 走同一个 facade 边界，输出为 JSON，仍然需要 `NEO4J_URI`、`NEO4J_USER` 和 `NEO4J_PASSWORD` 已在当前进程环境中配置：

```powershell
python scripts\drawing_graph_tool.py list-drawing-sets --project-id project:road-project --limit 10
python scripts\drawing_graph_tool.py list-pages --drawing-set-id set:road-project:lslq_yhd_2_1 --limit 5
python scripts\drawing_graph_tool.py block-trace --block-id block:road-project:lslq_yhd_2_1:road_24:<shape_hash>
python scripts\drawing_graph_tool.py list-text-observations --page-id page:road-project:lslq_yhd_2_1:road_24 --status confirmed
python scripts\drawing_graph_tool.py list-interpretations --page-id page:road-project:lslq_yhd_2_1:road_24 --status partial
python scripts\drawing_graph_tool.py list-candidate-relations --block-id block:road-project:lslq_yhd_2_1:road_24:<shape_hash> --relation-type candidate_section_mark --status candidate
python scripts\drawing_graph_tool.py list-section-matches --cross-section-id element:road-project:lslq_yhd_2_1:road_24:<shape_hash> --status candidate --status confirmed
```

Tool facade 的单元测试不需要真实 Neo4j 或真实云模型。真实 Neo4j 集成测试必须单独配置 disposable 测试库环境变量 `NEO4J_TEST_URI`、`NEO4J_TEST_USER` 和 `NEO4J_TEST_PASSWORD`；如果这些测试被跳过，跳过不等于通过，不能声称 live Neo4j 已验证。

查询返回稳定业务 ID，不返回 Neo4j 内部 ID。`bbox` 和 `normalized_bbox` 都使用 `{x_min, y_min, x_max, y_max}` 对象；`normalized_bbox` 的值在 `0` 到 `1` 之间。

`get_block_relations(block_id)` 返回 `caption_ids`、`basic_info_ids`、`basic_info_status`、`basic_info_source`、`annotation_ids`、`section_mark_ids`、`candidate_caption_ids`、`candidate_section_mark_ids` 和 `relation_status`。`basic_info_ids` 通过 `DrawingBlock <-[:HAS_BLOCK]- DrawingPage -[:HAS_BASIC_INFO|USES_BASIC_INFO]-> DrawingBasicInfo` 页面路径读取；历史 block 级基础信息关系只作为迁移兼容对象，不优先返回。`section_mark_ids` 是该图块已经通过 `HAS_SECTION_MARK` 关联的 `CrossSection` 稳定业务 ID 列表。`relation_status` 为 `not_enhanced` 表示该 block 尚无派生关系；`enhanced` 表示 caption、basic info、annotation 和 section mark 四组正式派生关系都存在；`partial` 表示只存在部分正式派生关系；`candidate` 表示存在尚未提升为正式事实的候选关系。该查询只返回 ID 和状态，不返回 OCR 文本 `caption_text` 或 `section_text`，也不返回 Agent 推理字段 `reason`。

## 8. QA 问答 CLI（第一阶段）

`scripts\drawing_graph_qa.py` 是 facade 外侧的薄 QA CLI：它读取环境变量创建 driver 和 facade，再调用 `DrawingGraphQAService` 回答结构化问题。QA 层默认只读，`write_back=false`；候选关系不是正式事实，`matched_candidate` 不能当作正式图谱关系；QAService 不直接写 Cypher，不直接访问 Neo4j driver、repository 或离线规则函数。

最短使用示例：

```powershell
python scripts\drawing_graph_qa.py ask-page --page-id page:road-project:lslq_yhd_2_1:road_24 --format json
python scripts\drawing_graph_qa.py ask-block --block-id block:road-project:lslq_yhd_2_1:road_24:<shape_hash> --format zh-brief
python scripts\drawing_graph_qa.py ask-candidates --page-id page:road-project:lslq_yhd_2_1:road_24 --format json
```

输出支持 JSON（默认）和简短中文（`--format zh-brief`）。QA CLI 与底层 `scripts\drawing_graph_tool.py` 一样只做参数解析、facade 创建和输出渲染；业务编排在 `src/drawing_graph/qa_service.py`。HTTP API 见下一节；MCP Tool adapter、Ava 专有 adapter、OCR、真实模型供应商和数据库 schema 变更仍未实现。

## 9. HTTP API（第二阶段）

`src/drawing_graph/qa_http.py` 与 `scripts\serve_drawing_graph_qa.py` 提供版本化、默认本机监听、默认只读的 HTTP adapter。调用链固定为 `HTTP adapter -> DrawingGraphQAService -> DrawingGraphToolFacade -> ports/services -> repository/Neo4j`；HTTP 路由只构造 `QARequest` 并调用 `DrawingGraphQAService.ask()`，不直接访问 facade、repository、Cypher 或 Neo4j。

启动服务（所有配置来自环境变量，不接受密码、token 或 API key 命令行参数）：

```powershell
$env:NEO4J_URI = "bolt://127.0.0.1:7687"
$env:NEO4J_USER = "neo4j"
$env:NEO4J_PASSWORD = "<your-password>"
python scripts\serve_drawing_graph_qa.py
```

HTTP 专用环境变量：

- `DRAWING_GRAPH_QA_HTTP_HOST`：默认 `127.0.0.1`（loopback）。
- `DRAWING_GRAPH_QA_HTTP_PORT`：默认 `8000`。
- `DRAWING_GRAPH_QA_HTTP_ALLOW_REMOTE`：默认 `false`；非 loopback 绑定必须同时显式允许远程并配置 token。
- `DRAWING_GRAPH_QA_HTTP_API_TOKEN`：可选 Bearer token；配置后业务路由和 `/health/ready` 需要 `Authorization: Bearer <token>`，`/health/live` 始终匿名。
- `DRAWING_GRAPH_QA_HTTP_ALLOWED_ORIGINS`：可选显式 origin 白名单，默认空（不启用 CORS），不接受 `*`。
- `DRAWING_GRAPH_QA_HTTP_MAX_REQUEST_BYTES`（默认 65536）、`DRAWING_GRAPH_QA_HTTP_REQUEST_TIMEOUT_SECONDS`（默认 30）、`DRAWING_GRAPH_QA_HTTP_MAX_CONCURRENT_REQUESTS`（默认 8）、`DRAWING_GRAPH_QA_HTTP_DOCS_ENABLED`（默认 `false`，仅允许 loopback）、`DRAWING_GRAPH_QA_HTTP_LOG_LEVEL`（默认 INFO）。

最小只读请求：

```powershell
$body = @{ question_type = "page_summary"; scope = @{ page_id = "page:road-project:lslq_yhd_2_1:road_24" } } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/drawing-qa/ask -ContentType "application/json" -Body $body
```

版本化入口：`POST /api/v1/drawing-qa/ask`（权威入口）、`GET /api/v1/drawing-qa/pages/{page_id}/summary`、`GET /api/v1/drawing-qa/blocks/{block_id}/relations`、`GET /api/v1/drawing-qa/candidates`、`GET /api/v1/drawing-qa/section-matches`、`GET /api/v1/drawing-qa/table-captions/status`、`GET /api/v1/drawing-qa/diagnostics`，以及 `GET /health/live` 和 `GET /health/ready`。

安全与验证边界：

- 默认 `write_back=false`，HTTP 不提供任何写回、候选提升或正式关系提升入口；`write_back=true` 返回 403。
- 候选关系、`matched_candidate`、语义观察与解释继续保持 `candidate_relation`、`semantic_observation`、`semantic_interpretation` 分层，不提升为正式事实。
- 默认单 worker、loopback、CORS 关闭、OpenAPI docs 关闭；远程绑定必须显式开启，并要求外部 TLS（由外部反向代理提供）。
- `GET /health/ready` 返回 `neo4j_status="not_checked"`：进程存活或 runtime 已装配**不等于 live Neo4j 验证**；live Neo4j 只有配置 disposable 测试库并实际运行集成测试后才能声称已验证。
- 请求体超限返回 413、并发上限返回 429、等待超时返回 504；错误消息经共享脱敏，不返回 traceback、URI、密码、token 或底层类名。

## 10. 测试命令

333 页全量数据导入、离线派生关系增强、Neo4j 计数、CLI 抽样和 live Neo4j 回归验收已记录在 `docs/acceptance/FULL_DATA_ACCEPTANCE.md`。该记录使用 `road-full-20260807-acceptance` 前缀保留验收数据，便于 Neo4j Browser 复查；真实密码未写入仓库文件。

运行 Task 27 的独立测试：

```powershell
python -m unittest tests.test_readme -v
```

运行 Task 18 的独立测试：

```powershell
python -m unittest tests.test_relation_readme -v
```

运行 Skill 静态边界测试：

```powershell
python -m unittest tests.test_skill_docs -v
```

运行全部测试发现命令：

```powershell
python -m unittest discover tests -v
```

未设置 `NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD` 时，`tests/integration/` 会按设计跳过；这种跳过不代表真实 Neo4j 已通过。如果要验证 live Neo4j，需要使用 disposable 测试库、专用测试账号或本机临时测试实例，并额外设置测试库连接：

```powershell
$env:NEO4J_TEST_URI = "bolt://127.0.0.1:7687"
$env:NEO4J_TEST_USER = "neo4j"
$env:NEO4J_TEST_PASSWORD = "<test-password>"
python -m unittest discover tests.integration -v
```

也可以分别运行三个真实 Neo4j 集成测试：

```powershell
python -m unittest tests.integration.test_neo4j_import -v
python -m unittest tests.integration.test_neo4j_relation_enrichment -v
python -m unittest tests.integration.test_neo4j_semantic_evidence -v
```

集成测试会初始化 Schema、导入样例页面、验证重复导入幂等性、基础导入不写 `Table -[:HAS_CAPTION]-> TableCaption`、离线派生关系增强幂等性、表格标题 legacy 兼容、`USES_BASIC_INFO`、`CANDIDATE_CAPTION_OF`、`CANDIDATE_HAS_SECTION_MARK`、`HAS_SECTION_MARK` 写入和查询闭环，并验证语义证据层 live Neo4j 闭环：`TextObservation`、`BlockInterpretation`、`BasicInfoInterpretation`、`TableInterpretation`、`HAS_OBSERVATION`、`HAS_INTERPRETATION`、`SUPPORTED_BY`、`CANDIDATE_MATCHES_SECTION_CAPTION`、`MATCHES_SECTION_CAPTION` 的真实写入、幂等和查询投影，同时确认不创建 `RecognitionRun` 图谱节点。测试结束后会清理本轮测试数据。

## 11. 常见错误

- `DRAWING_GRAPH_DATA_ROOT is required`：缺少必需环境变量，按第 2 节设置后重试。
- `DRAWING_GRAPH_BATCH_SIZE must be a positive integer`：批量大小不是正整数。
- Neo4j 连接失败：确认数据库已启动、`NEO4J_URI` 正确、用户具备目标库读写权限。
- 同名 PNG 缺失：补齐 `road_<数字>.png`，或确认 JSON 文件是否应该跳过。
- 页码解析失败：将文件名调整为 `road_<数字>.json` 格式。
- 查询为空：先用批次状态确认导入是否成功，再检查 `project_slug`、图纸册目录名、页面文件名和 shape hash 是否一致。
- `--rule-version` 缺失：离线派生关系增强必须显式声明规则版本后再运行。
- 增强后仍是 `not_enhanced`：确认基础页面级图谱已经导入，且输入的 `project_id`、`drawing_set_id`、`page_id` 或 `block_id` 与稳定业务 ID 一致。
