# 全量数据导入验收记录

本文记录一次真实 Neo4j 环境下的 333 页全量数据导入、离线派生关系增强、查询抽样和测试回归验收。它是当前实现状态的证据记录，不代表 HTTP API、Agent Skill、MCP Tool adapter、真实多模态模型供应商或全量自动语义扫描已经完成。

## 验收环境

- 验收日期：2026-08-07
- 工作目录：`C:\Users\40119\Desktop\图块图谱构建`
- 数据根目录：`C:\Users\40119\Desktop\图块图谱构建\data`
- Neo4j Bolt 地址：`bolt://127.0.0.1:7687`
- 验收 project slug：`road-full-20260807-acceptance`
- 规则版本：`full-acceptance-v1`
- 数据规模：333 个 JSON、333 个 PNG
- 图纸册：`lslq_yhd_2_1`、`lslq_yhd_2_2`

真实 Neo4j 密码只通过当前 PowerShell 进程环境变量临时注入，未写入仓库文件或本文档。

## Schema 初始化

执行命令：

```powershell
Get-Content -Encoding UTF8 scripts\create_schema.cypher | cypher-shell -a $env:NEO4J_URI -u $env:NEO4J_USER -p $env:NEO4J_PASSWORD
```

结果：命令退出码为 0。输出包含 Java/Neo4j runtime warning，但无 Cypher 错误。

## 全量导入

执行命令：

```powershell
python scripts\import_json.py all
```

结果：

```text
status: success
batch_id: batch:b3331ea7b6b848a6a3a736a44366b9fa
total_count: 333
success_count: 333
skipped_count: 0
failed_count: 0
warning_count: 0
```

## 离线派生关系增强

执行命令：

```powershell
python scripts\enrich_block_relations.py project --rule-version full-acceptance-v1
```

结果：业务状态为 `partial`，退出码为 1，但 `error_count` 为 0。该结果表示存在业务证据不足或候选歧义，不是程序崩溃。

关键统计：

```text
relation_batch_id: relation-batch:af8ad594-d514-4121-844f-2b7903186098
page_count: 333
block_count: 518
caption_count: 394
basic_info_count: 177
annotation_count: 129
cross_section_count: 164
table_count: 143
table_caption_count: 132
table_caption_relation_count: 132
uses_basic_info_count: 175
candidate_count: 30
ambiguous_count: 15
not_evaluated_count: 48
relation_count: 1290
warning_count: 63
error_count: 0
issue_summary: basic_info_not_evaluated=46, basic_info_partial=2, caption_candidate_ambiguous=15
```

## Neo4j 计数检查

项目主链路：

```text
drawing_sets: 2
pages: 333
```

各图纸册页数：

```text
set:road-full-20260807-acceptance:lslq_yhd_2_1 -> 103
set:road-full-20260807-acceptance:lslq_yhd_2_2 -> 230
```

节点计数：

```text
BlockCaption: 394
CrossSection: 164
DrawingAnnotation: 129
DrawingBasicInfo: 175
DrawingBlock: 518
DrawingPage: 333
DrawingSet: 2
IgnoredElement: 413
PlainText: 124
Project: 1
Table: 143
TableCaption: 132
Title: 14
```

按 `rule_version=full-acceptance-v1` 统计的派生关系：

```text
CANDIDATE_CAPTION_OF: 60
HAS_ANNOTATION: 852
HAS_CAPTION: 992
HAS_SECTION_MARK: 326
USES_BASIC_INFO: 350
```

## CLI 抽样查询

抽样页面和图块：

```text
page_id: page:road-full-20260807-acceptance:lslq_yhd_2_1:road_5
block_id: block:road-full-20260807-acceptance:lslq_yhd_2_1:road_5:16a6f9bdad0c077e
```

`list-drawing-sets` 返回两册，并在修复后正确返回页数：

```text
lslq_yhd_2_1 page_count=103
lslq_yhd_2_2 page_count=230
```

`list-pages` 可返回 `lslq_yhd_2_1` 的前 5 页。

`page-source-facts` 对 `road_5` 返回 4 类来源事实：

```text
DrawingBlock
BlockCaption
DrawingBasicInfo
DrawingAnnotation
```

`block-trace` 对抽样图块返回 project、drawing set、page、page number、image path、bbox、normalized bbox 和 citation ref。

`block-relations` 对抽样图块返回：

```text
relation_status: partial
caption_ids: 1
basic_info_status: confirmed
basic_info_source: current_page
basic_info_ids: 1
annotation_ids: 1
section_mark_ids: 0
candidate_caption_ids: 0
candidate_section_mark_ids: 0
```

## 验收中发现并修复的问题

全量验收发现 `drawing_graph_tool.py list-drawing-sets` 的 `page_count` 错误显示为每册 1。Neo4j 直接计数确认真实页数为 103 和 230。

原因：`QueryService.get_project_sets()` 读取的是 `DrawingSet.page_count` 节点属性；该属性在单页导入时会被写为 1，不适合作为全量图纸册摘要。

修复：`QueryService.get_project_sets()` 改为通过 `DrawingSet -[:HAS_PAGE]-> DrawingPage` 关系执行 `count(DISTINCT page)` 计数。新增测试先红后绿，防止回归。

验证：

```powershell
python -m unittest tests.test_query_project_sets -v
```

结果：5 tests OK。

## 回归测试

普通全量测试：

```powershell
python -m unittest discover tests -v
```

结果：

```text
Ran 529 tests
OK (skipped=3)
```

跳过项为 3 个真实 Neo4j 集成测试，因为该命令未注入 `NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD`。跳过不等于 live Neo4j 通过。

真实 Neo4j 集成测试：

```powershell
python -m unittest discover tests.integration -v
```

结果：

```text
Ran 3 tests
OK
```

三个集成测试均真实执行并通过：基础导入、离线派生关系增强、语义证据和断面匹配写入/查询闭环。

## 验收结论

已验证：

- 333 页全量 JSON/PNG 数据可全部导入 Neo4j，0 跳过、0 失败、0 warning。
- 全量离线派生关系增强可运行到业务 `partial` 状态，0 系统错误。
- Neo4j 中项目主链路、节点规模、派生关系规模与数据规模一致。
- facade CLI 可查询图纸册、页面、页面来源事实、图块追溯和图块关系。
- `list-drawing-sets` 的全量页数投影缺陷已修复并通过测试。
- 普通全量测试和真实 Neo4j 集成测试均通过。

仍未覆盖：

- 未接真实多模态模型供应商。
- 未实现 HTTP API、Agent Skill 或 MCP Tool adapter。
- 未验证正式生产账号、远程 Neo4j、CI 环境或多数据库部署。
- 本轮验收数据未清理，保留 `road-full-20260807-acceptance` 前缀便于 Neo4j Browser 复查。
