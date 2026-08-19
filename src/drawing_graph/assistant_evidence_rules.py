"""Shared pure evidence gating rules for 03 sufficiency and 05 fusion.

本模块抽取 03 与 05 共用的 scope match、fact-kind gate、minimum status
gate 和 formal gate 纯规则。03 的 ``EvidenceSufficiencyEvaluator`` 与 05
的 claim support 都只依赖这些纯 helper，05 不反向调用完整的
``SemanticGapDecisionService``。candidate/semantic 仍不能满足
formal/source fact requirement。
"""

from __future__ import annotations

from typing import Sequence

from .assistant_models import (
    AssistantScope,
    EvidenceItem,
    EvidenceType,
    FactKind,
    ReasonCode,
)

_BAD_STATUSES = frozenset(
    {"stale", "rejected", "recognition_failed", "failed", "not_found"}
)

_ACCEPTABLE_STATUSES_BY_KIND = {
    FactKind.SOURCE_FACT: None,
    FactKind.DERIVED_RELATION: None,
    FactKind.SEMANTIC_OBSERVATION: frozenset({"confirmed"}),
    FactKind.SEMANTIC_INTERPRETATION: frozenset({"interpreted"}),
    FactKind.CANDIDATE_RELATION: frozenset(
        {"candidate", "matched_candidate", "confirmed"}
    ),
    FactKind.FORMAL_RELATION: frozenset({"formal", "confirmed"}),
}

_ALLOWED_KINDS_BY_EVIDENCE_TYPE = {
    EvidenceType.PROJECT_DRAWING_SETS: frozenset({FactKind.SOURCE_FACT}),
    EvidenceType.DRAWING_SET_PAGES: frozenset({FactKind.SOURCE_FACT}),
    EvidenceType.PAGE_SOURCE_FACTS: frozenset({FactKind.SOURCE_FACT}),
    EvidenceType.BLOCK_TRACE: frozenset({FactKind.SOURCE_FACT}),
    EvidenceType.BLOCK_RELATIONS: frozenset({FactKind.DERIVED_RELATION}),
    EvidenceType.TEXT_OBSERVATIONS: frozenset({FactKind.SEMANTIC_OBSERVATION}),
    EvidenceType.STRUCTURED_INTERPRETATIONS: frozenset({FactKind.SEMANTIC_INTERPRETATION}),
    EvidenceType.SEMANTIC_PAYLOAD: frozenset(),
    EvidenceType.CANDIDATE_RELATIONS: frozenset({FactKind.CANDIDATE_RELATION}),
    EvidenceType.SECTION_MATCHES: frozenset(
        {FactKind.CANDIDATE_RELATION, FactKind.FORMAL_RELATION}
    ),
}


def scope_matches(target: AssistantScope, scope: AssistantScope) -> bool:
    """判断证据 scope 是否落在需求目标 page/block/element 范围内。"""

    if target.element_id is not None:
        if scope.element_id != target.element_id:
            return False
    elif target.block_id is not None:
        if scope.block_id != target.block_id:
            return False
    elif target.cross_section_id is not None:
        if scope.cross_section_id != target.cross_section_id:
            return False
    elif target.table_caption_id is not None:
        if scope.table_caption_id != target.table_caption_id:
            return False
    elif target.table_id is not None:
        if scope.table_id != target.table_id:
            return False
    elif target.page_id is not None:
        if scope.page_id != target.page_id:
            return False
    else:
        return False
    if (
        target.page_id is not None
        and scope.page_id is not None
        and scope.page_id != target.page_id
    ):
        return False
    return True


def allowed_fact_kinds(evidence_type: EvidenceType) -> frozenset[FactKind]:
    """返回某证据类型允许的 fact kind 集合。"""

    return _ALLOWED_KINDS_BY_EVIDENCE_TYPE.get(evidence_type, frozenset())


def fact_kind_allowed(evidence_type: EvidenceType, fact_kind: FactKind) -> bool:
    """判断某 fact kind 是否为某证据类型所允许，禁止跨层级替代。"""

    return fact_kind in allowed_fact_kinds(evidence_type)


def status_acceptability(
    fact_kind: FactKind,
    status: str | None,
    minimum_status: str | None = None,
) -> ReasonCode | None:
    """判断状态是否可接受；不可接受时返回稳定原因码，否则返回 None。"""

    if status in _BAD_STATUSES:
        return ReasonCode.EVIDENCE_STALE if status == "stale" else ReasonCode.STATUS_INSUFFICIENT
    acceptable = _ACCEPTABLE_STATUSES_BY_KIND.get(fact_kind)
    if acceptable is not None:
        if status not in acceptable:
            return ReasonCode.STATUS_INSUFFICIENT
        if minimum_status is not None and status != minimum_status:
            return ReasonCode.STATUS_INSUFFICIENT
    return None


def formal_review_required(
    evidence_type: EvidenceType,
    matched_items: Sequence[EvidenceItem],
) -> bool:
    """formal 缺失但存在 candidate 时要求正式复核，不直接视为满足。"""

    if evidence_type is not EvidenceType.SECTION_MATCHES:
        return False
    if any(item.fact_kind is FactKind.FORMAL_RELATION for item in matched_items):
        return False
    return any(item.fact_kind is FactKind.CANDIDATE_RELATION for item in matched_items)


__all__ = (
    "allowed_fact_kinds",
    "fact_kind_allowed",
    "formal_review_required",
    "scope_matches",
    "status_acceptability",
)
