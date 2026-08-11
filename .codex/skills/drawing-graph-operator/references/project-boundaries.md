# 项目边界

## 1. 三层架构与统一查询输出

本项目的数据组织遵循固定分层，回答和写回都必须保持分层边界：

```text
来源事实层
  -> 空间与上下文派生关系层
  -> 语义证据层
  -> 统一查询输出
```

- **来源事实层**：基础导入（如 `scripts/import_json.py`）写入的来源事实，例如 `Project -> DrawingSet -> DrawingPage -> DrawingBlock`、页面图片路径、业务 ID 和 bbox。来源事实是后续派生的依据，不允许被模型观察覆盖。
- **空间与上下文派生关系层**：离线增强（如 `scripts/enrich_block_relations.py`）依据来源事实生成的正式派生关系（如 `HAS_CAPTION`、`HAS_ANNOTATION`、`HAS_SECTION_MARK`、`Table -[:HAS_CAPTION]-> TableCaption`、`DrawingPage -[:USES_BASIC_INFO]-> DrawingBasicInfo`）和空间候选关系（如 `CANDIDATE_CAPTION_OF`、`CANDIDATE_HAS_SECTION_MARK`）。
- **语义证据层**：语义识别产生的证据，包括图谱内 `TextObservation` 与各类 `Interpretation`（`BlockInterpretation`、`BasicInfoInterpretation`、`TableInterpretation`），以及关联的图谱外运行日志。语义证据支持但不能替代来源事实。
- **统一查询输出**：通过 `DrawingGraphToolFacade` / 只读 port / `scripts/drawing_graph_tool.py` 返回的可追溯查询结果，必须保留业务 ID、页面 ID、图片路径、bbox、`recognition_run_id` 等证据字段。

## 2. Skill 定位与依赖方向

`drawing-graph-operator` 是本项目的操作型 Skill，位于 `DrawingGraphToolFacade` 外侧，不是新的业务逻辑层。

推荐依赖方向：

```text
Codex Skill
  -> MCP QA 工具（drawing-graph-qa）或受控 QA CLI（scripts/drawing_graph_qa.py）
  -> DrawingGraphQAService
  -> DrawingGraphToolFacade
  -> query / source-fact read port
  -> semantic service / run log / semantic repository
  -> candidate review service
  -> controlled repository / Neo4j
```

禁止依赖方向：

```text
Codex Skill
  -> Neo4j driver / Cypher / repository write methods / rule functions / real data bundle
```

## 3. 当前包含与不包含范围

当前已实现的能力包括：基础导入闭环、离线派生关系增强闭环、候选关系复核骨架、语义证据层（`TextObservation`、三类 `Interpretation`、图谱外 `RecognitionRun` 日志、稳定查询投影）、facade 只读/语义/候选查询、QA 问答 CLI、只读 HTTP API 和本地只读 MCP adapter（STDIO，`drawing-graph-qa`）。当前不包含：

- 远程 MCP 或 Streamable HTTP MCP
- MCP 写回
- 文件 watcher 或自动导入触发器
- 全量自动语义扫描
- OCR
- 默认真实云多模态模型调用（保留 fake/client protocol 与显式配置边界；云模型供应商接入未实现）
- 设置或推断 `DrawingBlock.block_type` 的自动能力
- 把项目 Skill 发布为独立 Agent Skill 插件或公共插件市场条目

## 4. 语义证据边界

- `RecognitionRun` 是**图谱外**运行日志，记录 recognition/interpretation/candidate_review 三类 run。
- `TextObservation` 和各类 `Interpretation` 是**图谱内**语义证据。
- 图谱外 run log 与图谱内语义证据只通过 `recognition_run_id` 关联，二者不能混为一谈。
- 模型输出只能进入语义证据或候选关系，不能覆盖来源事实。

## 5. 写回与候选关系边界

- 默认 `write_back=false`：查询只读、语义识别 dry-run，只返回临时 `recognition_run_id`、observation 和 interpretation。
- 只有显式 `write_back=true` 才允许写入图谱外 run log 和图谱内语义证据。
- **候选关系不是正式事实**，`matched_candidate` 也不等于正式图谱关系。
- 提升正式关系必须经过显式复核（`CandidateReviewService`）和硬规则；证据不足、多候选、跨页或规则边界不明确时，只保留候选关系。
- 禁止直接写 Cypher 或调用底层 repository 写回方法。

## 6. 不封装内容

本 Skill 不封装 data/、真实 JSON/PNG、Neo4j 数据、密钥或 `.env`，也不复制或引用以下内容为资产：

- `data/` 目录及其中真实 JSON/PNG（例如绘图 JSON 与扫描 PNG）
- Neo4j 导出或真实图谱数据
- Neo4j 密码、供应商 API key、token、`.env` 或其他密钥
- 完整项目文档（`README.md`、`Module.md`、`architecture.md`）的复制内容
