"""Feedback DTO contracts (08 feedback loop).

本模块定义反馈 action、状态、权限意图、审计事件和反馈结果 DTO。DTO
只承载稳定数据，不依赖 repository、查询语言、图数据库 driver，也不保存未
脱敏异常、secret、URI、完整 payload、完整 prompt 或 traceback。

``FeedbackEvent``（薄版）仍保留在 ``assistant_models`` 中作为反馈输入
事件载体，本模块不重复定义。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FeedbackAction(str, Enum):
    """用户反馈的稳定 action 集合。"""

    CONFIRM = "confirm"
    REJECT = "reject"
    CORRECT = "correct"
    REQUEST_REVIEW = "request_review"


class FeedbackStatus(str, Enum):
    """反馈处理的稳定状态集合。"""

    RECEIVED = "received"
    VALIDATED = "validated"
    RECORDED = "recorded"
    REVIEW_REQUIRED = "review_required"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNRESOLVED = "unresolved"
    FORBIDDEN = "forbidden"
    INVALID = "invalid"


class FeedbackPermission(str, Enum):
    """反馈相关权限意图，正式关系提升权限永远不会由反馈 action 授予。"""

    READ_TRACE = "read_trace"
    RECORD_FEEDBACK = "record_feedback"
    REQUEST_CANDIDATE_REVIEW = "request_candidate_review"
    PROMOTE_FORMAL_RELATION = "promote_formal_relation"


def _require_text(value: str | None, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _require_optional_text(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be None or a non-empty string")
    return value


def _require_text_tuple(values: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(values, tuple) or not all(
        isinstance(item, str) and item.strip() for item in values
    ):
        raise ValueError(f"{field_name} must be a tuple of non-empty strings")
    return values


def _coerce_enum(enum_type: type[Enum], value: object, field_name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        try:
            return enum_type(value)
        except ValueError as exc:
            raise ValueError(f"{field_name} is not a valid {enum_type.__name__}") from exc
    raise ValueError(f"{field_name} must be a {enum_type.__name__} or its stable string")


@dataclass(frozen=True)
class FeedbackAuditEvent:
    """append-only 审计事件，记录状态迁移或关键处理动作，不含未脱敏异常。"""

    audit_event_id: str
    feedback_id: str
    request_id: str | None = None
    event_type: str = "transition"
    from_status: FeedbackStatus | str | None = None
    to_status: FeedbackStatus | str | None = None
    actor_id: str | None = None
    detail: str | None = None
    created_at: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.audit_event_id, "audit_event_id")
        _require_text(self.feedback_id, "feedback_id")
        _require_optional_text(self.request_id, "request_id")
        _require_text(self.event_type, "event_type")
        if self.from_status is not None:
            object.__setattr__(
                self,
                "from_status",
                _coerce_enum(FeedbackStatus, self.from_status, "from_status"),
            )
        if self.to_status is not None:
            object.__setattr__(
                self,
                "to_status",
                _coerce_enum(FeedbackStatus, self.to_status, "to_status"),
            )
        _require_optional_text(self.actor_id, "actor_id")
        _require_optional_text(self.detail, "detail")
        _require_optional_text(self.created_at, "created_at")


@dataclass(frozen=True)
class FeedbackResult:
    """一次反馈提交的稳定处理结果，不含 repository、Cypher 或 driver 引用。"""

    feedback_id: str
    status: FeedbackStatus | str = FeedbackStatus.RECEIVED
    affected_claim_ids: tuple[str, ...] = field(default_factory=tuple)
    candidate_review_request_id: str | None = None
    candidate_review_result: Any = None
    new_evidence_request: str | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)
    audit_event_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _require_text(self.feedback_id, "feedback_id")
        object.__setattr__(self, "status", _coerce_enum(FeedbackStatus, self.status, "status"))
        object.__setattr__(
            self,
            "affected_claim_ids",
            _require_text_tuple(self.affected_claim_ids, "affected_claim_ids"),
        )
        _require_optional_text(self.candidate_review_request_id, "candidate_review_request_id")
        _require_optional_text(self.new_evidence_request, "new_evidence_request")
        object.__setattr__(self, "warnings", _require_text_tuple(self.warnings, "warnings"))
        object.__setattr__(
            self,
            "audit_event_ids",
            _require_text_tuple(self.audit_event_ids, "audit_event_ids"),
        )


__all__ = (
    "FeedbackAction",
    "FeedbackAuditEvent",
    "FeedbackPermission",
    "FeedbackResult",
    "FeedbackStatus",
)
