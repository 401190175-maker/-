# Skill 封装功能分析报告

## 0. 分析范围与输入文件

本报告分析“进行 Skill 的封装”这一新需求，只做架构、模块、方案和风险分析，不写业务代码，不修改 `src/`、`scripts/`、Schema、测试或 `data/`。

已读取和核对的输入：

- `architecture.md`
- `Module.md`
- `README.md`
- `图块图谱方案.md`
- `changes/tool-facade/Feature_Analysis_Report.md`
- `changes/语义证据层/Feature_Analysis_Report.md`

文件名说明：

- 用户要求读取 `modules.md`，仓库当前实际文件名为 `Module.md`，本报告按实际文件读取。
- 本需求中的 Skill 指 Codex Skill，即让后续 Codex 会话按项目规则使用现有图块图谱能力的“操作手册 + 工作流 + 约束包”，不是把图谱数据、Neo4j 数据库、源码业务逻辑或模型能力打包进 Skill。

当前实现边界：

- 已落地：基础导入、离线派生关系增强、候选关系复核骨架、只读查询、语义证据层应用边界、`DrawingGraphToolFacade`、薄 CLI adapter `scripts/drawing_graph_tool.py`。
- 未落地：Agent Skill、MCP Tool adapter、HTTP/REST API、文件 watcher、全量自动语义扫描、默认真实云多模态供应商调用。
- 本报告不把 Skill 封装描述为已完成能力，也不建议在 Skill 中封装真实 `data/` 数据、Neo4j 密码、供应商 API key 或项目私有数据。

## 1. 当前架构是否支持？

结论：当前架构支持进行轻量 Skill 封装，而且封装时机已经基本成熟；但支持方式应是“Skill 编排现有 facade 和文档约束”，不是让 Skill 直接调用 Neo4j、直接运行底层脚本、复制数据或实现新的业务逻辑。

### 1.1 已经支持的基础

| 支持点 | 当前依据 | 对 Skill 封装的意义 |
|---|---|---|
| 应用门面已存在 | `Module.md` 记录 `DrawingGraphToolFacade`、`tool_models.py`、`tool_factory.py`、`scripts/drawing_graph_tool.py` | Skill 可以把 facade 作为唯一推荐调用边界 |
| 查询与证据输出边界清楚 | `README.md` 记录 facade 查询命令和 DTO 输出；`architecture.md` 强调稳定业务 ID、bbox、来源事实、候选和正式关系区分 | Skill 可以指导 Codex 输出可追溯答案 |
| 默认安全边界明确 | `architecture.md`、`README.md` 和 `Module.md` 均强调 `write_back=false` 默认 dry-run | Skill 可以把 `write_back=false` 固化为默认规则 |
| 候选关系机制明确 | 文档明确候选关系不是正式事实，提升必须经过 `CandidateReviewService` 和硬规则 | Skill 可以防止后续 Agent 把 candidate 当 fact |
| 语义证据层边界明确 | `RecognitionRun` 图谱外、`TextObservation` 图谱内、`Interpretation` 图谱内、`payload_ref` 不可变产物 | Skill 可以规定回答时区分来源事实、模型观察、结构化解释和候选关系 |
| 当前非目标清楚 | 文档明确当前仍不包含 Agent Skill、HTTP API、MCP Tool adapter、全量自动语义扫描 | Skill 分析阶段不会误把后续集成当现状 |

### 1.2 仍不支持或不能由 Skill 解决的部分

| 缺口 | 当前判断 | 对 Skill 的影响 |
|---|---|---|
| 没有已安装项目专用 Skill | 仓库没有 `changes/skill封装` 下的 Skill 设计或实现；当前也未看到项目专用 Codex Skill 成品 | 本需求第一步应先做 Skill 分析和设计，不应直接宣称可用 |
| Skill 不是实时触发器 | Skill 不会监听 `data/` 目录，也不会因文件放入自动导入 | 若需要自动导入，需要 watcher、计划任务或外部编排，不属于 Skill 本身 |
| Skill 不是 Tool adapter | Skill 只能指导 Codex 如何工作，不能天然提供稳定机器接口 | 若要给其他系统调用，应另做 MCP Tool adapter 或 HTTP/API |
| Skill 不能内置真实数据 | `data/` 包含真实 JSON/PNG 和项目数据，不应复制到 Skill | Skill 只放 toy example 或路径规则，不封装真实数据 |
| Skill 不能绕过环境配置 | Neo4j 连接、模型供应商、测试库仍需外部环境变量和权限 | Skill 只能规定检查步骤和安全边界，不能携带密钥 |

因此，当前架构对“轻量 Codex Skill”是支持的；对“自动化平台能力”只支持到 facade/CLI 这一层，仍需要后续 Tool adapter 或外部触发系统。

## 2. 需要新增哪些模块？

本需求如果只做 Skill 封装，原则上不需要新增 Python 业务模块。需要新增的是 Skill 资产和项目侧变更说明文档。

### 2.1 推荐新增的 Skill 资产

| 模块或文件 | 建议位置 | 职责 |
|---|---|---|
| `SKILL.md` | `C:\Users\40119\.codex\skills\drawing-graph-operator\SKILL.md`，或仓库内 `.codex/skills/drawing-graph-operator/SKILL.md` | 定义 Skill 名称、触发场景、工作流、禁止事项和默认安全边界 |
| `agents/openai.yaml` | Skill 目录下 `agents/openai.yaml` | Codex UI 展示元数据，包含 display name、short description、default prompt |
| `references/project-boundaries.md` | Skill 目录下 `references/` | 记录三层架构、当前已实现/未实现边界、`write_back=false`、候选关系不是事实 |
| `references/facade-workflows.md` | Skill 目录下 `references/` | 记录通过 `DrawingGraphToolFacade` 或 `scripts/drawing_graph_tool.py` 查询、dry-run、审核候选的推荐流程 |
| `references/verification.md` | Skill 目录下 `references/` | 记录单元测试、集成测试、Neo4j live 验证和“跳过不等于通过”的报告规范 |
| `references/output-contract.md` | Skill 目录下 `references/` | 规定回答时必须区分 `source_fact`、`derived_relation`、`semantic_observation`、`semantic_interpretation`、`candidate_relation`、`formal_relation` |

说明：这些是 Skill 资源，不是项目业务源码模块。第一版建议只放 `SKILL.md`、`agents/openai.yaml` 和 2 到 4 个 `references/*.md`。暂不建议放 `scripts/`，除非后续出现稳定、反复重写且需要确定性执行的小工具。

### 2.2 可选新增的项目规划文件

| 文件 | 建议位置 | 职责 |
|---|---|---|
| `changes/skill封装/proposal.md` | 项目变更目录 | 描述 Skill 封装需求、范围和非目标 |
| `changes/skill封装/design.md` | 项目变更目录 | 描述 Skill 文件结构、触发规则、引用文档和 facade 调用边界 |
| `changes/skill封装/tasks.md` | 项目变更目录 | 如进入实现阶段，再拆成可独立验证的小任务 |

本次用户只要求输出 `Feature_Analysis_Report.md`，因此以上文件不是当前必须新增项。

### 2.3 不建议新增的内容

| 不建议新增 | 原因 |
|---|---|
| 复制 `data/` 到 Skill | 数据体积大、隐私和路径耦合风险高，且 Skill 不应作为数据包 |
| 在 Skill 中保存 Neo4j 密码或 API key | 违反安全边界，也会让 Skill 不可移植 |
| 在 Skill 中重写导入、增强、查询脚本 | 业务逻辑应留在仓库源码和 facade；Skill 只指导调用 |
| 在 Skill 中放完整 README、CHANGELOG、安装指南 | Skill 应精简，避免上下文膨胀 |
| 在 Skill 中直接写 Cypher 模板 | 既有架构要求 adapter/facade 不暴露 Cypher，Skill 更不应绕过 |

## 3. 影响哪些已有模块？

### 3.1 对源码模块的影响

| 已有模块 | 影响等级 | 说明 |
|---|---:|---|
| `src/drawing_graph/tool_facade.py` | 中 | Skill 会把它作为推荐应用边界，但第一版不需要修改源码 |
| `src/drawing_graph/tool_factory.py` | 低到中 | Skill 会说明工厂创建时不连接 Neo4j、不扫描数据、不接收密钥；是否需要补充 helper 以后再判断 |
| `scripts/drawing_graph_tool.py` | 中 | Skill 可把薄 CLI adapter 作为人工可运行的 facade 调用入口；第一版不修改 |
| `src/drawing_graph/query_service.py` / `query_port_adapter.py` | 低 | Skill 只引用其查询能力，不直接暴露给 Agent |
| `src/drawing_graph/semantic_*` | 低到中 | Skill 会描述语义证据查询、dry-run 和 write-back 边界；不新增模型调用能力 |
| `src/drawing_graph/relation_repository.py` / `candidate_review.py` | 低到中 | Skill 会强调候选审核和硬规则，不直接调用底层写回接口 |
| `scripts/import_json.py` / `scripts/enrich_block_relations.py` / `scripts/review_candidate_relations.py` | 低 | Skill 可记录显式流程，但不把它们变成自动工作流 |

第一版 Skill 封装不应要求修改上述源码。只有当实现阶段发现 CLI 输出、facade 入参或错误分类不利于 Skill 稳定调用时，才另开代码任务。

### 3.2 对文档和测试的影响

| 文件或目录 | 影响等级 | 建议 |
|---|---:|---|
| `architecture.md` | 低 | Skill 完成后可补一句“Agent Skill 已作为外部操作层存在”，但不能把它写成 HTTP/MCP |
| `Module.md` | 中 | 若 Skill 放在仓库内或作为项目资产维护，应记录 Skill 目录职责；若放在用户级 Codex 技能目录，可只在变更文档中记录 |
| `README.md` | 中 | 可补充“如何用 Codex Skill 操作项目”的入口说明，但不在本分析阶段修改 |
| `tests/` | 低 | 不建议删除；Skill 封装后仍依赖测试证明 facade 边界未被破坏 |
| `tests/test_planning_docs.py` | 中 | 既有测试依赖根目录规划文档，不能因为 Skill 封装清理文档而误删 |
| `data/` | 无代码影响 | 不进入 Skill；只作为外部运行数据路径 |

## 4. 技术方案有哪些？

### 4.1 方案 A：纯文档型 Skill

做法：

- 创建一个 Codex Skill，只包含 `SKILL.md` 和少量 `references/*.md`。
- Skill 说明如何读取项目文档、如何使用 facade、如何判断验证状态。
- 不包含脚本、不包含真实数据、不修改项目源码。

适用场景：

- 当前目标是让后续 Codex 会话稳定遵守项目边界。
- 还不需要机器到机器的 Tool 调用。

### 4.2 方案 B：项目操作型 Skill，引用 facade 与 CLI

做法：

- 在方案 A 基础上，把 `scripts/drawing_graph_tool.py` 的已落地命令作为推荐操作入口。
- Skill 按任务类型给出固定流程：只读查询、dry-run 识别、候选关系查看、候选复核、测试验证。
- 仍不复制数据、不保存密钥、不直接写 Cypher。

适用场景：

- 希望 Skill 不只是“原则说明”，还能指导 Codex 执行具体项目任务。
- 需要让后续会话知道先走 `DrawingGraphToolFacade`，再按需走 CLI adapter。

### 4.3 方案 C：带确定性辅助脚本的 Skill

做法：

- 在方案 B 基础上增加 Skill 自带 `scripts/`，例如检查文档边界、扫描敏感词、生成小型 dry-run 命令模板。
- 这些脚本只能做静态检查或命令生成，不应连接 Neo4j 或写数据。

适用场景：

- 后续发现 Codex 反复写错同类检查逻辑。
- 需要更稳定的技能验证工具。

### 4.4 方案 D：MCP Tool adapter 或 HTTP/API

做法：

- 基于 `DrawingGraphToolFacade` 实现真正的外部 Tool adapter。
- 让外部 Agent 或系统通过标准协议调用查询、dry-run、候选审核能力。

适用场景：

- 需要跨应用稳定调用。
- 需要让非 Codex 客户端使用图谱能力。

说明：这不是 Codex Skill 封装本身，而是后续独立工程。当前不建议和 Skill 第一版合并。

## 5. 优缺点比较

| 维度 | 方案 A：纯文档型 Skill | 方案 B：项目操作型 Skill | 方案 C：带辅助脚本 Skill | 方案 D：MCP/HTTP Tool |
|---|---|---|---|---|
| 改动量 | 最小 | 小 | 小到中 | 中到大 |
| 对源码影响 | 无 | 无或极小 | 无或极小 | 可能新增 adapter |
| 可复用性 | 中 | 高 | 高 | 很高 |
| 操作确定性 | 中 | 高 | 更高 | 最高 |
| 安全风险 | 低 | 低 | 中 | 中到高 |
| 是否适合当前阶段 | 可行 | 最推荐 | 后置 | 后置 |
| 是否封装数据 | 不封装 | 不封装 | 不封装 | 不封装 |
| 是否解决自动监听 | 不解决 | 不解决 | 不解决 | 仍需外部 watcher |

## 6. 推荐方案

推荐采用方案 B：项目操作型 Skill，引用现有 facade 与薄 CLI adapter。

推荐理由：

1. 当前 `DrawingGraphToolFacade` 已经是稳定应用边界。Skill 应位于它的外侧，作为 Codex 的操作规范，而不是重新实现业务逻辑。
2. Skill 第一版应解决“后续会话如何正确使用项目”的问题：读取哪些文档、走哪个入口、默认 dry-run、如何报告验证状态、如何避免把候选关系当事实。
3. 方案 B 不需要改源码，不需要移动或删除 `data/`，也不需要清理 `tests/`。它符合当前“不要写代码”的收口方向。
4. 方案 B 能为未来 MCP Tool adapter 留出清晰边界：Skill 是人机协作工作流，MCP/HTTP 是机器接口，两者不混淆。
5. Skill 可以轻量沉淀项目规则，避免每次新会话重新解释 `RecognitionRun` 图谱外、`TextObservation` 图谱内、`write_back=false` 和 live Neo4j 未验证边界。

推荐的 Skill 第一版结构：

```text
drawing-graph-operator/
  SKILL.md
  agents/
    openai.yaml
  references/
    project-boundaries.md
    facade-workflows.md
    verification.md
    output-contract.md
```

推荐的触发场景：

- 用户要求分析、查询、维护或扩展 `C:\Users\40119\Desktop\图块图谱构建`。
- 用户提到图块图谱、DrawingGraphToolFacade、Neo4j 图纸图谱、候选关系、语义证据层、断面匹配、write_back。
- 用户要求 Codex 使用该项目回答图纸来源事实、空间派生关系、语义观察或候选复核问题。

推荐的 Skill 核心规则：

- 先读取当前项目文档和受影响源码，再行动。
- 默认 `write_back=false`；没有明确授权不写数据库。
- 只通过 `DrawingGraphToolFacade`、`create_neo4j_tool_facade()` 或 `scripts/drawing_graph_tool.py` 进入工具能力。
- 不让 Skill 直接写 Cypher、创建 Neo4j driver、调用底层 repository 写回、调用导入或增强规则函数。
- 区分来源事实、派生关系、语义观察、结构化解释、候选关系和正式关系。
- 候选关系不是事实，`matched_candidate` 不是正式图谱关系。
- `RecognitionRun` 是图谱外日志，`TextObservation` 是图谱内证据。
- `data/`、真实 PNG/JSON、Neo4j 数据库和密钥不进入 Skill。
- 未设置 `NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD` 时，集成测试跳过不能报告为 live Neo4j 通过。

推荐实施顺序：

| 阶段 | 目标 | 输出 |
|---|---|---|
| 阶段 1：Skill 需求确认 | 明确 Skill 做什么、不做什么、放在哪里 | `changes/skill封装/proposal.md` 或直接进入设计 |
| 阶段 2：Skill 结构设计 | 确定 `SKILL.md`、`agents/openai.yaml`、references 文件 | `changes/skill封装/design.md` |
| 阶段 3：Skill 创建 | 用 skill-creator 流程创建 Skill 文件 | 用户级或仓库级 Skill 目录 |
| 阶段 4：Skill 验证 | 运行 quick validation，使用 2 到 3 个真实提示词试用 | 验证记录和必要修订 |
| 阶段 5：项目文档同步 | 若 Skill 确认为项目资产，同步 README/Module 边界 | 文档更新和测试 |

当前只完成阶段 0 的分析报告，不进入 Skill 创建。

## 7. 风险

### 7.1 高风险

| 风险 | 说明 | 缓解 |
|---|---|---|
| Skill 绕过 facade | 如果 Skill 指导 Codex 直接调用 Repository、写 Cypher 或运行底层规则函数，会破坏现有架构边界 | Skill 明确依赖方向：Skill -> `DrawingGraphToolFacade` -> ports/services -> repository |
| 把候选关系当正式事实 | 后续 Agent 容易把 `CANDIDATE_*`、`matched_candidate` 或模型观察写成确定答案 | 输出契约强制标注 fact kind；候选提升必须经过硬规则和显式复核 |
| `write_back=false` 失效 | Skill 如果默认写入语义证据或审核结果，会制造不可控数据库副作用 | 默认 dry-run；只有用户明确要求且环境确认后才允许 `write_back=true` |
| 把真实数据封装进 Skill | 复制 `data/`、PNG、JSON 或 Neo4j 导出会带来体积、隐私、路径和版本风险 | Skill 只放 toy example 和路径规则；真实数据留在项目外部运行环境 |
| 把 Skill 当自动化平台 | Skill 不会监听文件，也不是任务调度器或 API 服务 | 文档中明确 watcher、MCP、HTTP/API 是后续独立工程 |

### 7.2 中风险

| 风险 | 说明 | 缓解 |
|---|---|---|
| Skill 内容过重 | 复制大量 README、架构全文和任务历史会占用上下文，降低触发后的可用空间 | `SKILL.md` 保持短，详细内容放 references，并按需读取 |
| 文档状态漂移 | 项目源码、README、Module 和 Skill references 可能不一致 | Skill 要求行动前读取当前项目文档；每次架构变化后同步 references |
| Skill 触发过宽 | 描述写得太泛会导致无关 CAD/Neo4j 问题也触发 | description 精确限定到本项目、图块图谱、facade、候选关系、语义证据层 |
| 放置位置选择错误 | 用户级 Skill 自动发现方便，但与项目版本绑定弱；仓库级 Skill 便携，但可能需要 Codex 发现配置 | 先确认目标：个人长期使用推荐用户级；项目随仓库迁移推荐仓库级 |
| Windows 中文路径问题 | Skill 中若命令引用中文路径，可能出现编码或转义问题 | references 中统一给 PowerShell `-LiteralPath` 和 UTF8 读取约定 |
| 验证结果误报 | 单元测试通过但集成测试跳过，容易被说成全部通过 | Skill 中固定写明 skipped != live verified |

### 7.3 低风险

| 风险 | 说明 | 缓解 |
|---|---|---|
| Skill 与 README 内容重复 | 部分使用流程会和 README 重叠 | Skill 只保留操作决策规则，具体命令引用 README 或 workflow reference |
| Skill 名称不稳定 | 名称影响触发和维护 | 推荐 `drawing-graph-operator`，短且动作导向 |
| 后续需要辅助脚本 | 第一版无脚本可能无法自动检查某些边界 | 先观察真实使用，反复出现的检查再进入方案 C |

## 8. 最终结论

当前架构支持 Skill 封装，且推荐作为下一步轻量收口工作。Skill 不应包含 `data/`、Neo4j 数据、真实图纸、密钥或业务源码；它应封装的是 Codex 使用本项目时必须遵守的工作流、架构边界、调用入口、输出契约和验证纪律。

推荐方案是“项目操作型 Skill”：

```text
Codex Skill
  -> DrawingGraphToolFacade / scripts/drawing_graph_tool.py
  -> query/source-fact read port
  -> semantic service / run log / semantic repository
  -> candidate review service
  -> controlled repository / Neo4j
```

第一版 Skill 应聚焦：

1. 读取当前文档和源码再行动。
2. 默认 `write_back=false`。
3. 只经由 facade 或薄 CLI adapter 使用能力。
4. 严格区分来源事实、派生关系、语义证据、候选关系和正式关系。
5. 不封装真实数据，不保存密钥，不宣称跳过的集成测试为通过。

本需求当前只完成分析报告。若进入下一步，建议先创建 `changes/skill封装/design.md` 和 `tasks.md`，再用 `skill-creator` 流程生成 `drawing-graph-operator` Skill。
