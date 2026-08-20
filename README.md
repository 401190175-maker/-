# 图块图谱构建使用说明

本项目将 XAnyLabeling 标注 JSON 和同目录同名 PNG 导入 Neo4j，形成 `Project -> DrawingSet -> DrawingPage -> DrawingBlock` 及页面元素的可追溯图谱。当前阶段只做来源事实导入、离线派生关系增强、显式候选关系 AI 复核骨架、批次审计和只读查询，不做 OCR、Ava 专有 adapter 或完整图纸语义推理；已提供默认本机监听、默认只读的 HTTP API（见第 10 节）和本机 STDIO、默认只读的 MCP adapter（见第 9 节）。

当前闭环状态：基础导入、离线派生关系增强、候选关系复核服务骨架和查询验证已经形成流程。推荐运行顺序是初始化 Schema，执行 `scripts\import_json.py all` 写入来源事实，再显式执行 `scripts\enrich_block_relations.py project --rule-version <version>` 写入表格标题、页面级基础信息上下文、block 级正式派生关系和空间候选边；如需复核候选关系，再显式执行 `scripts\review_candidate_relations.py candidate-group ...`。最后用 `QueryService.get_block_trace()` 和 `QueryService.get_block_relations()` 验证单个图块的位置证据、候选 ID 与派生关系状态。

模块职责、新接口、新依赖、数据变化和架构变化见 `Module.md`；该文档按当前代码实现记录维护边界，不把未实现的 OCR、Ava 专有 adapter 或全量自动语义扫描当作已完成能力；旧 QA HTTP API 当前实现见第 10 节，本地只读 QA MCP adapter 当前实现见第 9 节，产品级只读 HTTP/MCP 问答 adapter 见“产品级 HTTP/MCP adapter（产品实现层）”。单页端到端 CLI 验收证据见 `docs/acceptance/E2E_CLI_ACCEPTANCE.md`，333 页全量数据导入验收证据见 `docs/acceptance/FULL_DATA_ACCEPTANCE.md`，答案生成与只读总编排验收见 `docs/acceptance/ANSWER_GENERATION_MVP_ACCEPTANCE.md`，追溯与反馈专项验收见 `docs/acceptance/TRACE_FEEDBACK_ACCEPTANCE.md`，产品 adapter 验收见 `docs/acceptance/PRODUCT_ADAPTER_ACCEPTANCE.md`，面向普通用户的最短运行流程见 `docs/acceptance/USER_RUNBOOK.md`。

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
$env:DRAWING_GRAPH_DATA_ROOT = "<your-data-root>"
$env:DRAWING_GRAPH_PROJECT_SLUG = "road-project"
$env:NEO4J_URI = "bolt://127.0.0.1:7687"
$env:NEO4J_USER = "neo4j"
$env:NEO4J_PASSWORD = "<your-password>"
$env:DRAWING_GRAPH_BATCH_SIZE = "500"
$env:DRAWING_GRAPH_LOG_LEVEL = "INFO"
$env:DRAWING_GRAPH_RECOGNITION_PROVIDER = "qwen"
$env:DASHSCOPE_API_KEY = "<your-dashscope-api-key>"
```

必需变量：

- `DRAWING_GRAPH_DATA_ROOT`：数据根目录，下面每个子目录视为一个 `DrawingSet`。
- `DRAWING_GRAPH_PROJECT_SLUG`：项目稳定标识，用于生成 `project:<slug>`、`set:<slug>:...`、`page:<slug>:...` 等业务 ID。
- `NEO4J_URI`、`NEO4J_USER`、`NEO4J_PASSWORD`：Neo4j 连接信息。

可选变量：

- `DRAWING_GRAPH_BATCH_SIZE`：批量写入大小，必须是正整数，默认 `500`。
- `DRAWING_GRAPH_LOG_LEVEL`：日志级别，默认 `INFO`。

多模态识别相关（可选，`DRAWING_GRAPH_RECOGNITION_PROVIDER=qwen` 时启用）：

- `DRAWING_GRAPH_RECOGNITION_PROVIDER`：识别 provider，设为 `qwen` 才调用 Qwen/DashScope；未设置时默认 Fake，不调用云模型。
- `DASHSCOPE_API_KEY`：DashScope API key（个人账号，按量计费），只有 `provider=qwen` 时需要。
- `DRAWING_GRAPH_QWEN_MODEL`、`DRAWING_GRAPH_QWEN_BASE_URL`、`DRAWING_GRAPH_QWEN_TIMEOUT_SECONDS`：Qwen 客户端可选参数，默认值见 `.env.example`。

仓库提供 `.env.example` 作为本机和 CI 配置模板，只包含占位符，不包含真实密码。真实 `.env`、`.env.local` 等本机密钥文件已加入 `.gitignore`，不要提交真实 Neo4j 密码、供应商 API key、token 或 secret。

Neo4j Browser 常见地址是 `http://localhost:7474/browser/`，它只用于浏览器管理界面；Python driver、导入脚本和集成测试需要 Bolt 地址，常见为 `bolt://127.0.0.1:7687`。如果 Browser 中 `CALL dbms.listConnections()` 显示 Bolt connector 为 `127.0.0.1:7687`，则测试和导入配置也应使用这个 Bolt 地址，而不是 `localhost:7474`。

### 2.1 首次运行配置清单（必读）

本项目的数据库和云模型都属于本机/个人外部资源，项目不能替你生成账号密码或 API key。首次运行按以下顺序配置：

1. **安装并启动 Neo4j**：安装 Neo4j Community 5.x（或用 Docker 起官方镜像），启动后确认 Bolt 端口（默认 `bolt://127.0.0.1:7687`）可连接，并记录你的账号密码。
2. **创建本机配置文件**：复制 `.env.example` 为 `.env`（`.env` 已被 `.gitignore` 忽略，不会上传 git）。在 `.env` 中至少填写：
   - `NEO4J_PASSWORD`（你的 Neo4j 密码）；
   - `DASHSCOPE_API_KEY`（如需多模态识别，填 DashScope 个人 key）；
   - `DRAWING_GRAPH_DATA_ROOT`、`DRAWING_GRAPH_PROJECT_SLUG`（按你的数据目录和项目标识填写；`PROJECT_SLUG` 在首次导入前可改，导入后改动会导致全部业务 ID 不一致）。
3. **把配置加载到当前会话**：本项目不自动读取 `.env`，所有脚本从当前进程环境变量读取。PowerShell 中加载：

   ```powershell
   Get-Content .env | Where-Object { $_ -match '^[A-Za-z_][A-Za-z0-9_]*=' } | ForEach-Object {
       $name, $value = $_ -split '=', 2
       [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim(), 'Process')
   }
   ```

   Codex/Skill 会话同样需要先加载；`DASHSCOPE_API_KEY` 若已在系统环境变量中则无需重复设置。
4. **验证配置**：运行前置门检查，报告 `"blocked": false` 才算配置完成（`mcp_not_registered` 只表示 MCP 未注册，不影响 Neo4j/识别链路）：

   ```powershell
   python scripts\skill_preflight.py
   ```

   启动 Neo4j（幂等，等待 Bolt 就绪）：`powershell -ExecutionPolicy Bypass -File scripts\start_neo4j.ps1`；产品 MCP 启动脚本 `scripts\start_drawing_assistant_mcp.ps1` 会在启动 server 前自动拉起本机 Neo4j，无需手动启动。

5. **按顺序初始化**：执行第 4 节 Schema 初始化、第 5 节导入数据、第 6 节离线派生关系增强，之后才能进行查询/问答。

安全边界：`.env` 含真实凭据，已被 gitignore，不要改名或复制到可提交路径；`.env.example` 只放占位符，可安全提交；不要在任何文档、日志、命令输出或 issue 中粘贴真实密码或 API key。

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

查询服务本身仍是 Python 内部接口，不直接开放 HTTP；对外 HTTP 入口见第 10 节。可以用下面的方式做最小验证：

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
python scripts\drawing_graph_tool.py recognize-page-semantics --page-id page:road-project:lslq_yhd_2_1:road_24 --target-type DrawingBlock --model-profile qwen3-vl-plus --prompt-version qwen-vision-v1
python scripts\drawing_graph_tool.py list-text-observations --page-id page:road-project:lslq_yhd_2_1:road_24 --status confirmed
python scripts\drawing_graph_tool.py list-interpretations --page-id page:road-project:lslq_yhd_2_1:road_24 --status partial
python scripts\drawing_graph_tool.py list-candidate-relations --block-id block:road-project:lslq_yhd_2_1:road_24:<shape_hash> --relation-type candidate_section_mark --status candidate
python scripts\drawing_graph_tool.py list-section-matches --cross-section-id element:road-project:lslq_yhd_2_1:road_24:<shape_hash> --status candidate --status confirmed
```

搜索图纸册页内容（只读）：

```powershell
python scripts\drawing_graph_tool.py search-pages --drawing-set-id set:road-project:lslq_yhd_2_2 --query 排水
python scripts\drawing_graph_tool.py search-pages --drawing-set-id set:road-project:lslq_yhd_2_2 --query 排水 --allow-recognition
```

`search-pages` 返回命中页（`matches`，含命中片段与元素 ID）与 `coverage`（扫描/缓存/本次识别/跳过）。`--allow-recognition` 对无缓存观察的页面按需识别，默认 dry-run；显式持久化识别缓存需追加 `--write-back`。无命中返回 `NOT_FOUND` 是正常状态。

`recognize-page-semantics` 默认 `write_back=false`，只返回本次临时 `recognition_run_id`、observation 和 interpretation；只有显式传入 `--write-back` 才会通过 facade 进入受控语义证据写回流程。使用 Qwen 时需要当前进程已配置 `DRAWING_GRAPH_RECOGNITION_PROVIDER=qwen` 和 `DASHSCOPE_API_KEY`，命令参数和输出不会包含真实 API key。

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

输出支持 JSON（默认）和简短中文（`--format zh-brief`）。QA CLI 与底层 `scripts\drawing_graph_tool.py` 一样只做参数解析、facade 创建和输出渲染；业务编排在 `src/drawing_graph/qa_service.py`。HTTP API 见第 10 节，本地只读 MCP adapter 见第 9 节；当前已提供可选 Qwen/DashScope 多模态客户端，但不默认调用，live DashScope 验证需单独执行；Ava 专有 adapter、OCR 和数据库 schema 变更仍未实现。

## 9. MCP 只读工具（第三阶段）

`src/drawing_graph/qa_mcp_*.py` 与 `scripts\serve_drawing_graph_mcp.py` 提供本机 STDIO、默认只读的 MCP adapter。调用链固定为 `MCP adapter -> DrawingGraphQAService -> DrawingGraphToolFacade -> ports/services -> repository/Neo4j`；MCP 不调用 HTTP API 或 QA CLI 子进程，每个业务工具只构造 `QARequest` 并调用一次 `DrawingGraphQAService.ask()`。

依赖安装与 QA CLI/HTTP 相同：

```powershell
python -m pip install -r requirements.txt
```

启动前设置与 QA CLI 相同的 Neo4j 环境变量（`NEO4J_URI`、`NEO4J_USER`、`NEO4J_PASSWORD`），可选 `DRAWING_GRAPH_QA_MCP_LOG_LEVEL`（默认 INFO）。MCP server 名称固定为 `drawing-graph-qa`，STDIO 启动命令：

```powershell
python scripts\serve_drawing_graph_mcp.py
```

脚本不接受 host、port、worker、HTTP token 或远程 transport 参数；stdout 只承载 MCP 协议帧，诊断日志进入 stderr 并经共享脱敏。

首版只注册六个窄口径只读工具，每个工具固定 `write_back=false` 且 `include_payload=false`：

| 工具 | 用途 | 必需 scope |
|---|---|---|
| `ask_drawing_page` | 页面摘要与事实 | `page_id` |
| `ask_drawing_block` | 图块关系 | `block_id` |
| `list_drawing_candidates` | 候选关系列表 | `page_id` 或 `block_id` |
| `get_section_match_status` | 断面匹配状态 | `cross_section_id` 或 `page_id` |
| `get_table_caption_status` | 表格/表题状态 | `table_id`、`table_caption_id` 或 `page_id` |
| `get_drawing_diagnostics` | 页面/图块诊断 | `page_id` 或 `block_id` |

Codex 项目级 MCP 配置只记录 server 名、启动命令、工作目录和允许转发的环境变量名，不写真实凭据值；建议客户端对六个工具使用显式 allowlist。MCP 不可用时，`drawing-graph-operator` Skill 会先明确说明，再按 `references/mcp-boundaries.md` 透明降级到只读 QA CLI，禁止静默降级或把 CLI 结果冒充 MCP 已验证。

验证边界：MCP 单元/合约测试、STDIO fake smoke 与 HTTP 回归都不能证明 live Neo4j；live Neo4j 只有配置 `NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD` 并实际运行集成测试后才能声称已验证。Skill 对 `drawing-graph-qa` 的 MCP 工具依赖声明当前为宿主兼容性待办（Task 40），未验证前不宣称依赖发现已通过。

首版不实现 Streamable HTTP MCP、远程监听、多 worker、OAuth、RBAC、TLS 或插件发布；不提供任何写回、候选复核、候选提升或任意 Cypher 工具。

## 10. HTTP API（第二阶段）

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

## 11. 测试命令

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

运行第三阶段 MCP/Skill 文档合同与路由行为测试：

```powershell
python -m unittest tests.test_qa_mcp_docs -v
python -m unittest tests.test_qa_mcp_skill_behavior -v
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

## 12. 常见错误

- `DRAWING_GRAPH_DATA_ROOT is required`：缺少必需环境变量，按第 2 节设置后重试。
- `DRAWING_GRAPH_BATCH_SIZE must be a positive integer`：批量大小不是正整数。
- Neo4j 连接失败：确认数据库已启动、`NEO4J_URI` 正确、用户具备目标库读写权限。
- 同名 PNG 缺失：补齐 `road_<数字>.png`，或确认 JSON 文件是否应该跳过。
- 页码解析失败：将文件名调整为 `road_<数字>.json` 格式。
- 查询为空：先用批次状态确认导入是否成功，再检查 `project_slug`、图纸册目录名、页面文件名和 shape hash 是否一致。
- `--rule-version` 缺失：离线派生关系增强必须显式声明规则版本后再运行。
- 增强后仍是 `not_enhanced`：确认基础页面级图谱已经导入，且输入的 `project_id`、`drawing_set_id`、`page_id` 或 `block_id` 与稳定业务 ID 一致。

## 13. 产品公共合同与通用检索闭环（产品实现层）

`src/drawing_graph/assistant_models.py`、`assistant_retrieval_planner.py`、`assistant_retrieval_executor.py`、`assistant_retrieval_projection.py`、`assistant_retrieval_service.py` 与 `assistant_qa_mapping.py` 组成产品实现层的公共合同与只读通用检索闭环：`QuestionUnderstandingResult -> EvidenceRequirement[] -> RetrievalPlan -> DrawingGraphToolFacade 白名单只读调用 -> RetrievalBundle`。该闭环是 Python 内部 API，入口为 `GraphRetrievalService.retrieve()`；`assistant_qa_mapping.py` 只做 `QARequest -> QuestionUnderstandingResult` 的单向兼容映射，不修改 `DrawingGraphQAService` 行为。

边界：通用检索默认只读，`write_back=false`；不调用 Qwen；不创建 RecognitionRun；不写 Neo4j；不审核或提升候选关系；候选关系不是正式事实，`matched_candidate` 不能当作正式图谱关系。`DrawingAssistantService` 与产品级只读 CLI 已在 06/07 MVP 中实现，产品级只读 HTTP/MCP 问答 adapter 已实现（见“产品级 HTTP/MCP adapter”一节），产品运行审计的追溯 store 与反馈 store/审计也已实现为 Python 内部能力；外部产品级 Web UI 与反馈入口、外部持久化 store、多用户账号集成和产品级业务写回入口尚未实现。

### 13.1 问题理解闭环（产品实现层 01，已实现）

`assistant_question_text.py`、`assistant_scope_resolution.py`、`assistant_question_rules.py`、`assistant_intent_splitter.py`、`assistant_evidence_templates.py`、`assistant_clarification.py`、`assistant_question_trace.py`、`assistant_question_llm.py`（协议与 fake，不默认真实模型）与 `assistant_question_understanding.py` 组成 01 问题理解闭环：`AssistantRequest -> QuestionUnderstandingService -> QuestionUnderstandingResult -> GraphRetrievalService -> RetrievalBundle`。首版采用规则优先的确定性中文路由；scope 缺失/冲突、指代不唯一或问题类型歧义时返回 `clarification_required` 结构化澄清；不支持时返回 `unknown_or_unsupported`；`QuestionUnderstandingModelClient` 只作为受约束适配口保留，fake 客户端与输出校验已实现，默认不调用真实文本模型。

问题理解模块不访问 Neo4j、不调用 `DrawingGraphToolFacade`、不创建 RecognitionRun、不写数据库；`write_back=false` 不会被问题文本提升。专项测试见 `tests/test_assistant_question_*.py` 与 `tests/test_assistant_question_security.py`；未运行 live Neo4j 或 live 模型时，不报告 live 验证通过。

验证方式（均为单元/合同测试，不连接真实 Neo4j，也不调用真实云模型）：

```powershell
python -m unittest tests.test_assistant_docs -v
python -m unittest tests.test_assistant_models_contract -v
python -m unittest tests.test_assistant_retrieval_planner -v
python -m unittest tests.test_assistant_retrieval_executor -v
python -m unittest tests.test_assistant_retrieval_projection -v
python -m unittest tests.test_assistant_retrieval_service -v
python -m unittest tests.test_assistant_qa_mapping -v
python -m unittest tests.test_assistant_retrieval_boundaries -v
```

未配置 `NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD` 时，集成测试会 skipped；这种 skipped live 测试不等于通过，跳过不等于 live Neo4j 通过，不能声称 live Neo4j 已验证。

### 13.2 语义缺口决策闭环（产品实现层 03，首阶段已实现）

`assistant_evidence_sufficiency.py`、`assistant_evidence_freshness.py`、`assistant_recognition_target_planner.py`、`assistant_recognition_budget.py` 与 `assistant_semantic_gap_decision.py` 组成语义缺口决策闭环：`QuestionUnderstandingResult + RetrievalBundle + RecognitionPolicy -> SemanticGapDecisionService -> SemanticGapDecision`。它回答“证据是否足够、缓存是否可复用、是否允许识别、识别哪些最小目标、哪些目标被预算/时延/scope 延后”，位于检索之后、语义识别执行之前。

边界：03 是纯决策层，不调用模型、不写缓存、不写 Neo4j、不创建 RecognitionRun、不提升候选关系；默认 `write_back=false`，`write_back_recommendation` 只是建议，不能修改授权。`candidate` 与 `matched_candidate` 不等于 formal，语义观察不能满足解释需求，来源事实不能被模型输出覆盖。执行衔接已由 `DrawingGraphToolFacade.recognize_semantic_targets()`、`SemanticRecognitionService.recognize_targets()` 与 04 `MultimodalRecognitionExecutionService` 落地：执行前按统一 cache key 二次校验，缓存命中不调用供应商、不创建 attempt 或持久化 run log，cache miss 才进入多模态执行流水线；04 输出可交给 05 `EvidenceFusionService` 做确定性融合与可选受控延迟写回。06 `AnswerGenerationService` 与 07 `DrawingAssistantService` 已消费 05 输出形成产品级只读 CLI 链路；07 追溯与 08 反馈已作为产品运行审计内部能力落地，产品级只读 HTTP/MCP 问答 adapter 已实现，但外部产品级 Web UI 与反馈入口、外部持久化 store 与多用户账号集成仍属后续范围。

验证方式（单元/合同/静态边界测试，不连接真实 Neo4j，也不调用真实云模型）：

```powershell
python -m unittest tests.test_assistant_semantic_gap_models -v
python -m unittest tests.test_assistant_evidence_sufficiency -v
python -m unittest tests.test_assistant_evidence_freshness -v
python -m unittest tests.test_assistant_recognition_target_planner -v
python -m unittest tests.test_assistant_recognition_budget -v
python -m unittest tests.test_assistant_semantic_gap_decision -v
python -m unittest tests.test_assistant_semantic_gap_boundaries -v
python -m unittest tests.test_assistant_semantic_gap_docs -v
```

未配置 live DashScope 或 live Neo4j 时，不报告 live 验证通过；skipped live 测试不等于 live 通过。

## 多模态识别执行层（04）

`changes/产品实现层/多模态识别产品化/tasks.md` 的 Task 1-43 已全部实现。产品实现层 04 形成供应商无关、同步优先的多模态识别执行流水线：

- 七类任务：`page_summary`、`element_text_observation`、`block_semantic_identification`、`basic_info_interpretation`、`table_interpretation`、`section_label_observation`、`relation_evidence_extraction`。
- 局部 bbox 内存裁剪、EXIF 规范化、受控缩放与资源上限；provider 只接收已渲染 prompt 与内存图。
- 受控重试与 attempt：429/暂时性 5xx/超时有限重试、最多一次结构修复、deadline 与预算门控；每次调用生成独立 attempt。
- 实际 usage/成本/分阶段延迟计量；缺失时 `unavailable`，不写 0。
- 统一 fail-closed 脱敏与图谱外 attempt log。
- `MultimodalRecognitionExecutionService` 唯一编排入口；`SemanticRecognitionService` 负责缓存、分组、投影与受控写回；Factory 默认 Fake，仅显式 qwen 配置才创建 Qwen adapter。
- 边界：默认 `write_back=false`；run/attempt 图谱外；observation/interpretation 图谱内；relation 输出只能为 `candidate_relation`；候选不等于正式事实；无 OCR；不改变 Neo4j 来源事实 schema。
- 专项验收：

```powershell
$env:PYTHONPATH='src'
python -m unittest tests.test_multimodal_recognition_docs tests.test_multimodal_recognition_acceptance tests.test_multimodal_recognition_contracts tests.test_multimodal_recognition_boundaries tests.test_tool_facade tests.test_semantic_service tests.test_qwen_semantic_client -v
```

2026-08-13 当前验证快照：专项 73 项通过；完整 `python -m unittest discover tests -v` 运行 1823 项，4 项 live Neo4j 集成测试因缺少 `NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD` 而跳过，其余通过。该结果属于离线/fake 验证；live DashScope、黄金集、live Neo4j、Codex/MCP 均未声称通过，本次文档同步也未执行这些 live 验证。

## 证据融合与缓存闭环（05）

`changes/产品实现层/证据融合与缓存闭环/tasks.md` 的 Task 1-56 已全部实现。产品实现层 05 位于 04 之后、06 之前，是独立、确定性、默认只读的证据融合与缓存闭环：

- 唯一编排入口 `EvidenceFusionService.fuse()`，固定执行：校验 -> 收集 -> 投影 -> 规范化 -> 去重 -> lineage -> 冲突 -> claim 支撑 -> answerability -> 可选受控写回 -> `EvidenceBundle`。
- 四类 key 职责分离：`cache_key` 只用于精确复用；`evidence_family_key` 只用于 lineage/stale；`comparison_key` 只用于可比证据分组；`content_fingerprint` 只用于确定性去重。
- 边界：默认 `write_back=false`；dry-run 零持久化，仅请求内 `RequestSemanticMemo`；persistent cache 仅在受控写回授权通过后提交；`candidate` 不等于 formal，融合/置信度/写回授权均不提升 `fact_kind`；05 不调用模型、不查询 Neo4j、不执行 Cypher、不新增外部 API。
- 06/07 已在后续 MVP 中消费本层 `EvidenceBundle` 形成产品级答案生成与只读总编排；本层自身仍不发起新查询、不调用模型、不写 Neo4j、不提升候选关系。

验证方式（离线/fake，不连接真实 Neo4j，也不调用真实云模型）：

```powershell
$env:PYTHONPATH='src'
python -m unittest tests.test_assistant_evidence_fusion_models tests.test_assistant_recognition_projection tests.test_assistant_evidence_normalization tests.test_assistant_evidence_deduplication tests.test_assistant_evidence_rules tests.test_assistant_evidence_lineage tests.test_assistant_evidence_conflicts tests.test_assistant_claim_support tests.test_assistant_answerability tests.test_assistant_cache_closure tests.test_assistant_semantic_write_back tests.test_assistant_evidence_fusion tests.test_assistant_evidence_fusion_factory tests.test_assistant_evidence_fusion_boundaries tests.test_assistant_evidence_fusion_docs -v
```

2026-08-14 的 05 验证快照：05 专项回归运行 280 项，0 失败、0 错误、0 跳过；当时完整 `python -m unittest discover tests -v` 运行 2150 项，0 失败、0 错误、4 项因缺少 `NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD` 而跳过。06/07 完成后的产品答案与只读总编排离线验证见下一节。以上属于离线/fake、合同和静态边界验证；live Neo4j、live DashScope 与黄金集未验证，skipped live 测试不等于 live 通过。

## 答案生成与只读总编排（产品实现层 06/07）

产品级只读 CLI 是现有 QA CLI/HTTP/MCP 的同级 adapter，接收自然语言问题并输出权威 JSON 或简短中文答案：

`python scripts/drawing_assistant.py --question "page:1 这张图主要讲什么" --request-id req:1`

参数：`--question`（必填）、`--request-id`、`--project-id`、`--drawing-set-id`、`--page-id`、`--block-id`、`--element-id`、`--cross-section-id`、`--allow-recognition | --no-recognition`、`--text-generation`、`--output json|text`。默认 `--output json`，stdout 只输出一个 `{"ok": true, "data": {...}}` envelope（含 `answer_contract_version`、`request_id`、`status`、`machine_answer`、`text_answer`）；`--output text` 只输出 `text_answer`。CLI 不提供 `--write-back` 参数，Neo4j 凭据与 provider 配置只从环境变量读取，不进入命令参数或输出。

退出码：`0` 得到合法 `AnswerPackage`（含 `answered`/`partial`/`clarification_required`/`unsupported`/`recognition_failed` 业务状态）；`1` 运行时基础设施或必需阶段失败；`2` 参数、配置、合同或只读授权错误。错误 envelope 输出到 stderr 且已脱敏。

`machine_answer`、claims、citations 与 status 是权威输出，由确定性代码生成；中文模板始终可用，受约束文本生成只是可选表现层（`--text-generation` 仅当 factory 显式装配生成器时生效，未装配时回退模板且不访问网络）。产品 CLI 与 `DrawingAssistantService`（07）、`AnswerGenerationService`（06）默认只读，全链路 `write_back=false`，不写 Neo4j、不提升候选关系。

离线/fake 验证入口：`python -m unittest tests.test_assistant_answer_models tests.test_assistant_claim_builder tests.test_assistant_citation_builder tests.test_assistant_answer_serialization tests.test_assistant_answer_templates tests.test_assistant_answer_text tests.test_assistant_answer_generation tests.test_assistant_answer_security tests.test_assistant_answer_boundaries tests.test_drawing_assistant_service tests.test_drawing_assistant_boundaries tests.test_drawing_assistant_factory tests.test_drawing_assistant_cli tests.test_drawing_assistant_cli_boundaries tests.test_drawing_assistant_e2e -v`。live Neo4j、live DashScope 与真实文本 provider 均未验证。

## 产品级 HTTP/MCP adapter（产品实现层）

产品级只读 HTTP/MCP adapter 把自然语言问答从 CLI 扩展到 HTTP 与本地 MCP，只调用 `DrawingAssistantService.answer()`：

- HTTP：`src/drawing_graph/assistant_http.py` + `src/drawing_graph/assistant_http_models.py` + `src/drawing_graph/assistant_http_runtime.py` + `scripts/serve_drawing_assistant.py` 提供 `POST /api/v1/drawing-assistant/ask`、`GET /health/live`、`GET /health/ready`。
- MCP：`src/drawing_graph/assistant_mcp_models.py` + `assistant_mcp_tools.py` + `assistant_mcp_runtime.py` + `assistant_mcp_server.py` + `scripts/serve_drawing_assistant_mcp.py` 提供本地 STDIO 只读工具 `ask_drawing_assistant`，structuredContent 来自 `AnswerPackage` JSON-safe 投影，TextContent 只概述状态与数量、不新增事实。
- 边界：默认 `write_back=false`，HTTP/MCP 首版不提供写回；HTTP 检测到 `write_back=true`/`allow_write_back=true` 返回 403；并发上限、请求超时、请求体限制、认证与错误映射均稳定脱敏；候选关系不是正式事实。
- 环境变量：HTTP 使用 `DRAWING_GRAPH_ASSISTANT_HTTP_*`（host/port/token/body limit/timeout/concurrency/docs/log level），MCP 使用 `NEO4J_*` 与 `DRAWING_GRAPH_ASSISTANT_MCP_LOG_LEVEL`。

离线/fake 验证入口：`python -m unittest tests.test_assistant_adapter_serialization tests.test_assistant_http_models tests.test_assistant_http_runtime tests.test_assistant_http tests.test_assistant_http_cli tests.test_assistant_http_boundaries tests.test_assistant_mcp_models tests.test_assistant_mcp_tools tests.test_assistant_mcp_runtime tests.test_assistant_mcp_server tests.test_assistant_mcp_cli tests.test_assistant_mcp_boundaries tests.test_product_adapter_e2e tests.test_product_adapter_qa_compatibility -v`。2026-08-17 产品 adapter 验收快照为专项 127 项 OK；根文档契约 `tests.test_readme tests.test_module_docs tests.test_assistant_docs tests.test_assistant_adapter_docs` 共 42 项 OK；全仓离线回归 `python -m unittest discover tests` 运行 2717 项，`OK (skipped=5)`。这些结果属于 unit/fake/offline、HTTP TestClient 与 MCP in-memory 验证；HTTP 真实 socket、MCP STDIO 子进程、live Neo4j、live DashScope、真实文本 provider 与真实 MCP 宿主注册均未验证；skipped live 测试不等于 live 通过。验收记录见 `docs/acceptance/PRODUCT_ADAPTER_ACCEPTANCE.md`。

## 追溯闭环（产品实现层 07）

`changes/产品实现层/追溯与反馈闭环/tasks.md` 的第 7 次追溯闭环已实现。产品运行审计层新增追溯模块，位于 `DrawingAssistantService` 外侧，只写产品运行审计 store，不写 Neo4j 业务图谱：

- 新增模块：`src/drawing_graph/assistant_trace_models.py`、`assistant_trace_store.py`、`assistant_trace_builder.py`、`assistant_claim_trace.py`、`assistant_traceability_service.py`。
- 可选接入：`DrawingAssistantService` 构造注入 `traceability_service=None`；`create_drawing_assistant_service(..., traceability_service=None, trace_store=None)` 可选装配；未注入时默认行为不变。
- 边界：trace 只写 `TraceStorePort`，不新增 Neo4j schema，不写业务事实，不把候选关系/`matched_candidate` 写成正式关系；trace 存储失败不把答案标记为失败；输出脱敏。
- 本节只描述追溯职责；反馈状态机、权限、审计与 `CandidateReviewService` 受控对接已由产品实现层 08 独立实现，见下一节。外部反馈 API 仍未实现。

追溯专项离线/fake 验证入口：`python -m unittest tests.test_assistant_trace_models tests.test_assistant_trace_store tests.test_assistant_trace_builder tests.test_assistant_claim_trace tests.test_assistant_traceability_service tests.test_assistant_trace_boundaries -v`。live Neo4j 未验证。

## 反馈闭环（产品实现层 08）

`changes/产品实现层/追溯与反馈闭环/tasks.md` 的第 8 次反馈闭环已实现。反馈模块位于 trace 模块外侧，只写反馈 store 与审计事件，仅在 `request_review` 且权限允许时受控调用注入的 `CandidateReviewService`：

- 新增模块：`src/drawing_graph/assistant_feedback_models.py`、`assistant_feedback_store.py`、`assistant_feedback_permissions.py`、`assistant_feedback_state_machine.py`、`assistant_candidate_review_adapter.py`、`assistant_feedback_service.py`。
- 四类 action：`confirm`/`reject`/`correct` 只记录反馈与审计，不产生正式事实；`request_review` 仅在权限与候选条件满足时调用 `CandidateReviewService.review_candidate_group()`，候选不完整/跨页/方向不明/缺 evidence refs 时 unresolved/invalid。
- 边界：默认 `write_back=false`，权限不足 fail closed；用户反馈不会直接覆盖来源事实、语义证据、候选关系或正式关系；不新增 Neo4j schema；不实现外部产品级 Web UI 或外部反馈入口。

反馈专项离线/fake 验证入口：`python -m unittest tests.test_assistant_feedback_models tests.test_assistant_feedback_store tests.test_assistant_feedback_permissions tests.test_assistant_feedback_state_machine tests.test_assistant_candidate_review_adapter tests.test_assistant_feedback_service tests.test_assistant_feedback_boundaries tests.test_candidate_review_service -v`。追溯与反馈专项验收快照中合并回归运行 107 项，0 失败、0 错误、0 跳过，详见 `docs/acceptance/TRACE_FEEDBACK_ACCEPTANCE.md`。后续产品 adapter 验收已补齐当时过期的根文档契约断言，并记录全仓离线回归 2717 项 `OK (skipped=5)`；这些快照均不证明 live Neo4j、live DashScope 或真实文本 provider 已通过。
