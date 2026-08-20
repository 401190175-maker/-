"""Launch the product feedback HTTP API (loopback, single worker)."""

from __future__ import annotations

import uvicorn

from drawing_graph.assistant_feedback_http import create_feedback_app
from drawing_graph.config import FeedbackHttpConfig


def main() -> None:
    config = FeedbackHttpConfig.from_env()
    app = create_feedback_app(config)
    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
        workers=1,
    )


if __name__ == "__main__":
    main()
