# 输出契约

## 1. 六类输出事实

回答涉及图谱结果时，必须明确标注以下事实类型，不得混用：

| 类型 | 含义 | 示例 |
|---|---|---|
| `source_fact` | 来源事实层：由导入写入、可追溯到输入数据的稳定事实 | 页面图片路径、`DrawingBlock` 业务 ID、bbox |
| `derived_relation` | 空间与上下文派生关系层：由离线增强按规则生成的正式派生关系 | `HAS_CAPTION`、`HAS_ANNOTATION`、`HAS_SECTION_MARK` |
| `semantic_observation` | 图谱内语义观察，来自模型对来源事实的识别 | `TextObservation` |
| `semantic_interpretation` | 图谱内语义解释，模型对观察的解读 | `BlockInterpretation`、`BasicInfoInterpretation`、`TableInterpretation` |
| `candidate_relation` | 候选关系：未经复核确认的关系 | `CANDIDATE_CAPTION_OF`、`CANDIDATE_HAS_SECTION_MARK` |
| `formal_relation` | 正式关系：经过显式复核和硬规则确认的关系 | `MATCHES_SECTION_CAPTION`（在规则条件满足时） |

## 2. 候选关系不是正式事实

- `candidate_relation` 与 `matched_candidate` 都**不是**正式图谱关系。
- 不得把候选 ID、模型匹配结果或 `matched_candidate` 写成确定答案。
- 只有经过 `CandidateReviewService` 和硬规则的显式复核，候选才能提升为 `formal_relation`。

## 3. 证据字段

回答必须保留可追溯证据字段，能查回原始来源：

- 稳定业务 ID（project/drawing set/page/block ID）
- 页面 ID
- 图片路径
- `bbox`
- `recognition_run_id`（关联图谱外 run log 与图谱内证据）
- `payload_ref`（不可变 payload 引用）
- 候选关系状态（如 candidate id、status、rule 版本）

## 4. 不确定状态保守表达

对以下状态如实、保守表达，不补猜：

- `partial`：部分完成
- `ambiguous`：结果有歧义
- `not_found`：未找到
- `recognition_failed`：识别失败
- `not_recognized`：未能识别

证据不足时不构造结论；多候选、跨页或规则边界不明确时，只报告候选状态。

## 5. 禁止混层表述

- 禁止把模型观察写回或表述为来源事实。
- 禁止把 AI 的 `interpreted_type` 写成 `DrawingBlock.block_type`。
- 禁止把 `RecognitionRun`（图谱外日志）与图谱内 `TextObservation`/`Interpretation` 混为一谈。
- 禁止把计划中的验证状态写成已执行结果。
