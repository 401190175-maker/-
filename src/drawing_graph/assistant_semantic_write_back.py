"""Controlled semantic write-back gate and adapter for the 05 fusion layer.

受控写回默认关闭；只有 request/module/environment 三层授权与 schema/scope/
payload/audit/evidence kind/dependency/conflict 门控全部通过时才允许执行。
recommendation、模型文本、confidence 和用户问题文字都不能提升写回授权。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence

from .assistant_evidence_fusion_models import (
    ConflictRecord,
    ConflictSeverity,
    LineagePlan,
    SemanticWriteBatch,
    WriteBackItemResult,
    WriteBackItemStatus,
    WriteBackPolicy,
    WriteBackResult,
    WriteBackStatus,
)
from .assistant_models import AssistantRequest, FactKind, ReasonCode


@dataclass(frozen=True)
class WriteBackGateResult:
    """一次写回门控的判定结果。"""

    allowed: bool
    reason_codes: tuple[ReasonCode, ...] = field(default_factory=tuple)


class ControlledSemanticWritePort(Protocol):
    """受控语义持久化端口，只接受已验证 SemanticWriteBatch。"""

    def persist(
        self,
        batch: SemanticWriteBatch,
        policy: WriteBackPolicy,
        lineage_plan: LineagePlan | None = None,
    ) -> WriteBackResult:
        """持久化一个已验证批次，返回逐项结果。"""


@dataclass(frozen=True)
class WriteBatchLimits:
    """写回批次资源上限；非法配置被拒绝。"""

    max_evidence: int = 100
    max_payload_bytes: int = 1_000_000
    max_attempts: int = 100

    def __post_init__(self) -> None:
        for field_name in ("max_evidence", "max_payload_bytes", "max_attempts"):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")


class WriteBackGate:
    """fail-closed 写回门控：任一条件失败即拒绝，零持久化调用。"""

    def evaluate(
        self,
        policy: WriteBackPolicy,
        batch: SemanticWriteBatch,
        *,
        assistant_request: AssistantRequest | None = None,
        conflicts: Sequence[ConflictRecord] = (),
        persistence_available: bool = True,
    ) -> WriteBackGateResult:
        reasons: list[ReasonCode] = []

        if not policy.request_allow_write_back:
            reasons.append(ReasonCode.WRITE_BACK_DENIED)
        if not policy.module_allow_write_back:
            reasons.append(ReasonCode.WRITE_BACK_DENIED)
        if not policy.environment_allow_write_back:
            reasons.append(ReasonCode.WRITE_BACK_DENIED)

        # policy 只能收紧授权，不能放宽原始 AssistantRequest
        if assistant_request is not None and policy.request_allow_write_back:
            if not assistant_request.allow_write_back:
                reasons.append(ReasonCode.WRITE_BACK_DENIED)

        if not batch.schema_valid:
            reasons.append(ReasonCode.WRITE_BACK_DENIED)
        if not batch.scope_valid:
            reasons.append(ReasonCode.SCOPE_CONFLICT)
        if not batch.payload_sanitized:
            reasons.append(ReasonCode.WRITE_BACK_DENIED)
        if not batch.audit_material_complete:
            reasons.append(ReasonCode.WRITE_BACK_DENIED)

        for fact_kind in _batch_fact_kinds(batch):
            if fact_kind not in policy.allowed_fact_kinds:
                reasons.append(ReasonCode.EVIDENCE_KIND_MISMATCH)

        if not persistence_available:
            reasons.append(ReasonCode.PERSISTENCE_UNAVAILABLE)

        for conflict in conflicts:
            if conflict.severity in policy.block_on_conflict_severities:
                reasons.append(ReasonCode.EVIDENCE_CONFLICT)

        return WriteBackGateResult(
            allowed=not reasons,
            reason_codes=tuple(dict.fromkeys(reasons)),
        )


def _batch_fact_kinds(batch: SemanticWriteBatch) -> tuple[FactKind, ...]:
    kinds: list[FactKind] = []
    if batch.observations:
        kinds.append(FactKind.SEMANTIC_OBSERVATION)
    if batch.interpretations:
        kinds.append(FactKind.SEMANTIC_INTERPRETATION)
    return tuple(kinds)


class SemanticServiceWriteAdapter:
    """按固定顺序执行受控持久化，并准确报告部分成功与幂等重放。"""

    def __init__(
        self,
        gate: WriteBackGate | None = None,
        *,
        persist_validated_batch=None,
        mark_evidence_stale=None,
        commit_cache=None,
        complete_run=None,
        limits: WriteBatchLimits | None = None,
    ) -> None:
        self.gate = gate or WriteBackGate()
        self._persist = persist_validated_batch
        self._mark_stale = mark_evidence_stale
        self._commit_cache = commit_cache
        self._complete_run = complete_run
        self.limits = limits or WriteBatchLimits()

    def persist(
        self,
        batch: SemanticWriteBatch,
        policy: WriteBackPolicy,
        lineage_plan: LineagePlan | None = None,
    ) -> WriteBackResult:
        gate_result = self.gate.evaluate(policy, batch)
        if not gate_result.allowed:
            return WriteBackResult(
                status=WriteBackStatus.SKIPPED,
                reason_codes=gate_result.reason_codes,
            )

        if len(_batch_evidence_ids(batch)) > self.limits.max_evidence:
            return WriteBackResult(
                status=WriteBackStatus.FAILED,
                reason_codes=(ReasonCode.RESULT_TRUNCATED,),
            )
        if len(batch.attempts) > self.limits.max_attempts:
            return WriteBackResult(
                status=WriteBackStatus.FAILED,
                reason_codes=(ReasonCode.RESULT_TRUNCATED,),
            )
        if (
            batch.sanitized_payload_envelope is not None
            and len(str(batch.sanitized_payload_envelope)) > self.limits.max_payload_bytes
        ):
            return WriteBackResult(
                status=WriteBackStatus.FAILED,
                reason_codes=(ReasonCode.RESULT_TRUNCATED,),
            )

        items: list[WriteBackItemResult] = []
        persisted_ids: list[str] = []
        payload_refs: list[str] = []

        if self._persist is None:
            return WriteBackResult(
                status=WriteBackStatus.SKIPPED,
                reason_codes=(ReasonCode.PERSISTENCE_UNAVAILABLE,),
            )

        # step 1: semantic evidence + run/attempt/payload
        try:
            payload_ref = self._persist(batch)
            evidence_ids = _batch_evidence_ids(batch)
            if payload_ref is not None:
                payload_refs.append(payload_ref)
            persisted_ids.extend(evidence_ids)
            items.append(
                WriteBackItemResult(
                    stage="semantic_evidence",
                    status=WriteBackItemStatus.PERSISTED,
                    evidence_ids=tuple(evidence_ids),
                )
            )
        except Exception as exc:
            items.append(
                WriteBackItemResult(
                    stage="semantic_evidence",
                    status=WriteBackItemStatus.FAILED,
                    reason_code=_safe_reason(exc),
                )
            )
            return WriteBackResult(
                status=WriteBackStatus.FAILED,
                items=tuple(items),
                reason_codes=(ReasonCode.WRITE_BACK_PARTIAL,),
            )

        # step 2: lineage stale
        if lineage_plan is not None and self._mark_stale is not None:
            try:
                stale_ids = self._mark_stale(
                    lineage_plan.evidence_ids,
                    superseded_by_evidence_id=lineage_plan.superseded_by_evidence_id,
                    stale_reason=lineage_plan.stale_reason or "superseded",
                    stale_at=lineage_plan.stale_at or "",
                    evidence_family_key=lineage_plan.evidence_family_key,
                )
                items.append(
                    WriteBackItemResult(
                        stage="lineage_stale",
                        status=WriteBackItemStatus.PERSISTED,
                        evidence_ids=tuple(stale_ids),
                    )
                )
            except Exception as exc:
                items.append(
                    WriteBackItemResult(
                        stage="lineage_stale",
                        status=WriteBackItemStatus.FAILED,
                        reason_code=ReasonCode.LINEAGE_WRITE_FAILED,
                    )
                )
                return WriteBackResult(
                    status=WriteBackStatus.PARTIAL,
                    items=tuple(items),
                    persisted_evidence_ids=tuple(persisted_ids),
                    payload_refs=tuple(payload_refs),
                    reason_codes=(ReasonCode.LINEAGE_WRITE_FAILED,),
                )

        # step 3: persistent cache commit
        cache_committed = False
        if self._commit_cache is not None and batch.cache_entries:
            try:
                for entry in batch.cache_entries:
                    self._commit_cache(entry)
                cache_committed = True
                items.append(
                    WriteBackItemResult(stage="persistent_cache", status=WriteBackItemStatus.PERSISTED)
                )
            except Exception:
                items.append(
                    WriteBackItemResult(stage="persistent_cache", status=WriteBackItemStatus.FAILED)
                )
                return WriteBackResult(
                    status=WriteBackStatus.PARTIAL,
                    items=tuple(items),
                    persisted_evidence_ids=tuple(persisted_ids),
                    payload_refs=tuple(payload_refs),
                    reason_codes=(ReasonCode.WRITE_BACK_PARTIAL,),
                )

        # step 4: run completion
        if self._complete_run is not None:
            try:
                self._complete_run(batch.recognition_run_id)
            except Exception:
                pass

        return WriteBackResult(
            status=WriteBackStatus.PERSISTED,
            items=tuple(items),
            persisted_evidence_ids=tuple(persisted_ids),
            payload_refs=tuple(payload_refs),
            recognition_run_ids=(batch.recognition_run_id,),
            persistent_cache_committed=cache_committed,
        )


def _batch_evidence_ids(batch: SemanticWriteBatch) -> tuple[str, ...]:
    ids: list[str] = []
    for observation in batch.observations:
        ids.append(observation.observation_id)
    for interpretation in batch.interpretations:
        ids.append(interpretation.interpretation_id)
    return tuple(ids)


def _safe_reason(exc: Exception) -> ReasonCode:
    category = getattr(exc, "category", None)
    if category == "PAYLOAD_STORE_UNAVAILABLE":
        return ReasonCode.PERSISTENCE_UNAVAILABLE
    if category == "SEMANTIC_EVIDENCE_UNAVAILABLE":
        return ReasonCode.PERSISTENCE_UNAVAILABLE
    return ReasonCode.WRITE_BACK_PARTIAL
