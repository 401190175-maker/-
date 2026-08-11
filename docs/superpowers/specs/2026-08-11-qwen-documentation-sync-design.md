# Qwen 文档同步设计

## 目标

以当前工作区已经实现但尚未提交的 Qwen/DashScope 多模态客户端、生产工厂配置和 `recognize-page-semantics` CLI 为依据，同步更新根目录 `architecture.md`、`Module.md` 和 `README.md`。更新只描述可由当前源码和测试证明的能力，不把 live DashScope、live Neo4j、候选关系或模型输出写成已经验证的正式事实。

## 范围

本次业务文档同步只修改以下三个目标文档：

- `architecture.md`
- `Module.md`
- `README.md`

现有业务源码、测试、环境模板以及工作区内其他未提交修改均保持不变。除此之外，Superpowers 流程会新增本规格文件和一份实施计划；二者属于流程产物，不属于业务文档或运行时业务能力。

## 依据

文档同步以当前工作区中的以下实现为准：

- `src/drawing_graph/qwen_semantic_client.py` 提供 `QwenRecognitionConfig` 和 `QwenMultimodalRecognitionClient`，通过 DashScope OpenAI-compatible chat completions 接口执行按需多模态识别。
- `src/drawing_graph/config.py` 在 `ToolFacadeConfig` 中提供 provider、模型、base URL 和超时配置，并从环境变量读取非密钥配置。
- `src/drawing_graph/tool_factory.py` 默认继续装配 fake client；只有显式选择 `qwen` 时才从当前进程读取 `DASHSCOPE_API_KEY` 并装配 Qwen client。
- `scripts/drawing_graph_tool.py` 提供 `recognize-page-semantics`，默认 `write_back=false`，只有显式 `--write-back` 才进入 facade 的受控语义证据写回流程。
- `tests/test_qwen_semantic_client.py`、`tests/test_tool_factory.py` 和 `tests/test_tool_adapter_cli.py` 提供离线 provider 合约、工厂选择和 CLI 参数边界证据。

## 文档设计

### `architecture.md`

保持现有章节结构，在整体分层、按需语义证据入口、目录与文件职责、配置模块、测试结构和阶段边界中补齐 Qwen 能力：

- 调用链保持 `CLI adapter -> DrawingGraphToolFacade -> SemanticRecognitionService -> MultimodalRecognitionClient -> Qwen/DashScope`。
- 默认 client 仍为 fake；Qwen 只在显式 provider 配置时启用，不属于默认真实云模型调用。
- API key 只由最外层生产装配从当前进程环境读取，不进入 facade DTO、命令参数、日志或文档示例值。
- Qwen 返回的是语义观察和解释输入，不能覆盖来源事实，也不能直接生成正式候选提升结果。
- 明确区分离线 mock 测试、live DashScope 验证与 live Neo4j 验证。

### `Module.md`

在既有“新模块职责、新接口、新依赖、数据变化、架构变化”结构中同步：

- 记录 `qwen_semantic_client.py` 的职责和错误映射边界。
- 记录 `ToolFacadeConfig` 新增的 `recognition_provider`、`qwen_model`、`qwen_base_url` 和 `qwen_timeout_seconds`；同时明确它不持有 API key。
- 记录 `create_neo4j_tool_facade()` 的 provider 选择行为，以及 `create_tool_facade()` 和默认生产配置继续使用 fake client 的行为。
- 记录 `recognize-page-semantics` CLI 的默认 dry-run 与显式写回规则。
- HTTPX 是现有 HTTP adapter 与 Qwen OpenAI-compatible 调用共用依赖，不新增供应商专用 SDK。
- Qwen 接入不改变 Neo4j schema、事实分层或候选提升硬规则。

### `README.md`

面向使用者补齐可执行说明：

- 在可选环境变量中列出 provider、模型、base URL、超时和 `DASHSCOPE_API_KEY`，使用占位符而非真实密钥。
- 给出启用 Qwen 后运行 `recognize-page-semantics` 的 dry-run 示例，并说明 `--write-back` 的持久化影响。
- 说明默认 fake client、密钥保护、错误输出脱敏和 provider 配置错误的排查方法。
- 在测试章节列出 Qwen、工厂和 CLI 的聚焦离线测试命令。
- 明确离线测试通过不能证明 live DashScope 或 live Neo4j 可用。

## 安全与事实边界

- 默认 `write_back=false`，文档不建议把 `--write-back` 作为普通查询默认参数。
- `RecognitionRun` 保持图谱外；`TextObservation` 和三类 `Interpretation` 保持图谱内，并只通过 `recognition_run_id` 关联。
- 来源事实、派生关系、语义观察、语义解释、候选关系和正式关系继续分层描述。
- `matched_candidate` 和任何 `CANDIDATE_*` 关系都不是正式事实。
- 不声称真实 DashScope 已调用，不声称本轮 live Neo4j 已验证。
- 不记录或输出真实 API key、Neo4j 密码、token 或 `.env` 内容。

## 验证设计

文档更新后依次执行：

1. 文档合同测试：`tests.test_readme`、`tests.test_relation_readme`、`tests.test_module_docs`、`tests.test_cross_section_docs`、`tests.test_planning_docs`、`tests.test_semantic_docs`、`tests.test_tool_facade_docs`、`tests.test_qa_docs`、`tests.test_qa_http_docs`、`tests.test_qa_mcp_docs`。
2. Qwen/工厂/CLI 聚焦测试：`tests.test_qwen_semantic_client`、`tests.test_tool_factory`、`tests.test_tool_adapter_cli`。
3. 完整回归：`python -m unittest discover tests -v`。
4. 检查三份文档的 Git diff、敏感值和过时表述，确认只包含获批范围内的文档同步。

最终报告分别给出单元测试、集成测试跳过情况、live DashScope 和 live Neo4j 状态；任何 skipped 都不计为 live 验证通过。

## 验收标准

- 三份文档对 Qwen 客户端、配置字段、工厂装配、CLI 用法和安全边界描述一致。
- 文档中的命令和环境变量名称与当前源码一致。
- 默认 fake、显式 Qwen、默认 dry-run、显式写回四个状态边界无歧义。
- 未引入 OCR、Ava 专有 adapter、全量自动语义扫描、远程 MCP 或新的数据库 schema 声明。
- 文档合同测试与完整单元回归结果被如实记录；未执行的 live 验证明确标为未验证。
