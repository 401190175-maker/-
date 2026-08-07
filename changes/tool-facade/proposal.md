# 最小 Tool Facade 变更提案

## 1. 背景

当前系统已经形成较清晰的三段式能力：来源事实导入、离线派生关系增强、候选关系复核骨架和只读查询。现有入口主要是 CLI、Service、Repository 和 Python 内部查询接口，还没有一个面向 Tool 或后续 Skill 的稳定应用门面。

已实现能力包括：

- 通过 `scripts/import_json.py` 导入 XAnyLabeling JSON/PNG，建立 `Project -> DrawingSet -> DrawingPage -> DrawingBlock` 和页面元素来源事实。
- 通过 `scripts/enrich_block_relations.py` 显式运行离线派生关系增强，写入表格标题、图块标题、页面级基础信息上下文、注释、剖面标记正式关系和空间候选关系。
- 通过 `scripts/review_candidate_relations.py` 提供候选关系复核骨架和显式复核入口，已具备 `accepted`、`rejected`、`unresolved` 三态、硬性提升规则和写回接口；完整的独立多模态复核流程仍属于目标设计。
- 通过 `QueryService` 查询图纸册、页面、图块追溯、图块关系和导入批次状态。

尚未实现的能力包括 Tool facade、完整语义证据层、`RecognitionRun`、`TextObservation`、HTTP/REST API 和 Agent Skill。本变更只规划并实施最小 Tool facade 的边界，不把这些尚未实现的能力描述为已完成。

## 2. 当前问题

当前架构部分支持 Tool facade，但不能直接把现有模块暴露为 Tool。主要问题如下：

- 没有统一的应用门面。Tool 如果现在接入，只能直接调用 `QueryService`、`CandidateReviewService` 或 Repository，边界会比较散。
- `QueryService` 直接依赖 Neo4j driver，并在内部执行 Cypher。它适合作为当前内部查询服务，但不适合作为 Tool API 原样暴露。
- 查询返回值主要是 `dict[str, object]`，字段契约对 Tool schema 不够稳定。
- 语义证据层尚未存在，无法直接支持查询 `TextObservation`；图谱外 `RecognitionRun` 运行日志也尚未建立，因此无法通过 `recognition_run_id` 回查模型、提示词、时间、状态和错误。
- `write_back` 边界尚未成为统一应用策略。当前 CLI 是显式流程，但 Tool 层还没有“默认只读或 dry-run，只有 `write_back=true` 才持久化”的硬约束。
- 当前候选关系复核骨架可复用，但空间候选关系和未来语义候选关系的证据来源不同，不能简单混成一个未区分的写入入口。
- 如果 Tool adapter 直接持有 Neo4j driver、直接调用 Repository 或直接调用规则函数，会绕过现有批次、审计、硬规则和候选提升边界。

## 3. 功能目标

建立一个最小 Tool facade，使外部 Tool 调用只面对稳定的业务能力、请求响应 DTO 和错误 envelope，不直接面对 Neo4j、Cypher、Repository 或底层规则函数。

目标能力包括：

| Tool 能力 | 输入 | 输出 | 写回策略 |
|---|---|---|---|
| 列出图纸册 | `project_id`、`limit` | `drawing_set_id`、名称、页面数或基础字段 | 只读 |
| 列出页面 | `drawing_set_id`、`limit` | `page_id`、`file_stem`、`page_number`、`image_path` | 只读 |
| 获取单页来源事实 | `page_id`、可选 `element_types` | 页面图片、尺寸、图块、标题、表格、基础信息、注释、bbox、source element id | 只读 |
| 执行单页语义识别 | `page_id`、`target_types`、`model_profile`、`prompt_version`、`write_back` | `recognition_run_id`、状态、观察结果摘要、是否已持久化 | 只有 `write_back=true` |
| 查询 `RecognitionRun` | `recognition_run_id` | 模型、prompt、输入范围、状态、错误、时间、是否写回 | 只读 |
| 查询 `TextObservation` | `page_id`、`element_id` 或 `recognition_run_id` | 原文、规范化文本、bbox、来源元素、置信度、状态、证据引用 | 只读 |
| 查看候选语义关系 | `page_id`、`block_id`、`relation_type`、`status` | 候选关系、候选端点、证据 ID、分数、状态、冲突原因 | 只读 |
| 显式审核候选关系 | `candidate_group_id`、`decision` 或复核请求、`reviewer`、`write_back` | `accepted`、`rejected` 或 `unresolved`、理由、是否提升正式关系 | 只有 `write_back=true` |

关键目标约束：

- `write_back=false` 时可以运行语义识别并返回临时结果，但不保证之后还能通过 `recognition_run_id` 查询到它。
- `write_back=true` 时，`RecognitionRun` 写入图谱外运行日志，`TextObservation` 写入图谱语义证据；`TextObservation` 通过 `recognition_run_id` 回查图谱外运行日志。
- 模型输出默认是语义证据，不是正式图谱事实。
- 候选语义关系必须先作为 candidate 存在，审核通过且满足硬规则后才可能转成正式关系。
- 后续 Skill 应编排 Tool，而不是直接调用 Neo4j、Repository、CLI 或规则函数。

## 4. 修改范围

推荐采用“应用 facade + typed DTO + ports”的方案。修改范围分为新增能力和必要的现有模块调整。

建议新增能力文件：

| 新增能力 | 建议文件 | 职责 |
|---|---|---|
| Tool facade | `tool_facade.py` 或 `facade.py` | 面向 Tool adapter 的应用门面，负责输入校验、服务编排、错误封装和 `write_back` 策略 |
| Tool 请求/响应 DTO | `tool_models.py` 或 `facade_models.py` | 定义 Tool 请求、响应、错误 envelope、分页信息和证据定位 DTO |
| 查询接口契约 | `query_ports.py` 或 `ports.py` | 定义 facade 依赖的只读查询最小接口，避免 facade 直接依赖 Neo4j driver |
| 单页来源事实查询 | `source_fact_query.py` 或查询模块扩展 | 读取页面图片路径、尺寸、页面元素、bbox 和 source element id |
| 语义证据模型 | `semantic_models.py` | 定义 `TextObservation`、识别状态、候选语义关系和证据引用；只定义 `RecognitionRun` 引用或运行日志 DTO，不把它作为图谱节点 |
| 语义识别编排 | `semantic_service.py` | 根据 `page_id` 找图片和元素 bbox，调用多模态客户端，生成观察结果 |
| 图谱外识别运行日志 | `recognition_run_log.py` 或 `run_log_repository.py` | 持久化和查询 `RecognitionRun` 运行日志，记录模型、提示词、输入范围、时间、状态、错误和成本统计；不作为知识图谱节点 |
| 语义证据持久化 | `semantic_repository.py` | 持久化和查询 `TextObservation`、候选语义关系和证据支持关系，通过 `recognition_run_id` 引用图谱外运行日志 |
| 多模态客户端协议 | `semantic_client.py` 或 `recognition_client.py` | 定义多模态识别客户端协议和 fake client，具体供应商后置 |

建议分阶段实施：

| 阶段 | 范围 | 不做什么 |
|---|---|---|
| 第 1 阶段：只读 facade | 列图纸册、列页面、获取页面来源事实、获取图块追溯和关系 | 不接模型，不写语义证据 |
| 第 2 阶段：语义证据模型和 dry-run 识别 | 定义图谱外 `RecognitionRun` 运行日志契约和图谱内 `TextObservation`，`write_back=false` 返回临时结果 | 不持久化，不生成正式语义关系 |
| 第 3 阶段：`write_back` 持久化 | `write_back=true` 时写入图谱外 run log 和图谱内 observation，可通过 `recognition_run_id` 回查历史运行 | 不自动提升正式关系 |
| 第 4 阶段：候选语义关系和显式审核 | 生成候选语义关系，审核通过才持久化状态或提升 | 不做 Skill，不做 HTTP，不做全量自动扫描 |

## 5. 不包含范围

本变更不包含以下内容：

- 不实现 HTTP/REST API。
- 不实现 Agent Skill。
- 不实现 MCP Tool adapter 的最终接入，当前先定义应用 facade 边界。
- 不让 Tool adapter 直接创建 Neo4j driver、写 Cypher 或调用 Repository。
- 不开放任意 Cypher 查询。
- 不让 Tool 直接调用 `RelationRepository.write_relations()`、`promote_candidate_relation()` 或 `block_relation_enrichment.py` 的单条规则函数。
- 不把 `CANDIDATE_*` 或候选语义关系当作正式事实。
- 不把模型输出直接提升为正式图谱关系。
- 不把 `RecognitionRun` 作为知识图谱节点。
- 不把语义证据层塞进 `block_relation_enrichment.py`。
- 不把全部语义证据写入混进 `RelationRepository`。
- 不默认调用外部模型供应商。
- 不做全量自动语义扫描。
- 不修改基础导入和离线增强的显式运行边界。
- 不删除或静默迁移历史图谱数据。

## 6. 影响模块

预计影响的现有模块：

| 模块 | 影响 |
|---|---|
| `src/drawing_graph/query_service.py` | 当前可支撑图纸册、页面、图块追溯和图块关系查询；需要由 facade 或 query port 包装，避免 Tool 直接消费内部 `dict` 和 Neo4j driver |
| `src/drawing_graph/candidate_review.py` | 可复用 `accepted/rejected/unresolved` 状态和硬规则思想；语义候选审核可能需要独立 request/result |
| `src/drawing_graph/relation_repository.py` | 当前负责空间候选关系、复核状态和候选提升；后续如复用候选提升机制，只能增加受控规格，不应承载全部语义证据 |
| `src/drawing_graph/neo4j_repository.py` | 基础导入持久化保持不变；后续导入 Tool 如需暴露，应通过 `ImportService` 间接使用 |
| `src/drawing_graph/import_service.py` | 当前不作为最小 facade 首批能力；后续如增加导入 Tool，应由 facade 编排 |
| `src/drawing_graph/relation_service.py` | 当前不作为最小 facade 首批能力；后续可暴露显式增强 Tool |
| `src/drawing_graph/audit.py` | 后续可扩展语义识别审计，但不建议混用导入、增强和语义识别的统计口径 |
| `src/drawing_graph/config.py` | facade 工厂可能复用环境配置；Tool 请求本身不应接收 Neo4j 密码 |
| `architecture.md` | 实现后需要更新 Tool facade 和语义证据层的真实实现状态 |
| `README.md` | 实现后需要补充 facade 使用边界、`write_back` 策略和 dry-run 行为 |
| `Module.md` | 实现后需要记录新增模块职责、接口和依赖 |
| `tests/` | 需要新增 facade、source fact query、semantic models、图谱外 `RecognitionRun` 日志边界、`write_back` 边界、fake client 和查询投影测试 |

推荐依赖方向：

```text
Tool adapter
  -> DrawingGraphToolFacade
      -> Query / SourceFact read port
      -> SemanticRecognitionService
      -> RecognitionRunLog port (graph-external)
      -> SemanticEvidenceRepository port (Neo4j semantic evidence)
      -> CandidateReviewService
          -> Repository port
              -> Neo4j implementation
```

这个依赖方向的核心是：Tool 只调用 facade；facade 调用应用服务；应用服务通过 Repository 或 port 访问 Neo4j；图谱外运行日志由独立 port 管理，`TextObservation` 只保存 `recognition_run_id` 引用；规则和领域模块不连接数据库，也不调用模型供应商。
