# 外部产品级反馈 API 设计

- 日期：2026-08-20
- 状态：已批准（待用户复审本文件）
- 关联：08 反馈模块（`assistant_feedback_*.py`）、只读产品 HTTP adapter（`assistant_http.py`）

## 1. 背景与现状

08 反馈模块的内部能力已实现：`FeedbackService.submit_feedback()`（confirm/reject/correct/request_review）、权限策略（fail-closed）、状态机、审计、`CandidateReviewAdapter` 受控对接，以及 `FeedbackStorePort`。**缺少对外入口**：外部系统无法通过 HTTP 提交反馈。

只读产品 HTTP adapter（`assistant_http.py`）已有可复用的模式：FastAPI 应用工厂、Bearer token 认证中间件（`hmac.compare_digest`）、统一成功/错误 envelope、请求体大小限制、`/health/live` 与 `/health/ready`。

## 2. 目标与范围

### 2.1 范围内

- 独立 FastAPI 应用 `assistant_feedback_http.py` + runtime + `scripts/serve_feedback_http.py`。
- `POST /api/v1/drawing-assistant/feedback`：接收并校验反馈请求，构造 `FeedbackEvent`，调用 `FeedbackService.submit_feedback()`，返回 `FeedbackResult`。
- Bearer token 认证（可关闭）、权限矩阵、统一 envelope、请求体大小限制、health 端点。
- 默认 `InMemoryFeedbackStore` + 可注入 `FeedbackStorePort`；默认 `InMemoryTraceStore` + 可注入 `TraceStorePort`（用于 claim 校验）。

### 2.2 范围外

- 外部持久化 feedback/trace store（仅留注入点）。
- 多用户账号/RBAC 集成（actor 由 token/配置解析为简单 actor）。
- `promote_formal_relation`（反馈 action 永不授予）。
- 外部产品级 Web UI、反馈驱动自动再训练。
- 不新增 Neo4j schema、不修改业务事实；`confirm/correct` 不改变 `fact_kind`；候选关系仍是候选。

## 3. 已确认决策

1. 采用方案 A：独立反馈 HTTP 应用，与只读 assistant HTTP 并列。
2. 认证复用 Bearer token 模式；`/health/live` 匿名，业务路由与 `/health/ready` 需要 token（配置 token 时）。
3. actor 由请求头/配置解析为 `{actor_id, permissions}`；默认权限：confirm/reject/correct → `RECORD_FEEDBACK`；request_review → 另需 `REQUEST_CANDIDATE_REVIEW`。
4. 存储默认 in-memory，`FeedbackStorePort`/`TraceStorePort` 可注入；外部持久化不在本期。
5. 默认 loopback、单 worker、关闭 CORS/OpenAPI docs，端口 8002（与 QA 8000、assistant 8001 分离）。

## 4. 架构与组件

新建：
- `src/drawing_graph/assistant_feedback_http_models.py` — `HttpFeedbackRequest`/`HttpFeedbackResponse` 与序列化。
- `src/drawing_graph/assistant_feedback_http_runtime.py` — `create_feedback_http_runtime(config)`：装配 store/trace_store/`FeedbackService`/actor 解析。
- `src/drawing_graph/assistant_feedback_http.py` — `create_feedback_app(config, runtime_factory)`：FastAPI 应用工厂、中间件、路由、错误映射。
- `scripts/serve_feedback_http.py` — uvicorn 启动脚本（loopback、单 worker）。
- `tests/test_assistant_feedback_http_models.py`
- `tests/test_assistant_feedback_http_runtime.py`
- `tests/test_assistant_feedback_http.py`

修改：
- `README.md`、`docs/acceptance/USER_RUNBOOK.md`、`architecture.md`/`Module.md` 边界记录（反馈外部入口已实现、外部持久化 store 仍未实现）。

## 5. 数据流

```text
POST /api/v1/drawing-assistant/feedback
  -> 认证中间件（Bearer token；/health/live 匿名）
  -> 请求体大小限制
  -> 模型校验 HttpFeedbackRequest（action/claim_id 必填校验）
  -> runtime 构造 FeedbackEvent(feedback_id, request_id, claim_id, action, reason, correction, user_id)
  -> FeedbackService.submit_feedback(event, actor, policy)
  -> FeedbackResult -> 成功 envelope / 错误 envelope
```

## 6. 契约

### 6.1 请求 `POST /api/v1/drawing-assistant/feedback`

```json
{
  "action": "confirm|reject|correct|request_review",
  "claim_id": "claim:<hex>",
  "feedback_id": "可选，缺省自动生成",
  "request_id": "可选，缺省自动生成",
  "reason": "可选",
  "correction": "可选"
}
```

`action` 与 `claim_id` 必填；`request_id` 缺省由服务生成（`FeedbackEvent.request_id` 为必填字段）。

### 6.2 响应

成功：`{"status":"ok","data":{"feedback_id":"...","status":"recorded|review_required|...","affected_claim_ids":[...],"warnings":[...]}}`

错误（复用 `build_error_envelope`）：`invalid_argument` 400、`unauthorized` 401、`forbidden` 403、`claim_not_found` 404、`store_failed` 500（fail-closed）。

### 6.3 Health

`GET /health/live`（匿名）、`GET /health/ready`（配置 token 时需认证，返回 runtime/store 装配状态）。

## 7. 权限与安全

- 认证：Bearer token，`hmac.compare_digest` 常量时间比较；token 不进 URL/DTO/响应/日志。
- 授权：`FeedbackPermissionPolicy.authorize(actor, action)`，fail-closed；无权限 403。
- actor：请求头 `X-Actor-ID`（可选）+ 配置权限集；缺省 actor 无权限 → 403（除非配置了默认权限）。
- 审计：`FeedbackService` 写 `FeedbackAuditEvent`；响应与日志不输出未脱敏异常。
- 不信任 `Content-Length`：按 receive 累计字节数，超限 413。

## 8. 错误处理与边界

- `claim_id` 缺失/无效 action/非法状态转移 → 400（invalid）。
- claim 在 trace store 不存在 → 404。
- 权限不足 → 403；未认证/认证失败 → 401。
- store 写入失败 → fail-closed 500，不把反馈标成成功。
- `confirm/correct` 只记录事件与审计，不产生正式事实；`request_review` 仅在权限允许时受控触发候选复核。

## 9. 测试与验收

- 单元：请求模型校验、序列化、错误映射、权限矩阵、actor 解析。
- TestClient 端到端：401/403/400/404/成功路径、health、请求体超限 413。
- 全量离线回归保持通过。
- live 冒烟：本机 loopback 起服务 + `curl` 提交一条 confirm（无 token 环境可临时关闭认证），如实记录。
- 分层报告：外部持久化 store 未做、live Neo4j/宿主注册按既有边界标注。

## 10. 实施任务（概要，细节见实施计划）

1. HTTP 请求/响应模型与序列化。
2. Runtime（FeedbackService 装配 + actor 解析 + 默认 store）。
3. FastAPI 应用（认证/大小限制/路由/错误映射/health）。
4. 启动脚本与配置。
5. 文档、全量回归与 live 冒烟。

## 11. 交付物

- 本设计文档。
- 实施计划（writing-plans 生成）与代码/测试。
- README/RUNBOOK/架构边界更新。
