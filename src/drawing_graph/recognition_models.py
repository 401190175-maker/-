"""Pure DTO and enum contracts for the 04 multimodal recognition execution layer.

This module defines the stable execution contracts shared by task
registration, input validation, image preprocessing, prompt rendering,
provider attempts, output validation, metrics and redaction. It is a pure
contract module: it must not import provider clients, Neo4j, repositories,
HTTP/MCP/CLI adapters or read environment variables.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from .tool_models import SemanticTargetInput, ToolModelError


class RecognitionTaskType(str, Enum):
    """The seven first-version recognition task types."""

    PAGE_SUMMARY = "page_summary"
    ELEMENT_TEXT_OBSERVATION = "element_text_observation"
    BLOCK_SEMANTIC_IDENTIFICATION = "block_semantic_identification"
    BASIC_INFO_INTERPRETATION = "basic_info_interpretation"
    TABLE_INTERPRETATION = "table_interpretation"
    SECTION_LABEL_OBSERVATION = "section_label_observation"
    RELATION_EVIDENCE_EXTRACTION = "relation_evidence_extraction"


class RecognitionExecutionStatus(str, Enum):
    """Run/result-level status for one logical recognition execution."""

    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"
    CONTRACT_FAILED = "contract_failed"
    PROVIDER_FAILED = "provider_failed"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    RECOGNITION_FAILED = "recognition_failed"


class RecognitionAttemptStatus(str, Enum):
    """Status of one concrete provider call (attempt)."""

    SUCCEEDED = "succeeded"
    RETRYABLE_FAILED = "retryable_failed"
    TERMINAL_FAILED = "terminal_failed"
    CONTRACT_FAILED = "contract_failed"


class ProviderErrorCategory(str, Enum):
    """Stable provider error categories used for retry decisions."""

    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    RATE_LIMITED = "rate_limited"
    TEMPORARY = "temporary"
    TIMEOUT = "timeout"
    PERMANENT = "permanent"
    INVALID_RESPONSE = "invalid_response"


class UsageStatus(str, Enum):
    """Whether actual provider usage is available."""

    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class CostStatus(str, Enum):
    """Whether a cost value is calculated, estimated or unavailable."""

    CALCULATED = "calculated"
    ESTIMATED = "estimated"
    UNAVAILABLE = "unavailable"


class RecognitionImageRole(str, Enum):
    """Role of one prepared image sent to a provider."""

    TARGET = "target"
    CONTEXT = "context"
    PAGE = "page"


@dataclass(frozen=True)
class RecognitionExecutionPolicy:
    """Bounded execution policy for provider attempts, retry and budget.

    Callers may only tighten these limits through validation; the values are
    deliberately server-side defaults and never accept provider credentials.
    """

    max_attempts: int = 3
    structure_repair_attempts: int = 1
    deadline_seconds: float = 60.0
    base_backoff_ms: int = 250
    max_backoff_ms: int = 2000
    jitter_ratio: float = 0.1
    estimated_cost_budget: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.max_attempts, int) or isinstance(self.max_attempts, bool) or self.max_attempts < 1:
            raise ToolModelError("invalid_policy", "max_attempts must be a positive integer")
        if (
            not isinstance(self.structure_repair_attempts, int)
            or isinstance(self.structure_repair_attempts, bool)
            or self.structure_repair_attempts < 0
            or self.structure_repair_attempts >= self.max_attempts
        ):
            raise ToolModelError(
                "invalid_policy",
                "structure_repair_attempts must be non-negative and below max_attempts",
            )
        _require_positive_number(self.deadline_seconds, "deadline_seconds")
        _require_positive_number(self.base_backoff_ms, "base_backoff_ms")
        _require_positive_number(self.max_backoff_ms, "max_backoff_ms")
        if self.max_backoff_ms < self.base_backoff_ms:
            raise ToolModelError("invalid_policy", "max_backoff_ms must not be below base_backoff_ms")
        if not isinstance(self.jitter_ratio, (int, float)) or isinstance(self.jitter_ratio, bool):
            raise ToolModelError("invalid_policy", "jitter_ratio must be numeric")
        if not 0 <= self.jitter_ratio <= 1:
            raise ToolModelError("invalid_policy", "jitter_ratio must be between 0 and 1")
        if self.estimated_cost_budget is not None:
            _require_positive_number(self.estimated_cost_budget, "estimated_cost_budget")


@dataclass(frozen=True)
class RecognitionExecutionRequest:
    """Pre-validation input contract for one execution compatibility group.

    The request deliberately contains no image path, provider header,
    credential or arbitrary provider body; source paths are resolved from
    trusted PageSourceFacts by the semantic service and validated projection.
    """

    request_id: str
    recognition_run_id: str
    page_id: str
    task_type: RecognitionTaskType | str
    targets: tuple[SemanticTargetInput, ...]
    model_profile: str
    prompt_version: str
    input_contract_version: str = "1"
    output_contract_version: str = "1"
    preprocessing_version: str = "preprocess-v1"
    write_back: bool = False
    deadline_seconds: float = 60.0
    execution_policy: RecognitionExecutionPolicy | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "request_id",
            "recognition_run_id",
            "page_id",
            "model_profile",
            "prompt_version",
            "input_contract_version",
            "output_contract_version",
            "preprocessing_version",
        ):
            _require_text(getattr(self, field_name), field_name)
        object.__setattr__(self, "task_type", _coerce_task_type(self.task_type))
        if not isinstance(self.targets, tuple) or not self.targets:
            raise ToolModelError("invalid_targets", "targets must be a non-empty tuple")
        if not all(isinstance(target, SemanticTargetInput) for target in self.targets):
            raise ToolModelError("invalid_targets", "targets must contain SemanticTargetInput instances")
        if not isinstance(self.write_back, bool):
            raise ToolModelError("invalid_write_back", "write_back must be a boolean")
        _require_positive_number(self.deadline_seconds, "deadline_seconds")
        if self.execution_policy is not None and not isinstance(self.execution_policy, RecognitionExecutionPolicy):
            raise ToolModelError("invalid_policy", "execution_policy must be a RecognitionExecutionPolicy or None")


@dataclass(frozen=True)
class ValidatedRecognitionRequest:
    """Validated internal projection used by preprocessing and execution.

    ``image_path`` and ``image_size`` are resolved from trusted source facts
    and are internal-only: they are excluded from repr and must never reach
    provider DTOs, logs, payloads or errors.
    """

    request_id: str
    recognition_run_id: str
    page_id: str
    task_type: RecognitionTaskType
    targets: tuple[SemanticTargetInput, ...]
    model_profile: str
    prompt_version: str
    input_contract_version: str = "1"
    output_contract_version: str = "1"
    preprocessing_version: str = "preprocess-v1"
    write_back: bool = False
    deadline_seconds: float = 60.0
    image_path: str | None = field(default=None, repr=False)
    image_size: tuple[int, int] | None = None
    execution_policy: RecognitionExecutionPolicy | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "request_id",
            "recognition_run_id",
            "page_id",
            "model_profile",
            "prompt_version",
            "input_contract_version",
            "output_contract_version",
            "preprocessing_version",
        ):
            _require_text(getattr(self, field_name), field_name)
        object.__setattr__(self, "task_type", _coerce_task_type(self.task_type))
        if not isinstance(self.targets, tuple) or not self.targets:
            raise ToolModelError("invalid_targets", "targets must be a non-empty tuple")
        if not all(isinstance(target, SemanticTargetInput) for target in self.targets):
            raise ToolModelError("invalid_targets", "targets must contain SemanticTargetInput instances")
        if not isinstance(self.write_back, bool):
            raise ToolModelError("invalid_write_back", "write_back must be a boolean")
        _require_positive_number(self.deadline_seconds, "deadline_seconds")
        _require_optional_text(self.image_path, "image_path")
        if self.image_size is not None:
            if (
                not isinstance(self.image_size, tuple)
                or len(self.image_size) != 2
                or not all(isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in self.image_size)
            ):
                raise ToolModelError("invalid_image_size", "image_size must be a positive (width, height) tuple")
        if self.execution_policy is not None and not isinstance(self.execution_policy, RecognitionExecutionPolicy):
            raise ToolModelError("invalid_policy", "execution_policy must be a RecognitionExecutionPolicy or None")


@dataclass(frozen=True)
class RecognitionProviderUsage:
    """Actual provider usage reported by one attempt."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    image_units: int | None = None
    status: UsageStatus | str = UsageStatus.UNAVAILABLE

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _coerce_usage_status(self.status))
        for field_name in ("input_tokens", "output_tokens", "image_units"):
            value = getattr(self, field_name)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
                raise ToolModelError("invalid_usage", f"{field_name} must be a non-negative integer or None")


@dataclass(frozen=True)
class RecognitionAttempt:
    """One auditable provider call inside a logical recognition run.

    The attempt deliberately stores no image bytes, prompt, Authorization
    header, local path or traceback; only safe summaries and non-sensitive
    metadata are permitted.
    """

    attempt_id: str
    recognition_run_id: str
    attempt_number: int
    task_type: RecognitionTaskType | str
    provider: str
    model_name: str
    request_fingerprint: str
    prompt_version: str
    output_contract_version: str
    status: RecognitionAttemptStatus | str
    latency_ms: float = 0.0
    started_at: str | None = None
    finished_at: str | None = None
    retry_reason: str | None = None
    provider_request_id: str | None = None
    usage: RecognitionProviderUsage | None = None
    estimated_cost: float | None = None
    actual_cost: float | None = None
    currency: str | None = None
    rate_card_version: str | None = None
    error_category: ProviderErrorCategory | str | None = None
    safe_error_summary: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "attempt_id",
            "recognition_run_id",
            "provider",
            "model_name",
            "request_fingerprint",
            "prompt_version",
            "output_contract_version",
        ):
            _require_text(getattr(self, field_name), field_name)
        object.__setattr__(self, "task_type", _coerce_task_type(self.task_type))
        object.__setattr__(self, "status", _coerce_attempt_status(self.status))
        if not isinstance(self.attempt_number, int) or isinstance(self.attempt_number, bool) or self.attempt_number < 1:
            raise ToolModelError("invalid_attempt_number", "attempt_number must be a positive integer")
        _require_non_negative_number(self.latency_ms, "latency_ms")
        for field_name in ("started_at", "finished_at", "retry_reason", "provider_request_id", "currency", "rate_card_version", "safe_error_summary"):
            _require_optional_text(getattr(self, field_name), field_name)
        if self.usage is not None and not isinstance(self.usage, RecognitionProviderUsage):
            raise ToolModelError("invalid_usage", "usage must be a RecognitionProviderUsage or None")
        for field_name in ("estimated_cost", "actual_cost"):
            value = getattr(self, field_name)
            if value is not None:
                _require_non_negative_number(value, field_name)
        if self.error_category is not None:
            object.__setattr__(self, "error_category", _coerce_provider_error_category(self.error_category))


@dataclass(frozen=True)
class RecognitionCostSummary:
    """Run-level cost summary with explicit unavailable semantics."""

    status: CostStatus | str
    estimated_cost: float | None = None
    actual_cost: float | None = None
    currency: str | None = None
    rate_card_version: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        status = _coerce_cost_status(self.status)
        object.__setattr__(self, "status", status)
        for field_name in ("estimated_cost", "actual_cost"):
            value = getattr(self, field_name)
            if value is not None:
                _require_non_negative_number(value, field_name)
        _require_optional_text(self.currency, "currency")
        _require_optional_text(self.rate_card_version, "rate_card_version")
        _require_optional_text(self.reason, "reason")
        if status is CostStatus.CALCULATED and self.actual_cost is None:
            raise ToolModelError("invalid_cost", "calculated cost requires a numeric actual_cost")
        if status is CostStatus.ESTIMATED and self.actual_cost is not None:
            raise ToolModelError("invalid_cost", "estimated cost must keep actual_cost null")
        if status is CostStatus.UNAVAILABLE and self.actual_cost is not None:
            raise ToolModelError("invalid_cost", "unavailable cost must use null actual_cost, not zero")


@dataclass(frozen=True)
class RecognitionLatencySummary:
    """Separately traceable latency segments for one execution."""

    validation_ms: float = 0.0
    preprocessing_ms: float = 0.0
    provider_ms: float = 0.0
    backoff_ms: float = 0.0
    output_validation_ms: float = 0.0
    total_ms: float = 0.0

    def __post_init__(self) -> None:
        for field_name in (
            "validation_ms",
            "preprocessing_ms",
            "provider_ms",
            "backoff_ms",
            "output_validation_ms",
            "total_ms",
        ):
            _require_non_negative_number(getattr(self, field_name), field_name)


@dataclass(frozen=True)
class ValidatedRecognitionOutput:
    """Contract-validated business output for exactly one target."""

    task_type: RecognitionTaskType | str
    target_id: str
    target_type: str
    status: RecognitionExecutionStatus | str
    output: Mapping[str, Any]
    confidence: float | None = None
    uncertainties: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_type", _coerce_task_type(self.task_type))
        _require_text(self.target_id, "target_id")
        _require_text(self.target_type, "target_type")
        object.__setattr__(self, "status", _coerce_execution_status(self.status))
        if not isinstance(self.output, Mapping):
            raise ToolModelError("invalid_output", "output must be a mapping")
        object.__setattr__(self, "output", MappingProxyType(dict(self.output)))
        if self.confidence is not None:
            if not isinstance(self.confidence, (int, float)) or isinstance(self.confidence, bool):
                raise ToolModelError("invalid_confidence", "confidence must be numeric")
            if not 0 <= self.confidence <= 1:
                raise ToolModelError("invalid_confidence", "confidence must be between 0 and 1")
        object.__setattr__(self, "uncertainties", _read_text_tuple(self.uncertainties, "uncertainties"))


@dataclass(frozen=True)
class RecognitionCandidateEvidence:
    """Relation evidence that can only stay at candidate level."""

    relation_type: str
    source_target_id: str
    supporting_target_ids: tuple[str, ...] = ()
    confidence: float | None = None
    status: str = "candidate_relation"

    def __post_init__(self) -> None:
        _require_text(self.relation_type, "relation_type")
        _require_text(self.source_target_id, "source_target_id")
        object.__setattr__(
            self,
            "supporting_target_ids",
            _read_text_tuple(self.supporting_target_ids, "supporting_target_ids"),
        )
        if self.confidence is not None:
            if not isinstance(self.confidence, (int, float)) or isinstance(self.confidence, bool):
                raise ToolModelError("invalid_confidence", "confidence must be numeric")
            if not 0 <= self.confidence <= 1:
                raise ToolModelError("invalid_confidence", "confidence must be between 0 and 1")
        status = str(self.status).strip().lower()
        if status != "candidate_relation":
            raise ToolModelError("invalid_fact_level", "relation evidence must use candidate_relation status")
        object.__setattr__(self, "status", status)


@dataclass(frozen=True)
class RecognitionExecutionResult:
    """Safe execution summary returned by the 04 execution layer."""

    recognition_run_id: str
    status: RecognitionExecutionStatus | str
    validated_outputs: tuple[ValidatedRecognitionOutput, ...] = ()
    candidate_evidence: tuple[RecognitionCandidateEvidence, ...] = ()
    attempts: tuple[RecognitionAttempt, ...] = ()
    usage_summary: RecognitionProviderUsage | None = None
    cost_summary: RecognitionCostSummary | None = None
    latency_summary: RecognitionLatencySummary | None = None
    payload_ref: str | None = None
    warnings: tuple[str, ...] = ()
    safe_error: Mapping[str, Any] | None = None
    persisted: bool = False

    def __post_init__(self) -> None:
        _require_text(self.recognition_run_id, "recognition_run_id")
        object.__setattr__(self, "status", _coerce_execution_status(self.status))
        _require_tuple_of(self.validated_outputs, ValidatedRecognitionOutput, "validated_outputs")
        _require_tuple_of(self.candidate_evidence, RecognitionCandidateEvidence, "candidate_evidence")
        _require_tuple_of(self.attempts, RecognitionAttempt, "attempts")
        for field_name in ("usage_summary", "cost_summary", "latency_summary"):
            value = getattr(self, field_name)
            if value is not None and not isinstance(
                value,
                (RecognitionProviderUsage, RecognitionCostSummary, RecognitionLatencySummary),
            ):
                raise ToolModelError("invalid_summary", f"{field_name} has an unsupported summary type")
        _require_optional_text(self.payload_ref, "payload_ref")
        object.__setattr__(self, "warnings", _read_text_tuple(self.warnings, "warnings"))
        if self.safe_error is not None and not isinstance(self.safe_error, Mapping):
            raise ToolModelError("invalid_safe_error", "safe_error must be a mapping or None")
        if self.safe_error is not None:
            object.__setattr__(self, "safe_error", MappingProxyType(dict(self.safe_error)))
        if not isinstance(self.persisted, bool):
            raise ToolModelError("invalid_persisted", "persisted must be a boolean")


def _coerce_task_type(value: RecognitionTaskType | str) -> RecognitionTaskType:
    try:
        return value if isinstance(value, RecognitionTaskType) else RecognitionTaskType(value)
    except ValueError as exc:
        raise ToolModelError("invalid_task_type", "unsupported recognition task type") from exc


def _coerce_execution_status(value: RecognitionExecutionStatus | str) -> RecognitionExecutionStatus:
    try:
        return value if isinstance(value, RecognitionExecutionStatus) else RecognitionExecutionStatus(value)
    except ValueError as exc:
        raise ToolModelError("invalid_execution_status", "unsupported recognition execution status") from exc


def _coerce_attempt_status(value: RecognitionAttemptStatus | str) -> RecognitionAttemptStatus:
    try:
        return value if isinstance(value, RecognitionAttemptStatus) else RecognitionAttemptStatus(value)
    except ValueError as exc:
        raise ToolModelError("invalid_attempt_status", "unsupported recognition attempt status") from exc


def _coerce_provider_error_category(value: ProviderErrorCategory | str) -> ProviderErrorCategory:
    try:
        return value if isinstance(value, ProviderErrorCategory) else ProviderErrorCategory(value)
    except ValueError as exc:
        raise ToolModelError("invalid_provider_error_category", "unsupported provider error category") from exc


def _coerce_usage_status(value: UsageStatus | str) -> UsageStatus:
    try:
        return value if isinstance(value, UsageStatus) else UsageStatus(value)
    except ValueError as exc:
        raise ToolModelError("invalid_usage_status", "unsupported usage status") from exc


def _coerce_cost_status(value: CostStatus | str) -> CostStatus:
    try:
        return value if isinstance(value, CostStatus) else CostStatus(value)
    except ValueError as exc:
        raise ToolModelError("invalid_cost_status", "unsupported cost status") from exc


def _read_text_tuple(values: Any, field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
        raise ToolModelError("invalid_sequence", f"{field_name} must be a sequence of strings")
    for value in values:
        _require_text(value, field_name)
    return tuple(values)


def _require_tuple_of(values: Any, expected: type, field_name: str) -> None:
    if not isinstance(values, tuple) or not all(isinstance(value, expected) for value in values):
        raise ToolModelError("invalid_sequence", f"{field_name} must be a tuple of {expected.__name__}")


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolModelError("missing_required_field", f"{field_name} must be a non-empty string")
    return value


def _require_optional_text(value: Any, field_name: str) -> None:
    if value is not None:
        _require_text(value, field_name)


def _require_positive_number(value: Any, field_name: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise ToolModelError("invalid_number", f"{field_name} must be a positive number")


def _require_non_negative_number(value: Any, field_name: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise ToolModelError("invalid_number", f"{field_name} must be a non-negative number")


__all__ = (
    "CostStatus",
    "ProviderErrorCategory",
    "RecognitionAttempt",
    "RecognitionAttemptStatus",
    "RecognitionCandidateEvidence",
    "RecognitionCostSummary",
    "RecognitionExecutionStatus",
    "RecognitionExecutionPolicy",
    "RecognitionExecutionRequest",
    "RecognitionExecutionResult",
    "RecognitionImageRole",
    "RecognitionLatencySummary",
    "RecognitionProviderUsage",
    "RecognitionTaskType",
    "UsageStatus",
    "ValidatedRecognitionOutput",
    "ValidatedRecognitionRequest",
)
