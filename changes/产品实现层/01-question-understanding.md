# 01 问题理解模块需求与设计

## 1. 模块目标

将用户自然语言问题转换为稳定、可执行、可验证的结构化请求，使后续模块知道“用户在问什么、目标对象是什么、需要哪些证据、是否允许识别和写回”。

## 2. 当前架构现状

当前 `qa_models.py` 已定义 `QuestionType`、`QAScope` 和 `QARequest`，`DrawingGraphQAService` 支持 `page_summary`、`block_relations`、`candidate_relations`、`section_matches`、`table_caption_status`、`diagnostic_status` 及保守的 unsupported 类型。

当前调用方仍需预先选择问题类型并提供准确 ID。项目级 Skill 可以辅助自然语言路由，但这不是可独立部署、稳定测试的产品运行时能力。

## 3. 目标问题类型

首版目标集合：

| 类型 | 示例 | 主要 scope |
|---|---|---|
| `page_summary` | 这张图主要讲什么？ | `page_id` |
| `block_relations` | 这个图块关联了哪些标题和标注？ | `block_id` |
| `block_semantic_identification` | 这个图块是什么构件？ | `block_id` |
| `element_text_or_meaning` | 这个标记写的是什么、表示什么？ | `element_id` |
| `candidate_relations` | 这里有哪些尚未确认的关系？ | `page_id` 或 `block_id` |
| `section_matches` | 这个断面与哪个标题对应？ | `cross_section_id` 或 `page_id` |
| `table_caption_status` | 这个表题对应哪个表格？ | `table_id`、`table_caption_id` 或 `page_id` |
| `drawing_diagnostic` | 为什么这个对象无法识别？ | `page_id` 或 `block_id` |
| `source_trace` | 这个结论来自哪里？ | 对象 ID 或 claim ID |
| `comparison` | 比较这两个图块的差异 | 两个或多个对象 ID |
| `unknown_or_unsupported` | 无法安全映射的问题 | 任意 |

现有六类问题保持兼容；新增类型不应被描述为当前已实现。

## 4. 输入契约

输入为 `AssistantRequest`：

```text
request_id
question
conversation_context
scope_hint
language
allow_recognition
allow_write_back
answer_format
```

约束：

- `question` 必须是非空文本。
- `scope_hint` 只能包含受支持的稳定业务 ID，不接受 Neo4j 内部 ID 或 Cypher。
- `allow_write_back` 缺省为 `false`，不得从问题语气中推断为 `true`。
- 对话上下文只能用于指代消解，不得覆盖用户本轮明确提供的 ID。

## 5. 输出契约

输出为 `QuestionUnderstandingResult`：

```text
request_id
subrequests[]
question_type
scope
required_evidence[]
answer_requirements
confidence
ambiguities[]
unsupported_parts[]
```

单意图请求的 `subrequests` 为空；多意图请求中每个子请求具有稳定 `subrequest_id`、独立 `question_type`、scope 和证据需求，同时保留父 `request_id`。

`scope` 支持：

```text
project_id
drawing_set_id
page_id
block_id
element_id
cross_section_id
table_id
table_caption_id
claim_id
```

每个 `EvidenceRequirement` 包含：

```text
evidence_type
target_scope
required
minimum_status
freshness_policy
allow_model_generation
```

## 6. 处理流程

1. 规范化问题文本和语言。
2. 从本轮问题提取稳定 ID 和对象指示词。
3. 使用 `scope_hint` 与对话上下文补充指代。
4. 判断单意图或多意图；多意图拆为有序子请求。
5. 映射 `question_type`。
6. 根据问题类型生成证据需求和回答格式要求。
7. 检查 scope 是否足够、是否冲突。
8. 输出结构化结果或要求澄清。

## 7. 关键规则

- “这张图”“这个图块”等指代只有存在唯一上下文对象时才能自动解析。
- 如果问题需要 block 级语义但只给出 page，不能随意选择某个 block；应要求澄清或返回可选对象。
- 问“是什么”通常需要 `semantic_interpretation`；问“在哪里”通常只需要 `source_fact`。
- 问“对应哪个标题”需要候选和正式关系，并可能需要双方语义观察。
- 问题理解模块只声明证据需求，不判断图谱当前是否已有证据。
- 低置信度不能静默选择问题类型；应在 `ambiguities` 中说明。

## 8. 模型使用策略

问题理解可以采用规则、轻量语言模型或二者组合，但不得在本模块读取图纸图像。建议首版采用：

1. 稳定 ID 和明确命令式问题优先走确定性规则。
2. 规则无法唯一分类时调用文本模型输出受约束 JSON。
3. 输出必须经过枚举、scope 和证据需求校验。
4. 模型失败时回退到 `unknown_or_unsupported` 或 `clarification_required`。

## 9. 不负责的内容

- 不访问 Neo4j 或 `DrawingGraphToolFacade`。
- 不读取图片，不调用 Qwen 视觉识别。
- 不判断证据是否缺失或过期。
- 不生成用户最终答案。
- 不执行任何写回或候选提升。

## 10. 错误与降级

| 情况 | 输出 |
|---|---|
| 问题为空 | `invalid_argument` |
| 缺少必要 scope | `clarification_required` |
| 多个 scope 冲突 | `clarification_required` 并列出冲突 |
| 问题类型不支持 | `unknown_or_unsupported` |
| 文本模型失败 | 使用规则结果；无规则结果则保守 unsupported |
| 对话指代不唯一 | 不猜测，返回可澄清对象类型 |

## 11. 测试策略

- 单元测试：每类问题的映射、证据需求、默认权限和 scope 校验。
- 参数化测试：常见中文同义表达、口语、省略主语和标点差异。
- 多意图测试：拆分顺序和子请求证据边界。
- 安全测试：问题文本不得注入 `write_back=true`、Cypher 或内部调用。
- 回归测试：现有六类 `QuestionType` 映射保持兼容。
- 模型合同测试：只接受受约束 JSON，不接受自由文本作为权威结果。

## 12. 验收标准

- 支持表中全部首版问题类型。
- 明确 ID 的典型问题可稳定生成正确 scope。
- 缺少关键 ID 时不调用后续检索或识别，而是要求澄清。
- `allow_write_back` 始终继承请求显式值，默认保持 `false`。
- 每种问题类型均生成可由图谱检索模块消费的证据需求。
- 单意图、多意图、unsupported 和歧义场景均有自动测试。
