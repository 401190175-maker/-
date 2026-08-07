# 语义证据层功能分析报告

## 0. 分析范围与读取文件

本报告分析“增加语义证据层内容”这一新需求，只做架构、模块、方案和风险分析，不写代码，不修改 `src/`、`scripts/`、Schema 或测试。

已读取和核对的输入：

- `changes/tool-facade/proposal.md`
- `changes/tool-facade/design.md`
- `changes/tool-facade/tasks.md`
- `changes/tool-facade/Feature_Analysis_Report.md`
- `architecture.md`
- `Module.md`
- `README.md`
- `图块图谱方案.md`
- `图块图谱目标三层架构.svg`
- `src/`、`tests/`、`scripts/` 中与 `tool_facade`、`semantic_*`、`recognition_run_log`、`query_port`、`candidate_review`、`relation_repository` 相关的文件列表

文件名说明：

- 用户要求读取 `changes/tool-facade/architecture.md`、`modules.md`、`constraints.md`，但当前 `changes/tool-facade/` 实际存在的是 `proposal.md`、`design.md`、`tasks.md` 和 `Feature_Analysis_Report.md`。本报告按实际存在的 tool-facade 设计文件作为替代依据。
- 根目录实际模块记录文件名为 `Module.md`，不是 `modules.md`。
- 当前根目录已有 `architecture.md`、`图块图谱方案.md` 和 `图块图谱目标三层架构.svg`，三者共同定义“来源事实层 -> 空间与上下文派生关系层 -> 语义证据层”的目标架构。

状态边界：

- 已落地：基础导入、离线派生关系增强、候选关系复核骨架、只读查询、Python 应用层 `DrawingGraphToolFacade`、Tool DTO、read port、source fact query、`semantic_models.py`、`semantic_service.py`、`semantic_client.py`、`recognition_run_log.py`、`semantic_repository.py` 的应用层/内存边界。
- 仍未等同于完整终态：HTTP API、Agent Skill、MCP Tool adapter、真实云多模态供应商默认调用、全量自动语义扫描、完整 Neo4j 语义证据持久化、`MATCHES_SECTION_CAPTION` 终态闭环、跨符号体系别名规则的生产级配置与审核。
- 本报告把“当前代码已有边界”和“目标语义证据层终态”分开表达。

## 1. 当前架构是否支持？

结论：当前架构支持新增语义证据层，但属于“已有底座 + 部分应用层边界已落地 + 终态能力仍需分阶段补齐”的状态。

### 1.1 已经支持的基础

| 支持点 | 当前依据 | 对语义证据层的意义 |
|---|---|---|
| 来源事实层稳定 | `Project -> DrawingSet -> DrawingPage -> DrawingBlock` 和页面元素已由基础导入建立 | 语义识别可以绑定到稳定页面、元素、图片路径和 bbox |
| 空间与上下文派生关系层存在 | `HAS_CAPTION`、`HAS_ANNOTATION`、`HAS_SECTION_MARK`、`USES_BASIC_INFO`、`CANDIDATE_CAPTION_OF`、`CANDIDATE_HAS_SECTION_MARK` | 语义证据层可复用候选关系和空间证据，不需要重建图谱底座 |
| 候选关系机制存在 | `CandidateReviewService`、`accepted/rejected/unresolved`、硬规则提升 | 语义候选关系可以沿用“候选不是事实，accepted 仍需硬规则”的边界 |
| Tool Facade 边界已落地 | `tool_facade.py`、`tool_models.py`、`query_ports.py`、`source_fact_query.py` | 后续 Tool/Skill 可通过 facade 编排语义识别，而不是直接访问 Neo4j |
| 语义应用层模型已出现 | `semantic_models.py`、`semantic_service.py`、`semantic_client.py`、`recognition_run_log.py`、`semantic_repository.py` | 已具备 `RecognitionRun` 图谱外、`TextObservation` 图谱内、`write_back=false` dry-run 的代码边界 |
| 目标方案明确 | `图块图谱方案.md` 和 SVG 明确三层架构、缓存、候选、复核、正式关系边界 | 新需求有清晰的目标架构，不是从零定义 |

### 1.2 仍不完整的部分

| 缺口 | 当前判断 | 影响 |
|---|---|---|
| 完整 Neo4j 语义证据持久化仍需核实或扩展 | 当前文档强调 `TextObservation` 图谱内，但已有 repository 仍以 port/内存实现为主；是否已有生产 Neo4j 写入需以源码和测试进一步确认 | 若要长期查询语义证据，需要明确 Neo4j schema、写入白名单和集成测试 |
| `MATCHES_SECTION_CAPTION` 尚不是当前已完成闭环 | 根目录 `architecture.md` 仍说明该关系待 OCR 或人工文本字段支持；目标方案允许预留和分阶段实现 | 不能把剖面语义匹配写成已实现事实 |
| 图块、基础信息、表格解释仍是终态目标 | `图块图谱方案.md` 定义 `BlockInterpretation`、`BasicInfoInterpretation`、`TableInterpretation`，但当前落地程度需逐项确认 | 不能一次性承诺完整图纸语义理解 |
| 真实多模态供应商未默认接入 | `semantic_client.py` 当前目标是协议和 fake client，不默认真实云模型 | 需要后续独立配置、错误处理、成本和安全边界 |
| 运行日志生产级存储未完全定义 | `RecognitionRun` 图谱外是原则，但存储介质、索引、生命周期、迁移策略仍需明确 | 审计、成本统计和跨进程查询会受影响 |

因此，当前架构不是“完全已经支持语义证据层终态”，但已经很适合按阶段补齐：先固化语义证据数据契约和查询边界，再补持久化、缓存、候选语义关系、独立复核和正式关系写入。

## 2. 需要新增哪些模块？

当前代码已出现一批语义相关模块，因此“新增模块”应分成两类：一类是已存在但可能需要扩展的模块，一类是目标语义证据层仍缺少的模块。

### 2.1 已存在但需要扩展或固化的模块

| 模块 | 当前职责 | 需要补齐的语义证据层内容 |
|---|---|---|
| `semantic_models.py` | 定义 `TextObservation`、`RecognitionRunSummary` 和语义状态 | 扩展 `BlockInterpretation`、`BasicInfoInterpretation`、`TableInterpretation`、候选语义关系、证据引用、缓存状态、stale/failed/ambiguous 等状态 |
| `semantic_service.py` | 编排单页语义识别，区分 dry-run 与 write-back | 增加目标类型策略、裁剪输入构造、缓存命中、结构化输出校验、失败降级 |
| `semantic_client.py` | 多模态识别客户端协议和 fake client | 增加供应商适配边界、响应 JSON schema 校验、超时和重试分类 |
| `semantic_repository.py` | `TextObservation` 语义证据 repository port 和内存实现 | 增加 Neo4j 实现、`HAS_OBSERVATION`、`HAS_INTERPRETATION`、`SUPPORTED_BY`、候选语义边读写 |
| `recognition_run_log.py` | 图谱外 `RecognitionRun` 日志 port 和内存实现 | 增加文件/数据库型生产实现、查询索引、失败状态、成本统计、输入 hash |
| `tool_facade.py` | 统一只读查询、dry-run 识别、候选查询和审核入口 | 增加语义证据查询、解释查询、候选语义关系审核、统一证据输出 |
| `source_fact_query.py` | 获取单页来源事实、元素 bbox 和图片证据 | 扩展为语义识别输入构造的稳定来源，不承担模型调用 |
| `candidate_review.py` | 候选关系三态审核和硬规则 | 抽象或扩展语义候选审核请求，避免只适配空间候选 |

### 2.2 建议新增的目标模块

| 新增模块 | 建议文件 | 职责 |
|---|---|---|
| 语义证据 Neo4j repository 实现 | `semantic_neo4j_repository.py` 或在 `semantic_repository.py` 中新增受控实现 | 幂等写入 `TextObservation`、`Interpretation`、`HAS_OBSERVATION`、`HAS_INTERPRETATION`、`SUPPORTED_BY` 和候选语义边 |
| 语义 Schema 规格 | `semantic_schema.py` 或更新 `scripts/create_schema.cypher` 的语义段 | 定义 `TextObservation`、`BlockInterpretation`、`BasicInfoInterpretation`、`TableInterpretation` 的约束、索引和关系白名单 |
| 裁剪与图像输入服务 | `semantic_image_inputs.py` 或 `crop_service.py` | 根据 `page_id`、元素 bbox、图片路径、image hash 构造模型输入；不写图谱 |
| 缓存键与失效策略 | `semantic_cache.py` | 生成 cache key，判断图片、bbox、模型、prompt、规则版本、契约版本变化后的失效 |
| 断面标签规范化 | `section_label_normalization.py` | 识别符号体系、规范值、`normalized_section_key`，区分 `I-I`、`Ⅰ-Ⅰ`、`1-1` |
| 断面语义匹配服务 | `section_match_service.py` | 组合 `CrossSection` observation、`BlockCaption` observation、空间候选和硬规则，生成候选或正式匹配 |
| 图谱外别名规则配置 | `section_alias_rules.py` | 管理 `SectionLabelAliasRule` 的作用域、版本、确认状态和审计引用；不建 Neo4j 节点 |
| 解释 payload 存储 | `semantic_payload_store.py` | 保存完整不可变 JSON 解析产物，通过 `payload_ref` 引用 |
| 统一证据输出投影 | `semantic_query_projection.py` | 组合来源事实、空间关系、observation、interpretation、candidate/formal relation，形成稳定返回 |

## 3. 影响哪些已有模块？

| 已有模块 | 影响等级 | 影响说明 | 建议边界 |
|---|---|---|---|
| `architecture.md` | 高 | 需要同步“语义证据层哪些已落地、哪些仍是目标” | 明确不要把终态能力写成当前已完成 |
| `Module.md` | 高 | 需要记录新增语义模块职责、接口、依赖和数据变化 | 每完成一个阶段同步一次 |
| `README.md` | 中 | 需要补充语义识别 dry-run、write-back、查询和降级说明 | 不写 HTTP/Agent/MCP 使用说明，除非实际实现 |
| `scripts/create_schema.cypher` | 高 | 若 Neo4j 持久化 `TextObservation` 和 `Interpretation`，需要新增约束/索引 | 使用 `IF NOT EXISTS`，保持可重复执行 |
| `tool_facade.py` | 高 | 是语义识别、语义查询、候选审核的对外门面 | facade 不写 Cypher，不直接调用供应商，不绕过 `write_back` |
| `semantic_models.py` | 高 | 需要承载语义证据契约 | 严格区分 observation、interpretation、candidate、formal relation |
| `semantic_service.py` | 高 | 需要编排识别、缓存、写回、错误状态 | 不直接提升正式关系 |
| `semantic_repository.py` | 高 | 需要从内存/port 扩展到可持久化语义证据 | 不存 `RecognitionRun` 节点 |
| `recognition_run_log.py` | 高 | 需要生产级图谱外运行日志 | 与 Neo4j 核心图谱保持解耦 |
| `query_service.py` / `query_port_adapter.py` | 中 | 查询输出要包含语义证据和解释内容 | 继续返回稳定业务 ID，不暴露内部节点 ID |
| `relation_repository.py` | 中 | 可能需要新增 `CANDIDATE_MATCHES_SECTION_CAPTION` 和 `MATCHES_SECTION_CAPTION` 受控规格 | 不开放任意 relation spec |
| `candidate_review.py` | 中 | 语义候选关系也需要三态审核和硬规则 | 复用理念，避免强行混合不同候选证据结构 |
| `block_relation_enrichment.py` | 低到中 | 仍负责空间与上下文派生关系，可能提供候选输入 | 不塞入多模态识别逻辑 |
| `config.py` / `tool_factory.py` | 中 | 增加模型 profile、prompt version、run log store、payload store 配置 | Tool 请求不能传入密钥或 Neo4j 密码 |
| `tests/` | 高 | 需要新增语义模型、缓存、schema、repository、facade、候选审核和文档边界测试 | 单元测试用 fake client，不依赖真实云模型 |

## 4. 技术方案有哪些？

### 方案 A：仅文档补充型

做法：

- 只更新架构报告和规划文档。
- 把 `图块图谱方案.md` 中的语义证据层内容迁移或摘录到 `changes/语义证据层/`。
- 不新增源码任务。

适用场景：

- 现在只是做需求立项或设计评审。
- 还没准备进入实现。

### 方案 B：在现有 Tool Facade 基础上补全语义证据契约

做法：

- 复用已存在的 `tool_facade.py`、`semantic_models.py`、`semantic_service.py`、`recognition_run_log.py`、`semantic_repository.py`。
- 先扩展语义数据契约：`TextObservation`、`BlockInterpretation`、`BasicInfoInterpretation`、`TableInterpretation`、`HAS_OBSERVATION`、`HAS_INTERPRETATION`、`SUPPORTED_BY`、cache key、状态机。
- 保持 `write_back=false` 默认，只用 fake client 和内存/port 先完成契约验证。

适用场景：

- 需要快速把语义证据层从目标方案推进到可测试应用层。
- 暂时不接真实 Neo4j 语义写入和真实云模型。

### 方案 C：语义证据 Neo4j 持久化优先

做法：

- 先扩展 Neo4j Schema 和 `SemanticEvidenceRepository` 的 Neo4j 实现。
- 建立 `TextObservation`、各类 `Interpretation` 节点和关系白名单。
- `write_back=true` 后可跨进程查询语义证据。

适用场景：

- 已确认要把语义证据长期作为图谱可查询资产。
- 需要真实数据库级验收，而不是只做应用层 dry-run。

### 方案 D：CrossSection 断面匹配专项优先

做法：

- 围绕 `CrossSection -> BlockCaption -> DrawingBlock` 建立专项流程。
- 实现断面标签识别、符号体系规范化、同页标题候选、`CANDIDATE_MATCHES_SECTION_CAPTION`、独立复核和 `MATCHES_SECTION_CAPTION`。
- 其他 `BlockInterpretation`、`TableInterpretation` 后置。

适用场景：

- 当前业务最急的是剖面标记与断面标题匹配。
- 希望先做一个高价值闭环，而不是铺开所有语义对象。

### 方案 E：完整语义证据平台化

做法：

- 同时实现真实多模态供应商、裁剪、缓存、Neo4j 语义写入、运行日志生产存储、断面匹配、图块解析、基础信息解析、表格解析、候选审核、人工兜底和统一查询。

适用场景：

- 已有明确产品交付、模型供应商、部署方式、数据迁移方案和验收预算。

当前不推荐一次性采用，因为范围大、风险高，也容易把规划能力误写成已完成。

## 5. 优缺点比较

| 维度 | 方案 A：仅文档 | 方案 B：契约优先 | 方案 C：持久化优先 | 方案 D：断面专项 | 方案 E：完整平台化 |
|---|---|---|---|---|---|
| 改动量 | 最小 | 小到中 | 中 | 中 | 最大 |
| 见效速度 | 快 | 快 | 中 | 中 | 慢 |
| 可测试性 | 文档检查为主 | 强，fake client 可覆盖 | 强，需要数据库测试 | 强，业务闭环清楚 | 复杂 |
| 对现有架构扰动 | 无 | 小 | 中 | 中 | 大 |
| 与当前 Tool Facade 匹配 | 中 | 最强 | 强 | 强 | 强但过重 |
| 语义证据长期价值 | 低 | 中到高 | 高 | 中到高 | 高 |
| 业务闭环完整度 | 低 | 中 | 中 | 高，限断面场景 | 最高 |
| 风险 | 文档漂移 | 契约先行但持久化后置 | Schema/迁移风险 | 专项逻辑可能过窄 | 范围失控 |

## 6. 推荐方案

推荐采用“方案 B + 方案 C 的分阶段组合”，并把 `CrossSection` 专项作为第二个可交付闭环，而不是一开始就做完整平台化。

推荐路径：

| 阶段 | 目标 | 主要内容 | 不做什么 |
|---|---|---|---|
| 阶段 1：语义证据契约固化 | 把语义证据层边界变成清晰、可测试的应用层契约 | 扩展 `semantic_models.py`，定义 observation、interpretation、状态、cache key、payload_ref、证据关系 | 不接真实供应商，不写正式语义关系 |
| 阶段 2：语义证据持久化 | 让 `write_back=true` 的 observation 和 interpretation 可跨进程查询 | 增加 Neo4j 语义 Schema、repository 实现、`RecognitionRun` 图谱外生产存储 | 不把 `RecognitionRun` 建成图谱节点 |
| 阶段 3：统一查询输出 | 让 Tool facade 返回来源事实 + 空间关系 + 语义证据 | 扩展 `list_text_observations`、interpretation 查询、证据定位和降级状态 | 不暴露 Neo4j 内部 ID |
| 阶段 4：CrossSection 断面匹配闭环 | 实现第一个高价值语义关系场景 | 断面标签规范化、`CANDIDATE_MATCHES_SECTION_CAPTION`、独立复核、满足硬规则后写 `MATCHES_SECTION_CAPTION` | 不做跨页自动匹配，不跨符号体系猜测 |
| 阶段 5：图块/基础信息/表格解释 | 扩展到更宽的图纸语义问答 | `BlockInterpretation`、`BasicInfoInterpretation`、`TableInterpretation`、payload store | 不把 AI 推断写回 `DrawingBlock.block_type` |

推荐理由：

1. 当前代码已经有 Tool Facade 和语义应用层雏形，继续沿这个边界推进最顺。
2. 语义证据层的核心不是“调用模型”，而是把模型输出保存为可追溯、可缓存、可降级、可审核的证据；契约应先稳定。
3. `RecognitionRun` 图谱外、`TextObservation` 图谱内的边界已经被多份文档反复确认，不能因为实现方便而改成运行日志节点。
4. `CANDIDATE_*` 与正式关系分离是防止误把模型判断当事实的关键安全机制，应贯穿所有阶段。
5. 先做 CrossSection 专项能形成可验收业务闭环，同时不会阻塞后续图块、基础信息和表格解析。

## 7. 风险

### 7.1 高风险

| 风险 | 说明 | 缓解 |
|---|---|---|
| 把规划能力写成已实现 | `图块图谱方案.md` 是目标方案，当前代码只落地部分语义边界 | 文档中必须标注“当前实现”和“目标状态”；每阶段用测试和源码核实 |
| 模型输出污染来源事实 | 如果把 `raw_text`、`interpreted_type` 或结构化解析写回来源节点，会破坏三层边界 | 模型输出只进入 observation 或 interpretation；不得覆盖 `DrawingBlock`、`DrawingBasicInfo` 等来源事实 |
| `RecognitionRun` 被建成图谱节点 | 为了查询方便把运行日志写入 Neo4j 节点，会违背目标架构 | 运行日志保留图谱外存储；图谱内证据只保存 `recognition_run_id` |
| 候选关系被当正式事实 | `matched_candidate`、`CANDIDATE_*` 如果被查询层投影成事实，会误导后续 Agent 或用户 | 响应中明确 `fact_kind=candidate`；正式关系必须满足硬规则或独立复核 |
| 语义层塞进空间规则模块 | 把多模态识别放入 `block_relation_enrichment.py` 会混淆空间规则和模型观察 | 保持 `semantic_*` 独立；空间层只提供候选和定位证据 |
| `write_back` 边界失效 | dry-run 如果写入 run log、observation 或候选边，会破坏安全预期 | 所有持久化入口统一由 facade/service 检查 `write_back=true` |

### 7.2 中风险

| 风险 | 说明 | 缓解 |
|---|---|---|
| Schema 扩展影响现有图谱 | 新增语义节点和关系可能与现有白名单、约束、查询冲突 | 使用独立标签、独立关系规格、`IF NOT EXISTS`、回归测试 |
| 缓存失效规则不清 | 图片、bbox、模型、prompt、规则版本变化会影响复用 | cache key 明确包含 image hash、bbox、task type、model、prompt、规则和契约版本 |
| 断面标签规范化误合并 | `I-I`、`Ⅰ-Ⅰ`、`1-1` 外观相近但语义不同 | 默认不跨符号体系合并；别名规则必须有作用域、版本和确认状态 |
| 多模态复核自我确认 | 第二次复核如果只读取第一次识别文字，会形成自我循环 | 复核必须一次看到全部候选、原始裁剪、页面上下文、空间证据和已有观察 |
| 图谱外运行日志不可查询 | 如果只用内存日志，跨进程审计会丢失 | 生产阶段需要文件或数据库型 run log，实现查询索引和生命周期策略 |
| 统一输出过早膨胀 | 一次性返回全部语义内容可能导致 DTO 复杂 | 按 `include_semantics`、目标类型和状态过滤分层返回 |

### 7.3 低风险

| 风险 | 说明 | 缓解 |
|---|---|---|
| 文档文件命名不一致 | 用户提到的 `architecture.md/modules.md/constraints.md` 在 `changes/tool-facade` 下不存在 | 可后续补 `constraints.md` 或在报告中持续说明实际读取文件 |
| CLI 与 facade 边界重叠 | 未来可能同时有 CLI、facade 和 Tool adapter | CLI 保留显式批处理入口；facade 服务 Tool/Skill |
| 测试数量增加 | 语义证据层会新增多组单元测试 | 使用 fake client、fake ports、内存 repository 控制成本 |

## 8. 最终结论

当前架构支持增加语义证据层，而且已经具备较好的底座：来源事实层稳定，空间与上下文派生关系层已形成候选机制，Tool Facade 和语义应用层边界也已经开始落地。

但“完整语义证据层”不能直接宣称完成。应继续坚持三层原则：

```text
来源事实层
  -> 空间与上下文派生关系层
  -> 语义证据层
  -> 统一查询输出
```

推荐主线是：

1. 先固化语义证据数据契约和状态机。
2. 再补 Neo4j 语义证据持久化与图谱外 `RecognitionRun` 生产存储。
3. 再通过 Tool Facade 统一输出 observation、interpretation、candidate 和 formal relation。
4. 然后优先做 `CrossSection` 与 `BlockCaption` 的断面匹配闭环。
5. 最后扩展到图块解析、基础信息解析、表格解析和其他页面文字。

这个方案能最大化复用当前代码，又能守住项目最重要的安全边界：模型观察不是来源事实，候选关系不是正式关系，`RecognitionRun` 不进核心图谱，`write_back=false` 不产生持久化副作用。
