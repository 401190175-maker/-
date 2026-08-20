# 外部产品级反馈 API 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 提供 `POST /api/v1/drawing-assistant/feedback`，让外部系统经 HTTP 提交 confirm/reject/correct/request_review 反馈，复用 08 `FeedbackService`（权限、状态机、审计、候选复核对接）。

**Architecture:** 独立 FastAPI 应用 `assistant_feedback_http.py`（Bearer token 认证 + 请求体大小限制 + 统一 envelope + health），runtime 装配 `FeedbackService(store, trace_store, policy)` 与 actor 解析；默认 in-memory store，`FeedbackStorePort`/`TraceStorePort` 可注入。

**Tech Stack:** Python 3.14、FastAPI、pydantic、unittest、uvicorn。

**设计文档:** `docs/superpowers/specs/2026-08-20-product-feedback-api-design.md`

---

## 文件结构

新建：
- `src/drawing_graph/assistant_feedback_http_models.py`
- `src/drawing_graph/assistant_feedback_http_runtime.py`
- `src/drawing_graph/assistant_feedback_http.py`
- `scripts/serve_feedback_http.py`
- `tests/test_assistant_feedback_http_models.py`
- `tests/test_assistant_feedback_http_runtime.py`
- `tests/test_assistant_feedback_http.py`

修改：
- `src/drawing_graph/config.py`（`FeedbackHttpConfig`）
- `README.md`、`docs/acceptance/USER_RUNBOOK.md`、`architecture.md`、`Module.md`

测试约定：`$env:PYTHONPATH="src"; python -m unittest tests.test_xxx -v`；全量 `python -m unittest discover tests -v`。

---

## Task 1: HTTP 请求/响应模型与序列化

**Files:**
- Create: `src/drawing_graph/assistant_feedback_http_models.py`
- Test: `tests/test_assistant_feedback_http_models.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for feedback HTTP request/response models."""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from drawing_graph.assistant_feedback_http_models import (
    HttpFeedbackRequest,
    feedback_result_to_data,
)
from drawing_graph.assistant_feedback_models import FeedbackResult, FeedbackStatus


class HttpFeedbackRequestTests(unittest.TestCase):
    def test_valid_request(self) -> None:
        request = HttpFeedbackRequest(
            action="confirm",
            claim_id="claim:1",
            reason="同意",
        )
        self.assertEqual(request.action, "confirm")
        self.assertEqual(request.claim_id, "claim:1")

    def test_invalid_action_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            HttpFeedbackRequest(action="delete", claim_id="claim:1")

    def test_missing_claim_id_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            HttpFeedbackRequest(action="confirm", claim_id="")


class FeedbackResultSerializationTests(unittest.TestCase):
    def test_result_to_data(self) -> None:
        result = FeedbackResult(
            feedback_id="fb:1",
            status=FeedbackStatus.RECORDED,
            affected_claim_ids=("claim:1",),
            warnings=("note",),
        )
        data = feedback_result_to_data(result)
        self.assertEqual(data["feedback_id"], "fb:1")
        self.assertEqual(data["status"], "recorded")
        self.assertEqual(data["affected_claim_ids"], ["claim:1"])
        self.assertEqual(data["warnings"], ["note"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails** — `python -m unittest tests.test_assistant_feedback_http_models -v` → FAIL（模块不存在）。

- [ ] **Step 3: Implement**

```python
"""HTTP request/response models for the product feedback API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from .assistant_feedback_models import FeedbackResult


_ACTIONS = frozenset({"confirm", "reject", "correct", "request_review"})


class HttpFeedbackRequest(BaseModel):
    """Validated feedback submission payload."""

    action: str
    claim_id: str = Field(min_length=1)
    feedback_id: str | None = None
    request_id: str | None = None
    reason: str | None = None
    correction: str | None = None

    @field_validator("action")
    @classmethod
    def _validate_action(cls, value: str) -> str:
        if value not in _ACTIONS:
            raise ValueError(f"action must be one of {sorted(_ACTIONS)}")
        return value


def feedback_result_to_data(result: FeedbackResult) -> dict[str, Any]:
    """Serialize a FeedbackResult into a stable HTTP data payload."""

    return {
        "feedback_id": result.feedback_id,
        "status": result.status.value if hasattr(result.status, "value") else str(result.status),
        "affected_claim_ids": list(result.affected_claim_ids),
        "warnings": list(result.warnings),
    }
```

（`FeedbackResult.warnings` 为 tuple；若字段名不同按 `assistant_feedback_models.FeedbackResult` 实际定义调整。）

- [ ] **Step 4: Run test to verify it passes** — `python -m unittest tests.test_assistant_feedback_http_models -v` → PASS。

- [ ] **Step 5: Commit**

```bash
git add src/drawing_graph/assistant_feedback_http_models.py tests/test_assistant_feedback_http_models.py
git commit -m "feat(feedback): HTTP request/response models for feedback API"
```

---

## Task 2: Runtime 与配置（FeedbackService 装配 + actor）

**Files:**
- Modify: `src/drawing_graph/config.py`（新增 `FeedbackHttpConfig`）
- Create: `src/drawing_graph/assistant_feedback_http_runtime.py`
- Test: `tests/test_assistant_feedback_http_runtime.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the feedback HTTP runtime."""

from __future__ import annotations

import unittest

from drawing_graph.assistant_feedback_http_runtime import (
    FeedbackHttpActor,
    FeedbackHttpRuntime,
)
from drawing_graph.assistant_feedback_models import FeedbackStatus
from drawing_graph.assistant_feedback_store import InMemoryFeedbackStore


class _FakeTraceStore:
    def __init__(self, known_claims: tuple[str, ...] = ()) -> None:
        self._known = set(known_claims)

    def get_claim_trace(self, claim_id: str):
        return object() if claim_id in self._known else None


class FeedbackHttpRuntimeTests(unittest.TestCase):
    def test_confirm_with_default_permission_is_recorded(self) -> None:
        store = InMemoryFeedbackStore()
        trace = _FakeTraceStore(("claim:1",))
        runtime = FeedbackHttpRuntime(
            store=store,
            trace_store=trace,
            default_permissions=("record_feedback",),
            allow_candidate_review=False,
        )
        result = runtime.submit(
            HttpFeedbackRequest(action="confirm", claim_id="claim:1")
        )
        self.assertIn(result.status.value, {"recorded", "received", "validated"})
        self.assertTrue(store.get_feedback(result.feedback_id) is not None)

    def test_request_review_without_permission_is_forbidden(self) -> None:
        runtime = FeedbackHttpRuntime(
            store=InMemoryFeedbackStore(),
            trace_store=_FakeTraceStore(("claim:1",)),
            default_permissions=("record_feedback",),
            allow_candidate_review=False,
        )
        result = runtime.submit(
            HttpFeedbackRequest(action="request_review", claim_id="claim:1")
        )
        self.assertEqual(result.status.value, "forbidden")


if __name__ == "__main__":
    unittest.main()
```

（测试顶部需 `from drawing_graph.assistant_feedback_http_models import HttpFeedbackRequest`。）

- [ ] **Step 2: Run test to verify it fails** — `python -m unittest tests.test_assistant_feedback_http_runtime -v` → FAIL（模块不存在）。

- [ ] **Step 3: Implement**

`src/drawing_graph/config.py` 追加：

```python
@dataclass(frozen=True)
class FeedbackHttpConfig:
    """Immutable product feedback HTTP settings from environment variables."""

    host: str = "127.0.0.1"
    port: int = 8002
    api_token: str = field(default="", repr=False)
    max_request_bytes: int = 65536
    default_permissions: tuple[str, ...] = ("record_feedback",)
    allow_candidate_review: bool = False
    docs_enabled: bool = False
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "FeedbackHttpConfig":
        import os

        permissions = tuple(
            part.strip()
            for part in os.environ.get(
                "FEEDBACK_HTTP_DEFAULT_PERMISSIONS",
                "record_feedback",
            ).split(",")
            if part.strip()
        )
        return cls(
            host=os.environ.get("FEEDBACK_HTTP_HOST", "127.0.0.1"),
            port=int(os.environ.get("FEEDBACK_HTTP_PORT", "8002")),
            api_token=os.environ.get("FEEDBACK_HTTP_API_TOKEN", ""),
            max_request_bytes=int(
                os.environ.get("FEEDBACK_HTTP_MAX_REQUEST_BYTES", "65536")
            ),
            default_permissions=permissions,
            allow_candidate_review=os.environ.get(
                "FEEDBACK_HTTP_ALLOW_CANDIDATE_REVIEW",
                "0",
            ).lower() in {"1", "true", "yes"},
            docs_enabled=os.environ.get("FEEDBACK_HTTP_DOCS_ENABLED", "0").lower()
            in {"1", "true", "yes"},
            log_level=os.environ.get("FEEDBACK_HTTP_LOG_LEVEL", "INFO").strip().upper(),
        )
```

`src/drawing_graph/assistant_feedback_http_runtime.py`：

```python
"""Runtime assembly for the product feedback HTTP API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .assistant_feedback_http_models import HttpFeedbackRequest, feedback_result_to_data
from .assistant_feedback_models import FeedbackResult, FeedbackStatus
from .assistant_feedback_permissions import FeedbackPermissionPolicy
from .assistant_feedback_service import FeedbackService
from .assistant_feedback_store import FeedbackStorePort, InMemoryFeedbackStore
from .assistant_models import FeedbackEvent
from .assistant_trace_store import TraceStorePort
from .config import FeedbackHttpConfig


@dataclass(frozen=True)
class FeedbackHttpActor:
    """Simple actor resolved from API configuration."""

    actor_id: str
    permissions: frozenset[str] = frozenset()


class FeedbackHttpRuntime:
    """Own the feedback service lifetime for one HTTP app instance."""

    def __init__(
        self,
        *,
        store: FeedbackStorePort | None = None,
        trace_store: TraceStorePort | None = None,
        default_permissions: tuple[str, ...] = ("record_feedback",),
        allow_candidate_review: bool = False,
        actor_id: str = "http-api",
    ) -> None:
        self.store = store or InMemoryFeedbackStore()
        self.trace_store = trace_store
        self.actor = FeedbackHttpActor(
            actor_id=actor_id,
            permissions=frozenset(default_permissions),
        )
        self.service = FeedbackService(
            store=self.store,
            trace_store=self.trace_store,
            permission_policy=FeedbackPermissionPolicy(
                allow_write_back=allow_candidate_review,
            ),
        )
        self._feedback_counter = 0

    def submit(self, request: HttpFeedbackRequest) -> FeedbackResult:
        self._feedback_counter += 1
        event = FeedbackEvent(
            feedback_id=request.feedback_id
            or f"feedback:http:{self._feedback_counter}",
            request_id=request.request_id or f"request:http:{self._feedback_counter}",
            claim_id=request.claim_id,
            action=request.action,
            reason=request.reason,
            correction=request.correction,
            user_id=self.actor.actor_id,
        )
        return self.service.submit_feedback(event, self.actor)

    def close(self) -> None:
        pass


def create_feedback_http_runtime(
    config: FeedbackHttpConfig,
) -> FeedbackHttpRuntime:
    """Build the default feedback runtime from configuration."""

    return FeedbackHttpRuntime(
        default_permissions=config.default_permissions,
        allow_candidate_review=config.allow_candidate_review,
    )
```

（`FeedbackPermissionPolicy` 构造参数若与 `allow_write_back` 命名不同，按 `assistant_feedback_permissions.py` 实际定义调整。）

- [ ] **Step 4: Run test to verify it passes** — `python -m unittest tests.test_assistant_feedback_http_runtime -v` → PASS。

- [ ] **Step 5: Commit**

```bash
git add src/drawing_graph/config.py src/drawing_graph/assistant_feedback_http_runtime.py tests/test_assistant_feedback_http_runtime.py
git commit -m "feat(feedback): feedback HTTP runtime with actor and service assembly"
```

---

## Task 3: FastAPI 应用（认证/路由/错误映射）

**Files:**
- Create: `src/drawing_graph/assistant_feedback_http.py`
- Test: `tests/test_assistant_feedback_http.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the feedback FastAPI application."""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from drawing_graph.assistant_feedback_http import create_feedback_app
from drawing_graph.config import FeedbackHttpConfig


def _config(**overrides) -> FeedbackHttpConfig:
    values = {
        "api_token": "secret",
        "default_permissions": ("record_feedback",),
        "allow_candidate_review": False,
    }
    values.update(overrides)
    return FeedbackHttpConfig(**values)


class _SeededTraceStore:
    def get_claim_trace(self, claim_id: str):
        return object() if claim_id == "claim:1" else None


class FeedbackHttpAppTests(unittest.TestCase):
    def test_health_live_is_anonymous(self) -> None:
        app = create_feedback_app(_config())
        app.state.feedback_runtime = None
        client = TestClient(app)
        response = client.get("/health/live")
        self.assertEqual(response.status_code, 200)

    def test_feedback_requires_token(self) -> None:
        app = create_feedback_app(_config())
        client = TestClient(app)
        response = client.post(
            "/api/v1/drawing-assistant/feedback",
            json={"action": "confirm", "claim_id": "claim:1"},
        )
        self.assertEqual(response.status_code, 401)

    def test_feedback_success_path(self) -> None:
        from drawing_graph.assistant_feedback_http_runtime import FeedbackHttpRuntime
        from drawing_graph.assistant_feedback_store import InMemoryFeedbackStore

        app = create_feedback_app(_config())
        app.state.feedback_runtime = FeedbackHttpRuntime(
            store=InMemoryFeedbackStore(),
            trace_store=_SeededTraceStore(),
            default_permissions=("record_feedback",),
        )
        client = TestClient(app)
        response = client.post(
            "/api/v1/drawing-assistant/feedback",
            headers={"Authorization": "Bearer secret"},
            json={"action": "confirm", "claim_id": "claim:1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertIn("feedback_id", response.json()["data"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails** — `python -m unittest tests.test_assistant_feedback_http -v` → FAIL（模块不存在）。

- [ ] **Step 3: Implement**

`src/drawing_graph/assistant_feedback_http.py`：

```python
"""FastAPI application factory for the product feedback API."""

from __future__ import annotations

import hmac
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from .assistant_adapter_serialization import (
    build_error_envelope,
    build_success_envelope,
    sanitize_error_message,
)
from .assistant_feedback_http_models import (
    HttpFeedbackRequest,
    feedback_result_to_data,
)
from .assistant_feedback_http_runtime import (
    FeedbackHttpRuntime,
    create_feedback_http_runtime,
)
from .assistant_feedback_models import FeedbackStatus
from .config import FeedbackHttpConfig


ADAPTER = "drawing-assistant-feedback-http"


def _error_response(request_id: str, status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=build_error_envelope(
            code=code,
            message=message,
            retryable=False,
            meta={"request_id": request_id},
        ),
    )


def create_feedback_app(
    config: FeedbackHttpConfig,
    runtime_factory: Callable[[FeedbackHttpConfig], FeedbackHttpRuntime] = create_feedback_http_runtime,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        runtime = runtime_factory(config)
        app.state.feedback_runtime = runtime
        try:
            yield
        finally:
            runtime.close()

    app = FastAPI(
        title="Drawing Assistant Feedback API",
        lifespan=lifespan,
        docs_url="/docs" if config.docs_enabled else None,
        redoc_url="/redoc" if config.docs_enabled else None,
    )

    @app.middleware("http")
    async def metadata_middleware(request: Request, call_next: Any) -> Any:
        request.state.request_id = str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next: Any) -> Any:
        if not config.api_token or request.url.path == "/health/live":
            return await call_next(request)
        request_id = request.state.request_id
        authorization = request.headers.get("Authorization", "")
        if not authorization:
            return _error_response(request_id, 401, "unauthorized", "authentication required")
        scheme, _, credentials = authorization.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(credentials, config.api_token):
            return _error_response(request_id, 401, "unauthorized", "authentication failed")
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _error_response(
            getattr(request.state, "request_id", "unknown"),
            400,
            "invalid_argument",
            "invalid feedback request",
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error_response(
            getattr(request.state, "request_id", "unknown"),
            exc.status_code,
            "invalid_argument",
            str(exc.detail),
        )

    @app.get("/health/live")
    def health_live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    def health_ready(request: Request) -> JSONResponse:
        runtime = getattr(request.app.state, "feedback_runtime", None)
        ready = runtime is not None
        return JSONResponse(content={"status": "ok" if ready else "not_ready"})

    @app.post("/api/v1/drawing-assistant/feedback")
    def submit_feedback(http_request: HttpFeedbackRequest, request: Request) -> JSONResponse:
        runtime: FeedbackHttpRuntime | None = getattr(request.app.state, "feedback_runtime", None)
        request_id = getattr(request.state, "request_id", "unknown")
        if runtime is None:
            return _error_response(request_id, 503, "initialization_failed", "feedback runtime unavailable")
        result = runtime.submit(http_request)
        if result.status == FeedbackStatus.FORBIDDEN:
            return _error_response(request_id, 403, "forbidden", "insufficient permission")
        if result.status == FeedbackStatus.INVALID:
            return _error_response(request_id, 400, "invalid_argument", "invalid feedback")
        return JSONResponse(
            content=build_success_envelope(
                data=feedback_result_to_data(result),
                meta={"request_id": request_id},
            )
        )

    return app
```

（若 `FeedbackStatus` 比较与 `result.status` 类型不一致，用 `result.status.value` 比较。）

- [ ] **Step 4: Run test to verify it passes** — `python -m unittest tests.test_assistant_feedback_http -v` → PASS。

- [ ] **Step 5: Commit**

```bash
git add src/drawing_graph/assistant_feedback_http.py tests/test_assistant_feedback_http.py
git commit -m "feat(feedback): feedback FastAPI app with auth, health and routes"
```

---

## Task 4: 启动脚本

**Files:**
- Create: `scripts/serve_feedback_http.py`

- [ ] **Step 1: Write the script**

```python
"""Launch the product feedback HTTP API (loopback, single worker)."""

from __future__ import annotations

import uvicorn

from drawing_graph.assistant_feedback_http import create_feedback_app
from drawing_graph.config import FeedbackHttpConfig


def main() -> None:
    config = FeedbackHttpConfig.from_env()
    app = create_feedback_app(config)
    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
        workers=1,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify import** — `python -c "import scripts.serve_feedback_http"` → 无错误。

- [ ] **Step 3: Commit**

```bash
git add scripts/serve_feedback_http.py
git commit -m "feat(feedback): feedback HTTP serve script"
```

---

## Task 5: 文档、全量回归与 live 冒烟

**Files:**
- Modify: `README.md`、`docs/acceptance/USER_RUNBOOK.md`、`architecture.md`、`Module.md`

- [ ] **Step 1: Run full regression** — `python -m unittest discover tests -v` → 全量通过。

- [ ] **Step 2: Update docs**

README/RUNBOOK 追加：反馈 API 启动方式（`python scripts\serve_feedback_http.py`，默认 `127.0.0.1:8002`）、`POST /api/v1/drawing-assistant/feedback` 请求/响应示例、环境变量（`FEEDBACK_HTTP_API_TOKEN`/`FEEDBACK_HTTP_DEFAULT_PERMISSIONS`/`FEEDBACK_HTTP_ALLOW_CANDIDATE_REVIEW`）、边界（confirm/correct 不改变 fact_kind；外部持久化 store 未做）。

architecture.md/Module.md 的 08 反馈边界段落同步：外部反馈 HTTP API 已实现，外部持久化 store/Web UI 仍未实现。

- [ ] **Step 3: Live smoke**

```powershell
$env:FEEDBACK_HTTP_API_TOKEN=""; 启动服务后：
curl -s -X POST http://127.0.0.1:8002/api/v1/drawing-assistant/feedback -H "Content-Type: application/json" -d '{"action":"confirm","claim_id":"claim:test"}'
```

期望：`invalid_argument` 或 `claim_not_found`（trace store 无该 claim 时）等稳定错误 envelope，进程不崩溃；如注入 trace 后返回 `ok`。

- [ ] **Step 4: Commit**

```bash
git add README.md docs/acceptance/USER_RUNBOOK.md architecture.md Module.md
git commit -m "docs(feedback): document product feedback HTTP API"
```
