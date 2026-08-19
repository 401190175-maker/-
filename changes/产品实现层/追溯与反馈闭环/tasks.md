# 追溯与反馈闭环 Tasks

## 1. 总目标

分两次补齐产品级追溯与反馈闭环：

- 第 7 次：完成 trace port/store、TraceRecord 构造、claim 追溯和只读总编排可选接入。
- 第 8 次：完成反馈状态机、权限、审计、FeedbackService 和 `CandidateReviewService` 受控对接。

本计划不实现外部产品级 HTTP/MCP/Web UI 反馈入口，不新增 Neo4j schema，不改变现有 QA/HTTP/MCP/ToolFacade 兼容链路。

## 2. 架构说明

新增模块位于 `src/drawing_graph/assistant_*` 产品应用层。追溯与反馈 store 是产品运行审计 store，不是 Neo4j 业务图谱。第 7 次只写 trace store；第 8 次写 feedback store 并仅在 `request_review` 且权限允许时调用注入的 `CandidateReviewService`。

依赖方向固定为：

```text
adapter / DrawingAssistantService
  -> assistant_traceability_service / assistant_feedback_service
  -> trace/feedback ports and policies
  -> CandidateReviewService（仅 request_review）
```

禁止 adapter 或 trace/feedback service 直接访问 Neo4j driver、session、transaction、repository 或 Cypher。

## 3. 全局约束

- 默认 `write_back=false`。
- 不新增 Neo4j schema。
- 不修改来源事实。
- 不把 `candidate_relation`、`matched_candidate`、用户确认或语义解释写成 `formal_relation`。
- 不绕过 `DrawingGraphToolFacade` 或 `CandidateReviewService`。
- 不改变现有 QA CLI、HTTP API、本地 STDIO MCP adapter 行为。
- 不在错误、trace、feedback、审计或 adapter 输出中泄漏 secret、Authorization、Neo4j URI、Cypher、绝对路径、完整 payload、完整 prompt、provider 原文或 traceback。
- fake/offline/unit/live 验证状态必须分层报告；skipped live 测试不能描述为 live Neo4j 已通过。

## 4. 文件职责表

| 文件 | 职责 |
|---|---|
| `src/drawing_graph/assistant_trace_models.py` | 追溯 DTO、claim trace、写入/查询结果 |
| `src/drawing_graph/assistant_trace_store.py` | TraceStorePort 与内存实现 |
| `src/drawing_graph/assistant_trace_builder.py` | 从 01-06 中间产物和 AnswerPackage 构造 TraceRecord |
| `src/drawing_graph/assistant_claim_trace.py` | claim_id 到 evidence/citation/run 的只读追溯投影 |
| `src/drawing_graph/assistant_traceability_service.py` | 追溯记录与查询入口 |
| `src/drawing_graph/assistant_feedback_models.py` | 反馈 action、状态、权限、审计、结果 DTO |
| `src/drawing_graph/assistant_feedback_store.py` | FeedbackStorePort 与 append-only 内存实现 |
| `src/drawing_graph/assistant_feedback_permissions.py` | 反馈权限策略 |
| `src/drawing_graph/assistant_feedback_state_machine.py` | 反馈状态机 |
| `src/drawing_graph/assistant_candidate_review_adapter.py` | feedback request_review 到 CandidateReviewService 的受控适配 |
| `src/drawing_graph/assistant_feedback_service.py` | 反馈服务入口 |
| `src/drawing_graph/drawing_assistant_service.py` | 可选接入 traceability service，保持只读 |
| `src/drawing_graph/drawing_assistant_factory.py` | 可选装配 traceability service，默认兼容 |
| `tests/test_assistant_trace_*.py` | 第 7 次追溯专项测试 |
| `tests/test_assistant_feedback_*.py` | 第 8 次反馈专项测试 |
| `tests/test_drawing_assistant_*.py` | 只读总编排兼容回归 |
| `tests/test_candidate_review_service.py` | 候选审核兼容回归 |
| `Module.md`、`README.md`、`architecture.md` | 实现完成后再同步文档边界与验证状态 |

## 5. 任务列表

### Task 1: 【第 7 次】定义追溯 DTO 合同

**明确目标：**
只定义产品级追溯、模块事件、成本/时延、claim trace 和 trace 查询结果 DTO。

**指定修改文件：**
- Create: `src/drawing_graph/assistant_trace_models.py`
- Modify: `src/drawing_graph/assistant_models.py`
- Test: `tests/test_assistant_trace_models.py`

**可独立测试：**
```powershell
python -m unittest tests.test_assistant_trace_models -v
```

**完成标准：**
DTO 校验 request_id、claim_id、evidence_ids、citation_ids、module_events、answer_status；兼容已有 `TraceRecord` 字段；不包含 Neo4j driver、repository、Cypher、完整 payload、完整 prompt 或 traceback 字段。

### Task 2: 【第 7 次】实现 TraceStorePort 与内存 store

**明确目标：**
提供 append/read 的追溯 store port 和内存实现，不做 Neo4j 持久化。

**指定修改文件：**
- Create: `src/drawing_graph/assistant_trace_store.py`
- Test: `tests/test_assistant_trace_store.py`

**可独立测试：**
```powershell
python -m unittest tests.test_assistant_trace_store -v
```

**完成标准：**
支持 `append_trace()`、`get_trace()`、`get_claim_trace()`；重复 request_id 不静默覆盖；store 不导入 Neo4j、repository、HTTP/MCP 或 CLI。

### Task 3: 【第 7 次】实现 TraceRecord 构造器

**明确目标：**
从 `AssistantRequest`、问题理解、检索、语义决策、识别、融合和答案结果构造单条 `TraceRecord`。

**指定修改文件：**
- Create: `src/drawing_graph/assistant_trace_builder.py`
- Test: `tests/test_assistant_trace_builder.py`

**可独立测试：**
```powershell
python -m unittest tests.test_assistant_trace_builder -v
```

**完成标准：**
TraceRecord 含 request、module events、source calls、decision、recognition_run_ids、evidence_ids、claim_ids、cache/cost/latency 摘要；不会读取图谱、调用模型或写 store；敏感字段被排除。

### Task 4: 【第 7 次】实现 claim 追溯投影

**明确目标：**
提供 `claim_id -> evidence/citation/run/payload/candidate/review` 的只读投影。

**指定修改文件：**
- Create: `src/drawing_graph/assistant_claim_trace.py`
- Test: `tests/test_assistant_claim_trace.py`

**可独立测试：**
```powershell
python -m unittest tests.test_assistant_claim_trace -v
```

**完成标准：**
能从 `AnswerPackage` 与 `TraceRecord` 回查 claim trace；candidate relation 仍标记为 candidate；缺失 claim 返回稳定 not_found；不使用 Neo4j 内部 ID。

### Task 5: 【第 7 次】实现 TraceabilityService

**明确目标：**
提供追溯记录和回查服务入口。

**指定修改文件：**
- Create: `src/drawing_graph/assistant_traceability_service.py`
- Test: `tests/test_assistant_traceability_service.py`

**可独立测试：**
```powershell
python -m unittest tests.test_assistant_traceability_service -v
```

**完成标准：**
支持记录 answer trace、按 request_id 查询、按 claim_id 查询；store 不可用时返回 trace unavailable，不把答案业务状态改成失败；无业务写回能力。

### Task 6: 【第 7 次】将只读总编排可选接入追溯服务

**明确目标：**
在不改变默认行为的前提下，让 `DrawingAssistantService` 可选记录 answer trace。

**指定修改文件：**
- Modify: `src/drawing_graph/drawing_assistant_service.py`
- Test: `tests/test_drawing_assistant_service.py`
- Test: `tests/test_drawing_assistant_boundaries.py`

**可独立测试：**
```powershell
python -m unittest tests.test_drawing_assistant_service tests.test_drawing_assistant_boundaries -v
```

**完成标准：**
未注入 trace service 时行为完全兼容；注入时答案生成后记录 trace；trace 失败不触发业务写回；`allow_write_back=true` 仍被拒绝。

### Task 7: 【第 7 次】更新 factory 的追溯装配

**明确目标：**
让产品 factory 可选装配内存 traceability service。

**指定修改文件：**
- Modify: `src/drawing_graph/drawing_assistant_factory.py`
- Test: `tests/test_drawing_assistant_factory.py`

**可独立测试：**
```powershell
python -m unittest tests.test_drawing_assistant_factory -v
```

**完成标准：**
默认装配保持只读兼容；可显式传入 trace store 或 traceability service；factory 不创建 Neo4j driver、不读取环境变量、不写业务数据。

### Task 8: 【第 7 次】补充追溯边界静态测试

**明确目标：**
防止 trace 模块导入禁止依赖或泄漏敏感字段。

**指定修改文件：**
- Create: `tests/test_assistant_trace_boundaries.py`
- Test: `tests/test_assistant_trace_boundaries.py`

**可独立测试：**
```powershell
python -m unittest tests.test_assistant_trace_boundaries -v
```

**完成标准：**
测试断言 trace 模块不导入 Neo4j driver、repository、Cypher、HTTP/MCP adapter 或 CLI；输出中不含 secret、URI、Cypher、绝对路径、payload、prompt、traceback。

### Task 9: 【第 7 次】同步追溯闭环文档

**明确目标：**
在实现完成后同步追溯闭环的架构边界、已实现能力和验证状态。

**指定修改文件：**
- Modify: `architecture.md`
- Modify: `Module.md`
- Modify: `README.md`
- Test: `tests/test_module_docs.py`
- Test: `tests/test_readme.py`

**可独立测试：**
```powershell
python -m unittest tests.test_module_docs tests.test_readme -v
```

**完成标准：**
文档只声明第 7 次已实现的 trace 能力；明确不含反馈状态机、CandidateReviewService 对接、Neo4j schema、外部反馈 API；验证状态分层说明。

### Task 10: 【第 8 次】定义反馈 DTO 合同

**明确目标：**
只定义反馈 action、状态、权限意图、审计事件和反馈结果 DTO。

**指定修改文件：**
- Create: `src/drawing_graph/assistant_feedback_models.py`
- Modify: `src/drawing_graph/assistant_models.py`
- Test: `tests/test_assistant_feedback_models.py`

**可独立测试：**
```powershell
python -m unittest tests.test_assistant_feedback_models -v
```

**完成标准：**
支持 confirm/reject/correct/request_review；状态包含 received/validated/recorded/review_required/accepted/rejected/unresolved/forbidden/invalid；DTO 不含 repository、Cypher、driver 或未脱敏异常字段。

### Task 11: 【第 8 次】实现 FeedbackStorePort 与 append-only 内存 store

**明确目标：**
提供反馈事件和审计事件的 append-only store。

**指定修改文件：**
- Create: `src/drawing_graph/assistant_feedback_store.py`
- Test: `tests/test_assistant_feedback_store.py`

**可独立测试：**
```powershell
python -m unittest tests.test_assistant_feedback_store -v
```

**完成标准：**
支持追加 feedback、追加 audit event、按 feedback_id/request_id 查询；不静默覆盖旧事件；store 不访问 Neo4j。

### Task 12: 【第 8 次】实现反馈权限策略

**明确目标：**
区分 trace read、feedback record、candidate review request 和 formal promotion 权限。

**指定修改文件：**
- Create: `src/drawing_graph/assistant_feedback_permissions.py`
- Test: `tests/test_assistant_feedback_permissions.py`

**可独立测试：**
```powershell
python -m unittest tests.test_assistant_feedback_permissions -v
```

**完成标准：**
默认 fail closed；无权限时不能记录反馈或触发候选审核；`allow_write_back=false` 不能被反馈 action 绕过。

### Task 13: 【第 8 次】实现反馈状态机

**明确目标：**
实现 feedback received -> validated -> recorded -> review_required -> accepted/rejected/unresolved 的合法迁移。

**指定修改文件：**
- Create: `src/drawing_graph/assistant_feedback_state_machine.py`
- Test: `tests/test_assistant_feedback_state_machine.py`

**可独立测试：**
```powershell
python -m unittest tests.test_assistant_feedback_state_machine -v
```

**完成标准：**
非法跳转被拒绝；confirm/reject/correct 不进入 formal promotion；request_review 可进入 review_required；所有迁移产生审计事件。

### Task 14: 【第 8 次】实现 CandidateReviewService 反馈适配器

**明确目标：**
把合法 `request_review` 反馈转换为 `CandidateReviewRequest` 并调用注入的 `CandidateReviewService`。

**指定修改文件：**
- Create: `src/drawing_graph/assistant_candidate_review_adapter.py`
- Test: `tests/test_assistant_candidate_review_adapter.py`

**可独立测试：**
```powershell
python -m unittest tests.test_assistant_candidate_review_adapter -v
```

**完成标准：**
只支持 candidate claim；候选集合不完整、跨页、方向不明、缺 evidence_refs 时返回 unresolved/invalid；不直接调用 repository 或 Cypher；accepted 仍由 `CandidateReviewService` 硬规则决定。

### Task 15: 【第 8 次】实现 FeedbackService 主流程

**明确目标：**
串联 feedback 校验、claim trace 读取、权限、状态机、store、审计和可选候选审核。

**指定修改文件：**
- Create: `src/drawing_graph/assistant_feedback_service.py`
- Test: `tests/test_assistant_feedback_service.py`

**可独立测试：**
```powershell
python -m unittest tests.test_assistant_feedback_service -v
```

**完成标准：**
四类 action 均有稳定结果；confirm/reject/correct 只记录反馈；request_review 仅在权限和候选条件满足时调用 adapter；store 写入失败时 fail closed。

### Task 16: 【第 8 次】补充反馈安全边界测试

**明确目标：**
防止反馈绕过只读、事实等级和候选审核边界。

**指定修改文件：**
- Create: `tests/test_assistant_feedback_boundaries.py`
- Test: `tests/test_assistant_feedback_boundaries.py`

**可独立测试：**
```powershell
python -m unittest tests.test_assistant_feedback_boundaries -v
```

**完成标准：**
断言 feedback 模块不导入 Neo4j driver/repository/Cypher/HTTP/MCP/CLI；用户 confirm/correct 不提升 formal；candidate/matched_candidate 不写成正式事实；敏感字段被脱敏。

### Task 17: 【第 8 次】回归 CandidateReviewService 兼容

**明确目标：**
确保反馈对接不改变既有候选审核三态和硬规则。

**指定修改文件：**
- Modify: `tests/test_candidate_review_service.py`
- Test: `tests/test_candidate_review_service.py`

**可独立测试：**
```powershell
python -m unittest tests.test_candidate_review_service -v
```

**完成标准：**
既有 accepted/rejected/unresolved 行为不变；硬规则失败仍 unresolved；repository 仅由 `CandidateReviewService` 既有路径调用。

### Task 18: 【第 8 次】同步反馈闭环文档

**明确目标：**
在实现完成后同步反馈状态机、权限、审计和 CandidateReviewService 对接边界。

**指定修改文件：**
- Modify: `architecture.md`
- Modify: `Module.md`
- Modify: `README.md`
- Test: `tests/test_module_docs.py`
- Test: `tests/test_readme.py`

**可独立测试：**
```powershell
python -m unittest tests.test_module_docs tests.test_readme -v
```

**完成标准：**
文档明确 trace/feedback 是产品运行审计；不新增 Neo4j schema；反馈不会直接修改来源事实或 formal；live 验证状态分层，不把 skipped 写成通过。

### Task 19: 【收尾】追溯与反馈专项离线回归

**明确目标：**
运行第 7、8 次全部 trace/feedback 专项测试。

**指定修改文件：**
- Test: `tests/test_assistant_trace_models.py`
- Test: `tests/test_assistant_trace_store.py`
- Test: `tests/test_assistant_trace_builder.py`
- Test: `tests/test_assistant_claim_trace.py`
- Test: `tests/test_assistant_traceability_service.py`
- Test: `tests/test_assistant_trace_boundaries.py`
- Test: `tests/test_assistant_feedback_models.py`
- Test: `tests/test_assistant_feedback_store.py`
- Test: `tests/test_assistant_feedback_permissions.py`
- Test: `tests/test_assistant_feedback_state_machine.py`
- Test: `tests/test_assistant_candidate_review_adapter.py`
- Test: `tests/test_assistant_feedback_service.py`
- Test: `tests/test_assistant_feedback_boundaries.py`

**可独立测试：**
```powershell
python -m unittest tests.test_assistant_trace_models tests.test_assistant_trace_store tests.test_assistant_trace_builder tests.test_assistant_claim_trace tests.test_assistant_traceability_service tests.test_assistant_trace_boundaries tests.test_assistant_feedback_models tests.test_assistant_feedback_store tests.test_assistant_feedback_permissions tests.test_assistant_feedback_state_machine tests.test_assistant_candidate_review_adapter tests.test_assistant_feedback_service tests.test_assistant_feedback_boundaries -v
```

**完成标准：**
专项测试全部通过；失败、跳过和未运行项分层记录；不声称 live Neo4j 或 live DashScope 已验证。

### Task 20: 【收尾】全量离线回归与验证报告

**明确目标：**
运行全量离线回归并形成验证状态说明。

**指定修改文件：**
- Test: `tests/`
- Modify: `docs/acceptance/ANSWER_GENERATION_MVP_ACCEPTANCE.md` 或新增后续 trace/feedback 验收文档

**可独立测试：**
```powershell
python -m unittest discover tests -v
```

**完成标准：**
全量离线回归结果记录为 unit/fake/offline；`tests/integration/` skipped 时明确写为 live Neo4j 未验证；不把 skipped live 测试写成通过。

## 6. 每个任务的测试命令或验证方式

每个任务已在任务条目中列出独立测试命令。第 7 次以 trace 专项测试和只读总编排兼容测试为主；第 8 次以 feedback 专项测试和 CandidateReviewService 兼容测试为主。最终再运行全量离线回归。

## 7. 完成标准

整体完成需同时满足：

- 第 7 次 trace port/store、trace builder、claim trace、traceability service 和只读总编排可选接入完成。
- 第 8 次 feedback DTO/store、权限、状态机、审计、FeedbackService 和 CandidateReviewService 对接完成。
- `confirm/reject/correct/request_review` 均有稳定处理语义。
- 用户反馈不会直接覆盖来源事实、语义证据、候选关系或正式关系。
- `request_review` 只经 `CandidateReviewService` 和硬规则。
- 不新增 Neo4j schema。
- QA/HTTP/MCP/ToolFacade 兼容链路不变。
- fake/offline/unit/live 验证状态分层报告。

## 8. 不包含范围

- 不实现外部产品级 HTTP/MCP/Web UI 反馈入口。
- 不新增 Neo4j trace/feedback 节点或关系。
- 不实现多用户权限系统的真实账号集成。
- 不实现反馈驱动的自动模型再训练。
- 不实现用户修正自动写入来源事实。
- 不实现候选关系绕过审核的 formal 提升。
- 不运行或声称 live Neo4j/live DashScope 验证，除非单独配置并实际执行。

