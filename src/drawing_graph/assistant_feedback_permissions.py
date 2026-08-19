"""Feedback permission policy (08 feedback loop).

根据 actor、action 和请求授权判断是否允许记录反馈、发起候选审核或触发
下游写操作。默认 fail-closed：没有权限或 ``allow_write_back=false`` 时
不能记录反馈、不能发起候选审核；``promote_formal_relation`` 永远不会
由反馈 action 授予。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .assistant_feedback_models import (
    FeedbackAction,
    FeedbackPermission,
)


@dataclass(frozen=True)
class PermissionDecision:
    """权限判断结果：是否允许、已授予、被拒绝的权限与原因。"""

    allowed: bool
    granted: frozenset[FeedbackPermission] = field(default_factory=frozenset)
    denied: frozenset[FeedbackPermission] = field(default_factory=frozenset)
    reason: str | None = None


_REQUIRED_PERMISSIONS = {
    FeedbackAction.CONFIRM: frozenset({FeedbackPermission.RECORD_FEEDBACK}),
    FeedbackAction.REJECT: frozenset({FeedbackPermission.RECORD_FEEDBACK}),
    FeedbackAction.CORRECT: frozenset({FeedbackPermission.RECORD_FEEDBACK}),
    FeedbackAction.REQUEST_REVIEW: frozenset(
        {
            FeedbackPermission.RECORD_FEEDBACK,
            FeedbackPermission.REQUEST_CANDIDATE_REVIEW,
        }
    ),
}

_WRITE_GATED_PERMISSIONS = frozenset(
    {
        FeedbackPermission.REQUEST_CANDIDATE_REVIEW,
        FeedbackPermission.PROMOTE_FORMAL_RELATION,
    }
)


def _coerce_action(action: FeedbackAction | str) -> FeedbackAction:
    if isinstance(action, FeedbackAction):
        return action
    if isinstance(action, str):
        try:
            return FeedbackAction(action)
        except ValueError as exc:
            raise ValueError(f"unknown feedback action: {action}") from exc
    raise ValueError("action must be a FeedbackAction or its stable string")


class FeedbackPermissionPolicy:
    """默认 fail-closed 的反馈权限策略。"""

    def __init__(self, allow_write_back: bool = False) -> None:
        if not isinstance(allow_write_back, bool):
            raise ValueError("allow_write_back must be a boolean")
        self.allow_write_back = allow_write_back

    def authorize(
        self,
        actor: object | None,
        action: FeedbackAction | str,
    ) -> PermissionDecision:
        normalized = _coerce_action(action)
        required = _REQUIRED_PERMISSIONS[normalized]
        actor_permissions = _actor_permissions(actor)

        granted = required & actor_permissions
        denied = required - granted

        if not self.allow_write_back:
            blocked = _WRITE_GATED_PERMISSIONS & required
            granted = granted - blocked
            denied = denied | blocked

        allowed = not denied
        reason = None
        if not allowed:
            reason = "insufficient permission"
        return PermissionDecision(
            allowed=allowed,
            granted=granted,
            denied=denied,
            reason=reason,
        )


def _actor_permissions(actor: object | None) -> frozenset[FeedbackPermission]:
    if actor is None:
        return frozenset()
    raw = getattr(actor, "permissions", frozenset())
    result: set[FeedbackPermission] = set()
    for item in raw:
        if isinstance(item, FeedbackPermission):
            result.add(item)
        elif isinstance(item, str):
            try:
                result.add(FeedbackPermission(item))
            except ValueError:
                continue
    return frozenset(result)


__all__ = ("FeedbackPermissionPolicy", "PermissionDecision")
