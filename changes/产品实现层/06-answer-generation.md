# 06 答案生成模块需求与设计

## 1. 模块目标

把已经融合且分层的证据转换为用户能理解、机器能消费、每条结论都能追溯的答案。机器可读 JSON 是权威输出，中文回答由同一结构化答案渲染或受约束生成。

## 2. 当前架构现状

当前项目已有 `QAAnswer`、`AnswerFact`、`EvidenceRef`、共享序列化和 `zh-brief` 渲染，能够对固定问题类型生成保守答案。当前回答主要是确定性模板和查询摘要，尚无针对自然语言问题、语义融合结果和 claim 级证据的完整生成能力。

## 3. 输入与输出

输入：

```text
AssistantRequest
QuestionUnderstandingResult
EvidenceBundle
```

输出 `AnswerPackage`：

```text
request_id
question_type
scope
status
machine_answer
text_answer
claims[]
citations[]
warnings[]
unsupported_parts[]
recognition_run_ids[]
follow_up_actions[]
```

`status` 固定为：

```text
answered
partial
clarification_required
unsupported
recognition_failed
```

## 4. Claim 契约

每个 `Claim` 包含：

```text
claim_id
statement
claim_type
status
confidence
evidence_ids[]
fact_kinds[]
scope
qualifiers[]
```

约束：

- 每条非 diagnostic claim 至少引用一个 `EvidenceItem`。
- `candidate_relation` 支撑的 statement 必须包含“候选、可能、待确认”等限定语。
- `semantic_interpretation` 支撑的 statement 不得写成来源标注原文。
- `formal_relation` 和 `source_fact` 才能使用无候选限定的确定性关系表达。
- 冲突或低置信度必须体现在 `status`、`confidence` 或 `qualifiers` 中。

## 5. 机器可读答案

`machine_answer` 应包含问题、scope、结论、证据、状态和后续动作，不复制不可控的大 payload。客户端需要完整 payload 时，应通过受控 `payload_ref` 查询。

机器答案必须：

- 使用稳定枚举和字段名。
- 保留 page/block/element/claim ID。
- bbox 使用统一 `{x_min, y_min, x_max, y_max}`。
- 区分 observation、interpretation、candidate 和 formal。
- 标记结果是否来自缓存或本次识别。
- 不暴露 Neo4j 内部 ID、Cypher、secret 或底层 traceback。

## 6. 中文回答结构

默认简短回答采用：

```text
直接结论

依据：
1. 来源事实或定位证据
2. 语义观察/解释
3. 候选或正式关系状态

注意：不确定性、缺失证据或验证边界
```

示例表达规则：

- `source_fact`： “该图块位于页面……的 bbox……”
- `semantic_observation`： “Qwen 在该区域观察到文字……”
- `semantic_interpretation`： “模型解释为……，置信度……”
- `candidate_relation`： “存在与标题……的候选关系，尚未正式确认。”
- `formal_relation`： “图谱中已有正式匹配关系……”

## 7. 生成策略

建议采用两阶段方式：

1. 确定性代码从 `EvidenceBundle` 构造 `claims`、citations 和状态。
2. 文本生成器只根据已经批准的 claim 生成自然中文，不得新增 claim。

如果文本模型不可用，系统仍可用模板渲染完整、准确的答案。生成式文本不是权威事实源。

## 8. 状态映射

| 条件 | AnswerPackage 状态 |
|---|---|
| 所有必需 claim 有足够证据 | `answered` |
| 部分 claim 可回答或存在 warning | `partial` |
| scope 或指代必须由用户补充 | `clarification_required` |
| 问题或证据类型不受支持 | `unsupported` |
| 必需识别失败且无法形成目标语义 claim | `recognition_failed` |

Qwen 失败但仍有来源事实可回答部分内容时，整体应为 `partial`，并在 warning 中记录识别失败，而不是丢弃已有事实。

## 9. 引用与追溯

`Citation` 至少可包含：

```text
project_id
drawing_set_id
page_id
block_id
element_id
image_path
bbox
observation_id
interpretation_id
candidate_group_id
recognition_run_id
review_run_id
payload_ref
rule_version
```

输出只包含当前 claim 所需的最小引用字段。路径等信息受 adapter 的数据最小化策略控制。

## 10. 不负责的内容

- 不查询图谱。
- 不调用 Qwen 图像识别。
- 不判断缓存是否有效。
- 不写回语义证据或关系。
- 不接受文本模型新生成的未引用事实。

## 11. 测试策略

- 每种 fact kind 的 claim 表达和限定语测试。
- claim 无 evidence 时拒绝生成的合同测试。
- candidate 不得渲染为 formal 的安全测试。
- Qwen 失败但来源事实存在时的 partial 测试。
- JSON 与中文回答事实一致性测试。
- unsupported、clarification、ambiguous 和 conflict 测试。
- 敏感字段、内部 ID、Cypher 和 traceback 不泄露测试。
- 文本模型不可用时模板回退测试。

## 12. 验收标准

- 同时输出稳定 JSON 和简短中文回答。
- 每条非诊断结论都有可解析证据引用。
- 中文回答不包含机器答案中不存在的新结论。
- candidate、interpretation 和 formal 使用不同确定性措辞。
- partial、unsupported、recognition_failed 的原因明确可见。
- 文本生成器失败时仍能返回结构化答案和模板文本。

