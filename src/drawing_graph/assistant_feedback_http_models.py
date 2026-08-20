"""HTTP request/response models for the product feedback API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from .assistant_feedback_models import FeedbackResult


_ACTIONS = frozenset({"confirm", "reject", "correct", "request_review"})


class HttpFeedbackRequest(BaseModel):
    """Validated feedback submission payload."""

    action: str
    claim_id: str = Field(min_length=1)
    feedback_id: str | None = None
    request_id: str | None = None
    reason: str | None = None
    correction: str | None = None

    @field_validator("action")
    @classmethod
    def _validate_action(cls, value: str) -> str:
        if value not in _ACTIONS:
            raise ValueError(f"action must be one of {sorted(_ACTIONS)}")
        return value


def feedback_result_to_data(result: FeedbackResult) -> dict[str, Any]:
    """Serialize a FeedbackResult into a stable HTTP data payload."""

    return {
        "feedback_id": result.feedback_id,
        "status": result.status.value
        if hasattr(result.status, "value")
        else str(result.status),
        "affected_claim_ids": list(result.affected_claim_ids),
        "warnings": list(result.warnings),
    }
