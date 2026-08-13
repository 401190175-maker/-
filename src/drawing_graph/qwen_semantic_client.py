"""Qwen/DashScope provider adapter for prepared-image recognition calls."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import urlsplit

import httpx

from .recognition_image_preprocessing import PreparedRecognitionImage
from .recognition_models import RecognitionProviderUsage, UsageStatus
from .recognition_retry import RecognitionProviderError, classify_exception, classify_http_status
from .semantic_client import RecognitionClientRequest, RecognitionClientResult
from .tool_models import ToolModelError


DEFAULT_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_QWEN_MODEL = "qwen3-vl-plus"


@dataclass(frozen=True)
class QwenRecognitionConfig:
    """Runtime settings for the Qwen provider adapter.

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
    """Prepared-image provider adapter for DashScope chat completions."""

    def __init__(self, config: QwenRecognitionConfig, http_client: httpx.Client | None = None):
        self.config = config
        self.http_client = http_client or httpx.Client(timeout=config.timeout_seconds)
        self.model_name = config.model
        self.model_version = config.model

    def recognize(self, request: RecognitionClientRequest) -> RecognitionClientResult:
        """Call Qwen with prepared images and return the adapted provider result."""

        _validate_base_url(self.config.base_url)
        payload = self._build_payload(request)
        try:
            response = self.http_client.post(
                _chat_completions_url(self.config.base_url),
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=request.timeout_seconds,
                follow_redirects=True,
            )
        except httpx.TimeoutException as exc:
            raise classify_exception(exc) from exc
        except httpx.HTTPError as exc:
            raise classify_exception(exc) from exc
        _reject_insecure_response_url(response)
        if response.status_code >= 400:
            raise classify_http_status(
                response.status_code,
                retry_after_header=response.headers.get("Retry-After"),
            )
        try:
            provider_payload = response.json()
            content = _extract_message_content(provider_payload)
            parsed = _parse_structured_content(content)
            model_name = str(provider_payload.get("model") or self.config.model)
            request_id = provider_payload.get("id")
            usage = _parse_usage(provider_payload.get("usage"))
        except (KeyError, TypeError, ValueError, ToolModelError) as exc:
            raise RecognitionProviderError(
                category="invalid_response",
                retryable=False,
                safe_message="recognition client returned unparseable output",
            ) from exc
        return RecognitionClientResult(
            payload=parsed,
            provider_request_id=str(request_id) if request_id is not None else None,
            model_name=model_name,
            model_version=model_name,
            usage=usage,
        )

    def _build_payload(self, request: RecognitionClientRequest) -> Mapping[str, Any]:
        content_parts = [
            {"type": "text", "text": request.rendered_prompt.user_instruction},
        ]
        content_parts.extend(
            {"type": "image_url", "image_url": {"url": _image_data_url(image)}}
            for image in request.prepared_images
        )
        return {
            "model": self.config.model,
            "messages": (
                {
                    "role": "system",
                    "content": request.rendered_prompt.system_instruction,
                },
                {
                    "role": "user",
                    "content": tuple(content_parts),
                },
            ),
            "temperature": 0,
        }


def _chat_completions_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/chat/completions"


def _image_data_url(image: PreparedRecognitionImage) -> str:
    payload = base64.b64encode(image.content).decode("ascii")
    return f"data:{image.mime};base64,{payload}"


def _validate_base_url(base_url: str) -> None:
    parsed = urlsplit(base_url)
    if parsed.username is not None or parsed.password is not None:
        raise ToolModelError("INVALID_ARGUMENT", "provider base URL must not embed credentials")
    host = parsed.hostname
    if not host:
        raise ToolModelError("INVALID_ARGUMENT", "provider base URL must include a host")
    if parsed.scheme != "https" and not _is_loopback(host):
        raise ToolModelError("INVALID_ARGUMENT", "provider base URL must use HTTPS outside loopback")


def _reject_insecure_response_url(response: httpx.Response) -> None:
    host = response.url.host or ""
    if response.url.scheme != "https" and not _is_loopback(host):
        raise RecognitionProviderError(
            category="permanent",
            retryable=False,
            safe_message="provider redirected to a non-HTTPS endpoint",
        )


def _is_loopback(host: str) -> bool:
    lowered = host.strip().lower().rstrip(".")
    return lowered in {"localhost", "127.0.0.1", "::1"} or lowered.startswith("127.")


def _parse_usage(usage: Any) -> RecognitionProviderUsage:
    if not isinstance(usage, Mapping):
        return RecognitionProviderUsage(status=UsageStatus.UNAVAILABLE)
    input_tokens = usage.get("prompt_tokens")
    output_tokens = usage.get("completion_tokens")
    image_units = usage.get("image_units")
    if input_tokens is None and output_tokens is None:
        return RecognitionProviderUsage(status=UsageStatus.UNAVAILABLE)
    return RecognitionProviderUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        image_units=image_units,
        status=UsageStatus.AVAILABLE,
    )


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


def _require_text(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ToolModelError("missing_required_field", f"{field_name} must be a non-empty string")


__all__ = (
    "DEFAULT_QWEN_BASE_URL",
    "DEFAULT_QWEN_MODEL",
    "QwenMultimodalRecognitionClient",
    "QwenRecognitionConfig",
)
