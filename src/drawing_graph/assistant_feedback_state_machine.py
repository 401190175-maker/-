"""Feedback state machine (08 feedback loop).

管理反馈状态迁移，防止非法跳转（如 ``received -> accepted``），并保证
``confirm/reject/correct`` 不进入 formal promotion、``request_review``
可进入 ``review_required``。每个合法迁移产生一条状态迁移记录。
"""

from __future__ import annotations

from dataclasses import dataclass

from .assistant_feedback_models import FeedbackAction, FeedbackStatus


class InvalidFeedbackTransitionError(ValueError):
    """非法状态迁移时抛出的稳定错误。"""


@dataclass(frozen=True)
class StateTransitionRecord:
    """一次状态迁移的稳定记录。"""

    from_status: FeedbackStatus
    to_status: FeedbackStatus
    event: str


_LINEAR_ORDER = (
    FeedbackStatus.RECEIVED,
    FeedbackStatus.VALIDATED,
    FeedbackStatus.RECORDED,
    FeedbackStatus.REVIEW_REQUIRED,
)

_RECORD_ACTIONS = frozenset(
    {
        FeedbackAction.CONFIRM,
        FeedbackAction.REJECT,
        FeedbackAction.CORRECT,
    }
)

_TERMINAL = frozenset(
    {
        FeedbackStatus.ACCEPTED,
        FeedbackStatus.REJECTED,
        FeedbackStatus.UNRESOLVED,
        FeedbackStatus.FORBIDDEN,
        FeedbackStatus.INVALID,
    }
)


def _coerce_action(action: FeedbackAction | str) -> FeedbackAction:
    if isinstance(action, FeedbackAction):
        return action
    if isinstance(action, str):
        try:
            return FeedbackAction(action)
        except ValueError as exc:
            raise InvalidFeedbackTransitionError(f"unknown feedback action: {action}") from exc
    raise InvalidFeedbackTransitionError("action must be a FeedbackAction or its stable string")


class FeedbackStateMachine:
    """反馈状态机：线性推进 received -> validated -> recorded -> review_required。"""

    def apply_action(
        self,
        current: FeedbackStatus | str,
        action: FeedbackAction | str,
    ) -> tuple[FeedbackStatus, tuple[StateTransitionRecord, ...]]:
        current = self._coerce_status(current)
        action = _coerce_action(action)

        if action in _RECORD_ACTIONS:
            target = FeedbackStatus.RECORDED
        else:  # request_review
            target = FeedbackStatus.REVIEW_REQUIRED

        return self._advance(current, target, action.value)

    def apply_review_result(
        self,
        current: FeedbackStatus | str,
        review_status: str,
    ) -> tuple[FeedbackStatus, tuple[StateTransitionRecord, ...]]:
        current = self._coerce_status(current)
        if current is not FeedbackStatus.REVIEW_REQUIRED:
            raise InvalidFeedbackTransitionError(
                f"review result requires review_required, got {current.value}"
            )
        if review_status not in {"accepted", "rejected", "unresolved"}:
            raise InvalidFeedbackTransitionError(f"invalid review status: {review_status}")
        target = FeedbackStatus(review_status)
        return target, (
            StateTransitionRecord(
                from_status=current,
                to_status=target,
                event=f"review:{review_status}",
            ),
        )

    @staticmethod
    def _coerce_status(status: FeedbackStatus | str) -> FeedbackStatus:
        if isinstance(status, FeedbackStatus):
            return status
        if isinstance(status, str):
            try:
                return FeedbackStatus(status)
            except ValueError as exc:
                raise InvalidFeedbackTransitionError(f"invalid status: {status}") from exc
        raise InvalidFeedbackTransitionError("status must be a FeedbackStatus or its stable string")

    def _advance(
        self,
        current: FeedbackStatus,
        target: FeedbackStatus,
        event: str,
    ) -> tuple[FeedbackStatus, tuple[StateTransitionRecord, ...]]:
        if current in _TERMINAL:
            raise InvalidFeedbackTransitionError(
                f"cannot advance from terminal status {current.value}"
            )
        if current not in _LINEAR_ORDER:
            raise InvalidFeedbackTransitionError(f"unknown current status {current.value}")

        current_index = _LINEAR_ORDER.index(current)
        target_index = _LINEAR_ORDER.index(target)

        if target_index < current_index:
            raise InvalidFeedbackTransitionError(
                f"cannot move backwards from {current.value} to {target.value}"
            )

        records = tuple(
            StateTransitionRecord(
                from_status=_LINEAR_ORDER[index],
                to_status=_LINEAR_ORDER[index + 1],
                event=event,
            )
            for index in range(current_index, target_index)
        )
        return target, records


__all__ = (
    "FeedbackStateMachine",
    "InvalidFeedbackTransitionError",
    "StateTransitionRecord",
)
