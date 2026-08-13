"""Prepared-image multimodal provider port and deterministic test fake."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Protocol, runtime_checkable

from .recognition_image_preprocessing import PreparedRecognitionImage
from .recognition_models import RecognitionProviderUsage
from .recognition_prompting import RenderedRecognitionPrompt
from .recognition_retry import RecognitionProviderError
from .tool_models import ToolModelError


@dataclass(frozen=True)
class RecognitionClientRequest:
    """Provider input projection for exactly one provider call.

    The request carries only the model profile, the already rendered prompt,
    in-memory prepared images, the output contract version, a single-call
    timeout and a stable request fingerprint. It never carries image paths,
    page context, credentials, headers or arbitrary provider bodies.
    """

    model_profile: str
    rendered_prompt: RenderedRecognitionPrompt
    prepared_images: tuple[PreparedRecognitionImage, ...]
    output_contract_version: str
    request_fingerprint: str
    timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        for field_name in ("model_profile", "output_contract_version", "request_fingerprint"):
            _require_text(getattr(self, field_name), field_name)
        if not isinstance(self.rendered_prompt, RenderedRecognitionPrompt):
            raise ToolModelError("invalid_prompt", "rendered_prompt must be a RenderedRecognitionPrompt")
        if (
            not isinstance(self.prepared_images, tuple)
            or not self.prepared_images
            or not all(isinstance(image, PreparedRecognitionImage) for image in self.prepared_images)
        ):
            raise ToolModelError(
                "invalid_images",
                "prepared_images must be a non-empty tuple of PreparedRecognitionImage",
            )
        if (
            not isinstance(self.timeout_seconds, (int, float))
            or isinstance(self.timeout_seconds, bool)
            or self.timeout_seconds <= 0
        ):
            raise ToolModelError("invalid_timeout", "timeout_seconds must be a positive number")


@dataclass(frozen=True)
class RecognitionClientResult:
    """Provider result projection with no headers, bodies or secrets."""

    payload: Mapping[str, Any]
    provider_request_id: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    usage: RecognitionProviderUsage | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.payload, Mapping):
            raise ToolModelError("invalid_payload", "payload must be a mapping")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        for field_name in ("provider_request_id", "model_name", "model_version"):
            _require_optional_text(getattr(self, field_name), field_name)
        if self.usage is not None and not isinstance(self.usage, RecognitionProviderUsage):
            raise ToolModelError("invalid_usage", "usage must be a RecognitionProviderUsage or None")


@runtime_checkable
class MultimodalRecognitionClient(Protocol):
    """Protocol for one prepared-image provider call."""

    def recognize(self, request: RecognitionClientRequest) -> RecognitionClientResult:
        """Return the adapted provider payload for one call."""


class FakeMultimodalRecognitionClient:
    """Scriptable fake that simulates success, HTTP/timeout and parse failures."""

    def __init__(self, script: tuple[object, ...] = ()):
        self._script = tuple(script)
        self._cursor = 0
        self.requests: list[RecognitionClientRequest] = []

    def recognize(self, request: RecognitionClientRequest) -> RecognitionClientResult:
        """Consume one scripted outcome and record the request."""

        if not isinstance(request, RecognitionClientRequest):
            raise TypeError("request must be a RecognitionClientRequest")
        self.requests.append(request)
        if not self._script:
            return _success_result({})
        outcome = self._script[min(self._cursor, len(self._script) - 1)]
        self._cursor += 1
        if isinstance(outcome, Mapping):
            return _success_result(dict(outcome))
        if isinstance(outcome, str):
            return _raise_outcome(outcome)
        if isinstance(outcome, tuple) and len(outcome) == 2 and isinstance(outcome[0], str):
            return _raise_outcome(outcome[0], outcome[1])
        raise TypeError("fake provider script items must be mappings or outcome tokens")


def _success_result(payload: Mapping[str, Any]) -> RecognitionClientResult:
    return RecognitionClientResult(
        payload=payload,
        model_name="fake-multimodal",
        model_version="fake-v1",
    )


def _raise_outcome(outcome: str, retry_after: Any = None) -> RecognitionClientResult:
    if outcome == "http_429":
        raise RecognitionProviderError(
            category="rate_limited",
            retryable=True,
            safe_message="provider is rate limited",
            retry_after_seconds=retry_after,
        )
    if outcome == "http_401":
        raise RecognitionProviderError(
            category="authentication",
            retryable=False,
            safe_message="provider authentication failed",
        )
    if outcome == "http_5xx":
        raise RecognitionProviderError(
            category="temporary",
            retryable=True,
            safe_message="provider returned a temporary server error",
        )
    if outcome == "timeout":
        raise RecognitionProviderError(
            category="timeout",
            retryable=True,
            safe_message="provider call timed out",
        )
    if outcome in {"invalid_json", "schema_failure"}:
        raise RecognitionProviderError(
            category="invalid_response",
            retryable=False,
            safe_message="provider returned an invalid response",
        )
    raise ValueError(f"unknown fake provider outcome: {outcome}")


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolModelError("missing_required_field", f"{field_name} must be a non-empty string")
    return value


def _require_optional_text(value: Any, field_name: str) -> None:
    if value is not None:
        _require_text(value, field_name)


__all__ = (
    "FakeMultimodalRecognitionClient",
    "MultimodalRecognitionClient",
    "RecognitionClientRequest",
    "RecognitionClientResult",
)
