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

from .assistant_adapter_serialization import (
    build_error_envelope,
    build_success_envelope,
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


def _error_response(
    request_id: str,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
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
    runtime_factory: Callable[
        [FeedbackHttpConfig],
        FeedbackHttpRuntime,
    ] = create_feedback_http_runtime,
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
        request_id = getattr(request.state, "request_id", "unknown")
        authorization = request.headers.get("Authorization", "")
        if not authorization:
            return _error_response(
                request_id,
                401,
                "unauthorized",
                "authentication required",
            )
        scheme, _, credentials = authorization.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(
            credentials,
            config.api_token,
        ):
            return _error_response(
                request_id,
                401,
                "unauthorized",
                "authentication failed",
            )
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        del exc
        return _error_response(
            getattr(request.state, "request_id", "unknown"),
            400,
            "invalid_argument",
            "invalid feedback request",
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
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
    def submit_feedback(
        http_request: HttpFeedbackRequest,
        request: Request,
    ) -> JSONResponse:
        runtime: FeedbackHttpRuntime | None = getattr(
            request.app.state,
            "feedback_runtime",
            None,
        )
        request_id = getattr(request.state, "request_id", "unknown")
        if runtime is None:
            return _error_response(
                request_id,
                503,
                "initialization_failed",
                "feedback runtime unavailable",
            )
        result = runtime.submit(http_request)
        status_value = (
            result.status.value if hasattr(result.status, "value") else str(result.status)
        )
        if status_value == FeedbackStatus.FORBIDDEN.value:
            return _error_response(
                request_id,
                403,
                "forbidden",
                "insufficient permission",
            )
        if status_value == FeedbackStatus.INVALID.value:
            return _error_response(
                request_id,
                400,
                "invalid_argument",
                "invalid feedback",
            )
        return JSONResponse(
            content=build_success_envelope(
                data=feedback_result_to_data(result),
                meta={"request_id": request_id},
            )
        )

    return app
