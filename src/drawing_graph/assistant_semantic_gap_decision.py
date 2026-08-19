"""Semantic gap decision orchestration for the product layer.

决策服务串联充分性、freshness/cache、目标规划与预算门控，生成唯一的
``SemanticGapDecision``。本模块是纯决策层：不调用 facade、图数据库、
数据仓储、模型客户端或 adapter，不创建识别运行记录、不写缓存或图谱，
``write_back_recommendation`` 只是建议，绝不提升任何写回授权。
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .assistant_evidence_freshness import EvidenceFreshnessEvaluator
from .assistant_evidence_sufficiency import EvidenceSufficiencyEvaluator
from .assistant_models import (
    PlanWarning,
    QuestionUnderstandingResult,
    ReasonCode,
    RecognitionPolicy,
    RecognitionTarget,
    RecognitionTargetStatus,
    RequirementAssessment,
    RequirementAssessmentStatus,
    RetrievalBundle,
    SemanticGapDecision,
    SemanticGapDecisionType,
)
from .assistant_recognition_budget import RecognitionBudgetEvaluator
from .assistant_recognition_target_planner import RecognitionTargetPlanner


_GAP_STATUSES = frozenset(
    {
        RequirementAssessmentStatus.MISSING,
        RequirementAssessmentStatus.STALE,
        RequirementAssessmentStatus.FORBIDDEN,
        RequirementAssessmentStatus.UNSUPPORTED,
        RequirementAssessmentStatus.CONFLICTING,
    }
)

_NON_GAP_STATUSES = frozenset(
    {
        RequirementAssessmentStatus.SATISFIED,
        RequirementAssessmentStatus.FORMAL_REVIEW_REQUIRED,
    }
)

_CLARIFICATION_REASONS = frozenset(
    {
        ReasonCode.SCOPE_MISSING,
        ReasonCode.TARGET_LOCATION_MISSING,
    }
)


class SemanticGapDecisionService:
    """校验输入并编排 03 模块，生成稳定的语义缺口决策。"""

    def __init__(
        self,
        sufficiency_evaluator: EvidenceSufficiencyEvaluator | None = None,
        freshness_evaluator: EvidenceFreshnessEvaluator | None = None,
        target_planner: RecognitionTargetPlanner | None = None,
        budget_evaluator: RecognitionBudgetEvaluator | None = None,
    ):
        self.sufficiency_evaluator = (
            sufficiency_evaluator or EvidenceSufficiencyEvaluator()
        )
        self.freshness_evaluator = (
            freshness_evaluator or EvidenceFreshnessEvaluator()
        )
        self.target_planner = target_planner or RecognitionTargetPlanner()
        self.budget_evaluator = budget_evaluator or RecognitionBudgetEvaluator()

    def decide(
        self,
        question_result: QuestionUnderstandingResult,
        retrieval_bundle: RetrievalBundle,
        recognition_policy: RecognitionPolicy | None = None,
    ) -> SemanticGapDecision:
        """执行完整决策编排：校验→充分性→freshness/cache→目标→预算→决策。"""

        policy = (
            recognition_policy
            if recognition_policy is not None
            else RecognitionPolicy()
        )
        self._validate(question_result, retrieval_bundle, policy)
        requirements = {
            requirement.requirement_id: requirement
            for requirement in question_result.required_evidence
        }
        assessments = self.sufficiency_evaluator.evaluate(
            question_result,
            retrieval_bundle,
        )
        assessments = self.freshness_evaluator.evaluate(
            assessments,
            retrieval_bundle,
            policy,
            requirements=requirements,
        )
        cache_candidates = self.freshness_evaluator.cache_candidates(
            assessments,
            retrieval_bundle,
            policy,
            requirements=requirements,
        )
        targets = self.target_planner.plan(
            assessments,
            retrieval_bundle,
            policy,
            requirements=requirements,
        )
        selected, deferred, estimate = self.budget_evaluator.evaluate(
            targets,
            policy,
        )
        decision = self._derive_decision(
            assessments,
            selected,
            deferred,
            targets,
            requirements,
        )
        missing_requirements = tuple(
            assessment.requirement_id
            for assessment in assessments
            if assessment.status in _GAP_STATUSES
        )
        return SemanticGapDecision(
            request_id=question_result.request_id,
            subrequest_id=retrieval_bundle.subrequest_id,
            decision=decision,
            requirement_assessments=assessments,
            missing_requirements=missing_requirements,
            cache_candidates=cache_candidates,
            selected_targets=selected,
            deferred_targets=deferred,
            estimate=estimate,
            reason_codes=self._reason_codes(
                assessments,
                targets,
                estimate,
                decision,
            ),
            write_back_recommendation=False,
            warnings=self._blocked_warnings(targets),
        )

    @staticmethod
    def _validate(
        question_result: QuestionUnderstandingResult,
        retrieval_bundle: RetrievalBundle,
        policy: RecognitionPolicy,
    ) -> None:
        """校验 request/subrequest、requirement ID 与策略，不做外部调用。"""

        if not isinstance(policy, RecognitionPolicy):
            raise ValueError("recognition_policy must be a RecognitionPolicy or None")
        if question_result.request_id != retrieval_bundle.request_id:
            raise ValueError(
                f"request_id mismatch: {question_result.request_id!r} != "
                f"{retrieval_bundle.request_id!r}"
            )
        if (
            question_result.subrequest_id is not None
            and question_result.subrequest_id != retrieval_bundle.subrequest_id
        ):
            raise ValueError(
                "subrequest_id mismatch: "
                f"question_result={question_result.subrequest_id!r} != "
                f"retrieval_bundle={retrieval_bundle.subrequest_id!r}"
            )
        if (
            retrieval_bundle.subrequest_id is not None
            and question_result.subrequests
        ):
            if not any(
                subrequest.subrequest_id == retrieval_bundle.subrequest_id
                for subrequest in question_result.subrequests
            ):
                raise ValueError(
                    "subrequest_id mismatch: "
                    f"{retrieval_bundle.subrequest_id!r} not in question subrequests"
                )
        for requirement in question_result.required_evidence:
            requirement_id = getattr(requirement, "requirement_id", None)
            if not isinstance(requirement_id, str) or not requirement_id.strip():
                raise ValueError("requirement_id must be a non-empty string")

    @staticmethod
    def _derive_decision(
        assessments: Sequence[RequirementAssessment],
        selected: Sequence[RecognitionTarget],
        deferred: Sequence[RecognitionTarget],
        targets: Sequence[RecognitionTarget],
        requirements: Mapping[str, object],
    ) -> SemanticGapDecisionType:
        """按设计规则推导最终 decision，保持可重放稳定输出。"""

        required_assessments: list[RequirementAssessment] = []
        generatable_gaps: list[RequirementAssessment] = []
        for assessment in assessments:
            requirement = requirements.get(assessment.requirement_id)
            is_required = (
                getattr(requirement, "required", True)
                if requirement is not None
                else True
            )
            if not is_required:
                continue
            required_assessments.append(assessment)
            if (
                assessment.status
                in {
                    RequirementAssessmentStatus.MISSING,
                    RequirementAssessmentStatus.STALE,
                }
                and assessment.allow_model_generation
            ):
                generatable_gaps.append(assessment)
        blocked_clarification = any(
            target.status is RecognitionTargetStatus.BLOCKED
            and any(
                reason_code in _CLARIFICATION_REASONS
                for reason_code in target.reason_codes
            )
            for target in targets
        )
        if not generatable_gaps and all(
            assessment.status in _NON_GAP_STATUSES
            for assessment in required_assessments
        ):
            return SemanticGapDecisionType.REUSE_EXISTING
        if generatable_gaps and (selected or deferred):
            return SemanticGapDecisionType.RECOGNIZE_REQUIRED
        if blocked_clarification:
            return SemanticGapDecisionType.CLARIFICATION_REQUIRED
        return SemanticGapDecisionType.UNSUPPORTED

    @staticmethod
    def _reason_codes(
        assessments: Sequence[RequirementAssessment],
        targets: Sequence[RecognitionTarget],
        estimate: object,
        decision: SemanticGapDecisionType,
    ) -> tuple[ReasonCode, ...]:
        """聚合评估、目标与估算原因码，保持稳定顺序。"""

        codes: list[ReasonCode] = []
        for assessment in assessments:
            codes.extend(assessment.reason_codes)
        for target in targets:
            codes.extend(target.reason_codes)
        if estimate is not None:
            codes.extend(getattr(estimate, "reason_codes", ()))
        if decision is SemanticGapDecisionType.REUSE_EXISTING and any(
            assessment.status is RequirementAssessmentStatus.FORMAL_REVIEW_REQUIRED
            for assessment in assessments
        ):
            codes.append(ReasonCode.FORMAL_REVIEW_REQUIRED)
        return tuple(dict.fromkeys(codes))

    @staticmethod
    def _blocked_warnings(
        targets: Sequence[RecognitionTarget],
    ) -> tuple[PlanWarning, ...]:
        """把 blocked 目标转为可追溯 warning，不静默丢弃缺口。"""

        warnings: list[PlanWarning] = []
        for target in targets:
            if target.status is not RecognitionTargetStatus.BLOCKED:
                continue
            requirement_id = (
                target.covered_requirement_ids[0]
                if target.covered_requirement_ids
                else None
            )
            warnings.append(
                PlanWarning(
                    reason_code=(
                        target.reason_codes[0]
                        if target.reason_codes
                        else ReasonCode.TARGET_LOCATION_MISSING
                    ),
                    message=(
                        f"recognition target for requirement "
                        f"{requirement_id} was blocked"
                    ),
                    requirement_id=requirement_id,
                )
            )
        return tuple(warnings)


__all__ = ("SemanticGapDecisionService",)
