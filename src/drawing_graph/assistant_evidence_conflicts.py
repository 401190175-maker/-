"""Deterministic evidence conflict detection for the 05 fusion layer.

只比较相同 ``comparison_key`` 的证据；不同 scope/slot 默认
``not_comparable``，不产生伪冲突。conflict ID 由 comparison key、conflict
type 和排序后的 evidence IDs 确定性生成。冲突组比较受大小上限约束，不
执行无界全量笛卡尔积。confidence 仅作为诊断字段，不单独选 winner。
"""

from __future__ import annotations

import hashlib
import json
from itertools import combinations
from typing import Any, Mapping, Sequence

from .assistant_evidence_fusion_models import (
    ConflictRecord,
    ConflictSeverity,
    ConflictType,
    FusionEvidence,
)
from .assistant_models import FactKind, ReasonCode


def build_conflict_id(
    comparison_key: str,
    conflict_type: ConflictType | str,
    evidence_ids: Sequence[str],
) -> str:
    """由 comparison key、conflict type 和排序后的 evidence IDs 生成稳定 ID。"""

    type_value = conflict_type.value if isinstance(conflict_type, ConflictType) else conflict_type
    payload = {
        "comparison_key": comparison_key,
        "conflict_type": type_value,
        "evidence_ids": tuple(sorted(evidence_ids)),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"conflict:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _record_sort_key(record: ConflictRecord) -> tuple:
    return (record.comparison_key or "", record.conflict_type.value, record.evidence_ids)


class EvidenceConflictDetector:
    """按 comparison key 分组并应用确定性冲突矩阵的纯组件。"""

    def __init__(self, max_group_size: int = 100, max_total_conflicts: int = 1000) -> None:
        if not isinstance(max_group_size, int) or isinstance(max_group_size, bool) or max_group_size < 1:
            raise ValueError("max_group_size must be a positive integer")
        if not isinstance(max_total_conflicts, int) or isinstance(max_total_conflicts, bool) or max_total_conflicts < 1:
            raise ValueError("max_total_conflicts must be a positive integer")
        self.max_group_size = max_group_size
        self.max_total_conflicts = max_total_conflicts

    def detect(self, evidence: Sequence[FusionEvidence]) -> tuple[ConflictRecord, ...]:
        """比较相同 comparison key 的证据，输出确定性排序的冲突记录。"""

        records: list[ConflictRecord] = list(self._comparison_conflicts(evidence))
        records.extend(self._support_conflicts(evidence))
        seen: set[str] = set()
        deduped: list[ConflictRecord] = []
        for record in sorted(records, key=_record_sort_key):
            if record.conflict_id not in seen:
                seen.add(record.conflict_id)
                deduped.append(record)
        return tuple(deduped)

    def _comparison_conflicts(self, evidence: Sequence[FusionEvidence]) -> tuple[ConflictRecord, ...]:
        groups = self._group(evidence)
        records: list[ConflictRecord] = []
        for comparison_key in sorted(groups):
            members = groups[comparison_key]
            if len(members) > self.max_group_size:
                members = sorted(members, key=lambda item: item.item.evidence_id)[: self.max_group_size]
            ordered = sorted(members, key=lambda item: item.item.evidence_id)
            for left, right in combinations(ordered, 2):
                if len(records) >= self.max_total_conflicts:
                    return tuple(records)
                conflict = self._pair_conflict(left, right)
                if conflict is not None:
                    records.append(self._record(comparison_key, conflict, left, right))
        return tuple(records)

    def _support_conflicts(self, evidence: Sequence[FusionEvidence]) -> tuple[ConflictRecord, ...]:
        """interpretation 未引用必要 observation 时产生 support_conflict。"""

        observation_ids = {
            fusion.item.evidence_id
            for fusion in evidence
            if fusion.item.fact_kind is FactKind.SEMANTIC_OBSERVATION
        }
        records: list[ConflictRecord] = []
        for fusion in evidence:
            if fusion.item.fact_kind is not FactKind.SEMANTIC_INTERPRETATION:
                continue
            supported_ids = _metadata_text_tuple(fusion.item, "supported_by_observation_ids")
            if supported_ids and any(sid in observation_ids for sid in supported_ids):
                continue
            comparison_key = fusion.metadata.comparison_key or ""
            records.append(
                ConflictRecord(
                    conflict_id=build_conflict_id(
                        comparison_key, ConflictType.SUPPORT_CONFLICT, (fusion.item.evidence_id,)
                    ),
                    comparison_key=fusion.metadata.comparison_key,
                    conflict_type=ConflictType.SUPPORT_CONFLICT,
                    severity=ConflictSeverity.WARNING,
                    evidence_ids=(fusion.item.evidence_id,),
                    blocks_answer=False,
                    reason_codes=(ReasonCode.EVIDENCE_CONFLICT,),
                    review_recommended=True,
                )
            )
        return tuple(records)

    def comparison_groups(
        self,
        evidence: Sequence[FusionEvidence],
    ) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """返回排序后的 (comparison key, 排序 evidence IDs) 分组，供测试与追踪。"""

        groups = self._group(evidence)
        return tuple(
            (key, tuple(sorted(item.item.evidence_id for item in groups[key])))
            for key in sorted(groups)
        )

    def _group(self, evidence: Sequence[FusionEvidence]) -> dict[str, list[FusionEvidence]]:
        groups: dict[str, list[FusionEvidence]] = {}
        for fusion in evidence:
            key = fusion.metadata.comparison_key
            if key is None:
                continue
            groups.setdefault(key, []).append(fusion)
        return groups

    def _record(
        self,
        comparison_key: str,
        conflict: tuple,
        left: FusionEvidence,
        right: FusionEvidence,
    ) -> ConflictRecord:
        conflict_type, severity, reason_codes, review = conflict
        evidence_ids = tuple(sorted((left.item.evidence_id, right.item.evidence_id)))
        return ConflictRecord(
            conflict_id=build_conflict_id(comparison_key, conflict_type, evidence_ids),
            comparison_key=comparison_key,
            conflict_type=conflict_type,
            severity=severity,
            evidence_ids=evidence_ids,
            blocks_answer=severity in (ConflictSeverity.BLOCKING, ConflictSeverity.CRITICAL),
            reason_codes=reason_codes,
            review_recommended=review,
        )

    def _pair_conflict(self, left: FusionEvidence, right: FusionEvidence) -> tuple | None:
        """冲突矩阵规则。"""

        kind_left = left.item.fact_kind
        kind_right = right.item.fact_kind
        if kind_left is FactKind.SOURCE_FACT and kind_right is FactKind.SOURCE_FACT:
            return self._source_source(left, right)
        if kind_left is FactKind.DERIVED_RELATION and kind_right is FactKind.DERIVED_RELATION:
            return self._derived_derived(left, right)
        if {kind_left, kind_right} == {FactKind.SOURCE_FACT, FactKind.DERIVED_RELATION}:
            return self._source_derived(left, right)
        if {kind_left, kind_right} == {FactKind.SOURCE_FACT, FactKind.SEMANTIC_OBSERVATION} or {
            kind_left, kind_right
        } == {FactKind.SOURCE_FACT, FactKind.SEMANTIC_INTERPRETATION}:
            return self._model_vs_source(left, right)
        if {kind_left, kind_right} == {FactKind.DERIVED_RELATION, FactKind.SEMANTIC_INTERPRETATION}:
            return self._semantic_vs_rule(left, right)
        if kind_left is FactKind.SEMANTIC_OBSERVATION and kind_right is FactKind.SEMANTIC_OBSERVATION:
            return self._observation_peer(left, right)
        if kind_left is FactKind.SEMANTIC_INTERPRETATION and kind_right is FactKind.SEMANTIC_INTERPRETATION:
            return self._interpretation_peer(left, right)
        if kind_left is FactKind.CANDIDATE_RELATION and kind_right is FactKind.CANDIDATE_RELATION:
            return self._candidate_candidate(left, right)
        if kind_left is FactKind.FORMAL_RELATION and kind_right is FactKind.FORMAL_RELATION:
            return self._formal_formal(left, right)
        if {kind_left, kind_right} == {FactKind.CANDIDATE_RELATION, FactKind.FORMAL_RELATION}:
            return None
        if {kind_left, kind_right} == {FactKind.FORMAL_RELATION, FactKind.SEMANTIC_OBSERVATION} or {
            kind_left, kind_right
        } == {FactKind.FORMAL_RELATION, FactKind.SEMANTIC_INTERPRETATION}:
            return self._formal_semantic(left, right)
        if kind_left is FactKind.DIAGNOSTIC and kind_right is FactKind.DIAGNOSTIC:
            return self._diagnostic_diagnostic(left, right)
        return None

    @staticmethod
    def _source_source(left: FusionEvidence, right: FusionEvidence) -> tuple | None:
        """source/source 同键不同值为 blocking hard_conflict。"""

        if _same_value(left, right):
            return None
        return (
            ConflictType.HARD_CONFLICT,
            ConflictSeverity.BLOCKING,
            (ReasonCode.EVIDENCE_CONFLICT,),
            True,
        )

    @staticmethod
    def _derived_derived(left: FusionEvidence, right: FusionEvidence) -> tuple | None:
        """derived/derived 同规格同槽不同目标为 rule_conflict。"""

        if _same_value(left, right):
            return None
        return (
            ConflictType.RULE_CONFLICT,
            ConflictSeverity.WARNING,
            (ReasonCode.EVIDENCE_CONFLICT,),
            True,
        )

    @staticmethod
    def _source_derived(left: FusionEvidence, right: FusionEvidence) -> tuple | None:
        """source/derived 默认互补；派生否定来源时为 rule_conflict。"""

        derived = left if left.item.fact_kind is FactKind.DERIVED_RELATION else right
        if _is_negating(derived.metadata.normalized_value):
            return (
                ConflictType.RULE_CONFLICT,
                ConflictSeverity.WARNING,
                (ReasonCode.EVIDENCE_CONFLICT,),
                True,
            )
        return None

    @staticmethod
    def _model_vs_source(left: FusionEvidence, right: FusionEvidence) -> tuple | None:
        """语义结果与来源事实冲突；来源事实不被覆盖。"""

        del left, right
        return (
            ConflictType.MODEL_VS_SOURCE,
            ConflictSeverity.WARNING,
            (ReasonCode.EVIDENCE_CONFLICT,),
            True,
        )

    @staticmethod
    def _semantic_vs_rule(left: FusionEvidence, right: FusionEvidence) -> tuple | None:
        del left, right
        return (
            ConflictType.SEMANTIC_VS_RULE,
            ConflictSeverity.WARNING,
            (ReasonCode.EVIDENCE_CONFLICT,),
            True,
        )

    @staticmethod
    def _observation_peer(left: FusionEvidence, right: FusionEvidence) -> tuple | None:
        """同区域同任务不同文本为 peer_conflict，默认保持 ambiguous。"""

        if _same_value(left, right):
            return None
        return (
            ConflictType.PEER_CONFLICT,
            ConflictSeverity.WARNING,
            (ReasonCode.EVIDENCE_CONFLICT,),
            False,
        )

    @staticmethod
    def _interpretation_peer(left: FusionEvidence, right: FusionEvidence) -> tuple | None:
        if _same_value(left, right):
            return None
        return (
            ConflictType.PEER_CONFLICT,
            ConflictSeverity.WARNING,
            (ReasonCode.EVIDENCE_CONFLICT,),
            False,
        )

    @staticmethod
    def _candidate_candidate(left: FusionEvidence, right: FusionEvidence) -> tuple | None:
        """同候选组多目标为 candidate_ambiguity，不自动选择 winner。"""

        if _same_value(left, right):
            return None
        return (
            ConflictType.CANDIDATE_AMBIGUITY,
            ConflictSeverity.WARNING,
            (ReasonCode.EVIDENCE_CONFLICT,),
            False,
        )

    @staticmethod
    def _formal_formal(left: FusionEvidence, right: FusionEvidence) -> tuple | None:
        """formal/formal 互斥槽多值为 critical/blocking integrity conflict。"""

        if _same_value(left, right):
            return None
        return (
            ConflictType.CRITICAL_INTEGRITY_CONFLICT,
            ConflictSeverity.CRITICAL,
            (ReasonCode.EVIDENCE_CONFLICT,),
            True,
        )

    @staticmethod
    def _formal_semantic(left: FusionEvidence, right: FusionEvidence) -> tuple | None:
        """formal/semantic 建议复核，不撤销 formal。"""

        del left, right
        return (
            ConflictType.FORMAL_VS_SEMANTIC,
            ConflictSeverity.WARNING,
            (ReasonCode.EVIDENCE_CONFLICT,),
            True,
        )

    @staticmethod
    def _diagnostic_diagnostic(left: FusionEvidence, right: FusionEvidence) -> tuple | None:
        """同 run 的 diagnostic 状态矛盾产生 diagnostic_conflict。"""

        if left.item.recognition_run_id != right.item.recognition_run_id:
            return None
        left_status = _run_status(left)
        right_status = _run_status(right)
        if left_status is not None and right_status is not None and left_status != right_status:
            return (
                ConflictType.DIAGNOSTIC_CONFLICT,
                ConflictSeverity.INFO,
                (ReasonCode.EVIDENCE_CONFLICT,),
                False,
            )
        return None


def _run_status(fusion: FusionEvidence) -> Any:
    value = fusion.metadata.normalized_value
    if isinstance(value, Mapping):
        return value.get("run_status")
    metadata = fusion.item.evidence_metadata
    if isinstance(metadata, Mapping):
        return metadata.get("run_status")
    return None


def _metadata_text_tuple(item: Any, key: str) -> tuple[str, ...]:
    metadata = item.evidence_metadata
    if not isinstance(metadata, Mapping):
        return ()
    value = metadata.get(key)
    if isinstance(value, (list, tuple)):
        return tuple(str(entry) for entry in value)
    return ()


def _same_value(left: FusionEvidence, right: FusionEvidence) -> bool:
    return left.metadata.normalized_value == right.metadata.normalized_value


def _is_negating(value: Any) -> bool:
    return isinstance(value, Mapping) and bool(value.get("negates"))
