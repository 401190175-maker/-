"""HTTP protocol models for the read-only drawing graph QA API.

本模块是协议层：使用严格字段白名单接收请求、验证响应，并在 HTTP 模型和
领域 ``QARequest``/``QAAnswer`` 之间转换。领域 DTO（``qa_models``）保持
框架无关；这里不复制 QAService 的完整 scope 业务规则，也不暴露 URI、
凭据、Cypher 或底层 driver/session/transaction 字段。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from .qa_models import QAAnswer, QARequest, QAScope
from .qa_serialization import to_jsonable


class HttpQuestionType(str, Enum):
    """Client-visible question types; ``unknown_or_unsupported`` stays internal."""

    PAGE_SUMMARY = "page_summary"
    BLOCK_RELATIONS = "block_relations"
    CANDIDATE_RELATIONS = "candidate_relations"
    SECTION_MATCHES = "section_matches"
    TABLE_CAPTION_STATUS = "table_caption_status"
    DIAGNOSTIC_STATUS = "diagnostic_status"


class HttpQAScope(BaseModel):
    """Business-ID query scope mirroring :class:`QAScope` with length limits."""

    model_config = ConfigDict(extra="forbid")

    project_id: str | None = Field(default=None, min_length=1, max_length=200)
    drawing_set_id: str | None = Field(default=None, min_length=1, max_length=200)
    page_id: str | None = Field(default=None, min_length=1, max_length=200)
    block_id: str | None = Field(default=None, min_length=1, max_length=200)
    cross_section_id: str | None = Field(default=None, min_length=1, max_length=200)
    table_id: str | None = Field(default=None, min_length=1, max_length=200)
    table_caption_id: str | None = Field(default=None, min_length=1, max_length=200)
    element_id: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("*")
    @classmethod
    def _not_blank(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            raise ValueError("business IDs must not be blank")
        return value


class HttpQARequest(BaseModel):
    """Strict request model for ``POST /api/v1/drawing-qa/ask``."""

    model_config = ConfigDict(extra="forbid")

    question_type: HttpQuestionType
    scope: HttpQAScope
    language: Literal["zh", "en"] = "zh"
    include_semantics: StrictBool = True
    include_candidates: StrictBool = True
    include_payload: StrictBool = False
    write_back: StrictBool = False

    def to_domain(self) -> QARequest:
        """Convert to the framework-independent domain :class:`QARequest`."""

        return QARequest(
            question_type=self.question_type.value,
            scope=QAScope(
                project_id=self.scope.project_id,
                drawing_set_id=self.scope.drawing_set_id,
                page_id=self.scope.page_id,
                block_id=self.scope.block_id,
                cross_section_id=self.scope.cross_section_id,
                table_id=self.scope.table_id,
                table_caption_id=self.scope.table_caption_id,
                element_id=self.scope.element_id,
            ),
            language=self.language,
            include_semantics=self.include_semantics,
            include_candidates=self.include_candidates,
            include_payload=self.include_payload,
            format_hint="json",
            write_back=self.write_back,
        )


class HttpEvidenceRef(BaseModel):
    """Traceable evidence reference; no Neo4j internal IDs or backend objects."""

    project_id: str | None = None
    drawing_set_id: str | None = None
    page_id: str | None = None
    block_id: str | None = None
    element_id: str | None = None
    image_path: str | None = None
    bbox: dict[str, float] | None = None
    normalized_bbox: dict[str, float] | None = None
    recognition_run_id: str | None = None
    observation_id: str | None = None
    interpretation_id: str | None = None
    payload_ref: str | None = None
    candidate_group_id: str | None = None
    rule_version: str | None = None
    review_run_id: str | None = None


class HttpAnswerFact(BaseModel):
    """One validated fact that never upgrades candidate semantics to formal."""

    fact_kind: Literal[
        "source_fact",
        "derived_relation",
        "semantic_observation",
        "semantic_interpretation",
        "candidate_relation",
        "formal_relation",
        "diagnostic",
        "unsupported",
    ]
    label: str
    status: str
    ids: dict[str, str] = Field(default_factory=dict)
    relation_type: str | None = None
    value: Any = None
    evidence: list[HttpEvidenceRef] = Field(default_factory=list)
    payload: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _candidate_cannot_be_formal(self) -> "HttpAnswerFact":
        relation_type = (self.relation_type or "").upper()
        status = (self.status or "").lower()
        is_candidate = relation_type.startswith("CANDIDATE_") or status == "matched_candidate"
        if is_candidate and self.fact_kind != "candidate_relation":
            raise ValueError("candidate semantics cannot be expressed as a formal or non-candidate fact_kind")
        return self


class HttpQAAnswer(BaseModel):
    """Validated serialized :class:`QAAnswer` without reinterpreting fact kinds."""

    question_type: str
    scope: HttpQAScope
    status: str
    summary: str
    facts: list[HttpAnswerFact] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    unsupported_parts: list[str] = Field(default_factory=list)
    source_calls: list[str] = Field(default_factory=list)


class HttpResponseMeta(BaseModel):
    """Per-response metadata generated by the server."""

    request_id: str
    contract_version: str = "drawing-qa-http-v1"


class HttpSuccessEnvelope(BaseModel):
    """Stable success envelope for HTTP responses."""

    status: Literal["ok"]
    data: HttpQAAnswer
    meta: HttpResponseMeta


class HttpErrorBody(BaseModel):
    """Stable sanitized error body; details never carry secrets or stack traces."""

    category: str
    message: str
    retryable: bool
    details: list[Any] | dict[str, Any] | None = None


class HttpErrorEnvelope(BaseModel):
    """Stable failure envelope for HTTP responses."""

    status: Literal["failed"]
    error: HttpErrorBody
    meta: HttpResponseMeta


class HttpHealthResponse(BaseModel):
    """Health payload; never claims live Neo4j verification."""

    status: str
    service: str
    contract_version: str
    neo4j_status: str | None = None


def http_answer_from_qa_answer(answer: QAAnswer) -> HttpQAAnswer:
    """Validate the serialized domain answer without reinterpreting facts."""

    return HttpQAAnswer.model_validate(to_jsonable(answer))


__all__ = (
    "HttpAnswerFact",
    "HttpErrorBody",
    "HttpErrorEnvelope",
    "HttpEvidenceRef",
    "HttpHealthResponse",
    "HttpQAAnswer",
    "HttpQARequest",
    "HttpQAScope",
    "HttpQuestionType",
    "HttpResponseMeta",
    "HttpSuccessEnvelope",
    "http_answer_from_qa_answer",
)
