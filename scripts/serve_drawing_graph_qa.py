"""Single-worker Uvicorn entry for the drawing graph QA HTTP API.

模块 import 不读取环境变量、不创建 driver、不启动 server；所有配置只来自
环境变量（``QAHttpConfig.from_env()``），不接受密码、token 或 API key 作为
命令行参数。启动摘要只输出 host、port、contract version、docs 与认证开关。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from drawing_graph.config import QAHttpConfig
from drawing_graph.qa_http import CONTRACT_VERSION, create_app
from drawing_graph.qa_serialization import sanitize_error_message


def main(
    config_loader: Callable[[], QAHttpConfig] = QAHttpConfig.from_env,
    runner: Callable[..., Any] | None = None,
) -> int:
    """Load HTTP config, build the app, and run Uvicorn with a single worker."""

    try:
        config = config_loader()
        app = create_app(config)
    except Exception as error:
        print("startup failed: " + sanitize_error_message(str(error)), file=sys.stderr)
        return 2

    if runner is None:
        import uvicorn

        runner = uvicorn.run
    print(
        f"starting drawing-graph-qa-http on {config.host}:{config.port} "
        f"contract={CONTRACT_VERSION} docs={'on' if config.docs_enabled else 'off'} "
        f"auth={'on' if config.api_token else 'off'}"
    )
    runner(app, host=config.host, port=config.port, workers=1, log_level=config.log_level.lower())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
