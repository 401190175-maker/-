# 空间与上下文派生关系层对齐技术设计

## 1. 系统架构变化

### 1.1 设计目标

本设计依据 `proposal.md`，将当前空间与上下文派生关系层调整到与《图块图谱方案.md》一致。设计原则是优先复用已有基础导入、离线派生关系增强、固定关系规格、批次审计和只读查询架构；只在现有边界无法表达目标语义时新增必要模块。

本次不重建图谱，不改基础导入主链路，不引入通用规则插件框架，不把 AI 语义解释写入来源事实节点。

本设计属于规划边界文档，用于约束实现方案、模块职责和非目标范围；文档中的目标关系与流程说明不声称代码已实现。

### 1.2 调整前架构

当前系统已经形成两条流程：

```text
基础导入
  -> 创建 Project / DrawingSet / DrawingPage / DrawingBlock / 页面元素
  -> 创建页面来源关系
  -> 写入稳定 ID、图片路径、bbox
  -> ImportBatch 审计

离线派生关系增强
  -> 读取页面快照
  -> 计算 Table 标题关系
  -> 计算 DrawingBlock 起点的标题、基础信息、注释、剖面标记关系
  -> 按固定关系规格写入 Neo4j
  -> RelationBatchAudit 审计
```

主要问题是：基础信息仍以 block 级 `HAS_BASIC_INFO` 扇出；空间歧义候选没有持久化；候选关系也没有进入独立 AI 复核。

### 1.3 调整后架构

调整后保留现有两条主流程，并在离线派生关系增强之后增加“候选关系 AI 复核”支线：

```text
基础导入
  -> 来源事实层
  -> 不自动触发派生增强

离线派生关系增强
  -> 页面快照读取
  -> Table 标题正式关系
  -> DrawingBlock 标题、注释、剖面标记正式关系
  -> DrawingPage 基础信息上下文关系
  -> BlockCaption / CrossSection 空间候选边
  -> RelationBatchAudit 审计

候选关系 AI 复核
  -> 读取同一冲突组的完整 CANDIDATE_* 候选集合
  -> 读取原始裁剪、页面上下文、空间证据和已有观察
  -> 调用独立多模态复核
  -> accepted / rejected / unresolved
  -> 通过硬性规则校验后提升正式关系，或保留候选状态
```

候选关系 AI 复核不挂到基础导入，也不强制每次离线增强自动执行。第一版可由独立服务函数或命令显式触发，后续再接入更完整的语义证据层。

### 1.4 分层边界

来源事实层保持不变：

- `Project -[:HAS_SET]-> DrawingSet`
- `DrawingSet -[:HAS_PAGE]-> DrawingPage`
- `DrawingPage -[:HAS_BLOCK]-> DrawingBlock`
- `DrawingPage -[:HAS_TABLE]-> Table`
- `DrawingPage -[:HAS_BASIC_INFO]-> DrawingBasicInfo`
- `DrawingPage -[:HAS_ANNOTATION]-> DrawingAnnotation`
- `DrawingPage -[:HAS_TEXT]-> PlainText / Title`
- `DrawingPage -[:HAS_ELEMENT]-> BlockCaption / CrossSection / IgnoredElement`
- `DrawingPage -[:IMPORTED_IN]-> ImportBatch`

空间与上下文派生关系层调整为：

- `Table -[:HAS_CAPTION]-> TableCaption`
- `DrawingBlock -[:HAS_CAPTION]-> BlockCaption`
- `DrawingBlock -[:HAS_ANNOTATION]-> DrawingAnnotation`
- `DrawingBlock -[:HAS_SECTION_MARK]-> CrossSection`
- `DrawingPage -[:USES_BASIC_INFO]-> DrawingBasicInfo`
- `BlockCaption -[:CANDIDATE_CAPTION_OF]-> DrawingBlock`
- `DrawingBlock -[:CANDIDATE_HAS_SECTION_MARK]-> CrossSection`

旧的 `DrawingBlock -[:HAS_BASIC_INFO]-> DrawingBasicInfo` 只作为历史实现和迁移兼容对象，不再作为目标关系。

### 1.5 兼容性原则

- 保留 `scripts/import_json.py` 和 `scripts/enrich_block_relations.py` 入口。
- 保留 `Project -> DrawingSet -> DrawingPage -> DrawingBlock` 追溯链路。
- 保留现有 `Table -[:HAS_CAPTION]-> TableCaption` 离线增强能力。
- 保留 `HAS_ANNOTATION` 同页共享上下文规则。
- 保留固定关系规格白名单，不开放动态 Label 或动态关系类型。
- 不因本次调整立即删除历史 block 级基础信息关系；迁移另行执行。

## 2. 新增模块

### 2.1 新增模块原则

本次只新增目标语义必须的逻辑模块。优先在现有离线增强架构中扩展；当模块职责与确定性几何规则明显不同，才单独建模块，避免把 AI 调用、复核日志和图形规则塞进同一个文件。

### 2.2 页面级基础信息上下文逻辑

建议作为 `block_relation_enrichment.py` 内的独立逻辑组件起步，职责包括：

- 判断页面是否存在 `DrawingBlock`；
- 当前页有 `DrawingBasicInfo` 时生成页面级上下文结果；
- 当前页缺失基础信息时返回 `not_evaluated` 或 `partial`，不再用直接上一页强行生成正式事实；
- 后续在 `BasicInfoInterpretation` 可用后，支持候选图纸组锚点和公共字段比较；
- 输出 `USES_BASIC_INFO` 所需属性。

如果实现后该部分明显膨胀，再拆为 `basic_info_context.py`。第一版不为拆文件而拆文件。

### 2.3 空间候选边生成逻辑

建议继续放在 `block_relation_enrichment.py`，复用现有 bbox、距离、包含和重叠规则。新增职责包括：

- 对 `BlockCaption` 生成完整 `DrawingBlock` 候选集合；
- 对 `CrossSection` 生成完整包含或重叠候选集合；
- 唯一且证据充分时输出正式关系；
- 多候选、冲突或证据接近时输出 `CANDIDATE_*`；
- 为候选关系填充候选数量、分数、冲突原因和几何证据。

### 2.4 候选关系 AI 复核模块

建议新增独立模块，例如 `candidate_review.py`，因为它属于模型复核和状态提升，不属于确定性空间规则。

职责：

- 按候选组读取 `CANDIDATE_*` 关系及其端点证据；
- 组织复核输入，包括完整候选集合、原始裁剪、页面上下文、空间证据和已有观察；
- 调用可注入的多模态复核客户端；
- 校验模型输出只能为 `accepted`、`rejected`、`unresolved`；
- 对 `accepted` 执行硬性规则校验；
- 输出候选状态更新或正式关系提升请求；
- 记录 `review_run_id` 和复核元数据。

AI 客户端应通过接口注入，设计文档不指定具体模型供应商，也不在本阶段实现完整云端调用细节。

### 2.5 图谱外复核运行日志

建议新增轻量运行日志能力，可独立文件或复用审计模块扩展，第一版只需要支持 `review_run_id` 回查：

- `review_run_id`
- `run_type`
- 候选组 ID 或候选集合指纹
- 模型版本
- 提示词版本
- 输入证据引用
- 输出状态
- 错误摘要
- started_at / finished_at

它不是 Neo4j 核心节点，不参与图纸对象之间的知识关系。

## 3. 修改模块

### 3.1 `src/drawing_graph/block_relation_enrichment.py`

修改职责：

- 停止新增 `block_basic_info` 规格对应的正式关系；
- 新增页面级基础信息上下文结果；
- 当前页缺失基础信息时，不再调用“直接上一页继承”为正式事实；
- `enrich_block_captions()` 改为先构造候选集合，再根据唯一性和冲突状态输出正式关系或候选边；
- `enrich_cross_sections()` 保留现有包含和重叠阈值，但把多个有效候选输出为候选边；
- `RelationCandidate` 或替代数据契约需要能表达正式关系和候选关系；
- `EnrichmentStats` 增加 `candidate_count`、`uses_basic_info_count`、`ambiguous_count`、`not_evaluated_count` 等统计。

`PageRelationSnapshot` 仍作为页面增强输入，继续复用现有 page/block/caption/table/basic_info/annotation/cross_section 快照。

### 3.2 `src/drawing_graph/relation_repository.py`

修改职责：

- 扩展 `RELATION_SPECS`；
- 删除目标设计中的 `block_basic_info` 写入路径，或将其标记为 legacy-only，不在新增强流程调用；
- 新增 `page_uses_basic_info` 规格；
- 新增 `candidate_caption_of` 规格；
- 新增 `candidate_section_mark` 规格；
- 支持 `DrawingPage` 起点和 `BlockCaption` 起点；
- 保持固定 Label、固定关系类型和参数化属性；
- 为候选边和复核状态更新提供受控写入函数。

固定规格建议如下：

| relation_spec | 起点 Label | 关系类型 | 终点 Label |
|---|---|---|---|
| `table_caption` | `Table` | `HAS_CAPTION` | `TableCaption` |
| `block_caption` | `DrawingBlock` | `HAS_CAPTION` | `BlockCaption` |
| `block_annotation` | `DrawingBlock` | `HAS_ANNOTATION` | `DrawingAnnotation` |
| `block_section_mark` | `DrawingBlock` | `HAS_SECTION_MARK` | `CrossSection` |
| `page_uses_basic_info` | `DrawingPage` | `USES_BASIC_INFO` | `DrawingBasicInfo` |
| `candidate_caption_of` | `BlockCaption` | `CANDIDATE_CAPTION_OF` | `DrawingBlock` |
| `candidate_section_mark` | `DrawingBlock` | `CANDIDATE_HAS_SECTION_MARK` | `CrossSection` |

### 3.3 `src/drawing_graph/relation_service.py`

修改职责：

- 保持 `enrich_page()`、`enrich_drawing_set()`、`enrich_project()` 公开接口；
- 在 page 范围运行时，如果需要 drawing set 上下文才能判断基础信息，返回 `not_evaluated` 或 `partial`；
- 在 drawing-set/project 范围运行时，为基础信息上下文提供页面序列和候选锚点；
- 写入正式关系、候选关系和 `USES_BASIC_INFO`；
- 汇总新增统计和 issue；
- 保持单页失败隔离。

### 3.4 `src/drawing_graph/query_service.py`

修改职责：

- `get_block_relations(block_id)` 改为通过所属页面读取基础信息；
- 返回 `basic_info_ids` 时优先来自 `DrawingPage -[:HAS_BASIC_INFO|USES_BASIC_INFO]-> DrawingBasicInfo`；
- 可新增 `basic_info_status`、`basic_info_source`、`candidate_caption_ids`、`candidate_section_mark_ids` 等字段；
- `relation_status` 需要区分 `not_enhanced`、`partial`、`enhanced`、`candidate`、`ambiguous`、`not_evaluated`；
- 不返回 Neo4j 内部 ID，不开放任意 Cypher。

如需保持旧调用方兼容，可保留原字段名，同时增加新字段。旧 block 级 `HAS_BASIC_INFO` 只作为迁移兼容读取，不作为新结果优先来源。

### 3.5 `src/drawing_graph/audit.py`

修改职责：

- `RelationBatchAudit` 增加页面级基础信息、候选边和 AI 复核统计；
- issue 分类增加 `basic_info_not_evaluated`、`basic_info_ambiguous`、`candidate_caption_ambiguous`、`candidate_section_mark_ambiguous`、`candidate_review_failed` 等；
- 审计摘要继续脱敏；
- AI 复核日志不作为核心图谱节点，但其 ID 应进入审计摘要和候选边属性。

### 3.6 `scripts/enrich_block_relations.py`

修改职责：

- 保持现有命令名称和参数兼容；
- 输出新增统计字段；
- 帮助文本改为“派生关系增强”，不再暗示只处理 block 起点关系；
- 不自动调用 AI 复核。

如果需要显式触发候选复核，建议后续新增单独 CLI，例如 `scripts/review_candidate_relations.py`，而不是把模型调用默认挂到现有增强命令里。

### 3.7 文档与测试

- `architecture.md` 更新目标关系、数据流和阶段边界；
- `README.md` 更新运行说明、候选边、AI 复核状态和查询结果；
- 单元测试覆盖页面级基础信息、候选边、AI 复核状态、查询路径；
- 集成测试在具备真实 Neo4j 时验证关系写入和幂等；无 Neo4j 环境时必须明确跳过。

## 4. 数据模型变化

### 4.1 Neo4j 节点模型

不新增核心业务节点类型。继续使用现有：

- `Project`
- `DrawingSet`
- `DrawingPage`
- `DrawingBlock`
- `Table`
- `TableCaption`
- `BlockCaption`
- `DrawingBasicInfo`
- `DrawingAnnotation`
- `CrossSection`
- `PlainText`
- `Title`
- `ImportBatch`

`RecognitionRun` 或 `review_run_id` 对应的运行日志不作为核心图谱节点。第一版设计为图谱外日志或审计存储。

### 4.2 Neo4j 关系模型

新增目标关系类型：

| 关系 | 层级 | 说明 |
|---|---|---|
| `DrawingPage -[:USES_BASIC_INFO]-> DrawingBasicInfo` | 空间与上下文派生关系层 | 页面级基础信息上下文 |
| `BlockCaption -[:CANDIDATE_CAPTION_OF]-> DrawingBlock` | 空间候选关系 | 标题归属不唯一时的候选 |
| `DrawingBlock -[:CANDIDATE_HAS_SECTION_MARK]-> CrossSection` | 空间候选关系 | 剖面标记归属不唯一时的候选 |

保留目标正式关系：

- `Table -[:HAS_CAPTION]-> TableCaption`
- `DrawingBlock -[:HAS_CAPTION]-> BlockCaption`
- `DrawingBlock -[:HAS_ANNOTATION]-> DrawingAnnotation`
- `DrawingBlock -[:HAS_SECTION_MARK]-> CrossSection`

停止新增目标外关系：

- `DrawingBlock -[:HAS_BASIC_INFO]-> DrawingBasicInfo`

### 4.3 `USES_BASIC_INFO` 属性

建议属性：

- `relation_batch_id`
- `rule_version`
- `link_rule`
- `source`：`current_page`、`group_start`、`group_end`
- `source_page_id`
- `group_id`
- `status`：`confirmed`、`partial`、`ambiguous`、`not_evaluated`
- `evidence_page_ids`
- `created_at`
- `updated_at`

当语义证据层尚未提供可靠字段时，不写 `confirmed` 的组内继承关系。

### 4.4 候选边属性

`CANDIDATE_CAPTION_OF` 建议属性：

- `relation_batch_id`
- `rule_version`
- `link_rule`
- `status`：`candidate`、`reviewing`、`promoted`、`rejected`、`ambiguous`
- `candidate_count`
- `score`
- `distance`
- `match_direction`
- `conflict_reason`
- `evidence_ref`
- `created_at`
- `updated_at`

`CANDIDATE_HAS_SECTION_MARK` 建议属性：

- `relation_batch_id`
- `rule_version`
- `link_rule`
- `status`
- `candidate_count`
- `score`
- `overlap_area`
- `overlap_ratio`
- `containment_status`
- `conflict_reason`
- `evidence_ref`
- `created_at`
- `updated_at`

### 4.5 AI 复核属性

候选边和由 AI 提升的正式边建议记录：

- `review_status`：`not_started`、`reviewing`、`accepted`、`rejected`、`unresolved`
- `review_run_id`
- `review_method`
- `review_model_version`
- `review_prompt_version`
- `review_score`
- `review_reason`
- `reviewed_at`
- `confirmation_method`：正式边可取 `deterministic_rule`、`multimodal_llm`、`human`

候选集合、页面上下文图像、观察版本或规则版本变化后，旧 `review_run_id` 不再作为当前候选集合的确认依据。

### 4.6 Python 数据契约

建议扩展或新增以下运行时结构：

- `RelationCandidate`：继续表达待写关系，但必须区分 `relation_spec` 和 `relation_type`；
- `RelationSpec`：固定起点、关系类型、终点和必需属性；
- `BasicInfoContextResult`：表达页面级基础信息上下文判断结果；
- `SpatialCandidateGroup`：表达同一标题或剖面标记下的完整候选集合；
- `CandidateReviewRequest`：表达 AI 复核输入；
- `CandidateReviewResult`：表达 `accepted/rejected/unresolved` 结构化输出。

这些结构优先使用不可变 dataclass，延续现有模型风格。

## 5. API设计

### 5.1 外部接口

不新增 HTTP/REST API，不开放任意 Cypher。

保留现有 CLI：

```text
scripts/enrich_block_relations.py project --rule-version <version>
scripts/enrich_block_relations.py drawing-set <drawing_set_id> --rule-version <version>
scripts/enrich_block_relations.py page <page_id> --rule-version <version>
```

这些命令只执行确定性离线派生关系增强，不默认触发 AI 复核。

### 5.2 页面级基础信息接口

建议新增内部函数：

```text
enrich_page_basic_info_context(scope, page, context) -> EnrichmentResult
```

设计语义：

- `scope` 提供批次、项目和规则版本；
- `page` 是当前页面快照；
- `context` 在 page 范围可为空，在 drawing-set/project 范围提供同一图纸册页面和基础信息锚点；
- 返回 `USES_BASIC_INFO` 关系、状态 issue 和统计。

当前页有基础信息时不依赖上下文；当前页无基础信息且上下文不足时返回 `not_evaluated`。

### 5.3 空间候选接口

建议调整现有内部函数语义：

```text
enrich_block_captions(scope, page) -> EnrichmentResult
enrich_cross_sections(scope, page) -> EnrichmentResult
```

输出可以同时包含正式关系和候选关系：

- 唯一且无冲突：正式 `HAS_CAPTION` 或 `HAS_SECTION_MARK`；
- 多候选或冲突：`CANDIDATE_CAPTION_OF` 或 `CANDIDATE_HAS_SECTION_MARK`；
- 证据不足：只输出 issue，不写候选边。

### 5.4 关系写入接口

`RelationRepository.write_relations(relations)` 保持公开签名不变，但内部按 `relation_spec` 分组。所有规格必须来自白名单。

建议新增受控状态更新接口：

```text
update_candidate_review(candidate_id_or_group_key, review_result)
promote_candidate_relation(candidate_relation, formal_relation_spec, review_metadata)
```

这两个接口只接受结构化输入，不接受 Cypher 字符串、动态 Label 或动态关系类型。

### 5.5 AI 复核接口

建议新增内部服务：

```text
CandidateReviewService.review_candidate_group(group_key) -> CandidateReviewResult
```

服务流程：

1. 读取同一候选组的全部 `CANDIDATE_*`；
2. 读取端点来源证据、bbox、页面图像路径和已有观察引用；
3. 创建 `review_run_id`；
4. 调用注入的多模态复核客户端；
5. 校验输出结构；
6. 写入候选状态；
7. 对 `accepted` 执行硬性规则校验；
8. 通过校验后提升为正式关系。

模型客户端接口：

```text
review(request) -> {status, accepted_candidate_id, score, reason}
```

其中 `status` 只能是 `accepted`、`rejected`、`unresolved`。

### 5.6 查询接口

`QueryService.get_block_relations(block_id)` 建议保持函数名，扩展返回字段：

- `caption_ids`
- `candidate_caption_ids`
- `basic_info_ids`
- `basic_info_status`
- `basic_info_source`
- `annotation_ids`
- `section_mark_ids`
- `candidate_section_mark_ids`
- `relation_status`

基础信息查询路径改为：

```text
DrawingBlock
  <-[:HAS_BLOCK]-
DrawingPage
  -[:HAS_BASIC_INFO|USES_BASIC_INFO]->
DrawingBasicInfo
```

旧 block 级 `HAS_BASIC_INFO` 可作为迁移期兼容字段读取，但不能优先于页面路径。

## 6. 异常处理

### 6.1 异常分类原则

- 编程契约错误使用分类异常并拒绝写入；
- 图纸内容缺失、上下文不足或候选不唯一使用 `EnrichmentIssue` 表达；
- AI 调用失败不应提升正式关系；
- `accepted` 未通过硬性规则校验时不得写正式关系；
- 所有异常消息必须脱敏；
- 不因派生关系失败删除来源事实。

### 6.2 基础信息异常

| 类别 | 严重性 | 处理 |
|---|---|---|
| `basic_info_not_evaluated` | warning | 缺少语义证据或上下文，暂不生成 `USES_BASIC_INFO`。 |
| `basic_info_partial` | warning | 只有一个可靠锚点或部分证据。 |
| `basic_info_ambiguous` | warning | 前后锚点冲突或组边界不唯一，不生成 confirmed 关系。 |
| `basic_info_context_unavailable` | warning | page 范围运行无法读取 drawing set 上下文。 |
| `basic_info_write_failed` | error | `USES_BASIC_INFO` 写入失败。 |

### 6.3 空间候选异常

| 类别 | 严重性 | 处理 |
|---|---|---|
| `caption_candidate_ambiguous` | warning | 写入 `CANDIDATE_CAPTION_OF`，等待 AI 复核。 |
| `caption_candidate_not_found` | warning | 无有效同页图块候选，不写候选边。 |
| `section_candidate_ambiguous` | warning | 写入 `CANDIDATE_HAS_SECTION_MARK`，等待 AI 复核。 |
| `section_candidate_low_evidence` | warning | 低于最低阈值，不写候选边。 |
| `candidate_write_failed` | error | 候选边写入失败，页面结果为 partial 或 failed。 |

### 6.4 AI 复核异常

| 类别 | 严重性 | 处理 |
|---|---|---|
| `candidate_review_unavailable` | warning | 模型服务不可用，候选保持 `candidate` 或 `ambiguous`。 |
| `candidate_review_invalid_output` | error | 模型输出不符合结构，拒绝状态更新和关系提升。 |
| `candidate_review_unresolved` | warning | 模型无法唯一判断，候选保持 `ambiguous`。 |
| `candidate_promotion_rule_failed` | error | 模型 accepted 但硬性规则未通过，不写正式关系。 |
| `candidate_review_write_failed` | error | 复核状态或正式关系写入失败。 |

### 6.5 服务状态

- 没有 warning/error：`success`；
- 有候选、partial 或 warning：`partial`；
- 写入失败、结构错误或范围级错误：按现有规则进入 `failed`；
- AI 复核失败不回滚已存在候选边；
- `unresolved` 不视为系统失败，而是业务不确定状态；
- 单页失败不阻断 drawing-set/project 范围内其他页面。

## 7. 安全方案

### 7.1 固定白名单

Neo4j Label 和关系类型必须来自 `RELATION_SPECS`。调用方只能提交 `relation_spec`、稳定业务 ID 和属性值，不得提交任意 Label、关系类型或 Cypher 片段。

禁止通过 ID 前缀推断 Label。ID 是业务标识，不是安全边界。

### 7.2 参数化查询

所有业务 ID、规则版本、批次 ID、候选分数、复核理由、状态和时间字段都使用参数化查询。任何动态 Cypher 拼接只能来自仓储内部固定白名单。

### 7.3 关系提升安全

候选提升正式关系必须满足：

- 候选关系存在且属于当前候选组；
- AI 输出为 `accepted`；
- accepted 候选唯一；
- 同页范围成立；
- 关系方向符合固定规格；
- 候选集合完整性校验通过；
- 硬性规则无冲突；
- `review_run_id` 可回查；
- 写入正式边后候选边标记为 `promoted`。

任何一项失败都不得写正式关系。

### 7.4 AI 复核安全

- 复核必须是独立第二次判断；
- 模型输入必须包含完整候选集合，不能只给单个候选；
- 模型不能直接执行数据库写入；
- 模型输出必须经过结构化校验；
- 模型理由可以存储，但不得替代规则校验；
- 模型返回 `unresolved` 时保持不确定状态，不强行唯一化。

### 7.5 数据完整性

- 来源事实关系不因派生增强或 AI 复核被删除；
- 历史 block 级 `HAS_BASIC_INFO` 不由功能逻辑静默删除；
- 候选边不参与正式事实统计；
- 与已有正式关系冲突时保留冲突候选和审计信息，不自动覆盖；
- 数据迁移必须单独、可回滚、可审计。

### 7.6 凭据与日志

- Neo4j 凭据继续来自环境变量和配置对象；
- 密码不得出现在 `repr`、日志、异常、审计或 AI 输入中；
- AI 复核输入只包含必要图纸证据和稳定业务 ID；
- `review_reason` 和错误摘要应脱敏；
- 不记录完整数据库连接字符串或认证信息。

### 7.7 范围安全

- 页面候选限定在同一 `DrawingPage`；
- 基础信息上下文限定在同一 `DrawingSet` 的候选图纸组；
- page 范围上下文不足时返回状态，不跨范围猜测；
- 不扩大数据根目录访问范围；
- 不新增后台自动任务或外部网络调用默认路径。
