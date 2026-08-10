"""FastAPI application factory for the read-only drawing graph QA API.

模块 import 无副作用：不读取环境变量、不创建 driver/facade/QAService、
不启动 Uvicorn。runtime 只在应用 lifespan 中创建一次并在关闭时释放一次；
业务路由只能从 ``app.state.qa_runtime`` 取得 service，不能自行创建底层资源。
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request

from .config import QAHttpConfig
from .qa_http_runtime import QAHttpRuntime, create_qa_http_runtime


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
    return app


def get_qa_service(request: Request) -> Any:
    """Return the QAService stored on the application runtime."""

    return request.app.state.qa_runtime.service


__all__ = ("create_app", "get_qa_service")
