"""Feedback store port and append-only in-memory implementation (08 feedback loop).

本模块提供反馈事件与审计事件的 append-only 内存 store。重复 feedback_id
不静默覆盖；store 不访问图数据库，不做业务写回。
"""

from __future__ import annotations

from typing import Protocol

from .assistant_feedback_models import FeedbackAuditEvent, FeedbackStatus
from .assistant_models import FeedbackEvent


class FeedbackStorePort(Protocol):
    """产品反馈 store 的稳定端口，反馈与审计均 append-only。"""

    def append_feedback(self, event: FeedbackEvent) -> None: ...

    def append_audit(self, audit: FeedbackAuditEvent) -> None: ...

    def get_feedback(self, feedback_id: str) -> FeedbackEvent | None: ...

    def list_feedback_for_request(self, request_id: str) -> tuple[FeedbackEvent, ...]: ...

    def list_audit(self, feedback_id: str) -> tuple[FeedbackAuditEvent, ...]: ...

    def set_status(self, feedback_id: str, status: FeedbackStatus) -> None: ...

    def get_status(self, feedback_id: str) -> FeedbackStatus | None: ...


class InMemoryFeedbackStore:
    """append-only 进程内反馈 store，不覆盖旧事件、不持久化。"""

    def __init__(self) -> None:
        self._feedback: dict[str, FeedbackEvent] = {}
        self._audit: dict[str, list[FeedbackAuditEvent]] = {}
        self._statuses: dict[str, FeedbackStatus] = {}

    def append_feedback(self, event: FeedbackEvent) -> None:
        if not isinstance(event, FeedbackEvent):
            raise ValueError("event must be a FeedbackEvent")
        if event.feedback_id in self._feedback:
            raise ValueError(f"feedback {event.feedback_id} already exists")
        self._feedback[event.feedback_id] = event

    def append_audit(self, audit: FeedbackAuditEvent) -> None:
        if not isinstance(audit, FeedbackAuditEvent):
            raise ValueError("audit must be a FeedbackAuditEvent")
        self._audit.setdefault(audit.feedback_id, []).append(audit)

    def get_feedback(self, feedback_id: str) -> FeedbackEvent | None:
        return self._feedback.get(feedback_id)

    def list_feedback_for_request(self, request_id: str) -> tuple[FeedbackEvent, ...]:
        return tuple(
            event
            for event in self._feedback.values()
            if event.request_id == request_id
        )

    def list_audit(self, feedback_id: str) -> tuple[FeedbackAuditEvent, ...]:
        return tuple(self._audit.get(feedback_id, ()))

    def set_status(self, feedback_id: str, status: FeedbackStatus) -> None:
        if not isinstance(status, FeedbackStatus):
            raise ValueError("status must be a FeedbackStatus")
        self._statuses[feedback_id] = status

    def get_status(self, feedback_id: str) -> FeedbackStatus | None:
        return self._statuses.get(feedback_id)


__all__ = ("InMemoryFeedbackStore", "FeedbackStorePort")
