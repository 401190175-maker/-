"""Single STDIO MCP process entry for the drawing graph QA adapter.

模块 import 不读取环境变量、不创建 driver、不启动 server、不输出 stdout 或
stderr；只有 ``main()`` 负责加载 ``QAMcpConfig``、创建 runtime 并装配
tools/server。脚本不接受 host、port、worker、HTTP token 或远程 transport
参数；真实 STDIO 协议运行在后续 Task 中加入。
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


def main(
    config_loader: Callable[[], QAMcpConfig] = QAMcpConfig.from_env,
    runtime_factory: Callable[[QAMcpConfig], QAMcpRuntime] = create_qa_mcp_runtime,
    tools_factory: Callable[[Any], DrawingGraphMCPTools] = DrawingGraphMCPTools,
    server_factory: Callable[[DrawingGraphMCPTools], Any] = create_mcp_server,
) -> int:
    """Load MCP config, assemble runtime/tools/server, then exit cleanly.

    生产依赖全部可注入 fake，单元测试不需要连接真实 Neo4j。启动或装配失败
    时输出脱敏 stderr 并返回非零退出码；已创建的 runtime 在失败路径关闭。
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
    runtime.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
