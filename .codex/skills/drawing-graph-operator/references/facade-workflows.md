# Facade 工作流

## 1. 入口选择

所有图谱能力调用只经过两个受控入口：

1. **Python facade**：`DrawingGraphToolFacade`，通过 `create_neo4j_tool_facade()` 装配；不要在 import 时连接数据库，不要把密钥传入 facade 配置。
2. **薄 CLI adapter**：`scripts/drawing_graph_tool.py`，从环境变量读取连接配置、创建 driver、调用 facade 并输出 JSON。

禁止：直接创建 Neo4j driver、拼写或执行 Cypher、直接调用 repository 写回方法、直接调用 `src/drawing_graph/block_relation_enrichment.py` 中的规则函数。

## 2. 只读查询（默认 `write_back=false`）

查询默认只读。CLI 能力示例（PowerShell）：

```powershell
python scripts\drawing_graph_tool.py list-drawing-sets --project-id <project-id>
python scripts\drawing_graph_tool.py list-pages --drawing-set-id <drawing-set-id>
python scripts\drawing_graph_tool.py page-source-facts --page-id <page-id>
python scripts\drawing_graph_tool.py block-trace --block-id <block-id>
python scripts\drawing_graph_tool.py block-relations --block-id <block-id>
python scripts\drawing_graph_tool.py list-text-observations --page-id <page-id>
python scripts\drawing_graph_tool.py list-interpretations --element-id <element-id>
python scripts\drawing_graph_tool.py list-candidate-relations --page-id <page-id>
python scripts\drawing_graph_tool.py list-section-matches --cross-section-id <cross-section-id>
```

连接配置通过环境变量提供（不写真实密码，只写变量名）：

```powershell
$env:NEO4J_URI = "<neo4j-uri>"
$env:NEO4J_USER = "<neo4j-user>"
$env:NEO4J_PASSWORD = "<neo4j-password>"
```

## 3. 薄 CLI adapter 能力清单

| 命令 | 用途 | 常用参数 |
|---|---|---|
| `list-drawing-sets` | 列出项目的图纸集 | `--project-id`, `--limit` |
| `list-pages` | 列出图纸集的页面 | `--drawing-set-id`, `--limit` |
| `page-source-facts` | 返回页面来源事实 | `--page-id`, `--element-type`, `--no-image-meta` |
| `block-trace` | 返回单个 `DrawingBlock` 的追溯证据 | `--block-id` |
| `block-relations` | 返回单个 block 的关系 | `--block-id` |
| `list-text-observations` | 查询持久化 `TextObservation` | `--page-id`/`--element-id`/`--recognition-run-id`, `--status` |
| `list-interpretations` | 查询持久化语义解释 | `--page-id`/`--element-id`/`--recognition-run-id`, `--status` |
| `list-candidate-relations` | 查询候选关系 | `--page-id`, `--block-id`, `--relation-type`, `--status` |
| `list-section-matches` | 查询断面标题候选与正式匹配 | `--cross-section-id`, `--page-id`, `--status` |

## 4. dry-run 与写回边界

- 默认 `write_back=false`：语义识别和断面匹配只返回临时 `recognition_run_id`、observation 和 interpretation，不写数据库。
- 只有用户明确授权、环境确认并有验证计划时，才允许显式 `write_back=true`。
- 候选复核流程使用 dry-run 先查看候选，确认后再执行显式复核；复核结果仍需经过 `CandidateReviewService` 和硬规则。

## 5. 显式流程与隐式触发边界

以下流程都是显式、独立执行的，不由 Skill 隐式自动触发：

- 来源事实导入：`scripts/import_json.py`
- 离线派生关系增强：`scripts/enrich_block_relations.py`
- 候选关系复核：`scripts/review_candidate_relations.py`

Skill 只描述这些流程的存在和正确顺序，不自动运行它们，不把它们挂到查询或识别调用上。
