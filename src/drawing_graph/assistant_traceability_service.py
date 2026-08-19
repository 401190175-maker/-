"""Traceability service (07 traceability loop).

追溯服务入口：接收已生成的 ``AnswerPackage`` 与中间阶段记录，构造并写入
``TraceStorePort``；提供只读 ``get_trace()`` 与 ``get_claim_trace()``。
存储不可用时返回 trace warning，不把答案本身标记为失败，也不具备任何
业务写回能力。
"""

from __future__ import annotations

from .assistant_claim_trace import ClaimTraceProjector
from .assistant_trace_builder import TraceRecordBuilder
from .assistant_trace_models import (
    ClaimTrace,
    TraceQueryResult,
    TraceRecord,
    TraceWriteResult,
    TraceWriteStatus,
)
from .assistant_trace_store import TraceStorePort


class TraceabilityService:
    """记录与回查产品运行追溯，只写 ``TraceStorePort``，无业务写回。"""

    def __init__(
        self,
        store: TraceStorePort,
        builder: TraceRecordBuilder | None = None,
        projector: ClaimTraceProjector | None = None,
    ) -> None:
        self.store = store
        self.builder = builder or TraceRecordBuilder()
        self.projector = projector or ClaimTraceProjector()

    def record_answer_trace(
        self,
        *,
        request,
        question_result,
        retrieval_bundle=None,
        gap_decision=None,
        recognition_results=(),
        evidence_bundle=None,
        answer_package=None,
    ) -> TraceWriteResult:
        try:
            record: TraceRecord = self.builder.build(
                request=request,
                question_result=question_result,
                retrieval_bundle=retrieval_bundle,
                gap_decision=gap_decision,
                recognition_results=recognition_results,
                evidence_bundle=evidence_bundle,
                answer_package=answer_package,
            )
        except Exception:  # noqa: BLE001 - trace failure must not fail the answer.
            return TraceWriteResult(
                request_id=getattr(request, "request_id", ""),
                status=TraceWriteStatus.UNAVAILABLE,
                warning="trace build failed",
            )

        try:
            result = self.store.append_trace(record)
            if answer_package is not None:
                for claim_trace in self.projector.project_all(record, answer_package):
                    self.store.append_claim_trace(claim_trace)
            return result
        except Exception:  # noqa: BLE001 - store unavailable must not fail the answer.
            return TraceWriteResult(
                request_id=record.request_id,
                status=TraceWriteStatus.UNAVAILABLE,
                warning="trace_unavailable",
            )

    def get_trace(self, request_id: str, actor: object | None = None) -> TraceQueryResult:
        try:
            record = self.store.get_trace(request_id)
        except Exception:  # noqa: BLE001
            return TraceQueryResult(
                request_id=request_id,
                found=False,
                warnings=("trace_unavailable",),
            )
        if record is None:
            return TraceQueryResult(request_id=request_id, found=False)
        return TraceQueryResult(request_id=request_id, found=True, record=record)

    def get_claim_trace(self, claim_id: str, actor: object | None = None) -> ClaimTrace | None:
        try:
            return self.store.get_claim_trace(claim_id)
        except Exception:  # noqa: BLE001
            return None


__all__ = ("TraceabilityService",)
