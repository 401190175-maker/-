"""Evidence lineage and stale policy for the 05 fusion layer.

本模块定义 observation/interpretation 的 stale 策略注册与同族证据的
lineage/supersede 计划。resolver 只生成判断，不修改持久化旧证据，不写
repository；formal/source/derived/candidate/diagnostic 不被语义 lineage
标 stale。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Sequence

from .assistant_evidence_fusion_models import (
    EvidenceLineage,
    FusionEvidence,
    LineagePlan,
)
from .assistant_models import FactKind

_STALE_ELIGIBLE_KINDS = frozenset(
    {FactKind.SEMANTIC_OBSERVATION, FactKind.SEMANTIC_INTERPRETATION}
)


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _coerce_fact_kind(value: FactKind | str) -> FactKind:
    if isinstance(value, FactKind):
        return value
    if isinstance(value, str):
        try:
            return FactKind(value)
        except ValueError as exc:
            raise ValueError(f"unknown fact kind: {value!r}") from exc
    raise ValueError("fact_kind must be a FactKind or its stable string")


@dataclass(frozen=True)
class StalePolicy:
    """一条针对语义证据类型的 stale 策略，只承载判断，不写 repository。"""

    fact_kind: FactKind | str
    policy_id: str
    version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "fact_kind", _coerce_fact_kind(self.fact_kind))
        _require_text(self.policy_id, "policy_id")
        _require_text(self.version, "version")


class StalePolicyLookupError(LookupError):
    """没有匹配 stale policy 时抛出的稳定失败。"""


class StalePolicyRegistry:
    """分别注册 observation 与 interpretation 的 stale 策略。

    source、derived、candidate、formal 和 diagnostic 被明确排除；重复
    策略被拒绝；缺失策略时 lookup fail closed。策略只生成判断，不执行
    repository 写入。
    """

    def __init__(
        self,
        policies: Sequence[StalePolicy] = (),
        registry_version: str = "stale-policy-v1",
    ) -> None:
        _require_text(registry_version, "registry_version")
        self._registry_version = registry_version
        indexed: dict[FactKind, StalePolicy] = {}
        for policy in policies:
            if not isinstance(policy, StalePolicy):
                raise TypeError("policies must contain only StalePolicy instances")
            if policy.fact_kind not in _STALE_ELIGIBLE_KINDS:
                raise ValueError(
                    f"fact kind {policy.fact_kind.value!r} is not stale-eligible"
                )
            if policy.fact_kind in indexed:
                raise ValueError(f"duplicate stale policy for {policy.fact_kind.value!r}")
            indexed[policy.fact_kind] = policy
        self._policies = MappingProxyType(dict(indexed))

    @property
    def registry_version(self) -> str:
        return self._registry_version

    def is_stale_eligible(self, fact_kind: FactKind | str) -> bool:
        """返回某 fact kind 是否可被语义 lineage 标 stale。"""

        kind = _coerce_fact_kind(fact_kind)
        return kind in self._policies

    def policy_for(self, fact_kind: FactKind | str) -> StalePolicy:
        """返回匹配策略；缺失时抛出稳定失败。"""

        kind = _coerce_fact_kind(fact_kind)
        policy = self._policies.get(kind)
        if policy is None:
            raise StalePolicyLookupError(f"no stale policy for fact_kind={kind.value!r}")
        return policy


@dataclass(frozen=True)
class LineageResult:
    """一次 lineage 解析的输出：lineage 记录与待写回的 supersede 计划。"""

    lineages: tuple[EvidenceLineage, ...] = field(default_factory=tuple)
    plans: tuple[LineagePlan, ...] = field(default_factory=tuple)


class EvidenceLineageResolver:
    """按 evidence family 解析同族证据的复用与 supersede 关系。

    resolver 只生成判断，不修改持久化旧证据；写回失败时仅由上层在本次
    bundle 中限制旧证据使用。输出排序与 lineage/plan ID 对相同输入稳定。
    """

    def __init__(self, stale_policy_registry: StalePolicyRegistry | None = None) -> None:
        self.stale_policy_registry = stale_policy_registry or StalePolicyRegistry()

    def resolve(
        self,
        evidence: Sequence[FusionEvidence],
        freshness_requirements: Mapping[str, object] | None = None,
    ) -> LineageResult:
        del freshness_requirements
        groups: dict[str, list[FusionEvidence]] = {}
        order: list[str] = []
        for fusion in evidence:
            if not self.stale_policy_registry.is_stale_eligible(fusion.item.fact_kind):
                continue
            family_key = fusion.metadata.evidence_family_key
            if family_key is None:
                continue
            if family_key not in groups:
                groups[family_key] = []
                order.append(family_key)
            groups[family_key].append(fusion)

        lineages: list[EvidenceLineage] = []
        plans: list[LineagePlan] = []
        for family_key in order:
            lineage, plan = self._resolve_family(family_key, groups[family_key])
            if lineage is not None:
                lineages.append(lineage)
            if plan is not None:
                plans.append(plan)

        lineages.sort(key=lambda item: item.lineage_id)
        plans.sort(key=lambda item: item.plan_id)
        return LineageResult(lineages=tuple(lineages), plans=tuple(plans))

    def _resolve_family(
        self,
        family_key: str,
        members: list[FusionEvidence],
    ) -> tuple[EvidenceLineage | None, LineagePlan | None]:
        current_members = [m for m in members if m.metadata.is_current_for_request]
        if not current_members:
            return None, None
        current = _select_current(current_members)
        old_members = [
            m for m in members
            if m.item.evidence_id != current.item.evidence_id
        ]
        superseded = [
            m for m in old_members
            if m.metadata.cache_key != current.metadata.cache_key
            or m.metadata.content_fingerprint != current.metadata.content_fingerprint
        ]
        superseded_ids = tuple(sorted(m.item.evidence_id for m in superseded))
        lineage_id = f"lineage:{family_key}"
        if not superseded_ids:
            lineage = EvidenceLineage(
                lineage_id=lineage_id,
                evidence_family_key=family_key,
                current_evidence_id=current.item.evidence_id,
                superseded_evidence_ids=(),
            )
            return lineage, None
        lineage = EvidenceLineage(
            lineage_id=lineage_id,
            evidence_family_key=family_key,
            current_evidence_id=current.item.evidence_id,
            superseded_evidence_ids=superseded_ids,
            stale_reason="superseded_by_newer_evidence",
        )
        plan = LineagePlan(
            plan_id=f"plan:{family_key}",
            evidence_family_key=family_key,
            evidence_ids=superseded_ids,
            superseded_by_evidence_id=current.item.evidence_id,
            stale_reason="superseded_by_newer_evidence",
        )
        return lineage, plan


def _select_current(members: list[FusionEvidence]) -> FusionEvidence:
    return max(members, key=_current_sort_key)


def _current_sort_key(fusion: FusionEvidence) -> tuple:
    return (
        fusion.item.created_at_or_version or "",
        fusion.item.evidence_id,
    )
