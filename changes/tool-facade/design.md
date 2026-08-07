# 最小 Tool Facade 技术设计

本设计基于 `changes/tool-facade/proposal.md`，目标是在不做无意义重构的前提下，为后续 Tool 或 Skill 提供一个稳定、窄口径、默认只读的应用门面。第一优先级是复用现有 `QueryService`、候选关系复核骨架和 Repository 边界；新增模块只承担 Tool 契约、语义证据扩展点和 `write_back` 边界收口。

## 1. 系统架构变化

当前系统的主要入口是 CLI、Service、Repository 和 Python 内部查询接口。Tool facade 引入后，外部 Tool 不再直接接触 Neo4j、Cypher、Repository、CLI 脚本或规则函数，而是只调用一个应用级门面。

推荐依赖方向如下：

```text
Tool adapter 或后续 Skill
  -> DrawingGraphToolFacade
      -> Tool DTO / error envelope
      -> Query / SourceFact read port
          -> QueryService
              -> Neo4j driver
      -> SemanticRecognitionService
          -> MultimodalRecognitionClient
          -> RecognitionRunLog port (graph-external)
          -> SemanticEvidenceRepository port (Neo4j semantic evidence)
      -> CandidateReviewService
          -> RelationRepository
              -> Neo4j driver
```

架构变化的核心是新增一层“应用门面”，而不是替换现有服务：

- `DrawingGraphToolFacade` 负责对外契约、输入校验、输出投影、错误封装和 `write_back` 策略。
- 现有 `QueryService` 继续作为内部查询能力，短期不强行拆分；facade 通过只读 port 或轻量适配器调用它。
- 现有候选关系复核骨架继续复用，但表述为“已具备复核入口和三态/硬规则机制”，不等同于完整的独立多模态复核流程已完成。
- 语义证据层作为新增能力接入，不塞进 `block_relation_enrichment.py`，也不把全部语义证据混进 `RelationRepository`。
- `RecognitionRun` 按 `图块图谱方案.md` 保持在图谱外运行日志中；`TextObservation` 才是图谱内语义证据节点，并通过 `recognition_run_id` 回查运行日志。

第一版架构允许 `QueryService` 仍然直接依赖 Neo4j driver，因为这是现状；但 Tool 层不能依赖它的内部 dict、driver 或 Cypher。后续如果查询复杂度上升，再把 `QueryService` 内部读模型拆成更细的 read repository，不能在本变更中提前大拆。

## 2. 新增模块

新增模块应只覆盖 Tool facade 所需的最小边界。

| 模块 | 建议文件 | 职责 | 是否首阶段必须 |
|---|---|---|---|
| Tool 应用门面 | `src/drawing_graph/tool_facade.py` 或 `src/drawing_graph/facade.py` | 暴露稳定业务方法；编排查询、识别、复核；统一校验 `write_back` | 是 |
| Tool DTO | `src/drawing_graph/tool_models.py` 或 `src/drawing_graph/facade_models.py` | 定义请求、响应、分页、证据定位、错误 envelope，不暴露 Neo4j 内部结构 | 是 |
| 查询 port | `src/drawing_graph/query_ports.py` 或 `src/drawing_graph/ports.py` | 定义 facade 依赖的只读最小接口，例如图纸册、页面、来源事实查询 | 建议首阶段引入 |
| 单页来源事实查询 | `src/drawing_graph/source_fact_query.py` 或 `QueryService` 小扩展 | 读取单页图片路径、尺寸、元素、bbox、source element id | 是 |
| 语义模型 | `src/drawing_graph/semantic_models.py` | 定义 `TextObservation`、识别状态、候选语义关系、证据引用；只保留 `RecognitionRun` 引用 DTO | 第二阶段 |
| 语义识别服务 | `src/drawing_graph/semantic_service.py` | 根据页面和 bbox 调用多模态客户端，生成 observation；处理 dry-run/write-back 分支 | 第二阶段 |
| 多模态客户端协议 | `src/drawing_graph/semantic_client.py` 或 `src/drawing_graph/recognition_client.py` | 定义云端多模态模型调用协议和 fake client；真实供应商后置 | 第二阶段 |
| 图谱外运行日志 | `src/drawing_graph/recognition_run_log.py` 或 `src/drawing_graph/run_log_repository.py` | 持久化和查询 `RecognitionRun` 运行日志；不作为知识图谱节点 | 第三阶段 |
| 语义证据 Repository | `src/drawing_graph/semantic_repository.py` | 写入/查询 `TextObservation`、候选语义关系、证据支持关系；不存储 `RecognitionRun` 节点 | 第三阶段 |

新增模块的边界要保持窄：

- facade 不写 Cypher。
- DTO 不持有 Neo4j driver 或 session。
- semantic service 不直接决定候选关系是否变正式事实。
- semantic repository 不承担图谱外运行日志。
- recognition run log 不连接成图谱节点。

## 3. 修改模块

现有模块只做必要适配，不做无意义重构。

| 现有模块 | 修改方式 | 修改原因 | 重构边界 |
|---|---|---|---|
| `src/drawing_graph/query_service.py` | 增加或复用图纸册、页面、图块追溯查询；必要时补一个单页来源事实查询投影 | 支撑 Tool 的只读能力 | 不把整个查询层重写成 repository 架构 |
| `src/drawing_graph/candidate_review.py` | 复用三态、硬规则和显式写回入口；可补充面向 facade 的 request/result 投影 | 支撑“显式审核候选关系”能力 | 不声称已有完整多模态复核；不让模型复核逻辑混入当前骨架 |
| `src/drawing_graph/relation_repository.py` | 仅在候选语义关系需要复用候选状态或提升机制时增加受控 relation spec | 避免 Tool 绕过硬规则直接写关系 | 不承载全部语义证据；不开放任意关系写入 |
| `src/drawing_graph/config.py` | 可增加 facade 工厂所需配置读取，例如模型 profile、run log 路径、默认 `write_back=false` | 集中配置来源 | Tool 请求中不接收 Neo4j 密码或供应商密钥 |
| `architecture.md` | 实现后再更新真实架构状态 | 避免文档与实现脱节 | 不能把语义证据层或 Tool adapter 提前写成已完成 |
| `README.md` | 实现后补充 facade 使用说明、dry-run 和 `write_back` 策略 | 面向用户说明边界 | 不写 Skill/HTTP 使用说明，除非实际实现 |
| `tests/` | 新增 facade 契约、只读查询投影、`write_back` 边界、fake client、图谱外 run log 边界测试 | 防止边界回退 | 不要求真实云模型或真实 Neo4j 才能跑单元测试 |

`ImportService`、`RelationEnrichmentService` 和对应 CLI 保持当前显式运行方式。最小 Tool facade 不把导入和离线增强作为首批 Tool 能力，以免把“查询/识别/审核”扩成“全流程自动处理平台”。

## 4. 数据模型变化

数据模型变化分为 Tool DTO、图谱内语义证据、图谱外运行日志和候选关系状态四类。

### 4.1 Tool DTO

Tool DTO 是对外契约，不等同于 Neo4j 节点结构。它们应该用稳定业务字段表达：

| DTO 类型 | 关键字段 | 说明 |
|---|---|---|
| 图纸册摘要 | `project_id`、`drawing_set_id`、`name`、`page_count` | 列图纸册返回 |
| 页面摘要 | `drawing_set_id`、`page_id`、`file_stem`、`page_number`、`image_path` | 列页面返回 |
| 来源事实 | `page_id`、`image_path`、`image_size`、`elements[]` | 单页来源事实返回 |
| 元素证据 | `element_id`、`element_type`、`bbox`、`normalized_bbox`、`source_label` | 定位证据的最小单位 |
| Tool 错误 | `code`、`message`、`details`、`retryable` | 所有 facade 方法统一返回或抛出 |

DTO 不暴露：

- Neo4j node labels 的完整内部组合。
- Cypher 查询片段。
- driver、session、transaction。
- 未稳定的内部 `dict` 字段。

### 4.2 图谱内语义证据

图谱内新增语义证据以 `TextObservation` 为第一阶段核心，不把模型输出直接当作正式事实。

`TextObservation` 建议字段：

| 字段 | 说明 |
|---|---|
| `observation_id` | 观察 ID |
| `recognition_run_id` | 回查图谱外运行日志 |
| `target_element_id` | 来源元素稳定 ID |
| `target_element_type` | 来源元素类型，例如 block、caption、table、annotation |
| `page_id` | 页面 ID |
| `raw_text` | 模型观察到的原文 |
| `normalized_text` | 规范化文本 |
| `bbox` / `normalized_bbox` | 裁剪或观察区域 |
| `confidence` | 置信度或模型自评 |
| `status` | `confirmed`、`matched_candidate`、`partial`、`ambiguous`、`not_found`、`recognition_failed` |
| `image_hash` | 图像或裁剪版本指纹 |
| `cache_key` | 缓存键 |
| `created_at` | 创建时间 |

关系建议：

```text
来源元素 -[:HAS_OBSERVATION]-> TextObservation
```

其中 `matched_candidate` 只表示“观察结果命中了候选”，不是正式图谱事实。

### 4.3 图谱外 RecognitionRun

`RecognitionRun` 不作为知识图谱节点，而是图谱外运行日志。它用于模型调用监控、审计、错误诊断、成本统计和证据回查。

运行日志建议字段：

| 字段 | 说明 |
|---|---|
| `recognition_run_id` | 运行 ID |
| `run_type` | `recognition` 或后续 `review` |
| `page_id` / `target_scope` | 本次调用范围 |
| `model_profile` | 模型配置名 |
| `model_name` / `model_version` | 实际模型信息 |
| `prompt_version` | 提示词版本 |
| `input_refs` | 图片、裁剪、元素 ID、上下文引用 |
| `status` | `succeeded`、`failed`、`partial`、`cancelled` |
| `error_summary` | 错误摘要 |
| `started_at` / `finished_at` | 时间 |
| `write_back` | 是否触发持久化 |
| `cost_summary` | 可选成本统计 |

`write_back=false` 的识别可以返回临时 `recognition_run_id`，但不保证之后可查询。只有 `write_back=true` 才写入图谱外运行日志，并允许后续通过 `recognition_run_id` 查询。

### 4.4 候选语义关系

候选语义关系继续使用 candidate 思路，不新增 `RelationAssessment` 节点。

候选边建议保留：

- `candidate_group_id`
- `relation_type`
- `status`
- `score`
- `conflict_reason`
- `evidence_ids`
- `recognition_run_id`
- 后续独立复核产生的 `review_run_id`
- `reviewer`
- `review_reason`
- `reviewed_at`

正式关系只能在满足硬规则后写入。多模态输出、候选边、人工审核都不能绕过这条边界。

## 5. API 设计

这里的 API 指 Python 应用 facade 的业务方法契约，不是 HTTP/REST API，也不是 MCP Tool adapter 的最终协议。后续 MCP Tool 或 Skill 应只包装这些方法。

### 5.1 统一返回原则

所有 facade 方法应遵循：

- 输入使用明确请求 DTO。
- 输出使用明确响应 DTO。
- 失败返回统一错误 envelope 或抛出统一应用异常。
- 查询类方法只读。
- 写入类方法必须显式传入 `write_back=true`。
- 默认 `write_back=false`。

### 5.2 Tool facade 能力契约

| 方法能力 | 输入 | 输出 | 持久化 |
|---|---|---|---|
| 列出图纸册 | `project_id`、`limit`、可选分页 cursor | 图纸册摘要列表、分页信息 | 否 |
| 列出页面 | `drawing_set_id`、`limit`、可选分页 cursor | 页面摘要列表、分页信息 | 否 |
| 获取单页来源事实 | `page_id`、可选 `element_types`、可选 `include_image_meta` | 页面来源事实、元素证据列表、图片定位证据 | 否 |
| 执行单页语义识别 | `page_id`、`target_types`、`model_profile`、`prompt_version`、`write_back` | `recognition_run_id`、状态、观察摘要、错误摘要、是否持久化 | 仅 `write_back=true` |
| 查询 RecognitionRun | `recognition_run_id` | 图谱外运行日志摘要 | 否 |
| 查询 TextObservation | `page_id`、`element_id` 或 `recognition_run_id`，可选状态过滤 | 观察列表、证据定位、分页信息 | 否 |
| 查看候选语义关系 | `page_id`、`block_id`、`relation_type`、`status` | 候选组、候选端点、证据 ID、分数、冲突原因 | 否 |
| 显式审核候选关系 | `candidate_group_id`、`decision`、`reviewer`、`reason`、`write_back` | 审核状态、是否提升、失败原因 | 仅 `write_back=true` |

### 5.3 write_back 规则

`write_back` 是 facade 的硬边界：

- 未提供 `write_back` 时按 `false` 处理。
- `write_back=false` 时，识别可以执行并返回临时结果，但不得写入 `RecognitionRun` 运行日志、`TextObservation`、候选边或审核状态。
- `write_back=false` 时调用审核候选关系，只能返回“将会如何处理”的 dry-run 结果，不得实际更新候选状态。
- `write_back=true` 时，facade 才能调用图谱外 run log 和 Neo4j 语义证据写入能力。
- 即使 `write_back=true`，候选关系提升仍必须通过 `CandidateReviewService` 和硬规则校验。

### 5.4 facade 与 Tool adapter 的关系

Tool adapter 只负责协议适配：

- 把外部 Tool 输入转换为 facade request DTO。
- 调用 facade。
- 把 facade response DTO 转换为 Tool 输出。

Tool adapter 不负责：

- 创建 Neo4j driver。
- 写 Cypher。
- 调用 Repository。
- 调用 `scripts/`。
- 调用 `block_relation_enrichment.py` 内部规则函数。
- 直接调用外部模型供应商。
- 直接决定候选关系是否提升为正式关系。

## 6. 异常处理

异常处理目标是让 Tool 得到稳定、可解释、不会泄露内部实现的错误。

### 6.1 错误分类

| 错误码 | 场景 | 是否可重试 |
|---|---|---|
| `INVALID_ARGUMENT` | 缺少 `page_id`、非法 `limit`、未知 `decision`、`target_types` 为空 | 否 |
| `NOT_FOUND` | 图纸册、页面、元素、候选组或运行日志不存在 | 否 |
| `WRITE_BACK_REQUIRED` | 需要持久化但 `write_back=false` | 否 |
| `WRITE_BACK_FORBIDDEN` | 只读能力被传入写回意图，或 Tool 试图绕过 facade 写入 | 否 |
| `RECOGNITION_FAILED` | 多模态识别调用失败或返回不可解析结果 | 视供应商错误而定 |
| `RUN_LOG_UNAVAILABLE` | 图谱外运行日志不可用 | 是 |
| `SEMANTIC_EVIDENCE_UNAVAILABLE` | 语义证据仓储不可用 | 是 |
| `NEO4J_UNAVAILABLE` | Neo4j 连接、查询或事务失败 | 是 |
| `CANDIDATE_REVIEW_REJECTED` | 审核请求未通过硬规则校验 | 否 |
| `CONFLICT` | 候选关系状态已变化、重复审核或版本冲突 | 可按最新状态重试 |

### 6.2 处理原则

- facade 捕获底层异常后转换为稳定错误 envelope，不把 Cypher、driver 栈、密钥、文件系统敏感路径直接暴露给 Tool。
- 查询失败和写入失败要区分；写入失败不能伪装成 dry-run 成功。
- 多模态识别失败时，如果 `write_back=true` 且 run log 已创建，应记录失败状态；如果 run log 创建失败，应返回 `RUN_LOG_UNAVAILABLE` 或组合错误摘要。
- 语义证据写入失败时，不应自动创建正式关系；必要时保留失败状态供后续重试。
- 候选审核冲突时，以最新候选状态为准，返回冲突说明，不静默覆盖。
- 对外错误信息说清楚“用户能怎么处理”，内部诊断细节留在日志或测试输出。

## 7. 安全方案

安全方案重点是防止 Tool 越权写图谱、泄露底层数据库能力、把模型输出误写成事实。

### 7.1 数据库访问安全

- Tool adapter 不接收 Neo4j URI、用户名、密码。
- Tool adapter 不创建 Neo4j driver。
- Tool adapter 不开放 Cypher 字符串输入。
- facade 只通过内部 service、repository 或 port 访问 Neo4j。
- 查询 port 只暴露白名单业务查询，不提供通用图查询。

### 7.2 写回安全

- 所有写操作默认禁止，必须显式 `write_back=true`。
- `write_back=true` 只表示允许进入持久化流程，不表示跳过校验。
- 候选关系提升必须经过 `CandidateReviewService` 和硬规则校验。
- 模型识别结果只能先落为语义证据或候选关系，不能直接覆盖来源事实或正式关系。
- 对已有正式关系的冲突不得由模型自动覆盖；需要保留冲突候选，必要时人工最终确认。

### 7.3 模型调用安全

- 第一版不默认调用真实外部模型供应商；测试使用 fake client。
- 模型 profile、prompt version 和供应商密钥来自受控配置，不来自 Tool 请求自由文本。
- Tool 请求可以选择已配置的 `model_profile`，不能直接传入任意 API key。
- 传给模型的输入只包含当前页面或目标元素所需的最小图片、bbox 和上下文。
- 失败、超时、不可解析输出统一归入识别错误，不写入正式事实。

### 7.4 证据与审计安全

- `TextObservation` 必须保留 `recognition_run_id`、bbox、来源元素 ID 和状态。
- `RecognitionRun` 只存在于图谱外运行日志，不建立 Neo4j 节点。
- 候选边或正式边如果引用模型复核，应记录 `review_run_id`，并可回查完整候选集合、复核模型和提示词版本。
- dry-run 结果必须标明 `persisted=false`，避免用户误以为已经写入。
- 对外响应返回稳定业务 ID 和证据定位，不返回数据库内部实现细节。

### 7.5 分阶段安全落地

| 阶段 | 安全重点 |
|---|---|
| 第 1 阶段：只读 facade | 验证 Tool 不依赖 Neo4j driver、不写 Cypher、不暴露内部 dict |
| 第 2 阶段：dry-run 识别 | 验证 `write_back=false` 不产生任何持久化副作用 |
| 第 3 阶段：持久化语义证据 | 验证 `RecognitionRun` 在图谱外、`TextObservation` 在图谱内，二者只通过 ID 关联 |
| 第 4 阶段：候选审核 | 验证候选关系不被当作正式事实，accepted 仍需硬规则校验 |

## 实施约束

- 禁止无意义重构：不重写导入、离线增强、Neo4j repository 或 CLI。
- 优先复用已有架构：查询复用 `QueryService`，候选审核复用 `CandidateReviewService` 思路，持久化继续通过受控 Repository/port。
- 第一版只建立 facade 契约和最小只读能力；语义证据层按阶段接入。
- 文档和实现状态必须分开表达：未实现的语义证据层、Tool adapter、Skill、HTTP API 不能写成已完成。
