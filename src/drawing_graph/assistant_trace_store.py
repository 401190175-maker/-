"""Trace store port and in-memory implementation (07 traceability loop).

本模块提供产品运行审计的 trace store。首版只提供 append/read 的内存
实现，不访问图数据库，不写业务事实；重复 request_id 不静默覆盖。
"""

from __future__ import annotations

from typing import Protocol

from .assistant_trace_models import (
    ClaimTrace,
    TraceRecord,
    TraceWriteResult,
    TraceWriteStatus,
)


class TraceStorePort(Protocol):
    """产品追溯 store 的稳定端口，只做 append/read。"""

    def append_trace(self, record: TraceRecord) -> TraceWriteResult: ...

    def get_trace(self, request_id: str) -> TraceRecord | None: ...

    def append_claim_trace(self, claim_trace: ClaimTrace) -> None: ...

    def get_claim_trace(self, claim_id: str) -> ClaimTrace | None: ...

    def list_feedback_refs(self, request_id: str) -> tuple[str, ...]: ...


class InMemoryTraceStore:
    """append/read 的进程内 trace store，不持久化、不覆盖旧记录。"""

    def __init__(self) -> None:
        self._traces: dict[str, TraceRecord] = {}
        self._claim_traces: dict[str, ClaimTrace] = {}
        self._feedback_refs: dict[str, tuple[str, ...]] = {}

    def append_trace(self, record: TraceRecord) -> TraceWriteResult:
        if not isinstance(record, TraceRecord):
            raise ValueError("record must be a TraceRecord")
        if record.request_id in self._traces:
            return TraceWriteResult(
                request_id=record.request_id,
                status=TraceWriteStatus.DUPLICATE,
                warning="trace for request_id already exists",
            )
        self._traces[record.request_id] = record
        return TraceWriteResult(request_id=record.request_id, status=TraceWriteStatus.RECORDED)

    def get_trace(self, request_id: str) -> TraceRecord | None:
        return self._traces.get(request_id)

    def append_claim_trace(self, claim_trace: ClaimTrace) -> None:
        if not isinstance(claim_trace, ClaimTrace):
            raise ValueError("claim_trace must be a ClaimTrace")
        self._claim_traces[claim_trace.claim_id] = claim_trace

    def get_claim_trace(self, claim_id: str) -> ClaimTrace | None:
        return self._claim_traces.get(claim_id)

    def list_feedback_refs(self, request_id: str) -> tuple[str, ...]:
        return self._feedback_refs.get(request_id, ())


__all__ = ("InMemoryTraceStore", "TraceStorePort")
