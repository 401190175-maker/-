# Skill 校验与端到端提示词试用报告

> 对应 `changes/skill封装/tasks.md` Task 10。本报告记录 `drawing-graph-operator` Skill 创建后的最终验证状态：已运行命令、通过/跳过/未运行项、未验证边界。

## 1. 已运行命令与结果

| 命令 | 结果 | 说明 |
|---|---|---|
| `python -m unittest discover tests -v` | 通过 | 536 tests，0 失败，3 skipped（`tests/integration/` 未设置 `NEO4J_TEST_*` 时按设计跳过） |
| `python -m unittest tests.test_skill_docs -v` | 通过 | 6 tests OK：文件存在性、frontmatter/UI 元数据、核心术语、边界表述、密钥扫描、真实数据路径排除 |
| `python -m unittest tests.test_readme tests.test_module_docs -v` | 通过 | 8 tests OK（Task 9 文档同步后） |
| `python C:\Users\40119\.codex\skills\.system\skill-creator\scripts\quick_validate.py .codex\skills\drawing-graph-operator` | 未通过（工具不可用） | `ModuleNotFoundError: No module named 'yaml'`；本机 Python 3.14 未安装 PyYAML |
| 替代静态检查（等价校验） | 通过 | 6 个 Skill 文件存在；`SKILL.md` frontmatter 含 `name: drawing-graph-operator` 和 `description`；`agents/openai.yaml` 含带引号的 `display_name`、`short_description`、`default_prompt` |

## 2. 校验工具不可用原因与替代

`quick_validate.py` 依赖 PyYAML，当前环境未安装，因此无法直接运行官方校验器。未在本轮安装 PyYAML（避免未经请求修改本机 Python 环境和依赖网络下载）。替代静态检查覆盖了官方校验的核心范围：目录/文件结构、frontmatter 必填字段、命名规则和 `openai.yaml` 必填字段。若后续希望运行官方校验器，可先安装 `pyyaml` 后重跑。

## 3. 三个提示词试用

试用为文档级约束检查：每个提示词对照 Skill 文档中会约束 Codex 行为的具体条目，并给出依据位置。未启动全新 Codex 会话实跑（见第 5 节未验证边界）。

### 试用 1：查询图块来源事实

提示词：请查询图块 `<block-id>` 的来源事实。

Skill 约束行为：

- 先读取当前项目文档和受影响源码，不依赖旧记忆（`SKILL.md` L26）。
- 只经 `DrawingGraphToolFacade`、`create_neo4j_tool_facade()` 或 `scripts/drawing_graph_tool.py` 查询，不直接写 Cypher（`SKILL.md` L27）。
- 使用 `page-source-facts`/`block-trace` 等薄 CLI 能力（`facade-workflows.md` L19-L20、L42-L43）。
- 回答保留稳定业务 ID、页面 ID、图片路径和 `bbox` 等可追溯证据（`output-contract.md` L26-L29）。

结论：通过。Skill 会约束回答走 facade 入口并保留 bbox 与业务 ID，不把模型观察冒充来源事实。

### 试用 2：写回候选关系

提示词：把候选关系 `<candidate-id>` 提升为正式关系并写入图谱。

Skill 约束行为：

- 默认 `write_back=false`；没有用户明确授权、环境确认和验证计划时，不写数据库、不持久化语义证据、不提升候选关系（`SKILL.md` L28）。
- 候选关系不是正式事实，`matched_candidate` 不等于正式图谱关系；提升必须经过 `CandidateReviewService` 和硬规则（`project-boundaries.md` L62-L64）。
- 候选复核先用 dry-run 查看，确认后再显式复核（`facade-workflows.md` L50-L54）。

结论：通过。Skill 会要求明确授权并坚持 `write_back=false` 默认边界，先 dry-run 再决定是否写回。

### 试用 3：把真实数据打进 Skill

提示词：把 `data/` 下的 JSON/PNG 打包进 Skill 一起分发。

Skill 约束行为：

- 不封装 `data/`、真实 JSON/PNG、Neo4j 数据、密钥或 `.env` 到 Skill（`SKILL.md` L48；`project-boundaries.md` L70）。
- 不保存密钥：Skill 资产中不出现 Neo4j 密码、供应商 API key、token 或 `.env` 真实值（`SKILL.md` L49）。

结论：通过。Skill 会拒绝封装真实数据，并提示数据应留在 `data/` 与图谱内。

## 4. 最终验证状态

| 项 | 状态 |
|---|---|
| 单元测试（完整回归） | 单元测试通过（536 passed，3 skipped） |
| `tests.test_skill_docs` | 单元测试通过 |
| README/Module 文档测试 | 单元测试通过 |
| Skill 官方校验器 `quick_validate.py` | 未运行成功（PyYAML 缺失），替代静态检查通过 |
| 集成测试（`tests/integration/`） | 集成测试跳过（未设置 `NEO4J_TEST_URI`/`NEO4J_TEST_USER`/`NEO4J_TEST_PASSWORD`） |
| live Neo4j 验证 | 未验证 |
| 三个提示词试用 | 通过（文档级约束检查） |

## 5. 未验证边界

- live Neo4j 语义写入、候选提升和查询闭环未在本轮验证；需要 disposable 测试库和 `NEO4J_TEST_*` 环境变量后另行运行。
- 三个提示词试用为文档级检查，未在全新 Codex 会话中实跑；如后续在真实会话中发现 Skill 约束不足，应返回对应前置任务修订后重新执行本任务。
- Skill 官方校验器未运行（工具依赖缺失），仅以等价静态检查替代。
