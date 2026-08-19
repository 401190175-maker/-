"""FastAPI application factory for the read-only product drawing assistant API.

模块 import 无副作用：不读取环境变量、不创建 driver/facade/service、
不启动 Uvicorn。runtime 只在应用 lifespan 中创建一次并在关闭时释放一次；
业务路由只能从 ``app.state.assistant_runtime`` 取得 service，不能自行创建
底层资源，也不能直接调用 ``DrawingGraphToolFacade`` 或 ``create_neo4j_tool_facade``。
"""

from __future__ import annotations

import hmac
import json
import queue
import threading
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware

from .assistant_adapter_serialization import (
    ASSISTANT_HTTP_CONTRACT_VERSION,
    AssistantErrorCode,
    answer_package_to_data,
    build_error_envelope,
    build_success_envelope,
    map_exception_to_error,
    sanitize_error_message,
)
from .assistant_http_models import HttpAssistantRequest
from .assistant_http_runtime import AssistantHttpRuntime, create_assistant_http_runtime
from .config import AssistantHttpConfig


ADAPTER = "drawing-assistant-http"
CONTRACT_VERSION = ASSISTANT_HTTP_CONTRACT_VERSION


_ERROR_STATUS_BY_CODE: dict[str, int] = {
    "invalid_argument": 400,
    "read_only_violation": 403,
    "configuration_failed": 500,
    "initialization_failed": 503,
    "assistant_call_failed": 500,
    "timeout": 504,
    "concurrency_limit_reached": 429,
    "request_too_large": 413,
    "unauthorized": 401,
    "forbidden": 403,
    "internal_error": 500,
}


def create_app(
    config: AssistantHttpConfig,
    runtime_factory: Callable[[AssistantHttpConfig], AssistantHttpRuntime] = create_assistant_http_runtime,
) -> FastAPI:
    """Create the FastAPI application without connecting to any backend."""

    async def lifespan(app: FastAPI) -> Any:
        runtime = runtime_factory(config)
        app.state.assistant_runtime = runtime
        app.state.assistant_ready = True
        try:
            yield
        finally:
            app.state.assistant_ready = False
            runtime.close()

    app = FastAPI(
        title="Drawing Assistant HTTP API",
        lifespan=lifespan,
        docs_url="/docs" if config.docs_enabled else None,
        redoc_url="/redoc" if config.docs_enabled else None,
        openapi_url="/openapi.json" if config.docs_enabled else None,
    )
    app.state.assistant_http_config = config
    app.state.assistant_concurrency_semaphore = threading.Semaphore(config.max_concurrent_requests)
    _register_middleware(app, config)
    _register_routes(app)
    _register_exception_handlers(app)
    return app


def _register_middleware(app: FastAPI, config: AssistantHttpConfig) -> None:
    """Install middleware with stable ordering: metadata outermost, auth innermost."""

    app.add_middleware(_AuthenticationMiddleware, api_token=config.api_token)
    if config.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(config.allowed_origins),
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
            allow_credentials=False,
        )
    app.add_middleware(
        _RequestBodySizeLimitMiddleware,
        max_request_bytes=config.max_request_bytes,
    )
    app.add_middleware(_RequestMetadataMiddleware)


def _register_exception_handlers(app: FastAPI) -> None:
    """Convert framework and unclassified errors into the unified sanitized envelope."""

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        if _is_write_back_rejection(exc):
            return _adapter_error_response(
                request.state.request_id,
                403,
                "read_only_violation",
                "write-back is not supported by the read-only product assistant",
                retryable=False,
            )
        details = [
            {"loc": list(error.get("loc", [])), "type": error.get("type")}
            for error in exc.errors()
        ]
        return _adapter_error_response(
            request.state.request_id,
            400,
            "invalid_argument",
            "request validation failed",
            details=details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            code, message, status_code = "invalid_argument", "route not found", 404
        elif exc.status_code == 405:
            code, message, status_code = "invalid_argument", "method not allowed", 405
        else:
            code, message, status_code = "internal_error", "http error", 500
        return _adapter_error_response(request.state.request_id, status_code, code, message)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        return _adapter_error_response(
            request.state.request_id,
            500,
            "internal_error",
            "internal server error",
        )


def _is_write_back_rejection(exc: RequestValidationError) -> bool:
    """Return true when a validation error stems from a forbidden write-back field."""

    for error in exc.errors():
        loc = error.get("loc", ())
        if any(part in ("write_back", "allow_write_back") for part in loc):
            return True
    return False


def get_assistant_service(request: Request) -> Any:
    """Return the product assistant service stored on the application runtime."""

    return request.app.state.assistant_runtime.service


def _register_routes(app: FastAPI) -> None:
    """Register the versioned read-only product assistant routes."""

    @app.get("/health/live")
    def health_live() -> dict[str, str]:
        """Minimal ASGI liveness check that never touches the assistant runtime."""

        return {
            "status": "live",
            "service": ADAPTER,
            "contract_version": CONTRACT_VERSION,
        }

    @app.get("/health/ready")
    def health_ready(request: Request) -> JSONResponse:
        """Report runtime assembly only; never claims live Neo4j verification."""

        request_id = request.state.request_id
        runtime = getattr(request.app.state, "assistant_runtime", None)
        if not getattr(runtime, "ready", False):
            meta = _meta(request_id)
            return JSONResponse(
                status_code=503,
                content=build_error_envelope(
                    "initialization_failed",
                    "assistant runtime is not ready",
                    retryable=True,
                    meta=meta,
                ),
            )
        return JSONResponse(
            status_code=200,
            content={
                "status": "ready",
                "service": ADAPTER,
                "contract_version": CONTRACT_VERSION,
                "neo4j_status": "not_checked",
            },
        )

    @app.post("/api/v1/drawing-assistant/ask")
    def ask(http_request: HttpAssistantRequest, request: Request) -> JSONResponse:
        """Authoritative read-only product assistant entry: validate, convert, answer."""

        request_id = request.state.request_id
        effective_request_id = http_request.request_id or request_id
        assistant_request = http_request.to_assistant_request(effective_request_id)
        return _ask_and_map(request, assistant_request)


def _ask_and_map(request: Request, assistant_request: Any) -> JSONResponse:
    """Run one AssistantRequest through the runtime service and return the response.

    semaphore 由实际执行 ``service.answer()`` 的工作线程获取并在该调用真正
    结束后的 ``finally`` 中释放；容量不足时快速返回 429，不排队、不调用
    service。超时语义由调用方在等待结果时决定，不会提前释放容量。
    """

    request_id = request.state.request_id
    service = get_assistant_service(request)
    semaphore = request.app.state.assistant_concurrency_semaphore
    if not semaphore.acquire(blocking=False):
        return _adapter_error_response(
            request_id,
            429,
            "concurrency_limit_reached",
            "server concurrency limit reached",
            retryable=True,
        )
    result_holder: queue.Queue = queue.Queue(maxsize=1)
    worker = threading.Thread(
        target=_run_answer,
        args=(service, assistant_request, semaphore, result_holder),
        daemon=True,
    )
    worker.start()
    timeout_seconds = request.app.state.assistant_http_config.request_timeout_seconds
    try:
        outcome = result_holder.get(timeout=timeout_seconds)
    except queue.Empty:
        return _adapter_error_response(
            request_id,
            504,
            "timeout",
            "assistant request timed out; the backend call may still be completing",
            retryable=True,
        )
    kind, payload = outcome
    if kind == "package":
        status_code, envelope = map_answer_to_http(payload, request_id)
        return JSONResponse(status_code=status_code, content=envelope)
    if kind == "error":
        status_code, envelope = map_error_to_http(payload, request_id)
        return JSONResponse(status_code=status_code, content=envelope)
    raise payload


def _run_answer(
    service: Any,
    assistant_request: Any,
    semaphore: threading.Semaphore,
    result_holder: queue.Queue,
) -> None:
    """Execute one service.answer() and always release the concurrency capacity."""

    try:
        package = service.answer(assistant_request)
    except Exception as error:  # noqa: BLE001
        result_holder.put(("error", error))
    else:
        result_holder.put(("package", package))
    finally:
        semaphore.release()


def map_answer_to_http(package: Any, request_id: str) -> tuple[int, dict[str, Any]]:
    """Map an ``AnswerPackage`` to HTTP 200 with a stable success envelope.

    所有业务状态（answered/partial/clarification_required/unsupported/
    recognition_failed）都以 200 返回，不重新分类候选/正式或证据层级。
    """

    data = answer_package_to_data(package)
    return 200, build_success_envelope(data, meta=_meta(request_id))


def map_error_to_http(error: BaseException, request_id: str) -> tuple[int, dict[str, Any]]:
    """Map a raised exception to a stable HTTP status and sanitized error envelope."""

    code, retryable = map_exception_to_error(error)
    status_code = _ERROR_STATUS_BY_CODE.get(code, 500)
    message = sanitize_error_message(str(error)) or "assistant request failed"
    return status_code, build_error_envelope(code, message, retryable=retryable, meta=_meta(request_id))


def _meta(request_id: str) -> dict[str, str]:
    return {
        "request_id": request_id,
        "adapter": ADAPTER,
        "contract_version": CONTRACT_VERSION,
    }


class _RequestMetadataMiddleware(BaseHTTPMiddleware):
    """Add a server-generated request ID and security headers to every response."""

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response


class _AuthenticationMiddleware(BaseHTTPMiddleware):
    """Optional constant-time Bearer token authentication.

    ``/health/live`` 始终匿名；配置 token 后，业务路由与 ``/health/ready``
    要求 ``Authorization: Bearer <token>``。token 不进入 URL、DTO、响应、
    request ID 或日志。
    """

    def __init__(self, app: Any, api_token: str):
        super().__init__(app)
        self.api_token = api_token

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        if not self.api_token or request.url.path == "/health/live":
            return await call_next(request)
        request_id = request.state.request_id
        authorization = request.headers.get("Authorization", "")
        if not authorization:
            return _adapter_error_response(
                request_id,
                401,
                "unauthorized",
                "authentication required",
            )
        scheme, _, credentials = authorization.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(credentials, self.api_token):
            return _adapter_error_response(
                request_id,
                401,
                "unauthorized",
                "authentication failed",
            )
        return await call_next(request)


class _RequestBodySizeLimitMiddleware:
    """Pure-ASGI middleware counting actual received body bytes.

    不信任 ``Content-Length``：按 receive 实际收到的字节数累计，超限立即返回
    413，不把完整 body 写入日志或响应，也不进入模型校验和 service。
    """

    def __init__(self, app: Any, max_request_bytes: int):
        self.app = app
        self.max_request_bytes = max_request_bytes

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        received = 0
        exceeded = False
        request_id = scope.get("state", {}).get("request_id", "")
        meta = _meta(request_id)

        async def limited_receive() -> Any:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_request_bytes:
                    exceeded = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        async def send_proxy(message: Any) -> None:
            if message["type"] == "http.response.start" and exceeded:
                envelope = build_error_envelope(
                    "request_too_large",
                    "request body exceeds the configured limit",
                    retryable=False,
                    meta=meta,
                )
                body = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
                await send(
                    {
                        "type": "http.response.start",
                        "status": 413,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode("ascii")),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
            await send(message)

        await self.app(scope, limited_receive, send_proxy)


def _adapter_error_response(
    request_id: str,
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    retryable: bool = False,
) -> JSONResponse:
    """Build an HTTP-adapter error envelope with request metadata."""

    envelope = build_error_envelope(code, message, retryable=retryable, meta=_meta(request_id))
    if details is not None:
        envelope["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=envelope)


__all__ = (
    "ADAPTER",
    "CONTRACT_VERSION",
    "create_app",
    "get_assistant_service",
    "map_answer_to_http",
    "map_error_to_http",
)
