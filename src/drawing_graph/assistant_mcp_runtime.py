"""Process-local MCP runtime assembling driver, facade, and product service.

只有本模块（和服务启动脚本）知道 Neo4j driver。runtime 不执行 Cypher、
不调用 repository、不运行导入、增强或候选复核脚本；生产装配仍通过
``create_neo4j_tool_facade(driver)`` 和 ``create_drawing_assistant_service(facade)``。
模块 import 不读取环境变量、不创建 driver、不连接 Neo4j、不启动 transport，
也不继承或调用 HTTP runtime。
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from .config import AssistantMcpConfig
from .drawing_assistant_factory import create_drawing_assistant_service
from .qa_serialization import sanitize_error_message
from .tool_factory import create_neo4j_tool_facade


logger = logging.getLogger("drawing_graph.assistant_mcp_runtime")


class AssistantMcpRuntime:
    """One process-local MCP runtime: driver, facade, service, and ready state.

    保存一个长生命周期 service，供只读 ``ask_drawing_assistant`` 工具复用；
    driver 只在 runtime 生命周期内创建和持有。
    """

    def __init__(self, config: AssistantMcpConfig, driver: Any, facade: Any, service: Any):
        self.config = config
        self.driver = driver
        self.facade = facade
        self.service = service
        self.ready = True
        self._closed = False

    def close(self) -> None:
        """Idempotently close the driver and mark the runtime not ready."""

        if self._closed:
            return
        self._closed = True
        self.ready = False
        driver, self.driver = self.driver, None
        self.facade = None
        self.service = None
        _close_quietly(driver)


def create_assistant_mcp_runtime(
    config: AssistantMcpConfig,
    driver_factory: Callable[[str, tuple[str, str]], Any] | None = None,
    facade_factory: Callable[[Any], Any] | None = None,
    service_factory: Callable[[Any], Any] | None = None,
) -> AssistantMcpRuntime:
    """Create a full MCP runtime with injectable factories.

    默认工厂映射：``neo4j.GraphDatabase.driver`` -> ``create_neo4j_tool_facade``
    -> ``create_drawing_assistant_service``，按 driver -> facade -> service 顺序
    装配。任一环节失败时关闭已创建的 driver 后重新抛出。测试通过注入 fake
    工厂，不连接真实 Neo4j。
    """

    driver = None
    try:
        driver = (driver_factory or _default_driver_factory)(
            config.neo4j_uri,
            (config.neo4j_user, config.neo4j_password),
        )
        facade = (facade_factory or _default_facade_factory)(driver)
        service = (service_factory or _default_service_factory)(facade)
    except BaseException:
        _close_quietly(driver)
        raise
    return AssistantMcpRuntime(config=config, driver=driver, facade=facade, service=service)


def _default_driver_factory(uri: str, auth: tuple[str, str]) -> Any:
    from neo4j import GraphDatabase

    return GraphDatabase.driver(uri, auth=auth)


_default_facade_factory = create_neo4j_tool_facade
_default_service_factory = create_drawing_assistant_service


def _close_quietly(driver: Any) -> None:
    close = getattr(driver, "close", None)
    if close is None:
        return
    try:
        close()
    except Exception as error:
        logger.error(
            "MCP runtime driver close failed: %s",
            sanitize_error_message(str(error)) or error.__class__.__name__,
        )


__all__ = ("AssistantMcpRuntime", "create_assistant_mcp_runtime")
