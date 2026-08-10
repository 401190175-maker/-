"""Framework-independent JSON serialization shared by QA adapters.

本模块只依赖 Python 标准库和 QA DTO，不依赖 FastAPI、Pydantic、Uvicorn
或 Neo4j，也不读取环境变量、不调用 QAService 或 facade。CLI 与 HTTP
共用同一套 JSON 转换、响应 envelope 和错误脱敏，保证同一 ``QAAnswer``
在不同 adapter 中保持一致的语义。
"""

from __future__ import annotations

import dataclasses
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


def to_jsonable(value: Any) -> Any:
    """Recursively convert QA DTOs and common containers to JSON-encodable values."""

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {field.name: to_jsonable(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    return value


def build_success_envelope(data: Any, meta: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build a stable success envelope with ``status="ok"`` and ``data``.

    未传 ``meta`` 时保持第一阶段 CLI 的顶层 ``status``/``data`` 兼容；
    HTTP adapter 必须传入 request ID 和 contract version。
    """

    envelope: dict[str, Any] = {"status": "ok", "data": data}
    if meta is not None:
        envelope["meta"] = meta
    return envelope


def build_error_envelope(
    category: str,
    message: str,
    retryable: bool,
    meta: Mapping[str, Any] | None = None,
    details: Any = None,
) -> dict[str, Any]:
    """Build a stable failure envelope with ``status="failed"`` and structured error."""

    error: dict[str, Any] = {
        "category": category,
        "message": message,
        "retryable": bool(retryable),
    }
    if details is not None:
        error["details"] = details
    envelope: dict[str, Any] = {"status": "failed", "error": error}
    if meta is not None:
        envelope["meta"] = meta
    return envelope


_SENSITIVE_TOKENS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "cypher",
    "driver",
    "session",
    "transaction",
    "bolt://",
    "neo4j://",
    "traceback",
    " at 0x",
)


def sanitize_error_message(message: str) -> str:
    """Return a safe client-facing message with backend and secret details removed."""

    lowered = message.lower()
    if any(token in lowered for token in _SENSITIVE_TOKENS):
        return "sensitive or low-level backend detail is unavailable"
    return message


__all__ = (
    "build_error_envelope",
    "build_success_envelope",
    "sanitize_error_message",
    "to_jsonable",
)
