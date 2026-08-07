# 用户级运行手册

本文给出从本机数据到 Neo4j 图谱再到 CLI 查询的最短运行流程。它面向使用者，不要求先理解内部 facade、repository 或语义证据层实现。

## 1. 准备环境

安装依赖：

```powershell
python -m pip install -r requirements.txt
```

启动 Neo4j 后，区分两个地址：

- Neo4j Browser：`http://localhost:7474/browser/`
- Python driver、导入脚本和测试使用 Bolt：`bolt://127.0.0.1:7687`

## 2. 配置环境变量

推荐只在当前 PowerShell 会话设置，不把真实密码写入文件：

```powershell
$env:DRAWING_GRAPH_DATA_ROOT = "C:\path\to\图块图谱构建\data"
$env:DRAWING_GRAPH_PROJECT_SLUG = "road-project"
$env:NEO4J_URI = "bolt://127.0.0.1:7687"
$env:NEO4J_USER = "neo4j"
$env:NEO4J_PASSWORD = "<your-password>"
$env:DRAWING_GRAPH_BATCH_SIZE = "500"
$env:DRAWING_GRAPH_LOG_LEVEL = "INFO"
```

仓库提供 `.env.example` 作为模板，但真实 `.env`、`.env.local` 等本机密钥文件不应提交。

## 3. 数据目录

数据根目录下每个子目录是一册图纸。每个页面需要 `road_<数字>.json` 和同目录同名 PNG：

```text
data\
  lslq_yhd_2_1\
    road_24.json
    road_24.png
```

如果 PNG 缺失，该页面会跳过；如果文件名不是 `road_<数字>.json`，页码解析会失败。

## 4. 最短运行流程

初始化 schema：

```powershell
Get-Content -Encoding UTF8 scripts\create_schema.cypher | cypher-shell -a $env:NEO4J_URI -u $env:NEO4J_USER -p $env:NEO4J_PASSWORD
```

导入全部数据：

```powershell
python scripts\import_json.py all
```

也可以只导入一册或一页：

```powershell
python scripts\import_json.py drawing-set batch:manual-001 data\lslq_yhd_2_1
python scripts\import_json.py page batch:manual-001 data\lslq_yhd_2_1\road_24.json
```

导入完成后，显式执行离线派生关系增强：

```powershell
python scripts\enrich_block_relations.py project --rule-version block-rel-v1
```

如果只验证单页：

```powershell
python scripts\enrich_block_relations.py page page:road-project:lslq_yhd_2_1:road_24 --rule-version block-rel-v1
```

`partial` 不是程序崩溃，它表示某些业务证据不足。例如页面没有 basic info 时会出现 `basic_info_not_evaluated`。

## 5. CLI 查询

查询图纸册：

```powershell
python scripts\drawing_graph_tool.py list-drawing-sets --project-id project:road-project --limit 10
```

查询页面：

```powershell
python scripts\drawing_graph_tool.py list-pages --drawing-set-id set:road-project:lslq_yhd_2_1 --limit 10
```

查询页面来源事实：

```powershell
python scripts\drawing_graph_tool.py page-source-facts --page-id page:road-project:lslq_yhd_2_1:road_24
```

查询一个图块的追溯证据和关系：

```powershell
python scripts\drawing_graph_tool.py block-trace --block-id block:road-project:lslq_yhd_2_1:road_24:<shape_hash>
python scripts\drawing_graph_tool.py block-relations --block-id block:road-project:lslq_yhd_2_1:road_24:<shape_hash>
```

查询语义证据和解释：

```powershell
python scripts\drawing_graph_tool.py list-text-observations --page-id page:road-project:lslq_yhd_2_1:road_24 --status confirmed
python scripts\drawing_graph_tool.py list-interpretations --page-id page:road-project:lslq_yhd_2_1:road_24 --status partial
```

查询候选关系和断面匹配：

```powershell
python scripts\drawing_graph_tool.py list-candidate-relations --block-id block:road-project:lslq_yhd_2_1:road_24:<shape_hash> --relation-type candidate_section_mark --status candidate
python scripts\drawing_graph_tool.py list-section-matches --cross-section-id element:road-project:lslq_yhd_2_1:road_24:<shape_hash> --status candidate --status confirmed
```

这些命令输出 JSON。成功时 `status` 为 `ok`；查不到数据时通常返回 `NOT_FOUND`。

## 6. Neo4j Browser 快速检查

在 Browser 中可以先查看某个项目：

```cypher
MATCH (project:Project {id: "project:road-project"})-[:HAS_SET]->(drawing_set)-[:HAS_PAGE]->(page)
RETURN project, drawing_set, page
LIMIT 25
```

查看某个验收或测试前缀：

```cypher
MATCH (node)
WHERE node.id STARTS WITH "project:e2e-cli-" OR node.id STARTS WITH "page:e2e-cli-" OR node.id STARTS WITH "block:e2e-cli-" OR node.id STARTS WITH "element:e2e-cli-"
RETURN node
LIMIT 50
```

## 7. 常见问题

- Browser 能打开不代表 Bolt 可用；CLI 需要 `NEO4J_URI=bolt://127.0.0.1:7687`。
- `DRAWING_GRAPH_DATA_ROOT is required` 表示环境变量没有设置。
- `page-source-facts` 返回 `NOT_FOUND` 时，先确认 page id 是否和 `project_slug`、图纸册目录名、文件名一致。
- `block-relations` 为 `not_enhanced` 时，先确认是否执行过 `scripts\enrich_block_relations.py`。
- `list-candidate-relations` 或 `list-section-matches` 返回 `NOT_FOUND` 可能是正常状态，表示当前图中没有候选关系或断面匹配关系。
- 不要把模型输出、候选关系或 `matched_candidate` 当成正式事实；正式关系需要明确规则或复核提升。

## 8. 验证命令

不连接真实 Neo4j 的全量测试：

```powershell
python -m unittest discover tests
```

连接 disposable Neo4j 测试库的集成测试：

```powershell
$env:NEO4J_TEST_URI = "bolt://127.0.0.1:7687"
$env:NEO4J_TEST_USER = "neo4j"
$env:NEO4J_TEST_PASSWORD = "<test-password>"
python -m unittest discover tests.integration -v
```

如果集成测试被跳过，跳过不等于通过。
