# 追溯与反馈闭环 Feature Analysis Report

## 0. 分析依据与当前边界

本报告基于当前工作区文件和源码扫描形成，已读取：

- 根目录 `architecture.md`、`Module.md`、`README.md`
- `changes/产品实现层/00-product-closure-blueprint.md` 至 `07-traceability-and-feedback.md`
- `src/drawing_graph/`、`scripts/`、`tests/`、`docs/acceptance/` 当前结构

当前源码已经具备产品公共合同、通用检索、问题理解、语义缺口决策、多模态识别执行、证据融合、答案生成和只读总编排 MVP。现有 `assistant_models.py` 已预留 `TraceRecord` 与 `FeedbackEvent` 名字级 DTO；`drawing_assistant_service.py` 已实现产品级 01-06 只读总编排；`candidate_review.py` 已实现候选关系审核三态与硬规则提升；`RecognitionRun`、`review_run_id`、`payload_ref`、claim/citation 等追溯字段已经存在于相邻模块。

但当前仍未实现产品级持久化追溯存储、claim 级回查服务、用户反馈 API/服务、反馈状态机、反馈权限、反馈审计，以及把反馈受控对接到 `CandidateReviewService` 的闭环。本需求应定位为 07 后续补齐项，而不是把 06/07 只读总编排改写成写回系统。

## 1. 当前架构是否支持

当前架构支持本需求的主要前提已经成立：

- 产品层位于 adapter 与 `DrawingGraphToolFacade` 之间，适合增加 `TraceabilityFeedbackService` 一类应用服务。
- `AnswerPackage`、`Claim`、`Citation` 已经能表达 claim 与 evidence/citation 的对应关系。
- `SourceCallRecord`、`RecognitionRun`、`RecognitionAttempt`、`EvidenceBundle`、`SemanticGapDecision` 已经提供模块级运行事实。
- `CandidateReviewService` 已有 accepted/rejected/unresolved 三态和硬规则，适合作为反馈触发候选复核的受控下游。
- `DrawingAssistantService` 首行拒绝 `allow_write_back=true`，这为本需求拆分“只读问答”和“显式反馈写入”提供了安全边界。

当前架构不支持或尚未落地的部分：

- 没有 `TraceStorePort`、`FeedbackStorePort` 或产品运行审计 store。
- `TraceRecord` 字段较薄，不能完整表达 07 文档要求的模块事件、识别、证据、claim、成本、时延和缓存闭环。
- `FeedbackEvent` 只是基础数据容器，没有 action 枚举、状态机、结果 DTO、权限策略或审计记录。
- 没有可回查 `request_id -> AnswerPackage/TraceRecord`、`claim_id -> evidence/citation` 的产品服务。
- 没有将 `request_review` 反馈转换为 `CandidateReviewRequest` 的受控适配器。
- 没有产品级反馈 CLI/HTTP/MCP/Web UI；当前产品 CLI 也不提供 write-back 参数。

结论：架构方向支持，但需要新增独立应用层模块和 store port；不应绕过 `DrawingGraphToolFacade`、不应让 adapter 直接访问 Neo4j driver/repository/Cypher，也不应把反馈记录混入来源事实图谱。

## 2. 需要新增哪些模块

建议新增模块分为两次实施。

第 7 次：追溯闭环基础

- `assistant_trace_models.py`：扩展产品级追溯、claim 支撑、成本/时延、模块事件和存储结果 DTO。
- `assistant_trace_store.py`：定义 `TraceStorePort` 与内存实现，负责 append/read，不访问 Neo4j。
- `assistant_trace_builder.py`：从 `AssistantRequest`、01-06 中间产物、`AnswerPackage` 构造 `TraceRecord`。
- `assistant_claim_trace.py`：提供 claim 到 evidence/citation/run/module event 的只读回查投影。
- `assistant_traceability_service.py`：产品级追溯服务入口，负责记录 trace、查询 request/claim 追溯，不做反馈写入。
- `tests/test_assistant_trace_*.py`：合同、store、builder、claim 回查、边界测试。

第 8 次：反馈闭环与受控对接

- `assistant_feedback_models.py`：反馈 action、状态、权限、审计、结果 DTO。
- `assistant_feedback_store.py`：定义 `FeedbackStorePort` 与内存实现，追加反馈事件和审计事件。
- `assistant_feedback_permissions.py`：权限策略，区分 trace read、feedback record、candidate review request、formal promotion authorization。
- `assistant_feedback_state_machine.py`：received -> validated -> recorded -> review_required -> accepted/rejected/unresolved 状态机。
- `assistant_feedback_service.py`：反馈服务入口，处理 confirm/reject/correct/request_review。
- `assistant_candidate_review_adapter.py`：把合法 feedback request_review 转为 `CandidateReviewRequest`，并调用注入的 `CandidateReviewService`。
- `tests/test_assistant_feedback_*.py`：状态机、权限、审计、CandidateReviewService 对接、安全边界测试。

可选 adapter 文档或后续任务：

- 产品 CLI/HTTP/MCP 反馈入口建议另立需求，除非明确要求本轮实现。

## 3. 影响哪些已有模块

需要影响但应保持兼容的模块：

- `assistant_models.py`：可保留已有 `TraceRecord`/`FeedbackEvent` 兼容导出，或通过新模块扩展并保持字段兼容；不得破坏现有测试。
- `drawing_assistant_service.py`：第 7 次可注入可选 trace service，在只读答案生成后记录 trace；默认未注入时行为不变。仍必须拒绝 `allow_write_back=true`。
- `assistant_answer_generation.py`、`assistant_claim_builder.py`、`assistant_citation_builder.py`：不需要重写，只需保证 claim/citation ID 足够供 trace builder 消费。
- `assistant_evidence_fusion.py` 与 `assistant_evidence_fusion_models.py`：作为 trace builder 输入，不应新增查询、模型调用或写回。
- `candidate_review.py`：第 8 次作为下游被注入调用；不得由 adapter 或 feedback service 绕过硬规则直接调用 repository。
- `tool_facade.py`、`tool_factory.py`：默认不改；如未来需要通过 facade 暴露受控反馈能力，应独立设计并保持旧 QA/HTTP/MCP 只读链路兼容。
- `scripts/drawing_assistant.py`：本需求不应默认添加 write-back 参数；若后续增加反馈 CLI，应是独立显式命令。

不应影响：

- 基础导入、离线派生关系增强、QA CLI、只读 HTTP API、本地只读 MCP adapter 的现有行为。
- Neo4j 来源事实 schema、语义证据 schema、候选关系与正式关系白名单。

## 4. 技术方案有哪些

### 方案 A：产品层独立 trace/feedback store，默认内存，后续可替换持久化

在产品层新增 port + service。trace/feedback 不作为 Neo4j 业务节点，默认使用内存 store 完成合同与服务闭环，后续再提供 JSONL、SQLite 或运行数据库实现。

优点：

- 最符合 07 文档“追溯记录属于产品运行审计，不应默认建成 Neo4j 业务节点”的边界。
- 不改变 Neo4j schema，不影响导入、QA、HTTP、MCP。
- 容易进行 fake/offline/unit 验证。
- 权限和审计可以在产品层 fail closed。

缺点：

- 首版内存 store 不具备跨进程持久化能力。
- 若后续需要多用户、多进程、权限域，需要再补持久化 store。

### 方案 B：将 TraceRecord/FeedbackEvent 写入 Neo4j 审计节点

把产品运行记录和反馈事件作为 Neo4j 节点/关系保存，并关联 page/block/claim/evidence。

优点：

- 与图谱查询天然接近，便于图查询。
- 可跨进程保存。

缺点：

- 需要新增 Neo4j schema 和迁移脚本，扩大风险。
- 容易把运行审计误写成来源事实或业务知识。
- 权限与清理策略复杂，可能影响 live Neo4j 测试。
- 与当前默认只读产品编排冲突较大。

### 方案 C：仅把追溯和反馈放进 AnswerPackage，不持久化

把 trace summary 和 feedback hint 放入返回值，不新增 store。

优点：

- 实施量最小。
- 不产生写回风险。

缺点：

- 无法满足“回查 request/claim、接收用户反馈、审计、反馈状态机”的核心目标。
- 用户关闭会话后追溯与反馈丢失。
- CandidateReviewService 无法形成稳定复核入口。

## 5. 优缺点比较

| 方案 | 架构兼容 | 实施风险 | 是否满足反馈闭环 | 是否新增 Neo4j schema | 推荐度 |
|---|---|---:|---|---|---|
| A 产品层独立 store | 高 | 低 | 是，分阶段满足 | 不新增 | 高 |
| B Neo4j 审计节点 | 中 | 高 | 是 | 新增 | 低 |
| C 仅返回 trace summary | 高 | 低 | 否 | 不新增 | 低 |

## 6. 推荐方案

推荐方案 A，并拆成第 7、8 两次：

- 第 7 次只做追溯闭环：补齐 trace DTO、store port、trace builder、claim 回查和只读总编排接入。该阶段仍不实现用户反馈写入，不调用 `CandidateReviewService`，不新增 Neo4j schema。
- 第 8 次再做反馈闭环：新增 feedback DTO/store、状态机、权限、审计、request_review 到 `CandidateReviewService` 的受控适配。该阶段仍不允许用户反馈直接改写来源事实或直接提升 formal。

这能把“追溯”和“反馈写入”拆成两个可独立验收的风险层：第 7 次证明每个回答可回查，第 8 次证明反馈能被记录、授权、审计并受控进入候选审核。

## 7. 风险

- 事实等级污染：用户确认、模型解释、`matched_candidate` 被误写成 `formal_relation`。缓解：feedback 状态机不提供事实等级提升能力，formal 只能由 `CandidateReviewService` 和硬规则产生。
- 写回授权漂移：`allow_write_back=false` 被 trace 或 feedback 旁路绕开。缓解：trace read/write 与 feedback/candidate review 权限分开，默认拒绝写回；只读问答服务继续拒绝 `allow_write_back=true`。
- 审计覆盖：纠正反馈覆盖历史 observation 或历史答案。缓解：store 仅 append，纠正形成新事件，旧 trace 保持不可变。
- 敏感信息泄漏：trace 记录完整 prompt、payload、路径、URI、密钥、traceback。缓解：复用现有脱敏原则；trace builder 只保存摘要、稳定 ID 和必要诊断。
- 兼容性破坏：为反馈新增 adapter 时误改 QA/HTTP/MCP 只读链路。缓解：本需求不改现有 QA/HTTP/MCP；若后续要外部入口，单独设计显式反馈入口。
- live 验证误报：skipped integration 被写成 live Neo4j 通过。缓解：测试计划分层报告 unit/fake/offline/skipped/live。

## 8. 与当前 00-07 产品实现层规划的关系

- `00-product-closure-blueprint.md` 把 `TraceRecord / FeedbackEvent` 作为端到端输出尾部，本需求补齐该尾部。
- `01-question-understanding.md` 已有 `source_trace` 问题类型和 `QuestionUnderstandingTraceBuilder` 轻量事件，本需求消费这些事件，不重做问题理解。
- `02-graph-retrieval.md` 负责只读证据获取，本需求记录 retrieval calls 与 evidence IDs，不新增检索路径。
- `03-semantic-gap-decision.md` 负责是否识别，本需求记录 decision、reason codes、cache candidates，不改变决策。
- `04-multimodal-recognition.md` 负责识别执行，本需求记录 recognition_run_ids、attempt 摘要和失败摘要，不直接调用模型。
- `05-evidence-fusion-and-cache.md` 负责融合与可选语义写回，本需求记录 EvidenceBundle、cache/write-back 结果，不做事实等级提升。
- `06-answer-generation.md` 负责 claim/citation/AnswerPackage，本需求基于这些结果建立 claim 级追溯。
- `07-traceability-and-feedback.md` 是本需求的直接蓝图；当前文档描述目标但未落地产品级 store/API/状态机，本需求将其拆成可实施计划。

## 9. 当前已实现能力与未实现能力边界

已实现或已有基础：

- `AssistantRequest`、`QuestionUnderstandingResult`、`EvidenceRequirement`、`RetrievalBundle`、`AnswerPackage`、`Claim`、`Citation`、薄版 `TraceRecord`、薄版 `FeedbackEvent`。
- 01-06 产品模块和 07 只读总编排 MVP。
- `DrawingAssistantService.answer()` 默认只读，拒绝 `allow_write_back=true`。
- `CandidateReviewService.review_candidate_group()` 三态审核、硬规则、可选 repository 写入。
- 图谱外 `RecognitionRun`，图谱内 `TextObservation`/`Interpretation`，以及 `recognition_run_id` 关联。
- QA CLI、只读 HTTP API、本地只读 MCP adapter 与 `DrawingGraphToolFacade` 兼容链路。

未实现或不能声称已实现：

- 产品级持久化 `TraceRecord` store。
- request/claim 追溯查询服务。
- 用户反馈 API、CLI、HTTP/MCP/Web UI 入口。
- 反馈状态机和权限策略。
- 反馈审计 append-only store。
- `request_review` 到 `CandidateReviewService` 的产品级对接。
- trace/feedback 的 live Neo4j 持久化验证。
- 反馈驱动的自动事实修正、自动 schema 变更或自动 formal 提升。

## 10. 验证建议

验证必须分层：

- unit/fake：DTO 校验、store port、trace builder、claim 回查、feedback 状态机、权限拒绝、CandidateReviewService fake 对接。
- offline/contract：`python -m unittest ... -v` 覆盖 trace/feedback 专项测试，不连接真实 Neo4j，不调用真实 Qwen。
- static boundary：测试禁止 trace/feedback 服务导入 Neo4j driver、repository、Cypher、HTTP/MCP adapter 或 CLI 脚本；CandidateReviewService 只能作为注入依赖。
- integration skipped：未配置 `NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD` 时 skipped 只能写为 live Neo4j 未验证。
- live Neo4j：本需求推荐首版不新增 Neo4j schema，因此 live Neo4j 只需验证现有候选审核链路不被破坏；若后续增加持久化 store 到 Neo4j，应另立 schema 和迁移验收。

建议最小专项回归：

```powershell
python -m unittest tests.test_assistant_trace_models tests.test_assistant_trace_store tests.test_assistant_trace_builder tests.test_assistant_claim_trace tests.test_assistant_traceability_service -v
python -m unittest tests.test_assistant_feedback_models tests.test_assistant_feedback_store tests.test_assistant_feedback_permissions tests.test_assistant_feedback_state_machine tests.test_assistant_candidate_review_adapter tests.test_assistant_feedback_service tests.test_assistant_feedback_boundaries -v
python -m unittest tests.test_drawing_assistant_service tests.test_drawing_assistant_boundaries tests.test_candidate_review_service -v
```

