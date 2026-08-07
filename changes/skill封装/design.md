# Skill 封装设计

本设计基于 `changes/skill封装/Feature_Analysis_Report.md`，目标是把当前图块图谱项目的 Codex 使用规则封装为一个轻量、可复用、边界清晰的 Skill。该 Skill 只作为 Codex 操作本项目的工作流和约束入口，不封装真实数据、不保存密钥、不重写业务逻辑，也不替代 `DrawingGraphToolFacade`、MCP Tool adapter、HTTP API 或外部自动化触发器。

## 1. 背景

当前项目已经形成较完整的图块图谱底座：基础导入、离线派生关系增强、候选关系复核骨架、语义证据层应用边界、只读查询、`DrawingGraphToolFacade` 和薄 CLI adapter `scripts/drawing_graph_tool.py` 均已落地。项目文档也已经反复确认三层架构边界：

```text
来源事实层
  -> 空间与上下文派生关系层
  -> 语义证据层
  -> 统一查询输出
```

当前适合新增的不是新的图谱业务逻辑，而是一个外层 Codex Skill，用来让后续 Codex 会话稳定遵守本项目的操作规则。Skill 的职责是指导 Codex 如何读取项目文档、如何通过 facade 或薄 CLI adapter 使用图谱能力、如何保持 `write_back=false` 默认安全边界、如何报告验证状态，以及如何区分来源事实、派生关系、语义证据、候选关系和正式关系。

Skill 的推荐定位是“项目操作型 Skill”：它位于 `DrawingGraphToolFacade` 外侧，作为 Codex 的专业工作流和约束包；业务能力仍由项目源码、facade、port、service 和 repository 承担。

## 2. 当前问题

当前项目虽然已经具备 facade 和查询/语义证据边界，但后续 Codex 会话如果没有固定 Skill 约束，仍可能出现以下问题：

| 问题 | 说明 | 后果 |
|---|---|---|
| 项目边界需要反复解释 | 每次新会话都需要重新说明 `write_back=false`、候选关系不是事实、`RecognitionRun` 图谱外等规则 | 容易遗漏关键安全边界 |
| Skill、Tool adapter、HTTP API 容易混淆 | Skill 是 Codex 工作流，Tool adapter/API 是机器接口，watcher 是外部触发器 | 可能把 Skill 误设计成自动化平台 |
| 可能绕过 facade | Codex 可能直接调用 Repository、拼 Cypher、运行底层规则函数或直接创建 Neo4j driver | 破坏既有架构依赖方向和写回安全 |
| 候选关系可能被误报为正式事实 | `CANDIDATE_*`、`matched_candidate`、模型观察可能被写成确定答案 | 后续问答和数据写回会污染事实层 |
| 验证状态可能误报 | 集成测试跳过时容易被写成 live Neo4j 通过 | 项目验证可信度下降 |
| 真实数据可能被误封装 | `data/`、PNG/JSON、Neo4j 数据、密钥或供应商 API key 不应进入 Skill | 带来体积、隐私、路径耦合和安全风险 |

因此，本次 Skill 封装的核心问题不是“实现更多图谱能力”，而是把已有能力的正确使用方式沉淀为可触发、可复用、可验证的 Codex Skill。

## 3. 功能目标

本变更目标是设计并后续创建一个项目专用 Codex Skill，建议名称为 `drawing-graph-operator`。该 Skill 应支持以下目标：

1. 明确触发场景：当用户要求分析、查询、维护或扩展 `C:\Users\40119\Desktop\图块图谱构建`，或提到图块图谱、`DrawingGraphToolFacade`、Neo4j 图纸图谱、候选关系、语义证据层、断面匹配、`write_back` 时，Codex 应使用该 Skill。
2. 固化读取顺序：Codex 行动前应优先读取当前项目文档和受影响源码，不依赖旧记忆替代当前文件状态。
3. 固化调用边界：Skill 只指导 Codex 通过 `DrawingGraphToolFacade`、`create_neo4j_tool_facade()` 或 `scripts/drawing_graph_tool.py` 使用项目能力。
4. 固化写回安全：默认 `write_back=false`；没有用户明确授权、环境确认和验证计划时，不写数据库、不持久化语义证据、不提升候选关系。
5. 固化事实分层：输出必须区分 `source_fact`、`derived_relation`、`semantic_observation`、`semantic_interpretation`、`candidate_relation` 和 `formal_relation`。
6. 固化候选规则：候选关系不是正式事实，`matched_candidate` 也不等于正式图谱关系；提升正式关系必须经过显式复核和硬规则。
7. 固化语义证据边界：`RecognitionRun` 是图谱外运行日志，`TextObservation` 和各类 `Interpretation` 是图谱内语义证据，二者通过 `recognition_run_id` 关联。
8. 固化验证报告：单元测试、集成测试、live Neo4j 验证必须分开报告；集成测试因环境变量缺失被跳过时，不能声称 live Neo4j 已通过。
9. 保持 Skill 精简：`SKILL.md` 只保留核心流程和入口说明，详细边界放入 `references/`，避免把完整项目文档复制进 Skill。

推荐 Skill 第一版结构：

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

其中：

| 文件 | 职责 |
|---|---|
| `SKILL.md` | 定义 Skill 名称、触发描述、核心工作流、禁止事项和按需读取 references 的规则 |
| `agents/openai.yaml` | 定义 Codex UI 展示元数据，包括 display name、short description、default prompt |
| `references/project-boundaries.md` | 记录三层架构、当前已实现/未实现边界、`write_back=false`、候选关系不是事实 |
| `references/facade-workflows.md` | 记录通过 facade 或薄 CLI adapter 进行只读查询、dry-run、候选查看和候选复核的推荐流程 |
| `references/verification.md` | 记录测试命令、集成测试环境变量、Neo4j live 验证和 skipped != passed 的报告规则 |
| `references/output-contract.md` | 规定回答中的事实类型、证据字段、候选/正式关系区分和不确定性表达方式 |

## 4. 修改范围

本变更的修改范围限定在 Skill 资产和项目侧变更文档，不修改业务源码。

### 4.1 当前设计阶段范围

当前阶段只填写：

- `changes/skill封装/design.md`

当前阶段不创建 Skill 目录，不写 `SKILL.md`，不生成 `agents/openai.yaml`，不新增 references 文件，不运行 Skill 校验。

### 4.2 后续 Skill 创建阶段范围

如用户批准进入实现阶段，建议新增或生成以下 Skill 资产：

| 类型 | 路径选择 | 说明 |
|---|---|---|
| 用户级 Skill | `C:\Users\40119\.codex\skills\drawing-graph-operator\` | 适合个人长期在本机使用，可被 Codex 自动发现 |
| 仓库级 Skill | `C:\Users\40119\Desktop\图块图谱构建\.codex\skills\drawing-graph-operator\` | 适合随项目迁移和版本管理，但需确认 Codex 发现机制 |
| 变更文档 | `changes/skill封装/proposal.md`、`tasks.md` | 如需要完整需求和任务拆分，再补齐 |

后续 Skill 创建可以使用 `skill-creator` 流程，并优先生成：

- `SKILL.md`
- `agents/openai.yaml`
- `references/project-boundaries.md`
- `references/facade-workflows.md`
- `references/verification.md`
- `references/output-contract.md`

第一版不建议新增 Skill 自带 `scripts/`。只有在真实使用中发现某些静态检查、命令生成或验证步骤被反复重写且容易出错时，再另行评估是否增加确定性辅助脚本。

### 4.3 可选文档同步范围

Skill 真正创建并验证后，可按需同步：

- `README.md`：补充“如何通过 Codex Skill 操作本项目”的入口说明。
- `Module.md`：如果 Skill 作为项目资产维护，记录 Skill 目录职责和不属于业务源码的边界。
- `architecture.md`：如果 Skill 已成为正式外部操作层，补充其位于 facade 外侧，不等同于 HTTP API 或 MCP Tool adapter。

这些文档同步应在 Skill 创建完成后再做，不能在当前设计阶段把 Skill 写成已实现能力。

## 5. 不包含范围

本变更明确不包含以下内容：

| 不包含项 | 原因 |
|---|---|
| 不封装 `data/`、真实 JSON、PNG、Neo4j 导出或业务数据 | Skill 是工作流和约束包，不是数据包 |
| 不保存 Neo4j 密码、供应商 API key、token 或 `.env` | 避免密钥泄露和不可移植 |
| 不修改 `src/`、`scripts/`、Schema 或测试 | Skill 封装第一版不需要改变业务能力 |
| 不删除 `tests/` 或规划文档 | 测试和根目录规划文档仍是项目安全网和文档契约 |
| 不新增 HTTP/REST API | API 是独立工程，不是 Codex Skill |
| 不新增 MCP Tool adapter | Tool adapter 可后续基于 facade 另行设计 |
| 不实现文件 watcher 或自动导入触发器 | Skill 不监听文件系统；自动触发需要外部调度能力 |
| 不做全量自动语义扫描 | 当前语义证据层是按需识别和 dry-run/write-back 边界 |
| 不默认调用真实云多模态模型 | 当前应保留 fake/client protocol 和显式配置边界 |
| 不把模型观察写成来源事实 | 模型输出只能进入语义证据或候选关系，不覆盖来源事实 |
| 不直接写 Cypher 或调用底层 repository 写回 | Skill 必须走 facade 或薄 CLI adapter |
| 不把 skipped 集成测试报告为 live Neo4j 通过 | 验证报告必须区分单元测试、跳过、真实数据库验证 |

## 6. 影响模块

### 6.1 新增 Skill 资产影响

| 模块或资产 | 影响 | 说明 |
|---|---|---|
| `drawing-graph-operator/SKILL.md` | 新增 | 定义 Skill 的触发规则、核心流程和安全边界 |
| `drawing-graph-operator/agents/openai.yaml` | 新增 | 提供 Codex UI 元数据 |
| `drawing-graph-operator/references/project-boundaries.md` | 新增 | 承载架构边界和非目标，减少 `SKILL.md` 体积 |
| `drawing-graph-operator/references/facade-workflows.md` | 新增 | 承载 facade/CLI 使用流程 |
| `drawing-graph-operator/references/verification.md` | 新增 | 承载测试与验证报告规范 |
| `drawing-graph-operator/references/output-contract.md` | 新增 | 承载事实分层和回答输出契约 |

这些资产不属于 `src/drawing_graph/` 业务模块，不应改变项目运行行为。

### 6.2 对现有源码模块的影响

| 已有模块 | 影响等级 | 设计约束 |
|---|---:|---|
| `src/drawing_graph/tool_facade.py` | 中 | Skill 将其作为主要应用边界；第一版不修改 |
| `src/drawing_graph/tool_factory.py` | 低到中 | Skill 说明通过工厂装配 facade，但不传入密钥，不在 import 时连接数据库 |
| `scripts/drawing_graph_tool.py` | 中 | Skill 可引用它作为薄 CLI adapter；不把它扩展成 Agent Skill 或 MCP Tool |
| `src/drawing_graph/query_ports.py` / `query_port_adapter.py` | 低 | Skill 只依赖其经过 facade 暴露的只读能力 |
| `src/drawing_graph/source_fact_query.py` | 低 | Skill 可引用页面来源事实查询概念，不直接调用内部实现 |
| `src/drawing_graph/semantic_service.py` / `semantic_repository.py` / `recognition_run_log.py` | 低到中 | Skill 强调 dry-run、图谱外 run log、图谱内 observation 的边界 |
| `src/drawing_graph/candidate_review.py` / `relation_repository.py` | 低到中 | Skill 强调候选审核和硬规则，不直接调用底层写回接口 |
| `scripts/import_json.py` / `enrich_block_relations.py` / `review_candidate_relations.py` | 低 | Skill 可以描述这些显式流程，但不让它们自动运行或被 Skill 隐式触发 |

### 6.3 对文档和测试的影响

| 文件或目录 | 影响等级 | 设计约束 |
|---|---:|---|
| `changes/skill封装/design.md` | 高 | 本次新增设计文档 |
| `changes/skill封装/Feature_Analysis_Report.md` | 中 | 作为本设计依据 |
| `README.md` | 低到中 | Skill 创建并验证后可补使用入口；当前不修改 |
| `Module.md` | 低到中 | Skill 若作为项目资产维护，后续可记录模块边界；当前不修改 |
| `architecture.md` | 低 | 后续只记录已完成状态，不提前宣称 |
| `tests/` | 低 | 不删除、不重构；Skill 完成后仍依赖测试保护 facade 边界 |
| `tests/test_planning_docs.py` | 中 | 根目录规划文档仍需保留，不能因 Skill 封装误删 |
| `data/` | 无 | 不进入 Skill，不移动，不清理 |

### 6.4 推荐依赖方向

Skill 封装后的推荐依赖方向保持为：

```text
Codex Skill
  -> DrawingGraphToolFacade / scripts/drawing_graph_tool.py
  -> query/source-fact read port
  -> semantic service / run log / semantic repository
  -> candidate review service
  -> controlled repository / Neo4j
```

禁止形成以下依赖方向：

```text
Codex Skill
  -> Neo4j driver / Cypher / Repository write methods / relation rule functions / real data bundle
```

最终设计结论：本变更应采用“项目操作型 Skill”方案，先沉淀 Codex 使用本项目的规则、入口、输出契约和验证纪律；业务能力继续保留在当前 Python 项目与 `DrawingGraphToolFacade` 内，Skill 不成为新的业务逻辑层。
