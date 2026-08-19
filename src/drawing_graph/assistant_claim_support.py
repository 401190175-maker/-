"""Claim support evaluation for the 05 fusion layer.

本模块把 ``EvidenceRequirement`` 确定性映射到所需 claim capability，并按
固定顺序评估证据对 requirement 的 scope、capability、minimum status、
freshness、冲突、formal gate 与限定语支撑。映射不读取问题自由文本来放宽
capability；未知 requirement/schema slot fail closed 为 unsupported。
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .assistant_evidence_fusion_models import (
    ClaimCapability,
    ClaimSupportAssessment,
    ClaimSupportStatus,
    ConflictRecord,
    ConflictType,
    FusionEvidence,
)
from .assistant_evidence_normalization import ClaimCapabilityRegistry
from .assistant_evidence_rules import scope_matches, status_acceptability
from .assistant_models import (
    EvidenceRequirement,
    EvidenceType,
    FactKind,
    ReasonCode,
    RequirementAssessment,
)

_CAPABILITY_BY_EVIDENCE_TYPE = {
    EvidenceType.PROJECT_DRAWING_SETS: ClaimCapability.IDENTITY_AND_LOCATION,
    EvidenceType.DRAWING_SET_PAGES: ClaimCapability.IDENTITY_AND_LOCATION,
    EvidenceType.PAGE_SOURCE_FACTS: ClaimCapability.IDENTITY_AND_LOCATION,
    EvidenceType.BLOCK_TRACE: ClaimCapability.IDENTITY_AND_LOCATION,
    EvidenceType.BLOCK_RELATIONS: ClaimCapability.RULE_DERIVED_CONTEXT,
    EvidenceType.TEXT_OBSERVATIONS: ClaimCapability.OBSERVED_TEXT_OR_SYMBOL,
    EvidenceType.STRUCTURED_INTERPRETATIONS: ClaimCapability.SEMANTIC_MEANING,
    EvidenceType.CANDIDATE_RELATIONS: ClaimCapability.POSSIBLE_RELATION,
    EvidenceType.SECTION_MATCHES: ClaimCapability.CONFIRMED_RELATION,
}


class RequirementCapabilityMapper:
    """把 EvidenceRequirement 确定性映射到所需 claim capability。

    只依据 requirement 的 evidence_type，不读取问题自由文本；未知
    evidence type 返回 None（unsupported），不使用通用 fallback 提升证据。
    """

    def map(self, requirement: EvidenceRequirement) -> ClaimCapability | None:
        return _CAPABILITY_BY_EVIDENCE_TYPE.get(requirement.evidence_type)


class ClaimSupportEvaluator:
    """按固定顺序评估证据对 requirement 的 claim 支撑能力。"""

    def __init__(
        self,
        capability_mapper: RequirementCapabilityMapper | None = None,
        capability_registry: ClaimCapabilityRegistry | None = None,
    ) -> None:
        self.capability_mapper = capability_mapper or RequirementCapabilityMapper()
        self.capability_registry = capability_registry or ClaimCapabilityRegistry()

    def evaluate(
        self,
        requirements: Sequence[EvidenceRequirement],
        evidence: Sequence[FusionEvidence],
        conflicts: Sequence[ConflictRecord] = (),
        prior_assessments: Sequence[RequirementAssessment] = (),
        subrequest_id: str | None = None,
    ) -> tuple[ClaimSupportAssessment, ...]:
        del prior_assessments
        return tuple(
            self._evaluate_requirement(requirement, evidence, conflicts, subrequest_id)
            for requirement in requirements
        )

    def _evaluate_requirement(
        self,
        requirement: EvidenceRequirement,
        evidence: Sequence[FusionEvidence],
        conflicts: Sequence[ConflictRecord],
        subrequest_id: str | None,
    ) -> ClaimSupportAssessment:
        capability = self.capability_mapper.map(requirement)
        if capability is None:
            return ClaimSupportAssessment(
                requirement_id=requirement.requirement_id,
                subrequest_id=subrequest_id,
                claim_capability=None,
                status=ClaimSupportStatus.UNSUPPORTED,
                reason_codes=(ReasonCode.UNSUPPORTED_GENERATION,),
            )

        supporting: list[FusionEvidence] = []
        qualifying: list[FusionEvidence] = []
        rejected: list[str] = []
        candidate_ids: list[str] = []
        reason_codes: list[ReasonCode] = []

        for fusion in evidence:
            # scope gate
            if fusion.item.scope is None:
                rejected.append(fusion.item.evidence_id)
                _append_reason(reason_codes, ReasonCode.SCOPE_MISSING)
                continue
            if not scope_matches(requirement.target_scope, fusion.item.scope):
                rejected.append(fusion.item.evidence_id)
                _append_reason(reason_codes, ReasonCode.SCOPE_CONFLICT)
                continue
            # formal gate candidate tracking
            if (
                capability is ClaimCapability.CONFIRMED_RELATION
                and fusion.item.fact_kind is FactKind.CANDIDATE_RELATION
            ):
                candidate_ids.append(fusion.item.evidence_id)
                continue
            # capability gate
            if capability not in fusion.metadata.claim_capabilities:
                rejected.append(fusion.item.evidence_id)
                _append_reason(reason_codes, ReasonCode.EVIDENCE_KIND_MISMATCH)
                continue
            # observation support chain gate for semantic meaning
            if capability is ClaimCapability.SEMANTIC_MEANING and not _has_observation_support(
                fusion, evidence
            ):
                rejected.append(fusion.item.evidence_id)
                _append_reason(reason_codes, ReasonCode.OBSERVATION_MISSING)
                continue
            # minimum status gate
            status_reason = status_acceptability(
                fusion.item.fact_kind, fusion.item.status, requirement.minimum_status
            )
            if status_reason is not None:
                rejected.append(fusion.item.evidence_id)
                _append_reason(reason_codes, status_reason)
                continue
            # freshness gate
            if not fusion.metadata.is_current_for_request:
                qualifying.append(fusion)
                _append_reason(reason_codes, ReasonCode.EVIDENCE_STALE)
                continue
            supporting.append(fusion)

        supporting_ids = tuple(sorted(item.item.evidence_id for item in supporting))
        qualifying_ids = tuple(sorted(item.item.evidence_id for item in qualifying))
        relevant_conflicts = [
            conflict
            for conflict in conflicts
            if set(conflict.evidence_ids) & set(supporting_ids + qualifying_ids)
        ]
        conflict_ids = tuple(sorted(conflict.conflict_id for conflict in relevant_conflicts))
        blocking = any(conflict.blocks_answer for conflict in relevant_conflicts)

        status, qualifiers = self._derive_status(
            requirement,
            capability,
            supporting,
            qualifying,
            candidate_ids,
            blocking,
            relevant_conflicts,
        )
        return ClaimSupportAssessment(
            requirement_id=requirement.requirement_id,
            subrequest_id=subrequest_id,
            claim_capability=capability,
            status=status,
            supporting_evidence_ids=supporting_ids,
            qualifying_evidence_ids=qualifying_ids,
            rejected_evidence_ids=tuple(sorted(rejected)),
            conflict_ids=conflict_ids,
            qualifiers=tuple(sorted(qualifiers)),
            reason_codes=tuple(dict.fromkeys(reason_codes)),
        )

    @staticmethod
    def _derive_status(
        requirement: EvidenceRequirement,
        capability: ClaimCapability,
        supporting: Sequence[FusionEvidence],
        qualifying: Sequence[FusionEvidence],
        candidate_ids: Sequence[str],
        blocking: bool,
        relevant_conflicts: Sequence[ConflictRecord],
    ) -> tuple[ClaimSupportStatus, tuple[str, ...]]:
        del requirement
        if blocking:
            return ClaimSupportStatus.CONFLICTING, ()
        if capability is ClaimCapability.CONFIRMED_RELATION:
            has_formal = any(
                item.item.fact_kind is FactKind.FORMAL_RELATION for item in supporting
            )
            if not has_formal and candidate_ids:
                return ClaimSupportStatus.FORMAL_REVIEW_REQUIRED, ()
        if supporting:
            qualifiers = _derive_qualifiers(supporting, relevant_conflicts)
            if qualifiers:
                return ClaimSupportStatus.SUPPORTED_WITH_QUALIFIER, qualifiers
            return ClaimSupportStatus.SUPPORTED, ()
        if qualifying:
            return ClaimSupportStatus.STALE_ONLY, ()
        return ClaimSupportStatus.MISSING, ()


def _derive_qualifiers(
    supporting: Sequence[FusionEvidence],
    conflicts: Sequence[ConflictRecord],
) -> tuple[str, ...]:
    qualifiers: set[str] = set()
    for fusion in supporting:
        confidence = fusion.item.confidence
        if confidence is not None and confidence < 0.5:
            qualifiers.add("low_confidence")
        if fusion.item.status == "partial":
            qualifiers.add("partial")
    if any(
        conflict.conflict_type in (ConflictType.PEER_CONFLICT, ConflictType.CANDIDATE_AMBIGUITY)
        for conflict in conflicts
    ):
        qualifiers.add("ambiguous")
    return tuple(sorted(qualifiers))


def _has_observation_support(fusion: FusionEvidence, evidence: Sequence[FusionEvidence]) -> bool:
    supported_ids = _metadata_text_tuple(fusion.item, "supported_by_observation_ids")
    if not supported_ids:
        return False
    observation_ids = {
        item.item.evidence_id
        for item in evidence
        if item.item.fact_kind is FactKind.SEMANTIC_OBSERVATION
    }
    return any(supported_id in observation_ids for supported_id in supported_ids)


def _metadata_text_tuple(item: object, key: str) -> tuple[str, ...]:
    metadata = getattr(item, "evidence_metadata", None)
    if not isinstance(metadata, Mapping):
        return ()
    value = metadata.get(key)
    if isinstance(value, (list, tuple)):
        return tuple(str(entry) for entry in value)
    return ()


def _append_reason(reason_codes: list[ReasonCode], reason: ReasonCode) -> None:
    if reason not in reason_codes:
        reason_codes.append(reason)
