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

本 Skill 是本项目（图块图谱构建）的操作策略层 Skill：指导 Codex 如何安全地分析、查询、维护和扩展图块图谱，不封装真实数据、不保存密钥、不替代业务源码、`DrawingGraphToolFacade`、MCP Tool adapter、HTTP API 或文件 watcher，也不声称自己是 MCP server、业务服务或数据库接口。

## 核心工作流

处理本项目相关请求时，按以下顺序执行：

1. **先读当前文件，再行动。** 行动前先读取项目根目录的 `README.md`、`Module.md`、`architecture.md` 以及受影响源码和测试；不要依赖旧记忆或旧结论替代当前文件状态。
2. **MCP 优先：优先选择已配置的 MCP 工具。** 固定 QA 问题按 `references/qa-workflows.md` 路由到六个只读 MCP QA 工具；产品级自然语言问答测试按 `references/product-test-workflows.md` 路由到产品只读 MCP 工具 `ask_drawing_assistant`。MCP 不可用时按 `references/mcp-boundaries.md` 透明降级到受控 CLI。禁止静默降级或冒充 MCP 已验证。
3. **只经由受控入口使用项目能力。** 项目图谱能力只能通过 `DrawingGraphToolFacade`、`create_neo4j_tool_facade()` 或薄 CLI adapter `scripts/drawing_graph_tool.py` 使用。禁止直接创建 Neo4j driver、拼写或执行 Cypher、调用底层 repository 写回方法或运行规则函数。
4. **默认 `write_back=false`。** 查询默认只读，语义识别默认 dry-run。没有用户明确授权、环境确认和验证计划时，不写数据库、不持久化语义证据、不提升候选关系。
5. **分层输出事实。** 回答必须区分来源事实、派生关系、语义观察、语义解释、候选关系与正式关系；候选关系不是正式事实，`matched_candidate` 不等于正式图谱关系。
6. **如实报告验证状态。** 单元测试、集成测试、live Neo4j 验证分开报告；集成测试跳过不等于 live Neo4j 已通过。

## 前置门与失败封闭（强制执行）

任何请求的第一步动作固定为“前置门”，完成后才能进入查询、识别或回答：

1. **读取当前文档**：README.md、Module.md、architecture.md 及本次请求影响的源码与测试（skill references 按需渐进读取）。
2. **运行前置检查**：执行 `python scripts\skill_preflight.py`，完整引用其 JSON 输出作为“前置门报告”；脚本只读，不输出任何密钥。
3. **按报告选择入口**，只允许三类：
   - MCP 可用 → 按 `references/qa-workflows.md` / `references/product-test-workflows.md` 使用 MCP；
   - MCP 不可用但 Neo4j 环境齐全且连接成功 → 按 `references/mcp-boundaries.md` 透明降级到受控 CLI；
   - 其余情况 → 进入失败封闭（下一条）。
4. **失败封闭**：所有受控入口不可用时，禁止继续执行查询、识别或任何替代识别手段；必须按 `references/blocked-path.md` 输出 BLOCKED 报告并询问用户。只有用户明确授权后，才可执行授权范围内的兜底方案。
5. **禁止兜底清单**（未获用户明确授权一律不得使用）：
   - 本地 OCR（Tesseract、Windows OCR、PaddleOCR、EasyOCR 等）；
   - 用图像查看/视觉工具代替项目识别能力；
   - 第三方识别 API 或未列入受控入口的任何识别通道；
   - 直接读取 PNG 猜测文字、直接写 Cypher、直接创建 Neo4j driver、直接调用 repository 写回方法。
6. 写回默认 `write_back=false`；所有回答按 `references/output-contract.md` 分层并如实标注验证状态；BLOCKED、兜底、降级结果一律不得冒充 MCP 已验证。

配置来源说明：preflight 与受控 CLI 均从当前进程环境变量读取配置；本机配置可存放在已 gitignore 的 `.env` 文件，使用前需先加载到当前会话（加载方法见 README「2.1 首次运行配置清单」），不要把 `.env` 内容复制到任何会提交的文件或日志。

## 按需读取 references

以下 reference 文件按需读取（渐进披露），不要一次性全部载入：

| 触发场景 | 读取文件 |
|---|---|
| 需要确认架构边界、已实现/未实现范围或禁止事项 | `references/project-boundaries.md` |
| 需要执行只读查询、dry-run、候选查看或候选复核 | `references/facade-workflows.md` |
| 需要运行测试、配置集成测试环境或报告验证状态 | `references/verification.md` |
| 需要组织图谱查询回答的事实分层和证据字段 | `references/output-contract.md` |
| 需要把自然语言问题路由到 MCP QA 工具或组合多意图 | `references/qa-workflows.md` |
| 需要用产品级自然语言问答入口测试 `DrawingAssistantService.answer()`、产品 CLI/HTTP/MCP adapter 或三入口一致性 | `references/product-test-workflows.md` |
| 需要判断 MCP 不可用、超时、降级或禁止调用链 | `references/mcp-boundaries.md` |
| 所有受控入口不可用、需要输出 BLOCKED 报告或请求授权 | `references/blocked-path.md` |

## 禁止事项

- 不直接创建 Neo4j driver、不直接写 Cypher、不直接调用 repository 写回方法、不直接调用 `block_relation_enrichment.py` 规则函数。
- 不把候选关系、`matched_candidate` 或模型观察写成正式事实或来源事实。
- 不把 `RecognitionRun` 与图谱内语义证据混为一谈：run log 在图谱外，`TextObservation`/`Interpretation` 在图谱内，二者只通过 `recognition_run_id` 关联。
- 不静默降级：MCP 不可用时必须按 `mcp-boundaries.md` 明确说明后降级到 QA CLI，不冒充 MCP 已验证。
- 不封装 `data/`、真实 JSON/PNG、Neo4j 数据、密钥或 `.env` 到本 Skill。
- 不保存密钥：Skill 资产中不出现 Neo4j 密码、供应商 API key、token 或 `.env` 的真实值。
- 不把 skipped 集成测试报告为 live Neo4j 通过。
