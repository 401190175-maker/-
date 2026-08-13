"""Unified fail-closed redaction for recognition errors, payloads and traces."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping


_REDACTED = "<redacted>"

_FORBIDDEN_KEY_TOKENS = (
    "api_key",
    "apikey",
    "token",
    "password",
    "secret",
    "cookie",
    "authorization",
    "header",
    "traceback",
    "prompt",
    "provider_body",
    "base64",
    "data_url",
    "image_bytes",
    "path",
)

_WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\/]")
_BASE64_PATTERN = re.compile(r"^[A-Za-z0-9+/]{40,}={0,2}$")


class RecognitionRedactionError(RuntimeError):
    """Raised when redaction itself cannot complete safely (fail closed)."""


@dataclass(frozen=True)
class SafeRecognitionError:
    """Safe error projection with stable code/category and sanitized summary."""

    code: str | None
    category: str | None
    safe_message: str
    run_id: str | None = None
    attempt_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.safe_message, str) or not self.safe_message.strip():
            raise RecognitionRedactionError("safe_message must be a non-empty string")


class RecognitionRedactor:
    """Recursively mask secrets, paths, binaries and unknown objects."""

    def redact_error(self, error: Exception) -> SafeRecognitionError:
        """Project one exception into a safe error summary."""

        try:
            category = getattr(error, "category", None)
            if category is not None and isinstance(category, str) and str(category).strip():
                code = getattr(category, "value", category)
                code = str(code)
                safe_message = self._sanitize_text(str(error)) or "recognition failed"
                return SafeRecognitionError(
                    code=code,
                    category=code,
                    safe_message=safe_message,
                    run_id=getattr(error, "recognition_run_id", None),
                    attempt_id=getattr(error, "attempt_id", None),
                )
            return SafeRecognitionError(
                code=None,
                category="recognition_failed",
                safe_message="recognition failed",
                run_id=getattr(error, "recognition_run_id", None),
                attempt_id=getattr(error, "attempt_id", None),
            )
        except Exception:
            return SafeRecognitionError(
                code=None,
                category="recognition_failed",
                safe_message="recognition failed",
            )

    def redact_payload(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """Return a recursively redacted deep copy of one payload mapping."""

        try:
            result = self._redact_value(payload)
        except RecognitionRedactionError:
            raise
        except Exception as exc:
            raise RecognitionRedactionError("redaction failed closed") from exc
        if not isinstance(result, Mapping):
            raise RecognitionRedactionError("redaction produced a non-mapping result")
        return result

    def redact_trace(self, details: Mapping[str, Any]) -> Mapping[str, Any]:
        """Redact one trace/details mapping (same rules as payloads)."""

        return self.redact_payload(details)

    def _redact_value(self, value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                str(key): (
                    _REDACTED
                    if self._is_forbidden_key(str(key))
                    else self._redact_value(child)
                )
                for key, child in value.items()
            }
        if isinstance(value, list):
            return [self._redact_value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._redact_value(item) for item in value)
        if isinstance(value, bytes):
            return _REDACTED
        if isinstance(value, str):
            return self._sanitize_text(value)
        if value is None or isinstance(value, (int, float, bool)):
            return value
        return _REDACTED

    @staticmethod
    def _is_forbidden_key(key: str) -> bool:
        lowered = key.lower()
        return any(token in lowered for token in _FORBIDDEN_KEY_TOKENS)

    @staticmethod
    def _sanitize_text(value: str) -> str:
        if (
            _WINDOWS_PATH.match(value)
            or value.startswith("/")
            or "\\" in value
            or "://" in value
            or value.startswith("data:")
            or ";base64," in value
            or _BASE64_PATTERN.match(value)
            or "Traceback (most recent call last)" in value
            or value.lower().startswith("bearer ")
        ):
            return _REDACTED
        return value


__all__ = ("RecognitionRedactionError", "RecognitionRedactor", "SafeRecognitionError")
