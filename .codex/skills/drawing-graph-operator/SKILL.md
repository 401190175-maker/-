---
name: drawing-graph-operator
description: >-
  Project-operation skill for the 图块图谱构建 drawing-graph workspace. Use when
  the user asks to analyze, query, maintain, or extend the drawing graph, or
  mentions 图块图谱, DrawingGraphToolFacade, Neo4j 图纸图谱, 候选关系,
  语义证据层, 断面匹配, or write_back. The skill defines the safe operation
  workflow: read current project docs and affected source before acting; use
  project capabilities only through DrawingGraphToolFacade,
  create_neo4j_tool_facade(), or scripts/drawing_graph_tool.py; default to
  write_back=false; keep candidate relations distinct from formal facts; keep
  source facts, derived relations, semantic evidence, and verification status
  honestly separated in every answer.
---

# Drawing Graph Operator

## 用途

本 Skill 是本项目（图块图谱构建）的操作型 Skill：指导 Codex 如何安全地分析、查询、维护和扩展图块图谱，不封装真实数据、不保存密钥、不替代业务源码、`DrawingGraphToolFacade`、MCP Tool adapter、HTTP API 或文件 watcher。

## 核心工作流

处理本项目相关请求时，按以下顺序执行：

1. **先读当前文件，再行动。** 行动前先读取项目根目录的 `README.md`、`Module.md`、`architecture.md` 以及受影响源码和测试；不要依赖旧记忆或旧结论替代当前文件状态。
2. **只经由受控入口使用项目能力。** 项目图谱能力只能通过 `DrawingGraphToolFacade`、`create_neo4j_tool_facade()` 或薄 CLI adapter `scripts/drawing_graph_tool.py` 使用。禁止直接创建 Neo4j driver、拼写或执行 Cypher、调用底层 repository 写回方法或运行规则函数。
3. **默认 `write_back=false`。** 查询默认只读，语义识别默认 dry-run。没有用户明确授权、环境确认和验证计划时，不写数据库、不持久化语义证据、不提升候选关系。
4. **分层输出事实。** 回答必须区分来源事实、派生关系、语义观察、语义解释、候选关系与正式关系；候选关系不是正式事实，`matched_candidate` 不等于正式图谱关系。
5. **如实报告验证状态。** 单元测试、集成测试、live Neo4j 验证分开报告；集成测试跳过不等于 live Neo4j 已通过。

## 按需读取 references

以下 reference 文件按需读取，不要一次性全部载入：

| 触发场景 | 读取文件 |
|---|---|
| 需要确认架构边界、已实现/未实现范围或禁止事项 | `references/project-boundaries.md` |
| 需要执行只读查询、dry-run、候选查看或候选复核 | `references/facade-workflows.md` |
| 需要运行测试、配置集成测试环境或报告验证状态 | `references/verification.md` |
| 需要组织图谱查询回答的事实分层和证据字段 | `references/output-contract.md` |

## 禁止事项

- 不直接创建 Neo4j driver、不直接写 Cypher、不直接调用 repository 写回方法、不直接调用 `block_relation_enrichment.py` 规则函数。
- 不把候选关系、`matched_candidate` 或模型观察写成正式事实或来源事实。
- 不把 `RecognitionRun` 与图谱内语义证据混为一谈：run log 在图谱外，`TextObservation`/`Interpretation` 在图谱内，二者只通过 `recognition_run_id` 关联。
- 不封装 `data/`、真实 JSON/PNG、Neo4j 数据、密钥或 `.env` 到本 Skill。
- 不保存密钥：Skill 资产中不出现 Neo4j 密码、供应商 API key、token 或 `.env` 的真实值。
- 不把 skipped 集成测试报告为 live Neo4j 通过。
