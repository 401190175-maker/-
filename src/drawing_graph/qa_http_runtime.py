"""Process-local HTTP runtime assembling driver, facade, and QA service.

只有本模块（和服务启动脚本）知道 Neo4j driver。runtime 不执行 Cypher、
不调用 repository、不运行导入、增强或候选复核脚本；生产装配仍通过
``create_neo4j_tool_facade(driver)`` 和 ``DrawingGraphQAService(facade)``。
"""

from __future__ import annotations

from typing import Any, Callable

from .config import QAHttpConfig
from .qa_service import DrawingGraphQAService
from .tool_factory import create_neo4j_tool_facade


class QAHttpRuntime:
    """One process-local runtime: driver, facade, service, and ready state.

    ``close()`` 幂等：首次调用关闭 driver 并清理引用，之后重复调用不再
    释放资源，也不向调用方泄露低层关闭异常。
    """

    def __init__(self, config: QAHttpConfig, driver: Any, facade: Any, service: Any):
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


def create_qa_http_runtime(
    config: QAHttpConfig,
    driver_factory: Callable[[str, tuple[str, str]], Any] | None = None,
    facade_factory: Callable[[Any], Any] | None = None,
    service_factory: Callable[[Any], Any] | None = None,
) -> QAHttpRuntime:
    """Create a full runtime with injectable factories.

    默认工厂映射：``neo4j.GraphDatabase.driver`` -> ``create_neo4j_tool_facade``
    -> ``DrawingGraphQAService``。任一环节失败时关闭已创建的 driver 后重新
    抛出原内部异常，交由应用层统一处理。
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
    return QAHttpRuntime(config=config, driver=driver, facade=facade, service=service)


def _default_driver_factory(uri: str, auth: tuple[str, str]) -> Any:
    from neo4j import GraphDatabase

    return GraphDatabase.driver(uri, auth=auth)


_default_facade_factory = create_neo4j_tool_facade
_default_service_factory = DrawingGraphQAService


def _close_quietly(driver: Any) -> None:
    close = getattr(driver, "close", None)
    if close is not None:
        try:
            close()
        except Exception:
            # 低层关闭失败只留在服务端，不进入客户端响应。
            pass


__all__ = ("QAHttpRuntime", "create_qa_http_runtime")
