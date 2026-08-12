"""Deterministic evidence sufficiency evaluation for the semantic gap loop.

充分性评估器按 ``EvidenceRequirement`` 逐个比较 ``RetrievalBundle`` 中的证据，
输出独立的 ``RequirementAssessment``，不给整个 bundle 一个总状态。
本模块是纯决策层：不调用 ``DrawingGraphToolFacade``、图数据库、数据仓储、
Qwen/DashScope、HTTP/MCP/CLI，不创建 ``RecognitionRun``，不写缓存或图谱。
事实分层不变量（candidate 不能满足 formal、observation 不能满足
interpretation 等）由后续任务逐步细化，本文件只提供稳定骨架。
"""

from __future__ import annotations

from typing import Sequence

from .assistant_models import (
    AssistantScope,
    EvidenceItem,
    EvidenceRequirement,
    EvidenceType,
    FactKind,
    QuestionUnderstandingResult,
    ReasonCode,
    RequirementAssessment,
    RequirementAssessmentStatus,
    RetrievalBundle,
)


_BUCKETS_BY_EVIDENCE_TYPE = {
    EvidenceType.PROJECT_DRAWING_SETS: ("source_facts",),
    EvidenceType.DRAWING_SET_PAGES: ("source_facts",),
    EvidenceType.PAGE_SOURCE_FACTS: ("source_facts",),
    EvidenceType.BLOCK_TRACE: ("source_facts",),
    EvidenceType.BLOCK_RELATIONS: ("derived_relations",),
    EvidenceType.TEXT_OBSERVATIONS: ("semantic_observations",),
    EvidenceType.STRUCTURED_INTERPRETATIONS: ("semantic_interpretations",),
    EvidenceType.SEMANTIC_PAYLOAD: (),
    EvidenceType.CANDIDATE_RELATIONS: ("candidate_relations",),
    EvidenceType.SECTION_MATCHES: ("candidate_relations", "formal_relations"),
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

_GENERATABLE_EVIDENCE_TYPES = frozenset(
    {
        EvidenceType.TEXT_OBSERVATIONS,
        EvidenceType.STRUCTURED_INTERPRETATIONS,
    }
)


class EvidenceSufficiencyEvaluator:
    """逐个证据需求输出独立充分性评估结果。"""

    def evaluate(
        self,
        question_result: QuestionUnderstandingResult,
        retrieval_bundle: RetrievalBundle,
    ) -> tuple[RequirementAssessment, ...]:
        """为每个 requirement 生成一条 assessment，空 bundle 不抛异常。"""

        return tuple(
            self._assess(requirement, retrieval_bundle)
            for requirement in question_result.required_evidence
        )

    def _assess(
        self,
        requirement: EvidenceRequirement,
        bundle: RetrievalBundle,
    ) -> RequirementAssessment:
        """对单个需求执行 scope/kind 过滤并生成 assessment。"""

        items = self._bucket_items(requirement, bundle)
        matched, rejected, reject_reasons = self._scope_filter(requirement, items)
        matched, rejected, reject_reasons = self._kind_filter(
            requirement,
            matched,
            rejected,
            reject_reasons,
        )
        formal_review = self._formal_gate(requirement, matched)
        matched, rejected, reject_reasons, conflicting = self._status_filter(
            requirement,
            matched,
            rejected,
            reject_reasons,
        )
        return self._build_assessment(
            requirement,
            matched,
            rejected,
            reject_reasons,
            formal_review,
            conflicting,
        )

    @staticmethod
    def _bucket_items(
        requirement: EvidenceRequirement,
        bundle: RetrievalBundle,
    ) -> list[EvidenceItem]:
        """返回需求证据类型对应的固定桶中的全部证据。"""

        bucket_names = _BUCKETS_BY_EVIDENCE_TYPE.get(requirement.evidence_type, ())
        items: list[EvidenceItem] = []
        for bucket_name in bucket_names:
            items.extend(getattr(bundle, bucket_name))
        return items

    @staticmethod
    def _scope_filter(
        requirement: EvidenceRequirement,
        items: Sequence[EvidenceItem],
    ) -> tuple[list[EvidenceItem], list[EvidenceItem], list[ReasonCode]]:
        """按需求 scope 拆分匹配/拒绝证据，防止跨 page/block/element 误用。"""

        target = requirement.target_scope
        matched: list[EvidenceItem] = []
        rejected: list[EvidenceItem] = []
        reasons: list[ReasonCode] = []
        for item in items:
            scope = item.scope
            if scope is None:
                rejected.append(item)
                reasons.append(ReasonCode.SCOPE_MISSING)
            elif EvidenceSufficiencyEvaluator._item_matches_scope(target, scope):
                matched.append(item)
            else:
                rejected.append(item)
                reasons.append(ReasonCode.SCOPE_CONFLICT)
        return matched, rejected, EvidenceSufficiencyEvaluator._dedupe_reasons(reasons)

    @staticmethod
    def _kind_filter(
        requirement: EvidenceRequirement,
        matched: Sequence[EvidenceItem],
        rejected: Sequence[EvidenceItem],
        reject_reasons: Sequence[ReasonCode],
    ) -> tuple[list[EvidenceItem], list[EvidenceItem], list[ReasonCode]]:
        """按 fact kind 允许集过滤，禁止跨层级替代证据。"""

        allowed = _ALLOWED_KINDS_BY_EVIDENCE_TYPE.get(
            requirement.evidence_type,
            frozenset(),
        )
        kept: list[EvidenceItem] = []
        kind_rejected: list[EvidenceItem] = []
        reasons = list(reject_reasons)
        for item in matched:
            if item.fact_kind in allowed:
                kept.append(item)
            else:
                kind_rejected.append(item)
                reasons.append(ReasonCode.EVIDENCE_KIND_MISMATCH)
        return kept, list(rejected) + kind_rejected, EvidenceSufficiencyEvaluator._dedupe_reasons(reasons)

    @staticmethod
    def _formal_gate(
        requirement: EvidenceRequirement,
        matched: Sequence[EvidenceItem],
    ) -> bool:
        """formal 缺失但存在 candidate 时要求正式复核，不直接视为满足。"""

        if requirement.evidence_type is not EvidenceType.SECTION_MATCHES:
            return False
        if any(item.fact_kind is FactKind.FORMAL_RELATION for item in matched):
            return False
        return any(item.fact_kind is FactKind.CANDIDATE_RELATION for item in matched)

    @staticmethod
    def _status_filter(
        requirement: EvidenceRequirement,
        matched: Sequence[EvidenceItem],
        rejected: Sequence[EvidenceItem],
        reject_reasons: Sequence[ReasonCode],
    ) -> tuple[list[EvidenceItem], list[EvidenceItem], list[ReasonCode], bool]:
        """按证据类型的可接受状态过滤，并检测同一目标上的互斥证据。"""

        minimum = requirement.minimum_status
        kept: list[EvidenceItem] = []
        status_rejected: list[EvidenceItem] = []
        reasons = list(reject_reasons)
        for item in matched:
            status = item.status
            if status in _BAD_STATUSES:
                status_rejected.append(item)
                reasons.append(
                    ReasonCode.EVIDENCE_STALE
                    if status == "stale"
                    else ReasonCode.STATUS_INSUFFICIENT
                )
                continue
            acceptable = _ACCEPTABLE_STATUSES_BY_KIND.get(item.fact_kind)
            if acceptable is not None:
                if status not in acceptable:
                    status_rejected.append(item)
                    reasons.append(ReasonCode.STATUS_INSUFFICIENT)
                    continue
                if minimum is not None and status != minimum:
                    status_rejected.append(item)
                    reasons.append(ReasonCode.STATUS_INSUFFICIENT)
                    continue
            kept.append(item)
        conflicting_items = EvidenceSufficiencyEvaluator._conflicting_items(kept)
        if conflicting_items:
            conflict_ids = {item.evidence_id for item in conflicting_items}
            kept = [item for item in kept if item.evidence_id not in conflict_ids]
            status_rejected.extend(conflicting_items)
            reasons.append(ReasonCode.EVIDENCE_CONFLICT)
            return (
                kept,
                list(rejected) + status_rejected,
                EvidenceSufficiencyEvaluator._dedupe_reasons(reasons),
                True,
            )
        return (
            kept,
            list(rejected) + status_rejected,
            EvidenceSufficiencyEvaluator._dedupe_reasons(reasons),
            False,
        )

    @staticmethod
    def _conflicting_items(items: Sequence[EvidenceItem]) -> list[EvidenceItem]:
        """同一目标存在多种互斥状态时返回冲突证据，避免把歧义当满足。"""

        by_target: dict[tuple[str | None, ...], list[EvidenceItem]] = {}
        for item in items:
            scope = item.scope
            key = (
                scope.page_id if scope is not None else None,
                scope.block_id if scope is not None else None,
                scope.element_id if scope is not None else None,
                scope.cross_section_id if scope is not None else None,
                scope.table_id if scope is not None else None,
                scope.table_caption_id if scope is not None else None,
            )
            by_target.setdefault(key, []).append(item)
        conflicting: list[EvidenceItem] = []
        for group in by_target.values():
            if len(group) > 1 and len({item.status for item in group}) > 1:
                conflicting.extend(group)
        return conflicting

    @staticmethod
    def _item_matches_scope(target: AssistantScope, scope: AssistantScope) -> bool:
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

    @staticmethod
    def _build_assessment(
        requirement: EvidenceRequirement,
        matched: Sequence[EvidenceItem],
        rejected: Sequence[EvidenceItem],
        reject_reasons: Sequence[ReasonCode],
        formal_review: bool,
        conflicting: bool,
    ) -> RequirementAssessment:
        """按匹配结果构造评估；scope 缺失时明确返回 ``scope_missing``。"""

        target = requirement.target_scope
        scope_present = any(
            value is not None
            for value in (
                target.page_id,
                target.block_id,
                target.element_id,
                target.cross_section_id,
                target.table_id,
                target.table_caption_id,
                target.claim_id,
            )
        )
        if not scope_present:
            return RequirementAssessment(
                requirement_id=requirement.requirement_id,
                status=RequirementAssessmentStatus.MISSING,
                reason_codes=(ReasonCode.SCOPE_MISSING,),
                allow_model_generation=requirement.allow_model_generation,
            )
        matched_ids = tuple(item.evidence_id for item in matched)
        if conflicting:
            status = RequirementAssessmentStatus.CONFLICTING
            reasons = [ReasonCode.EVIDENCE_CONFLICT]
            allow_generation = requirement.allow_model_generation
        elif formal_review:
            status = RequirementAssessmentStatus.FORMAL_REVIEW_REQUIRED
            reasons = [ReasonCode.FORMAL_REVIEW_REQUIRED]
            allow_generation = False
        elif matched:
            status = RequirementAssessmentStatus.SATISFIED
            reasons = [ReasonCode.EVIDENCE_COMPLETE]
            allow_generation = requirement.allow_model_generation
        else:
            if not requirement.required:
                status = RequirementAssessmentStatus.MISSING
                reasons = [ReasonCode.EVIDENCE_MISSING]
                allow_generation = requirement.allow_model_generation
            elif requirement.evidence_type in _GENERATABLE_EVIDENCE_TYPES:
                if requirement.allow_model_generation:
                    status = RequirementAssessmentStatus.MISSING
                    missing_code = (
                        ReasonCode.OBSERVATION_MISSING
                        if requirement.evidence_type is EvidenceType.TEXT_OBSERVATIONS
                        else ReasonCode.INTERPRETATION_MISSING
                    )
                    reasons = [missing_code]
                    allow_generation = True
                else:
                    status = RequirementAssessmentStatus.FORBIDDEN
                    reasons = [ReasonCode.RECOGNITION_FORBIDDEN]
                    allow_generation = False
            else:
                status = RequirementAssessmentStatus.UNSUPPORTED
                reasons = [ReasonCode.UNSUPPORTED_GENERATION]
                allow_generation = False
        reasons.extend(reject_reasons)
        return RequirementAssessment(
            requirement_id=requirement.requirement_id,
            status=status,
            matched_evidence_ids=matched_ids,
            rejected_evidence_ids=tuple(item.evidence_id for item in rejected),
            reason_codes=tuple(EvidenceSufficiencyEvaluator._dedupe_reasons(reasons)),
            allow_model_generation=allow_generation,
        )

    @staticmethod
    def _dedupe_reasons(
        reasons: Sequence[ReasonCode],
    ) -> list[ReasonCode]:
        """按首次出现顺序去重原因码，保持输出稳定。"""

        seen: set[ReasonCode] = set()
        ordered: list[ReasonCode] = []
        for reason in reasons:
            if reason not in seen:
                seen.add(reason)
                ordered.append(reason)
        return ordered


__all__ = ("EvidenceSufficiencyEvaluator",)
