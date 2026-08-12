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
from typing import Any

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


def _coerce_task_type(value: RecognitionTaskType | str) -> RecognitionTaskType:
    try:
        return value if isinstance(value, RecognitionTaskType) else RecognitionTaskType(value)
    except ValueError as exc:
        raise ToolModelError("invalid_task_type", "unsupported recognition task type") from exc


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


__all__ = (
    "CostStatus",
    "ProviderErrorCategory",
    "RecognitionAttemptStatus",
    "RecognitionExecutionStatus",
    "RecognitionExecutionPolicy",
    "RecognitionExecutionRequest",
    "RecognitionImageRole",
    "RecognitionTaskType",
    "UsageStatus",
    "ValidatedRecognitionRequest",
)
