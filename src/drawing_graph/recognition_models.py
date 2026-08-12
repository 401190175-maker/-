"""Pure DTO and enum contracts for the 04 multimodal recognition execution layer.

This module defines the stable execution contracts shared by task
registration, input validation, image preprocessing, prompt rendering,
provider attempts, output validation, metrics and redaction. It is a pure
contract module: it must not import provider clients, Neo4j, repositories,
HTTP/MCP/CLI adapters or read environment variables.
"""

from __future__ import annotations

from enum import Enum


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


__all__ = (
    "CostStatus",
    "ProviderErrorCategory",
    "RecognitionAttemptStatus",
    "RecognitionExecutionStatus",
    "RecognitionImageRole",
    "RecognitionTaskType",
    "UsageStatus",
)
