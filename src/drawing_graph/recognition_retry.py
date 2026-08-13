"""Provider error classification and bounded retry execution for the 04 layer."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import httpx

from .recognition_models import ProviderErrorCategory
from .tool_models import ToolModelError


_MAX_RETRY_AFTER_SECONDS = 120.0


@dataclass(frozen=True)
class RecognitionProviderError(Exception):
    """Safe provider error carrying only classification and summary fields."""

    category: ProviderErrorCategory | str
    retryable: bool
    safe_message: str
    retry_after_seconds: float | None = None

    def __post_init__(self) -> None:
        try:
            category = (
                self.category
                if isinstance(self.category, ProviderErrorCategory)
                else ProviderErrorCategory(self.category)
            )
        except ValueError as exc:
            raise ToolModelError("invalid_provider_error", "unsupported provider error category") from exc
        object.__setattr__(self, "category", category)
        if not isinstance(self.retryable, bool):
            raise ToolModelError("invalid_provider_error", "retryable must be a boolean")
        if not isinstance(self.safe_message, str) or not self.safe_message.strip():
            raise ToolModelError("invalid_provider_error", "safe_message must be a non-empty string")
        if self.retry_after_seconds is not None and (
            not isinstance(self.retry_after_seconds, (int, float))
            or isinstance(self.retry_after_seconds, bool)
            or self.retry_after_seconds <= 0
        ):
            raise ToolModelError("invalid_provider_error", "retry_after_seconds must be positive or None")

    def __str__(self) -> str:
        return self.safe_message


def parse_retry_after(value: Any, *, cap_seconds: float = _MAX_RETRY_AFTER_SECONDS) -> float | None:
    """Parse a bounded Retry-After value; return None when invalid or too large."""

    if value is None:
        return None
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed <= 0 or parsed > cap_seconds:
        return None
    return parsed


def classify_http_status(status_code: int, retry_after_header: str | None = None) -> RecognitionProviderError:
    """Map one provider HTTP status to a stable, safe provider error."""

    if status_code == 429:
        return RecognitionProviderError(
            category=ProviderErrorCategory.RATE_LIMITED,
            retryable=True,
            safe_message="provider is rate limited",
            retry_after_seconds=parse_retry_after(retry_after_header),
        )
    if status_code == 401:
        return RecognitionProviderError(
            category=ProviderErrorCategory.AUTHENTICATION,
            retryable=False,
            safe_message="provider authentication failed",
        )
    if status_code == 403:
        return RecognitionProviderError(
            category=ProviderErrorCategory.PERMISSION,
            retryable=False,
            safe_message="provider permission denied",
        )
    if status_code == 408:
        return RecognitionProviderError(
            category=ProviderErrorCategory.TIMEOUT,
            retryable=True,
            safe_message="provider request timed out",
        )
    if 500 <= status_code <= 599:
        return RecognitionProviderError(
            category=ProviderErrorCategory.TEMPORARY,
            retryable=True,
            safe_message="provider returned a temporary server error",
        )
    if 400 <= status_code <= 499:
        return RecognitionProviderError(
            category=ProviderErrorCategory.PERMANENT,
            retryable=False,
            safe_message="provider returned a permanent client error",
        )
    return RecognitionProviderError(
        category=ProviderErrorCategory.INVALID_RESPONSE,
        retryable=False,
        safe_message="provider returned an unexpected status",
    )


def classify_exception(exc: Exception) -> RecognitionProviderError:
    """Map transport/timeout exceptions to safe retryable provider errors."""

    if isinstance(exc, httpx.TimeoutException):
        return RecognitionProviderError(
            category=ProviderErrorCategory.TIMEOUT,
            retryable=True,
            safe_message="provider call timed out",
        )
    if isinstance(exc, (httpx.TransportError, ConnectionError, OSError)):
        return RecognitionProviderError(
            category=ProviderErrorCategory.TEMPORARY,
            retryable=True,
            safe_message="provider connection failed",
        )
    return RecognitionProviderError(
        category=ProviderErrorCategory.PERMANENT,
        retryable=False,
        safe_message="provider request failed",
    )


__all__ = (
    "RecognitionProviderError",
    "classify_exception",
    "classify_http_status",
    "parse_retry_after",
)
