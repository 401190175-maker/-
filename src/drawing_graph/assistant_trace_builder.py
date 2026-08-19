"""Trace record builder (07 traceability loop).

从 01—06 中间产物与 ``AnswerPackage`` 构造单条富版 ``TraceRecord``。
构造过程只做数据最小化提取，不读取图谱、不调用模型、不写 store。
"""

from __future__ import annotations

from datetime import datetime, timezone

from .assistant_models import (
    AssistantRequest,
    QuestionUnderstandingResult,
    RetrievalBundle,
    SemanticGapDecision,
)
from .assistant_trace_models import (
    TraceCostSummary,
    TraceLatencySummary,
    TraceModuleEvent,
    TraceRecord,
)

_SENSITIVE_MARKERS = (
    "authorization",
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "traceback",
    "cypher",
)


def _redact(text: str) -> str:
    lowered = text.lower()
    if any(marker in lowered for marker in _SENSITIVE_MARKERS):
        return "[redacted]"
    return text


class TraceRecordBuilder:
    """构造富版 ``TraceRecord``，不产生任何副作用。"""

    def __init__(self) -> None:
        self._counter = 0

    def build(
        self,
        request: AssistantRequest,
        question_result: QuestionUnderstandingResult,
        retrieval_bundle: RetrievalBundle | None = None,
        gap_decision: SemanticGapDecision | None = None,
        recognition_results: tuple[object, ...] = (),
        evidence_bundle: object | None = None,
        answer_package: object | None = None,
    ) -> TraceRecord:
        self._counter += 1
        request_id = request.request_id
        events: list[TraceModuleEvent] = []

        scope = question_result.scope or request.scope_hint
        events.append(
            self._event(
                request_id,
                "question_understanding",
                question_result.question_type,
            )
        )

        retrieval_calls = ()
        evidence_ids: list[str] = []
        model_profiles: list[str] = []
        prompt_versions: list[str] = []

        if retrieval_bundle is not None:
            retrieval_calls = retrieval_bundle.source_calls
            events.append(
                self._event(
                    request_id,
                    "retrieval",
                    retrieval_bundle.status.value,
                )
            )
            for bucket in (
                retrieval_bundle.source_facts,
                retrieval_bundle.derived_relations,
                retrieval_bundle.semantic_observations,
                retrieval_bundle.semantic_interpretations,
                retrieval_bundle.candidate_relations,
                retrieval_bundle.formal_relations,
                retrieval_bundle.diagnostics,
            ):
                for item in bucket:
                    evidence_ids.append(item.evidence_id)
                    if item.model_profile:
                        model_profiles.append(item.model_profile)
                    if item.prompt_version:
                        prompt_versions.append(item.prompt_version)

        if gap_decision is not None:
            events.append(
                self._event(
                    request_id,
                    "semantic_gap_decision",
                    gap_decision.decision.value,
                )
            )

        recognition_run_ids: list[str] = []
        for result in recognition_results:
            run_id = getattr(result, "recognition_run_id", None)
            if run_id:
                recognition_run_ids.append(run_id)
        if recognition_results:
            events.append(self._event(request_id, "recognition", "executed"))

        cache_status = None
        answerability_value = None
        if evidence_bundle is not None:
            accepted = getattr(evidence_bundle, "accepted_evidence", ())
            for fusion_evidence in accepted:
                item = getattr(fusion_evidence, "item", None)
                evidence_id = getattr(item, "evidence_id", None)
                if evidence_id:
                    evidence_ids.append(evidence_id)
                if getattr(item, "model_profile", None):
                    model_profiles.append(item.model_profile)
                if getattr(item, "prompt_version", None):
                    prompt_versions.append(item.prompt_version)
            cache_summary = getattr(evidence_bundle, "cache_summary", None)
            if cache_summary is not None:
                cache_status = getattr(cache_summary, "status", None)
                cache_status = cache_status.value if cache_status is not None else None
            answerability = getattr(evidence_bundle, "answerability", None)
            if answerability is not None:
                answerability_value = getattr(answerability, "status", None)
                answerability_value = (
                    answerability_value.value if answerability_value is not None else None
                )
            events.append(
                self._event(
                    request_id,
                    "evidence_fusion",
                    answerability_value or "unknown",
                )
            )

        answer_status = None
        claim_ids: list[str] = []
        package_run_ids: list[str] = []
        if answer_package is not None:
            answer_status = getattr(answer_package, "status", None)
            for claim in getattr(answer_package, "claims", ()):
                claim_ids.append(claim.claim_id)
            for run_id in getattr(answer_package, "recognition_run_ids", ()):
                package_run_ids.append(run_id)
            events.append(self._event(request_id, "answer_generation", answer_status or "unknown"))

        all_run_ids = list(dict.fromkeys(recognition_run_ids + package_run_ids))

        cost_summary = self._cost_summary(gap_decision)
        latency_summary = self._latency_summary(gap_decision)

        return TraceRecord(
            request_id=request_id,
            question=request.question,
            question_type=question_result.question_type,
            scope=scope,
            module_events=tuple(events),
            retrieval_calls=tuple(retrieval_calls),
            semantic_gap_decision=gap_decision,
            recognition_run_ids=tuple(all_run_ids),
            evidence_ids=tuple(dict.fromkeys(evidence_ids)),
            claim_ids=tuple(dict.fromkeys(claim_ids)),
            answer_status=answer_status,
            model_profiles=tuple(dict.fromkeys(model_profiles)),
            prompt_versions=tuple(dict.fromkeys(prompt_versions)),
            cache_status=cache_status,
            cost_summary=cost_summary,
            latency_summary=latency_summary,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def _event(self, request_id: str, module: str, status: str) -> TraceModuleEvent:
        self._counter += 1
        return TraceModuleEvent(
            event_id=f"trace-event:{request_id}:{self._counter}",
            module=module,
            status=_redact(str(status)),
        )

    @staticmethod
    def _cost_summary(gap_decision: SemanticGapDecision | None) -> TraceCostSummary | None:
        if gap_decision is None or gap_decision.estimate is None:
            return None
        estimate = gap_decision.estimate
        return TraceCostSummary(
            estimated_cost=estimate.estimated_cost,
            currency=estimate.currency,
            selected_target_count=estimate.selected_target_count,
            deferred_target_count=estimate.deferred_target_count,
        )

    @staticmethod
    def _latency_summary(gap_decision: SemanticGapDecision | None) -> TraceLatencySummary | None:
        if gap_decision is None or gap_decision.estimate is None:
            return None
        return TraceLatencySummary(estimated_latency_ms=gap_decision.estimate.estimated_latency_ms)


__all__ = ("TraceRecordBuilder",)
