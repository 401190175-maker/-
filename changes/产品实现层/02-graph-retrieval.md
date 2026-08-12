# 02 图谱检索模块需求与设计

## 1. 模块目标

根据问题理解结果，以最少、只读、受控的调用获取回答所需的现有证据，并按统一事实类型组织为 `RetrievalBundle`。本模块必须在任何模型调用之前运行。

## 2. 当前架构现状

当前 `DrawingGraphToolFacade` 已提供图纸册、页面、页面来源事实、图块追溯、图块关系、语义 observation、interpretation、payload、候选关系和断面匹配等稳定接口。真实 Neo4j 装配通过 `create_neo4j_tool_facade()`，facade 不暴露 driver、session、transaction、Cypher 或内部节点 ID。

当前 `DrawingGraphQAService` 会针对固定问题类型组合若干 facade 调用，但尚无按照任意 `EvidenceRequirement` 构造最小查询计划的通用检索模块。

## 3. 输入与输出

输入：

```text
QuestionUnderstandingResult
RetrievalPolicy
```

输出 `RetrievalBundle`：

```text
request_id
scope
source_facts[]
derived_relations[]
semantic_observations[]
semantic_interpretations[]
candidate_relations[]
formal_relations[]
diagnostics[]
missing_evidence[]
warnings[]
source_calls[]
```

每个证据条目必须带：

```text
fact_kind
status
ids
value
evidence_refs
created_at_or_version
```

## 4. 查询规划

模块先把证据需求转换为受控查询计划：

| 证据需求 | 首选 facade 能力 |
|---|---|
| 页面来源事实 | `get_page_source_facts()` |
| 图块位置与归属 | `get_block_trace()` |
| 图块派生关系 | `get_block_relations()` |
| 已有文字观察 | `list_text_observations()` |
| 已有结构化解释 | `list_interpretations()` |
| 完整语义 payload | `get_semantic_payload()`，仅明确需要时 |
| 候选关系 | `list_candidate_relations()` |
| 断面候选/正式关系 | `list_section_matches()` |
| 图纸册与页面定位 | `list_drawing_sets()`、`list_pages()` |

检索器不得通过自行拼写 Cypher 补齐 facade 缺失能力。若缺少必要受控接口，应在 `missing_evidence` 中报告，并作为后续独立设计项扩展 facade/port。

## 5. 处理流程

1. 校验 `QuestionUnderstandingResult` 和 scope。
2. 对证据需求去重，生成按依赖排序的查询计划。
3. 优先获取定位和来源事实，验证目标存在。
4. 查询正式派生关系和候选关系。
5. 查询已有语义观察、解释和缓存相关元数据。
6. 仅在答案确实需要详细字段时读取 payload。
7. 将结果投影为统一事实分层。
8. 标记缺失、不可用、过期候选和部分失败。

## 6. 一致性与边界

- `source_fact` 只能来自来源事实读取路径。
- 规则生成的 `HAS_*`、`USES_BASIC_INFO` 等关系标记为 `derived_relation`。
- `TextObservation` 标记为 `semantic_observation`。
- 三类 `Interpretation` 标记为 `semantic_interpretation`。
- `CANDIDATE_*` 始终标记为 `candidate_relation`。
- `MATCHES_SECTION_CAPTION` 等已经受控确认的关系才可标记为 `formal_relation`。
- 空结果与查询失败必须区分；空结果是 `not_found`，基础设施失败是 degraded/error。
- 检索不得创建 `RecognitionRun`，不得触发 Qwen，不得写数据库。

## 7. 性能策略

- 同一请求内相同 facade 调用去重。
- 先查轻量摘要，再按需要展开 payload。
- 对页面级大集合设置明确上限和分页；截断必须写入 warning。
- 多个独立只读查询可并发，但输出顺序必须确定。
- 不在本模块建立跨请求业务缓存；语义缓存由既有语义缓存和模块 05 管理。

## 8. 错误与降级

| 情况 | 处理 |
|---|---|
| 目标不存在 | 返回 `not_found`，停止目标相关查询 |
| 可选语义查询不可用 | 保留来源事实，标记 partial |
| Neo4j 不可用 | 返回 `neo4j_unavailable`，不得伪造空结果 |
| facade 缺少所需能力 | 写入 `missing_evidence` 和 `unsupported` |
| payload 不可用 | 保留解释摘要，标记 payload 缺失 |
| 结果超过上限 | 返回截断结果和明确 warning |

## 9. 不负责的内容

- 不解释自然语言问题。
- 不调用 Qwen 或其他模型。
- 不判断是否值得识别。
- 不合并相互冲突的证据。
- 不生成最终回答。
- 不绕过 facade 访问 Neo4j。

## 10. 测试策略

- 使用 fake facade 验证证据需求到 facade 调用的映射。
- 验证相同需求只调用一次底层能力。
- 验证事实类型投影不混淆候选与正式关系。
- 验证可选查询失败时返回 partial，基础查询失败时返回 error。
- 验证 payload 按需加载，不默认扩大输出。
- 架构测试禁止导入 Neo4j driver、repository 或 Cypher。
- live Neo4j 集成测试单独运行；跳过不得报告为通过。

## 11. 验收标准

- 能消费问题理解模块的所有首版证据需求。
- 所有查询只通过 `DrawingGraphToolFacade` 或新增受控只读 port。
- 不产生模型调用、运行日志或持久化副作用。
- `RetrievalBundle` 中每条证据均具有明确 `fact_kind` 和稳定 ID。
- 候选关系、正式关系和语义解释不会互相冒充。
- 任一可选证据源失败时仍能保留已成功获取的证据和准确状态。

