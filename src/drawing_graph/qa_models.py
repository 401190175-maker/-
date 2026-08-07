"""Stable data contracts and error types for the drawing graph QA layer.

The QA layer is an orchestration layer outside ``DrawingGraphToolFacade``.
Its DTOs intentionally never carry Neo4j driver, session, transaction,
Cypher, credentials, or repository write handles.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class QuestionType(str, Enum):
    """Supported phase-one question types.

    每个枚举成员表示一种可安全映射的问题类型；值同时作为 JSON/CLI 的稳定标识。
    """

    PAGE_SUMMARY = "page_summary"
    BLOCK_RELATIONS = "block_relations"
    CANDIDATE_RELATIONS = "candidate_relations"
    SECTION_MATCHES = "section_matches"
    TABLE_CAPTION_STATUS = "table_caption_status"
    DIAGNOSTIC_STATUS = "diagnostic_status"
    UNKNOWN_OR_UNSUPPORTED = "unknown_or_unsupported"


class QAAnswerStatus(str, Enum):
    """Aggregate answer status used by :class:`QAAnswer`.

    状态只表达问答聚合结果，不替代底层图谱状态。
    """

    ANSWERED = "answered"
    PARTIAL = "partial"
    NOT_FOUND = "not_found"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class QAErrorCode(str, Enum):
    """Stable QA error categories shared by service and adapters."""

    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    UNSUPPORTED_QUESTION = "UNSUPPORTED_QUESTION"
    UNSUPPORTED_SCOPE = "UNSUPPORTED_SCOPE"
    NOT_FOUND = "NOT_FOUND"
    PARTIAL_ANSWER = "PARTIAL_ANSWER"
    WRITE_BACK_FORBIDDEN = "WRITE_BACK_FORBIDDEN"
    FACADE_UNAVAILABLE = "FACADE_UNAVAILABLE"
    NEO4J_UNAVAILABLE = "NEO4J_UNAVAILABLE"
    SEMANTIC_EVIDENCE_UNAVAILABLE = "SEMANTIC_EVIDENCE_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


ALLOWED_FACT_KINDS = frozenset(
    {
        "source_fact",
        "derived_relation",
        "semantic_observation",
        "semantic_interpretation",
        "candidate_relation",
        "formal_relation",
        "diagnostic",
        "unsupported",
    }
)

ALLOWED_ANSWER_STATUSES = frozenset(item.value for item in QAAnswerStatus)


class QAError(ValueError):
    """Raised when a QA request, DTO, or orchestration call is invalid."""

    def __init__(self, category: QAErrorCode | str, message: str, *, retryable: bool = False):
        self.category = _coerce_error_code(category)
        self.retryable = retryable
        super().__init__(message)


@dataclass(frozen=True)
class QAScope:
    """Query scope carrying optional stable business IDs.

    只承载业务 ID，不接收 driver、URI、密码或 Cypher。
    """

    project_id: str | None = None
    drawing_set_id: str | None = None
    page_id: str | None = None
    block_id: str | None = None
    cross_section_id: str | None = None
    table_id: str | None = None
    table_caption_id: str | None = None
    element_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in dataclasses.fields(self):
            _require_optional_text(getattr(self, field_name.name), field_name.name)


@dataclass(frozen=True)
class EvidenceRef:
    """One traceable evidence reference for an :class:`AnswerFact`."""

    project_id: str | None = None
    drawing_set_id: str | None = None
    page_id: str | None = None
    block_id: str | None = None
    element_id: str | None = None
    image_path: str | None = None
    bbox: Mapping[str, float] | None = None
    normalized_bbox: Mapping[str, float] | None = None
    recognition_run_id: str | None = None
    observation_id: str | None = None
    interpretation_id: str | None = None
    payload_ref: str | None = None
    candidate_group_id: str | None = None
    rule_version: str | None = None
    review_run_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "project_id",
            "drawing_set_id",
            "page_id",
            "block_id",
            "element_id",
            "image_path",
            "recognition_run_id",
            "observation_id",
            "interpretation_id",
            "payload_ref",
            "candidate_group_id",
            "rule_version",
            "review_run_id",
        ):
            _require_optional_text(getattr(self, field_name), field_name)
        object.__setattr__(self, "bbox", _bbox_mapping(self.bbox, "bbox"))
        object.__setattr__(self, "normalized_bbox", _bbox_mapping(self.normalized_bbox, "normalized_bbox"))


@dataclass(frozen=True)
class AnswerFact:
    """One structured fact, relation, or diagnostic entry in a QA answer."""

    fact_kind: str
    label: str
    status: str
    ids: Mapping[str, str] = field(default_factory=dict)
    relation_type: str | None = None
    value: Any = None
    evidence: tuple[EvidenceRef, ...] = ()
    payload: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.fact_kind not in ALLOWED_FACT_KINDS:
            raise QAError(QAErrorCode.INVALID_ARGUMENT, f"unsupported fact_kind: {self.fact_kind}")
        _require_text(self.label, "label")
        _require_text(self.status, "status")
        _require_optional_text(self.relation_type, "relation_type")
        if not isinstance(self.ids, Mapping):
            raise QAError(QAErrorCode.INVALID_ARGUMENT, "ids must be a mapping")
        if not all(isinstance(key, str) and isinstance(value, str) for key, value in self.ids.items()):
            raise QAError(QAErrorCode.INVALID_ARGUMENT, "ids must map strings to strings")
        if not isinstance(self.evidence, tuple) or not all(isinstance(item, EvidenceRef) for item in self.evidence):
            raise QAError(QAErrorCode.INVALID_ARGUMENT, "evidence must be a tuple of EvidenceRef")
        if self.payload is not None and not isinstance(self.payload, Mapping):
            raise QAError(QAErrorCode.INVALID_ARGUMENT, "payload must be a mapping when provided")
        _validate_fact_relation_kind(self.fact_kind, self.relation_type)
        object.__setattr__(self, "ids", MappingProxyType(dict(self.ids)))
        if self.payload is not None:
            object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True)
class QARequest:
    """One QA request.

    ``write_back`` defaults to ``False``; the service rejects ``True`` with
    :attr:`QAErrorCode.WRITE_BACK_FORBIDDEN` in phase one.
    """

    question_type: QuestionType | str
    scope: QAScope
    language: str = "zh"
    include_semantics: bool = True
    include_candidates: bool = True
    include_payload: bool = False
    format_hint: str | None = None
    write_back: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "question_type", _coerce_question_type(self.question_type))
        if not isinstance(self.scope, QAScope):
            raise QAError(QAErrorCode.INVALID_ARGUMENT, "scope must be a QAScope")
        if self.language not in {"zh", "en"}:
            raise QAError(QAErrorCode.INVALID_ARGUMENT, "language must be zh or en")
        for field_name in ("include_semantics", "include_candidates", "include_payload", "write_back"):
            if not isinstance(getattr(self, field_name), bool):
                raise QAError(QAErrorCode.INVALID_ARGUMENT, f"{field_name} must be a boolean")
        _require_optional_text(self.format_hint, "format_hint")


@dataclass(frozen=True)
class QAAnswer:
    """Final structured answer returned by the QA service."""

    question_type: QuestionType | str
    scope: QAScope
    status: QAAnswerStatus | str
    summary: str
    facts: tuple[AnswerFact, ...] = ()
    warnings: tuple[str, ...] = ()
    unsupported_parts: tuple[str, ...] = ()
    source_calls: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "question_type", _coerce_question_type(self.question_type))
        object.__setattr__(self, "status", _coerce_answer_status(self.status))
        _require_text(self.summary, "summary")
        if not isinstance(self.facts, tuple) or not all(isinstance(item, AnswerFact) for item in self.facts):
            raise QAError(QAErrorCode.INVALID_ARGUMENT, "facts must be a tuple of AnswerFact")
        for field_name in ("warnings", "unsupported_parts", "source_calls"):
            object.__setattr__(self, field_name, _read_text_tuple(getattr(self, field_name), field_name))


def _coerce_question_type(value: QuestionType | str) -> QuestionType:
    if isinstance(value, QuestionType):
        return value
    if isinstance(value, str):
        try:
            return QuestionType(value)
        except ValueError as exc:
            raise QAError(QAErrorCode.INVALID_ARGUMENT, f"unsupported question_type: {value}") from exc
    raise QAError(QAErrorCode.INVALID_ARGUMENT, "question_type must be a QuestionType or string")


def _coerce_answer_status(value: QAAnswerStatus | str) -> QAAnswerStatus:
    if isinstance(value, QAAnswerStatus):
        return value
    if isinstance(value, str) and value in ALLOWED_ANSWER_STATUSES:
        return QAAnswerStatus(value)
    raise QAError(QAErrorCode.INVALID_ARGUMENT, f"unsupported answer status: {value}")


def _coerce_error_code(value: QAErrorCode | str) -> QAErrorCode:
    if isinstance(value, QAErrorCode):
        return value
    if isinstance(value, str):
        try:
            return QAErrorCode(value)
        except ValueError as exc:
            raise QAError(QAErrorCode.INVALID_ARGUMENT, f"unsupported QA error code: {value}") from exc
    raise QAError(QAErrorCode.INVALID_ARGUMENT, "QA error category must be a QAErrorCode or string")


def _validate_fact_relation_kind(fact_kind: str, relation_type: str | None) -> None:
    if relation_type is None:
        return
    if relation_type.upper().startswith("CANDIDATE_"):
        if fact_kind != "candidate_relation":
            raise QAError(
                QAErrorCode.INVALID_ARGUMENT,
                "candidate relation types cannot be expressed as a non-candidate fact_kind",
            )


def _bbox_mapping(value: Mapping[str, Any] | None, field_name: str) -> Mapping[str, float] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise QAError(QAErrorCode.INVALID_ARGUMENT, f"{field_name} must be a mapping")
    required_keys = ("x_min", "y_min", "x_max", "y_max")
    if any(key not in value for key in required_keys):
        raise QAError(QAErrorCode.INVALID_ARGUMENT, f"{field_name} must contain x_min, y_min, x_max, y_max")
    converted = {}
    for key in required_keys:
        number = value[key]
        if not isinstance(number, (int, float)) or isinstance(number, bool):
            raise QAError(QAErrorCode.INVALID_ARGUMENT, f"{field_name}.{key} must be numeric")
        converted[key] = float(number)
    if converted["x_min"] >= converted["x_max"] or converted["y_min"] >= converted["y_max"]:
        raise QAError(QAErrorCode.INVALID_ARGUMENT, f"{field_name} minimum coordinates must be less than maximum")
    return MappingProxyType(converted)


def _require_text(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise QAError(QAErrorCode.INVALID_ARGUMENT, f"{field_name} must be a non-empty string")


def _require_optional_text(value: Any, field_name: str) -> None:
    if value is not None:
        _require_text(value, field_name)


def _read_text_tuple(values: Any, field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, (tuple, list)):
        raise QAError(QAErrorCode.INVALID_ARGUMENT, f"{field_name} must be a sequence of strings")
    for value in values:
        _require_text(value, field_name)
    return tuple(values)


__all__ = (
    "ALLOWED_ANSWER_STATUSES",
    "ALLOWED_FACT_KINDS",
    "AnswerFact",
    "EvidenceRef",
    "QAAnswer",
    "QAAnswerStatus",
    "QAError",
    "QAErrorCode",
    "QARequest",
    "QAScope",
    "QuestionType",
)
