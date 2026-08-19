"""Deterministic claim builder for the 06 answer-generation layer.

本模块把 ``QuestionUnderstandingResult + EvidenceBundle`` 确定性投影为
``Claim`` 集合。claim 只由确定性代码生成，不调用文本模型；非诊断 claim
必须绑定受支持 evidence ID；candidate/interpretation/conflict 不会被提升为
formal/source fact。
"""

from __future__ import annotations

import hashlib
import json
from typing import Mapping, Sequence

from .assistant_evidence_fusion_models import (
    ClaimCapability,
    ClaimSupportAssessment,
    ClaimSupportStatus,
    ConflictRecord,
    FusionEvidence,
)
from .assistant_models import (
    ANSWER_CONTRACT_VERSION,
    AssistantScope,
    Claim,
    ClaimStatus,
    FactKind,
    QuestionUnderstandingResult,
    ReasonCode,
)
from .assistant_evidence_rules import scope_matches

_SCOPE_FIELDS = (
    "project_id",
    "drawing_set_id",
    "page_id",
    "block_id",
    "element_id",
    "cross_section_id",
    "table_id",
    "table_caption_id",
    "claim_id",
)

_FACT_KIND_ORDER = (
    FactKind.SOURCE_FACT,
    FactKind.DERIVED_RELATION,
    FactKind.SEMANTIC_OBSERVATION,
    FactKind.SEMANTIC_INTERPRETATION,
    FactKind.CANDIDATE_RELATION,
    FactKind.FORMAL_RELATION,
    FactKind.DIAGNOSTIC,
    FactKind.UNSUPPORTED,
)
_FACT_KIND_RANK = {kind: index for index, kind in enumerate(_FACT_KIND_ORDER)}


def _capability_value(capability: ClaimCapability | str | None) -> str:
    if capability is None:
        return ""
    if isinstance(capability, ClaimCapability):
        return capability.value
    return str(capability)


def _status_value(status: ClaimStatus | str) -> str:
    if isinstance(status, ClaimStatus):
        return status.value
    return str(status)


def _scope_key(scope: AssistantScope | None) -> dict:
    if scope is None:
        return {}
    return {
        field_name: getattr(scope, field_name)
        for field_name in _SCOPE_FIELDS
        if getattr(scope, field_name) is not None
    }


def build_claim_id(
    request_id: str,
    subrequest_id: str | None,
    capability: ClaimCapability | str | None,
    scope: AssistantScope | None,
    evidence_ids: tuple[str, ...],
    status: ClaimStatus | str,
    contract_version: str = ANSWER_CONTRACT_VERSION,
) -> str:
    """由合同版本、请求/子请求、capability、scope、排序 evidence IDs 与
    status 生成稳定 claim ID。不使用时间戳或随机数。"""

    payload = {
        "answer_contract_version": contract_version,
        "request_id": request_id,
        "subrequest_id": subrequest_id or "",
        "capability": _capability_value(capability),
        "scope": _scope_key(scope),
        "evidence_ids": tuple(sorted(evidence_ids)),
        "status": _status_value(status),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"claim:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


_CAPABILITY_CLAIM_LABELS = {
    ClaimCapability.IDENTITY_AND_LOCATION: "目标定位与来源",
    ClaimCapability.CONFIRMED_RELATION: "关系确认",
    ClaimCapability.RULE_DERIVED_CONTEXT: "规则派生关系",
    ClaimCapability.OBSERVED_TEXT_OR_SYMBOL: "图中识别到的文字与符号",
    ClaimCapability.SEMANTIC_MEANING: "语义解释",
    ClaimCapability.POSSIBLE_RELATION: "候选关系",
    ClaimCapability.RUNTIME_OR_CACHE_STATUS: "运行与缓存状态",
}

_STATUS_MAP = {
    ClaimSupportStatus.SUPPORTED: ClaimStatus.SUPPORTED,
    ClaimSupportStatus.SUPPORTED_WITH_QUALIFIER: ClaimStatus.QUALIFIED,
    ClaimSupportStatus.CONFLICTING: ClaimStatus.CONFLICTING,
    ClaimSupportStatus.FORMAL_REVIEW_REQUIRED: ClaimStatus.FORMAL_REVIEW_REQUIRED,
}

_NON_GENERATING_STATUSES = frozenset(
    {
        ClaimSupportStatus.MISSING,
        ClaimSupportStatus.STALE_ONLY,
        ClaimSupportStatus.UNSUPPORTED,
    }
)


def _statement(capability: ClaimCapability | None, status: ClaimStatus) -> str:
    label = _CAPABILITY_CLAIM_LABELS.get(capability) or _capability_value(capability)
    if status is ClaimStatus.CONFLICTING:
        return f"{label}存在冲突，无法得出确定性结论"
    if status is ClaimStatus.FORMAL_REVIEW_REQUIRED:
        return f"{label}仅有候选证据，待复核"
    if status is ClaimStatus.DIAGNOSTIC:
        return f"{label}为本次运行状态说明"
    if status is ClaimStatus.QUALIFIED:
        return f"{label}已确认，但存在限定条件"
    return f"{label}已确认"


def _evidence_by_id(bundle) -> dict[str, FusionEvidence]:
    result: dict[str, FusionEvidence] = {}
    for fusion in tuple(bundle.accepted_evidence) + tuple(bundle.conflicting_evidence):
        result[fusion.item.evidence_id] = fusion
    return result


def _distinct_fact_kinds(
    evidence_ids: Sequence[str],
    evidence_by_id: Mapping[str, FusionEvidence],
) -> tuple[FactKind, ...]:
    kinds: list[FactKind] = []
    for evidence_id in evidence_ids:
        fusion = evidence_by_id.get(evidence_id)
        if fusion is None:
            continue
        kind = fusion.item.fact_kind
        if kind not in kinds:
            kinds.append(kind)
    return tuple(sorted(kinds, key=lambda item: _FACT_KIND_RANK.get(item, 999)))


def _conflict_evidence_ids(
    assessment: ClaimSupportAssessment,
    conflicts: Sequence[ConflictRecord],
) -> tuple[str, ...]:
    conflict_ids = set(assessment.conflict_ids)
    result: set[str] = set()
    for conflict in conflicts:
        if conflict.conflict_id in conflict_ids:
            result.update(conflict.evidence_ids)
    return tuple(sorted(result))


def _candidate_evidence_ids(requirement, bundle) -> tuple[str, ...]:
    if requirement is None:
        return ()
    target = requirement.target_scope
    ids: list[str] = []
    for fusion in _evidence_by_id(bundle).values():
        item = fusion.item
        if item.fact_kind is FactKind.CANDIDATE_RELATION and item.scope is not None:
            if scope_matches(target, item.scope):
                ids.append(item.evidence_id)
    return tuple(sorted(ids))


def _claim_evidence_ids(assessment, claim_status, bundle, requirement):
    if claim_status is ClaimStatus.CONFLICTING:
        return _conflict_evidence_ids(assessment, bundle.conflicts)
    if claim_status is ClaimStatus.FORMAL_REVIEW_REQUIRED:
        return _candidate_evidence_ids(requirement, bundle)
    return tuple(
        sorted(assessment.supporting_evidence_ids + assessment.qualifying_evidence_ids)
    )


def _claim_qualifiers(assessment, claim_status):
    if claim_status is ClaimStatus.FORMAL_REVIEW_REQUIRED:
        return ("待复核",)
    if claim_status is ClaimStatus.QUALIFIED:
        return tuple(sorted(assessment.qualifiers))
    return ()


def _map_status(status: ClaimSupportStatus) -> ClaimStatus | None:
    """把 05 支撑状态映射为 claim 状态；非生成状态返回 None。"""

    if status in _NON_GENERATING_STATUSES:
        return None
    return _STATUS_MAP.get(status)


class ClaimBuilder:
    """把 ClaimSupportAssessment 确定性投影为 Claim。"""

    def build(
        self,
        question_result: QuestionUnderstandingResult,
        evidence_bundle,
    ) -> tuple[Claim, ...]:
        requirements = {
            requirement.requirement_id: requirement
            for requirement in question_result.required_evidence
        }
        evidence_by_id = _evidence_by_id(evidence_bundle)
        claims: list[Claim] = []
        for assessment in evidence_bundle.claim_support:
            claim_status = _map_status(assessment.status)
            if claim_status is None:
                continue
            requirement = requirements.get(assessment.requirement_id)
            scope = requirement.target_scope if requirement is not None else question_result.scope
            evidence_ids = _claim_evidence_ids(
                assessment,
                claim_status,
                evidence_bundle,
                requirement if requirement is not None else None,
            )
            if not evidence_ids:
                continue
            claims.append(
                Claim(
                    claim_id=build_claim_id(
                        request_id=question_result.request_id,
                        subrequest_id=question_result.subrequest_id,
                        capability=assessment.claim_capability,
                        scope=scope,
                        evidence_ids=evidence_ids,
                        status=claim_status,
                    ),
                    statement=_statement(assessment.claim_capability, claim_status),
                    claim_type=_capability_value(assessment.claim_capability) or None,
                    status=claim_status.value,
                    confidence=assessment.confidence,
                    evidence_ids=evidence_ids,
                    fact_kinds=_distinct_fact_kinds(evidence_ids, evidence_by_id),
                    scope=scope,
                    qualifiers=_claim_qualifiers(assessment, claim_status),
                    subrequest_id=question_result.subrequest_id,
                    reason_codes=assessment.reason_codes,
                )
            )
        return tuple(claims)

    @staticmethod
    def build_diagnostic_claim(
        request_id: str,
        subrequest_id: str | None,
        scope: AssistantScope | None,
        reason_code: ReasonCode | str | None,
    ) -> Claim:
        reason = _coerce_reason(reason_code)
        if reason is None:
            raise ValueError("diagnostic claim requires a stable reason code")
        capability = ClaimCapability.RUNTIME_OR_CACHE_STATUS
        return Claim(
            claim_id=build_claim_id(
                request_id=request_id,
                subrequest_id=subrequest_id,
                capability=capability,
                scope=scope,
                evidence_ids=(),
                status=ClaimStatus.DIAGNOSTIC,
            ),
            statement=f"运行状态说明：{reason.value}",
            claim_type=capability.value,
            status=ClaimStatus.DIAGNOSTIC.value,
            confidence=None,
            evidence_ids=(),
            fact_kinds=(FactKind.DIAGNOSTIC,),
            scope=scope,
            qualifiers=(reason.value,),
            subrequest_id=subrequest_id,
            reason_codes=(reason,),
        )


def _coerce_reason(reason_code: ReasonCode | str | None) -> ReasonCode | None:
    if isinstance(reason_code, ReasonCode):
        return reason_code
    if isinstance(reason_code, str) and reason_code.strip():
        try:
            return ReasonCode(reason_code)
        except ValueError:
            return None
    return None
