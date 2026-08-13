"""Prepared-image multimodal provider port and deterministic test fake."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Protocol, runtime_checkable

from .recognition_image_preprocessing import PreparedRecognitionImage
from .recognition_models import RecognitionProviderUsage
from .recognition_prompting import RenderedRecognitionPrompt
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


class FakeProviderFailure(Exception):
    """Deterministic fake provider failure carrying a stable category."""

    def __init__(self, category: str, message: str):
        self.category = category
        super().__init__(message)


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
        raise TypeError("fake provider script items must be mappings or outcome tokens")


def _success_result(payload: Mapping[str, Any]) -> RecognitionClientResult:
    return RecognitionClientResult(
        payload=payload,
        model_name="fake-multimodal",
        model_version="fake-v1",
    )


def _raise_outcome(outcome: str) -> RecognitionClientResult:
    failures = {
        "http_429": ("http_429", "provider is rate limited"),
        "http_5xx": ("http_5xx", "provider returned a temporary server error"),
        "timeout": ("timeout", "provider call timed out"),
        "invalid_json": ("invalid_json", "provider returned malformed JSON"),
        "schema_failure": ("schema_failure", "provider output failed schema validation"),
    }
    try:
        category, message = failures[outcome]
    except KeyError as exc:
        raise ValueError(f"unknown fake provider outcome: {outcome}") from exc
    raise FakeProviderFailure(category, message)


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolModelError("missing_required_field", f"{field_name} must be a non-empty string")
    return value


def _require_optional_text(value: Any, field_name: str) -> None:
    if value is not None:
        _require_text(value, field_name)


__all__ = (
    "FakeMultimodalRecognitionClient",
    "FakeProviderFailure",
    "MultimodalRecognitionClient",
    "RecognitionClientRequest",
    "RecognitionClientResult",
)
