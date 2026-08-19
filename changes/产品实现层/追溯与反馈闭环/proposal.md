# 追溯与反馈闭环 Proposal

## 1. 背景

当前产品实现层已经完成从自然语言问题到只读答案的 MVP：系统能够理解问题、检索图谱、判断语义缺口、按需 dry-run 识别、融合证据并生成带 claim/citation 的答案。`AnswerPackage` 中已经包含 claim、citation、状态、warning 和识别运行引用，为后续追溯提供了基础。

但产品闭环还缺少最后一环：用户拿到答案后，需要能够追问“这条结论来自哪里”，系统也需要能够记录用户确认、否认、纠正或复核请求，并把这些反馈纳入受控审核流程。没有这层闭环，答案虽然可读，但不可长期审计；用户反馈也只能停留在对话层，无法形成可复查、可授权、可回滚的产品行为。

## 2. 当前问题

- 当前只有薄版 `TraceRecord` 与 `FeedbackEvent` 数据容器，没有完整的产品级追溯存储和反馈服务。
- 当前 `DrawingAssistantService` 是只读总编排，不持久化答案运行记录，也没有 claim 级回查入口。
- 当前用户反馈没有状态机、权限、审计和结果 DTO。
- 当前 `CandidateReviewService` 已有候选审核能力，但产品反馈尚未受控对接它。
- 当前不能把用户确认、模型解释或 `matched_candidate` 当成正式事实；这一边界需要在反馈闭环中被显式保护。

## 3. 功能目标

本需求目标是补齐产品级追溯与反馈闭环：

- 记录一次产品问答从请求、模块事件、检索、语义决策、识别、证据、claim 到答案状态的追溯链。
- 支持通过 `request_id` 回查一次答案的模块决策、证据引用、claim、识别运行、缓存和 warning。
- 支持通过 `claim_id` 回查该结论关联的 citation、evidence、page/block/element、bbox、payload_ref、recognition_run_id 或 candidate/review 引用。
- 接收用户对 claim 的 `confirm`、`reject`、`correct`、`request_review` 反馈，并输出稳定反馈结果。
- 为反馈写入、候选复核、正式提升分别建立权限和审计边界。
- 将 `request_review` 类型反馈受控转交给 `CandidateReviewService`，但不绕过其三态与硬规则。

## 4. 修改范围

建议拆成第 7、8 两次实施：

第 7 次：追溯闭环基础

- 扩展追溯数据合同。
- 新增 trace store port 和内存实现。
- 新增 trace builder。
- 新增 claim 追溯查询投影。
- 可选接入 `DrawingAssistantService`，在不改变只读答案行为的前提下记录 trace。

第 8 次：反馈闭环

- 新增 feedback 数据合同。
- 新增 feedback store port 和内存实现。
- 新增反馈状态机。
- 新增反馈权限与审计。
- 新增反馈服务。
- 新增 `CandidateReviewService` 受控适配。

## 5. 不包含范围

- 不修改业务源码以外的目标文档之外内容，当前文档阶段不写代码。
- 不新增 Neo4j schema。
- 不把产品 trace/feedback 默认写入 Neo4j 业务图谱。
- 不新增或修改 QA CLI、QA HTTP API、本地只读 MCP adapter 的现有行为。
- 不实现产品级外部 HTTP/MCP/Web UI 反馈入口。
- 不让 adapter 直接访问 Neo4j driver、repository 或 Cypher。
- 不让用户确认直接修改来源事实、`DrawingBlock.block_type` 或正式关系。
- 不把 `candidate_relation`、`matched_candidate`、语义解释或用户修正写成 `formal_relation`。
- 不把 skipped live 测试描述成 live Neo4j 已通过。

## 6. 影响模块

- 产品公共合同：扩展 trace/feedback 相关 DTO，但保持已有字段兼容。
- 产品只读总编排：可选注入 trace service，默认未注入时行为不变。
- 答案生成：继续提供 claim/citation，不承担持久化或反馈处理。
- 证据融合：继续输出 EvidenceBundle，不承担反馈状态机。
- 候选审核：作为反馈 `request_review` 的受控下游，不被绕过。
- 测试与验收文档：新增 trace/feedback 专项测试和验证分层说明。

## 7. 兼容性要求

- 必须保持现有 QA / HTTP / MCP / ToolFacade 兼容。
- `DrawingGraphQAService` 继续作为固定六类 QA 兼容层，不变成完整产品反馈编排器。
- `DrawingAssistantService` 默认仍是只读链路；不得因为 trace 接入而允许业务写回。
- 默认 `write_back=false`；任何反馈持久化和候选复核都必须显式权限控制。
- `CandidateReviewService` 的 accepted/rejected/unresolved 三态与硬规则必须保留。
- 候选关系和 `matched_candidate` 不能被写成正式事实。
- unit/fake/offline/live 验证状态必须分层报告。

## 8. 验收标准

- 任一 `AnswerPackage` 可通过 `request_id` 回查对应 `TraceRecord`。
- 任一非诊断 claim 可通过 `claim_id` 回查关联 citation 和 evidence。
- trace 记录不包含 secret、Neo4j URI、Cypher、绝对路径、完整 payload、完整 prompt 或 traceback。
- `confirm`、`reject`、`correct`、`request_review` 均有稳定状态和审计事件。
- `allow_write_back=false` 或权限不足时，反馈不得触发候选审核或任何持久化业务写回。
- `request_review` 只能通过注入的 `CandidateReviewService` 处理候选集合，并保留 unresolved/rejected 结果。
- 用户反馈不会直接覆盖来源事实、语义证据或正式关系。
- 所有新增任务均可用 fake/offline 单元测试独立验证；live Neo4j 未运行时必须明确写为未验证。

