"""Cache closure summary for the 05 fusion layer.

汇总 03 预期缓存候选、04 实际缓存处置、lineage 与写回结果，生成不夸大
的请求级缓存状态。evaluator 只汇总，不直接调用 cache get/put。
"""

from __future__ import annotations

from typing import Sequence

from .assistant_evidence_fusion_models import (
    CacheClosureStatus,
    CacheSummary,
    CacheTargetSummary,
    WriteBackResult,
)
from .assistant_models import CacheCandidate
from .recognition_models import CacheOutcome

_DISPOSITION_MAP = {
    "hit": CacheClosureStatus.FULL_HIT,
    "miss": CacheClosureStatus.MISS,
    "bypassed": CacheClosureStatus.BYPASSED,
    "stale": CacheClosureStatus.STALE,
    "unknown": CacheClosureStatus.UNKNOWN,
}


class CacheClosureEvaluator:
    """合并 expected/actual/lineage/write-back 生成 CacheSummary。"""

    def evaluate(
        self,
        expected: Sequence[CacheCandidate] = (),
        actual: Sequence[CacheOutcome] = (),
        lineage: object | None = None,
        write_back_result: WriteBackResult | None = None,
    ) -> CacheSummary:
        superseded_ids: set[str] = set()
        for plan in getattr(lineage, "plans", ()):
            superseded_ids.update(getattr(plan, "evidence_ids", ()))
        expected_by_target = {
            candidate.target_id: candidate
            for candidate in expected
            if candidate.target_id is not None
        }
        matched_target_ids: set[str] = set()
        targets: list[CacheTargetSummary] = []
        warnings: list[str] = []

        for outcome in actual:
            candidate = expected_by_target.get(outcome.target_id)
            actual_disposition = _DISPOSITION_MAP.get(
                outcome.disposition, CacheClosureStatus.UNKNOWN
            )
            if (
                outcome.disposition == "hit"
                and outcome.reused_evidence_ids
                and all(
                    evidence_id in superseded_ids
                    for evidence_id in outcome.reused_evidence_ids
                )
            ):
                actual_disposition = CacheClosureStatus.STALE
            targets.append(
                CacheTargetSummary(
                    target_id=outcome.target_id,
                    expected_cache_key=candidate.cache_key if candidate else None,
                    expected_disposition=candidate.disposition if candidate else None,
                    actual_cache_key=outcome.cache_key,
                    actual_disposition=actual_disposition,
                    reused_evidence_ids=outcome.reused_evidence_ids,
                    new_evidence_ids=(),
                    recognition_run_id=None,
                    provider_called=outcome.provider_called,
                    persisted=(
                        write_back_result.persistent_cache_committed
                        if write_back_result is not None
                        else False
                    ),
                )
            )
            matched_target_ids.add(outcome.target_id)

        for candidate in expected:
            if candidate.target_id is not None and candidate.target_id not in matched_target_ids:
                warnings.append(
                    f"no actual cache outcome for target {candidate.target_id}"
                )

        status = _derive_status(
            [target.actual_disposition for target in targets if target.actual_disposition is not None]
        )
        if warnings:
            status = CacheClosureStatus.UNKNOWN

        return CacheSummary(
            status=status,
            targets=tuple(targets),
            persistent_cache_committed=(
                write_back_result.persistent_cache_committed
                if write_back_result is not None
                else False
            ),
            request_memo_used=False,
            new_recognition_run_ids=(
                write_back_result.recognition_run_ids
                if write_back_result is not None
                else ()
            ),
            reason_codes=(),
            warnings=tuple(warnings),
        )


def _derive_status(dispositions: Sequence[CacheClosureStatus]) -> CacheClosureStatus:
    if not dispositions:
        return CacheClosureStatus.UNKNOWN
    unique = set(dispositions)
    if unique == {CacheClosureStatus.FULL_HIT}:
        return CacheClosureStatus.FULL_HIT
    if unique == {CacheClosureStatus.MISS}:
        return CacheClosureStatus.MISS
    if unique == {CacheClosureStatus.STALE}:
        return CacheClosureStatus.STALE
    if unique == {CacheClosureStatus.BYPASSED}:
        return CacheClosureStatus.BYPASSED
    if unique == {CacheClosureStatus.UNKNOWN}:
        return CacheClosureStatus.UNKNOWN
    if CacheClosureStatus.FULL_HIT in unique and unique <= {
        CacheClosureStatus.FULL_HIT,
        CacheClosureStatus.MISS,
        CacheClosureStatus.STALE,
        CacheClosureStatus.UNKNOWN,
    }:
        return CacheClosureStatus.PARTIAL_HIT
    return CacheClosureStatus.MIXED
