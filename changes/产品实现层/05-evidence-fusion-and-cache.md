# 05 证据融合与缓存模块需求与设计

## 1. 模块目标

把图谱已有证据、本次 Qwen 临时识别结果、缓存状态和诊断信息组合成一个可回答、可追溯、保留冲突的 `EvidenceBundle`。融合是组织证据，不是抹平来源或提升事实等级。

## 2. 当前架构现状

当前已有 `SemanticCacheService`、`SemanticPayloadStore`、语义 repository、`SemanticQueryProjection` 和 stale 机制，可以保存和查询单类语义证据。当前尚无以一次用户问题为范围的跨来源融合器，也没有 claim 支撑、冲突优先级和回答充分性统一规则。

## 3. 输入与输出

输入：

```text
RetrievalBundle
SemanticGapDecision
RecognitionResult[]
WriteBackPolicy
```

输出 `EvidenceBundle`：

```text
request_id
accepted_evidence[]
conflicting_evidence[]
unsupported_claims[]
cache_status
provenance[]
overall_confidence
answerability
warnings[]
write_back_result
```

`answerability` 固定为：

```text
answerable
partially_answerable
clarification_required
unsupported
```

## 4. 证据规范化

所有输入先映射为统一 `EvidenceItem`：

```text
evidence_id
fact_kind
status
scope
claim_capabilities[]
value
confidence
source_system
recognition_run_id
payload_ref
model_profile
prompt_version
rule_version
created_at
evidence_refs[]
```

规范化不得改变 `fact_kind`。例如，Qwen 输出“疑似钢筋混凝土构件”仍是 `semantic_interpretation`，即使置信度很高也不能变成 `source_fact`。

## 5. 融合顺序

1. 校验每条证据的 ID、scope 和来源。
2. 移除完全重复的证据引用，不删除审计字段。
3. 将同一目标、同一字段的证据分组。
4. 判断一致、互补或冲突。
5. 根据当前问题需要选择可用于回答的证据。
6. 保留冲突证据和冲突原因，不静默覆盖。
7. 计算 claim 级和整体可回答程度。
8. 按明确权限执行可选语义证据写回。

## 6. 证据优先级

优先级只用于判断某类 claim 能否成立，不代表高优先级证据可以改写低优先级原始记录。

建议规则：

1. 来源事实用于回答对象身份、位置、bbox 和归属。
2. 正式关系用于回答已经确认的关系。
3. 规则派生关系用于回答有明确规则依据的上下文关系。
4. 语义观察用于回答模型实际读到或看到的内容。
5. 语义解释用于回答“可能是什么、表示什么”。
6. 候选关系只用于表达可能性、歧义和待复核状态。
7. diagnostic 只用于解释运行状态，不支持工程事实结论。

不同类型证据通常是互补关系，而不是简单排序替代。

## 7. 冲突处理

冲突至少包括：

- 两次有效 observation 对同一区域读取出不同文本。
- interpretation 与明确来源标签不一致。
- 多个候选关系得分接近，无法唯一选择。
- 旧缓存与当前图片 hash 不一致。
- 正式关系与新的模型解释不一致。

处理规则：

- 正式关系不会被模型结果自动撤销。
- 与来源事实冲突的模型结果进入 `conflicting_evidence`。
- 同等级语义证据冲突时降低 claim 置信度并标记 ambiguous。
- 图片或版本已变化的旧证据标记 stale，不参与当前 claim。
- 冲突无法解决时，答案必须明确说明，不选择看似合理的一方。

## 8. 缓存策略

`cache_status` 至少包含：

```text
full_hit
partial_hit
miss
stale
bypassed
```

- 缓存由图片 hash、bbox、task type、模型、prompt 和合同版本共同约束。
- 同一次请求中临时结果可以参与融合，但 `write_back=false` 时不得跨请求持久化。
- 缓存命中不创建新的 `RecognitionRun`。
- 新结果写回后，旧 interpretation 按既有机制标记 stale，不静默覆盖审计历史。
- payload 为不可变内容；修订结果产生新的 payload_ref。

## 9. 写回策略

`WriteBackPolicy` 必须同时检查：

```text
request_allow_write_back
module_allow_write_back
result_schema_valid
target_scope_valid
repository_available
```

只有全部满足时才允许通过 semantic service 的受控路径写入 observation/interpretation。以下内容即使允许写回也不能在本模块直接完成：

- 覆盖来源事实。
- 把 `interpreted_type` 写入 `DrawingBlock.block_type`。
- 把 candidate 直接提升为 formal。
- 绕过 `CandidateReviewService` 写正式关系。

## 10. 不负责的内容

- 不调用 Qwen。
- 不执行新的 Neo4j 查询。
- 不理解用户自然语言。
- 不撰写最终中文答案。
- 不进行候选关系正式提升。

## 11. 测试策略

- 各 `fact_kind` 规范化和不变性测试。
- 重复证据去重但审计字段保留测试。
- observation 一致、互补、冲突矩阵测试。
- candidate/formal 不可混淆测试。
- stale、图片 hash 和版本变更测试。
- full/partial/miss 缓存状态测试。
- `write_back=false` 无持久化副作用测试。
- 写回失败时保留临时结果并返回 partial 的测试。

## 12. 验收标准

- 输入证据全部保留可追溯来源和原始事实等级。
- 冲突证据不会被静默丢弃或强行统一。
- 能输出 claim 级可用证据和整体 answerability。
- 缓存命中、部分命中、失效和绕过状态可观测。
- `write_back=false` 下无 run log、Neo4j 或持久化缓存写入。
- candidate 从不因融合而变成 formal。

