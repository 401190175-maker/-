# Skill 封装实施任务

> 本文件依据 `changes/skill封装/design.md` 生成。每个任务只交付一个明确能力，均包含明确目标、指定修改文件、独立测试和完成标准。Skill 是 Codex 操作本项目的工作流和约束包，不封装真实 `data/`、Neo4j 数据、密钥、业务源码，不替代 `DrawingGraphToolFacade`、MCP Tool adapter、HTTP API 或文件 watcher。

## Task 1: 创建 Skill 外壳

**目标：** 创建 `drawing-graph-operator` Skill 的最小目录和必需入口文件，使后续任务可以逐步填充内容。

**修改文件：**
- 新增：`.codex/skills/drawing-graph-operator/SKILL.md`
- 新增目录：`.codex/skills/drawing-graph-operator/agents/`
- 新增目录：`.codex/skills/drawing-graph-operator/references/`

**独立测试：**
- `Test-Path -LiteralPath ".codex\skills\drawing-graph-operator\SKILL.md"`
- `Test-Path -LiteralPath ".codex\skills\drawing-graph-operator\agents"`
- `Test-Path -LiteralPath ".codex\skills\drawing-graph-operator\references"`

**完成标准：**
- Skill 目录存在，目录名固定为 `drawing-graph-operator`。
- `SKILL.md` 包含合法 YAML frontmatter，至少包含 `name: drawing-graph-operator` 和完整 `description`。
- `description` 明确触发场景：图块图谱、`DrawingGraphToolFacade`、Neo4j 图纸图谱、候选关系、语义证据层、断面匹配、`write_back`。
- 本任务不写任何 references 详细内容，不创建脚本，不复制 `data/`。

## Task 2: 编写 Skill 核心工作流

**目标：** 在 `SKILL.md` 中定义 Codex 使用本项目时的核心流程、默认安全边界和按需读取 references 的导航规则。

**修改文件：**
- 修改：`.codex/skills/drawing-graph-operator/SKILL.md`

**独立测试：**
- `Select-String -LiteralPath ".codex\skills\drawing-graph-operator\SKILL.md" -Pattern "write_back=false|DrawingGraphToolFacade|scripts/drawing_graph_tool.py|project-boundaries.md|facade-workflows.md|verification.md|output-contract.md"`

**完成标准：**
- `SKILL.md` 明确要求先读取当前项目文档和受影响源码，再行动。
- `SKILL.md` 明确默认 `write_back=false`，没有用户明确授权、环境确认和验证计划时不写数据库。
- `SKILL.md` 明确只经由 `DrawingGraphToolFacade`、`create_neo4j_tool_facade()` 或 `scripts/drawing_graph_tool.py` 使用项目能力。
- `SKILL.md` 明确按需读取四个 references 文件：`project-boundaries.md`、`facade-workflows.md`、`verification.md`、`output-contract.md`。
- `SKILL.md` 不包含真实 Neo4j 密码、供应商 API key、真实数据路径清单或完整项目 README 复制内容。

## Task 3: 编写项目边界 reference

**目标：** 编写 `project-boundaries.md`，集中记录当前实现边界、非目标、三层架构和 Skill 禁止事项。

**修改文件：**
- 新增：`.codex/skills/drawing-graph-operator/references/project-boundaries.md`

**独立测试：**
- `Select-String -LiteralPath ".codex\skills\drawing-graph-operator\references\project-boundaries.md" -Pattern "来源事实层|空间与上下文派生关系层|语义证据层|write_back=false|候选关系不是正式事实|RecognitionRun|TextObservation|不封装 data"`

**完成标准：**
- 文档明确三层架构：来源事实层、空间与上下文派生关系层、语义证据层。
- 文档明确 Skill 位于 facade 外侧，推荐依赖方向为 `Codex Skill -> DrawingGraphToolFacade -> ports/services -> controlled repository`。
- 文档明确当前不包含 Agent Skill、MCP Tool adapter、HTTP/REST API、文件 watcher、全量自动语义扫描、默认真实云模型调用。
- 文档明确 `RecognitionRun` 是图谱外运行日志，`TextObservation` 和各类 `Interpretation` 是图谱内语义证据。
- 文档明确不封装 `data/`、真实 JSON/PNG、Neo4j 数据、密钥或 `.env`。

## Task 4: 编写 facade 工作流 reference

**目标：** 编写 `facade-workflows.md`，说明 Codex 如何通过 facade 或薄 CLI adapter 执行只读查询、dry-run、候选查看和候选复核。

**修改文件：**
- 新增：`.codex/skills/drawing-graph-operator/references/facade-workflows.md`

**独立测试：**
- `Select-String -LiteralPath ".codex\skills\drawing-graph-operator\references\facade-workflows.md" -Pattern "DrawingGraphToolFacade|create_neo4j_tool_facade|scripts/drawing_graph_tool.py|list-drawing-sets|block-trace|list-candidate-relations|write_back=false"`

**完成标准：**
- 文档说明只读查询优先走 `DrawingGraphToolFacade` 或 `scripts/drawing_graph_tool.py`。
- 文档列出当前可引用的薄 CLI adapter 能力，例如 `list-drawing-sets`、`list-pages`、`page-source-facts`、`block-trace`、`block-relations`、`list-text-observations`、`list-interpretations`、`list-candidate-relations`、`list-section-matches`。
- 文档明确 Skill 不直接创建 Neo4j driver、不写 Cypher、不直接调用 repository 写回方法、不直接调用 `block_relation_enrichment.py` 规则函数。
- 文档明确导入、离线增强和候选复核是显式流程，不由 Skill 隐式自动触发。
- 文档中的命令示例使用 PowerShell 友好的路径和参数表达，不写真实密码。

## Task 5: 编写验证规则 reference

**目标：** 编写 `verification.md`，固定单元测试、集成测试、Skill 校验和验证状态报告规则。

**修改文件：**
- 新增：`.codex/skills/drawing-graph-operator/references/verification.md`

**独立测试：**
- `Select-String -LiteralPath ".codex\skills\drawing-graph-operator\references\verification.md" -Pattern "python -m unittest discover tests -v|NEO4J_TEST_URI|NEO4J_TEST_USER|NEO4J_TEST_PASSWORD|skipped|不等于|quick_validate.py"`

**完成标准：**
- 文档列出基础回归命令：`python -m unittest discover tests -v`。
- 文档列出真实 Neo4j 集成测试所需环境变量：`NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD`。
- 文档明确集成测试跳过不等于 live Neo4j 已通过。
- 文档说明 Skill 创建后应运行 `quick_validate.py <skill-path>` 或等价 Skill 校验。
- 文档要求最终报告区分：未运行、单元测试通过、集成测试跳过、live Neo4j 已验证、live Neo4j 未验证。

## Task 6: 编写输出契约 reference

**目标：** 编写 `output-contract.md`，规定 Codex 输出图谱结果时必须区分事实类型、证据字段和不确定状态。

**修改文件：**
- 新增：`.codex/skills/drawing-graph-operator/references/output-contract.md`

**独立测试：**
- `Select-String -LiteralPath ".codex\skills\drawing-graph-operator\references\output-contract.md" -Pattern "source_fact|derived_relation|semantic_observation|semantic_interpretation|candidate_relation|formal_relation|matched_candidate|bbox|recognition_run_id"`

**完成标准：**
- 文档定义至少六类输出事实：`source_fact`、`derived_relation`、`semantic_observation`、`semantic_interpretation`、`candidate_relation`、`formal_relation`。
- 文档明确候选关系不是正式事实，`matched_candidate` 不是正式图谱关系。
- 文档要求回答保留稳定业务 ID、页面 ID、图片路径、bbox、`recognition_run_id`、`payload_ref` 或候选关系状态等可追溯证据。
- 文档要求对 `partial`、`ambiguous`、`not_found`、`recognition_failed`、`not_recognized` 等状态保守表达，不补猜。
- 文档禁止把模型观察写回或表述为来源事实，禁止把 AI 的 `interpreted_type` 写成 `DrawingBlock.block_type`。

## Task 7: 编写 agents/openai.yaml

**目标：** 编写 Codex UI 元数据，使 Skill 在界面和触发提示中有清晰名称、简短说明和默认提示。

**修改文件：**
- 新增：`.codex/skills/drawing-graph-operator/agents/openai.yaml`

**独立测试：**
- `Select-String -LiteralPath ".codex\skills\drawing-graph-operator\agents\openai.yaml" -Pattern "display_name|short_description|default_prompt|drawing-graph-operator|DrawingGraphToolFacade|write_back"`

**完成标准：**
- `openai.yaml` 包含 `display_name`、`short_description`、`default_prompt`。
- `short_description` 长度足够表达用途，不能只写极短中文短语。
- `default_prompt` 明确该 Skill 用于图块图谱项目操作、facade 边界、`write_back=false` 和候选关系区分。
- `openai.yaml` 与 `SKILL.md` 的名称、触发场景和非目标保持一致。
- 文件不包含密钥、真实数据目录清单或供应商账号信息。

## Task 8: 增加 Skill 静态边界测试

**目标：** 增加项目内静态测试，防止 Skill 内容缺少关键边界或误包含真实数据、密钥、自动化平台承诺。

**修改文件：**
- 新增：`tests/test_skill_docs.py`

**独立测试：**
- `python -m unittest tests.test_skill_docs -v`

**完成标准：**
- 测试验证 `.codex/skills/drawing-graph-operator/SKILL.md`、`agents/openai.yaml` 和四个 references 文件全部存在。
- 测试验证 Skill 文档包含 `DrawingGraphToolFacade`、`write_back=false`、`candidate_relation`、`formal_relation`、`RecognitionRun`、`TextObservation`。
- 测试验证 Skill 文档包含不封装 `data/`、不保存密钥、不直接写 Cypher、不替代 MCP Tool adapter/HTTP API/watcher 的边界。
- 测试扫描 Skill 文档中不得出现明显密钥字段值，例如真实 `NEO4J_PASSWORD` 值、`sk-` token、`api_key: <真实内容>`。
- 测试不连接 Neo4j、不调用真实云模型、不运行导入或增强脚本。

## Task 9: 同步项目文档中的 Skill 边界

**目标：** 在 Skill 创建并通过静态测试后，同步项目说明，使 README 和模块记录知道 Skill 是外部操作层，而不是业务源码或 API。

**修改文件：**
- 修改：`README.md`
- 修改：`Module.md`
- 修改：`architecture.md`

**独立测试：**
- `python -m unittest tests.test_readme tests.test_module_docs -v`
- `python -m unittest tests.test_skill_docs -v`

**完成标准：**
- `README.md` 增加 Codex Skill 使用入口说明，并明确 Skill 不封装数据、不保存密钥、不自动监听文件、不替代 HTTP/MCP。
- `Module.md` 记录 Skill 资产职责，并说明它不属于 `src/drawing_graph/` 业务模块，不改变运行时图谱能力。
- `architecture.md` 只把 Skill 描述为 facade 外侧的操作层，不把它写成已经实现的 HTTP API、MCP Tool adapter 或自动化 watcher。
- 文档仍保留当前实现/目标状态区分，不把规划能力写成已完成。
- 相关文档测试和 Skill 静态测试通过。

## Task 10: 运行 Skill 校验与端到端提示词试用

**目标：** 对已创建的 Skill 做最终验证，确认 Skill 文件结构合法，并用真实提示词检查是否能约束 Codex 行为。

**修改文件：**
- 新增：`changes/skill封装/Skill_Verification_Report.md`

**独立测试：**
- `python <skill-creator-path>\scripts\quick_validate.py .codex\skills\drawing-graph-operator`
- `python -m unittest tests.test_skill_docs -v`
- 手工提示词试用 1：要求查询图块来源事实，检查回答是否走 facade、保留 bbox 和业务 ID。
- 手工提示词试用 2：要求写回候选关系，检查回答是否要求明确授权并坚持 `write_back=false` 默认。
- 手工提示词试用 3：要求“把 data 打进 Skill”，检查回答是否拒绝封装真实数据。

**完成标准：**
- Skill 校验通过，或记录校验工具不可用的具体原因和替代静态检查结果。
- `tests.test_skill_docs` 通过。
- 三个提示词试用均体现 Skill 约束：不绕过 facade、不默认写库、不封装真实数据、不把候选关系当正式事实。
- 如试用发现 Skill 文档不够约束，本任务不直接扩大修改范围；应在 `Skill_Verification_Report.md` 中记录失败项，并返回对应前置任务修订后重新执行本任务。
- `Skill_Verification_Report.md` 记录最终验证状态，包括已运行命令、通过/跳过/未运行项和未验证边界。
