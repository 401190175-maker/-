# 03 语义缺口判断模块需求与设计

## 1. 模块目标

比较“回答问题需要什么证据”与“图谱当前有什么证据”，决定直接回答、复用缓存、调用 Qwen、要求用户澄清或返回不支持。这是自动化闭环的决策核心。

## 2. 当前架构现状

当前项目已经有语义 observation、interpretation、状态、图片 hash、cache key、模型 profile 和 prompt version，也支持默认 dry-run 的按需识别。当前是否调用识别主要由外部调用者明确触发，尚无统一的证据充分性与成本决策模块。

## 3. 输入与输出

输入：

```text
QuestionUnderstandingResult
RetrievalBundle
RecognitionPolicy
```

输出 `SemanticGapDecision`：

```text
decision
missing_requirements[]
recognition_targets[]
cache_candidates[]
reason_codes[]
estimated_cost
write_back_recommendation
warnings[]
```

`decision` 固定为：

```text
reuse_existing
recognize_required
clarification_required
unsupported
```

## 4. 证据充分性规则

每项 `EvidenceRequirement` 按以下顺序判断：

1. 是否存在满足目标 scope 的证据。
2. `fact_kind` 是否满足需求，不能用低等级证据冒充高等级证据。
3. 状态是否达到 `minimum_status`。
4. 图片 hash、模型 profile、prompt version 和契约版本是否满足 freshness policy。
5. 是否存在冲突、歧义或多个同等候选。
6. 是否允许通过模型生成缺失证据。

典型规则：

| 问题 | 必需证据 | 决策示例 |
|---|---|---|
| 图块在哪里 | `source_fact` | 有 trace 即直接回答 |
| 图块是什么构件 | `semantic_interpretation` | 无有效解释则识别 block |
| 标记写了什么 | `semantic_observation` | 无有效观察则识别 element |
| 断面对应哪个标题 | 双方 observation + 候选/正式匹配 | 缺一方 observation 时识别缺失目标 |
| 是否为正式关系 | `formal_relation` | 只有 candidate 时不能靠识别直接确认 |

## 5. 识别目标规划

每个 `RecognitionTarget` 包含：

```text
page_id
target_element_id
target_type
task_type
required_output
context_element_ids
priority
reason
```

规划原则：

- 目标尽可能精确到单个元素或 bbox。
- 页面级摘要可以使用整页输入，但不得默认识别所有元素。
- 同一目标的多个证据需求应合并为一次兼容任务。
- 不同 prompt/output contract 的任务不得错误共享缓存。
- 如果缺少 image path、bbox 或合法目标 ID，应返回 clarification/unsupported，而不是调用模型猜测。

## 6. 缓存与时效

`reuse_existing` 需要同时满足：

- cache key 对应当前图片 hash、bbox、任务类型、模型 profile、prompt version 和输出契约版本。
- observation/interpretation 状态可用于当前问题。
- 证据未被标记为 `stale`、`rejected` 或冲突。
- 当前问题不要求比缓存更严格的证据等级。

缓存命中不创建新的 `RecognitionRun`。若缓存仅部分满足需求，应只为剩余缺口创建识别目标。

## 7. 成本与策略

`RecognitionPolicy` 至少包含：

```text
allow_recognition
max_targets
max_estimated_cost
max_latency_seconds
preferred_model_profile
prompt_version_policy
```

决策规则：

- `allow_recognition=false` 时不得创建识别请求，只能返回 partial/clarification/unsupported。
- 超过目标数、预算或时延上限时，应选择最小必要目标或要求用户缩小范围。
- 成本估算用于决策和提示，不作为实际账单。
- `write_back_recommendation` 只能是建议，最终权限仍来自 `AssistantRequest.allow_write_back`。

## 8. 原因码

至少支持：

```text
evidence_complete
observation_missing
interpretation_missing
evidence_stale
image_changed
prompt_version_changed
contract_version_changed
evidence_conflict
scope_missing
recognition_forbidden
budget_exceeded
formal_review_required
unsupported_evidence_type
```

原因码供答案生成、诊断和监控复用，不依赖自由文本解析。

## 9. 不负责的内容

- 不执行 facade 查询。
- 不直接调用 Qwen。
- 不写入缓存、run log 或 Neo4j。
- 不把 candidate 提升为 formal。
- 不生成最终中文答案。

## 10. 错误与降级

| 情况 | 决策 |
|---|---|
| 来源事实不足，无法定位图片 | `clarification_required` 或 `unsupported` |
| 有效缓存完整命中 | `reuse_existing` |
| 仅缺模型可生成证据且允许识别 | `recognize_required` |
| 只缺正式审核结论 | `reuse_existing`，并标记 `formal_review_required` |
| 禁止识别且证据不足 | 不调用模型，保守 partial/unsupported |
| 超出预算或目标上限 | 要求缩小 scope 或返回 partial |

## 11. 测试策略

- 证据完整、部分缺失、全部缺失、过期和冲突矩阵测试。
- observation 与 interpretation 不可互相替代的类型测试。
- candidate 不可满足 formal requirement 的安全测试。
- cache key、图片 hash、模型和 prompt 版本变更测试。
- `allow_recognition=false` 与预算超限测试。
- 多目标去重、合并和优先级测试。
- 属性测试：任何输入均不得自行把 `allow_write_back` 改为 true。

## 12. 验收标准

- 对每项证据需求给出可解释的满足或缺失判断。
- 有有效缓存时不产生新识别目标。
- 只缺部分证据时仅识别缺失目标。
- candidate 永远不能满足 formal relation 需求。
- 禁止识别、预算不足或 scope 不完整时不会调用模型。
- 所有决策包含稳定原因码，可供诊断和答案生成使用。

