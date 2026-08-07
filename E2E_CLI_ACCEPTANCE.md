# 端到端 CLI 验收记录

本文记录一次真实 Neo4j 环境下的端到端 CLI 验收。它是当前实现状态的证据记录，不是目标规划，也不代表 HTTP API、Agent Skill 或 MCP Tool adapter 已完成。

## 验收环境

- 验收日期：2026-08-06
- 工作目录：`C:\Users\40119\Desktop\图块图谱构建`
- Neo4j Browser：`http://localhost:7474/browser/`
- Python/CLI 使用的 Bolt 地址：`bolt://127.0.0.1:7687`
- 验收 project slug：`e2e-cli-20260806172326`
- 临时数据根目录：`.test_tmp\e2e-cli-20260806172326`
- 输入样例：`tests\fixtures\sample_page\road_24.json` 和同目录同名 PNG 副本

真实密码只通过当前 PowerShell 进程环境变量临时注入，未写入仓库文件。Neo4j 中不清理 Neo4j 验收数据，保留 `e2e-cli-20260806172326` 前缀便于 Browser 复查。

## 验收命令链路

初始化 Schema：

```powershell
Get-Content -Encoding UTF8 scripts\create_schema.cypher | cypher-shell -a $env:NEO4J_URI -u $env:NEO4J_USER -p $env:NEO4J_PASSWORD
```

本次实际通过 Python driver 执行同一个 schema 文件，共执行 39 条 statement，状态为 `ok`。

导入单页：

```powershell
python scripts\import_json.py page batch:e2e-cli-20260806172326:manual-001 .test_tmp\e2e-cli-20260806172326\sample_page\road_24.json
```

结果：`status: success`，写入页面 `page:e2e-cli-20260806172326:sample_page:road_24`。

facade CLI 查询图纸册与页面：

```powershell
python scripts\drawing_graph_tool.py list-drawing-sets --project-id project:e2e-cli-20260806172326 --limit 5
python scripts\drawing_graph_tool.py list-pages --drawing-set-id set:e2e-cli-20260806172326:sample_page --limit 5
```

结果：返回 `set:e2e-cli-20260806172326:sample_page`，页面为 `road_24`，并返回图片路径。

facade CLI 查询页面来源事实：

```powershell
python scripts\drawing_graph_tool.py page-source-facts --page-id page:e2e-cli-20260806172326:sample_page:road_24
```

结果：返回 `Title`、`TableCaption`、`Table`、`DrawingBlock` 四类来源事实。验收过程中发现真实 Neo4j factory 未默认注入 source facts reader，已补 `Neo4jPageSourceFactReader` 并接入 `create_neo4j_tool_facade()`。

facade CLI 查询图块追溯与关系：

```powershell
python scripts\drawing_graph_tool.py block-trace --block-id block:e2e-cli-20260806172326:sample_page:road_24:de7259429469c372
python scripts\drawing_graph_tool.py block-relations --block-id block:e2e-cli-20260806172326:sample_page:road_24:de7259429469c372
```

结果：`block-trace` 返回 project、drawing set、page、bbox、normalized bbox、image path 和 citation ref；基础导入后 `block-relations` 为 `relation_status: not_enhanced`。

离线派生关系增强：

```powershell
python scripts\enrich_block_relations.py page page:e2e-cli-20260806172326:sample_page:road_24 --rule-version e2e-cli-v1
```

结果：业务状态为 `partial`。这是样例页数据预期内结果：`table_caption_relation_count: 1`，同时因为页面没有 basic info，记录 `basic_info_not_evaluated`，所以增强 CLI 返回非零退出码。该结果证明表格标题派生关系写入成功，也证明缺失业务证据不会被伪装成完整增强。

语义证据和候选/正式断面关系成功路径：

本次验收在同一 project 下种入最小语义证据和断面候选/正式关系，用于验证 CLI 查询成功路径。写入内容包括：

- `TextObservation`：CrossSection 与 BlockCaption 各一条，状态 `confirmed`
- `BlockInterpretation`：一条 block 解释，状态 `partial`
- `CANDIDATE_HAS_SECTION_MARK`
- `CANDIDATE_MATCHES_SECTION_CAPTION`
- `MATCHES_SECTION_CAPTION`

CLI 查询命令：

```powershell
python scripts\drawing_graph_tool.py list-text-observations --page-id page:e2e-cli-20260806172326:sample_page:road_24 --status confirmed
python scripts\drawing_graph_tool.py list-interpretations --page-id page:e2e-cli-20260806172326:sample_page:road_24 --status partial
python scripts\drawing_graph_tool.py list-candidate-relations --block-id block:e2e-cli-20260806172326:sample_page:road_24:de7259429469c372 --relation-type candidate_section_mark --status candidate
python scripts\drawing_graph_tool.py list-section-matches --cross-section-id element:e2e-cli-20260806172326:sample_page:road_24:cross_e2e --status candidate --status confirmed
```

结果：

- `list-text-observations` 返回 2 条 `semantic_observation`
- `list-interpretations` 返回 1 条 `semantic_interpretation`
- `list-candidate-relations` 返回 1 条 `candidate_section_mark`
- `list-section-matches` 返回 1 条 `candidate_relation` 和 1 条 `formal_relation`

验收过程中还发现 `section matches were not found` 被错误清洗为低层敏感错误，原因是 CLI 错误清洗规则把普通单词 `matches` 误判为低层 `MATCH` 细节；已收窄为只清洗 password、secret、cypher 等真实敏感或低层词。

## 验收结论

已验证的真实链路：

- Schema 初始化
- 单页来源事实导入
- 图纸册、页面、页面来源事实、图块追溯、图块关系查询
- 离线派生关系增强的业务状态和 table caption 关系写入
- 语义 observation 查询
- interpretation 查询
- candidate relation 查询
- section match candidate/formal 查询
- CLI JSON 输出和结构化错误输出

仍未覆盖的边界：

- 未做全量 333 页数据导入验收
- 未接真实多模态模型供应商
- 未实现 HTTP API、Agent Skill 或 MCP Tool adapter
- 未验证正式生产账号、远程 Neo4j、CI 环境或多数据库部署
- 未清理 `e2e-cli-20260806172326` 验收数据

## 回归验证

验收和修复后执行：

```powershell
python -m unittest discover tests
```

结果：`Ran 526 tests`，`OK (skipped=3)`。

临时注入 live Neo4j 测试环境变量后执行：

```powershell
python -m unittest discover tests
```

结果：`Ran 526 tests`，`OK`。
