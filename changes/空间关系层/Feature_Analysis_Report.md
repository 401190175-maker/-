# 来源事实层调整功能分析报告

> 2026-08-05 更新说明：本文件最初用于分析“来源事实层 / Table 标题关系迁移”。本次追加第 14 节，专门分析当前架构与《图块图谱方案.md》中“空间与上下文派生关系层”的差异。前 1-13 节保留其历史结论；涉及 `DrawingBasicInfo`、`CANDIDATE_*` 和查询路径时，以第 14 节为新的对齐分析。

## 1. 报告目的

本文只分析一项架构调整：使当前项目的“基础导入/基础关系”严格符合《图块图谱方案.md》中的“来源事实层”定义，并将通过 bbox 几何计算得到的 `Table -[:HAS_CAPTION]-> TableCaption` 从基础导入流程迁移到离线派生关系增强流程。

本文不实施代码，不修改 Neo4j 数据，不展开语义证据层、多模态识别、`DrawingBasicInfo` 页面级迁移或其他图谱方案阶段。

本次确认采用“方案一：最小迁移”。基本原则是：

- 保留现有 `Table`、`TableCaption` 节点及其稳定业务 ID、bbox 和页面归属；
- 保留 `DrawingPage -[:HAS_TABLE]-> Table`；
- 保留 `DrawingPage -[:HAS_ELEMENT]-> TableCaption`；
- 从来源事实层移除 `Table -[:HAS_CAPTION]-> TableCaption`；
- 保留现有表格标题几何匹配算法，但将其执行时机迁移到离线派生关系增强；
- 不新增业务节点类型，不新增关系类型，不重建基础图谱。

## 2. 需求边界

### 2.1 目标边界

修改后，基础导入应严格终止于：

```text
原始 JSON/PNG
  -> 来源节点
  -> 页面归属关系
  -> 稳定 ID、图片路径、bbox
  -> ImportBatch 审计
```

基础导入只保存原始标注及文件结构能够直接确定的事实。任何需要比较两个独立标注区域的 bbox、距离、方向、包含或重叠才能得到的关系，都不属于来源事实层。

因此：

- “某个 `TableCaption` 位于某个 `DrawingPage`”是来源事实；
- “某个 `TableCaption` 属于哪个 `Table`”需要几何匹配，是派生关系；
- 即使当前算法能够确定最近表格，也不能把算法执行结果描述成原始标注直接给出的事实。

### 2.2 非目标

本次不处理：

- 不改变 `Table` 或 `TableCaption` 节点属性；
- 不改变 `DrawingPage` 到表格、表格标题的页面归属关系；
- 不改变 `DrawingBlock -[:HAS_CAPTION]-> BlockCaption` 的现有规则；
- 不引入 `CANDIDATE_*` 候选边或多模态复核；
- 不调整 `DrawingBasicInfo`、`DrawingAnnotation`、`CrossSection` 的现有实现；
- 不新增 HTTP/REST API、Agent Skill、OCR 或多模态识别；
- 不重构全部派生关系为通用插件框架；
- 不在本报告中执行既有 Neo4j 数据清理或回填。

## 3. 当前实现证据

### 3.1 当前架构文档的归类

当前 `architecture.md` 将系统分为“基础导入流程”和“离线 block 级关系增强流程”，但基础导入流程中仍包含“表格标题匹配”。其“基础关系”列表也把 `Table -[:HAS_CAPTION]-> TableCaption` 与页面来源关系放在同一层。

这造成两个概念混在一起：

1. `DrawingPage -[:HAS_ELEMENT]-> TableCaption` 是原始标注可以直接确定的页面归属事实；
2. `Table -[:HAS_CAPTION]-> TableCaption` 是由同页 bbox 距离算法计算出的派生关系。

目标方案要求将二者分层保存，当前文档分类与目标方案不一致。

### 3.2 当前基础导入调用路径

当前 `ImportService.import_page()` 在单页数据完成校验、路径修正、页码解析、几何规范化、ID 生成和元素映射后，还会执行 `_append_table_caption_relations()`。

`_append_table_caption_relations()` 的职责是：

- 从当前页面的 `ElementRecord` 中筛选 `table`；
- 筛选 `table caption`；
- 调用 `match_table_captions()`；
- 把返回的 `HAS_CAPTION` 加入基础导入关系集合；
- 如果没有可匹配表格，将 `CaptionMatchingError.category` 记入基础导入 warning。

因此，当前基础导入不只是保存来源事实，还直接执行了一条几何派生规则。

### 3.3 当前几何匹配算法

`src/drawing_graph/caption_matching.py` 中的 `match_table_captions()` 已实现并有独立测试，当前规则为：

- 每个 `TableCaption` 在给定表格集合中选择 bbox 距离最小的 `Table`；
- 距离相同时按 `Table.id` 字典序稳定决胜；
- 一个标题最多返回一条 `HAS_CAPTION`；
- 一个表格可以接收多个标题；
- 有标题但没有表格时抛出分类异常；
- 输入元素类型不正确时抛出分类异常。

本次需求改变的是算法所属层和执行时机，不要求改变这套几何规则。

### 3.4 当前派生关系增强的数据契约限制

当前离线增强基础设施可以按项目、图纸册或页面读取图谱、执行规则、幂等写关系并记录审计，但它仍以 `DrawingBlock` 为中心：

- `PageRelationSnapshot` 只有 blocks、captions、basic_infos、annotations、cross_sections，没有 tables 和 table_captions；
- `RelationCandidate` 的文档语义是从 `DrawingBlock` 指向增强元素；
- `RelationRepository` 写入时固定使用 `DrawingBlock` 作为起点；
- `RELATION_END_LABELS` 把 `HAS_CAPTION` 唯一映射为 `BlockCaption`；
- 同一个 `HAS_CAPTION` 关系类型目前无法在该仓储中同时表达 `DrawingBlock -> BlockCaption` 和 `Table -> TableCaption` 两组端点；
- `EnrichmentStats` 和 `RelationBatchAudit` 没有 table_count、table_caption_count 或 table_caption_relation_count。

所以现有增强基础设施具备复用条件，但不能在不调整数据契约和仓储端点约束的情况下直接承载表格标题关系。

### 3.5 当前测试边界

当前测试把表格标题关系当成基础导入产物：

- `tests/test_import_page.py` 明确断言单页基础导入后出现一条 `HAS_CAPTION`；
- `tests/test_caption_matching.py` 独立验证几何匹配算法；
- `tests/test_mapping.py` 已正确验证 `TableCaption` 通过 `HAS_ELEMENT` 归属于页面；
- `tests/test_relation_repository_writes.py` 当前只验证 `DrawingBlock -[:HAS_CAPTION]-> BlockCaption` 的仓储端点；
- 离线增强的页面、服务、仓储和集成测试尚未覆盖 `Table -[:HAS_CAPTION]-> TableCaption`。

这意味着迁移必须同时改变测试职责，不能只移动生产调用。

## 4. 当前架构是否支持

### 4.1 结论

当前架构“原则上支持、实现上需要扩展”。

支持条件已经存在：

- 基础导入和离线增强是两个显式分离的流程；
- `Table`、`TableCaption` 及页面来源关系已经入库；
- 两类节点都有稳定 ID 和 bbox；
- 离线增强已经能按 project、drawing-set、page 三种范围读取页面快照；
- 派生关系具有 `relation_batch_id`、`rule_version`、`link_rule` 和分类审计；
- Neo4j 基础白名单已经允许 `Table`、`TableCaption` 和 `HAS_CAPTION`；
- `match_table_captions()` 的确定性算法和单元测试可以复用。

当前不能直接支持的部分是：

- 增强快照不读取表格和表格标题；
- 增强关系数据契约默认起点为 `DrawingBlock`；
- 仓储使用“关系类型 -> 单一终点 Label”的映射，无法区分同名关系的两组合法端点；
- 审计统计没有表格标题维度；
- 当前 README、architecture 和测试把匹配行为放在基础导入阶段。

因此，不需要新建第二套导入或新建图谱，但需要把现有离线增强从“只支持 block 起点”适度泛化为“支持固定白名单的派生关系端点组合”。

### 4.2 Schema 是否需要修改

不需要修改 `scripts/create_schema.cypher`。

原因是：

- `Table` 和 `TableCaption` 唯一约束已经存在；
- `HAS_CAPTION` 关系类型已经存在；
- Neo4j 不要求为新增的合法端点组合单独创建关系 Schema；
- 本次没有新增节点属性索引需求。

需要改变的是应用层关系端点白名单和派生写入规则，不是数据库结构。

## 5. 需要新增的能力或模块

### 5.1 是否需要新增生产模块

采用方案一后，不建议新增独立生产模块。

现有模块已经覆盖：

- 几何算法：`caption_matching.py`；
- 页面级规则组合：`block_relation_enrichment.py`；
- 图谱读取与派生关系写入：`relation_repository.py`；
- 项目、图纸册、页面范围编排：`relation_service.py`；
- 离线 CLI：`scripts/enrich_block_relations.py`；
- 派生批次审计：`audit.py`。

新增一个独立表格增强模块会增加接口和测试层，但当前只有一条成熟规则，没有足够复杂度支撑新的生产模块边界。

### 5.2 需要新增的数据契约字段

需要在现有派生快照中加入：

- `tables`：同页 `Table` 快照；
- `table_captions`：同页 `TableCaption` 快照。

需要在派生统计和审计中考虑加入：

- `table_count`；
- `table_caption_count`；
- 表格标题匹配关系数可继续纳入总 `relation_count`，也可以增加 `table_caption_relation_count` 方便验收。

其中前两项是输入规模证据，第三项是可选的专门结果指标。为了提高迁移可观察性，推荐三项都保留。

### 5.3 需要新增的规则入口

建议在现有派生规则层增加 `enrich_table_captions(scope, page)`，职责是：

1. 读取同一页面内的 tables 和 table_captions；
2. 调用现有 `match_table_captions()` 几何算法；
3. 将算法结果包装为带批次、规则版本和 link_rule 的派生关系数据；
4. 将缺失表格、非法输入或无法匹配转换为 `EnrichmentIssue`；
5. 返回关系、问题和统计；
6. 由 `enrich_page_relations()` 与现有四类规则一起汇总。

这样可以保留纯几何算法，又让执行结果进入统一派生审计。

### 5.4 需要新增的固定端点规格

当前仓储不能只用 `HAS_CAPTION` 推断终点 Label，因为同一关系类型存在两组合法端点：

- `DrawingBlock -[:HAS_CAPTION]-> BlockCaption`
- `Table -[:HAS_CAPTION]-> TableCaption`

推荐把仓储白名单从“关系类型 -> 终点 Label”升级为固定的“派生关系规格”，每个规格至少定义：

- 规格标识；
- 起点 Label；
- 关系类型；
- 终点 Label；
- 必需证据属性。

派生关系对象引用固定规格标识，仓储据此选择预定义 Label 和关系类型。调用方不能自由传入 Cypher Label，从而继续满足白名单和注入防护要求。

这不是新增业务关系，而是对现有应用层安全契约的泛化。

## 6. 影响的已有模块

### 6.1 直接影响

| 文件或模块 | 当前职责 | 所需调整 | 影响程度 |
|---|---|---|---|
| `architecture.md` | 描述现有两条流程和“基础关系” | 将“基础关系”正式改名为“来源事实层”；移除其中的 Table `HAS_CAPTION`；在派生层加入表格标题关系；更新两条数据流 | 高 |
| `README.md` | 使用者运行说明 | 从基础导入说明中移除表格标题匹配；在离线增强说明中增加该规则、执行时机、审计和验证方式 | 高 |
| `src/drawing_graph/import_service.py` | 单页基础导入编排 | 停止调用 `_append_table_caption_relations()`；移除只为该调用服务的依赖和辅助函数；基础导入仍创建 Table、TableCaption 和页面关系 | 高 |
| `src/drawing_graph/caption_matching.py` | 表格标题几何算法 | 保留算法；必要时仅适配派生规则调用的数据形式，不改变现有匹配语义 | 低至中 |
| `src/drawing_graph/block_relation_enrichment.py` | 页面派生规则与数据契约 | 增加 tables、table_captions、表格标题规则、统计和页面汇总 | 高 |
| `src/drawing_graph/relation_repository.py` | 读取页面快照并写 block 起点关系 | 读取 Table/TableCaption；支持固定白名单下的 Table 起点；解决同一 `HAS_CAPTION` 的两组合法端点 | 高 |
| `src/drawing_graph/relation_service.py` | 范围编排与失败隔离 | 将表格标题规则纳入 page/set/project 三种范围；保持单页失败隔离 | 中 |
| `src/drawing_graph/audit.py` | 派生批次统计和问题汇总 | 增加表格、表格标题及可选专门关系计数；表格标题问题进入派生审计而不是导入审计 | 中 |
| `scripts/enrich_block_relations.py` | 离线增强 CLI | 保留文件和命令兼容性；输出摘要增加表格相关计数；帮助文本改为派生关系增强 | 中 |
| `tests/test_import_page.py` | 基础导入闭环 | 保留 Table、TableCaption、页面关系断言；改为明确断言基础导入不产生 Table `HAS_CAPTION` | 高 |
| `tests/test_caption_matching.py` | 几何规则测试 | 保留全部确定性算法测试，并在测试说明中归入派生关系规则测试 | 低 |

### 6.2 需要扩展的派生关系测试

需要修改或增加覆盖：

- `tests/test_block_relation_models.py`：tables、table_captions、关系规格和统计字段；
- `tests/test_enrich_page_relations.py`：页面汇总包含表格标题关系；
- `tests/test_relation_repository_reads.py`：快照读取 Table 和 TableCaption；
- `tests/test_relation_repository_writes.py`：验证 Table/HAS_CAPTION/TableCaption 固定端点、参数化和幂等；
- `tests/test_relation_service_page.py`：单页范围写入表格标题关系；
- `tests/test_relation_service_set.py`：图纸册范围汇总及单页失败隔离；
- `tests/test_relation_service_project.py`：项目范围汇总；
- `tests/test_relation_cli.py`：CLI 摘要和错误分类；
- `tests/test_relation_audit.py`：表格相关计数与 warning/error；
- `tests/integration/test_neo4j_import.py`：基础导入后只存在来源事实，不再期待 Table `HAS_CAPTION`；
- `tests/integration/test_neo4j_relation_enrichment.py`：显式增强后产生 Table `HAS_CAPTION`，重复增强保持预期幂等。

### 6.3 文档测试和登记文档

还需要检查：

- `tests/test_readme.py`；
- `tests/test_relation_readme.py`；
- `module.md` 中 import、caption matching、relation enrichment 的职责；
- `design.md`、`proposal.md`、`tasks.md` 中仍把表格标题匹配放入基础导入的历史描述。

本次架构调整至少应同步 architecture、README 和 module。旧 design/proposal/tasks 如果作为历史阶段档案保留，应明确标注其阶段性，而不是让它们继续作为当前架构依据；如果仍被测试或维护流程视为现行规范，则必须同步更新。

### 6.4 原则上不受影响

以下模块不需要因本需求改变业务逻辑：

- `scanner.py`、`validation.py`；
- `image_paths.py`、`page_number.py`、`geometry.py`、`identifiers.py`；
- `mapping.py`，其中 `TableCaption -> HAS_ELEMENT -> DrawingPage` 的映射必须保留；
- `scripts/create_schema.cypher`；
- `QueryService.get_block_relations()`，因为表格标题关系不应改变 block 的四组增强状态。

## 7. 技术方案比较

### 7.1 方案一：迁入现有派生关系增强流程

做法：保留 `caption_matching.py`，在现有页面派生规则中增加包装入口，扩展快照、仓储端点规格、服务、审计和测试。

优点：

- 改动集中，复用现有算法和增强编排；
- 不新增业务节点、关系类型或数据库 Schema；
- project、drawing-set、page 三种运行范围自然复用；
- 表格标题关系获得统一 rule_version、relation_batch_id 和审计；
- 基础导入边界变得严格、清晰；
- 不引入与本需求无关的大规模重构。

缺点：

- `block_relation_enrichment.py` 和 `enrich_block_relations.py` 的名称不再完全准确；
- 需要泛化当前“起点固定为 DrawingBlock”的仓储契约；
- 同一个 `HAS_CAPTION` 对应两组端点，不能继续使用当前简单映射；
- 现有数据库内无规则版本的旧关系需要兼容处理。

### 7.2 方案二：新增独立表格关系增强模块

做法：新增 `table_relation_enrichment.py` 及专门仓储或服务接口，再由离线 CLI 调用。

优点：

- 表格关系职责独立；
- 不需要让 block 规则文件承载 Table 起点；
- 未来扩展表格结构关系时边界清晰。

缺点：

- 仅为一条成熟规则增加模块、接口和测试层；
- 可能复制范围编排、审计和写入逻辑；
- 如果仍要共用 CLI 和批次，最终仍需修改现有服务；
- 当前阶段维护成本高于收益。

### 7.3 方案三：重构为通用派生关系规则框架

做法：引入规则注册器或插件协议，将五类派生规则统一注册、执行和写入。

优点：

- 长期扩展性最好；
- 可以统一不同起点、终点和证据属性；
- 文件命名和概念可彻底泛化。

缺点：

- 改动范围最大；
- 会触及所有已验证的 block 关系；
- 回归风险高，难以维持小步验证；
- 当前只有一个新增非 block 规则，抽象依据不足；
- 容易把一次架构归层修正扩大为无关重构。

### 7.4 比较结论

| 维度 | 方案一 | 方案二 | 方案三 |
|---|---|---|---|
| 符合来源事实层目标 | 是 | 是 | 是 |
| 改动范围 | 小到中 | 中 | 大 |
| 复用现有增强流程 | 高 | 中 | 低，需重构后复用 |
| 新增生产模块 | 否 | 是 | 是 |
| 对现有四类 block 关系风险 | 低至中 | 低 | 高 |
| 长期扩展性 | 中 | 中到高 | 高 |
| 当前投入产出比 | 最优 | 一般 | 较低 |

## 8. 推荐方案

### 8.1 推荐结论

推荐方案一：将表格标题匹配迁入现有离线派生关系增强流程，并只做支持该关系所必需的契约泛化。

推荐原因：

- 本次问题是执行层归类错误，不是算法缺失；
- 现有增强流程已经具备范围、批次、失败隔离、幂等写入和审计；
- 新建模块不能显著降低当前复杂度；
- 通用规则框架会放大回归面；
- 最小迁移最符合“不重建底座、不做无关重构”的原则。

### 8.2 推荐目标架构

来源事实层：

```text
Project -[:HAS_SET]-> DrawingSet
DrawingSet -[:HAS_PAGE]-> DrawingPage
DrawingPage -[:HAS_BLOCK]-> DrawingBlock
DrawingPage -[:HAS_TABLE]-> Table
DrawingPage -[:HAS_ELEMENT]-> TableCaption
DrawingPage -[:HAS_ELEMENT]-> BlockCaption / CrossSection / IgnoredElement
DrawingPage -[:HAS_BASIC_INFO]-> DrawingBasicInfo
DrawingPage -[:HAS_ANNOTATION]-> DrawingAnnotation
DrawingPage -[:HAS_TEXT]-> PlainText / Title
DrawingPage -[:IMPORTED_IN]-> ImportBatch
```

空间与上下文派生关系层：

> 注：下列列表保留旧报告当时的迁移目标。关于 `DrawingBasicInfo` 的目标关系，第 14 节已将其修正为页面级 `DrawingPage -[:HAS_BASIC_INFO|USES_BASIC_INFO]-> DrawingBasicInfo`，不再建议新增 block 级 `HAS_BASIC_INFO`。

```text
Table -[:HAS_CAPTION]-> TableCaption
DrawingBlock -[:HAS_CAPTION]-> BlockCaption
DrawingBlock -[:HAS_BASIC_INFO]-> DrawingBasicInfo
DrawingBlock -[:HAS_ANNOTATION]-> DrawingAnnotation
DrawingBlock -[:HAS_SECTION_MARK]-> CrossSection
```

说明：本报告只迁移 Table 标题关系的所属流程。其他 block 级关系是否符合目标图块图谱的最终语义，不属于本次范围。

### 8.3 推荐数据流

基础导入：

```text
JSON 文件
  -> validate_document()
  -> normalize_image_path()
  -> parse_page_number()
  -> normalize_geometry()
  -> make_shape_hash() / make_element_id()
  -> ElementRecord
  -> map_element()
  -> merge_nodes()
  -> merge_relations() 仅写来源事实
  -> link_page_to_batch()
```

离线派生关系增强：

```text
显式运行 enrich_block_relations.py
  -> 读取页面、Table、TableCaption 及现有 block 关系输入
  -> 执行 match_table_captions()
  -> 包装为带规则版本和批次证据的派生关系
  -> 按固定端点规格幂等写入 HAS_CAPTION
  -> 记录匹配数量、warning/error 和批次摘要
```

### 8.4 模块命名处理

为保持命令兼容，本次不建议立即重命名：

- `block_relation_enrichment.py`；
- `scripts/enrich_block_relations.py`。

但文档中的架构名称应从“离线 block 级关系增强”调整为“离线派生关系增强”，并说明当前 CLI 文件名是兼容保留名称。

只有当后续继续加入多个非 block 起点的派生规则时，才应另立任务将文件和类型系统整体更名；本次不提前承担该迁移成本。

## 9. 既有数据兼容与迁移

### 9.1 既有关系的语义

现有 Neo4j 中已经由基础导入生成的 `Table -[:HAS_CAPTION]-> TableCaption`，其业务语义与迁移后的关系相同，差异主要是：

- 旧关系由基础导入产生；
- 旧关系通常没有 relation_batch_id、rule_version、link_rule；
- 新关系由显式离线增强产生并带派生证据。

因此，不应仅因为架构归层变化就无条件删除旧关系。

### 9.2 重复关系风险

当前派生仓储使用带 `rule_version` 的关系 `MERGE` 语义。旧 Table 标题关系没有该属性，如果新流程直接按带规则版本的模式写入，可能在相同 Table 和 TableCaption 之间创建第二条 `HAS_CAPTION`。

这是本次迁移的主要数据风险。

### 9.3 推荐兼容策略

推荐在未来实现中采用“识别并接管 legacy 关系”的兼容策略：

1. 新流程计算出同一 Table/TableCaption 配对；
2. 写入前检查两端之间是否已有无规则版本的 `HAS_CAPTION`；
3. 如果旧关系与新计算结果一致，为旧关系补充迁移标识、规则版本和审计信息，避免生成重复边；
4. 如果旧关系与新规则结果不一致，不自动删除或覆盖，记录迁移冲突；
5. 冲突数据通过独立、可回滚的 backfill/migration 任务处理；
6. 新导入页面不再由基础导入产生该关系，只有显式增强后才出现。

如果不实现 legacy 接管，就必须提供一次性迁移脚本；二者至少选择其一，不能直接忽略旧关系。

### 9.4 运行时状态变化

迁移后，一个刚完成基础导入的页面可能已经具有 Table 和 TableCaption，但暂时没有二者之间的 `HAS_CAPTION`。这是合法的“尚未增强”状态，不是导入失败。

README、审计和验证说明必须明确：

- 来源事实导入成功；
- 表格标题派生关系尚未执行；
- 显式运行离线增强后才生成匹配关系。

`QueryService.get_block_relations()` 的 `relation_status` 只描述 block 四组关系，不应把 Table 标题关系加入其 `enhanced` 判定，否则会改变现有接口语义。

## 10. 测试与验收方案

### 10.1 基础导入验收

基础导入测试应验证：

- `Table` 节点存在；
- `TableCaption` 节点存在；
- `DrawingPage -[:HAS_TABLE]-> Table` 存在；
- `DrawingPage -[:HAS_ELEMENT]-> TableCaption` 存在；
- 基础导入结果中不存在 `Table -[:HAS_CAPTION]-> TableCaption`；
- 不再因缺少 Table 而在基础导入 warning 中产生表格标题匹配异常；
- ImportBatch、稳定 ID、图片路径和 bbox 行为不变。

### 10.2 几何规则验收

保留 `tests/test_caption_matching.py`，继续验证：

- 单表单标题；
- 多表选择最小 bbox 距离；
- 等距按稳定 ID 决胜；
- 每个标题最多一条关系；
- 一个表格可关联多个标题；
- 缺少表格和输入类型错误的分类异常。

该测试文件从概念上归入派生关系规则测试，但不必为了本次调整重命名文件或重写成熟算法。

### 10.3 派生流程验收

离线增强测试应验证：

- 页面快照能够读取 Table 和 TableCaption；
- project、drawing-set、page 三种范围均会执行表格标题匹配；
- 生成的关系端点固定为 Table/HAS_CAPTION/TableCaption；
- 属性包含 relation_batch_id、rule_version、link_rule；
- 重复运行符合确定的幂等策略；
- 缺失表格时不影响同页其他派生关系；
- 单页失败不阻断图纸册和项目范围内其他页面；
- 审计摘要包含表格及表格标题统计；
- legacy 无版本关系不会被静默复制为重复当前关系。

### 10.4 文档验收

`architecture.md` 必须满足：

- “基础关系”标题改为“来源事实层”；
- 来源事实层不含 `Table -[:HAS_CAPTION]-> TableCaption`；
- 基础导入数据流不调用 `match_table_captions()`；
- 空间与上下文派生关系层包含 Table 标题关系；
- `caption_matching.py` 的职责描述为派生几何规则；
- 离线增强模块职责包含 Table/TableCaption；
- 基础导入终点与本报告第 2.1 节一致。

`README.md` 必须满足：

- 项目概述不再声称基础导入自动完成表格标题匹配；
- 导入章节说明只创建来源事实；
- 离线增强章节列出表格标题规则；
- 明确新导入页面在增强前可能没有 Table `HAS_CAPTION`；
- 测试说明和常见错误按新阶段边界更新。

## 11. 风险分析

### 11.1 高风险

#### 同名关系的端点歧义

`HAS_CAPTION` 同时用于 DrawingBlock/BlockCaption 和 Table/TableCaption。若仓储仍按关系类型唯一推断端点 Label，会把 Table 关系写成错误端点或拒绝写入。

缓解：使用固定关系规格白名单，不能依赖关系名称或 ID 前缀猜测端点。

#### 既有数据重复边

旧关系无 rule_version，新关系带 rule_version；直接采用当前 `MERGE` 方式可能生成平行重复边。

缓解：实现 legacy 接管或单独的可回滚迁移，不允许无策略直接上线。

### 11.2 中风险

#### 基础导入成功但关系暂缺被误判为失败

使用者可能仍预期导入后立即看到表格标题关系。

缓解：同步 README、审计状态和运行顺序，明确导入与增强是两个合法阶段。

#### 派生增强名称与职责不一致

文件和 CLI 仍叫 block relations，但开始处理 Table 起点关系。

缓解：本次保留文件名兼容，在架构文档中使用“离线派生关系增强”；达到多个非 block 规则后再单独重命名。

#### 审计口径变化

`missing_table` 等问题将从导入 warning 移到派生关系 issue，历史统计不能直接横向比较。

缓解：在版本说明中记录统计口径变更，保留明确 rule_version。

#### 规则重复调用或漏调用

如果 `_append_table_caption_relations()` 未从导入路径完全移除，同时又加入增强路径，会重复执行；如果只删除未接入页面汇总，则关系完全缺失。

缓解：基础导入负向测试和离线增强正向测试必须同时存在。

### 11.3 低风险

#### Schema 误改

本需求不需要新增 Schema。无必要的 Schema 调整会扩大部署风险。

缓解：保持 `create_schema.cypher` 不变，仅验证既有 Table、TableCaption 约束仍存在。

#### 几何规则行为意外变化

迁移过程中如果顺便重写算法，可能改变等距决胜和一个表格多标题等既有行为。

缓解：保留 `test_caption_matching.py`，本次只改变调用层，不改变算法语义。

## 12. 实施顺序建议

后续如进入代码实施，建议采用以下小步顺序：

1. 先修改基础导入测试，使其要求“保留来源节点和页面关系，但不产生 Table `HAS_CAPTION`”；
2. 从 `ImportService` 移除表格标题匹配调用；
3. 扩展派生页面快照和仓储读取；
4. 增加表格标题派生规则包装及规则级测试；
5. 泛化固定端点规格并增加仓储写入测试；
6. 接入 page、drawing-set、project 服务编排及审计；
7. 增加 legacy 关系兼容测试；
8. 更新 architecture、README、module 和文档测试；
9. 运行全部非集成测试；
10. 在独立 Neo4j 测试库验证“基础导入无关系、显式增强有关系、重复运行无非预期重复边”。

本顺序仅用于说明技术依赖和风险控制，不代表本报告已授权或执行代码修改。

## 13. 最终结论

当前架构能够支持本次来源事实层调整，不需要重建项目，也不需要新增业务节点、关系类型、Schema 或独立生产模块。

真正需要解决的不是表格标题算法，而是三项边界问题：

1. 基础导入必须停止执行 `_append_table_caption_relations()`，严格只写来源事实；
2. 现有离线增强需要从“固定 DrawingBlock 起点”适度泛化，以安全支持 Table/HAS_CAPTION/TableCaption；
3. 既有无规则版本的 Table 标题关系必须有明确兼容策略，避免迁移后出现重复或互相冲突的关系。

推荐保留 `caption_matching.py` 的几何规则和 `tests/test_caption_matching.py`，将其作为派生关系规则复用；扩展现有快照、仓储、服务和审计，而不是新建表格专用子系统或重构全部规则框架。

完成调整后，项目的架构边界应明确为：

```text
基础导入 = 来源事实层
离线增强 = 空间与上下文派生关系层
TableCaption 页面归属 = 来源事实
Table 与 TableCaption 的标题归属 = 派生关系
```

## 14. 空间与上下文派生关系层对齐分析

### 14.1 需求与注释范围

本节对应新的架构调整需求：修改当前架构中与《图块图谱方案.md》“空间与上下文派生关系层”不一致的部分。分析依据包括 `architecture.md`、`README.md`、`src/drawing_graph/block_relation_enrichment.py`、`src/drawing_graph/relation_repository.py`、`src/drawing_graph/query_service.py` 以及注释中指出的差异。

本节不写代码、不执行 Neo4j 数据迁移、不修改数据库。目标是明确当前架构是否支持、需要新增哪些模块、影响哪些已有模块、可选技术方案、优缺点、推荐方案和风险。

### 14.2 当前架构是否支持

结论：当前架构“部分支持”，但不能直接满足目标方案。

已经支持的部分：

- 来源事实层已保留 `DrawingPage -[:HAS_BASIC_INFO]-> DrawingBasicInfo`，这与目标方案一致。
- `Table -[:HAS_CAPTION]-> TableCaption` 已经从基础导入迁入离线派生关系增强，并通过 `table_caption` 固定关系规格写入，这一点已经比旧报告前半部分描述的状态更接近目标方案。
- `DrawingBlock -[:HAS_CAPTION]-> BlockCaption`、`DrawingBlock -[:HAS_ANNOTATION]-> DrawingAnnotation`、`DrawingBlock -[:HAS_SECTION_MARK]-> CrossSection` 已作为离线派生关系存在，且带有 `relation_batch_id`、`rule_version`、`link_rule` 和部分几何证据。
- `RelationRepository` 已有 `RELATION_SPECS`，不再完全只能从 `DrawingBlock` 起点写入关系，已经支持 `Table -> TableCaption` 的特殊端点组合。

不支持或不一致的部分：

- `DrawingBasicInfo` 仍被批量复制到每个 `DrawingBlock`：当前存在 `DrawingBlock -[:HAS_BASIC_INFO]-> DrawingBasicInfo`，并且本页基础信息和上一页基础信息都会按 block 扇出。目标方案要求基础信息只走页面级 `DrawingPage -[:HAS_BASIC_INFO|USES_BASIC_INFO]-> DrawingBasicInfo`。
- 当前“上一页继承”只读取同一 `DrawingSet` 的 `page_number - 1`，目标方案要求在候选图纸组内依据前后锚点、公共字段和状态判断，连续页码不能单独证明归属。
- 当前没有 `DrawingPage -[:USES_BASIC_INFO]-> DrawingBasicInfo`。
- 当前没有 `BlockCaption -[:CANDIDATE_CAPTION_OF]-> DrawingBlock` 和 `DrawingBlock -[:CANDIDATE_HAS_SECTION_MARK]-> CrossSection`。
- 当前标题和剖面标记的歧义处理只记录 warning，未把有效候选写入图谱。
- 当前 `get_block_relations()` 仍直接从 block 读取 `HAS_BASIC_INFO`，查询路径不符合目标方案的页面级基础信息路径。
- 当前 `RelationCandidate` 虽名为 candidate，但实际表示准备写入的正式派生关系，不等同于目标方案中的 `CANDIDATE_*` 候选边。

### 14.3 需要新增哪些模块

推荐新增“能力模块”，不一定都必须新增独立 Python 文件；实现时可按代码规模决定是否拆文件。

1. 页面级基础信息上下文模块

职责：替代 block 级 `HAS_BASIC_INFO` 扇出，生成或返回 `DrawingPage -[:USES_BASIC_INFO]-> DrawingBasicInfo`。它应支持本页优先、无 block 页面不补充、缺失时按候选图纸组前后锚点判断，并输出 `current_page`、`group_start`、`group_end`、`partial`、`ambiguous`、`not_evaluated` 等状态。

2. 基础信息锚点与图纸组判定模块

职责：在语义证据层未完成前，先提供保守的 `not_evaluated/partial` 输出；在 `BasicInfoInterpretation` 可用后，再比较项目、专业、图名、图号等公共字段，形成可审计的 `group_id` 和锚点证据。

3. 空间候选边生成模块

职责：为 block caption 和 cross section 生成完整候选集合。唯一且满足阈值时生成正式关系；多候选、证据接近或冲突时生成 `CANDIDATE_*`，并记录 `status`、`candidate_count`、`score`、`conflict_reason`、`rule_version` 和几何证据。候选边不是终点，后续必须进入独立 AI 复核流程，由模型同时比较完整候选集合、原始裁剪、页面上下文、空间证据和已有观察。

4. 候选关系 AI 复核模块

职责：读取 `CANDIDATE_CAPTION_OF`、`CANDIDATE_HAS_SECTION_MARK` 等候选边，一次性提交同一冲突组内的全部候选给多模态模型判断。模型只允许返回 `accepted`、`rejected` 或 `unresolved`：`accepted` 且通过硬性规则校验后才能提升为正式关系；`rejected` 标记候选失效并保留原因；`unresolved` 保持 `ambiguous`，只有业务必须唯一时才进入人工复核。候选边和正式边都应记录独立 `review_run_id`、复核模型版本、提示词版本、复核分数、复核理由和时间。

5. 候选关系写入规格

职责：扩展 `RELATION_SPECS`，加入 `CANDIDATE_CAPTION_OF`、`CANDIDATE_HAS_SECTION_MARK`、`USES_BASIC_INFO`。仍然使用固定白名单，不接受任意 Label 或关系类型。

6. 查询投影调整模块

职责：更新 `get_block_relations()` 或新增更明确的查询接口，使图块基础信息通过所属页面读取 `HAS_BASIC_INFO|USES_BASIC_INFO`，并返回来源、状态和证据，而不是只返回 block 级 `basic_info_ids`。

7. 既有数据迁移方案

职责：为历史 `DrawingBlock -[:HAS_BASIC_INFO]-> DrawingBasicInfo` 制定单独、可回滚的数据迁移脚本或运维步骤。本报告只定义需要，不执行迁移。

### 14.4 影响哪些已有模块

| 模块 | 当前职责 | 需要调整 | 影响程度 |
|---|---|---|---|
| `architecture.md` | 描述当前离线派生关系层 | 移除目标架构中的 block 级 `HAS_BASIC_INFO`，增加 `USES_BASIC_INFO` 和 `CANDIDATE_*`，明确当前实现与目标差异 | 高 |
| `README.md` | 说明运行顺序、关系类型和查询结果 | 更新基础信息继承说明、候选边说明、查询返回字段和 warning/error 状态 | 高 |
| `block_relation_enrichment.py` | 计算 table caption、block caption、basic info、annotation、cross section 关系 | 停止生成 block 级基础信息；拆分页面级基础信息上下文；block caption 和 cross section 改为“候选集合 -> 正式/候选关系 -> AI 复核/提升”流程 | 高 |
| `relation_repository.py` | 读取页面快照、读取上一页基础信息、按规格写关系 | 移除“只读上一页”作为目标路径；增加 `USES_BASIC_INFO` 和 `CANDIDATE_*` 规格；支持页面起点和 caption 起点 | 高 |
| `relation_service.py` | 编排 page/set/project 范围增强 | 需要按 drawing set 收集候选锚点；处理 `partial/ambiguous/not_evaluated`；保证单页失败隔离仍成立 | 高 |
| `query_service.py` | 返回图块追溯与派生关系 ID | 基础信息改走页面路径；候选关系可作为可选输出；`relation_status` 需要区分正式、候选、未评估和歧义 | 高 |
| `audit.py` | 记录增强批次统计与问题分类 | 增加 candidate、reviewing、accepted、rejected、unresolved、uses_basic_info、ambiguous、partial、not_evaluated 等统计和 issue 分类 | 中 |
| 图谱外复核运行日志 | 当前尚未实现 | 新增或复用目标方案中的运行日志概念，用 `review_run_id` 记录 AI 复核输入、模型、提示词、结论和错误 | 高 |
| `scripts/enrich_block_relations.py` | 离线增强 CLI | 帮助文本和摘要字段更新；命令名称可暂时保留兼容 | 中 |
| `tests/*basic_info*` | 验证当前页和上一页 block 级基础信息 | 需要改为页面级 `USES_BASIC_INFO` 和状态测试 | 高 |
| `tests/*caption*`、`tests/*cross_section*` | 验证唯一正式关系和冲突 warning | 需要新增候选边持久化、正式关系提升条件和冲突证据测试 | 高 |
| `tests/test_query_block_relations.py` | 验证 block 关系查询字段 | 需要改为页面级基础信息查询路径和候选状态输出 | 高 |

### 14.5 技术方案有哪些

#### 方案一：最小补丁式对齐

做法：在现有 `block_relation_enrichment.py` 和 `relation_repository.py` 内直接追加 `USES_BASIC_INFO`、`CANDIDATE_*` 逻辑，并以最小方式补一个 AI 复核调用入口，保持现有 CLI、服务和测试结构基本不变。

优点：

- 改动文件少，最快能让文档和代码关系模型靠近目标方案。
- 保留现有离线增强入口和批次审计，用户运行方式变化小。
- 适合先阻断新的 block 级 `HAS_BASIC_INFO` 膨胀。

缺点：

- `block_relation_enrichment.py` 会继续变大，基础信息上下文、空间候选和正式关系提升混在一起。
- 容易把“候选关系”和“待写正式关系”继续混用，`RelationCandidate` 命名会更容易误导。
- AI 复核如果也塞入现有规则文件，会把确定性空间规则和模型判断耦合在一起，后续仍可能需要二次拆分。

#### 方案二：分层增强模块对齐

做法：保留现有离线增强入口，但在规则层拆出四个明确能力：页面级基础信息上下文、空间候选生成、候选/正式关系写入规格、AI 候选复核。`relation_service.py` 仍负责编排确定性规则，AI 复核作为独立后续流程读取候选边和证据，再按结构化结论更新候选状态或提升正式关系。

优点：

- 与目标三层架构更一致：来源事实、空间/上下文派生、语义证据依赖关系清楚。
- 可以先实现保守状态：没有 `BasicInfoInterpretation` 时不强行组内继承，只返回 `not_evaluated/partial`。
- 候选边和正式边可以有不同的数据契约，减少把 warning 当审计证据的风险。
- 多模态独立复核可以只消费 `CANDIDATE_*` 和证据集合，不必反推已丢失的候选集合。
- 复核模型的输入、输出和 `review_run_id` 与确定性规则分离，符合目标方案“独立第二次判断”的要求。

缺点：

- 初次改动比方案一多，需要同步更多测试和文档。
- 需要谨慎设计状态字段，否则查询返回会短期变复杂。
- 需要新增 AI 复核运行日志或复核批次记录，否则候选提升缺少可审计来源。
- 如果拆分过细，可能在当前规模下显得模块偏多。

#### 方案三：通用派生关系规则框架

做法：建立统一规则注册器、候选评分协议、正式关系提升协议、AI 复核协议，把 table caption、block caption、basic info、annotation、cross section 都纳入同一套规则框架。

优点：

- 长期扩展性最好，适合后续 `MATCHES_SECTION_CAPTION`、多模态复核、人工兜底和更多关系类型。
- 规则输入、候选输出、审计字段可以高度统一。
- AI 复核、人工兜底和候选提升可以形成统一状态机。

缺点：

- 当前需求不需要完整框架，容易扩大范围。
- 一次性重构会影响已验证的导入、增强、查询闭环。
- 在语义证据层尚未实现前，框架中的复核接口容易变成空壳抽象。

### 14.6 推荐方案

推荐方案二：分层增强模块对齐。

推荐实施原则：

1. 先停止新增 `DrawingBlock -[:HAS_BASIC_INFO]-> DrawingBasicInfo`，保留 `DrawingPage -[:HAS_BASIC_INFO]-> DrawingBasicInfo` 来源事实。
2. 新增页面级 `DrawingPage -[:USES_BASIC_INFO]-> DrawingBasicInfo` 规格。当前页存在基础信息时，可直接通过页面路径返回；当前页缺失且语义证据层尚未具备时，返回 `not_evaluated` 或 `partial`，不要继续把“上一页必然继承”写成正式事实。
3. 将基础信息查询改为 `DrawingBlock <-[:HAS_BLOCK]- DrawingPage -[:HAS_BASIC_INFO|USES_BASIC_INFO]-> DrawingBasicInfo`。
4. 为 block caption 先生成完整候选集合：唯一、满足方向和距离规则且无冲突时写正式 `DrawingBlock -[:HAS_CAPTION]-> BlockCaption`；否则写 `BlockCaption -[:CANDIDATE_CAPTION_OF]-> DrawingBlock`。
5. 为 cross section 保留当前保守阈值，但把“多个包含候选”或“重叠证据接近”的有效候选写成 `DrawingBlock -[:CANDIDATE_HAS_SECTION_MARK]-> CrossSection`，不再只写 warning。
6. 对所有非唯一、冲突或证据接近的 `CANDIDATE_*` 启动独立 AI 复核。复核模型必须一次比较同一冲突组的全部候选，并返回 `accepted/rejected/unresolved`；只有 `accepted` 且通过同页范围、关系方向、候选集合完整性和硬性规则校验后，才能把候选提升为正式关系。
7. 候选边增加复核字段：`review_status`、`review_run_id`、`review_method`、`review_model_version`、`review_prompt_version`、`review_score`、`review_reason`、`reviewed_at`。正式边保留 `confirmation_method=multimodal_llm` 或确定性规则来源。
8. 扩展关系规格白名单，而不是开放任意 Label/关系类型。目标规格至少包括：`block_caption`、`table_caption`、`block_annotation`、`block_section_mark`、`candidate_caption_of`、`candidate_section_mark`、`page_uses_basic_info`。
9. 历史 block 级 `HAS_BASIC_INFO` 不在功能代码中静默删除，单独制定可回滚迁移。

推荐原因：方案二能把本次目标方案中的关键边界落清楚，又不会为了尚未实现的语义证据层提前重构整个规则引擎。它允许当前项目继续保持“显式离线增强 + 批次审计 + 只读查询”的闭环，同时把歧义候选、AI 独立复核和页面级上下文从旧模型中分离出来。

### 14.7 风险

高风险：

- 基础信息语义回归：停止 block 级 `HAS_BASIC_INFO` 后，旧查询如果未同步改为页面路径，会看起来像基础信息丢失。
- 历史数据并存：旧的 block 级 `HAS_BASIC_INFO` 与新的页面级 `USES_BASIC_INFO` 可能同时存在，查询若不区分版本会返回重复或矛盾结果。
- 候选边误当正式事实：`CANDIDATE_*` 必须在关系类型、状态和查询输出中明确标识，不能参与正式结论统计。
- AI 自我确认风险：复核必须是独立第二次判断，模型要看到完整候选集合和原始视觉证据，不能只读取第一次规则或识别结果后自我确认。
- 候选提升过度：模型返回 `accepted` 不能直接写正式边，仍需通过硬性规则校验；`unresolved` 必须保持 `ambiguous`，不能为了唯一答案强行提升。
- 基础信息锚点依赖语义证据：没有 `BasicInfoInterpretation` 时，不能用连续页码替代项目、专业、图名、图号等公共字段判断。

中风险：

- `relation_status` 口径变化：当前只按四组 block 级关系判断 `not_enhanced/enhanced/partial`，新增候选和页面级基础信息后需要重新定义。
- 审计统计变化：warning、candidate、ambiguous、partial、not_evaluated 的边界需要一致，否则后续排查困难。
- AI 复核缓存失效：候选集合、页面上下文图像、观察版本或规则版本变化后，旧 `review_run_id` 不能继续作为当前候选的确认依据。
- 关系规格扩展错误：`CANDIDATE_CAPTION_OF` 的起点是 `BlockCaption`，`USES_BASIC_INFO` 的起点是 `DrawingPage`，不能沿用所有关系从 block 起点写入的旧假设。
- 单页范围增强能力下降：页面级基础信息组锚点判断需要 drawing set 上下文；单页增强应明确返回上下文不足，而不是猜测。

低风险：

- Schema 不一定需要新增约束；Neo4j 可以写入新关系类型，但文档和测试必须明确白名单。
- `HAS_ANNOTATION` 当前表达同页共享上下文，与目标方案基本一致，短期可保留。
- `Table -[:HAS_CAPTION]-> TableCaption` 已经迁入离线增强，本次只需确保它仍归入空间与上下文派生关系层。

### 14.8 验收口径

后续进入实现时，建议验收标准如下：

- `architecture.md` 不再把 `DrawingBlock -[:HAS_BASIC_INFO]-> DrawingBasicInfo` 描述为目标关系。
- 新增 `DrawingPage -[:USES_BASIC_INFO]-> DrawingBasicInfo`，并说明其状态和证据字段。
- `get_block_relations()` 或替代查询接口通过所属页面返回基础信息。
- `CANDIDATE_CAPTION_OF` 和 `CANDIDATE_HAS_SECTION_MARK` 在冲突或多候选时可持久化，并带候选数量、分数、冲突原因和规则版本。
- `CANDIDATE_*` 后续进入独立 AI 复核；复核输入包含完整候选集合、原始裁剪、页面上下文、空间证据和已有观察。
- AI 复核只输出 `accepted/rejected/unresolved`；`accepted` 经硬性规则校验后提升正式关系，`rejected` 保留候选失效原因，`unresolved` 保持 `ambiguous`。
- 候选边和正式边保存 `review_run_id`、复核模型/提示词版本、复核理由和确认方式，能够追溯 AI 判断来源。
- 当前唯一且证据充分的 `HAS_CAPTION`、`HAS_SECTION_MARK` 仍可生成正式关系。
- 没有语义证据层支持时，不把上一页连续页码继承写成正式基础信息事实。
- 既有 block 级基础信息关系的清理或兼容有单独、可回滚的数据迁移方案。
