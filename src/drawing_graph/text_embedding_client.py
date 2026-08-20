"""Constrained text-embedding client (DashScope-compatible HTTP)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Sequence


@dataclass(frozen=True)
class EmbeddingClientConfig:
    model: str = "text-embedding-v3"
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    timeout_seconds: float = 60.0
    api_key: str = ""


class TextEmbeddingClient:
    """Embedding client protocol: embed texts into fixed-size vectors."""

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        raise NotImplementedError


class HttpTextEmbeddingClient(TextEmbeddingClient):
    def __init__(
        self,
        config: EmbeddingClientConfig,
        http_post: Callable[..., tuple[int, str]] | None = None,
    ) -> None:
        self._config = config
        self._http_post = http_post or self._default_post

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        status, body = self._http_post(
            f"{self._config.base_url.rstrip('/')}/embeddings",
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._config.api_key}",
            },
            {
                "model": self._config.model,
                "input": list(texts),
            },
            self._config.timeout_seconds,
        )
        if status != 200:
            raise RuntimeError(f"text embedding HTTP {status}")
        payload = json.loads(body)
        items = sorted(payload["data"], key=lambda item: item["index"])
        return [list(item["embedding"]) for item in items]

    @staticmethod
    def _default_post(url, headers, body, timeout):
        import requests

        response = requests.post(url, headers=headers, json=body, timeout=timeout)
        return response.status_code, response.text


def text_embedding_client_from_env() -> HttpTextEmbeddingClient | None:
    """Build the embedding client from environment when an API key is present."""

    import os

    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        return None
    return HttpTextEmbeddingClient(
        EmbeddingClientConfig(
            model=os.environ.get(
                "DRAWING_GRAPH_EMBEDDING_MODEL",
                "text-embedding-v3",
            ).strip(),
            base_url=os.environ.get(
                "DRAWING_GRAPH_EMBEDDING_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ).strip(),
            timeout_seconds=float(
                os.environ.get("DRAWING_GRAPH_EMBEDDING_TIMEOUT_SECONDS", "60.0")
            ),
            api_key=api_key,
        )
    )
