# 语义证据层技术设计

本设计依据 `changes/语义证据层/proposal.md`、`Feature_Analysis_Report.md`、根目录 `architecture.md`、`README.md`、`图块图谱方案.md` 和 `图块图谱目标三层架构.svg`。目标是在不做无意义重构的前提下，复用现有来源事实层、空间与上下文派生关系层、Tool Facade、只读 port、语义 service/repository port 和候选审核骨架，分阶段补齐语义证据层。

设计原则：

- 优先复用已有架构，不重写基础导入、离线派生关系增强、查询服务、候选复核 CLI 或 Neo4j repository。
- 严格区分来源事实、空间/上下文派生关系、语义证据和正式语义关系。
- `RecognitionRun` 保持图谱外；`TextObservation` 和各类 `Interpretation` 位于图谱内。
- `write_back=false` 默认不持久化；只有显式 `write_back=true` 才写入图谱外 run log 和图谱内语义证据。
- 候选关系不是正式事实；`matched_candidate` 也不是正式关系。
- 没有可比较文本、规范化逻辑键和唯一证据时，不写入 `MATCHES_SECTION_CAPTION`。

## 1. 系统架构变化

### 1.1 目标分层

新增语义证据层后，系统目标分层保持为：

```text
来源事实层
  -> 空间与上下文派生关系层
  -> 语义证据层
  -> 统一查询输出
```

来源事实层继续由基础导入负责，只写原始标注可直接确定的项目、图纸册、页面、图块、页面元素、图片路径、bbox 和导入批次。

空间与上下文派生关系层继续由显式离线增强负责，写入 `HAS_CAPTION`、`HAS_ANNOTATION`、`HAS_SECTION_MARK`、`USES_BASIC_INFO`、`CANDIDATE_CAPTION_OF` 和 `CANDIDATE_HAS_SECTION_MARK` 等关系。

语义证据层新增模型观察、结构化解释、候选语义匹配和确认状态，但不覆盖来源事实，也不替代空间派生关系。模型输出首先成为 `TextObservation` 或 `Interpretation`；只有满足确定性规则、独立复核或人工最终确认条件时，才允许写入正式语义关系。

### 1.2 推荐依赖方向

继续沿用 Tool Facade 方向，而不是新增一套平行入口：

```text
Tool adapter / 后续 Skill / Python 调用端
  -> DrawingGraphToolFacade
      -> SourceFact / Query read port
      -> SemanticRecognitionService
          -> SemanticImageInputBuilder
          -> SemanticCacheService
          -> MultimodalRecognitionClient
          -> RecognitionRunLogPort
          -> SemanticEvidenceRepositoryPort
          -> SemanticPayloadStore
      -> SectionMatchService
          -> SectionLabelNormalizer
          -> SectionAliasRuleStore
          -> CandidateReviewService
              -> 受控 RelationRepository
                  -> Neo4j
```

关键边界：

- Tool adapter 或后续 Skill 只调用 `DrawingGraphToolFacade`。
- facade 不写 Cypher，不直接创建 Neo4j driver，不直接调用 CLI 脚本，不直接调用 `block_relation_enrichment.py` 内部规则函数。
- `SemanticRecognitionService` 只负责识别编排、缓存和语义证据写回，不负责直接提升正式关系。
- `SectionMatchService` 只在双方存在可比较 observation 后生成候选或正式匹配判断。
- `RelationRepository` 只接受受控 relation spec，不开放任意关系写入。

### 1.3 与现有流程的关系

现有流程保持不变：

```text
scripts/import_json.py
  -> ImportService
  -> Neo4jRepository
  -> 来源事实层

scripts/enrich_block_relations.py
  -> RelationEnrichmentService
  -> RelationRepository
  -> 空间与上下文派生关系层

scripts/review_candidate_relations.py
  -> CandidateReviewService
  -> RelationRepository
  -> 候选关系审核与受控提升
```

语义证据层新增的是按需识别、证据写入、缓存和统一输出，不把基础导入变成自动识别流程，也不让离线增强默认触发多模态识别。

## 2. 新增模块

新增模块按最小必要边界设计。已有 `semantic_models.py`、`semantic_service.py`、`semantic_client.py`、`semantic_repository.py`、`recognition_run_log.py` 可继续扩展；只有职责明显独立时才新增文件。

| 模块 | 建议文件 | 职责 |
|---|---|---|
| 语义图像输入构造 | `src/drawing_graph/semantic_image_inputs.py` | 根据 `page_id`、元素 ID、bbox、图片路径和页面上下文构造模型输入；计算图片 hash 和裁剪引用；不调用模型、不写图谱 |
| 语义缓存服务 | `src/drawing_graph/semantic_cache.py` | 生成 cache key，判断 observation、interpretation、关系匹配和复核缓存是否有效 |
| 语义证据 Neo4j 实现 | `src/drawing_graph/semantic_neo4j_repository.py` 或扩展 `semantic_repository.py` | 幂等写入和查询 `TextObservation`、各类 `Interpretation`、`HAS_OBSERVATION`、`HAS_INTERPRETATION`、`SUPPORTED_BY` |
| 语义 Schema 规格 | `src/drawing_graph/semantic_schema.py` 或文档化到 Schema 测试 | 定义新增标签、关系类型、唯一约束、索引和白名单，辅助 `scripts/create_schema.cypher` 更新 |
| 语义 payload 存储 | `src/drawing_graph/semantic_payload_store.py` | 保存完整不可变 JSON 解析产物，返回 `payload_ref`；避免把大嵌套结构全部塞入 Neo4j 节点属性 |
| 断面标签规范化 | `src/drawing_graph/section_label_normalization.py` | 识别 `alphabetic`、`roman`、`numeric`、`alphanumeric`、`unknown`，生成 `normalized_section_key` |
| 图谱外别名规则 | `src/drawing_graph/section_alias_rules.py` | 管理 `SectionLabelAliasRule` 的作用域、版本、状态和审计引用；不建立图谱节点 |
| 断面语义匹配服务 | `src/drawing_graph/section_match_service.py` | 组合 `CrossSection`、`BlockCaption` observation、空间候选、别名规则和硬规则，生成 `CANDIDATE_MATCHES_SECTION_CAPTION` 或 `MATCHES_SECTION_CAPTION` |
| 语义查询投影 | `src/drawing_graph/semantic_query_projection.py` | 组合来源事实、空间关系、observation、interpretation、candidate/formal relation，输出稳定 DTO |

这些模块不替代现有 `QueryService`、`RelationEnrichmentService` 或 `CandidateReviewService`。新增代码只服务语义证据层，保持现有模块职责清晰。

## 3. 修改模块

| 模块 | 修改方式 | 修改原因 | 边界 |
|---|---|---|---|
| `src/drawing_graph/semantic_models.py` | 扩展语义 DTO 和领域模型 | 承载 `TextObservation`、`BlockInterpretation`、`BasicInfoInterpretation`、`TableInterpretation`、状态、cache key、payload_ref | 不把 `RecognitionRun` 定义为 Neo4j 节点 |
| `src/drawing_graph/semantic_service.py` | 增加图像输入、缓存、结构化校验和 write-back 编排 | 支持按需识别与持久化 | 不提升正式关系 |
| `src/drawing_graph/semantic_client.py` | 扩展客户端协议、fake client、错误分类和响应校验 | 支持可替换多模态模型 | 不默认绑定真实供应商 |
| `src/drawing_graph/semantic_repository.py` | 补充 port 方法或接入 Neo4j 实现 | 支持图谱内语义证据读写 | 不保存 `RecognitionRun` 节点 |
| `src/drawing_graph/recognition_run_log.py` | 增加生产级 port 或实现 | 支持跨进程查询运行日志 | 与核心图谱解耦 |
| `src/drawing_graph/tool_facade.py` | 增加语义识别、语义证据查询、解释查询、断面匹配和候选审核方法 | 对外统一入口 | 不暴露 repository、driver 或 Cypher |
| `src/drawing_graph/tool_models.py` | 增加语义响应 DTO、错误 envelope、候选/正式关系 DTO | 保持 Tool 输出稳定 | 不返回 Neo4j 内部节点 ID |
| `src/drawing_graph/source_fact_query.py` | 补充模型输入所需页面图片、尺寸、元素和 bbox 投影 | 为语义识别提供来源证据 | 不调用模型 |
| `src/drawing_graph/query_ports.py` / `query_port_adapter.py` | 增加语义查询 port 或投影适配 | 统一 facade 查询输出 | 不重写 `QueryService` |
| `src/drawing_graph/relation_repository.py` | 增加受控 `CANDIDATE_MATCHES_SECTION_CAPTION` 和 `MATCHES_SECTION_CAPTION` relation spec | 支持断面语义候选和正式关系 | 不开放任意 relation spec |
| `src/drawing_graph/candidate_review.py` | 扩展候选审核输入/输出，支持语义候选完整候选集 | 复用三态和硬规则思想 | 不把模型 accepted 直接当事实 |
| `src/drawing_graph/config.py` / `tool_factory.py` | 增加受控配置：模型 profile、prompt version、run log store、payload store、默认 write_back | 集中依赖创建 | import 时不连接 Neo4j、不扫描数据、不接收密钥字段 |
| `scripts/create_schema.cypher` | 增加语义节点约束和索引 | 支持 Neo4j 语义证据持久化 | 使用 `IF NOT EXISTS`，可重复执行 |
| `architecture.md`、`README.md`、`Module.md` | 同步真实实现状态 | 防止文档把目标写成已完成 | 每阶段实现后再更新 |
| `tests/` | 新增语义模型、缓存、repository、run log、断面规范化、facade 和文档边界测试 | 防止边界回退 | 单元测试不依赖真实云模型；Neo4j 集成测试单独标注 |

不修改或不重构：

- 不重写 `ImportService`、`Neo4jRepository`、`RelationEnrichmentService`、`QueryService` 的主体结构。
- 不把语义识别放进 `block_relation_enrichment.py`。
- 不把 `scripts/import_json.py` 改成自动触发语义识别。
- 不让 `scripts/enrich_block_relations.py` 默认触发多模态识别或候选复核。

## 4. 数据模型变化

### 4.1 图谱内新增节点

| 节点 | 作用 | 关键字段 |
|---|---|---|
| `TextObservation` | 模型对来源元素或局部区域的文字/符号观察 | `id`、`recognition_run_id`、`target_element_id`、`target_element_type`、`page_id`、`raw_text`、`normalized_text`、`bbox`、`normalized_bbox`、`confidence`、`status`、`image_hash`、`cache_key`、`model_profile`、`prompt_version`、`created_at` |
| `BlockInterpretation` | 对完整 `DrawingBlock` 的结构化解析和自然语言总结 | `id`、`recognition_run_id`、`block_id`、`summary`、`interpreted_type`、`components`、`materials`、`dimensions`、`construction_features`、`spatial_relations`、`analysis_status`、`uncertainties`、`payload_ref`、`cache_key`、`contract_version`、`created_at` |
| `BasicInfoInterpretation` | 对 `DrawingBasicInfo` 的结构化基础信息解析 | `id`、`recognition_run_id`、`basic_info_id`、`raw_text`、`summary`、`project_name`、`drawing_name`、`discipline`、`drawing_number`、`scale`、`date`、`analysis_status`、`uncertainties`、`payload_ref`、`cache_key` |
| `TableInterpretation` | 对 `Table` 的表格结构解析 | `id`、`recognition_run_id`、`table_id`、`caption_ref`、`summary`、`analysis_status`、`uncertainties`、`payload_ref`、`cache_key` |

说明：

- 节点 ID 使用稳定、可重算的语义 ID，不依赖 Neo4j 内部 ID。
- 同一来源元素可保留多个不同模型、prompt 或契约版本的 observation/interpretation。
- 旧 interpretation 失效时标记为 `stale`，不静默覆盖。

### 4.2 图谱内新增关系

| 关系 | 起点 | 终点 | 说明 |
|---|---|---|---|
| `HAS_OBSERVATION` | 来源元素 | `TextObservation` | 说明这条 observation 描述哪个来源对象或局部区域 |
| `HAS_INTERPRETATION` | `DrawingBlock` / `DrawingBasicInfo` / `Table` | 对应 `Interpretation` | 说明该来源对象有一次结构化语义解析 |
| `SUPPORTED_BY` | `Interpretation` | `TextObservation` | 说明结构化解释依赖哪些文字观察 |
| `CANDIDATE_MATCHES_SECTION_CAPTION` | `CrossSection` | `BlockCaption` | 表示断面标记与标题可能匹配，但尚未成为正式事实 |
| `MATCHES_SECTION_CAPTION` | `CrossSection` | `BlockCaption` | 表示经确定性规则、独立复核或人工确认后的正式语义关系 |

关系属性建议：

- 候选边：`candidate_group_id`、`status`、`score`、`candidate_count`、`conflict_reason`、`observation_ids`、`rule_version`、`alias_rule_id`、`alias_rule_version`、`recognition_run_id`、`review_run_id`、`created_at`、`updated_at`。
- 正式边：`confirmation_method`、`confirmed_at`、`rule_version`、`observation_ids`、`review_run_id`、`alias_rule_id`、`alias_rule_version`。

### 4.3 图谱外数据

`RecognitionRun` 保持图谱外运行日志：

| 字段 | 说明 |
|---|---|
| `run_id` | 运行 ID |
| `run_type` | `recognition`、`interpretation`、`candidate_review` |
| `target_scope` | 页面、元素、候选组或任务范围 |
| `model_profile`、`model_name`、`model_version` | 模型配置和实际模型信息 |
| `prompt_version` | 提示词版本 |
| `input_refs` | 图片、bbox、元素 ID、页面上下文和 hash |
| `status` | `succeeded`、`partial`、`failed`、`cancelled` |
| `error_summary` | 错误摘要 |
| `started_at`、`finished_at` | 运行时间 |
| `write_back` | 是否触发持久化 |
| `cost_summary` | 可选成本信息 |

`SectionLabelAliasRule` 也保持图谱外配置：

- `alias_rule_id`
- `alias_rule_version`
- `scope`
- `source_system`
- `from_symbol_system`
- `to_symbol_system`
- `mapping`
- `status`
- `evidence_ref`
- `confirmed_by`
- `created_at`
- `revoked_at`

### 4.4 缓存模型

缓存键是证据属性，不建立独立缓存节点。

```text
cache_key = hash(
  image_hash
  + bbox
  + target_element_id
  + task_type
  + model_profile/model_version
  + prompt_version
  + preprocessing_version
  + normalization_rule_version
  + contract_version
)
```

缓存边界：

- `TextObservation` 缓存不包含别名规则版本。
- `Interpretation` 缓存包含数据契约版本。
- 关系匹配缓存包含双方 observation、候选范围、匹配规则版本和适用 alias rule 版本。
- 别名规则变化只使依赖它的匹配结果失效，不使原始 observation 失效。

## 5. API 设计

这里的 API 指 Python 应用 facade 的方法契约，不是 HTTP API，也不是 MCP Tool adapter 协议。

### 5.1 扩展 facade 方法

| 方法能力 | 输入 | 输出 | 持久化 |
|---|---|---|---|
| 单页语义识别 | `page_id`、`target_types`、`model_profile`、`prompt_version`、`write_back=false` | `recognition_run_id`、状态、observation 摘要、`persisted`、错误摘要 | 仅 `write_back=true` |
| 查询运行日志 | `recognition_run_id` | run log 摘要、模型、prompt、输入范围、状态、错误和时间 | 否 |
| 查询文字观察 | `page_id`、`element_id` 或 `recognition_run_id`，可选状态过滤 | `TextObservation` 列表、来源元素、bbox、状态、证据引用 | 否 |
| 查询结构化解释 | `element_id`、`element_type`、可选 `latest_only`、状态过滤 | `BlockInterpretation` / `BasicInfoInterpretation` / `TableInterpretation` 摘要和 `payload_ref` | 否 |
| 获取完整解释 payload | `payload_ref` | 不可变 JSON 解析产物 | 否 |
| 执行断面匹配 | `cross_section_id`、可选 `page_id`、`write_back=false` | 匹配状态、候选标题、逻辑键、证据、是否写入候选/正式关系 | 仅 `write_back=true` |
| 查询断面匹配 | `cross_section_id` 或 `page_id`，可选状态过滤 | `CANDIDATE_MATCHES_SECTION_CAPTION` 和 `MATCHES_SECTION_CAPTION` 投影 | 否 |
| 审核语义候选关系 | `candidate_group_id`、`decision`、`reviewer`、`reason`、`write_back=false` | `accepted`、`rejected`、`unresolved`、是否提升、失败原因 | 仅 `write_back=true` |

### 5.2 输入 DTO 原则

- 所有 ID 使用稳定业务 ID，不使用 Neo4j 内部 ID。
- `target_types` 只能取受控枚举，例如 `cross_section`、`block_caption`、`drawing_block`、`basic_info`、`table`、`table_caption`、`title`、`plain_text`、`annotation`。
- `model_profile` 只能选择受控配置，不接受 API key 或任意供应商参数。
- `prompt_version` 使用已登记版本，不接受自由 prompt 覆盖核心策略。
- 写入类能力必须显式传入 `write_back=true`。

### 5.3 输出 DTO 原则

统一输出包含：

- `fact_kind`：`source_fact`、`derived_relation`、`semantic_observation`、`semantic_interpretation`、`candidate_relation`、`formal_relation`。
- `status`：明确表达 `not_recognized`、`recognized`、`partial`、`ambiguous`、`not_found`、`failed`、`stale`、`candidate`、`confirmed`。
- `evidence`：稳定业务 ID、图片路径、bbox、observation ID、run ID、review run ID、规则版本。
- `persisted`：区分 dry-run 临时结果和持久化结果。
- `warnings`：用于说明缓存失效、证据不足、候选冲突或降级。

输出不包含：

- Neo4j 内部节点 ID。
- Cypher、driver、session、transaction。
- 供应商密钥、原始异常栈或敏感路径。

## 6. 前后端流程

当前项目没有实际前端、HTTP API 或 MCP Tool adapter。本节中的“前端”指未来 Tool、Skill、CLI 包装器或可视化界面等调用端；“后端”指当前 Python 应用层和 Neo4j/图谱外存储。

### 6.1 只读语义查询流程

```text
前端/调用端
  -> DrawingGraphToolFacade 查询请求
  -> Query / SourceFact read port
  -> SemanticEvidenceRepositoryPort 查询 observation / interpretation
  -> RecognitionRunLogPort 补充运行日志摘要
  -> SemanticQueryProjection 组合输出
  -> 前端展示来源事实、bbox、语义内容、状态和审计信息
```

行为：

- 不触发模型调用。
- 不写入 Neo4j。
- 如果没有语义证据，返回 `not_recognized` 或 `not_interpreted`，而不是用空字符串伪装已识别。

### 6.2 dry-run 语义识别流程

```text
前端/调用端
  -> recognize_page_semantics(write_back=false)
  -> SourceFact read port 读取页面、图片和元素 bbox
  -> SemanticImageInputBuilder 构造输入
  -> SemanticCacheService 检查可复用缓存
  -> MultimodalRecognitionClient 调用 fake/受控模型客户端
  -> SemanticRecognitionService 生成临时 observation / interpretation
  -> 返回 persisted=false 的临时结果
```

行为：

- 不创建持久化 `RecognitionRun`。
- 不写入 `TextObservation` 或 `Interpretation`。
- 不写入候选边或正式边。

### 6.3 write-back 语义识别流程

```text
前端/调用端
  -> recognize_page_semantics(write_back=true)
  -> SourceFact read port 读取来源事实
  -> RecognitionRunLogPort 创建 run
  -> SemanticImageInputBuilder 构造输入
  -> SemanticCacheService 检查缓存
  -> MultimodalRecognitionClient 调用模型
  -> SemanticEvidenceRepositoryPort 写入 observation / interpretation
  -> RecognitionRunLogPort 完成或失败 run
  -> 返回 persisted=true 的证据摘要
```

行为：

- run log 在图谱外。
- observation/interpretation 在图谱内。
- 写入失败不能伪装成 dry-run 成功。
- 识别失败如果 run 已创建，应记录失败状态。

### 6.4 CrossSection 断面匹配流程

```text
前端/调用端
  -> match_section_caption(cross_section_id, write_back)
  -> 查询 CrossSection 来源事实和同页 BlockCaption 候选
  -> 确保双方有可比较 TextObservation
  -> SectionLabelNormalizer 生成符号体系和 normalized_section_key
  -> SectionAliasRuleStore 读取已确认别名规则
  -> SectionMatchService 比较同页候选
  -> 唯一且无冲突：可写 MATCHES_SECTION_CAPTION
  -> 多候选或冲突：写/返回 CANDIDATE_MATCHES_SECTION_CAPTION
  -> 必要时进入 CandidateReviewService 独立复核
```

行为：

- 没有双方 observation 时，不创建候选边或正式边。
- 空间接近不能替代文本相等证据。
- 跨符号体系匹配必须引用已确认的外部别名规则。
- 模型复核必须一次看到全部候选、原始裁剪、页面上下文、空间证据和已有观察。

### 6.5 降级流程

```text
多模态服务不可用
  -> 返回已有来源事实和空间关系
  -> 语义状态标记为 recognition_failed 或 not_recognized
  -> 不写正式语义关系
```

降级要求：

- 明确区分“未执行识别”和“识别后未找到”。
- 保留已有图谱可用结果，不阻断基础查询。
- 不补猜、不强制填值。

## 7. 异常处理

### 7.1 错误分类

| 错误码 | 场景 | 是否可重试 |
|---|---|---|
| `INVALID_ARGUMENT` | 缺少 ID、非法 target type、非法状态、非法 bbox、未知模型 profile | 否 |
| `NOT_FOUND` | 页面、元素、observation、interpretation、run、payload 或候选组不存在 | 否 |
| `WRITE_BACK_REQUIRED` | 调用持久化语义证据或候选审核但未显式 `write_back=true` | 否 |
| `WRITE_BACK_FORBIDDEN` | 只读查询被传入写回意图，或调用端试图绕过 facade 写入 | 否 |
| `RUN_LOG_UNAVAILABLE` | 图谱外运行日志存储不可用 | 是 |
| `SEMANTIC_EVIDENCE_UNAVAILABLE` | 语义证据 repository 不可用或写入失败 | 是 |
| `PAYLOAD_UNAVAILABLE` | 完整 JSON payload 存储不可用 | 是 |
| `RECOGNITION_FAILED` | 模型调用失败、超时、返回不可解析或结构化校验失败 | 视错误而定 |
| `CACHE_STALE` | 缓存命中但版本或输入 hash 已失效 | 可重新识别 |
| `NORMALIZATION_FAILED` | 断面标签无法规范化或符号体系未知 | 否 |
| `MATCH_NOT_FOUND` | 有可比较 observation，但没有同键候选 | 否 |
| `AMBIGUOUS_MATCH` | 多候选、字符歧义、符号体系冲突或规则范围不唯一 | 否 |
| `CANDIDATE_REVIEW_REJECTED` | accepted 请求未通过硬规则校验 | 否 |
| `CONFLICT` | 候选状态已变化、正式关系已存在冲突或版本冲突 | 可按最新状态重试 |
| `NEO4J_UNAVAILABLE` | Neo4j 查询或事务失败 | 是 |

### 7.2 处理原则

- facade 捕获底层异常后转换为稳定错误 envelope，不向调用端暴露 Cypher、driver 栈、密钥或敏感路径。
- 查询失败、识别失败、run log 写入失败和语义证据写入失败必须区分。
- `write_back=true` 下，如果 run log 已创建但识别失败，应把 run 标记为 failed。
- 语义证据写入失败时，不写候选边或正式关系。
- 候选审核冲突时，以最新候选状态为准，不静默覆盖。
- `ambiguous` 必须返回至少两个候选或冲突项及其证据；单纯缺少信息不应误报为歧义。
- `stale` 解析可保留用于审计，但不得作为默认最新语义结果返回。

## 8. 安全方案

### 8.1 数据库访问安全

- Tool adapter、Skill 或未来前端不接收 Neo4j URI、用户名、密码。
- Tool adapter、Skill 或未来前端不创建 Neo4j driver。
- 不开放任意 Cypher 查询。
- Neo4j 访问只通过受控 repository 或 port implementation。
- 新增语义关系必须进入固定白名单和 relation spec。

### 8.2 写回安全

- 默认 `write_back=false`，所有语义识别和候选审核默认 dry-run。
- `write_back=true` 只表示允许进入持久化流程，不表示跳过校验。
- 语义证据写回只能写 observation、interpretation、候选语义边或受控正式语义边。
- 模型输出不得覆盖来源事实节点。
- `BlockInterpretation.interpreted_type` 不得写入 `DrawingBlock.block_type`。
- 已有正式关系出现冲突时，模型不得自动覆盖；应保留冲突候选，必要时人工兜底。

### 8.3 模型调用安全

- 第一阶段使用 fake client 或受控多模态客户端协议，不默认绑定真实供应商。
- 模型 profile、prompt version 和密钥来自受控配置，不来自 Tool 请求自由文本。
- 输入给模型的内容限制在当前页面、目标元素 bbox 和必要上下文。
- 供应商错误、超时、不可解析输出必须归入 `RECOGNITION_FAILED` 或更具体错误状态。
- 模型回答不能直接成为正式图谱事实。

### 8.4 证据与审计安全

- `TextObservation` 必须保留 `recognition_run_id`、来源元素 ID、bbox、图片 hash、模型版本、prompt 版本、cache key 和状态。
- `RecognitionRun` 只存在于图谱外运行日志。
- 候选边和正式边如果依赖复核，必须保存 `review_run_id`。
- 候选关系响应必须明确 `fact_kind=candidate_relation`。
- dry-run 响应必须明确 `persisted=false`。
- 真实 Neo4j 集成测试跳过不能作为 live Neo4j 已验证证据。

### 8.5 架构边界安全

- 不新增 HTTP API、Agent Skill、MCP Tool adapter 或全量自动扫描，除非后续单独立项。
- 不把语义证据层塞入 `block_relation_enrichment.py`。
- 不让基础导入自动触发语义识别。
- 不让离线增强默认触发模型复核。
- 不建立 `RelationAssessment` 节点。
- 不建立 `NEAR` 空间关系网络。
- 不跨 `DrawingPage` 自动断面匹配。

## 9. 分阶段落地建议

虽然本设计不拆具体代码任务，但建议后续任务顺序如下：

| 阶段 | 目标 | 验收重点 |
|---|---|---|
| 阶段 1：契约与状态 | 扩展语义模型、状态、cache key、payload_ref | 单元测试验证非法状态、bbox、cache key 和 DTO 边界 |
| 阶段 2：run log 与 repository | 图谱外 run log、图谱内语义证据持久化 | 验证 `RecognitionRun` 不建图谱节点，`TextObservation` 可追溯 |
| 阶段 3：facade 查询输出 | 统一 observation、interpretation、candidate/formal relation 投影 | 验证不暴露 Neo4j 内部 ID，状态不混淆 |
| 阶段 4：断面匹配 | `CrossSection` 与 `BlockCaption` 语义匹配 | 没有 observation 不建边；多候选只建 candidate；唯一且无冲突才 formal |
| 阶段 5：图块/基础信息/表格解释 | 扩展 `BlockInterpretation`、`BasicInfoInterpretation`、`TableInterpretation` | AI 解析不覆盖来源事实，旧结果可 stale 并保留审计 |

每个阶段完成后再更新 `architecture.md`、`README.md` 和 `Module.md` 的真实状态，避免目标方案与当前实现混写。

## 10. 当前实现状态（Task 1-25 后）

本节记录 `tasks.md` Task 1-25 完成后的真实状态，与上文目标设计区分；尚未实现的能力不写成已完成。

已实现：

- 数据契约：`TextObservation` 扩展了 `model_profile`、`prompt_version`、`created_at`；三类 `Interpretation` 已定义（含 `page_id`、`supported_by_observation_ids` 等增量字段）；`matched_candidate` 与 `interpreted_type` 均明确不是正式事实/来源字段。
- 缓存与 payload：`semantic_cache.py` 提供确定性 cache key（observation key 不含 alias rule 版本；断面匹配 key 含 alias 版本）和内存缓存服务；`semantic_payload_store.py` 提供不可变 payload 与 `payload_ref`。
- 图像输入：`semantic_image_inputs.py` 从 `PageSourceFacts` 构造目标元素输入，支持注入图片 hash 或读取文件 hash；`PageSourceFacts` 增加可选 `image_hash`。
- run log：`RecognitionRunLogPort`/内存实现支持 `recognition`、`interpretation`、`candidate_review`，记录 `target_scope`、模型信息、输入引用、状态、错误、时间、`write_back` 和可选成本摘要；缓存命中与查询不创建新 run。
- repository：`SemanticEvidenceRepositoryPort`/内存实现支持 observation 与三类 interpretation 按 page/element/run/status 读写；`semantic_neo4j_repository.py` 以稳定 ID 幂等 MERGE 写入语义节点与 `HAS_OBSERVATION`、`HAS_INTERPRETATION`、`SUPPORTED_BY`，同 cache key 旧 interpretation 标记 `stale`，不创建 `RecognitionRun` 节点。
- Schema：`semantic_schema.py` 定义语义节点/关系/约束/索引/来源标签白名单；`scripts/create_schema.cypher` 以 `IF NOT EXISTS` 增加语义约束和索引。
- 编排：`SemanticRecognitionService` 支持输入构造、缓存复用、dry-run 无副作用和 write-back 写回；识别失败或证据写入失败会标记 run 为 failed，不会伪装成 dry-run 成功；识别流程不写候选/正式关系。
- 查询输出：Tool DTO 增加语义 summary；`semantic_query_projection.py` 区分 `source_fact`、`derived_relation`、`semantic_observation`、`semantic_interpretation`、`candidate_relation`、`formal_relation`；facade 提供 run/observation/interpretation/payload 查询。
- 断面专项：`SectionLabelNormalizer`（alphabetic/roman/numeric/alphanumeric/unknown，默认不合并 `I-I`、`Ⅰ-Ⅰ`、`1-1`）、`SectionAliasRuleStore`（仅 confirmed+scope 命中参与）、`SectionMatchService`（候选与正式硬规则）、受控 relation spec（`CANDIDATE_MATCHES_SECTION_CAPTION`、`MATCHES_SECTION_CAPTION`）、facade `match_section_caption`/`list_section_matches` 与语义候选审核（`candidate_matches_section_caption`）。
- 配置工厂：`ToolFacadeConfig` 支持 `run_log_store`、`payload_store`、`semantic_repository`、`cache_store`、`section_match_rule_version` 等受控配置，拒绝敏感字段；模块 import 不连接 Neo4j、不扫描数据、不调用模型。

尚未实现/未验证（保持目标状态）：

- 真实多模态供应商客户端未接入；当前仅 fake client 与受控协议。
- `SemanticNeo4jRepository` 的查询方法（`find_by_page`/`find_by_element`/`find_by_run`/`find_interpretations`）当前返回 `NEO4J_UNAVAILABLE`，live Neo4j 语义查询闭环未实现。
- 未配置 `NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD` 时，真实 Neo4j 集成测试跳过；跳过不等于通过，live 语义写入未验证。
- HTTP API、Agent Skill、MCP Tool adapter、全量自动语义扫描、全量离线 OCR、默认真实云模型调用均不在当前实现范围。
