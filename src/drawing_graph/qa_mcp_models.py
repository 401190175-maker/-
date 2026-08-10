"""Narrow-scope input and output contracts for the STDIO MCP QA adapter.

本模块是 MCP adapter 的传输层合同：只接收六个只读工具需要的窄口径字段，
拒绝额外字段、写回、payload、Cypher、凭据、路径和底层对象。领域 DTO
（``qa_models``）保持不变；MCP 模型只负责把白名单参数转换为只读
``QARequest``，不调用 QAService、facade、repository 或 Neo4j。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


MCP_DEFAULT_LANGUAGE = "zh"
MCP_ALLOWED_LANGUAGES = frozenset({"zh", "en"})
MAX_SCOPE_ID_LENGTH = 512


class McpInputError(ValueError):
    """Raised when an MCP input violates the narrow whitelist contract."""


def normalize_language(value: str | None) -> str:
    """Return the allowed language or raise without echoing the input value."""

    language = MCP_DEFAULT_LANGUAGE if value is None else value
    if not isinstance(language, str) or language not in MCP_ALLOWED_LANGUAGES:
        raise McpInputError("language must be one of: zh, en")
    return language


def normalize_scope_id(value: str | None, field_name: str) -> str:
    """Return a stripped non-empty scope ID bounded by ``MAX_SCOPE_ID_LENGTH``."""

    if value is None:
        raise McpInputError(f"{field_name} is required")
    if not isinstance(value, str):
        raise McpInputError(f"{field_name} must be a string")
    stripped = value.strip()
    if not stripped:
        raise McpInputError(f"{field_name} must not be blank")
    if len(stripped) > MAX_SCOPE_ID_LENGTH:
        raise McpInputError(f"{field_name} must be at most {MAX_SCOPE_ID_LENGTH} characters")
    return stripped


class McpInputModel(BaseModel):
    """Shared strict-input base: unknown or extra fields are rejected."""

    model_config = ConfigDict(extra="forbid")


__all__ = (
    "MAX_SCOPE_ID_LENGTH",
    "MCP_ALLOWED_LANGUAGES",
    "MCP_DEFAULT_LANGUAGE",
    "McpInputError",
    "McpInputModel",
    "normalize_language",
    "normalize_scope_id",
)
