"""Stable DTOs and error contracts for the drawing graph tool facade."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class ToolModelError(ValueError):
    """Raised when a tool facade DTO receives invalid public input."""

    def __init__(self, category: str, message: str):
        self.category = category
        super().__init__(message)


class ToolErrorCode(str, Enum):
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    NOT_FOUND = "NOT_FOUND"
    WRITE_BACK_REQUIRED = "WRITE_BACK_REQUIRED"
    WRITE_BACK_FORBIDDEN = "WRITE_BACK_FORBIDDEN"
    RECOGNITION_FAILED = "RECOGNITION_FAILED"
    RUN_LOG_UNAVAILABLE = "RUN_LOG_UNAVAILABLE"
    SEMANTIC_EVIDENCE_UNAVAILABLE = "SEMANTIC_EVIDENCE_UNAVAILABLE"
    NEO4J_UNAVAILABLE = "NEO4J_UNAVAILABLE"
    CANDIDATE_REVIEW_REJECTED = "CANDIDATE_REVIEW_REJECTED"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True)
class BBox:
    x_min: float
    y_min: float
    x_max: float
    y_max: float

    def __post_init__(self) -> None:
        for field_name in ("x_min", "y_min", "x_max", "y_max"):
            value = getattr(self, field_name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ToolModelError("invalid_bbox", f"{field_name} must be numeric")
        if self.x_min >= self.x_max or self.y_min >= self.y_max:
            raise ToolModelError("invalid_bbox", "bbox minimum coordinates must be less than maximum coordinates")


@dataclass(frozen=True)
class Pagination:
    limit: int = 100
    cursor: str | None = None
    next_cursor: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.limit, int) or isinstance(self.limit, bool) or self.limit < 1:
            raise ToolModelError("invalid_limit", "limit must be a positive integer")
        _require_optional_text(self.cursor, "cursor")
        _require_optional_text(self.next_cursor, "next_cursor")


@dataclass(frozen=True)
class ToolError:
    code: ToolErrorCode | str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)
    retryable: bool = False

    def __post_init__(self) -> None:
        code = _coerce_error_code(self.code)
        _require_text(self.message, "message")
        if not isinstance(self.details, Mapping):
            raise ToolModelError("invalid_error_details", "details must be a mapping")
        if not isinstance(self.retryable, bool):
            raise ToolModelError("invalid_retryable", "retryable must be a boolean")
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))


@dataclass(frozen=True)
class DrawingSetSummary:
    project_id: str
    drawing_set_id: str
    name: str
    page_count: int | None = None

    def __post_init__(self) -> None:
        _require_text(self.project_id, "project_id")
        _require_text(self.drawing_set_id, "drawing_set_id")
        _require_text(self.name, "name")
        _require_optional_non_negative_int(self.page_count, "page_count")


@dataclass(frozen=True)
class PageSummary:
    drawing_set_id: str
    page_id: str
    file_stem: str
    page_number: int | None = None
    image_path: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.drawing_set_id, "drawing_set_id")
        _require_text(self.page_id, "page_id")
        _require_text(self.file_stem, "file_stem")
        _require_optional_non_negative_int(self.page_number, "page_number")
        _require_optional_text(self.image_path, "image_path")


@dataclass(frozen=True)
class ElementEvidence:
    element_id: str
    element_type: str
    bbox: BBox
    normalized_bbox: BBox
    source_label: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.element_id, "element_id")
        _require_text(self.element_type, "element_type")
        _require_text(self.source_label, "source_label")
        if not isinstance(self.bbox, BBox) or not isinstance(self.normalized_bbox, BBox):
            raise ToolModelError("invalid_bbox", "bbox and normalized_bbox must be BBox instances")
        _require_normalized_bbox(self.normalized_bbox)
        if not isinstance(self.metadata, Mapping):
            raise ToolModelError("invalid_metadata", "metadata must be a mapping")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class PageSourceFacts:
    page_id: str
    image_path: str | None
    elements: tuple[ElementEvidence, ...]
    image_size: tuple[int, int] | None = None
    image_hash: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.page_id, "page_id")
        _require_optional_text(self.image_path, "image_path")
        _require_optional_text(self.image_hash, "image_hash")
        if not isinstance(self.elements, tuple) or not all(isinstance(item, ElementEvidence) for item in self.elements):
            raise ToolModelError("invalid_elements", "elements must be a tuple of ElementEvidence")
        if self.image_size is not None:
            if (
                not isinstance(self.image_size, tuple)
                or len(self.image_size) != 2
                or not all(isinstance(value, int) and value > 0 for value in self.image_size)
            ):
                raise ToolModelError("invalid_image_size", "image_size must be a positive (width, height) tuple")


@dataclass(frozen=True)
class BlockTrace:
    block_id: str
    project_id: str
    drawing_set_id: str
    page_id: str
    bbox: BBox
    normalized_bbox: BBox
    page_number: int | None = None
    image_path: str | None = None
    citation_ref: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("block_id", "project_id", "drawing_set_id", "page_id"):
            _require_text(getattr(self, field_name), field_name)
        _require_optional_non_negative_int(self.page_number, "page_number")
        _require_optional_text(self.image_path, "image_path")
        _require_optional_text(self.citation_ref, "citation_ref")
        _require_normalized_bbox(self.normalized_bbox)


@dataclass(frozen=True)
class BlockRelations:
    block_id: str
    caption_ids: tuple[str, ...] = ()
    basic_info_ids: tuple[str, ...] = ()
    annotation_ids: tuple[str, ...] = ()
    section_mark_ids: tuple[str, ...] = ()
    candidate_caption_ids: tuple[str, ...] = ()
    candidate_section_mark_ids: tuple[str, ...] = ()
    relation_status: str = "not_enhanced"
    basic_info_status: str | None = None
    basic_info_source: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.block_id, "block_id")
        for field_name in (
            "caption_ids",
            "basic_info_ids",
            "annotation_ids",
            "section_mark_ids",
            "candidate_caption_ids",
            "candidate_section_mark_ids",
        ):
            object.__setattr__(self, field_name, _read_text_tuple(getattr(self, field_name), field_name))
        _require_text(self.relation_status, "relation_status")
        _require_optional_text(self.basic_info_status, "basic_info_status")
        _require_optional_text(self.basic_info_source, "basic_info_source")


@dataclass(frozen=True)
class CandidateRelationSummary:
    candidate_group_id: str
    page_id: str
    block_id: str
    relation_type: str
    status: str
    score: float | None = None
    conflict_reason: str | None = None
    evidence_ids: tuple[str, ...] = ()
    recognition_run_id: str | None = None
    fact_kind: str = "candidate"
    source_element_id: str | None = None
    target_element_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("candidate_group_id", "page_id", "block_id", "relation_type", "status"):
            _require_text(getattr(self, field_name), field_name)
        if self.score is not None and (
            not isinstance(self.score, (int, float)) or isinstance(self.score, bool) or not 0 <= self.score <= 1
        ):
            raise ToolModelError("invalid_score", "score must be between 0 and 1 when provided")
        _require_optional_text(self.conflict_reason, "conflict_reason")
        _require_optional_text(self.recognition_run_id, "recognition_run_id")
        if self.fact_kind != "candidate":
            raise ToolModelError("invalid_fact_kind", "candidate relation summaries must use fact_kind='candidate'")
        _require_optional_text(self.source_element_id, "source_element_id")
        _require_optional_text(self.target_element_id, "target_element_id")
        object.__setattr__(self, "evidence_ids", _read_text_tuple(self.evidence_ids, "evidence_ids"))


@dataclass(frozen=True)
class CandidateReviewSummary:
    candidate_group_id: str
    status: str
    persisted: bool
    promoted: bool = False
    reason: str | None = None
    issue_category: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.candidate_group_id, "candidate_group_id")
        _require_text(self.status, "status")
        if not isinstance(self.persisted, bool) or not isinstance(self.promoted, bool):
            raise ToolModelError("invalid_review_summary", "persisted and promoted must be booleans")
        _require_optional_text(self.reason, "reason")
        _require_optional_text(self.issue_category, "issue_category")


@dataclass(frozen=True)
class SemanticObservationSummary:
    """Stable facade output for one TextObservation."""

    observation_id: str
    recognition_run_id: str
    target_element_id: str
    target_element_type: str
    page_id: str
    raw_text: str
    normalized_text: str
    bbox: BBox
    normalized_bbox: BBox
    confidence: float
    status: str
    model_profile: str = "default"
    model_version: str | None = None
    prompt_version: str = "default"
    contract_version: str | None = None
    preprocessing_version: str | None = None
    normalization_rule_version: str | None = None
    created_at: str | None = None
    image_hash: str | None = None
    cache_key: str | None = None
    fact_kind: str = "semantic_observation"
    evidence: Mapping[str, Any] = field(default_factory=dict)
    persisted: bool = False
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "observation_id",
            "recognition_run_id",
            "target_element_id",
            "target_element_type",
            "page_id",
            "raw_text",
            "normalized_text",
            "status",
            "model_profile",
            "prompt_version",
        ):
            _require_text(getattr(self, field_name), field_name)
        for field_name in (
            "model_version",
            "contract_version",
            "preprocessing_version",
            "normalization_rule_version",
        ):
            _require_optional_text(getattr(self, field_name), field_name)
        _require_optional_text(self.created_at, "created_at")
        _require_optional_text(self.image_hash, "image_hash")
        _require_optional_text(self.cache_key, "cache_key")
        if (
            not isinstance(self.confidence, (int, float))
            or isinstance(self.confidence, bool)
            or not 0 <= self.confidence <= 1
        ):
            raise ToolModelError("invalid_confidence", "confidence must be between 0 and 1")
        if not isinstance(self.bbox, BBox) or not isinstance(self.normalized_bbox, BBox):
            raise ToolModelError("invalid_bbox", "bbox and normalized_bbox must be BBox instances")
        _require_normalized_bbox(self.normalized_bbox)
        if self.fact_kind != "semantic_observation":
            raise ToolModelError("invalid_fact_kind", "observation summaries must use fact_kind='semantic_observation'")
        _require_mapping(self.evidence, "evidence")
        _require_boolean(self.persisted, "persisted")
        object.__setattr__(self, "evidence", MappingProxyType(dict(self.evidence)))
        object.__setattr__(self, "warnings", _read_text_tuple(self.warnings, "warnings"))


@dataclass(frozen=True)
class SemanticTargetInput:
    """精确识别目标输入合同，供后续执行层消费，不含产品决策/预算/答案状态。"""

    target_id: str
    page_id: str
    target_type: str
    task_type: str
    output_contract_version: str = "1"
    input_contract_version: str = "1"
    preprocessing_version: str = "preprocess-v1"
    target_element_id: str | None = None
    required_outputs: tuple[str, ...] = ()
    bbox: BBox | None = None
    normalized_bbox: BBox | None = None
    context_element_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.target_id, "target_id")
        _require_text(self.page_id, "page_id")
        _require_text(self.target_type, "target_type")
        _require_text(self.task_type, "task_type")
        _require_text(self.output_contract_version, "output_contract_version")
        _require_text(self.input_contract_version, "input_contract_version")
        _require_text(self.preprocessing_version, "preprocessing_version")
        _require_optional_text(self.target_element_id, "target_element_id")
        object.__setattr__(
            self,
            "required_outputs",
            _read_text_tuple(self.required_outputs, "required_outputs"),
        )
        if self.bbox is not None and not isinstance(self.bbox, BBox):
            raise ToolModelError("invalid_bbox", "bbox must be a BBox or None")
        if self.normalized_bbox is not None and not isinstance(
            self.normalized_bbox, BBox
        ):
            raise ToolModelError(
                "invalid_bbox",
                "normalized_bbox must be a BBox or None",
            )
        object.__setattr__(
            self,
            "context_element_ids",
            _read_text_tuple(self.context_element_ids, "context_element_ids"),
        )


@dataclass(frozen=True)
class SemanticInterpretationSummary:
    """Stable facade output for one structured interpretation."""

    interpretation_id: str
    recognition_run_id: str
    element_id: str
    element_type: str
    page_id: str | None
    summary: str
    analysis_status: str
    interpreted_type: str | None = None
    payload_ref: str | None = None
    cache_key: str | None = None
    contract_version: str = "1"
    image_hash: str | None = None
    model_profile: str | None = None
    model_version: str | None = None
    prompt_version: str | None = None
    created_at: str | None = None
    uncertainties: tuple[str, ...] = ()
    supported_by_observation_ids: tuple[str, ...] = ()
    fact_kind: str = "semantic_interpretation"
    evidence: Mapping[str, Any] = field(default_factory=dict)
    persisted: bool = False
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "interpretation_id",
            "recognition_run_id",
            "element_id",
            "element_type",
            "summary",
            "analysis_status",
            "contract_version",
        ):
            _require_text(getattr(self, field_name), field_name)
        _require_optional_text(self.page_id, "page_id")
        _require_optional_text(self.interpreted_type, "interpreted_type")
        _require_optional_text(self.payload_ref, "payload_ref")
        _require_optional_text(self.cache_key, "cache_key")
        for field_name in (
            "image_hash",
            "model_profile",
            "model_version",
            "prompt_version",
            "created_at",
        ):
            _require_optional_text(getattr(self, field_name), field_name)
        if self.fact_kind != "semantic_interpretation":
            raise ToolModelError(
                "invalid_fact_kind",
                "interpretation summaries must use fact_kind='semantic_interpretation'",
            )
        _require_mapping(self.evidence, "evidence")
        _require_boolean(self.persisted, "persisted")
        object.__setattr__(self, "uncertainties", _read_text_tuple(self.uncertainties, "uncertainties"))
        object.__setattr__(
            self,
            "supported_by_observation_ids",
            _read_text_tuple(self.supported_by_observation_ids, "supported_by_observation_ids"),
        )
        object.__setattr__(self, "evidence", MappingProxyType(dict(self.evidence)))
        object.__setattr__(self, "warnings", _read_text_tuple(self.warnings, "warnings"))


@dataclass(frozen=True)
class SemanticPayloadSummary:
    """Stable facade output for one immutable semantic payload."""

    payload_ref: str
    content_hash: str
    contract_version: str
    payload: Mapping[str, Any]
    fact_kind: str = "semantic_payload"
    status: str = "available"
    evidence: Mapping[str, Any] = field(default_factory=dict)
    persisted: bool = True
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("payload_ref", "content_hash", "contract_version", "status"):
            _require_text(getattr(self, field_name), field_name)
        _require_mapping(self.payload, "payload")
        if self.fact_kind != "semantic_payload":
            raise ToolModelError("invalid_fact_kind", "payload summaries must use fact_kind='semantic_payload'")
        _require_mapping(self.evidence, "evidence")
        _require_boolean(self.persisted, "persisted")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(self, "evidence", MappingProxyType(dict(self.evidence)))
        object.__setattr__(self, "warnings", _read_text_tuple(self.warnings, "warnings"))


@dataclass(frozen=True)
class SectionMatchSummary:
    """Stable facade output for a section-caption match judgment."""

    cross_section_id: str
    match_status: str
    logical_key: str | None = None
    symbol_system: str | None = None
    matched_caption_ids: tuple[str, ...] = ()
    candidate_count: int = 0
    conflict_reason: str | None = None
    observation_ids: tuple[str, ...] = ()
    rule_version: str | None = None
    alias_rule_id: str | None = None
    fact_kind: str = "candidate_relation"
    status: str = "candidate"
    evidence: Mapping[str, Any] = field(default_factory=dict)
    persisted: bool = False
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.cross_section_id, "cross_section_id")
        _require_text(self.match_status, "match_status")
        _require_optional_text(self.logical_key, "logical_key")
        _require_optional_text(self.symbol_system, "symbol_system")
        _require_optional_text(self.conflict_reason, "conflict_reason")
        _require_optional_text(self.rule_version, "rule_version")
        _require_optional_text(self.alias_rule_id, "alias_rule_id")
        if (
            not isinstance(self.candidate_count, int)
            or isinstance(self.candidate_count, bool)
            or self.candidate_count < 0
        ):
            raise ToolModelError("invalid_candidate_count", "candidate_count must be a non-negative integer")
        if self.fact_kind not in {"candidate_relation", "formal_relation"}:
            raise ToolModelError(
                "invalid_fact_kind",
                "section match fact_kind must be candidate_relation or formal_relation",
            )
        _require_text(self.status, "status")
        _require_mapping(self.evidence, "evidence")
        _require_boolean(self.persisted, "persisted")
        object.__setattr__(self, "matched_caption_ids", _read_text_tuple(self.matched_caption_ids, "matched_caption_ids"))
        object.__setattr__(self, "observation_ids", _read_text_tuple(self.observation_ids, "observation_ids"))
        object.__setattr__(self, "evidence", MappingProxyType(dict(self.evidence)))
        object.__setattr__(self, "warnings", _read_text_tuple(self.warnings, "warnings"))


@dataclass(frozen=True)
class SemanticCandidateRelationSummary:
    """Stable facade output for a candidate semantic relation."""

    candidate_group_id: str
    cross_section_id: str
    block_caption_id: str
    page_id: str
    status: str
    candidate_count: int = 1
    score: float | None = None
    conflict_reason: str | None = None
    observation_ids: tuple[str, ...] = ()
    rule_version: str | None = None
    recognition_run_id: str | None = None
    review_run_id: str | None = None
    fact_kind: str = "candidate_relation"
    evidence: Mapping[str, Any] = field(default_factory=dict)
    persisted: bool = False
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "candidate_group_id",
            "cross_section_id",
            "block_caption_id",
            "page_id",
            "status",
        ):
            _require_text(getattr(self, field_name), field_name)
        if (
            not isinstance(self.candidate_count, int)
            or isinstance(self.candidate_count, bool)
            or self.candidate_count < 1
        ):
            raise ToolModelError("invalid_candidate_count", "candidate_count must be a positive integer")
        if self.score is not None and (
            not isinstance(self.score, (int, float)) or isinstance(self.score, bool) or not 0 <= self.score <= 1
        ):
            raise ToolModelError("invalid_score", "score must be between 0 and 1 when provided")
        _require_optional_text(self.conflict_reason, "conflict_reason")
        _require_optional_text(self.rule_version, "rule_version")
        _require_optional_text(self.recognition_run_id, "recognition_run_id")
        _require_optional_text(self.review_run_id, "review_run_id")
        if self.fact_kind != "candidate_relation":
            raise ToolModelError(
                "invalid_fact_kind",
                "candidate relation summaries must use fact_kind='candidate_relation'",
            )
        _require_mapping(self.evidence, "evidence")
        _require_boolean(self.persisted, "persisted")
        object.__setattr__(self, "observation_ids", _read_text_tuple(self.observation_ids, "observation_ids"))
        object.__setattr__(self, "evidence", MappingProxyType(dict(self.evidence)))
        object.__setattr__(self, "warnings", _read_text_tuple(self.warnings, "warnings"))


def _coerce_error_code(value: ToolErrorCode | str) -> ToolErrorCode:
    try:
        return value if isinstance(value, ToolErrorCode) else ToolErrorCode(value)
    except ValueError as exc:
        raise ToolModelError("invalid_error_code", "code must be a supported ToolErrorCode") from exc


def _read_text_tuple(values: Any, field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
        raise ToolModelError("invalid_sequence", f"{field_name} must be a sequence of strings")
    for value in values:
        _require_text(value, field_name)
    return tuple(values)


def _require_normalized_bbox(bbox: BBox) -> None:
    if not all(0 <= getattr(bbox, field_name) <= 1 for field_name in ("x_min", "y_min", "x_max", "y_max")):
        raise ToolModelError("invalid_normalized_bbox", "normalized_bbox values must be between 0 and 1")


def _require_text(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ToolModelError("missing_required_field", f"{field_name} must be a non-empty string")


def _require_optional_text(value: Any, field_name: str) -> None:
    if value is not None:
        _require_text(value, field_name)


def _require_optional_non_negative_int(value: Any, field_name: str) -> None:
    if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
        raise ToolModelError("invalid_integer", f"{field_name} must be a non-negative integer")


def _require_mapping(value: Any, field_name: str) -> None:
    if not isinstance(value, Mapping):
        raise ToolModelError("invalid_mapping", f"{field_name} must be a mapping")


def _require_boolean(value: Any, field_name: str) -> None:
    if not isinstance(value, bool):
        raise ToolModelError("invalid_boolean", f"{field_name} must be a boolean")


__all__ = (
    "BBox",
    "BlockRelations",
    "BlockTrace",
    "CandidateRelationSummary",
    "CandidateReviewSummary",
    "DrawingSetSummary",
    "ElementEvidence",
    "PageSourceFacts",
    "PageSummary",
    "Pagination",
    "SectionMatchSummary",
    "SemanticCandidateRelationSummary",
    "SemanticInterpretationSummary",
    "SemanticObservationSummary",
    "SemanticPayloadSummary",
    "SemanticTargetInput",
    "ToolError",
    "ToolErrorCode",
    "ToolModelError",
)
