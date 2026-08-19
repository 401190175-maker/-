"""Feedback service (08 feedback loop).

反馈服务入口：校验反馈事件、读取 claim trace、检查权限、执行状态机、
写入反馈审计，并在 ``request_review`` 且权限允许时受控调用候选审核适配器。
``confirm/reject/correct`` 只记录事件与审计，不产生正式事实。
"""

from __future__ import annotations

from .assistant_candidate_review_adapter import (
    CandidateReviewAdapter,
    CandidateReviewAdapterError,
)
from .assistant_feedback_models import (
    FeedbackAction,
    FeedbackAuditEvent,
    FeedbackPermission,
    FeedbackResult,
    FeedbackStatus,
)
from .assistant_feedback_permissions import FeedbackPermissionPolicy
from .assistant_feedback_state_machine import (
    FeedbackStateMachine,
    InvalidFeedbackTransitionError,
)
from .assistant_feedback_store import FeedbackStorePort
from .assistant_models import FeedbackEvent
from .assistant_trace_store import TraceStorePort


class FeedbackService:
    """反馈主流程，只写 ``FeedbackStorePort`` 与审计事件。"""

    def __init__(
        self,
        store: FeedbackStorePort,
        trace_store: TraceStorePort | None = None,
        permission_policy: FeedbackPermissionPolicy | None = None,
        state_machine: FeedbackStateMachine | None = None,
        candidate_review_adapter: CandidateReviewAdapter | None = None,
    ) -> None:
        self.store = store
        self.trace_store = trace_store
        self.permission_policy = permission_policy or FeedbackPermissionPolicy()
        self.state_machine = state_machine or FeedbackStateMachine()
        self.candidate_review_adapter = candidate_review_adapter
        self._audit_counter = 0

    def submit_feedback(
        self,
        event: FeedbackEvent,
        actor: object | None = None,
        policy: FeedbackPermissionPolicy | None = None,
    ) -> FeedbackResult:
        policy = policy or self.permission_policy

        if not isinstance(event, FeedbackEvent):
            return FeedbackResult(
                feedback_id="",
                status=FeedbackStatus.INVALID,
                warnings=("invalid_event",),
            )

        feedback_id = event.feedback_id
        action = self._coerce_action(event.action)
        if action is None:
            return self._invalid(feedback_id, "invalid action")

        if not event.claim_id:
            return self._invalid(feedback_id, "missing claim_id")

        claim_trace = self._get_claim_trace(event.claim_id)
        if claim_trace is None:
            return self._invalid(feedback_id, "claim not found")

        decision = policy.authorize(actor, action)
        if not decision.allowed:
            return self._forbidden(event, actor, decision)

        try:
            target, transitions = self.state_machine.apply_action(
                FeedbackStatus.RECEIVED,
                action,
            )
        except InvalidFeedbackTransitionError:
            return self._invalid(feedback_id, "invalid transition")

        try:
            self.store.append_feedback(event)
        except Exception:  # noqa: BLE001 - store failure must fail closed.
            return self._fail_closed(event, "store write failed")

        audit_event_ids: list[str] = []
        current = FeedbackStatus.RECEIVED
        try:
            self.store.set_status(feedback_id, FeedbackStatus.RECEIVED)
            for transition in transitions:
                current = transition.to_status
                audit_id = self._append_audit(
                    event,
                    actor,
                    from_status=transition.from_status,
                    to_status=transition.to_status,
                )
                audit_event_ids.append(audit_id)
                self.store.set_status(feedback_id, current)
        except Exception:  # noqa: BLE001
            return self._fail_closed(event, "store write failed")

        candidate_review_request_id: str | None = None
        candidate_review_result: object | None = None
        warnings: list[str] = []

        if action is FeedbackAction.REQUEST_REVIEW:
            candidate_review_request_id, candidate_review_result, review_status, warning = self._run_review(
                event,
                claim_trace,
                current,
            )
            if warning:
                warnings.append(warning)
            try:
                final, review_transitions = self.state_machine.apply_review_result(
                    current,
                    review_status,
                )
            except InvalidFeedbackTransitionError:
                final = FeedbackStatus.UNRESOLVED
                review_transitions = ()
            for transition in review_transitions:
                audit_id = self._append_audit(
                    event,
                    actor,
                    from_status=transition.from_status,
                    to_status=transition.to_status,
                )
                audit_event_ids.append(audit_id)
                current = transition.to_status
            try:
                self.store.set_status(feedback_id, final)
            except Exception:  # noqa: BLE001
                return self._fail_closed(event, "store write failed")
            final_status = final
        else:
            final_status = current

        return FeedbackResult(
            feedback_id=feedback_id,
            status=final_status,
            affected_claim_ids=(event.claim_id,),
            candidate_review_request_id=candidate_review_request_id,
            candidate_review_result=candidate_review_result,
            new_evidence_request=event.correction if action is FeedbackAction.CORRECT else None,
            warnings=tuple(warnings),
            audit_event_ids=tuple(audit_event_ids),
        )

    def get_feedback(self, feedback_id: str, actor: object | None = None) -> FeedbackResult | None:
        try:
            event = self.store.get_feedback(feedback_id)
        except Exception:  # noqa: BLE001
            return None
        if event is None:
            return None
        status = self.store.get_status(feedback_id) if event else FeedbackStatus.RECEIVED
        return FeedbackResult(
            feedback_id=event.feedback_id,
            status=status or FeedbackStatus.RECEIVED,
            affected_claim_ids=((event.claim_id,) if event.claim_id else ()),
        )

    def list_feedback_for_request(
        self,
        request_id: str,
        actor: object | None = None,
    ) -> tuple[FeedbackResult, ...]:
        try:
            events = self.store.list_feedback_for_request(request_id)
        except Exception:  # noqa: BLE001
            return ()
        results = []
        for event in events:
            status = self.store.get_status(event.feedback_id)
            results.append(
                FeedbackResult(
                    feedback_id=event.feedback_id,
                    status=status or FeedbackStatus.RECEIVED,
                    affected_claim_ids=((event.claim_id,) if event.claim_id else ()),
                )
            )
        return tuple(results)

    def _run_review(self, event, claim_trace, current):
        if self.candidate_review_adapter is None:
            return None, None, "unresolved", "candidate review unavailable"
        try:
            result = self.candidate_review_adapter.request_review(event, claim_trace)
        except CandidateReviewAdapterError as exc:
            if exc.category == "not_candidate_claim":
                return None, None, "invalid", "not a candidate claim"
            return None, None, "unresolved", exc.category
        review_run_id = getattr(result, "review_run_id", None)
        review_status = getattr(result, "status", "unresolved")
        if review_status not in {"accepted", "rejected", "unresolved"}:
            review_status = "unresolved"
        return review_run_id, result, review_status, None

    def _get_claim_trace(self, claim_id: str):
        if self.trace_store is None:
            return None
        try:
            return self.trace_store.get_claim_trace(claim_id)
        except Exception:  # noqa: BLE001
            return None

    def _append_audit(self, event, actor, from_status, to_status) -> str:
        self._audit_counter += 1
        audit = FeedbackAuditEvent(
            audit_event_id=f"audit:{event.feedback_id}:{self._audit_counter}",
            feedback_id=event.feedback_id,
            request_id=event.request_id,
            event_type="transition",
            from_status=from_status,
            to_status=to_status,
            actor_id=getattr(actor, "user_id", None) or self._actor_id(actor),
        )
        self.store.append_audit(audit)
        return audit.audit_event_id

    @staticmethod
    def _actor_id(actor: object | None) -> str | None:
        if actor is None:
            return None
        return getattr(actor, "user_id", None)

    @staticmethod
    def _coerce_action(action) -> FeedbackAction | None:
        if isinstance(action, FeedbackAction):
            return action
        if isinstance(action, str):
            try:
                return FeedbackAction(action)
            except ValueError:
                return None
        return None

    def _invalid(self, feedback_id: str, reason: str) -> FeedbackResult:
        return FeedbackResult(
            feedback_id=feedback_id,
            status=FeedbackStatus.INVALID,
            warnings=(reason,),
        )

    def _forbidden(self, event, actor, decision) -> FeedbackResult:
        return FeedbackResult(
            feedback_id=event.feedback_id,
            status=FeedbackStatus.FORBIDDEN,
            warnings=(decision.reason or "permission denied",),
        )

    def _fail_closed(self, event, reason: str) -> FeedbackResult:
        return FeedbackResult(
            feedback_id=event.feedback_id,
            status=FeedbackStatus.FORBIDDEN,
            warnings=(reason,),
        )


__all__ = ("FeedbackService",)
