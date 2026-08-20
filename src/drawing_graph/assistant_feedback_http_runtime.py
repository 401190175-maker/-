"""Runtime assembly for the product feedback HTTP API."""

from __future__ import annotations

from dataclasses import dataclass

from .assistant_feedback_http_models import HttpFeedbackRequest
from .assistant_feedback_models import FeedbackResult
from .assistant_feedback_permissions import FeedbackPermissionPolicy
from .assistant_feedback_service import FeedbackService
from .assistant_feedback_store import FeedbackStorePort, InMemoryFeedbackStore
from .assistant_models import FeedbackEvent
from .assistant_trace_store import TraceStorePort
from .config import FeedbackHttpConfig


@dataclass(frozen=True)
class FeedbackHttpActor:
    """Simple actor resolved from API configuration."""

    actor_id: str
    permissions: frozenset[str] = frozenset()


class FeedbackHttpRuntime:
    """Own the feedback service lifetime for one HTTP app instance."""

    def __init__(
        self,
        *,
        store: FeedbackStorePort | None = None,
        trace_store: TraceStorePort | None = None,
        default_permissions: tuple[str, ...] = ("record_feedback",),
        allow_candidate_review: bool = False,
        actor_id: str = "http-api",
    ) -> None:
        self.store = store or InMemoryFeedbackStore()
        self.trace_store = trace_store
        self.actor = FeedbackHttpActor(
            actor_id=actor_id,
            permissions=frozenset(default_permissions),
        )
        self.service = FeedbackService(
            store=self.store,
            trace_store=self.trace_store,
            permission_policy=FeedbackPermissionPolicy(
                allow_write_back=allow_candidate_review,
            ),
        )
        self._feedback_counter = 0

    def submit(self, request: HttpFeedbackRequest) -> FeedbackResult:
        self._feedback_counter += 1
        event = FeedbackEvent(
            feedback_id=request.feedback_id
            or f"feedback:http:{self._feedback_counter}",
            request_id=request.request_id or f"request:http:{self._feedback_counter}",
            claim_id=request.claim_id,
            action=request.action,
            reason=request.reason,
            correction=request.correction,
            user_id=self.actor.actor_id,
        )
        return self.service.submit_feedback(event, self.actor)

    def close(self) -> None:
        pass


def create_feedback_http_runtime(
    config: FeedbackHttpConfig,
) -> FeedbackHttpRuntime:
    """Build the default feedback runtime from configuration."""

    return FeedbackHttpRuntime(
        default_permissions=config.default_permissions,
        allow_candidate_review=config.allow_candidate_review,
    )
