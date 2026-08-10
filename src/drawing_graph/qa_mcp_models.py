"""Narrow-scope input and output contracts for the STDIO MCP QA adapter.

本模块是 MCP adapter 的传输层合同：只接收六个只读工具需要的窄口径字段，
拒绝额外字段、写回、payload、Cypher、凭据、路径和底层对象。领域 DTO
（``qa_models``）保持不变；MCP 模型只负责把白名单参数转换为只读
``QARequest``，不调用 QAService、facade、repository 或 Neo4j。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, StrictBool, field_validator, model_validator

from .qa_models import QARequest, QAScope, QuestionType


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


class AskDrawingPageInput(McpInputModel):
    """Narrow input for the ``ask_drawing_page`` tool (page_summary)."""

    page_id: str
    language: str = MCP_DEFAULT_LANGUAGE
    include_semantics: StrictBool = True

    @field_validator("page_id")
    @classmethod
    def _validate_page_id(cls, value: str) -> str:
        return normalize_scope_id(value, "page_id")

    @field_validator("language")
    @classmethod
    def _validate_language(cls, value: str) -> str:
        return normalize_language(value)

    def to_qa_request(self) -> QARequest:
        """Convert to a fixed read-only ``page_summary`` request."""

        return QARequest(
            question_type=QuestionType.PAGE_SUMMARY,
            scope=QAScope(page_id=self.page_id),
            language=self.language,
            include_semantics=self.include_semantics,
            include_payload=False,
            write_back=False,
        )


class AskDrawingBlockInput(McpInputModel):
    """Narrow input for the ``ask_drawing_block`` tool (block_relations)."""

    block_id: str
    language: str = MCP_DEFAULT_LANGUAGE
    include_candidates: StrictBool = True

    @field_validator("block_id")
    @classmethod
    def _validate_block_id(cls, value: str) -> str:
        return normalize_scope_id(value, "block_id")

    @field_validator("language")
    @classmethod
    def _validate_language(cls, value: str) -> str:
        return normalize_language(value)

    def to_qa_request(self) -> QARequest:
        """Convert to a fixed read-only ``block_relations`` request."""

        return QARequest(
            question_type=QuestionType.BLOCK_RELATIONS,
            scope=QAScope(block_id=self.block_id),
            language=self.language,
            include_candidates=self.include_candidates,
            include_payload=False,
            write_back=False,
        )


class ListDrawingCandidatesInput(McpInputModel):
    """Narrow input for the ``list_drawing_candidates`` tool."""

    page_id: str | None = None
    block_id: str | None = None
    language: str = MCP_DEFAULT_LANGUAGE

    @field_validator("page_id")
    @classmethod
    def _validate_page_id(cls, value: str | None) -> str | None:
        return None if value is None else normalize_scope_id(value, "page_id")

    @field_validator("block_id")
    @classmethod
    def _validate_block_id(cls, value: str | None) -> str | None:
        return None if value is None else normalize_scope_id(value, "block_id")

    @field_validator("language")
    @classmethod
    def _validate_language(cls, value: str) -> str:
        return normalize_language(value)

    @model_validator(mode="after")
    def _exactly_one_scope(self) -> "ListDrawingCandidatesInput":
        if (self.page_id is None) == (self.block_id is None):
            raise ValueError("exactly one of page_id or block_id must be provided")
        return self

    def to_qa_request(self) -> QARequest:
        """Convert to a fixed read-only ``candidate_relations`` request."""

        return QARequest(
            question_type=QuestionType.CANDIDATE_RELATIONS,
            scope=QAScope(page_id=self.page_id, block_id=self.block_id),
            language=self.language,
            include_payload=False,
            write_back=False,
        )


class GetSectionMatchStatusInput(McpInputModel):
    """Narrow input for the ``get_section_match_status`` tool."""

    cross_section_id: str | None = None
    page_id: str | None = None
    language: str = MCP_DEFAULT_LANGUAGE

    @field_validator("cross_section_id")
    @classmethod
    def _validate_cross_section_id(cls, value: str | None) -> str | None:
        return None if value is None else normalize_scope_id(value, "cross_section_id")

    @field_validator("page_id")
    @classmethod
    def _validate_page_id(cls, value: str | None) -> str | None:
        return None if value is None else normalize_scope_id(value, "page_id")

    @field_validator("language")
    @classmethod
    def _validate_language(cls, value: str) -> str:
        return normalize_language(value)

    @model_validator(mode="after")
    def _exactly_one_scope(self) -> "GetSectionMatchStatusInput":
        if (self.cross_section_id is None) == (self.page_id is None):
            raise ValueError("exactly one of cross_section_id or page_id must be provided")
        return self

    def to_qa_request(self) -> QARequest:
        """Convert to a fixed read-only ``section_matches`` request."""

        return QARequest(
            question_type=QuestionType.SECTION_MATCHES,
            scope=QAScope(cross_section_id=self.cross_section_id, page_id=self.page_id),
            language=self.language,
            include_payload=False,
            write_back=False,
        )


__all__ = (
    "AskDrawingBlockInput",
    "AskDrawingPageInput",
    "GetSectionMatchStatusInput",
    "ListDrawingCandidatesInput",
    "MAX_SCOPE_ID_LENGTH",
    "MCP_ALLOWED_LANGUAGES",
    "MCP_DEFAULT_LANGUAGE",
    "McpInputError",
    "McpInputModel",
    "normalize_language",
    "normalize_scope_id",
)
