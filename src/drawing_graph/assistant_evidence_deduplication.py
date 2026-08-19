"""Deterministic evidence deduplication for the 05 fusion layer.

只合并 fact kind、comparison key、normalized value 与 content fingerprint
全部相同的证据，合并后保留全部原 evidence ID、run、attempt、payload 与
source refs。去重只影响展示分组，不改变事实等级、置信度或持久化状态。
"""

from __future__ import annotations

import functools
import json
from dataclasses import dataclass, field
from typing import Any, Sequence

from .assistant_evidence_fusion_models import FusionEvidence


@dataclass(frozen=True)
class DeduplicationResult:
    """一次去重的输出，``groups`` 记录每个 canonical 组覆盖的证据 ID。"""

    deduplicated: tuple[FusionEvidence, ...] = field(default_factory=tuple)
    groups: tuple[tuple[str, ...], ...] = field(default_factory=tuple)


class EvidenceDeduplicator:
    """只按四条件全同合并证据，并保留完整 provenance。"""

    def deduplicate(
        self,
        evidence: Sequence[FusionEvidence],
    ) -> DeduplicationResult:
        groups: dict[tuple, list[FusionEvidence]] = {}
        order: list[tuple] = []
        for fusion in evidence:
            key = _group_key(fusion)
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(fusion)

        deduplicated: list[FusionEvidence] = []
        group_ids: list[tuple[str, ...]] = []
        for key in order:
            members = groups[key]
            canonical = _merge_group(members)
            deduplicated.append(canonical)
            group_ids.append(tuple(sorted(member.item.evidence_id for member in members)))

        deduplicated.sort(key=_output_sort_key)
        return DeduplicationResult(
            deduplicated=tuple(deduplicated),
            groups=tuple(group_ids),
        )


def _group_key(fusion: FusionEvidence) -> tuple:
    return (
        fusion.item.fact_kind,
        fusion.metadata.comparison_key,
        _canonical_value(fusion.metadata.normalized_value),
        fusion.metadata.content_fingerprint,
    )


def _canonical_value(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def _merge_group(members: list[FusionEvidence]) -> FusionEvidence:
    canonical = _select_canonical(members)
    if len(members) == 1:
        return canonical
    all_ids = tuple(sorted(member.item.evidence_id for member in members))
    provenance = tuple(prov for member in members for prov in member.provenance)
    return FusionEvidence(
        item=canonical.item,
        metadata=canonical.metadata,
        provenance=provenance,
        original_evidence_ids=all_ids,
    )


def _select_canonical(members: list[FusionEvidence]) -> FusionEvidence:
    return sorted(members, key=functools.cmp_to_key(_compare_canonical))[0]


def _compare_canonical(a: FusionEvidence, b: FusionEvidence) -> int:
    rank_a = _transient_rank(a.item.evidence_id)
    rank_b = _transient_rank(b.item.evidence_id)
    if rank_a != rank_b:
        return rank_a - rank_b
    created_a = a.item.created_at_or_version or ""
    created_b = b.item.created_at_or_version or ""
    if created_a != created_b:
        return -1 if created_a > created_b else 1
    if a.item.evidence_id == b.item.evidence_id:
        return 0
    return -1 if a.item.evidence_id < b.item.evidence_id else 1


def _transient_rank(evidence_id: str) -> int:
    """优先选择非临时（持久化稳定）ID 作为 canonical。"""

    return 1 if "temp" in evidence_id.lower() else 0


def _output_sort_key(fusion: FusionEvidence) -> tuple:
    return (
        fusion.item.fact_kind.value,
        fusion.metadata.comparison_key or "",
        fusion.item.evidence_id,
    )
