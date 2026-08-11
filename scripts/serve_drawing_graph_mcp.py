"""Single STDIO MCP process entry for the drawing graph QA adapter.

模块 import 不读取环境变量、不创建 driver、不启动 server、不输出 stdout 或
stderr；只有 ``main()`` 负责加载 ``QAMcpConfig``、创建 runtime 并装配
tools/server，然后运行官方 STDIO transport。脚本不接受 host、port、worker、
HTTP token 或远程 transport 参数；stdout 只承载 MCP 协议帧。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from drawing_graph.config import QAMcpConfig
from drawing_graph.qa_mcp_runtime import QAMcpRuntime, create_qa_mcp_runtime
from drawing_graph.qa_mcp_server import create_mcp_server
from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools
from drawing_graph.qa_serialization import sanitize_error_message


MCP_SERVER_VERSION = "1.0.0"


def main(
    config_loader: Callable[[], QAMcpConfig] = QAMcpConfig.from_env,
    runtime_factory: Callable[[QAMcpConfig], QAMcpRuntime] = create_qa_mcp_runtime,
    tools_factory: Callable[[Any], DrawingGraphMCPTools] = DrawingGraphMCPTools,
    server_factory: Callable[[DrawingGraphMCPTools], Any] = create_mcp_server,
    transport_runner: Callable[[Any], Any] | None = None,
) -> int:
    """Load MCP config, assemble runtime/tools/server, then run STDIO.

    生产依赖全部可注入 fake，单元测试不需要连接真实 Neo4j。启动或装配失败
    时输出脱敏 stderr 并返回非零退出码；协议正常结束后 runtime 恰好关闭一次。
    """

    try:
        config = config_loader()
        runtime = runtime_factory(config)
    except Exception as error:
        message = sanitize_error_message(str(error)) or error.__class__.__name__
        print("startup failed: " + message, file=sys.stderr)
        return 2
    try:
        tools = tools_factory(runtime.service)
        server = server_factory(tools)
    except Exception as error:
        runtime.close()
        message = sanitize_error_message(str(error)) or error.__class__.__name__
        print("startup failed: " + message, file=sys.stderr)
        return 2
    runner = transport_runner or _run_stdio_transport
    exit_code = 0
    try:
        runner(server)
    except Exception as error:
        exit_code = 3
        message = sanitize_error_message(str(error)) or error.__class__.__name__
        print("transport failed: " + message, file=sys.stderr)
    try:
        runtime.close()
    except Exception as error:
        if exit_code == 0:
            exit_code = 4
        message = sanitize_error_message(str(error)) or error.__class__.__name__
        print("close failed: " + message, file=sys.stderr)
    return exit_code


def _run_stdio_transport(server: Any) -> None:
    """Run the official MCP STDIO transport until the client closes it.

    只在调用时导入 SDK transport 模块，保持模块 import 无副作用。stdout 只
    写协议帧，诊断日志由 SDK 写入 stderr；不启动 Uvicorn、HTTP socket 或
    后台 worker。
    """

    import asyncio

    from mcp.server.lowlevel import NotificationOptions
    from mcp.server.models import InitializationOptions
    from mcp.server.stdio import stdio_server

    async def _serve() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name=server.name,
                    server_version=MCP_SERVER_VERSION,
                    capabilities=server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )

    asyncio.run(_serve())


if __name__ == "__main__":
    raise SystemExit(main())
