"""Narrow-scope input and output contracts for the STDIO MCP product adapter.

本模块是产品 MCP adapter 的传输层合同：只接收一个只读自然语言工具需要的
白名单字段，拒绝额外字段、写回、Cypher、凭据、路径和底层对象。领域 DTO
（``assistant_models``）保持不变；MCP 模型只负责把白名单参数转换为只读
``AssistantRequest``，不调用 service、facade、repository 或 Neo4j。
"""

from __future__ import annotations

import uuid
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from .assistant_models import AssistantRequest, AssistantScope

MCP_ASSISTANT_CONTRACT_VERSION = "drawing-assistant-mcp-v1"
MCP_ASSISTANT_TOOL_NAME = "ask_drawing_assistant"
MCP_ASSISTANT_DEFAULT_LANGUAGE = "zh-CN"
MCP_ASSISTANT_ALLOWED_LANGUAGES = frozenset({"zh-CN", "en"})
MAX_SCOPE_ID_LENGTH = 512
MAX_QUESTION_LENGTH = 2000
MAX_REQUEST_ID_LENGTH = 128

McpAssistantErrorCategory: TypeAlias = Literal[
    "invalid_argument",
    "read_only_violation",
    "configuration_failed",
    "initialization_failed",
    "assistant_call_failed",
    "timeout",
    "concurrency_limit_reached",
    "internal_error",
]


class McpAssistantInputError(ValueError):
    """Raised when a product MCP input violates the narrow whitelist contract."""


def normalize_language(value: str | None) -> str:
    """Return the allowed language or raise without echoing the input value."""

    language = MCP_ASSISTANT_DEFAULT_LANGUAGE if value is None else value
    if not isinstance(language, str) or language not in MCP_ASSISTANT_ALLOWED_LANGUAGES:
        raise McpAssistantInputError("language must be one of: zh-CN, en")
    return language


def normalize_scope_id(value: str | None, field_name: str) -> str | None:
    """Return a stripped non-empty scope ID bounded by ``MAX_SCOPE_ID_LENGTH``."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise McpAssistantInputError(f"{field_name} must be a string")
    stripped = value.strip()
    if not stripped:
        raise McpAssistantInputError(f"{field_name} must not be blank")
    if len(stripped) > MAX_SCOPE_ID_LENGTH:
        raise McpAssistantInputError(f"{field_name} must be at most {MAX_SCOPE_ID_LENGTH} characters")
    return stripped


class McpAssistantInputModel(BaseModel):
    """Shared strict-input base: unknown or extra fields are rejected."""

    model_config = ConfigDict(extra="forbid")


class AssistantScopeHint(McpAssistantInputModel):
    """Business-ID scope hint mirroring :class:`AssistantScope` with length limits."""

    project_id: str | None = None
    drawing_set_id: str | None = None
    page_id: str | None = None
    block_id: str | None = None
    element_id: str | None = None
    cross_section_id: str | None = None
    table_id: str | None = None
    table_caption_id: str | None = None
    claim_id: str | None = None

    @field_validator(
        "project_id",
        "drawing_set_id",
        "page_id",
        "block_id",
        "element_id",
        "cross_section_id",
        "table_id",
        "table_caption_id",
        "claim_id",
    )
    @classmethod
    def _validate_id(cls, value: str | None, info) -> str | None:
        return normalize_scope_id(value, str(info.field_name))

    def is_empty(self) -> bool:
        return all(
            getattr(self, name) is None
            for name in (
                "project_id",
                "drawing_set_id",
                "page_id",
                "block_id",
                "element_id",
                "cross_section_id",
                "table_id",
                "table_caption_id",
                "claim_id",
            )
        )

    def to_assistant_scope(self) -> AssistantScope | None:
        if self.is_empty():
            return None
        return AssistantScope(
            project_id=self.project_id,
            drawing_set_id=self.drawing_set_id,
            page_id=self.page_id,
            block_id=self.block_id,
            element_id=self.element_id,
            cross_section_id=self.cross_section_id,
            table_id=self.table_id,
            table_caption_id=self.table_caption_id,
            claim_id=self.claim_id,
        )


class AskDrawingAssistantInput(McpAssistantInputModel):
    """Narrow input for the ``ask_drawing_assistant`` read-only product tool."""

    question: str
    request_id: str | None = None
    language: str = MCP_ASSISTANT_DEFAULT_LANGUAGE
    scope_hint: AssistantScopeHint | None = None
    allow_recognition: StrictBool = True
    answer_format: str | None = None

    @field_validator("question")
    @classmethod
    def _validate_question(cls, value: str) -> str:
        if not isinstance(value, str):
            raise McpAssistantInputError("question must be a string")
        stripped = value.strip()
        if not stripped:
            raise McpAssistantInputError("question must not be blank")
        if len(stripped) > MAX_QUESTION_LENGTH:
            raise McpAssistantInputError(f"question must be at most {MAX_QUESTION_LENGTH} characters")
        return stripped

    @field_validator("request_id")
    @classmethod
    def _validate_request_id(cls, value: str | None) -> str | None:
        return normalize_scope_id(value, "request_id") if value is not None else None

    @field_validator("language")
    @classmethod
    def _validate_language(cls, value: str) -> str:
        return normalize_language(value)

    @field_validator("answer_format")
    @classmethod
    def _validate_answer_format(cls, value: str | None) -> str | None:
        return normalize_scope_id(value, "answer_format") if value is not None else None

    @model_validator(mode="after")
    def _scope_hint_not_empty(self) -> "AskDrawingAssistantInput":
        if self.scope_hint is not None and self.scope_hint.is_empty():
            raise ValueError("scope_hint must contain at least one business ID when provided")
        return self

    def to_assistant_request(self, request_id: str | None = None) -> AssistantRequest:
        """Convert to a fixed read-only domain :class:`AssistantRequest`."""

        effective_request_id = request_id or self.request_id or f"req:{uuid.uuid4().hex}"
        scope = self.scope_hint.to_assistant_scope() if self.scope_hint is not None else None
        return AssistantRequest(
            request_id=effective_request_id,
            question=self.question,
            scope_hint=scope,
            language=self.language,
            allow_recognition=self.allow_recognition,
            allow_write_back=False,
            answer_format=self.answer_format,
        )


class McpAssistantResultMeta(BaseModel):
    """Per-result metadata shared by success and failure roots."""

    contract_version: Literal["drawing-assistant-mcp-v1"] = MCP_ASSISTANT_CONTRACT_VERSION
    tool_name: Literal["ask_drawing_assistant"] = MCP_ASSISTANT_TOOL_NAME
    call_id: str = Field(min_length=1, max_length=128)


class McpAssistantAnswer(BaseModel):
    """JSON-safe product AnswerPackage projection exposed as structuredContent."""

    answer_contract_version: str | None = None
    request_id: str
    status: str | None = None
    machine_answer: dict[str, Any] | None = None
    text_answer: str | None = None
    claims: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[Any] = Field(default_factory=list)
    unsupported_parts: list[str] = Field(default_factory=list)
    recognition_run_ids: list[str] = Field(default_factory=list)


class McpAssistantErrorBody(BaseModel):
    """Stable sanitized error object returned inside a failure root."""

    category: McpAssistantErrorCategory
    message: str = Field(min_length=1, max_length=2000)
    retryable: bool


class McpAssistantSuccess(BaseModel):
    """Stable success root: status, JSON-safe AnswerPackage projection, and meta."""

    status: Literal["ok"] = "ok"
    data: dict[str, Any]
    meta: McpAssistantResultMeta


class McpAssistantFailure(BaseModel):
    """Stable failure root: status, sanitized error, and meta."""

    status: Literal["error"] = "error"
    error: McpAssistantErrorBody
    meta: McpAssistantResultMeta


McpAssistantToolOutcome: TypeAlias = McpAssistantSuccess | McpAssistantFailure


__all__ = (
    "AskDrawingAssistantInput",
    "AssistantScopeHint",
    "MAX_QUESTION_LENGTH",
    "MAX_REQUEST_ID_LENGTH",
    "MAX_SCOPE_ID_LENGTH",
    "MCP_ASSISTANT_ALLOWED_LANGUAGES",
    "MCP_ASSISTANT_CONTRACT_VERSION",
    "MCP_ASSISTANT_DEFAULT_LANGUAGE",
    "MCP_ASSISTANT_TOOL_NAME",
    "McpAssistantErrorBody",
    "McpAssistantErrorCategory",
    "McpAssistantFailure",
    "McpAssistantInputError",
    "McpAssistantInputModel",
    "McpAssistantAnswer",
    "McpAssistantResultMeta",
    "McpAssistantSuccess",
    "McpAssistantToolOutcome",
    "normalize_language",
    "normalize_scope_id",
)
