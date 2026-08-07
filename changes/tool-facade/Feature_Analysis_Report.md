# Tool Facade 功能分析报告

## 0. 分析范围与输入文件

本报告分析“做 Tool facade”这一新需求，只做架构与变更影响分析，不写业务代码，不修改 `src/`、`scripts/` 或测试。

已读取和核对的输入：

- `architecture.md`
- `Module.md`
- `README.md`
- `changes/tool-facade/proposal.md`
- `changes/tool-facade/design.md`
- `changes/tool-facade/tasks.md`
- `src/drawing_graph/`
- `scripts/`
- `tests/`

文件名说明：

- 用户要求读取 `modules.md`，仓库当前实际文件名为 `Module.md`，本报告按实际文件读取。
- 用户要求读取 `constraints.md`，仓库当前不存在该文件。本报告将 `architecture.md`、`README.md` 和 `changes/tool-facade/*` 中已经明确的边界作为约束来源，并在风险中记录该缺口。

当前实现边界：

- 已实现：来源事实导入、离线派生关系增强、候选关系复核骨架、只读查询。
- 未实现：Tool facade、完整语义证据层、OCR、HTTP/REST API、Agent Skill。
- 本报告不把 `RecognitionRun`、`TextObservation` 或语义候选关系描述为已完成能力。

## 1. 当前架构是否支持

结论：当前架构“部分支持”，适合以最小增量方式建设 Tool facade，但不能直接把现有模块暴露为 Tool。

已经支持的基础：

| 支持点 | 当前依据 | 对 Tool facade 的意义 |
|---|---|---|
| 来源事实导入闭环已存在 | `ImportService`、`Neo4jRepository`、`scripts/import_json.py` | Tool 可在后续阶段暴露导入能力，但不是首批必须 |
| 查询能力已存在 | `QueryService.get_project_sets()`、`get_set_pages()`、`get_page_blocks()`、`get_block_trace()`、`get_block_relations()`、`get_batch_status()` | 可作为 facade 只读能力的底层来源 |
| 离线增强与基础导入分离 | `RelationEnrichmentService`、`RelationRepository`、`scripts/enrich_block_relations.py` | Tool 可避免把导入和增强绑成隐式自动流程 |
| 候选复核骨架已存在 | `CandidateReviewService`、`RelationRepository.update_candidate_review()`、`promote_candidate_relation()` | 可复用 accepted/rejected/unresolved 和硬规则思想 |
| 写入安全边界已有雏形 | 固定 Label、关系白名单、参数化 Cypher、候选提升硬规则 | facade 可延续这些安全边界 |

当前不直接支持的部分：

| 缺口 | 现状 | 对 Tool facade 的影响 |
|---|---|---|
| 没有 facade 模块 | `src/drawing_graph/` 下没有 Tool 入口 | Tool adapter 若现在接入，只能直接调内部服务 |
| 查询返回多为 `dict[str, object]` | `QueryService` 直接返回字典投影 | Tool schema 不够稳定，字段版本化困难 |
| 查询层直接依赖 Neo4j driver | `QueryService(driver)` 内部执行 Cypher | Tool 若直接调它，容易继承数据库耦合 |
| 语义证据层不存在 | 未发现 `RecognitionRun`、`TextObservation` 相关源码或 Schema | 语义识别、证据查询、候选语义关系必须新增 |
| `write_back` 边界尚未落到代码 | 当前 CLI 有显式流程，但没有 Tool 级 write_back 策略 | 需要由 facade 统一执行默认只读或 dry-run |
| relation batch 审计为内存存储 | `RelationAuditStore` 当前是内存摘要 | Tool 跨进程查询增强批次状态时存在限制 |

因此，当前架构可以支撑一个“应用 facade + DTO + ports”的最小设计，但不适合采用“Tool 直接调用 QueryService/Repository”的方式。

## 2. 需要新增哪些模块

建议新增模块按“最小可用 + 语义证据预留”组织，避免一次性重构现有导入和增强流程。

### 2.1 Tool facade 层

| 新增模块 | 职责 |
|---|---|
| `tool_facade.py` | 面向 Tool adapter 的应用门面；负责输入校验、调用现有服务、封装响应、执行 `write_back` 策略 |
| `tool_models.py` | 定义 Tool 请求、响应、错误 envelope、分页信息、证据定位 DTO |
| `tool_errors.py` 或纳入 `tool_models.py` | 定义 Tool 级错误分类，如 `invalid_request`、`not_found`、`dependency_unavailable`、`write_back_required` |

### 2.2 只读来源事实查询能力

| 新增模块 | 职责 |
|---|---|
| `source_fact_query.py` | 读取单页来源事实、图片路径、尺寸、页面元素、bbox 和来源元素 ID |
| `query_ports.py` 或 `ports.py` | 定义 facade 依赖的只读查询最小接口，避免 facade 直接依赖 Neo4j driver |

说明：也可以短期扩展 `query_service.py`，但更推荐新增 `source_fact_query.py`，避免 `QueryService` 继续变成所有只读能力的集合。

### 2.3 语义证据层

| 新增模块 | 职责 |
|---|---|
| `semantic_models.py` | 定义 `RecognitionRun`、`TextObservation`、识别状态、候选语义关系、证据引用 |
| `semantic_service.py` | 编排页面语义识别：读取页面定位证据、调用多模态客户端、生成 run 和 observation |
| `semantic_repository.py` | 持久化和查询 `RecognitionRun`、`TextObservation`、候选语义关系 |
| `semantic_client.py` | 定义多模态识别客户端协议和 fake client，具体模型供应商后置 |

语义证据层不应放入 `block_relation_enrichment.py`。该文件当前承担空间与上下文派生规则，继续塞入多模态识别会造成规则层和模型调用耦合。

### 2.4 候选语义关系审核能力

| 新增或扩展模块 | 职责 |
|---|---|
| `semantic_candidate_review.py` | 如语义候选关系与现有空间候选关系差异较大，可新增独立审核服务 |
| 扩展 `candidate_review.py` | 如语义候选仍采用同一 accepted/rejected/unresolved 结构，可复用并扩展现有服务 |

推荐先不要强行合并。空间候选关系和语义候选关系的证据来源不同，早期可以共享状态理念，但保持请求/响应契约独立。

## 3. 影响哪些已有模块

| 现有模块 | 影响 | 建议 |
|---|---|---|
| `query_service.py` | 当前可支撑列图纸册、列页面、图块追溯和图块关系，但缺少单页来源事实完整查询 | 不直接暴露给 Tool；由 facade 或 read port 包装；必要时新增页面来源事实查询 |
| `candidate_review.py` | 已有候选组复核、三态结果、硬规则、写回逻辑 | 复用审核理念；语义候选是否共用服务需看证据结构 |
| `relation_repository.py` | 当前负责空间候选关系、复核状态和候选提升写回 | 不应承载全部语义证据；只在需要复用正式关系提升时扩展受控规格 |
| `neo4j_repository.py` | 基础导入持久化 | 首批 Tool facade 不需要直接使用；后续导入 Tool 可通过 `ImportService` 间接使用 |
| `import_service.py` | 导入编排 | 当前不作为最小 facade 首批能力；后续如果加导入 Tool，应通过 facade 调用 |
| `relation_service.py` | 离线增强编排 | 当前不作为最小 facade 首批能力；后续可暴露显式增强 Tool |
| `config.py` | 环境变量读取 | facade 工厂可能复用配置，但 Tool 请求本身不应接收密码 |
| `audit.py` | 导入和增强审计 | 可扩展语义识别审计，但不建议混用所有统计口径 |
| `architecture.md` | 当前架构说明 | 实现后需更新 Tool facade 和语义证据层状态 |
| `README.md` | 用户说明 | 实现后需补充 facade 使用、write_back、dry-run、语义证据查询说明 |
| `Module.md` | 模块记录 | 实现后需记录新增模块职责、接口和依赖 |
| `tests/` | 当前覆盖导入、增强、查询和候选复核 | 需新增 facade、source fact query、semantic models、write_back 边界、fake client 测试 |

## 4. 技术方案有哪些

### 4.1 方案一：直接包装现有 Service

做法：

- Tool facade 直接持有 `QueryService`、`CandidateReviewService`、`RelationRepository`。
- 查询直接复用 `QueryService` 返回字典。
- 审核直接复用 `CandidateReviewService.review_candidate_group()`。
- 语义识别后续再补。

适用场景：

- 只想快速把已有查询暴露出来。
- 暂时不做语义证据层。

### 4.2 方案二：应用 facade + DTO + ports

做法：

- 新增 `DrawingGraphToolFacade`。
- 新增 Tool 请求/响应 DTO 和统一错误 envelope。
- facade 依赖窄接口，例如 source fact read port、query port、semantic evidence port。
- Neo4j driver 只出现在 Repository 或具体 port 实现里。
- 语义证据层通过独立 `semantic_*` 模块接入。
- 所有持久化由 facade 统一检查 `write_back=true`。

适用场景：

- 既要最小实现，又要为语义证据层和后续 Skill 留稳定边界。
- 不希望 Tool 直接暴露内部 Service、Repository 或 Cypher。

### 4.3 方案三：完整 Tool/Skill 平台化

做法：

- 同时实现 Tool facade、Tool adapter、Skill 工作流、完整语义证据层、模型适配、缓存、批次持久化、候选审核和正式提升。

适用场景：

- 已经确定 Tool/Skill 最终产品形态、调用协议、模型供应商和持久化 Schema。

当前不推荐该方案，因为语义证据层尚未实现，过早平台化会制造未验证抽象。

## 5. 优缺点比较

| 维度 | 方案一：直接包装 | 方案二：facade + DTO + ports | 方案三：完整平台化 |
|---|---|---|---|
| 首次改动量 | 最小 | 小到中 | 最大 |
| 上手速度 | 最快 | 较快 | 慢 |
| Tool 契约稳定性 | 弱 | 强 | 强 |
| Neo4j 隔离 | 弱 | 强 | 强 |
| 语义证据层扩展 | 弱，后续易返工 | 好 | 理论最好 |
| 对现有代码扰动 | 小 | 小到中 | 大 |
| 测试难度 | 低 | 中 | 高 |
| 风险 | 短期快，长期耦合 | 平衡 | 范围失控 |

## 6. 推荐方案

推荐方案二：应用 facade + DTO + ports。

推荐理由：

1. 它与当前项目已有分层最匹配。当前已经有 CLI、Service、Repository、规则模块，但缺少面向 Tool 的应用门面。补 facade 是顺势而为，不是重建系统。
2. 它能保留当前显式流程边界。基础导入、离线增强、候选复核仍是显式流程，不会因为 Tool 入口出现而隐式自动写库。
3. 它能把 `write_back` 做成统一硬边界。默认只读或 dry-run，只有用户显式传入 `write_back=true` 才持久化。
4. 它能给语义证据层留下清晰位置。`RecognitionRun`、`TextObservation`、多模态客户端、语义证据仓储独立演进，不污染现有空间规则模块。
5. 它能支持后续 Skill。Skill 应编排 Tool，而不是直接调用 Neo4j、Repository 或规则函数。

推荐的首批能力顺序：

| 阶段 | 目标 | 能力 |
|---|---|---|
| 第一阶段 | 只读 Tool facade | 列图纸册、列页面、获取单页来源事实、查询图块追溯、查询图块关系 |
| 第二阶段 | 语义识别 dry-run | 执行页面多模态识别，但 `write_back=false` 时只返回临时 run 和 observations |
| 第三阶段 | 语义证据持久化 | `write_back=true` 时持久化 `RecognitionRun` 和 `TextObservation`，并支持查询 |
| 第四阶段 | 候选语义关系审核 | 查看候选语义关系，显式审核，accepted 后仍需硬规则校验 |

推荐的依赖方向：

| 层级 | 职责 | 不应做的事 |
|---|---|---|
| Tool adapter | 接收外部 Tool 调用并转给 facade | 不创建 Neo4j driver，不写 Cypher |
| Tool facade | 业务输入输出、错误封装、write_back 策略、服务编排 | 不写具体规则，不直接拼接 Cypher |
| Application Service | 导入、增强、语义识别、候选审核等编排 | 不暴露给 Tool 直接调用 |
| Repository / Port implementation | 读写 Neo4j 或其他持久化后端 | 不绕过业务服务做正式事实提升 |
| Rule / Domain | 几何、ID、映射、候选判断、状态模型 | 不连接数据库，不调用模型供应商 |

## 7. 风险

### 7.1 高风险

| 风险 | 说明 | 缓解 |
|---|---|---|
| Tool 直接依赖 Neo4j | 若 Tool adapter 直接创建 driver 或调用 Repository，facade 失去意义 | Tool adapter 只调用 facade；Neo4j 只出现在 Repository 实现 |
| `write_back` 被绕过 | 语义识别或候选审核如果直接写库，会破坏 dry-run 边界 | 所有持久化入口集中到 facade 和 Service；默认 `write_back=false` |
| 语义证据被误当正式事实 | 模型输出可能被错误提升为图谱正式关系 | 区分 observation、candidate、formal relation；accepted 后仍需硬规则 |
| 语义证据层污染空间规则层 | 将多模态识别塞入 `block_relation_enrichment.py` 会扩大耦合 | 新增 `semantic_*` 模块，规则层只保留确定性空间/上下文逻辑 |
| QueryService 变成 Tool API | 直接把现有字典返回作为 Tool schema，后续字段难以演进 | 新增 DTO 和错误 envelope，facade 做稳定投影 |

### 7.2 中风险

| 风险 | 说明 | 缓解 |
|---|---|---|
| `constraints.md` 缺失 | 用户指定的约束文件不存在，约束来源分散 | 后续可补一个 `constraints.md`，集中记录 write_back、无 Skill、无 HTTP、无自动扫描等边界 |
| relation batch 状态不可跨进程稳定查询 | 当前 `RelationAuditStore` 为内存存储 | Tool 首期不承诺跨进程 relation batch 查询；后续再设计持久化审计 |
| 语义模型供应商过早绑定 | 直接绑定具体云模型会影响测试和替换 | 先定义 `semantic_client` 协议，用 fake client 测试 |
| 一次性改动范围过大 | 同时做 facade、语义层、审核和文档会增加回归风险 | 按四阶段实施，每阶段独立测试 |
| 源码中 `Any` 依赖较多 | 当前 Service/Repository 通过 `Any` 注入，缺少静态契约 | 在 facade 边界新增 ports 或 Protocol，先约束外部依赖 |

### 7.3 低风险

| 风险 | 说明 | 缓解 |
|---|---|---|
| CLI 与 facade 能力重叠 | 后续可能同时存在 CLI 和 Tool facade | CLI 继续保留；facade 作为应用入口，不替代脚本 |
| README 和 Module.md 滞后 | 新增 facade 后文档需要同步 | 每阶段完成后更新当前实现状态 |
| 测试数量增加 | 新增 facade 和语义层会增加测试文件 | 用 fake ports/fake client 控制测试成本 |

## 8. 最终结论

当前架构支持“最小 Tool facade”的建设，但支持方式应是新增应用门面和语义证据扩展点，而不是把现有 `QueryService`、`RelationRepository` 或 CLI 直接包装成 Tool。

推荐实施路径是：

1. 先做只读 facade，覆盖图纸册、页面、单页来源事实、图块追溯和图块关系。
2. 再做语义识别 dry-run，默认不持久化。
3. 再引入 `RecognitionRun`、`TextObservation` 的持久化查询。
4. 最后做候选语义关系和显式审核。

这条路径能最大化复用现有系统，又能为后续 Tool 和 Skill 留出干净边界。

## 9. 按已确认设计补充的最小 Tool facade 契约

本节根据已确认的功能地图和最小 Tool facade 设计进一步细化。这里的“最小”不是只包一层函数，而是先定义 Tool 对外能做什么、输入输出是什么、写回边界是什么；内部继续复用现有导入、查询、关系增强和候选复核模块，不为 Tool 一次性重构整个项目。

### 9.1 设计方案再确认

| 方案 | 做法 | 优点 | 缺点 |
|---|---|---|---|
| 方案 A：直接包 `QueryService` 和现有 Service | Tool facade 只是薄包装，读查询直接调用 `QueryService`，复核调用 `CandidateReviewService` | 改动最小，最快能跑 read-only 查询 | 容易把 Neo4j driver、`dict` 返回、内部字段泄露给 Tool；语义证据层没有稳定位置，后续会返工 |
| 方案 B：应用 facade + typed DTO + ports | 新增 `DrawingGraphToolFacade`，Tool 只调用 facade；facade 再调用现有 Service、查询 port、语义证据 Service | 边界最清楚，适合后续 Skill；可以保持小步实施 | 比方案 A 多几个请求/响应对象和接口契约 |
| 方案 C：完整 Tool/Skill 平台层 | 同时做 facade、MCP Tool、Skill、语义证据层、模型适配、缓存和审计 | 终态完整 | 当前范围太大，会把语义层和 Tool 层一起搅乱 |

继续推荐方案 B。它不是大重构，而是在现有系统外面加一个稳定应用门面：Tool 只认识业务请求和业务响应，不认识 Neo4j、不认识 Cypher、不直接碰规则函数。

### 9.2 推荐的最小 Tool 能力

| Tool 能力 | 输入 | 输出 | 写回 |
|---|---|---|---|
| 列出图纸册 | `project_id`、`limit` | `drawing_set_id`、名称、页面数或基础字段 | 否 |
| 列出页面 | `drawing_set_id`、`limit` | `page_id`、`file_stem`、`page_number`、`image_path` | 否 |
| 获取单页来源事实 | `page_id`、可选 `element_types` | 页面图片、尺寸、图块、标题、表格、基础信息、注释、bbox、source element id | 否 |
| 执行单页语义识别 | `page_id`、`target_types`、`model_profile`、`prompt_version`、`write_back` | `recognition_run_id`、状态、观察结果摘要、是否已持久化 | 只有 `write_back=true` |
| 查询 `RecognitionRun` | `recognition_run_id` | 模型、prompt、输入范围、状态、错误、时间、是否写回 | 否 |
| 查询 `TextObservation` | `page_id`、`element_id` 或 `recognition_run_id` | 原文、规范化文本、bbox、来源元素、置信度、状态、证据引用 | 否 |
| 查看候选语义关系 | `page_id`、`block_id`、`relation_type`、`status` | 候选关系、候选端点、证据 ID、分数、状态、冲突原因 | 否 |
| 显式审核候选关系 | `candidate_group_id`、`decision` 或复核请求、`reviewer`、`write_back` | `accepted`、`rejected` 或 `unresolved`、理由、是否提升正式关系 | 只有 `write_back=true` |

关键约束：`write_back=false` 时可以运行识别并返回临时结果，但不能保证之后还能通过 `recognition_run_id` 查到它。能长期查询的 `RecognitionRun` 和 `TextObservation` 必须来自 `write_back=true` 的持久化运行。

### 9.3 facade 与现有 Service 的关系

建议新增应用层 `DrawingGraphToolFacade`。它不做具体规则，只负责：

- 校验 Tool 输入。
- 创建或接收 Neo4j 相关依赖，但不把 driver 暴露给 Tool。
- 调用现有 `QueryService` 或查询 port 获取项目、图纸册、页面、图块关系。
- 调用新增的页面来源事实查询能力获取单页元素和 bbox。
- 调用新增的语义识别 Service。
- 调用新增的语义证据 Repository 查询 `RecognitionRun` 和 `TextObservation`。
- 调用候选关系审核 Service，并强制检查 `write_back=true` 才允许持久化。

现有 `ImportService` 和 `RelationEnrichmentService` 不优先暴露到最小 Tool facade。当前目标用例是“在已有图谱上查询、识别、审核”，不是让 Tool 负责导入和补关系。这样可以先把 facade 做薄，避免首期就引入导入、增强、识别、审核全流程自动编排。

推荐依赖方向：

```text
Tool adapter
  -> DrawingGraphToolFacade
      -> Query / SourceFact read port
      -> SemanticRecognitionService
      -> SemanticEvidenceRepository port
      -> CandidateReviewService
          -> Repository port
              -> Neo4j implementation
```

Tool adapter 不应做以下事情：

- 创建 Cypher。
- 直接持有 Neo4j driver。
- 直接调用 `RelationRepository.write_relations()`。
- 直接调用 `promote_candidate_relation()`。
- 直接调用 `block_relation_enrichment.py` 里的单条规则函数。
- 自己决定候选关系是否变成正式事实。

### 9.4 语义证据层放置方式

语义证据层应该是新增一层，不放进 `block_relation_enrichment.py`，也不塞进 `RelationRepository`。建议拆成三个能力：

| 新能力 | 职责 |
|---|---|
| 语义证据模型 | `RecognitionRun`、`TextObservation`、识别状态、模型版本、prompt 版本、bbox、image hash、cache key |
| 语义识别 Service | 根据 `page_id` 找图片和元素 bbox，裁剪或构造输入，调用多模态客户端，生成观察结果 |
| 语义证据 Repository | 持久化和查询 `RecognitionRun`、`TextObservation`、候选语义关系、证据支持关系 |

这层可以读取来源事实和图片定位证据，但不能把模型输出直接当正式图谱事实。候选语义关系应先是 candidate，审核通过后才可能转成正式关系。

### 9.5 现有文件影响和新增文件建议

预计影响的现有文件：

| 文件 | 影响 |
|---|---|
| `src/drawing_graph/query_service.py` | 可能新增或拆出“单页来源事实查询”；避免 Tool 直接消费内部 `dict` |
| `src/drawing_graph/relation_repository.py` | 后续如果候选语义关系复用现有候选/提升机制，需要增加受控规格；不建议直接混入所有语义证据写入 |
| `src/drawing_graph/candidate_review.py` | 可复用审核状态思路，但语义候选审核可能需要独立 request/result |
| `architecture.md`、`README.md`、`Module.md` | 需要新增 Tool facade 和语义证据层边界说明，且不能把未实现能力写成已完成 |
| `tests/` | 新增 facade、语义证据模型、`write_back` 边界、查询投影测试 |

建议新增文件：

| 新增能力 | 建议文件 |
|---|---|
| Tool facade | `tool_facade.py` 或 `facade.py` |
| Tool 请求/响应 DTO | `tool_models.py` 或 `facade_models.py` |
| 语义证据模型 | `semantic_models.py` |
| 语义识别编排 | `semantic_service.py` |
| 语义证据持久化 | `semantic_repository.py` |
| 多模态客户端协议/适配 | `semantic_client.py` 或 `recognition_client.py` |
| 单页来源事实查询 | 可先放查询模块扩展，后续再拆 `source_fact_query.py` |

### 9.6 分阶段实施建议

| 阶段 | 做什么 | 不做什么 |
|---|---|---|
| 第 1 阶段：只读 facade | 列图纸册、列页面、获取页面来源事实、获取图块追溯和关系 | 不接模型，不写语义证据 |
| 第 2 阶段：语义证据模型和 dry-run 识别 | 定义 `RecognitionRun` / `TextObservation`，`write_back=false` 返回临时结果 | 不持久化，不生成正式语义关系 |
| 第 3 阶段：`write_back` 持久化 | `write_back=true` 时写入 run 和 observation，可查询历史 run | 不自动提升正式关系 |
| 第 4 阶段：候选语义关系和显式审核 | 生成候选语义关系，审核通过才持久化状态或提升 | 不做 Skill，不做 HTTP，不做全量自动扫描 |

最终设计结论：先做方案 B 的“应用 facade + DTO + 语义证据扩展点”。第一版 facade 只覆盖读查询和 `write_back=false` 的语义识别入口，把门面边界立稳；第二版再接 `RecognitionRun` / `TextObservation` 的持久化。这样最小，但不会短视。
