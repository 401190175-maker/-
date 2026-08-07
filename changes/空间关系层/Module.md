# 空间与上下文派生关系层模块记录

本文记录当前已完成的空间与上下文派生关系层实现，面向维护者说明新模块职责、新接口、新依赖、数据变化和架构变化。本文以当前代码为准，不把 `proposal.md` / `design.md` 中尚未实现的完整语义证据层、OCR、HTTP API 或 Agent Skill 描述为已完成能力。

## 1. 新模块职责

| 文件 | 职责 |
|---|---|
| `src/drawing_graph/block_relation_enrichment.py` | 离线派生关系规则计算模块。负责把 `PageRelationSnapshot` 转换为 `RelationCandidate`、`EnrichmentIssue` 和 `EnrichmentStats`；当前已覆盖表格标题、图块标题、页面级基础信息上下文、同页注释、剖面标记正式关系和空间候选关系。 |
| `src/drawing_graph/relation_repository.py` | 离线派生关系 Neo4j 仓储模块。负责读取已入库页面快照，按固定 `RELATION_SPECS` 写入正式关系、`USES_BASIC_INFO` 和 `CANDIDATE_*` 候选关系；同时提供候选复核状态更新与候选提升接口。 |
| `src/drawing_graph/relation_service.py` | 离线派生关系编排模块。负责按 `page`、`drawing-set`、`project` 范围读取页面、调用规则、写入关系，并汇总 `RelationBatchAudit`。单页失败不阻断更大范围内其他页面。 |
| `src/drawing_graph/candidate_review.py` | 候选关系 AI 复核服务模块。负责校验完整候选组请求、调用注入的复核客户端、解析 `accepted/rejected/unresolved` 结构化结果、执行硬性提升规则，并通过仓储写回复核状态或提升正式关系。 |
| `src/drawing_graph/audit.py` | 审计模块。除基础导入审计外，新增 `RelationBatchAudit`、`RelationAuditStore` 和派生关系问题分类统计，覆盖页面级基础信息、候选边和复核状态计数。 |
| `src/drawing_graph/query_service.py` | 只读查询模块。`get_block_relations()` 通过 `DrawingPage` 页面路径读取基础信息，并返回正式关系 ID、候选关系 ID 和 `relation_status`。 |
| `scripts/enrich_block_relations.py` | 离线派生关系增强 CLI。保留原命名兼容性，支持 `project`、`drawing-set`、`page` 三种范围，输出新增统计字段，但不自动触发候选关系 AI 复核。 |
| `scripts/review_candidate_relations.py` | 显式候选复核 CLI。按完整 candidate group 构造 `CandidateReviewRequest`，调用 `CandidateReviewService.review_candidate_group`，输出 `review_run_id`、`review_status` 和候选提升结果。 |

这些模块复用原有基础导入模块：`scanner.py`、`validation.py`、`image_paths.py`、`page_number.py`、`geometry.py`、`identifiers.py`、`mapping.py`、`import_service.py`、`neo4j_repository.py` 和 `scripts/import_json.py`。基础导入仍只写来源事实，不自动触发离线增强或 AI 复核。

## 2. 新接口

### 2.1 离线增强规则接口

- `enrich_table_captions(scope, page)`：生成 `Table -[:HAS_CAPTION]-> TableCaption`。
- `enrich_block_captions(scope, page)`：唯一明确时生成 `DrawingBlock -[:HAS_CAPTION]-> BlockCaption`；歧义时生成 `BlockCaption -[:CANDIDATE_CAPTION_OF]-> DrawingBlock`。
- `enrich_current_page_basic_infos(scope, page)`：当前页存在 `DrawingBasicInfo` 且页面有图块时，生成 `DrawingPage -[:USES_BASIC_INFO]-> DrawingBasicInfo`。
- `enrich_previous_page_basic_infos(scope, page, previous_page, previous_page_context_available=True)`：当前页缺少基础信息时只返回 `basic_info_partial`、`basic_info_not_evaluated` 或 `basic_info_ambiguous`，不再生成 `DrawingBlock -[:HAS_BASIC_INFO]-> DrawingBasicInfo`。
- `enrich_page_annotations(scope, page)`：同页图块共享 `DrawingAnnotation`。
- `enrich_cross_sections(scope, page)`：唯一几何归属时生成 `DrawingBlock -[:HAS_SECTION_MARK]-> CrossSection`；多个合理候选时生成 `DrawingBlock -[:CANDIDATE_HAS_SECTION_MARK]-> CrossSection`。
- `enrich_page_relations(scope, page, previous_page=None, previous_page_context_available=True)`：组合单页表格标题、页面级基础信息、图块正式关系和候选关系。

### 2.2 关系仓储接口

- `RelationRepository.read_pages(scope, limit=100)`：读取项目、图纸册或页面范围内的页面快照。
- `RelationRepository.write_relations(relations)`：按固定关系规格幂等写入关系；不接受动态 Label、动态关系类型或任意 Cypher。
- `RelationRepository.update_candidate_review(...)`：只更新固定候选关系规格上的复核字段，状态只接受 `not_started`、`reviewing`、`accepted`、`rejected`、`unresolved`。
- `RelationRepository.promote_candidate_relation(...)`：只允许已 `accepted` 的候选关系提升为正式 `HAS_CAPTION` 或 `HAS_SECTION_MARK`，并写入 `confirmation_method` 与 `review_run_id`。

### 2.3 服务与 CLI 接口

- `RelationEnrichmentService.enrich_page(scope)`：增强单页；上下文不足时返回保守状态。
- `RelationEnrichmentService.enrich_drawing_set(scope)`：增强单个图纸册；按页码顺序传递同图纸册前页上下文。
- `RelationEnrichmentService.enrich_project(scope)`：增强整个项目；按 `drawing_set_id` 隔离不同图纸册的上下文。
- `RelationEnrichmentService.get_batch_summary(relation_batch_id)`：读取内存中的派生关系批次摘要。
- `CandidateReviewService.review_candidate_group(request)`：执行完整候选组复核，输出 `CandidateReviewResult`。
- `scripts/enrich_block_relations.py project|drawing-set|page --rule-version <version>`：显式运行确定性离线派生关系增强，不自动触发候选关系 AI 复核。
- `scripts/review_candidate_relations.py candidate-group ... --review-run-id <id>`：显式运行候选关系 AI 复核。

### 2.4 查询接口

`QueryService.get_block_relations(block_id)` 当前返回：

- `caption_ids`
- `basic_info_ids`
- `basic_info_status`
- `basic_info_source`
- `annotation_ids`
- `section_mark_ids`
- `candidate_caption_ids`
- `candidate_section_mark_ids`
- `relation_status`

其中 `basic_info_ids` 通过 `DrawingBlock <-[:HAS_BLOCK]- DrawingPage -[:HAS_BASIC_INFO|USES_BASIC_INFO]-> DrawingBasicInfo` 页面路径读取；历史 block 级基础信息只作为迁移兼容对象，不作为新结果优先来源。

## 3. 新依赖

本次空间与上下文派生关系层实现没有新增第三方 Python 包。运行依赖仍由 `requirements.txt` 管理，当前核心外部依赖是 Neo4j Python Driver。

新增模块依赖关系如下：

```text
scripts/enrich_block_relations.py
  -> config.ImportConfig
  -> relation_repository.RelationRepository
  -> relation_service.RelationEnrichmentService
  -> block_relation_enrichment.EnrichmentScope

scripts/review_candidate_relations.py
  -> config.ImportConfig
  -> relation_repository.RelationRepository
  -> candidate_review.CandidateReviewRequest
  -> candidate_review.CandidateReviewService

relation_service.py
  -> block_relation_enrichment.py
  -> audit.RelationAuditStore
  -> relation_repository.RelationRepository

candidate_review.py
  -> 注入式 review_client
  -> 可选 RelationRepository
```

候选关系 AI 复核客户端是注入依赖，当前代码不绑定具体模型供应商，不默认发起外部网络调用。

## 4. 数据变化

### 4.1 新增或调整的图谱关系

当前离线派生关系层写入以下目标关系：

- `Table -[:HAS_CAPTION]-> TableCaption`
- `DrawingBlock -[:HAS_CAPTION]-> BlockCaption`
- `DrawingBlock -[:HAS_ANNOTATION]-> DrawingAnnotation`
- `DrawingBlock -[:HAS_SECTION_MARK]-> CrossSection`
- `DrawingPage -[:USES_BASIC_INFO]-> DrawingBasicInfo`
- `BlockCaption -[:CANDIDATE_CAPTION_OF]-> DrawingBlock`
- `DrawingBlock -[:CANDIDATE_HAS_SECTION_MARK]-> CrossSection`

历史 `DrawingBlock -[:HAS_BASIC_INFO]-> DrawingBasicInfo` 不再作为目标派生关系写入。现有历史数据不由功能逻辑静默删除，后续如需清理应单独设计可回滚迁移。

### 4.2 关系属性变化

所有派生关系继续保留：

- `relation_batch_id`
- `rule_version`
- `link_rule`

页面级基础信息上下文关系包含：

- `status`
- `source`
- `source_page_id`
- `group_id`

空间候选关系包含：

- `status`
- `candidate_count`
- `score`
- `conflict_reason`
- `distance` / `match_direction`，用于标题候选。
- `overlap_area` / `overlap_ratio` / `containment_status`，用于剖面标记候选。

AI 复核写回字段包含：

- `review_status`
- `review_run_id`
- `review_model_version`
- `review_prompt_version`
- `review_score`
- `review_reason`
- `reviewed_at`
- `confirmation_method`，仅提升后的正式边使用。

### 4.3 审计和统计变化

`EnrichmentStats` 和 `RelationBatchAudit` 已覆盖：

- `uses_basic_info_count`
- `candidate_count`
- `ambiguous_count`
- `not_evaluated_count`
- `reviewing_count`
- `accepted_count`
- `rejected_count`
- `unresolved_count`

常见新增 issue 分类包括：

- `caption_candidate_ambiguous`
- `section_candidate_ambiguous`
- `basic_info_not_evaluated`
- `basic_info_partial`
- `basic_info_ambiguous`
- `candidate_review_unavailable`
- `candidate_review_invalid_output`
- `candidate_promotion_rule_failed`
- `candidate_review_write_failed`

### 4.4 测试数据变化

真实 Neo4j 派生关系集成测试使用唯一 project slug 创建可清理数据，覆盖 `USES_BASIC_INFO`、`CANDIDATE_CAPTION_OF`、`CANDIDATE_HAS_SECTION_MARK`、候选复核状态字段和重复运行幂等。未配置 `NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD` 时，该测试会跳过；跳过不代表真实 Neo4j 已通过。

## 5. 架构变化

### 5.1 从 block 级基础信息扇出改为页面级上下文

旧实现倾向于给每个 `DrawingBlock` 连接 `DrawingBasicInfo`。当前实现改为页面级上下文：

```text
DrawingBlock
  <-[:HAS_BLOCK]-
DrawingPage
  -[:HAS_BASIC_INFO|USES_BASIC_INFO]->
DrawingBasicInfo
```

当前页有基础信息时，离线增强写入 `DrawingPage -[:USES_BASIC_INFO]-> DrawingBasicInfo`。当前页缺少基础信息且上下文或语义证据不足时，返回 `partial`、`not_evaluated` 或 `ambiguous`，不把“上一页必然继承”写成正式事实。

### 5.2 从强制唯一空间匹配改为“正式关系 + 候选关系”

标题和剖面标记不再在所有冲突场景下强制生成唯一正式事实：

- 唯一且规则证据充分：写正式 `HAS_CAPTION` 或 `HAS_SECTION_MARK`。
- 多候选、冲突或证据接近：写 `CANDIDATE_CAPTION_OF` 或 `CANDIDATE_HAS_SECTION_MARK`。
- 证据不足：只记录 issue，不写候选边。

候选关系不参与正式事实结论统计；`QueryService.get_block_relations()` 以 `relation_status="candidate"` 暴露候选状态。

### 5.3 候选关系 AI 复核独立成显式流程

候选关系 AI 复核不挂到基础导入，也不挂到默认离线增强。它必须通过 `scripts/review_candidate_relations.py` 或内部服务显式触发。模型客户端只能返回结构化结果，不能直接写数据库。`accepted` 结果仍必须通过硬性规则校验，才能调用 `RelationRepository.promote_candidate_relation` 提升正式关系。

### 5.4 固定关系规格替代动态写入

`RelationRepository` 通过固定 `RELATION_SPECS` 控制起点 Label、关系类型、终点 Label 和必需属性。当前可写规格包括：

- `table_caption`
- `block_caption`
- `block_annotation`
- `block_section_mark`
- `page_uses_basic_info`
- `candidate_caption_of`
- `candidate_section_mark`

`block_basic_info` 只作为 legacy-only 规格保留，不允许新的增强流程写入。

### 5.5 保持不变的边界

- 不改变基础导入主链路：`Project -> DrawingSet -> DrawingPage -> DrawingBlock`。
- 不删除来源事实关系。
- 不新增核心业务节点类型。
- 不实现 OCR、完整语义证据层、HTTP/REST API、Agent Skill、`NEAR` 空间关系或 `DrawingBlock.block_type` 推断。
- 不默认调用外部模型。
- 不记录 Neo4j 密码、连接字符串密码或模型密钥。
