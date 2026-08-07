# Tool 层 QA 编排技术设计

本设计基于 `changes/tool层/proposal.md`、`changes/tool层/Feature_Analysis_Report.md`、根目录 `README.md`、`Module.md`、`architecture.md` 和当前 `DrawingGraphToolFacade` 实现边界。目标是在禁止无意义重构、优先复用已有架构的前提下，新增面向问答场景的 Tool 层编排能力。

设计原则：

- QA 层只做问题类型识别、证据聚合和输出组织，不重做图谱、不重写 facade。
- 所有图谱能力通过 `DrawingGraphToolFacade` 获取；QAService 不直接访问 Neo4j、Cypher、repository 写回方法或离线规则函数。
- 默认只读，默认 `write_back=false`，第一阶段 QA 不持久化语义证据、不提升候选关系。
- 输出必须区分 `source_fact`、`derived_relation`、`semantic_observation`、`semantic_interpretation`、`candidate_relation`、`formal_relation`。
- CLI、HTTP、Skill、MCP 都是 adapter，业务编排只放在 `DrawingGraphQAService`。

## 1. 系统架构变化

### 1.1 当前架构

当前系统已经有稳定的底层分层：

```text
来源事实层
  -> 空间与上下文派生关系层
  -> 语义证据层
  -> DrawingGraphToolFacade / scripts/drawing_graph_tool.py
```

当前 `DrawingGraphToolFacade` 已经封装：

- 图纸册、页面、页面来源事实查询。
- block 追溯链路和 block 关系查询。
- 按需语义识别 dry-run / write-back 边界。
- `RecognitionRun` 图谱外日志查询。
- `TextObservation`、`Interpretation`、payload 查询。
- 候选关系查询和候选复核入口。
- 断面候选/正式匹配 dry-run 与查询。

因此，本变更不新增第二套底层 Tool facade，也不重构导入、增强、语义证据、候选复核或 Neo4j repository。

### 1.2 新增 QA 编排层

新增架构层次如下：

```text
Codex Skill / QA CLI / HTTP API / MCP Tool adapter / Ava
  -> DrawingGraphQAService
      -> QARequest / QAAnswer / AnswerFact / EvidenceRef
      -> DrawingGraphToolFacade
          -> read port / source fact query
          -> semantic service / run log / semantic repository / payload store
          -> section match service
          -> candidate review service
          -> controlled repository / Neo4j
```

架构变化的核心是新增“问答编排层”，而不是新增“图谱能力层”：

- `DrawingGraphQAService` 接收明确的 `question_type` 和 scope。
- QAService 根据问题类型调用一个或多个 facade 方法。
- QAService 把 facade DTO 组合成结构化 `QAAnswer`。
- adapter 只负责协议转换和展示，不复制业务逻辑。

### 1.3 禁止依赖方向

QA 层禁止以下依赖：

```text
DrawingGraphQAService -> Neo4j driver
DrawingGraphQAService -> Cypher
DrawingGraphQAService -> QueryService
DrawingGraphQAService -> RelationRepository
DrawingGraphQAService -> RelationRepository.write_relations()
DrawingGraphQAService -> RelationRepository.promote_candidate_relation()
DrawingGraphQAService -> block_relation_enrichment.py 内部规则函数
DrawingGraphQAService -> scripts/import_json.py / scripts/enrich_block_relations.py 主函数
```

原因：

1. `DrawingGraphToolFacade` 已经是当前受控边界。
2. QAService 的职责是问答组织，不是数据库访问。
3. 一旦 QAService 绕过 facade，CLI、HTTP、MCP 和 Skill 会继承同一个安全漏洞。

### 1.4 分阶段架构

第一阶段：

```text
QA CLI
  -> DrawingGraphQAService
  -> DrawingGraphToolFacade
```

第二阶段：

```text
HTTP API
  -> DrawingGraphQAService
  -> DrawingGraphToolFacade
```

第三阶段：

```text
Codex Skill / MCP Tool adapter
  -> DrawingGraphQAService
  -> DrawingGraphToolFacade
```

第一阶段不实现 HTTP、MCP、Ava 对接或真实模型供应商。

## 2. 新增模块

### 2.1 `src/drawing_graph/qa_models.py`

职责：定义 QA 层对外稳定数据契约。

建议模型：

| 模型 | 作用 |
|---|---|
| `QuestionType` | 问题类型枚举 |
| `QAScope` | 问答范围，承载 `project_id`、`drawing_set_id`、`page_id`、`block_id`、`cross_section_id`、`table_id`、`table_caption_id` 等可选 ID |
| `QARequest` | 一次问答请求，包含 `question_type`、scope、输出语言、include 选项和安全选项 |
| `EvidenceRef` | 证据引用，保留业务 ID、page ID、image path、bbox、run ID、payload ref、rule version |
| `AnswerFact` | 单条事实或关系，强制携带 `fact_kind`、`status`、`ids`、`evidence` |
| `QAAnswer` | 最终结构化 answer，包含 summary、facts、warnings、unsupported_parts |
| `QAError` / `QAErrorCode` | QA 层错误分类 |

`QuestionType` 建议值：

```text
page_summary
block_relations
candidate_relations
section_matches
table_caption_status
diagnostic_status
unknown_or_unsupported
```

`fact_kind` 固定取值：

```text
source_fact
derived_relation
semantic_observation
semantic_interpretation
candidate_relation
formal_relation
diagnostic
unsupported
```

说明：`diagnostic` 和 `unsupported` 是 QA 层展示辅助类型，不应写入 Neo4j，不等同于图谱事实。

### 2.2 `src/drawing_graph/qa_service.py`

职责：实现 `DrawingGraphQAService`，作为 QA 编排核心。

主要职责：

- 校验 `QARequest`。
- 根据 `question_type` 路由到内部处理函数。
- 调用 `DrawingGraphToolFacade` 的已有方法。
- 把 facade DTO 转换为 `AnswerFact`。
- 生成 `QAAnswer.summary`、`warnings`、`unsupported_parts`。
- 保持查询只读，不传入 `write_back=true`。

建议内部方法：

| 方法 | 职责 |
|---|---|
| `ask(request)` | 统一入口 |
| `_answer_page_summary(request)` | 聚合页面来源事实、元素统计、语义证据状态 |
| `_answer_block_relations(request)` | 聚合 block trace、block relations、候选关系 |
| `_answer_candidate_relations(request)` | 聚合 block/page 候选关系和断面候选 |
| `_answer_section_matches(request)` | 查询或 dry-run 断面匹配，但默认不写回 |
| `_answer_table_caption_status(request)` | 输出表格标题状态；当前 facade 不足时返回明确 unsupported 部分 |
| `_answer_diagnostic_status(request)` | 输出导入、增强、语义证据、候选和未验证状态 |
| `_unsupported(request, reason)` | 统一构造不支持回答 |

实现边界：

- QAService 不创建 facade；facade 由工厂或 adapter 注入。
- QAService 不读环境变量。
- QAService 不做 JSON 序列化。
- QAService 不生成长篇自然语言；只生成简短 summary 和结构化 facts。

### 2.3 `scripts/drawing_graph_qa.py`

职责：第一阶段 CLI adapter。

建议子命令：

| 命令 | 映射问题类型 | 必需参数 |
|---|---|---|
| `ask-page` | `page_summary` | `--page-id` |
| `ask-block` | `block_relations` | `--block-id` |
| `ask-candidates` | `candidate_relations` | `--page-id` 或 `--block-id` |
| `ask-section` | `section_matches` | `--cross-section-id`，可选 `--page-id` |
| `ask-table-caption` | `table_caption_status` | `--page-id` 或 `--table-id` / `--table-caption-id` |
| `diagnose` | `diagnostic_status` | `--page-id` 或 `--block-id` |

输出选项：

```text
--format json
--format zh-brief
```

职责边界：

- 参考 `scripts/drawing_graph_tool.py` 的环境变量读取、driver 创建、错误脱敏和 JSON 输出方式。
- CLI 只创建 facade 和 QAService，然后调用 `QAService.ask()`。
- CLI 不直接调用 `QueryService`、`RelationRepository` 或底层脚本。

### 2.4 `src/drawing_graph/qa_rendering.py`（可选）

职责：将 `QAAnswer` 转为简短中文输出。

第一阶段可选。如果 CLI 中中文渲染逻辑超过少量分支，建议拆出该模块，避免 `scripts/drawing_graph_qa.py` 变成业务逻辑文件。

边界：

- 渲染层只读 `QAAnswer`。
- 渲染层不调用 facade。
- 渲染层不修改事实类型或状态。

### 2.5 测试模块

建议新增：

| 测试文件 | 覆盖内容 |
|---|---|
| `tests/test_qa_models.py` | DTO 构造、非法 question type、空 ID、非法 fact kind、证据字段 |
| `tests/test_qa_service.py` | fake facade 下的五类核心问题、diagnostic、unsupported、候选不当事实 |
| `tests/test_qa_cli.py` | CLI 参数、JSON 输出、中文简短输出、错误脱敏 |
| `tests/test_qa_docs.py` | 文档边界词：不写 Cypher、不直接访问 Neo4j、默认只读、HTTP/MCP 非第一阶段 |

## 3. 修改模块

### 3.1 第一阶段修改模块

| 模块 | 修改方式 | 修改原因 | 边界 |
|---|---|---|---|
| `README.md` | 增加 QA CLI 最短使用说明 | 用户能通过更自然的命令问 page/block/candidate | 不写 HTTP/MCP 已完成 |
| `Module.md` | 增加 QA 模块职责、新接口和依赖方向 | 维护者能理解 QAService 是 facade 外侧编排层 | 不把 QAService 描述为底层图谱能力 |
| `architecture.md` | 增加 Tool 层 QA 编排位置 | 更新当前架构图中的调用路径 | 不改变导入/增强/语义证据现有分层 |
| `tests/` | 增加 QA 模型、服务、CLI、文档测试 | 防止 QA 层绕过 facade 或混淆 candidate/formal | 不依赖真实 Neo4j 或真实模型 |

### 3.2 原则上不修改的模块

| 模块 | 原因 |
|---|---|
| `src/drawing_graph/tool_facade.py` | 当前 facade 已有足够能力支撑 MVP；除非发现表格标题状态确有只读缺口，否则不改 |
| `src/drawing_graph/query_service.py` | QAService 不直接依赖查询层，不为 QA 重写查询 |
| `src/drawing_graph/relation_repository.py` | QA 第一阶段只读，不增加写回规格 |
| `src/drawing_graph/block_relation_enrichment.py` | QA 不计算空间关系 |
| `src/drawing_graph/import_service.py` | QA 不导入数据 |
| `scripts/import_json.py` | QA 不改变导入 CLI |
| `scripts/enrich_block_relations.py` | QA 不改变离线增强 CLI |
| `scripts/review_candidate_relations.py` | QA 不替代显式候选复核 CLI |
| `scripts/create_schema.cypher` | QA 第一阶段不新增 schema |

### 3.3 允许的最小适配

如果实现 `table_caption_status` 时发现当前 facade 无法只读返回表格标题关系状态，有两种保守选择：

1. 第一阶段在 `QAAnswer.unsupported_parts` 中明确说明该项缺少 facade 只读接口。
2. 后续单独给 `DrawingGraphToolFacade` 增加一个窄口径只读方法，例如 `get_table_caption_status(page_id|table_id|table_caption_id)`。

不允许为了这个问题直接在 QAService 中拼 Cypher。

## 4. 数据模型变化

### 4.1 不新增 Neo4j schema

第一阶段 QA 编排不新增 Neo4j 节点、关系、约束或索引。QA 层是运行时聚合与输出模型，不是新的图谱事实层。

原因：

- 当前 `page_summary`、`block_relations`、`candidate_relations`、`section_matches` 已可由 facade 现有方法组合。
- `table_caption_status` 即便有缺口，也应先通过 facade 只读扩展解决，而不是新增数据库结构。
- 问答运行日志、HTTP 调用日志或用户问题审计属于后续独立需求。

### 4.2 QA 请求模型

`QARequest` 建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `question_type` | `QuestionType` | 问题类型 |
| `scope` | `QAScope` | 查询范围，承载 page/block/section/table 等 ID |
| `language` | `str` | 输出语言，第一阶段支持 `zh` 和 `en`，默认 `zh` |
| `include_semantics` | `bool` | 是否尝试查询语义证据，默认 `true` |
| `include_candidates` | `bool` | 是否包含候选关系，默认 `true` |
| `include_payload` | `bool` | 是否展开 payload，默认 `false` |
| `format_hint` | `str` | adapter 渲染提示，例如 `json` 或 `zh-brief` |
| `write_back` | `bool` | 第一阶段必须为 `false` 或缺省 |

`QAScope` 建议字段：

| 字段 | 说明 |
|---|---|
| `project_id` | 项目 ID，可用于未来项目级诊断 |
| `drawing_set_id` | 图纸册 ID |
| `page_id` | 页面 ID |
| `block_id` | 图块 ID |
| `cross_section_id` | 断面标记 ID |
| `table_id` | 表格 ID |
| `table_caption_id` | 表格标题 ID |
| `element_id` | 通用元素 ID，用于后续扩展 |

校验原则：

- `page_summary` 必须有 `page_id`。
- `block_relations` 必须有 `block_id`。
- `candidate_relations` 至少有 `page_id` 或 `block_id`。
- `section_matches` 至少有 `cross_section_id` 或 `page_id`。
- `table_caption_status` 至少有 `page_id`、`table_id` 或 `table_caption_id`。
- `diagnostic_status` 至少有 `page_id` 或 `block_id`。

### 4.3 QA 输出模型

`QAAnswer` 建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `question_type` | `QuestionType` | 实际处理的问题类型 |
| `scope` | `QAScope` | 实际查询范围 |
| `status` | `str` | `answered`、`partial`、`not_found`、`unsupported`、`failed` |
| `summary` | `str` | 简短可读摘要 |
| `facts` | `tuple[AnswerFact, ...]` | 结构化事实、关系或诊断条目 |
| `warnings` | `tuple[str, ...]` | 降级、缺证据、候选冲突、能力缺口 |
| `unsupported_parts` | `tuple[str, ...]` | 明确无法回答的部分 |
| `source_calls` | `tuple[str, ...]` | 可选记录调用了哪些 facade 能力，用于测试和诊断 |

`AnswerFact` 建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `fact_kind` | `str` | 六类事实之一，或 QA 辅助类型 |
| `label` | `str` | 面向用户的短标签 |
| `status` | `str` | `confirmed`、`candidate`、`partial`、`ambiguous`、`not_found`、`not_recognized` 等 |
| `ids` | `dict[str, str]` | 相关稳定业务 ID |
| `relation_type` | `str | None` | 关系类型，例如 `HAS_CAPTION` |
| `value` | `object | None` | 简短值或摘要 |
| `evidence` | `tuple[EvidenceRef, ...]` | 可追溯证据 |
| `payload` | `dict | None` | 默认不展开，只在明确 include 时提供 |

`EvidenceRef` 建议字段：

| 字段 | 说明 |
|---|---|
| `project_id` |
| `drawing_set_id` |
| `page_id` |
| `block_id` |
| `element_id` |
| `image_path` |
| `bbox` |
| `normalized_bbox` |
| `recognition_run_id` |
| `observation_id` |
| `interpretation_id` |
| `payload_ref` |
| `candidate_group_id` |
| `rule_version` |
| `review_run_id` |

### 4.4 状态模型

QA 层状态不替代底层状态，只做聚合表达：

| QA 状态 | 含义 |
|---|---|
| `answered` | 请求范围和主要事实均可回答 |
| `partial` | 只回答了部分问题，存在缺失语义证据或缺少 facade 能力 |
| `not_found` | 请求对象不存在或 facade 返回 not found |
| `unsupported` | 问题类型或所需能力不在当前范围 |
| `failed` | 底层 facade、配置或依赖不可用 |

候选关系状态必须保留底层语义：

- `candidate` 仍是候选，不是正式事实。
- `matched_candidate` 不等于正式关系。
- `formal_relation` 只能来自明确正式关系或 facade 的正式匹配投影。

## 5. API 设计

这里的 API 指 Python QAService 和 adapter 契约，不是第一阶段 HTTP API。

### 5.1 Python API

推荐入口：

```text
DrawingGraphQAService(facade)
DrawingGraphQAService.ask(request) -> QAAnswer
```

设计约束：

- `facade` 必须由外部注入。
- `ask()` 不接收 Neo4j driver、URI、用户名、密码或 Cypher。
- `ask()` 默认拒绝 `write_back=true`。
- 返回值始终是 `QAAnswer`，调用失败以 `QAError` 或等价稳定错误抛出。

### 5.2 问题类型到 facade 调用映射

| `question_type` | facade 调用 | 输出重点 |
|---|---|---|
| `page_summary` | `get_page_source_facts(page_id)`；可选 `list_text_observations(page_id)`、`list_interpretations(page_id)` | 页面图片、元素统计、来源事实、语义证据状态 |
| `block_relations` | `get_block_trace(block_id)`、`get_block_relations(block_id)`；可选 `list_candidate_relations(block_id)` | block 追溯、正式派生关系、候选关系、增强状态 |
| `candidate_relations` | `list_candidate_relations(page_id|block_id)`、`list_section_matches(page_id, statuses=("candidate",))` | 候选组、候选端点、状态、冲突原因 |
| `section_matches` | `list_section_matches(cross_section_id|page_id)`；有 `cross_section_id` 时可 `match_section_caption(write_back=false)` | 断面匹配状态、逻辑键、符号体系、候选/正式区分 |
| `table_caption_status` | 第一阶段优先 `get_page_source_facts(page_id)`；缺专用 facade 查询时返回 `partial` 和 unsupported | 表格与表格标题存在性、是否缺少状态能力 |
| `diagnostic_status` | 根据 scope 组合 `get_page_source_facts()`、`get_block_trace()`、`get_block_relations()`、语义查询 | 导入、增强、语义证据、候选状态 |
| `unknown_or_unsupported` | 不调用底层 facade，或只做最小 scope 校验 | 返回 unsupported reason |

### 5.3 CLI API

建议命令：

```text
python scripts\drawing_graph_qa.py ask-page --page-id <page_id> --format json
python scripts\drawing_graph_qa.py ask-block --block-id <block_id> --format zh-brief
python scripts\drawing_graph_qa.py ask-candidates --page-id <page_id> --format json
python scripts\drawing_graph_qa.py ask-section --cross-section-id <cross_section_id> --format json
python scripts\drawing_graph_qa.py ask-table-caption --page-id <page_id> --format json
python scripts\drawing_graph_qa.py diagnose --block-id <block_id> --format zh-brief
```

CLI 返回规则：

- 成功：stdout 输出 JSON 或简短中文，退出码 `0`。
- 已知业务错误：stderr 输出结构化错误 JSON，退出码 `1`。
- 配置或依赖初始化失败：stderr 输出脱敏错误 JSON，退出码 `2`。

错误 JSON 建议：

```text
{
  "status": "failed",
  "category": "INVALID_ARGUMENT",
  "message": "page_id is required for page_summary"
}
```

### 5.4 后续 HTTP API

第二阶段建议 HTTP 接口：

| 方法 | 路径 | 对应问题类型 |
|---|---|---|
| `POST` | `/drawing-qa/ask` | 通用 QARequest |
| `GET` | `/drawing-qa/pages/{page_id}/summary` | `page_summary` |
| `GET` | `/drawing-qa/blocks/{block_id}/relations` | `block_relations` |
| `GET` | `/drawing-qa/candidates` | `candidate_relations` |
| `GET` | `/drawing-qa/section-matches` | `section_matches` |

HTTP 层不在第一阶段实现。实现时仍只调用 `DrawingGraphQAService`，不直接调用 facade 或 repository。

### 5.5 后续 MCP Tool API

第三阶段可选 MCP 工具：

```text
ask_drawing_page
ask_drawing_block
list_drawing_candidates
match_section_caption_dry_run
get_table_caption_status
```

MCP 工具只包装 QAService 的稳定问题类型，不暴露任意 Cypher，不暴露 repository，不暴露完整 facade 内部方法集。

## 6. 前后端流程

当前项目没有真实前端。这里的“前端”指 CLI、Codex Skill、HTTP 客户端、Ava 或 MCP 调用端；“后端”指 QAService、facade、Python 应用层和 Neo4j。

### 6.1 CLI 问答流程

```text
用户命令
  -> scripts/drawing_graph_qa.py
  -> argparse 参数校验
  -> ImportConfig.from_env()
  -> GraphDatabase.driver()
  -> create_neo4j_tool_facade(driver)
  -> DrawingGraphQAService(facade)
  -> QAService.ask(QARequest)
  -> QAAnswer
  -> JSON / zh-brief 渲染
```

说明：

- driver 只在 CLI adapter 最外层创建，与现有 `scripts/drawing_graph_tool.py` 一致。
- QAService 不知道 driver 的存在。
- CLI 结束时关闭 driver。
- CLI 不读取或修改真实 `data/` 文件。

### 6.2 Codex Skill 问答流程

```text
用户自然语言问题
  -> drawing-graph-operator Skill 判断是否属于图块图谱问题
  -> 读取当前项目文档和受影响文件
  -> 选择 QA CLI 或 facade CLI
  -> 执行只读查询
  -> 按 fact_kind 分层回答
```

说明：

- Skill 是操作层，不是业务逻辑。
- Skill 不封装真实数据、Neo4j 密码或供应商密钥。
- Skill 不直接写 Cypher，不直接调用 repository。

### 6.3 HTTP 问答流程

```text
HTTP 客户端 / Ava
  -> HTTP request
  -> HTTP 路由层校验请求体和路径参数
  -> app startup 中创建或复用 facade
  -> DrawingGraphQAService.ask()
  -> QAAnswer
  -> HTTP JSON response
```

说明：

- HTTP 层只做协议适配、连接生命周期、鉴权或本机访问限制、错误脱敏。
- HTTP 层不实现第二套 page/block/candidate 聚合逻辑。
- Neo4j 密码来自环境变量或受控配置，不来自请求体。

### 6.4 MCP 问答流程

```text
外部 Agent
  -> MCP tool call
  -> MCP adapter 参数校验
  -> DrawingGraphQAService.ask()
  -> QAAnswer
  -> MCP tool result
```

说明：

- MCP adapter 不暴露全部 facade 方法。
- MCP adapter 不接受 Cypher。
- MCP adapter 不提供写回类工具，除非后续单独设计权限和审核流程。

### 6.5 单个问题类型流程

`page_summary`：

```text
page_id
  -> get_page_source_facts(page_id)
  -> list_text_observations(page_id) 可选
  -> list_interpretations(page_id) 可选
  -> 统计元素、语义证据和 unsupported 状态
  -> QAAnswer
```

`block_relations`：

```text
block_id
  -> get_block_trace(block_id)
  -> get_block_relations(block_id)
  -> list_candidate_relations(block_id) 可选
  -> 区分正式派生关系和候选关系
  -> QAAnswer
```

`candidate_relations`：

```text
page_id / block_id
  -> list_candidate_relations()
  -> list_section_matches(statuses=("candidate",)) 可选
  -> 标注 fact_kind=candidate_relation
  -> QAAnswer
```

`section_matches`：

```text
cross_section_id / page_id
  -> list_section_matches()
  -> cross_section_id 存在时可 match_section_caption(write_back=false)
  -> formal 与 candidate 分开输出
  -> QAAnswer
```

`table_caption_status`：

```text
page_id / table_id / table_caption_id
  -> get_page_source_facts()
  -> 能确认来源元素存在性
  -> 如缺少 facade 专用派生状态查询，返回 partial + unsupported_parts
  -> QAAnswer
```

## 7. 异常处理

### 7.1 QA 错误分类

| 错误码 | 场景 | 是否可重试 |
|---|---|---|
| `INVALID_ARGUMENT` | 缺少必需 ID、非法 question type、非法 format、多个互斥 scope 冲突 | 否 |
| `UNSUPPORTED_QUESTION` | 问题类型不在当前 QA 能力内 | 否 |
| `UNSUPPORTED_SCOPE` | 当前问题类型不支持给定 scope，例如 table caption 只给了 block ID | 否 |
| `NOT_FOUND` | facade 返回页面、block、候选、断面或语义证据不存在 | 否 |
| `PARTIAL_ANSWER` | 主要问题可回答，但部分语义证据、候选或表格标题状态不可用 | 否 |
| `WRITE_BACK_FORBIDDEN` | 第一阶段 QA 请求传入 `write_back=true` | 否 |
| `FACADE_UNAVAILABLE` | facade 未配置或初始化失败 | 是 |
| `NEO4J_UNAVAILABLE` | 底层 read port 或 Neo4j 查询不可用 | 是 |
| `SEMANTIC_EVIDENCE_UNAVAILABLE` | 语义 repository、payload 或 run log 不可用 | 是 |
| `INTERNAL_ERROR` | 未分类异常，输出前必须脱敏 | 视情况 |

### 7.2 错误转换规则

QAService 捕获 facade 的 `ToolModelError` 或等价错误后转换为 QA 层错误：

| facade 错误 | QA 层处理 |
|---|---|
| `INVALID_ARGUMENT` | 转为 `INVALID_ARGUMENT` |
| `NOT_FOUND` | 转为 `NOT_FOUND`；如果是可选语义查询，则降级为 warning |
| `WRITE_BACK_FORBIDDEN` | 转为 `WRITE_BACK_FORBIDDEN` |
| `NEO4J_UNAVAILABLE` | 转为 `NEO4J_UNAVAILABLE` |
| `SEMANTIC_EVIDENCE_UNAVAILABLE` | 对必需语义问题转错误；对 page/block 摘要转 warning |
| `PAYLOAD_UNAVAILABLE` | 若 `include_payload=false` 不应发生；否则转 warning 或错误 |
| `RECOGNITION_FAILED` | 第一阶段 QA 默认不触发识别；若后续启用 dry-run 识别，转为 warning |

### 7.3 降级原则

- 页面来源事实可用但语义证据不可用时，`page_summary` 返回 `partial`，保留来源事实。
- block trace 可用但候选关系查询不可用时，`block_relations` 返回 `partial`，保留正式派生关系。
- 候选关系为空不是错误；应返回 `answered` 或 `not_found` 取决于 scope 是否存在。
- `table_caption_status` 第一阶段如果无法获取派生状态，应返回 `partial`，并把缺失的 facade 能力写入 `unsupported_parts`。
- 不用空字符串、默认值或猜测填补缺失事实。

### 7.4 CLI 错误输出

CLI stderr 输出必须脱敏：

- 不输出 Neo4j 密码。
- 不输出完整 Cypher。
- 不输出 driver/session/transaction 栈细节。
- 不输出供应商 key 或 `.env` 内容。

CLI 可输出：

- 错误分类。
- 简短用户可理解原因。
- 是否可重试。
- 需要补充的 ID 或运行前置条件。

## 8. 安全方案

### 8.1 只读与写回边界

- 第一阶段 QAService 强制只读。
- `QARequest.write_back` 缺省为 `false`。
- 第一阶段传入 `write_back=true` 时直接返回 `WRITE_BACK_FORBIDDEN`。
- QAService 不调用 `review_candidate_relation(write_back=true)`。
- QAService 不调用 `recognize_page_semantics(write_back=true)`。
- `match_section_caption` 只能以 `write_back=false` dry-run 方式调用。

### 8.2 数据库访问安全

- QAService 不接收 Neo4j URI、用户、密码。
- QAService 不创建 Neo4j driver。
- QAService 不接收或生成 Cypher。
- QAService 只通过注入的 `DrawingGraphToolFacade` 查询。
- CLI/HTTP/MCP adapter 不开放任意图查询。

### 8.3 事实分层安全

QA 输出必须保留事实层级：

| fact_kind | 允许来源 |
|---|---|
| `source_fact` | `PageSourceFacts`、`BlockTrace` 等来源事实 DTO |
| `derived_relation` | `BlockRelations` 中的正式派生关系 |
| `semantic_observation` | `SemanticObservationSummary` |
| `semantic_interpretation` | `SemanticInterpretationSummary` |
| `candidate_relation` | `CandidateRelationSummary`、candidate section match |
| `formal_relation` | formal section match 或已确认正式关系 |

禁止：

- 把 `candidate_relation` 写成 `formal_relation`。
- 把 `matched_candidate` 写成正式关系。
- 把模型 observation 或 interpretation 写成来源事实。
- 把 `BlockInterpretation.interpreted_type` 写入或表述为 `DrawingBlock.block_type`。

### 8.4 敏感信息安全

- 不把真实 `data/`、PNG/JSON、Neo4j 数据或 `.env` 内容写入 QA 文档、测试 fixture 或 Skill。
- QA CLI 和 HTTP 错误输出必须清洗 password、secret、token、Cypher 等敏感词。
- HTTP 请求体不接受 Neo4j 密码、供应商 API key 或 token。
- 模型 profile 和 prompt version 只能来自受控配置或已登记选项。

### 8.5 Adapter 安全

CLI：

- 只在最外层读取环境变量。
- 只在最外层创建和关闭 driver。
- 不把 driver 传给 QAService 以外的对象；实际由 facade 工厂处理。

HTTP：

- 只在 app startup/shutdown 管理连接生命周期。
- 默认本机或受控网络访问。
- 写回类接口不在第一阶段提供。

MCP：

- 只暴露少量 QA 工具。
- 不暴露通用 Cypher 或底层 facade 全方法。
- 不提供持久化写回，除非单独设计权限、审计和确认流程。

### 8.6 验证安全

- 单元测试使用 fake facade，不依赖真实 Neo4j。
- 如果运行 `python -m unittest discover tests -v` 时集成测试跳过，必须报告“集成测试跳过，live Neo4j 未验证”。
- 文档测试应检查：默认只读、`write_back=false`、候选不是事实、不直接写 Cypher、不提供 HTTP/MCP 已完成声明。

## 9. 设计取舍

### 9.1 推荐方案：QAService + DTO + adapter

推荐采用：

```text
adapter -> DrawingGraphQAService -> DrawingGraphToolFacade
```

优点：

- 最大化复用现有 facade、DTO、port 和 repository 边界。
- 不重写查询、导入、增强和语义证据层。
- CLI、HTTP、Skill、MCP 能共享同一个 QA 编排逻辑。
- 容易测试，可用 fake facade 覆盖大多数场景。

### 9.2 不推荐方案：adapter 直接组合 facade

不推荐让 CLI、HTTP、MCP 各自直接组合 facade 方法。短期看少一个模块，但会让三个 adapter 各写一套 page/block/candidate 聚合逻辑，后续输出不一致，候选关系也更容易被误表述。

### 9.3 不推荐方案：QAService 直接访问 Neo4j

不推荐 QAService 直接访问 Neo4j 或 `QueryService`。这会绕过当前已建立的 facade 安全边界，破坏“Tool adapter -> facade -> ports/services -> repository”的依赖方向。

## 10. 第一阶段完成标准

第一阶段设计落地后应满足：

1. `QARequest`、`QAAnswer`、`AnswerFact`、`EvidenceRef` 等 DTO 已定义并有单元测试。
2. `DrawingGraphQAService` 能通过 fake facade 回答 `page_summary`、`block_relations`、`candidate_relations`、`section_matches`、`table_caption_status`。
3. `table_caption_status` 若缺少 facade 只读能力，必须返回 `partial` 和 `unsupported_parts`，不能绕过 facade 写 Cypher。
4. `scripts/drawing_graph_qa.py` 支持 JSON 和简短中文输出。
5. 所有 QA 输出都明确 fact kind。
6. QA 第一阶段没有新增 schema、HTTP API、MCP Tool adapter、真实模型供应商、OCR 或数据库写回。
7. 文档同步当前实现状态，不能把后续阶段写成已完成能力。
