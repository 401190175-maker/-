"""Semantic evidence DTOs for recognition outputs and candidate facts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from .recognition_models import RecognitionLatencySummary, RecognitionProviderUsage
from .tool_models import BBox, ToolModelError


class ObservationStatus(str, Enum):
    """Status of a text observation.

    ``matched_candidate`` is a provisional candidate status produced by a
    model; it is not a formal graph fact and must not be projected as one.
    """

    CONFIRMED = "confirmed"
    MATCHED_CANDIDATE = "matched_candidate"
    PARTIAL = "partial"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"
    RECOGNITION_FAILED = "recognition_failed"
    STALE = "stale"


class RecognitionRunStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"


class InterpretationStatus(str, Enum):
    """Status of a structured semantic interpretation."""

    INTERPRETED = "interpreted"
    PARTIAL = "partial"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"
    FAILED = "failed"
    STALE = "stale"


@dataclass(frozen=True)
class TextObservation:
    """Graph-internal text observation produced by a recognition run.

    The observation records what a model read from one source element or
    local region. It never overwrites source-fact nodes, and its status
    ``matched_candidate`` is explicitly not a formal graph fact.
    """

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
    status: ObservationStatus | str
    image_hash: str | None = None
    cache_key: str | None = None
    model_profile: str = "default"
    prompt_version: str = "default"
    input_contract_version: str = "1"
    output_contract_version: str = "1"
    preprocessing_version: str = "preprocess-v1"
    created_at: str | None = None
    evidence_family_key: str | None = None
    normalization_rule_version: str | None = None
    superseded_by_evidence_id: str | None = None
    stale_reason: str | None = None
    stale_at: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "observation_id",
            "recognition_run_id",
            "target_element_id",
            "target_element_type",
            "page_id",
            "raw_text",
            "normalized_text",
            "model_profile",
            "prompt_version",
            "input_contract_version",
            "output_contract_version",
            "preprocessing_version",
        ):
            _require_text(getattr(self, field_name), field_name)
        status = _coerce_observation_status(self.status)
        if not isinstance(self.confidence, (int, float)) or isinstance(self.confidence, bool):
            raise ToolModelError("invalid_confidence", "confidence must be numeric")
        if not 0 <= self.confidence <= 1:
            raise ToolModelError("invalid_confidence", "confidence must be between 0 and 1")
        if not isinstance(self.bbox, BBox) or not isinstance(self.normalized_bbox, BBox):
            raise ToolModelError("invalid_bbox", "bbox and normalized_bbox must be BBox instances")
        _require_normalized_bbox(self.normalized_bbox)
        _require_optional_text(self.image_hash, "image_hash")
        _require_optional_text(self.cache_key, "cache_key")
        _require_optional_text(self.created_at, "created_at")
        for field_name in (
            "evidence_family_key",
            "normalization_rule_version",
            "superseded_by_evidence_id",
            "stale_reason",
            "stale_at",
        ):
            _require_optional_text(getattr(self, field_name), field_name)
        object.__setattr__(self, "status", status)


@dataclass(frozen=True)
class BlockInterpretation:
    """Structured interpretation of one DrawingBlock.

    ``interpreted_type`` is an AI judgment about the block and must never be
    written back to the source-fact field ``DrawingBlock.block_type``.
    """

    interpretation_id: str
    recognition_run_id: str
    block_id: str
    summary: str
    page_id: str | None = None
    interpreted_type: str | None = None
    components: tuple[str, ...] = ()
    materials: tuple[str, ...] = ()
    dimensions: tuple[str, ...] = ()
    construction_features: tuple[str, ...] = ()
    spatial_relations: tuple[str, ...] = ()
    analysis_status: InterpretationStatus | str = InterpretationStatus.INTERPRETED
    uncertainties: tuple[str, ...] = ()
    supported_by_observation_ids: tuple[str, ...] = ()
    payload_ref: str | None = None
    cache_key: str | None = None
    contract_version: str = "1"
    model_profile: str = "default"
    prompt_version: str = "default"
    input_contract_version: str = "1"
    preprocessing_version: str = "preprocess-v1"
    evidence_family_key: str | None = None
    supersedes_evidence_ids: tuple[str, ...] = ()
    superseded_by_evidence_id: str | None = None
    stale_reason: str | None = None
    stale_at: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "interpretation_id",
            "recognition_run_id",
            "block_id",
            "summary",
            "contract_version",
            "model_profile",
            "prompt_version",
            "input_contract_version",
            "preprocessing_version",
        ):
            _require_text(getattr(self, field_name), field_name)
        _require_optional_text(self.page_id, "page_id")
        _require_optional_text(self.interpreted_type, "interpreted_type")
        for field_name in ("components", "materials", "dimensions", "construction_features", "spatial_relations"):
            object.__setattr__(self, field_name, _read_text_tuple(getattr(self, field_name), field_name))
        object.__setattr__(self, "uncertainties", _read_text_tuple(self.uncertainties, "uncertainties"))
        object.__setattr__(
            self,
            "supported_by_observation_ids",
            _read_text_tuple(self.supported_by_observation_ids, "supported_by_observation_ids"),
        )
        _require_optional_text(self.payload_ref, "payload_ref")
        _require_optional_text(self.cache_key, "cache_key")
        object.__setattr__(self, "analysis_status", _coerce_interpretation_status(self.analysis_status))
        _require_optional_text(self.evidence_family_key, "evidence_family_key")
        object.__setattr__(
            self,
            "supersedes_evidence_ids",
            _read_text_tuple(self.supersedes_evidence_ids, "supersedes_evidence_ids"),
        )
        for field_name in ("superseded_by_evidence_id", "stale_reason", "stale_at"):
            _require_optional_text(getattr(self, field_name), field_name)


@dataclass(frozen=True)
class BasicInfoInterpretation:
    """Structured interpretation of one DrawingBasicInfo source fact."""

    interpretation_id: str
    recognition_run_id: str
    basic_info_id: str
    raw_text: str
    summary: str
    page_id: str | None = None
    project_name: str | None = None
    drawing_name: str | None = None
    discipline: str | None = None
    drawing_number: str | None = None
    scale: str | None = None
    date: str | None = None
    analysis_status: InterpretationStatus | str = InterpretationStatus.INTERPRETED
    uncertainties: tuple[str, ...] = ()
    supported_by_observation_ids: tuple[str, ...] = ()
    payload_ref: str | None = None
    cache_key: str | None = None
    contract_version: str = "1"
    model_profile: str = "default"
    prompt_version: str = "default"
    input_contract_version: str = "1"
    preprocessing_version: str = "preprocess-v1"
    evidence_family_key: str | None = None
    supersedes_evidence_ids: tuple[str, ...] = ()
    superseded_by_evidence_id: str | None = None
    stale_reason: str | None = None
    stale_at: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "interpretation_id",
            "recognition_run_id",
            "basic_info_id",
            "raw_text",
            "summary",
            "contract_version",
            "model_profile",
            "prompt_version",
            "input_contract_version",
            "preprocessing_version",
        ):
            _require_text(getattr(self, field_name), field_name)
        _require_optional_text(self.page_id, "page_id")
        for field_name in (
            "project_name",
            "drawing_name",
            "discipline",
            "drawing_number",
            "scale",
            "date",
        ):
            _require_optional_text(getattr(self, field_name), field_name)
        object.__setattr__(self, "uncertainties", _read_text_tuple(self.uncertainties, "uncertainties"))
        object.__setattr__(
            self,
            "supported_by_observation_ids",
            _read_text_tuple(self.supported_by_observation_ids, "supported_by_observation_ids"),
        )
        _require_optional_text(self.payload_ref, "payload_ref")
        _require_optional_text(self.cache_key, "cache_key")
        object.__setattr__(self, "analysis_status", _coerce_interpretation_status(self.analysis_status))
        _require_optional_text(self.evidence_family_key, "evidence_family_key")
        object.__setattr__(
            self,
            "supersedes_evidence_ids",
            _read_text_tuple(self.supersedes_evidence_ids, "supersedes_evidence_ids"),
        )
        for field_name in ("superseded_by_evidence_id", "stale_reason", "stale_at"):
            _require_optional_text(getattr(self, field_name), field_name)


@dataclass(frozen=True)
class TableInterpretation:
    """Structured interpretation of one Table source fact."""

    interpretation_id: str
    recognition_run_id: str
    table_id: str
    summary: str
    page_id: str | None = None
    caption_ref: str | None = None
    analysis_status: InterpretationStatus | str = InterpretationStatus.INTERPRETED
    uncertainties: tuple[str, ...] = ()
    supported_by_observation_ids: tuple[str, ...] = ()
    payload_ref: str | None = None
    cache_key: str | None = None
    contract_version: str = "1"
    model_profile: str = "default"
    prompt_version: str = "default"
    input_contract_version: str = "1"
    preprocessing_version: str = "preprocess-v1"
    evidence_family_key: str | None = None
    supersedes_evidence_ids: tuple[str, ...] = ()
    superseded_by_evidence_id: str | None = None
    stale_reason: str | None = None
    stale_at: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "interpretation_id",
            "recognition_run_id",
            "table_id",
            "summary",
            "contract_version",
            "model_profile",
            "prompt_version",
            "input_contract_version",
            "preprocessing_version",
        ):
            _require_text(getattr(self, field_name), field_name)
        _require_optional_text(self.page_id, "page_id")
        _require_optional_text(self.caption_ref, "caption_ref")
        object.__setattr__(self, "uncertainties", _read_text_tuple(self.uncertainties, "uncertainties"))
        object.__setattr__(
            self,
            "supported_by_observation_ids",
            _read_text_tuple(self.supported_by_observation_ids, "supported_by_observation_ids"),
        )
        _require_optional_text(self.payload_ref, "payload_ref")
        _require_optional_text(self.cache_key, "cache_key")
        object.__setattr__(self, "analysis_status", _coerce_interpretation_status(self.analysis_status))
        _require_optional_text(self.evidence_family_key, "evidence_family_key")
        object.__setattr__(
            self,
            "supersedes_evidence_ids",
            _read_text_tuple(self.supersedes_evidence_ids, "supersedes_evidence_ids"),
        )
        for field_name in ("superseded_by_evidence_id", "stale_reason", "stale_at"):
            _require_optional_text(getattr(self, field_name), field_name)


@dataclass(frozen=True)
class RecognitionRunSummary:
    recognition_run_id: str
    run_type: str
    page_id: str
    model_profile: str
    prompt_version: str
    status: RecognitionRunStatus | str
    write_back: bool
    model_name: str | None = None
    model_version: str | None = None
    error_summary: str | None = None
    input_refs: Mapping[str, Any] = field(default_factory=dict)
    started_at: str | None = None
    finished_at: str | None = None
    target_scope: str | None = None
    cost_summary: Mapping[str, Any] | None = None
    attempt_ids: tuple[str, ...] = ()
    usage_summary: RecognitionProviderUsage | None = None
    latency_summary: RecognitionLatencySummary | None = None
    input_contract_version: str = "1"
    output_contract_version: str = "1"
    preprocessing_version: str = "preprocess-v1"
    payload_ref: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "recognition_run_id",
            "run_type",
            "page_id",
            "model_profile",
            "prompt_version",
            "input_contract_version",
            "output_contract_version",
            "preprocessing_version",
        ):
            _require_text(getattr(self, field_name), field_name)
        if self.run_type not in {"recognition", "interpretation", "candidate_review"}:
            raise ToolModelError("invalid_run_type", "run_type must be a supported recognition run type")
        status = _coerce_run_status(self.status)
        if not isinstance(self.write_back, bool):
            raise ToolModelError("invalid_write_back", "write_back must be a boolean")
        for field_name in (
            "model_name",
            "model_version",
            "error_summary",
            "started_at",
            "finished_at",
            "target_scope",
        ):
            _require_optional_text(getattr(self, field_name), field_name)
        if not isinstance(self.input_refs, Mapping):
            raise ToolModelError("invalid_input_refs", "input_refs must be a mapping")
        if self.cost_summary is not None and not isinstance(self.cost_summary, Mapping):
            raise ToolModelError("invalid_cost_summary", "cost_summary must be a mapping when provided")
        object.__setattr__(self, "attempt_ids", _read_text_tuple(self.attempt_ids, "attempt_ids"))
        if self.usage_summary is not None and not isinstance(self.usage_summary, RecognitionProviderUsage):
            raise ToolModelError("invalid_usage_summary", "usage_summary must be a RecognitionProviderUsage or None")
        if self.latency_summary is not None and not isinstance(self.latency_summary, RecognitionLatencySummary):
            raise ToolModelError(
                "invalid_latency_summary",
                "latency_summary must be a RecognitionLatencySummary or None",
            )
        _require_optional_text(self.payload_ref, "payload_ref")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "input_refs", MappingProxyType(dict(self.input_refs)))
        if self.cost_summary is not None:
            object.__setattr__(self, "cost_summary", MappingProxyType(dict(self.cost_summary)))


@dataclass(frozen=True)
class PageSummaryResult:
    """Transient page-summary output; never becomes a graph node."""

    recognition_run_id: str
    page_id: str
    summary: str
    key_elements: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("recognition_run_id", "page_id", "summary"):
            _require_text(getattr(self, field_name), field_name)
        object.__setattr__(self, "key_elements", _read_text_tuple(self.key_elements, "key_elements"))
        object.__setattr__(self, "uncertainties", _read_text_tuple(self.uncertainties, "uncertainties"))


@dataclass(frozen=True)
class CandidateSemanticRelation:
    candidate_group_id: str
    relation_type: str
    status: str
    score: float | None = None
    conflict_reason: str | None = None
    evidence_ids: tuple[str, ...] = ()
    recognition_run_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("candidate_group_id", "relation_type", "status"):
            _require_text(getattr(self, field_name), field_name)
        if self.score is not None and (
            not isinstance(self.score, (int, float)) or isinstance(self.score, bool) or not 0 <= self.score <= 1
        ):
            raise ToolModelError("invalid_score", "score must be between 0 and 1 when provided")
        _require_optional_text(self.conflict_reason, "conflict_reason")
        _require_optional_text(self.recognition_run_id, "recognition_run_id")
        object.__setattr__(self, "evidence_ids", _read_text_tuple(self.evidence_ids, "evidence_ids"))


def _coerce_observation_status(value: ObservationStatus | str) -> ObservationStatus:
    try:
        return value if isinstance(value, ObservationStatus) else ObservationStatus(value)
    except ValueError as exc:
        raise ToolModelError("invalid_observation_status", "unsupported observation status") from exc


def _coerce_run_status(value: RecognitionRunStatus | str) -> RecognitionRunStatus:
    try:
        return value if isinstance(value, RecognitionRunStatus) else RecognitionRunStatus(value)
    except ValueError as exc:
        raise ToolModelError("invalid_run_status", "unsupported recognition run status") from exc


def _coerce_interpretation_status(value: InterpretationStatus | str) -> InterpretationStatus:
    try:
        return value if isinstance(value, InterpretationStatus) else InterpretationStatus(value)
    except ValueError as exc:
        raise ToolModelError("invalid_interpretation_status", "unsupported interpretation status") from exc


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


__all__ = (
    "BasicInfoInterpretation",
    "BlockInterpretation",
    "CandidateSemanticRelation",
    "InterpretationStatus",
    "ObservationStatus",
    "PageSummaryResult",
    "RecognitionRunStatus",
    "RecognitionRunSummary",
    "TableInterpretation",
    "TextObservation",
)
