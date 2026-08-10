"""FastAPI application factory for the read-only drawing graph QA API.

模块 import 无副作用：不读取环境变量、不创建 driver/facade/QAService、
不启动 Uvicorn。runtime 只在应用 lifespan 中创建一次并在关闭时释放一次；
业务路由只能从 ``app.state.qa_runtime`` 取得 service，不能自行创建底层资源。
"""

from __future__ import annotations

import dataclasses
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
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import QAHttpConfig
from .qa_http_models import HttpQARequest, http_answer_from_qa_answer
from .qa_http_runtime import QAHttpRuntime, create_qa_http_runtime
from .qa_models import QAAnswer, QAAnswerStatus, QAError, QAErrorCode, QARequest, QAScope, QuestionType
from .qa_serialization import build_error_envelope, build_success_envelope, sanitize_error_message


CONTRACT_VERSION = "drawing-qa-http-v1"


def create_app(
    config: QAHttpConfig,
    runtime_factory: Callable[[QAHttpConfig], QAHttpRuntime] = create_qa_http_runtime,
) -> FastAPI:
    """Create the FastAPI application without connecting to any backend.

    ``docs_enabled`` 由配置控制，默认关闭 OpenAPI/docs；lifespan 在应用启动
    时调用 ``runtime_factory(config)`` 一次，在关闭时调用一次 ``close()``。
    """

    async def lifespan(app: FastAPI) -> Any:
        runtime = runtime_factory(config)
        app.state.qa_runtime = runtime
        app.state.qa_ready = True
        try:
            yield
        finally:
            app.state.qa_ready = False
            runtime.close()

    app = FastAPI(
        title="Drawing Graph QA HTTP API",
        lifespan=lifespan,
        docs_url="/docs" if config.docs_enabled else None,
        redoc_url="/redoc" if config.docs_enabled else None,
        openapi_url="/openapi.json" if config.docs_enabled else None,
    )
    app.state.qa_http_config = config
    app.state.qa_concurrency_semaphore = threading.Semaphore(config.max_concurrent_requests)
    _register_middleware(app, config)
    _register_routes(app)
    _register_exception_handlers(app)
    return app


def _register_middleware(app: FastAPI, config: QAHttpConfig) -> None:
    """Install middleware with stable ordering: metadata first, auth inside it."""

    # Starlette 的 add_middleware 使用 insert(0)，最后添加的中间件最外层。
    # 因此按 认证 -> CORS -> metadata 的顺序添加，使 metadata 最外层先写入
    # request ID，CORS 在认证之前处理预检，认证只保护真实业务请求。
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
        details = [
            {"loc": list(error.get("loc", [])), "type": error.get("type")}
            for error in exc.errors()
        ]
        return _adapter_error_response(
            request.state.request_id,
            422,
            "INVALID_ARGUMENT",
            "request validation failed",
            details=details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            category, message, status_code = "ROUTE_NOT_FOUND", "route not found", 404
        elif exc.status_code == 405:
            category, message, status_code = "METHOD_NOT_ALLOWED", "method not allowed", 405
        else:
            category, message, status_code = "HTTP_INTERNAL_ERROR", "http error", 500
        return _adapter_error_response(request.state.request_id, status_code, category, message)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        # 客户端只得到固定脱敏消息；低层 traceback 留在服务端日志。
        return _adapter_error_response(
            request.state.request_id,
            500,
            "HTTP_INTERNAL_ERROR",
            "internal server error",
        )


def get_qa_service(request: Request) -> Any:
    """Return the QAService stored on the application runtime."""

    return request.app.state.qa_runtime.service


def _register_routes(app: FastAPI) -> None:
    """Register the versioned read-only QA routes."""

    @app.get("/health/live")
    def health_live() -> dict[str, str]:
        """Minimal ASGI liveness check that never touches the QA runtime."""

        return {
            "status": "live",
            "service": "drawing-graph-qa-http",
            "contract_version": CONTRACT_VERSION,
        }

    @app.get("/health/ready")
    def health_ready(request: Request) -> JSONResponse:
        """Report runtime assembly only; never claims live Neo4j verification."""

        request_id = request.state.request_id
        runtime = getattr(request.app.state, "qa_runtime", None)
        if not getattr(runtime, "ready", False):
            meta = {"request_id": request_id, "contract_version": CONTRACT_VERSION}
            return JSONResponse(
                status_code=503,
                content=build_error_envelope(
                    "FACADE_UNAVAILABLE",
                    "QA runtime is not ready",
                    retryable=True,
                    meta=meta,
                ),
            )
        return JSONResponse(
            status_code=200,
            content={
                "status": "ready",
                "service": "drawing-graph-qa-http",
                "contract_version": CONTRACT_VERSION,
                "neo4j_status": "not_checked",
            },
        )

    @app.post("/api/v1/drawing-qa/ask")
    def ask(http_request: HttpQARequest, request: Request) -> JSONResponse:
        """Authoritative generic QA entry: validate, convert, ask, map."""

        return _ask_and_map(request, http_request.to_domain())

    @app.get("/api/v1/drawing-qa/pages/{page_id}/summary")
    def page_summary(page_id: str, request: Request, include_semantics: bool = True) -> JSONResponse:
        """Read-only page summary convenience adapter."""

        qa_request = QARequest(
            question_type=QuestionType.PAGE_SUMMARY,
            scope=QAScope(page_id=page_id),
            include_semantics=include_semantics,
            format_hint="json",
        )
        return _ask_and_map(request, qa_request)

    @app.get("/api/v1/drawing-qa/blocks/{block_id}/relations")
    def block_relations(block_id: str, request: Request, include_candidates: bool = True) -> JSONResponse:
        """Read-only block relations convenience adapter."""

        qa_request = QARequest(
            question_type=QuestionType.BLOCK_RELATIONS,
            scope=QAScope(block_id=block_id),
            include_candidates=include_candidates,
            format_hint="json",
        )
        return _ask_and_map(request, qa_request)

    @app.get("/api/v1/drawing-qa/candidates")
    def candidate_relations(
        request: Request,
        page_id: str | None = None,
        block_id: str | None = None,
    ) -> JSONResponse:
        """Read-only candidate relations convenience adapter."""

        qa_request = QARequest(
            question_type=QuestionType.CANDIDATE_RELATIONS,
            scope=QAScope(page_id=page_id, block_id=block_id),
            format_hint="json",
        )
        return _ask_and_map(request, qa_request)

    @app.get("/api/v1/drawing-qa/section-matches")
    def section_matches(
        request: Request,
        cross_section_id: str | None = None,
        page_id: str | None = None,
    ) -> JSONResponse:
        """Read-only section caption match convenience adapter."""

        qa_request = QARequest(
            question_type=QuestionType.SECTION_MATCHES,
            scope=QAScope(cross_section_id=cross_section_id, page_id=page_id),
            format_hint="json",
        )
        return _ask_and_map(request, qa_request)

    @app.get("/api/v1/drawing-qa/table-captions/status")
    def table_caption_status(
        request: Request,
        page_id: str | None = None,
        table_id: str | None = None,
        table_caption_id: str | None = None,
    ) -> JSONResponse:
        """Read-only table caption status convenience adapter."""

        qa_request = QARequest(
            question_type=QuestionType.TABLE_CAPTION_STATUS,
            scope=QAScope(
                page_id=page_id,
                table_id=table_id,
                table_caption_id=table_caption_id,
            ),
            format_hint="json",
        )
        return _ask_and_map(request, qa_request)

    @app.get("/api/v1/drawing-qa/diagnostics")
    def diagnostic_status(
        request: Request,
        page_id: str | None = None,
        block_id: str | None = None,
        include_semantics: bool = True,
        include_candidates: bool = True,
    ) -> JSONResponse:
        """Read-only diagnostic status convenience adapter."""

        qa_request = QARequest(
            question_type=QuestionType.DIAGNOSTIC_STATUS,
            scope=QAScope(page_id=page_id, block_id=block_id),
            include_semantics=include_semantics,
            include_candidates=include_candidates,
            format_hint="json",
        )
        return _ask_and_map(request, qa_request)


def _ask_and_map(request: Request, qa_request: QARequest) -> JSONResponse:
    """Run one QARequest through the runtime service and return the HTTP response.

    semaphore 由实际执行 ``QAService.ask()`` 的工作线程获取并在该调用真正
    结束后的 ``finally`` 中释放；容量不足时快速返回 429，不排队、不调用
    service。超时语义由调用方在等待结果时决定，不会提前释放容量。
    """

    request_id = request.state.request_id
    service = get_qa_service(request)
    semaphore = request.app.state.qa_concurrency_semaphore
    if not semaphore.acquire(blocking=False):
        return _adapter_error_response(
            request_id,
            429,
            "TOO_MANY_REQUESTS",
            "server concurrency limit reached",
        )
    result_holder: queue.Queue = queue.Queue(maxsize=1)
    worker = threading.Thread(
        target=_run_ask,
        args=(service, qa_request, semaphore, result_holder),
        daemon=True,
    )
    worker.start()
    timeout_seconds = request.app.state.qa_http_config.request_timeout_seconds
    try:
        outcome = result_holder.get(timeout=timeout_seconds)
    except queue.Empty:
        # 超时只结束客户端等待；已启动的同步调用继续安全完成，容量由
        # 工作线程在 finally 中释放，不在此处提前释放。
        return _adapter_error_response(
            request_id,
            504,
            "REQUEST_TIMEOUT",
            "QA request timed out; the backend call may still be completing",
        )
    kind, payload = outcome
    if kind == "answer":
        status_code, envelope = map_answer_to_http(payload, request_id)
        return JSONResponse(status_code=status_code, content=envelope)
    if kind == "qa_error":
        status_code, envelope = map_error_to_http(payload, request_id)
        return JSONResponse(status_code=status_code, content=envelope)
    raise payload


def _run_ask(
    service: Any,
    qa_request: QARequest,
    semaphore: threading.Semaphore,
    result_holder: queue.Queue,
) -> None:
    """Execute one service.ask() and always release the concurrency capacity."""

    try:
        answer = service.ask(qa_request)
    except QAError as error:
        result_holder.put(("qa_error", error))
    except Exception as error:
        result_holder.put(("error", error))
    else:
        result_holder.put(("answer", answer))
    finally:
        semaphore.release()


def map_answer_to_http(answer: QAAnswer, request_id: str) -> tuple[int, dict[str, Any]]:
    """Map a structured QAAnswer to an HTTP status and stable envelope.

    ``answered``/``partial`` 返回 200 success data（partial 完整保留 facts、
    warnings 和 unsupported parts）；``not_found``/``unsupported``/``failed``
    转为错误 envelope。映射只解释 answer status，不重新分类候选/正式或
    语义/来源事实。
    """

    meta = {"request_id": request_id, "contract_version": CONTRACT_VERSION}
    if answer.status in (QAAnswerStatus.ANSWERED, QAAnswerStatus.PARTIAL):
        data = http_answer_from_qa_answer(answer).model_dump()
        return 200, build_success_envelope(data, meta=meta)
    if answer.status is QAAnswerStatus.NOT_FOUND:
        return 404, build_error_envelope(
            "NOT_FOUND",
            sanitize_error_message(answer.summary),
            retryable=False,
            meta=meta,
            details=_safe_answer_details(answer),
        )
    if answer.status is QAAnswerStatus.UNSUPPORTED:
        return 422, build_error_envelope(
            "UNSUPPORTED_QUESTION",
            sanitize_error_message(answer.summary),
            retryable=False,
            meta=meta,
            details=_safe_answer_details(answer),
        )
    return 500, build_error_envelope(
        "INTERNAL_ERROR",
        sanitize_error_message(answer.summary),
        retryable=False,
        meta=meta,
        details=_safe_answer_details(answer),
    )


_ERROR_STATUS_AND_RETRYABLE = {
    QAErrorCode.INVALID_ARGUMENT: (422, False),
    QAErrorCode.UNSUPPORTED_QUESTION: (422, False),
    QAErrorCode.UNSUPPORTED_SCOPE: (422, False),
    QAErrorCode.NOT_FOUND: (404, False),
    QAErrorCode.PARTIAL_ANSWER: (422, False),
    QAErrorCode.WRITE_BACK_FORBIDDEN: (403, False),
    QAErrorCode.FACADE_UNAVAILABLE: (503, True),
    QAErrorCode.NEO4J_UNAVAILABLE: (503, True),
    QAErrorCode.SEMANTIC_EVIDENCE_UNAVAILABLE: (503, True),
    QAErrorCode.INTERNAL_ERROR: (500, False),
}


def map_error_to_http(error: QAError, request_id: str) -> tuple[int, dict[str, Any]]:
    """Map a QAError to an HTTP status, category, retryable flag, and sanitized envelope."""

    status_code, retryable = _ERROR_STATUS_AND_RETRYABLE.get(error.category, (500, False))
    meta = {"request_id": request_id, "contract_version": CONTRACT_VERSION}
    return status_code, build_error_envelope(
        error.category.value,
        sanitize_error_message(str(error)),
        retryable=retryable,
        meta=meta,
    )


def _safe_answer_details(answer: QAAnswer) -> dict[str, Any]:
    """Return error details with question type, scope field names, and source calls only."""

    scope_fields = [
        field.name for field in dataclasses.fields(answer.scope) if getattr(answer.scope, field.name) is not None
    ]
    return {
        "question_type": answer.question_type.value,
        "scope_fields": scope_fields,
        "source_calls": list(answer.source_calls),
    }


class _RequestMetadataMiddleware(BaseHTTPMiddleware):
    """Add a server-generated request ID and security headers to every response.

    request ID 由服务端生成并只存放在 ``request.state``，不信任客户端同名
    header，也不写入领域 ``QARequest``/``QAAnswer``。业务响应统一设置
    ``Cache-Control: no-store`` 与 ``X-Content-Type-Options: nosniff``。
    """

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
                "AUTHENTICATION_REQUIRED",
                "authentication required",
            )
        scheme, _, credentials = authorization.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(credentials, self.api_token):
            return _adapter_error_response(
                request_id,
                401,
                "AUTHENTICATION_FAILED",
                "authentication failed",
            )
        return await call_next(request)


class _RequestBodySizeLimitMiddleware:
    """Pure-ASGI middleware counting actual received body bytes.

    不信任 ``Content-Length``：按 receive 实际收到的字节数累计，超限立即返回
    413，不把完整 body 写入日志或响应，也不进入模型校验和 QAService。
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
        meta = {"request_id": request_id, "contract_version": CONTRACT_VERSION}

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
                    "REQUEST_TOO_LARGE",
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
    category: str,
    message: str,
    details: Any = None,
) -> JSONResponse:
    """Build an HTTP-adapter error envelope with request metadata."""

    meta = {"request_id": request_id, "contract_version": CONTRACT_VERSION}
    return JSONResponse(
        status_code=status_code,
        content=build_error_envelope(
            category,
            sanitize_error_message(message),
            retryable=False,
            meta=meta,
            details=details,
        ),
    )


__all__ = (
    "CONTRACT_VERSION",
    "create_app",
    "get_qa_service",
    "map_answer_to_http",
    "map_error_to_http",
)
