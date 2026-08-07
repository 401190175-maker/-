# 空间与上下文派生关系层对齐任务计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 `design.md` 将当前空间与上下文派生关系层调整为页面级基础信息、空间候选边和候选关系 AI 复核的目标模型。

**Architecture:** 保留基础导入主链路、显式离线派生关系增强、固定关系规格、批次审计和只读查询。确定性离线增强负责页面级基础信息上下文、正式空间关系和 `CANDIDATE_*` 候选边；候选关系 AI 复核作为独立后续流程读取候选边和证据，返回 `accepted/rejected/unresolved`，通过硬性规则校验后才提升正式关系。

**Tech Stack:** Python 3.11+、标准库 `unittest`、Neo4j Python Driver 5.x、Neo4j 5.x、PowerShell。

## Global Constraints

- 不重建基础图谱，不改变 `Project -> DrawingSet -> DrawingPage -> DrawingBlock` 追溯链路。
- 不改基础导入主链路，不让 `scripts/import_json.py` 自动触发派生增强或 AI 复核。
- 不把 AI 推断字段写入或覆盖来源事实节点。
- 不新增 HTTP/REST API、Agent Skill、`NEAR` 空间关系网络或 `DrawingBlock.block_type` 推断。
- 不把连续页码单独作为图纸组归属证明。
- 不把 `CANDIDATE_*` 关系当作正式事实参与确定性结论统计。
- 不让 AI 复核直接覆盖已有正式关系。
- Neo4j Label 和关系类型必须来自固定白名单。
- 所有属性值必须通过参数化 Cypher 写入。
- 没有设置 Neo4j 集成测试环境变量时，集成测试跳过只能报告为“未验证”，不能报告为通过。
- 每个任务只实现一个明确目标，并在进入下一任务前运行其独立测试。

## File Responsibility Map

| 文件 | 本计划中的职责 |
|---|---|
| `src/drawing_graph/block_relation_enrichment.py` | 页面级基础信息上下文、空间候选集合、正式/候选关系数据契约和增强统计。 |
| `src/drawing_graph/relation_repository.py` | 固定关系规格、页面/候选关系写入、候选复核状态更新和候选提升写入。 |
| `src/drawing_graph/relation_service.py` | page、drawing-set、project 范围编排，处理上下文不足、候选状态和失败隔离。 |
| `src/drawing_graph/candidate_review.py` | 候选关系 AI 复核请求、结果、硬性规则校验和复核服务。 |
| `src/drawing_graph/audit.py` | 页面级基础信息、候选边和 AI 复核统计及问题分类。 |
| `src/drawing_graph/query_service.py` | 图块关系查询改为页面级基础信息路径，并返回候选和歧义状态。 |
| `scripts/enrich_block_relations.py` | 保持离线增强 CLI 兼容，更新摘要和帮助文本，不自动触发 AI 复核。 |
| `scripts/review_candidate_relations.py` | 显式触发候选关系 AI 复核。 |
| `architecture.md` | 更新目标关系、数据流和阶段边界。 |
| `README.md` | 更新运行说明、候选边、AI 复核状态和查询结果。 |

---

## Task 1: 定义页面级基础信息上下文数据契约

**明确目标：** 新增表达页面级基础信息判断结果的数据契约，为 `USES_BASIC_INFO` 和保守状态输出提供统一结构。

**指定修改文件：**

- Modify: `src/drawing_graph/block_relation_enrichment.py`
- Modify: `tests/test_block_relation_models.py`

**可独立测试：**

Run: `python -m unittest tests.test_block_relation_models -v`

Expected: `BasicInfoContextResult` 接受合法 `page_id`、`status`、`source`、`source_page_id`、`group_id`、`basic_info_ids`；拒绝空 page_id、未知 status、未知 source 和非序列 basic_info_ids。

**完成标准：**

- `BasicInfoContextResult` 为不可变数据结构。
- 允许状态只包括 `confirmed`、`partial`、`ambiguous`、`not_evaluated`。
- 允许来源只包括 `current_page`、`group_start`、`group_end`、`unavailable`。
- 未修改任何 Neo4j 写入逻辑。

---

## Task 2: 定义空间候选组数据契约

**明确目标：** 新增表达同一标题或剖面标记完整候选集合的数据契约，避免只保留单一最近候选。

**指定修改文件：**

- Modify: `src/drawing_graph/block_relation_enrichment.py`
- Modify: `tests/test_block_relation_models.py`

**可独立测试：**

Run: `python -m unittest tests.test_block_relation_models -v`

Expected: `SpatialCandidateGroup` 能保存 `group_key`、`relation_spec`、`source_element_id`、候选列表、`candidate_count` 和 `conflict_reason`；候选数量与候选列表长度不一致时拒绝。

**完成标准：**

- 候选组能区分 `candidate_caption_of` 和 `candidate_section_mark`。
- 每个候选保留目标 ID、分数和几何证据。
- 数据契约不依赖 Neo4j driver 或文件系统。

---

## Task 3: 扩展关系候选属性契约

**明确目标：** 让 `RelationCandidate` 能表达正式关系、候选关系和复核元数据字段。

**指定修改文件：**

- Modify: `src/drawing_graph/block_relation_enrichment.py`
- Modify: `tests/test_block_relation_models.py`

**可独立测试：**

Run: `python -m unittest tests.test_block_relation_models -v`

Expected: `RelationCandidate` 保留现有字段，并允许候选边携带 `status`、`candidate_count`、`score`、`conflict_reason`、`review_status`、`review_run_id` 等属性；缺少必需 relation_spec 时拒绝。

**完成标准：**

- `relation_spec` 仍为必填非空字符串。
- `relation_type` 与 `relation_spec` 的合法性仍由仓储白名单校验。
- 候选关系属性不会被写入来源事实节点。

---

## Task 4: 扩展增强统计契约

**明确目标：** 为页面级基础信息、候选边和歧义状态增加独立统计字段。

**指定修改文件：**

- Modify: `src/drawing_graph/block_relation_enrichment.py`
- Modify: `tests/test_block_relation_models.py`

**可独立测试：**

Run: `python -m unittest tests.test_block_relation_models -v`

Expected: `EnrichmentStats` 新增 `uses_basic_info_count`、`candidate_count`、`ambiguous_count`、`not_evaluated_count`、`reviewing_count`、`accepted_count`、`rejected_count`、`unresolved_count`；默认值为 0，负数和布尔值被拒绝。

**完成标准：**

- 所有新增统计字段与既有计数字段使用相同非负整数校验。
- 既有统计字段和测试不回归。

---

## Task 5: 扩展固定关系规格白名单

**明确目标：** 在仓储层加入 `USES_BASIC_INFO` 和两类 `CANDIDATE_*` 固定规格，并将 block 级基础信息规格标记为 legacy-only。

**指定修改文件：**

- Modify: `src/drawing_graph/relation_repository.py`
- Modify: `tests/test_relation_repository_writes.py`

**可独立测试：**

Run: `python -m unittest tests.test_relation_repository_writes -v`

Expected: `page_uses_basic_info` 固定为 `DrawingPage/USES_BASIC_INFO/DrawingBasicInfo`；`candidate_caption_of` 固定为 `BlockCaption/CANDIDATE_CAPTION_OF/DrawingBlock`；`candidate_section_mark` 固定为 `DrawingBlock/CANDIDATE_HAS_SECTION_MARK/CrossSection`；新增强流程拒绝写入 `block_basic_info`。

**完成标准：**

- 仓储不接受动态 Label、动态关系类型或未知规格。
- `block_basic_info` 不再作为新增强流程的合法写入规格。
- 现有 table caption、block caption、annotation、section mark 规格仍可写入。

---

## Task 6: 写入页面级 USES_BASIC_INFO 关系

**明确目标：** 支持 `DrawingPage -[:USES_BASIC_INFO]-> DrawingBasicInfo` 的参数化、幂等写入。

**指定修改文件：**

- Modify: `src/drawing_graph/relation_repository.py`
- Modify: `tests/test_relation_repository_writes.py`

**可独立测试：**

Run: `python -m unittest tests.test_relation_repository_writes -v`

Expected: `page_uses_basic_info` 使用固定端点和参数化属性写入；必需属性包含 `status`、`source`、`source_page_id`、`rule_version`；重复同版本输入幂等。

**完成标准：**

- 写入 Cypher 固定匹配 `DrawingPage` 和 `DrawingBasicInfo`。
- 不从 `DrawingBlock` 起点写基础信息关系。
- `status` 和 `source` 作为属性写入关系。

---

## Task 7: 写入 CANDIDATE_CAPTION_OF 关系

**明确目标：** 支持 `BlockCaption -[:CANDIDATE_CAPTION_OF]-> DrawingBlock` 的参数化、幂等写入。

**指定修改文件：**

- Modify: `src/drawing_graph/relation_repository.py`
- Modify: `tests/test_relation_repository_writes.py`

**可独立测试：**

Run: `python -m unittest tests.test_relation_repository_writes -v`

Expected: 候选标题关系使用固定端点写入，属性包含 `status`、`candidate_count`、`score`、`distance`、`match_direction`、`conflict_reason`、`rule_version`。

**完成标准：**

- 起点只能是 `BlockCaption`。
- 终点只能是 `DrawingBlock`。
- 候选边不会被写成正式 `HAS_CAPTION`。

---

## Task 8: 写入 CANDIDATE_HAS_SECTION_MARK 关系

**明确目标：** 支持 `DrawingBlock -[:CANDIDATE_HAS_SECTION_MARK]-> CrossSection` 的参数化、幂等写入。

**指定修改文件：**

- Modify: `src/drawing_graph/relation_repository.py`
- Modify: `tests/test_relation_repository_writes.py`

**可独立测试：**

Run: `python -m unittest tests.test_relation_repository_writes -v`

Expected: 候选剖面标记关系使用固定端点写入，属性包含 `status`、`candidate_count`、`score`、`overlap_area`、`overlap_ratio`、`containment_status`、`conflict_reason`、`rule_version`。

**完成标准：**

- 起点只能是 `DrawingBlock`。
- 终点只能是 `CrossSection`。
- 候选边不会被写成正式 `HAS_SECTION_MARK`。

---

## Task 9: 更新候选复核状态

**明确目标：** 在仓储层提供受控接口更新候选边 AI 复核状态。

**指定修改文件：**

- Modify: `src/drawing_graph/relation_repository.py`
- Modify: `tests/test_relation_repository_writes.py`

**可独立测试：**

Run: `python -m unittest tests.test_relation_repository_writes -v`

Expected: `update_candidate_review(...)` 只能更新固定候选规格，状态只接受 `not_started`、`reviewing`、`accepted`、`rejected`、`unresolved`；写入 `review_run_id`、模型版本、提示词版本、分数、理由和时间。

**完成标准：**

- 不能通过该接口更新正式关系或来源事实关系。
- 非法复核状态被拒绝且不打开写事务。
- 所有复核属性参数化写入。

---

## Task 10: 提升候选为正式关系

**明确目标：** 在仓储层提供受控接口，将已通过校验的候选关系提升为正式关系。

**指定修改文件：**

- Modify: `src/drawing_graph/relation_repository.py`
- Modify: `tests/test_relation_repository_writes.py`

**可独立测试：**

Run: `python -m unittest tests.test_relation_repository_writes -v`

Expected: `promote_candidate_relation(...)` 只接受 `accepted` 候选；为 caption 候选写 `DrawingBlock -[:HAS_CAPTION]-> BlockCaption`，为 section 候选写 `DrawingBlock -[:HAS_SECTION_MARK]-> CrossSection`；候选边标记为 `promoted`。

**完成标准：**

- 未 accepted 的候选不能提升。
- 正式边保存 `confirmation_method`、`review_run_id`、`rule_version`。
- 候选提升不删除候选边。

---

## Task 11: 当前页基础信息上下文

**明确目标：** 当前页存在 `DrawingBasicInfo` 时，生成页面级基础信息上下文关系或结果。

**指定修改文件：**

- Modify: `src/drawing_graph/block_relation_enrichment.py`
- Create or Modify: `tests/test_basic_info_current_page_enrichment.py`

**可独立测试：**

Run: `python -m unittest tests.test_basic_info_current_page_enrichment -v`

Expected: 有 block 且本页有基础信息时，输出 `page_uses_basic_info` 或页面路径结果；无 block 页面不生成上下文关系；不输出 `block_basic_info`。

**完成标准：**

- 不再为页面内每个 `DrawingBlock` 扇出基础信息关系。
- 当前页基础信息优先级高于任何外部上下文。
- 统计包含 `uses_basic_info_count`。

---

## Task 12: 基础信息上下文不足状态

**明确目标：** 当前页缺失基础信息且上下文不足时返回保守状态，不再直接继承上一页为正式事实。

**指定修改文件：**

- Modify: `src/drawing_graph/block_relation_enrichment.py`
- Modify: `tests/test_basic_info_previous_page_enrichment.py`

**可独立测试：**

Run: `python -m unittest tests.test_basic_info_previous_page_enrichment -v`

Expected: 当前页有 block 但无基础信息，且缺少可靠候选图纸组上下文时，返回 `basic_info_not_evaluated` 或 `basic_info_partial`；不生成 `DrawingBlock -[:HAS_BASIC_INFO]-> DrawingBasicInfo`。

**完成标准：**

- `page_number - 1` 不再单独产生正式基础信息关系。
- 单页范围上下文不足时有明确 issue。
- 统计包含 `not_evaluated_count` 或 partial 结果。

---

## Task 13: 基础信息锚点冲突状态

**明确目标：** 在 drawing-set/project 上下文中识别基础信息锚点冲突，并返回 `ambiguous`。

**指定修改文件：**

- Modify: `src/drawing_graph/block_relation_enrichment.py`
- Modify: `tests/test_basic_info_previous_page_enrichment.py`

**可独立测试：**

Run: `python -m unittest tests.test_basic_info_previous_page_enrichment -v`

Expected: 前后锚点公共字段冲突或候选组边界不唯一时，返回 `basic_info_ambiguous`，不写 confirmed `USES_BASIC_INFO`。

**完成标准：**

- `ambiguous` 至少包含两个冲突锚点或候选组证据。
- 不用连续页码强行消解冲突。
- 不生成 block 级基础信息关系。

---

## Task 14: 页面汇总接入基础信息上下文

**明确目标：** `enrich_page_relations()` 使用页面级基础信息上下文替代当前页/上一页 block 级基础信息规则。

**指定修改文件：**

- Modify: `src/drawing_graph/block_relation_enrichment.py`
- Modify: `tests/test_enrich_page_relations.py`

**可独立测试：**

Run: `python -m unittest tests.test_enrich_page_relations -v`

Expected: 页面汇总结果包含 `USES_BASIC_INFO` 或保守状态 issue；不包含 `block_basic_info`；table caption、block caption、annotation、section mark 现有正式关系不回归。

**完成标准：**

- 汇总统计包含基础信息上下文新增计数。
- 页面无 block 时不要求基础信息上下文。
- 现有非基础信息规则继续执行。

---

## Task 15: BlockCaption 完整候选集合

**明确目标：** `enrich_block_captions()` 先生成完整图块候选集合，而不是直接只保留最近候选。

**指定修改文件：**

- Modify: `src/drawing_graph/block_relation_enrichment.py`
- Modify: `tests/test_block_caption_enrichment.py`

**可独立测试：**

Run: `python -m unittest tests.test_block_caption_enrichment -v`

Expected: 单一明确候选生成正式 `HAS_CAPTION`；多个距离接近或冲突候选生成多条 `CANDIDATE_CAPTION_OF`；候选边包含候选数量、分数、距离、方向和冲突原因。

**完成标准：**

- 不再用稳定 ID 排序作为业务确定证据。
- 被放弃的合理标题候选进入图谱候选边。
- 无有效同页 block 时只记录 issue，不写候选边。

---

## Task 16: CrossSection 完整候选集合

**明确目标：** `enrich_cross_sections()` 在多个包含或重叠候选接近时持久化候选边。

**指定修改文件：**

- Modify: `src/drawing_graph/block_relation_enrichment.py`
- Modify: `tests/test_cross_section_enrichment.py`

**可独立测试：**

Run: `python -m unittest tests.test_cross_section_enrichment -v`

Expected: 唯一包含或显著领先重叠候选生成正式 `HAS_SECTION_MARK`；多个包含候选或重叠证据接近时生成 `CANDIDATE_HAS_SECTION_MARK`；完全无重叠或低于最低阈值不写候选边。

**完成标准：**

- 候选边包含 overlap、containment、score、candidate_count 和 conflict_reason。
- 原有低重叠保护规则不回归。
- 不把歧义候选压成正式关系。

---

## Task 17: 页面范围服务写入新关系

**明确目标：** `RelationEnrichmentService.enrich_page()` 能写入页面级基础信息关系和空间候选边，并隔离单页失败。

**指定修改文件：**

- Modify: `src/drawing_graph/relation_service.py`
- Modify: `tests/test_relation_service_page.py`

**可独立测试：**

Run: `python -m unittest tests.test_relation_service_page -v`

Expected: page 范围写入 `USES_BASIC_INFO`、`CANDIDATE_CAPTION_OF`、`CANDIDATE_HAS_SECTION_MARK`；上下文不足时返回 `not_evaluated` 或 `partial`；写入失败分类为对应 issue。

**完成标准：**

- 公开接口 `enrich_page(scope)` 保持不变。
- 不自动触发 AI 复核。
- 单页内某类候选写入失败不删除来源事实。

---

## Task 18: 图纸册范围服务提供基础信息上下文

**明确目标：** `RelationEnrichmentService.enrich_drawing_set()` 为基础信息上下文判断提供同一图纸册页面序列和候选锚点。

**指定修改文件：**

- Modify: `src/drawing_graph/relation_service.py`
- Modify: `tests/test_relation_service_set.py`

**可独立测试：**

Run: `python -m unittest tests.test_relation_service_set -v`

Expected: drawing-set 范围能处理本页基础信息、上下文不足、partial 和 ambiguous；候选关系统计按页面汇总；单页失败不阻断后续页面。

**完成标准：**

- 不跨 `DrawingSet` 共享基础信息锚点。
- 直接上一页不再自动成为正式继承来源。
- 新增统计与页面结果之和一致。

---

## Task 19: 项目范围服务隔离多个图纸册

**明确目标：** `RelationEnrichmentService.enrich_project()` 在项目范围内隔离各 `DrawingSet` 的基础信息上下文和候选关系。

**指定修改文件：**

- Modify: `src/drawing_graph/relation_service.py`
- Modify: `tests/test_relation_service_project.py`

**可独立测试：**

Run: `python -m unittest tests.test_relation_service_project -v`

Expected: 多图纸册统计正确；基础信息锚点不跨图纸册；一个图纸册页面失败不阻断其他图纸册。

**完成标准：**

- project 范围汇总包含 `uses_basic_info_count`、`candidate_count`、`ambiguous_count`、`not_evaluated_count`。
- 多 drawing set 隔离测试通过。
- 现有 table caption 和 annotation 规则不回归。

---

## Task 20: 审计统计与 issue 分类

**明确目标：** `RelationBatchAudit` 汇总页面级基础信息、候选边和 AI 复核相关统计与 issue。

**指定修改文件：**

- Modify: `src/drawing_graph/audit.py`
- Modify: `tests/test_relation_audit.py`

**可独立测试：**

Run: `python -m unittest tests.test_relation_audit -v`

Expected: 审计摘要包含 candidate、reviewing、accepted、rejected、unresolved、uses_basic_info、ambiguous、partial、not_evaluated；新增 issue 分类能脱敏汇总。

**完成标准：**

- 旧统计字段仍保留。
- AI 复核日志 ID 可进入审计摘要。
- 密码和连接信息不进入审计输出。

---

## Task 21: 定义候选复核请求与结果

**明确目标：** 新增 `CandidateReviewRequest` 和 `CandidateReviewResult`，约束 AI 复核输入和输出。

**指定修改文件：**

- Create: `src/drawing_graph/candidate_review.py`
- Create: `tests/test_candidate_review_models.py`

**可独立测试：**

Run: `python -m unittest tests.test_candidate_review_models -v`

Expected: 请求必须包含候选组、完整候选集合、证据引用和 `review_run_id`；结果状态只接受 `accepted`、`rejected`、`unresolved`；`accepted` 必须包含唯一 accepted_candidate_id。

**完成标准：**

- 模型数据结构不可变。
- 不引入具体云模型 SDK。
- 非法状态或不完整 accepted 结果被拒绝。

---

## Task 22: 实现候选复核服务骨架

**明确目标：** 新增 `CandidateReviewService.review_candidate_group()`，用可注入客户端执行结构化复核。

**指定修改文件：**

- Modify: `src/drawing_graph/candidate_review.py`
- Create: `tests/test_candidate_review_service.py`

**可独立测试：**

Run: `python -m unittest tests.test_candidate_review_service -v`

Expected: 服务读取候选组、调用注入客户端、校验输出状态、返回结构化结果；客户端不可用时返回或记录 `candidate_review_unavailable`。

**完成标准：**

- 复核客户端通过接口注入。
- 服务不直接连接 Neo4j。
- 模型输出不合法时不生成 accepted 结果。

---

## Task 23: 实现候选提升硬性规则校验

**明确目标：** 对 AI `accepted` 结果执行提升前硬性规则校验。

**指定修改文件：**

- Modify: `src/drawing_graph/candidate_review.py`
- Modify: `tests/test_candidate_review_service.py`

**可独立测试：**

Run: `python -m unittest tests.test_candidate_review_service -v`

Expected: accepted 候选必须存在于当前候选组、唯一、同页范围成立、关系方向符合规格、候选集合完整；任一失败返回 `candidate_promotion_rule_failed`。

**完成标准：**

- `accepted` 不能绕过规则校验直接提升。
- `unresolved` 不视为系统失败。
- `rejected` 不触发正式关系写入。

---

## Task 24: 持久化候选复核结果

**明确目标：** 将候选复核结果写回候选边，并在 accepted 且校验通过时请求正式关系提升。

**指定修改文件：**

- Modify: `src/drawing_graph/candidate_review.py`
- Modify: `src/drawing_graph/relation_repository.py`
- Modify: `tests/test_candidate_review_service.py`

**可独立测试：**

Run: `python -m unittest tests.test_candidate_review_service tests.test_relation_repository_writes -v`

Expected: `accepted` 更新候选状态并提升正式关系；`rejected` 更新候选状态和原因；`unresolved` 更新候选为 ambiguous；写入失败返回 `candidate_review_write_failed`。

**完成标准：**

- 候选边保存 `review_run_id`、模型版本、提示词版本、分数、理由和时间。
- 正式边保存 `confirmation_method=multimodal_llm`。
- 复核失败不删除候选边。

---

## Task 25: 新增候选复核 CLI

**明确目标：** 提供显式命令触发候选关系 AI 复核，不把 AI 调用挂到现有离线增强命令中。

**指定修改文件：**

- Create: `scripts/review_candidate_relations.py`
- Create: `tests/test_candidate_review_cli.py`

**可独立测试：**

Run: `python -m unittest tests.test_candidate_review_cli -v`

Expected: CLI 支持按 candidate group 显式复核；缺少必要参数返回非零；输出 review_run_id、review_status 和统计；不读取或打印 Neo4j 密码。

**完成标准：**

- `scripts/enrich_block_relations.py` 不自动调用 AI 复核。
- 新 CLI 只通过服务接口触发复核。
- 帮助文本说明 `accepted/rejected/unresolved` 语义。

---

## Task 26: 扩展离线增强 CLI 摘要

**明确目标：** 更新 `scripts/enrich_block_relations.py` 输出新增派生统计，但不触发 AI 复核。

**指定修改文件：**

- Modify: `scripts/enrich_block_relations.py`
- Modify: `tests/test_relation_cli.py`

**可独立测试：**

Run: `python -m unittest tests.test_relation_cli -v`

Expected: project、drawing-set、page 三种模式输出 `uses_basic_info_count`、`candidate_count`、`ambiguous_count`、`not_evaluated_count`；帮助文本说明不自动复核候选关系。

**完成标准：**

- 现有 CLI 参数保持兼容。
- 未新增默认外部模型调用。
- 输出仍然脱敏。

---

## Task 27: 更新图块关系查询路径

**明确目标：** `QueryService.get_block_relations()` 通过所属页面读取基础信息，并返回候选关系状态。

**指定修改文件：**

- Modify: `src/drawing_graph/query_service.py`
- Modify: `tests/test_query_block_relations.py`

**可独立测试：**

Run: `python -m unittest tests.test_query_block_relations -v`

Expected: 查询路径包含 `DrawingBlock <-[:HAS_BLOCK]- DrawingPage -[:HAS_BASIC_INFO|USES_BASIC_INFO]-> DrawingBasicInfo`；返回 `basic_info_status`、`basic_info_source`、`candidate_caption_ids`、`candidate_section_mark_ids`；旧 block 级基础信息只作为迁移兼容，不优先返回。

**完成标准：**

- 不暴露 Neo4j 内部 ID。
- 不开放任意 Cypher。
- `relation_status` 能区分 `candidate`、`ambiguous`、`not_evaluated`。

---

## Task 28: 更新架构文档

**明确目标：** 让 `architecture.md` 与新的空间与上下文派生关系层目标模型一致。

**指定修改文件：**

- Modify: `architecture.md`
- Modify: `tests/test_cross_section_docs.py`

**可独立测试：**

Run: `python -m unittest tests.test_cross_section_docs -v`

Expected: 文档包含 `USES_BASIC_INFO`、`CANDIDATE_CAPTION_OF`、`CANDIDATE_HAS_SECTION_MARK`、候选关系 AI 复核边界；不再把 block 级 `HAS_BASIC_INFO` 描述为目标关系。

**完成标准：**

- 来源事实层仍保留 `DrawingPage -[:HAS_BASIC_INFO]-> DrawingBasicInfo`。
- 空间与上下文派生关系层列出正式关系和候选关系。
- AI 复核说明为独立后续流程，不挂到基础导入。

---

## Task 29: 更新 README 使用说明

**明确目标：** 让 `README.md` 说明页面级基础信息、候选边、AI 复核和查询状态。

**指定修改文件：**

- Modify: `README.md`
- Modify: `tests/test_readme.py`
- Modify: `tests/test_relation_readme.py`

**可独立测试：**

Run: `python -m unittest tests.test_readme tests.test_relation_readme -v`

Expected: README 不再描述 block 级基础信息为目标关系；说明 `USES_BASIC_INFO`、候选边、`accepted/rejected/unresolved`、`review_run_id`、显式复核命令和 Neo4j 集成测试边界。

**完成标准：**

- 用户能区分离线增强和 AI 复核两个阶段。
- README 不声称完整语义证据层已经实现。
- README 不包含真实凭据。

---

## Task 30: 更新 proposal/design/tasks 文档一致性测试

**明确目标：** 增加静态文档测试，防止 proposal、design、tasks 对目标关系和非目标范围描述不一致。

**指定修改文件：**

- Create or Modify: `tests/test_planning_docs.py`
- Modify: `proposal.md`
- Modify: `design.md`
- Modify: `tasks.md`

**可独立测试：**

Run: `python -m unittest tests.test_planning_docs -v`

Expected: 三份规划文档均包含 `USES_BASIC_INFO`、`CANDIDATE_CAPTION_OF`、`CANDIDATE_HAS_SECTION_MARK`、AI 复核、`review_run_id`；均不把 `DrawingBlock -[:HAS_BASIC_INFO]-> DrawingBasicInfo` 作为目标关系。

**完成标准：**

- 文档一致性测试只检查规划边界，不声称代码已实现。
- 测试失败信息能指出缺失文件和缺失关键词。

---

## Task 31: 更新真实 Neo4j 派生关系集成测试

**明确目标：** 在真实 Neo4j 测试库验证 `USES_BASIC_INFO` 和 `CANDIDATE_*` 的写入、查询和幂等。

**指定修改文件：**

- Modify: `tests/integration/test_neo4j_relation_enrichment.py`

**可独立测试：**

Run: `python -m unittest tests.integration.test_neo4j_relation_enrichment -v`

Expected with configured disposable database: PASS，验证页面级基础信息、候选标题边、候选剖面标记边、候选复核状态字段和重复运行幂等。未配置 `NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD` 时测试跳过并报告未验证。

**完成标准：**

- 集成测试使用独立测试库或可清理 project slug。
- 候选边不被计入正式关系统计。
- 缺少环境变量时不报告为真实 Neo4j 通过。

---

## Task 32: 执行完整回归验证

**明确目标：** 验证本轮空间与上下文派生关系层调整没有破坏现有导入、增强、查询和文档边界。

**指定修改文件：**

- No production file changes.
- Modify only if verification exposes an in-scope defect: the exact source or test file responsible for that defect.

**可独立测试：**

Run: `python -m unittest discover tests -v`

Then, with configured disposable Neo4j:

- `python -m unittest tests.integration.test_neo4j_import -v`
- `python -m unittest tests.integration.test_neo4j_relation_enrichment -v`

Expected: 所有非跳过测试零失败；真实 Neo4j 集成测试零失败。若集成环境变量缺失，必须单独报告未验证。

**完成标准：**

- 全量测试发现中的所有非跳过测试通过。
- 两组真实 Neo4j 集成测试通过，或明确记录因缺少环境变量而未验证。
- `proposal.md`、`design.md`、`tasks.md`、`architecture.md`、`README.md` 术语一致。
- 没有新增动态 Cypher、自动删除历史关系、默认外部模型调用或无关重构。
