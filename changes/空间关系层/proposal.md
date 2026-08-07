# 空间与上下文派生关系层对齐提案

## 1. 背景

本项目将 XAnyLabeling 标注 JSON 和同目录同名 PNG 导入 Neo4j，形成以 `Project -> DrawingSet -> DrawingPage -> DrawingBlock` 为核心的可追溯图块图谱。当前系统已经具备基础导入、离线派生关系增强、批次审计和只读查询闭环。

《图块图谱方案.md》将目标图谱分为三层：来源事实层、空间与上下文派生关系层、语义证据层。来源事实层保存原始标注和文件结构能够直接确定的事实；空间与上下文派生关系层保存通过 bbox、页面范围、页码顺序或上下文规则得到的关系；语义证据层保存多模态模型观察、结构化解释和候选关系复核证据。

根据 `Feature_Analysis_Report.md` 的最新分析，当前来源事实层整体已经具备稳定底座，`Table -[:HAS_CAPTION]-> TableCaption` 也已迁入离线派生关系增强。但当前“空间与上下文派生关系层”仍存在与目标方案不一致的部分，尤其集中在 `DrawingBasicInfo` 页面级上下文、空间候选边、候选关系 AI 复核和查询路径上。

本提案用于定义新的功能调整需求：优先把当前架构中空间与上下文派生关系层不一致的部分调整到与《图块图谱方案.md》保持一致。本提案只描述需求、范围和影响模块，不实施代码，不修改 Neo4j 数据。

本提案属于规划边界文档，用于约束后续实现方向和非目标范围；文档中的目标关系与流程说明不声称代码已实现。

## 2. 当前问题

当前实现存在以下问题：

1. `DrawingBasicInfo` 仍通过 `DrawingBlock -[:HAS_BASIC_INFO]-> DrawingBasicInfo` 批量关联到页面内每个图块。当前页有基础信息时，每个图块都会连接本页基础信息；当前页缺失时，部分流程会继承同一 `DrawingSet` 内直接上一页的基础信息。目标方案要求基础信息只通过页面级来源或上下文关系表达。
2. 当前“上一页基础信息继承”只依据 `page_number - 1` 和同一 `DrawingSet`，缺少图纸组前后锚点、公共字段和状态判断。连续页码不能单独证明图纸组归属。
3. 当前没有 `DrawingPage -[:USES_BASIC_INFO]-> DrawingBasicInfo`，无法表达某个存在图块的页面使用本页或图纸组锚点基础信息。
4. 当前 `get_block_relations()` 仍直接从 `DrawingBlock` 读取 `HAS_BASIC_INFO`，不符合目标方案中的页面级查询路径：`DrawingBlock <-[:HAS_BLOCK]- DrawingPage -[:HAS_BASIC_INFO|USES_BASIC_INFO]-> DrawingBasicInfo`。
5. 当前没有 `BlockCaption -[:CANDIDATE_CAPTION_OF]-> DrawingBlock` 和 `DrawingBlock -[:CANDIDATE_HAS_SECTION_MARK]-> CrossSection`。标题或剖面标记存在多个合理候选时，系统只记录 warning，候选本身没有进入图谱。
6. 当前 `BlockCaption` 冲突处理过于确定：每个标题先选最近图块，多个标题指向同一图块时保留最近标题，被放弃的标题只形成 warning。这会把部分不确定空间判断压成单一正式关系。
7. 当前 `CrossSection` 规则虽然在冲突时比较保守，但多个包含候选、重叠证据接近等有效候选没有持久化，后续无法交给 AI 复核。
8. 当前 `RelationCandidate` 名称容易误导。它实际表示准备写入的正式派生关系，不等同于目标方案中带状态和证据的 `CANDIDATE_*` 候选边。
9. 当前尚未具备候选关系的独立 AI 复核流程。目标方案要求复杂、冲突或多候选情况先保留候选边，再由多模态模型基于完整候选集合、原始裁剪、页面上下文、空间证据和已有观察进行独立判断。

## 3. 功能目标

本次调整完成后，应达到以下目标：

1. 停止新增 `DrawingBlock -[:HAS_BASIC_INFO]-> DrawingBasicInfo` 批量关系。
2. 保留 `DrawingPage -[:HAS_BASIC_INFO]-> DrawingBasicInfo` 作为来源事实关系。
3. 新增页面级 `DrawingPage -[:USES_BASIC_INFO]-> DrawingBasicInfo` 上下文关系，用于表达存在图块的页面使用哪一份基础信息。
4. 当前页存在基础信息时，图块查询应通过所属页面取得本页基础信息。
5. 当前页缺失基础信息且语义证据层尚未具备可靠字段解析时，不继续把“上一页必然继承”写成正式事实，应返回 `not_evaluated` 或 `partial`。
6. 在 `BasicInfoInterpretation` 可用后，基础信息上下文判断应依据候选图纸组前后锚点，以及项目、专业、图名、图号等公共字段。锚点冲突或组边界不唯一时返回 `ambiguous`。
7. 为 `BlockCaption` 与 `DrawingBlock` 建立完整空间候选集合。唯一、满足规则且无冲突时写正式 `DrawingBlock -[:HAS_CAPTION]-> BlockCaption`；否则写 `BlockCaption -[:CANDIDATE_CAPTION_OF]-> DrawingBlock`。
8. 为 `CrossSection` 与 `DrawingBlock` 建立完整包含或重叠候选集合。唯一、满足规则且证据显著领先时写正式 `DrawingBlock -[:HAS_SECTION_MARK]-> CrossSection`；多个合理候选或证据接近时写 `DrawingBlock -[:CANDIDATE_HAS_SECTION_MARK]-> CrossSection`。
9. `CANDIDATE_*` 候选边记录 `status`、`candidate_count`、`score`、`conflict_reason`、`rule_version`、几何证据、创建时间和更新时间。
10. 候选边不是终点。复杂、冲突或多候选关系必须进入独立 AI 复核流程。复核模型应一次性比较同一冲突组内的全部候选，并只能返回 `accepted`、`rejected` 或 `unresolved`。
11. AI 返回 `accepted` 后，仍需通过同页范围、关系方向、候选集合完整性和硬性规则校验，才能提升为正式关系；`rejected` 保留候选失效原因；`unresolved` 保持 `ambiguous`，只有业务必须唯一时才进入人工复核。
12. 候选边和由 AI 提升的正式边应保存 `review_run_id`、复核模型版本、提示词版本、复核分数、复核理由和复核时间。
13. 关系写入继续使用固定白名单，支持 `DrawingPage`、`DrawingBlock`、`BlockCaption`、`Table` 等不同起点，但不允许调用方自由传入 Label 或关系类型。
14. 更新图块关系查询，使基础信息通过页面路径返回，并能区分正式关系、候选关系、未评估、部分结果和歧义状态。

## 4. 修改范围

### 4.1 架构与使用文档

- 更新 `architecture.md`，将目标空间与上下文派生关系层调整为：
  - `DrawingBlock -[:HAS_CAPTION]-> BlockCaption`
  - `DrawingBlock -[:HAS_ANNOTATION]-> DrawingAnnotation`
  - `DrawingBlock -[:HAS_SECTION_MARK]-> CrossSection`
  - `Table -[:HAS_CAPTION]-> TableCaption`
  - `DrawingPage -[:USES_BASIC_INFO]-> DrawingBasicInfo`
  - `BlockCaption -[:CANDIDATE_CAPTION_OF]-> DrawingBlock`
  - `DrawingBlock -[:CANDIDATE_HAS_SECTION_MARK]-> CrossSection`
- 明确 `DrawingBlock -[:HAS_BASIC_INFO]-> DrawingBasicInfo` 是旧实现证据，不再作为目标关系。
- 更新 `README.md` 中的离线派生关系说明、基础信息上下文说明、候选边说明、AI 复核状态和查询返回状态。
- 保留当前基础导入与显式离线增强的运行边界，不让基础导入自动触发派生增强或 AI 复核。

### 4.2 页面级基础信息上下文

- 移除或停用 block 级基础信息生成路径。
- 新增页面级 `USES_BASIC_INFO` 生成逻辑。
- 本页存在基础信息时，优先使用 `DrawingPage -[:HAS_BASIC_INFO]-> DrawingBasicInfo`。
- 本页缺失基础信息时，先判断该页是否存在 `DrawingBlock`；没有图块的页面不要求补充或继承基础信息。
- 语义证据层尚未实现前，对缺失基础信息页面采用保守状态，不以直接上一页作为正式继承事实。
- 后续具备 `BasicInfoInterpretation` 后，支持候选图纸组前后锚点和公共字段比较，并记录 `source`、`source_page_id`、`group_id`、`rule_version`、`status` 和证据引用。

### 4.3 空间候选边

- 调整 block caption 规则，从“先选一个最近图块”改为“先生成完整候选集合”。
- 当候选唯一且确定性条件充分时，生成正式 `HAS_CAPTION`。
- 当候选不唯一、距离证据接近或存在冲突时，生成 `CANDIDATE_CAPTION_OF`。
- 调整 cross section 规则，保留当前包含和重叠阈值，但在多个包含候选或重叠候选证据接近时生成 `CANDIDATE_HAS_SECTION_MARK`。
- 完全无重叠或低于最低阈值的对象不生成候选边，只记录低证据或未找到状态。

### 4.4 候选关系 AI 复核

- 新增独立 AI 复核流程，读取 `CANDIDATE_*` 候选边及其证据。
- 复核输入必须包含完整候选集合、原始裁剪、页面上下文、空间证据、已有观察和规则版本。
- 复核输出限定为 `accepted`、`rejected`、`unresolved`。
- `accepted` 只表示模型选择了唯一候选；写入正式边前必须再次执行硬性规则校验。
- `rejected` 更新候选边状态并保存原因。
- `unresolved` 保持候选组为 `ambiguous`，不写正式关系；只有业务必须唯一时才进入人工复核。
- 复核过程使用独立 `review_run_id`，不能只读取第一次规则或识别结果进行自我确认。

### 4.5 关系写入与审计

- 扩展关系规格白名单，至少覆盖：
  - `block_caption`
  - `table_caption`
  - `block_annotation`
  - `block_section_mark`
  - `candidate_caption_of`
  - `candidate_section_mark`
  - `page_uses_basic_info`
- 每个规格明确起点 Label、关系类型、终点 Label 和必需属性。
- 保持稳定业务 ID、参数化 Cypher 和幂等写入。
- 扩展增强审计统计，增加 candidate、reviewing、accepted、rejected、unresolved、uses_basic_info、ambiguous、partial、not_evaluated 等计数和问题分类。

### 4.6 查询与既有数据兼容

- 更新 `get_block_relations()` 或新增替代查询接口，通过所属 `DrawingPage` 读取基础信息。
- 查询结果应区分正式关系、候选关系、未评估、部分结果和歧义状态。
- 对历史 `DrawingBlock -[:HAS_BASIC_INFO]-> DrawingBasicInfo` 不在功能逻辑中静默删除。
- 单独制定可回滚的数据迁移方案，用于清理或兼容旧的 block 级基础信息关系。

### 4.7 测试与验收

- 更新基础信息相关测试，从 block 级 `HAS_BASIC_INFO` 调整为页面级 `USES_BASIC_INFO` 与状态判断。
- 增加 block caption 候选集合测试，覆盖唯一正式关系、多候选候选边和冲突状态。
- 增加 cross section 候选边测试，覆盖多个包含候选、重叠证据接近、低证据不建候选等场景。
- 增加 AI 复核状态测试，覆盖 `accepted`、`rejected`、`unresolved` 和硬性规则校验。
- 更新查询测试，验证基础信息页面路径和候选状态输出。
- 更新文档测试，确保 `architecture.md`、`README.md` 和本提案的边界一致。

## 5. 不包含范围

本次修改不包含：

- 不重建基础图谱，不改变 `Project -> DrawingSet -> DrawingPage -> DrawingBlock` 追溯链路。
- 不删除 `DrawingPage -[:HAS_BASIC_INFO]-> DrawingBasicInfo` 来源事实关系。
- 不把 AI 推断字段写入或覆盖 `DrawingBlock`、`DrawingBasicInfo`、`BlockCaption`、`CrossSection` 等来源事实节点。
- 不把连续页码单独作为图纸组归属证明。
- 不在基础导入阶段自动运行离线派生关系增强或 AI 复核。
- 不在本次功能中实现完整语义证据层的所有节点和解析能力，例如完整 `TextObservation`、`BlockInterpretation`、`TableInterpretation` 或 `MATCHES_SECTION_CAPTION`。
- 不实现 HTTP/REST API、Agent Skill、`NEAR` 空间关系网络或 `DrawingBlock.block_type` 推断。
- 不把 `CANDIDATE_*` 关系当作正式事实参与确定性结论统计。
- 不让 AI 复核直接覆盖已有正式关系；与已有正式关系冲突时，应保留冲突候选和审计信息，必要时再人工兜底。
- 不在本提案中执行 Neo4j 数据迁移；历史 block 级基础信息关系的清理另行制定可回滚方案。

## 6. 影响模块

### 6.1 直接影响模块

| 文件或模块 | 影响内容 |
|---|---|
| `architecture.md` | 更新空间与上下文派生关系层目标模型；移除目标架构中的 block 级基础信息关系；增加 `USES_BASIC_INFO` 和 `CANDIDATE_*`。 |
| `README.md` | 更新运行说明、关系说明、候选边说明、AI 复核状态和查询返回状态。 |
| `src/drawing_graph/block_relation_enrichment.py` | 停止生成 block 级基础信息；拆分页面级基础信息上下文；block caption 和 cross section 改为候选集合、正式关系、候选关系与 AI 复核/提升流程。 |
| `src/drawing_graph/relation_repository.py` | 扩展固定关系规格；支持页面起点、caption 起点和候选边；替换直接上一页基础信息读取的目标路径。 |
| `src/drawing_graph/relation_service.py` | 调整 page、drawing-set、project 范围编排；处理页面级基础信息状态、候选边状态和单页上下文不足。 |
| `src/drawing_graph/query_service.py` | 将基础信息查询改为页面路径；返回正式关系、候选关系、未评估、部分结果和歧义状态。 |
| `src/drawing_graph/audit.py` | 增加候选、AI 复核、页面级基础信息和歧义状态相关统计及问题分类。 |
| `scripts/enrich_block_relations.py` | 更新离线增强摘要和帮助说明；保留命令兼容性。 |
| 图谱外复核运行日志 | 新增或复用目标方案中的运行日志能力，用 `review_run_id` 追溯 AI 复核输入、模型、提示词、结论和错误。 |

### 6.2 直接影响测试

| 测试文件 | 影响内容 |
|---|---|
| `tests/test_basic_info_current_page_enrichment.py` | 从 block 级基础信息关系改为页面级当前页基础信息上下文。 |
| `tests/test_basic_info_previous_page_enrichment.py` | 停止验证直接上一页继承为正式事实，改为验证保守状态、锚点判断和歧义状态。 |
| `tests/test_enrich_page_relations.py` | 更新页面汇总关系和统计，覆盖 `USES_BASIC_INFO` 与 `CANDIDATE_*`。 |
| `tests/test_block_caption_enrichment.py` | 增加完整候选集合、正式关系条件和 `CANDIDATE_CAPTION_OF`。 |
| `tests/test_cross_section_enrichment.py` | 增加多个包含候选、重叠证据接近和 `CANDIDATE_HAS_SECTION_MARK`。 |
| `tests/test_relation_repository_reads.py` | 更新基础信息上下文读取能力，支持候选锚点需要的页面范围。 |
| `tests/test_relation_repository_writes.py` | 验证 `USES_BASIC_INFO`、`CANDIDATE_CAPTION_OF`、`CANDIDATE_HAS_SECTION_MARK` 的固定端点、参数化和幂等写入。 |
| `tests/test_relation_service_page.py` | 验证单页上下文不足时返回 `not_evaluated` 或 `partial`，不强行继承。 |
| `tests/test_relation_service_set.py` | 验证 drawing set 范围内页面级基础信息和候选关系汇总。 |
| `tests/test_relation_service_project.py` | 验证项目范围内多 drawing set 隔离、候选状态和失败隔离。 |
| `tests/test_query_block_relations.py` | 验证图块基础信息经页面路径返回，并区分候选、歧义和未评估状态。 |
| `tests/test_relation_audit.py` | 验证 candidate、reviewing、accepted、rejected、unresolved、uses_basic_info 等统计。 |
| `tests/test_readme.py`、`tests/test_relation_readme.py` | 验证文档边界与新提案一致。 |
| `tests/integration/test_neo4j_relation_enrichment.py` | 验证真实 Neo4j 中页面级基础信息、候选边、AI 复核状态字段和幂等写入。 |

### 6.3 原则上不受影响模块

- `src/drawing_graph/scanner.py`
- `src/drawing_graph/validation.py`
- `src/drawing_graph/image_paths.py`
- `src/drawing_graph/page_number.py`
- `src/drawing_graph/geometry.py`
- `src/drawing_graph/identifiers.py`
- `src/drawing_graph/mapping.py` 中来源事实映射
- `src/drawing_graph/neo4j_repository.py` 的基础导入节点与页面来源关系写入
- `scripts/create_schema.cypher`
- `scripts/import_json.py` 的基础导入入口行为
