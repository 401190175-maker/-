"""Process-local MCP runtime assembling driver, facade, and QA service.

只有本模块（和服务启动脚本）知道 Neo4j driver。runtime 不执行 Cypher、
不调用 repository、不运行导入、增强或候选复核脚本；生产装配仍通过
``create_neo4j_tool_facade(driver)`` 和 ``DrawingGraphQAService(facade)``。
模块 import 不读取环境变量、不创建 driver、不连接 Neo4j、不启动 transport，
也不继承或调用 HTTP runtime。
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from .config import QAMcpConfig
from .qa_service import DrawingGraphQAService
from .qa_serialization import sanitize_error_message
from .tool_factory import create_neo4j_tool_facade


logger = logging.getLogger("drawing_graph.qa_mcp_runtime")


class QAMcpRuntime:
    """One process-local MCP runtime: driver, facade, service, and ready state.

    保存一个长生命周期 service，供所有六个 MCP 工具复用；driver 只在
    runtime 生命周期内创建和持有。
    """

    def __init__(self, config: QAMcpConfig, driver: Any, facade: Any, service: Any):
        self.config = config
        self.driver = driver
        self.facade = facade
        self.service = service
        self.ready = True
        self._closed = False

    def close(self) -> None:
        """Idempotently close the driver and mark the runtime not ready.

        首次调用关闭 driver 并清理引用；重复调用不再释放资源。driver 关闭
        失败只记录脱敏诊断，不向调用方抛出连接信息。
        """

        if self._closed:
            return
        self._closed = True
        self.ready = False
        driver, self.driver = self.driver, None
        self.facade = None
        self.service = None
        _close_quietly(driver)


def create_qa_mcp_runtime(
    config: QAMcpConfig,
    driver_factory: Callable[[str, tuple[str, str]], Any] | None = None,
    facade_factory: Callable[[Any], Any] | None = None,
    service_factory: Callable[[Any], Any] | None = None,
) -> QAMcpRuntime:
    """Create a full MCP runtime with injectable factories.

    默认工厂映射：``neo4j.GraphDatabase.driver`` -> ``create_neo4j_tool_facade``
    -> ``DrawingGraphQAService``，按 driver -> facade -> service 顺序装配。
    测试通过注入 fake 工厂，不连接真实 Neo4j。
    """

    driver = (driver_factory or _default_driver_factory)(
        config.neo4j_uri,
        (config.neo4j_user, config.neo4j_password),
    )
    try:
        facade = (facade_factory or _default_facade_factory)(driver)
        service = (service_factory or _default_service_factory)(facade)
    except BaseException:
        _close_quietly(driver)
        raise
    return QAMcpRuntime(config=config, driver=driver, facade=facade, service=service)


def _default_driver_factory(uri: str, auth: tuple[str, str]) -> Any:
    from neo4j import GraphDatabase

    return GraphDatabase.driver(uri, auth=auth)


_default_facade_factory = create_neo4j_tool_facade
_default_service_factory = DrawingGraphQAService


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


__all__ = ("QAMcpRuntime", "create_qa_mcp_runtime")
