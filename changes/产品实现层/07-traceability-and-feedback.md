# 07 追溯与反馈模块需求与设计

## 1. 模块目标

记录一次问答从用户问题、模块决策、模型运行、证据到最终 claim 的完整追溯链，并接收用户确认、否认、纠正和复核请求，使系统能够受控地改进，而不是通过无审计的自动覆盖“越用越乱”。

## 2. 当前架构现状

当前已有：

- 语义识别的 `recognition_run_id`。
- 候选审核的 `review_run_id`。
- 图谱外 `RecognitionRun` 与图谱内语义证据的关联。
- `CandidateReviewService` 的 accepted/rejected/unresolved 三态和硬规则提升。
- page/block/element、bbox、payload_ref、模型和 prompt 等证据字段。

当前尚无产品级问答运行记录、claim 级追溯、用户反馈 API 和反馈状态机。

## 3. 追溯数据契约

`TraceRecord`：

```text
request_id
question
question_type
scope
module_events[]
retrieval_calls[]
semantic_gap_decision
recognition_run_ids[]
evidence_ids[]
claim_ids[]
answer_status
model_profiles[]
prompt_versions[]
cache_status
cost_summary
latency_summary
created_at
```

追溯记录属于产品运行审计，不应默认建成 Neo4j 业务节点。其存储位置应通过独立 port 抽象，可先采用本地持久化或专用运行数据库。

## 4. 反馈契约

`FeedbackEvent`：

```text
feedback_id
request_id
claim_id
action
reason
correction
user_id
created_at
```

`action`：

```text
confirm
reject
correct
request_review
```

`FeedbackResult`：

```text
feedback_id
status
affected_claim_ids[]
candidate_review_request_id
new_evidence_request
warnings[]
```

## 5. 反馈状态机

```text
received
  -> validated
  -> recorded
  -> review_required
  -> accepted / rejected / unresolved
```

规则：

- `confirm` 记录用户认可，但不自动把语义解释变成来源事实。
- `reject` 标记该 claim 的用户反馈，不删除底层证据和历史回答。
- `correct` 保存用户修正内容，并生成待审核的新证据或复核任务。
- `request_review` 将既有 candidate 送入 `CandidateReviewService`。
- 任何 formal 提升仍需通过候选集合完整性、同页范围、关系方向和冲突检查等硬规则。

## 6. Claim 到证据的追溯

系统必须能够回答：

- 这条结论属于哪个用户问题？
- 使用了哪些来源事实、派生关系或语义证据？
- 是否调用了 Qwen，使用什么模型和 prompt？
- 是否命中缓存？
- 是否存在候选或正式关系？
- 用户是否确认、否认或纠正过？
- 哪次审核将候选提升为正式关系？

追溯引用使用稳定业务 ID，不依赖 Neo4j 内部节点 ID。

## 7. 写回与提升边界

反馈模块可以发起受控操作，但不得直接调用 repository 写回方法或拼写 Cypher。

允许路径：

```text
FeedbackEvent
  -> FeedbackService
  -> CandidateReviewService / semantic service
  -> DrawingGraphToolFacade 或受控 application port
  -> repository
```

禁止行为：

- 用户点击确认后直接修改 `DrawingBlock.block_type`。
- 删除与用户反馈冲突的历史 observation。
- 把 `matched_candidate` 当作正式关系。
- 绕过硬规则建立 `MATCHES_SECTION_CAPTION` 或其他正式边。
- 在没有 `allow_write_back=true` 和权限校验时持久化反馈衍生证据。

## 8. 隐私、权限与审计

- `user_id` 应为业务身份引用，不保存不必要的个人信息。
- 反馈写入、候选审核和正式提升分别授权。
- 审计记录不可静默覆盖；纠正形成新事件。
- 错误日志不得包含 API key、数据库密码或完整敏感 payload。
- 对外回答可展示必要追溯字段，内部成本和诊断字段按权限控制。

## 9. 可观测性

至少记录：

```text
request_count
answer_status_count
recognition_trigger_rate
cache_hit_rate
recognition_failure_rate
average_latency
estimated_and_actual_cost
feedback_rate
claim_rejection_rate
candidate_promotion_rate
```

指标用于评估系统效果，不替代具体 run 和证据审计。

## 10. 错误与降级

| 情况 | 处理 |
|---|---|
| 追溯存储不可用 | 仍可返回答案，但标记 trace unavailable |
| claim_id 不存在 | 拒绝反馈，返回 not found |
| 用户无写回权限 | 记录只读请求结果或返回 forbidden |
| candidate 不满足硬规则 | 保持 candidate，状态 unresolved/rejected |
| 修正内容缺少依据 | 保存反馈事件，不生成正式事实 |
| 审核服务不可用 | 保持待审核状态，可重试 |

## 11. 不负责的内容

- 不重新理解原始用户问题。
- 不执行常规图谱检索和证据融合。
- 不直接调用 Qwen 完成首次识别。
- 不替代 CandidateReviewService 的硬规则。
- 不把运行审计混入来源事实图谱。

## 12. 测试策略

- TraceRecord 从请求到 claim 的完整关联测试。
- confirm/reject/correct/request_review 状态机测试。
- 用户确认不能直接提升 formal 的安全测试。
- 候选审核三态和硬规则失败测试。
- `allow_write_back=false` 与权限不足测试。
- 存储不可用时答案可返回但带 warning 的降级测试。
- 审计不可覆盖、修正追加事件的测试。
- 敏感信息脱敏和访问控制测试。

## 13. 验收标准

- 任一 AnswerPackage 可通过 `request_id` 回查模块决策、证据和运行信息。
- 任一 claim 可定位到 page/block/element、bbox 或语义证据。
- 用户反馈有稳定事件 ID、状态和审计时间。
- confirm、reject、correct 和 request_review 均有确定处理语义。
- 用户反馈不会直接覆盖来源事实或提升正式关系。
- 正式关系提升只能经候选审核和硬规则完成。
- 追溯存储故障不会被误报为答案本身已失败。

