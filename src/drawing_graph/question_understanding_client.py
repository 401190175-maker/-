"""Constrained HTTP question-understanding client (rule fallback enhancement)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .assistant_models import AssistantScope
from .assistant_question_llm import (
    QuestionUnderstandingCandidate,
    QuestionUnderstandingModelClient,
    validate_model_output,
)


@dataclass(frozen=True)
class QuestionUnderstandingClientConfig:
    model: str = "qwen3-vl-plus"
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    timeout_seconds: float = 60.0
    api_key: str = ""


_PROMPT = (
    "你是图纸问答意图分类器。只从以下类型中选择一个 question_type："
    "page_summary, block_relations, block_semantic_identification, "
    "element_text_or_meaning, candidate_relations, section_matches, "
    "table_caption_status, drawing_diagnostic, source_trace, comparison, "
    "page_content_search, unknown_or_unsupported。"
    "只输出 JSON：{\"question_type\": ..., \"confidence\": 0..1, "
    "\"ambiguities\": [...], \"unsupported_parts\": [...]}。"
    "不得输出任何事实、查询语句或写回授权。"
)


class HttpQuestionUnderstandingClient(QuestionUnderstandingModelClient):
    """Call an OpenAI-compatible chat endpoint and validate the candidate."""

    def __init__(
        self,
        config: QuestionUnderstandingClientConfig,
        http_post: Callable[..., tuple[int, str]] | None = None,
    ) -> None:
        self._config = config
        self._http_post = http_post or self._default_post

    def understand(
        self,
        question: str,
        scope: AssistantScope | None = None,
    ) -> QuestionUnderstandingCandidate:
        del scope
        messages = [
            {"role": "system", "content": _PROMPT},
            {"role": "user", "content": question},
        ]
        status, body = self._http_post(
            f"{self._config.base_url.rstrip('/')}/chat/completions",
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._config.api_key}",
            },
            {
                "model": self._config.model,
                "messages": messages,
                "temperature": 0.0,
                "response_format": {"type": "json_object"},
            },
            self._config.timeout_seconds,
        )
        if status != 200:
            raise RuntimeError(f"question understanding HTTP {status}")
        content = json.loads(body)["choices"][0]["message"]["content"]
        raw: Mapping[str, object] = json.loads(content)
        validation = validate_model_output(raw)
        if validation.candidate is None:
            raise RuntimeError(
                "question understanding model output invalid: "
                + ",".join(validation.reason_codes)
            )
        return validation.candidate

    @staticmethod
    def _default_post(
        url: str,
        headers: dict[str, str],
        body: dict[str, object],
        timeout: float,
    ) -> tuple[int, str]:
        import requests

        response = requests.post(url, headers=headers, json=body, timeout=timeout)
        return response.status_code, response.text


def question_understanding_client_from_env() -> HttpQuestionUnderstandingClient | None:
    """Build the HTTP client from environment when an API key is present."""

    import os

    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        return None
    return HttpQuestionUnderstandingClient(
        QuestionUnderstandingClientConfig(
            model=os.environ.get("DRAWING_GRAPH_QWEN_MODEL", "qwen3-vl-plus").strip(),
            base_url=os.environ.get(
                "DRAWING_GRAPH_QWEN_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ).strip(),
            timeout_seconds=float(
                os.environ.get("DRAWING_GRAPH_QWEN_TIMEOUT_SECONDS", "60.0")
            ),
            api_key=api_key,
        )
    )
