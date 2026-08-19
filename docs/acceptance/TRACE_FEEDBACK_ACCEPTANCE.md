# 追溯与反馈闭环验收记录

## 范围

`changes/产品实现层/追溯与反馈闭环/tasks.md` 的第 7 次（追溯闭环）与第 8 次（反馈闭环）Task 1-20 已实现：

- 第 7 次：追溯 DTO、`TraceStorePort` + 内存 store、`TraceRecord` 构造器、claim 追溯投影、`TraceabilityService`、`DrawingAssistantService` 可选接入与 factory 可选装配、追溯边界静态测试。
- 第 8 次：反馈 DTO、`FeedbackStorePort` + append-only store、权限策略、状态机、`CandidateReviewService` 受控适配、`FeedbackService`、反馈安全边界测试。

新增源码（`src/drawing_graph/`）：`assistant_trace_models.py`、`assistant_trace_store.py`、`assistant_trace_builder.py`、`assistant_claim_trace.py`、`assistant_traceability_service.py`、`assistant_feedback_models.py`、`assistant_feedback_store.py`、`assistant_feedback_permissions.py`、`assistant_feedback_state_machine.py`、`assistant_candidate_review_adapter.py`、`assistant_feedback_service.py`。

可选修改：`drawing_assistant_service.py`（注入 `traceability_service=None`）、`drawing_assistant_factory.py`（`traceability_service` / `trace_store` 可选装配）、`assistant_trace_models.py`（`ClaimTrace` 增加 `rule_version`）。

## 验证方式

所有命令均在仓库根目录，先 `$env:PYTHONPATH='src'` 再执行，属于 unit/fake/offline 验证，不连接真实 Neo4j，也不调用真实云模型。

### 第 7 次追溯专项

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_trace_models tests.test_assistant_trace_store tests.test_assistant_trace_builder tests.test_assistant_claim_trace tests.test_assistant_traceability_service tests.test_assistant_trace_boundaries tests.test_drawing_assistant_service tests.test_drawing_assistant_factory tests.test_drawing_assistant_boundaries -v
```

### 第 8 次反馈专项

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_feedback_models tests.test_assistant_feedback_store tests.test_assistant_feedback_permissions tests.test_assistant_feedback_state_machine tests.test_assistant_candidate_review_adapter tests.test_assistant_feedback_service tests.test_assistant_feedback_boundaries tests.test_candidate_review_service -v
```

### 追溯与反馈专项合并回归

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_trace_models tests.test_assistant_trace_store tests.test_assistant_trace_builder tests.test_assistant_claim_trace tests.test_assistant_traceability_service tests.test_assistant_trace_boundaries tests.test_assistant_feedback_models tests.test_assistant_feedback_store tests.test_assistant_feedback_permissions tests.test_assistant_feedback_state_machine tests.test_assistant_candidate_review_adapter tests.test_assistant_feedback_service tests.test_assistant_feedback_boundaries -v
```

## 验证结果快照（2026-08-17）

- 追溯与反馈专项合并回归：`Ran 107 tests ... OK`（0 失败、0 错误、0 跳过）。
- 候选审核兼容回归：`tests.test_candidate_review_service` + `tests.test_candidate_review_models` 通过，既有 accepted/rejected/unresolved 三态与硬规则不变。
- 全量离线回归 `python -m unittest discover tests`：`Ran 2577 tests`，`skipped=4`（`tests/integration/` 因缺少 `NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD` 跳过），另有 3 项既有文档契约失败（`test_assistant_docs`、`test_assistant_evidence_fusion_docs` 中关于 05 时代“06/07 仍未实现”的过期断言，与本次追溯/反馈改动无关）。

## 验证状态分层说明

- **unit/fake/offline**：追溯与反馈全部专项测试通过，属于离线/fake 验证。
- **live Neo4j**：未验证。`tests/integration/` 的 4 项测试因未配置 live Neo4j 测试环境而跳过，跳过不等于 live Neo4j 通过。
- **live DashScope / 真实文本 provider**：未验证。

## 边界确认

- 追溯只写 `TraceStorePort`，反馈只写 `FeedbackStorePort` 与审计事件；均不新增 Neo4j schema、不写业务事实。
- 用户 `confirm/reject/correct` 只记录反馈与审计，不改变 `fact_kind`、不产生正式事实；`correct` 只形成反馈事件或待审核新证据请求。
- `request_review` 仅在权限允许且候选集合完整时，通过注入的 `CandidateReviewService.review_candidate_group()`；候选不完整/跨页/方向不明/缺 evidence refs 时 unresolved/invalid。
- 默认 `write_back=false`，权限不足 fail closed；`promote_formal_relation` 永不因反馈 action 授予；`candidate_relation`/`matched_candidate` 不等于 `formal_relation`。
- 未实现外部产品级 HTTP/MCP/Web UI 反馈入口、真实多用户账号集成、反馈驱动自动再训练。
