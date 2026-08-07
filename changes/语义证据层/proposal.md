# 语义证据层变更提案

## 1. 背景

当前图块图谱已经形成较稳定的两层底座：来源事实层负责从 XAnyLabeling JSON/PNG 中导入 `Project -> DrawingSet -> DrawingPage -> DrawingBlock` 及页面元素，空间与上下文派生关系层负责显式离线生成图块标题、页面基础信息上下文、注释、剖面标记、表格标题和候选空间关系。现有查询可以返回稳定业务 ID、图片路径、bbox、候选 ID 和派生关系状态，已经能够回答“对象在哪里”和“空间/上下文关系是什么”。

目标架构在此基础上进一步引入第三层：语义证据层。该层保存多模态模型对图纸局部区域或整体区域产生的文字观察、结构化解释、候选匹配、确认状态和推理来源。它不替代来源事实层，也不把模型输出直接写成正式图谱事实，而是把模型结果表达为可追溯、可缓存、可复核的证据。

当前代码已经出现 Tool Facade 和部分语义应用层边界，包括 `DrawingGraphToolFacade`、Tool DTO、只读 port、单页来源事实查询、`semantic_models.py`、`semantic_service.py`、`semantic_client.py`、`recognition_run_log.py` 和 `semantic_repository.py`。这些内容说明系统已经具备语义证据层的接入基础，但完整的终态能力仍需要分阶段补齐。

## 2. 当前问题

当前架构仍存在以下问题：

- 图谱可以定位页面、图块和页面元素，但缺少稳定的语义证据闭环，不能长期、统一地返回标题、注释、基础信息、表格、剖面标记和图块内部文字的可读语义内容。
- `TextObservation`、`BlockInterpretation`、`BasicInfoInterpretation`、`TableInterpretation` 等语义证据对象尚未形成完整的生产级数据契约、Schema、持久化和查询输出。
- `RecognitionRun` 已被确定为图谱外运行日志，但生产级存储、查询索引、失败状态、成本统计、输入 hash 和生命周期策略仍需明确。
- 当前 `write_back=false` 的 dry-run 边界已经在 Tool Facade 中形成，但完整语义证据持久化、缓存复用、缓存失效和跨进程查询仍需补齐。
- `MATCHES_SECTION_CAPTION` 仍不能作为当前已完成关系写入。断面匹配需要 `CrossSection` 与 `BlockCaption` 两侧都有可比较文本、符号体系、规范化逻辑键和候选证据，空间接近本身不能作为语义相等证据。
- 候选关系必须继续与正式事实分离。`matched_candidate`、`CANDIDATE_*` 和模型复核结果不能被查询层或后续 Tool/Skill 误投影为正式关系。
- 现有空间关系增强模块不应承载多模态模型调用。如果把语义识别塞进 `block_relation_enrichment.py`，会混淆确定性空间规则和模型观察证据。

## 3. 功能目标

本变更目标是在现有来源事实层和空间与上下文派生关系层之上，补齐独立语义证据层，使系统逐步具备以下能力：

- 定义并固化语义证据数据契约，包括 `TextObservation`、`BlockInterpretation`、`BasicInfoInterpretation`、`TableInterpretation`、语义状态、证据引用、缓存键、`payload_ref` 和版本字段。
- 保持 `RecognitionRun` 位于核心图谱之外，仅通过 `recognition_run_id` 与图谱内语义证据关联，用于回查模型、提示词、输入范围、图片 hash、运行状态、错误和时间信息。
- 将模型识别结果保存为 observation 或 interpretation，而不是覆盖 `DrawingBlock`、`DrawingBasicInfo`、`Table`、`BlockCaption` 等来源事实节点。
- 建立来源元素到语义观察的显性证据关系，例如 `来源元素 -[:HAS_OBSERVATION]-> TextObservation`。
- 建立来源元素到结构化解释的显性关系，例如 `DrawingBlock -[:HAS_INTERPRETATION]-> BlockInterpretation`、`DrawingBasicInfo -[:HAS_INTERPRETATION]-> BasicInfoInterpretation`、`Table -[:HAS_INTERPRETATION]-> TableInterpretation`。
- 建立解释与文字观察之间的证据支持关系，例如 `Interpretation -[:SUPPORTED_BY]-> TextObservation`。
- 支持 `write_back=false` dry-run 语义识别：可以返回临时识别结果，但不写入运行日志、语义证据或候选关系。
- 支持 `write_back=true` 语义证据持久化：写入图谱外 run log 和图谱内 observation/interpretation，并允许后续查询。
- 支持缓存键和缓存失效策略，使相同图片、bbox、任务类型、模型版本、提示词版本、规则版本和数据契约版本能够复用语义结果。
- 优先形成 `CrossSection` 与 `BlockCaption` 的断面匹配闭环：识别端点标签和标题文字，生成符号体系、规范值和 `normalized_section_key`，在证据唯一且硬规则满足时写入正式 `MATCHES_SECTION_CAPTION`，否则保留 `CANDIDATE_MATCHES_SECTION_CAPTION`。
- 统一 Tool Facade 查询输出，使后续 Tool/Skill 能通过稳定业务 ID、bbox、语义内容、状态和审计信息读取证据，而不是直接访问 Neo4j、Cypher 或内部 repository。

## 4. 修改范围

本变更建议按阶段推进，修改范围包括文档、数据契约、持久化、查询输出和断面专项能力。

### 4.1 语义证据数据契约

- 扩展 `semantic_models.py` 中的语义数据模型。
- 定义 `TextObservation` 的字段：观察 ID、`recognition_run_id`、目标元素 ID、目标元素类型、页面 ID、原始文本、规范化文本、bbox、置信描述、状态、图片 hash、缓存键、创建时间。
- 定义 `BlockInterpretation`、`BasicInfoInterpretation`、`TableInterpretation` 的结构化字段、自然语言摘要、状态、版本、`payload_ref`、不确定性和证据引用。
- 明确状态集合，例如 `confirmed`、`matched_candidate`、`partial`、`ambiguous`、`not_found`、`recognition_failed`、`interpreted`、`failed`、`stale` 等。

### 4.2 图谱外运行日志

- 扩展 `recognition_run_log.py` 的生产级 port 或实现。
- 保持 `RecognitionRun` 不作为 Neo4j 节点。
- 记录 `run_id`、`run_type`、任务范围、模型名称和版本、提示词版本、输入图片和内容 hash、开始/结束时间、状态、错误摘要和可选成本统计。
- 确保缓存命中和普通查询不创建新的运行日志。

### 4.3 语义证据持久化

- 扩展 `semantic_repository.py` 或新增受控 Neo4j repository 实现。
- 增加 `TextObservation`、`BlockInterpretation`、`BasicInfoInterpretation`、`TableInterpretation` 的图谱内持久化能力。
- 增加 `HAS_OBSERVATION`、`HAS_INTERPRETATION`、`SUPPORTED_BY` 等关系的白名单和幂等写入策略。
- 更新 Schema 初始化脚本，使用 `IF NOT EXISTS` 增加必要约束和索引。

### 4.4 语义识别编排与缓存

- 扩展 `semantic_service.py`，使其根据 `page_id`、目标元素类型、图片路径和 bbox 构造识别输入。
- 通过 `semantic_client.py` 的协议接入 fake client 或后续真实多模态客户端。
- 增加缓存键生成和缓存失效判断，避免重复识别相同有效输入。
- 保持 `write_back=false` 默认不持久化，只有显式 `write_back=true` 才写入图谱外运行日志和图谱内语义证据。

### 4.5 断面匹配专项

- 定义 `CrossSection` 与 `BlockCaption` 的通用断面标签规范化规则。
- 区分 `alphabetic`、`roman`、`numeric`、`alphanumeric` 和 `unknown` 符号体系。
- 默认不合并 `I-I`、`Ⅰ-Ⅰ` 和 `1-1`；跨符号体系匹配必须引用作用域明确、版本化、已确认的图谱外别名规则。
- 新增或扩展候选语义关系规格：`CANDIDATE_MATCHES_SECTION_CAPTION`。
- 在候选唯一、规范化逻辑键一致、同页范围满足且无规则冲突时，允许写入正式 `MATCHES_SECTION_CAPTION`。
- 多候选、证据冲突或规则边界不明确时，保留候选关系并进入独立多模态复核；复核仍 `unresolved` 时保持 `ambiguous`。

### 4.6 统一查询输出

- 扩展 Tool Facade 的语义证据查询能力。
- 查询结果同时返回稳定业务 ID、来源元素、图片路径、bbox、语义内容、状态、`recognition_run_id`、`review_run_id` 和候选/正式关系类型。
- 明确区分未识别、识别失败、未找到、候选匹配、歧义和正式确认。
- 不暴露 Neo4j 内部节点 ID、Cypher、driver、session 或 transaction。

## 5. 不包含范围

本变更不包含以下内容：

- 不实现 HTTP/REST API。
- 不实现 Agent Skill。
- 不实现 MCP Tool adapter 最终接入。
- 不实现全量自动语义扫描。
- 不实现全量离线 OCR。
- 不默认调用真实外部多模态模型供应商；真实供应商适配应后置并通过受控配置接入。
- 不让 Tool 请求传入 Neo4j 密码、供应商 API key、token 或 secret。
- 不让 Tool adapter 直接创建 Neo4j driver、写 Cypher、调用 repository 或调用 CLI 脚本。
- 不把 `RecognitionRun` 建成核心知识图谱节点。
- 不把模型输出覆盖到来源事实节点上。
- 不写入或推断 `DrawingBlock.block_type`；AI 判断类型只能存在于 `BlockInterpretation.interpreted_type`。
- 不把 `matched_candidate`、`CANDIDATE_*` 或模型复核结果直接当作正式图谱事实。
- 不在证据不足、候选不唯一或规则冲突时写入正式 `MATCHES_SECTION_CAPTION`。
- 不建立 `RelationAssessment` 节点；未确认判断继续使用带属性的候选关系表达。
- 不建立 `NEAR` 空间关系网络。
- 不跨 `DrawingPage` 自动做断面匹配。
- 不删除或静默迁移历史图谱数据；涉及历史关系迁移时需另行制定可回滚方案。
- 不把 `DrawingBasicInfo` 批量复制到页面内每个 `DrawingBlock`；目标路径仍是页面级 `HAS_BASIC_INFO` / `USES_BASIC_INFO`。

## 6. 影响模块

| 模块 | 影响 | 说明 |
|---|---|---|
| `architecture.md` | 高 | 需要同步语义证据层的真实落地状态，区分当前实现和目标能力 |
| `README.md` | 中 | 需要补充语义识别 dry-run、`write_back=true`、语义证据查询、降级和真实 Neo4j 验证边界 |
| `Module.md` | 高 | 需要记录新增或扩展的语义模块职责、接口、依赖和数据变化 |
| `图块图谱方案.md` | 中 | 作为目标方案继续保留；后续可根据实现阶段补充验收状态，但不能写成代码事实 |
| `图块图谱目标三层架构.svg` | 低到中 | 若新增语义关系或持久化边界变化，需要同步图中规划关系、候选关系和外部日志说明 |
| `scripts/create_schema.cypher` | 高 | 语义证据进入 Neo4j 后，需要增加节点约束、索引和关系白名单 |
| `src/drawing_graph/semantic_models.py` | 高 | 扩展 observation、interpretation、候选语义关系、状态、缓存和证据引用 |
| `src/drawing_graph/semantic_service.py` | 高 | 负责编排识别、缓存、dry-run、write-back、失败状态和输出摘要 |
| `src/drawing_graph/semantic_client.py` | 中 | 扩展多模态客户端协议、fake client、错误分类和响应校验 |
| `src/drawing_graph/semantic_repository.py` | 高 | 从内存/port 边界扩展为图谱内语义证据持久化和查询能力 |
| `src/drawing_graph/recognition_run_log.py` | 高 | 扩展图谱外运行日志的生产级存储、查询和失败状态记录 |
| `src/drawing_graph/tool_facade.py` | 高 | 对外统一语义识别、语义证据查询、候选语义关系查询和审核入口 |
| `src/drawing_graph/source_fact_query.py` | 中 | 为语义识别提供页面、图片、元素、bbox 和来源证据输入 |
| `src/drawing_graph/query_ports.py` / `query_port_adapter.py` | 中 | 需要把语义证据和解释内容投影为稳定 DTO |
| `src/drawing_graph/query_service.py` | 中 | 可能需要补充语义证据查询入口或由 adapter 组合查询；仍不应暴露内部 dict 为 Tool API |
| `src/drawing_graph/relation_repository.py` | 中 | 可能增加 `CANDIDATE_MATCHES_SECTION_CAPTION` 和 `MATCHES_SECTION_CAPTION` 的受控 relation spec |
| `src/drawing_graph/candidate_review.py` | 中 | 需要支持语义候选关系的三态审核和硬规则校验，或抽出独立语义候选审核服务 |
| `src/drawing_graph/block_relation_enrichment.py` | 低到中 | 继续负责空间与上下文派生关系；可提供候选输入，但不承载多模态识别 |
| `src/drawing_graph/config.py` / `tool_factory.py` | 中 | 增加模型 profile、prompt version、run log 存储、payload 存储、默认 `write_back=false` 等受控配置 |
| `tests/` | 高 | 新增语义模型、Schema、repository、run log、cache、facade、断面规范化、候选审核和文档边界测试 |

推荐依赖方向保持为：

```text
Tool adapter 或后续 Skill
  -> DrawingGraphToolFacade
      -> SourceFact / Query read port
      -> SemanticRecognitionService
          -> MultimodalRecognitionClient
          -> RecognitionRunLogPort
          -> SemanticEvidenceRepositoryPort
      -> CandidateReviewService
          -> 受控 Repository
              -> Neo4j implementation
```

这条依赖方向的核心约束是：Tool/Skill 只调用 facade；facade 只做输入输出、错误封装、`write_back` 策略和服务编排；语义证据层保存模型观察和解释，正式关系仍由确定性规则、独立复核和硬规则共同约束。
