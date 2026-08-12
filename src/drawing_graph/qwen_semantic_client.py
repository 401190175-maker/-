"""Qwen multimodal recognition client using DashScope's OpenAI-compatible API."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import httpx

from .semantic_client import RecognitionClientRequest, RecognitionClientResult
from .tool_models import ToolModelError


DEFAULT_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_QWEN_MODEL = "qwen3-vl-plus"


@dataclass(frozen=True)
class QwenRecognitionConfig:
    """Runtime settings for the Qwen recognition client.

    The API key stays inside this provider config and is excluded from repr so
    it cannot leak through ordinary debug output.
    """

    api_key: str = field(repr=False)
    model: str = DEFAULT_QWEN_MODEL
    base_url: str = DEFAULT_QWEN_BASE_URL
    timeout_seconds: float = 60.0

    @classmethod
    def from_env(
        cls,
        *,
        model: str = DEFAULT_QWEN_MODEL,
        base_url: str = DEFAULT_QWEN_BASE_URL,
        timeout_seconds: float = 60.0,
    ) -> "QwenRecognitionConfig":
        """Create Qwen config from the process environment without printing it."""

        return cls(
            api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
            model=model,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )

    def __post_init__(self) -> None:
        _require_text(self.api_key, "DASHSCOPE_API_KEY")
        _require_text(self.model, "qwen_model")
        _require_text(self.base_url, "qwen_base_url")
        if not isinstance(self.timeout_seconds, (int, float)) or isinstance(self.timeout_seconds, bool):
            raise ToolModelError("invalid_timeout", "qwen_timeout_seconds must be numeric")
        if self.timeout_seconds <= 0:
            raise ToolModelError("invalid_timeout", "qwen_timeout_seconds must be positive")


class QwenMultimodalRecognitionClient:
    """Multimodal recognition client backed by Qwen-VL compatible chat completions."""

    def __init__(self, config: QwenRecognitionConfig, http_client: httpx.Client | None = None):
        self.config = config
        self.http_client = http_client or httpx.Client(timeout=config.timeout_seconds)
        self.model_name = config.model
        self.model_version = config.model

    def recognize(self, request: RecognitionClientRequest) -> RecognitionClientResult:
        """Call Qwen and return the existing semantic recognition result DTO."""

        payload = self._build_payload(request)
        try:
            response = self.http_client.post(
                _chat_completions_url(self.config.base_url),
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.config.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise ToolModelError("RECOGNITION_FAILED", "recognition client timed out") from exc
        except httpx.HTTPError as exc:
            raise ToolModelError("RECOGNITION_FAILED", "recognition provider request failed") from exc
        if response.status_code >= 400:
            raise ToolModelError("RECOGNITION_FAILED", "recognition provider returned an error")
        try:
            provider_payload = response.json()
            content = _extract_message_content(provider_payload)
            parsed = _parse_structured_content(content)
            status = str(parsed.get("status", "succeeded"))
            observations = _read_mapping_sequence(parsed.get("observations", ()), "observations")
            interpretations = _read_mapping_sequence(parsed.get("interpretations", ()), "interpretations")
        except (KeyError, TypeError, ValueError, ToolModelError) as exc:
            raise ToolModelError("RECOGNITION_FAILED", "recognition client returned unparseable output") from exc
        return RecognitionClientResult(
            status=status,
            observations=observations,
            interpretations=interpretations,
            error_code=parsed.get("error_code"),
            error_message=parsed.get("error_message"),
            model_name=str(provider_payload.get("model") or self.config.model),
            model_version=str(parsed.get("model_version") or provider_payload.get("model") or self.config.model),
        )

    def _build_payload(self, request: RecognitionClientRequest) -> Mapping[str, Any]:
        image_url = _image_data_url(request.image_path)
        target_lines = [
            (
                f"- id={target_id}; type={target_type}; "
                f"bbox=({bbox.x_min},{bbox.y_min},{bbox.x_max},{bbox.y_max}); "
                f"normalized_bbox=({normalized.x_min},{normalized.y_min},{normalized.x_max},{normalized.y_max})"
            )
            for target_id, target_type, bbox, normalized in request.targets
        ]
        # Keep the schema in the prompt explicit so provider output can be
        # validated by the existing semantic service without provider-specific DTOs.
        user_text = "\n".join(
            (
                "Recognize the requested drawing elements from this page image.",
                f"page_id: {request.page_id}",
                f"prompt_version: {request.prompt_version}",
                "Return only JSON with keys: status, observations, interpretations, model_version.",
                "Each observation must include target_element_id, target_element_type, raw_text, normalized_text, confidence, status.",
                "Targets:",
                *(target_lines or ["- no explicit targets"]),
            )
        )
        return {
            "model": self.config.model,
            "messages": (
                {
                    "role": "system",
                    "content": "You are a construction drawing multimodal recognition engine. Return strict JSON only.",
                },
                {
                    "role": "user",
                    "content": (
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ),
                },
            ),
            "temperature": 0,
        }


def _chat_completions_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/chat/completions"


def _image_data_url(image_path: str) -> str:
    path = Path(image_path)
    try:
        payload = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError as exc:
        raise ToolModelError("RECOGNITION_FAILED", "recognition image is not readable") from exc
    return f"data:{_mime_type(path)};base64,{payload}"


def _mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


def _extract_message_content(provider_payload: Mapping[str, Any]) -> str:
    choices = provider_payload["choices"]
    message = choices[0]["message"]
    content = message["content"]
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(item.get("text", "")) for item in content if isinstance(item, Mapping))
    raise ToolModelError("RECOGNITION_FAILED", "recognition content has an unsupported shape")


def _parse_structured_content(content: str) -> Mapping[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    parsed = json.loads(stripped)
    if not isinstance(parsed, Mapping):
        raise ToolModelError("RECOGNITION_FAILED", "recognition content must be a JSON object")
    return parsed


def _read_mapping_sequence(value: Any, field_name: str) -> tuple[Mapping[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ToolModelError("RECOGNITION_FAILED", f"{field_name} must be a sequence")
    if not all(isinstance(item, Mapping) for item in value):
        raise ToolModelError("RECOGNITION_FAILED", f"{field_name} must contain objects")
    return tuple(dict(item) for item in value)


def _require_text(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ToolModelError("missing_required_field", f"{field_name} must be a non-empty string")


__all__ = (
    "DEFAULT_QWEN_BASE_URL",
    "DEFAULT_QWEN_MODEL",
    "QwenMultimodalRecognitionClient",
    "QwenRecognitionConfig",
)
