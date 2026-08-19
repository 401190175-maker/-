"""Answerability evaluation for the 05 fusion layer.

先按 subrequest 计算 answerability，再确定性聚合到整个 request，避免多
意图请求中单个失败掩盖其他可回答部分。answerability 以证据需求满足为主，
不由不同事实等级的简单平均置信度决定。
"""

from __future__ import annotations

from typing import Sequence

from .assistant_evidence_fusion_models import (
    Answerability,
    AnswerabilityResult,
    ClaimSupportAssessment,
    ClaimSupportStatus,
    ConflictRecord,
)
from .assistant_models import (
    EvidenceRequirement,
    QuestionUnderstandingResult,
    ReasonCode,
    SemanticGapDecision,
)

_ANSWERABLE_STATUSES = frozenset(
    {ClaimSupportStatus.SUPPORTED, ClaimSupportStatus.SUPPORTED_WITH_QUALIFIER}
)


class AnswerabilityEvaluator:
    """先对每个 subrequest 聚合 required/optional assessment，再聚合 request。"""

    def evaluate(
        self,
        question_result: QuestionUnderstandingResult,
        assessments: tuple[ClaimSupportAssessment, ...],
        conflicts: tuple[ConflictRecord, ...] = (),
        decision: SemanticGapDecision | None = None,
    ) -> AnswerabilityResult:
        """聚合 request 级 answerability。"""

        del decision
        if question_result.subrequests:
            subresults = tuple(
                self.evaluate_subrequest(
                    subrequest.required_evidence,
                    tuple(
                        item
                        for item in assessments
                        if item.subrequest_id is None
                        or item.subrequest_id == subrequest.subrequest_id
                    ),
                    conflicts,
                    subrequest_id=subrequest.subrequest_id,
                )
                for subrequest in question_result.subrequests
            )
            return self._aggregate(subresults)
        return self.evaluate_subrequest(
            question_result.required_evidence,
            assessments,
            conflicts,
            subrequest_id=question_result.subrequest_id,
        )

    @staticmethod
    def _aggregate(subresults: Sequence[AnswerabilityResult]) -> AnswerabilityResult:
        statuses = [item.status for item in subresults]
        if any(status is Answerability.CLARIFICATION_REQUIRED for status in statuses):
            return AnswerabilityResult(
                status=Answerability.CLARIFICATION_REQUIRED,
                subrequest_results=tuple(subresults),
            )
        if statuses and all(status is Answerability.ANSWERABLE for status in statuses):
            return AnswerabilityResult(
                status=Answerability.ANSWERABLE,
                subrequest_results=tuple(subresults),
            )
        if statuses and all(status is Answerability.UNSUPPORTED for status in statuses):
            return AnswerabilityResult(
                status=Answerability.UNSUPPORTED,
                subrequest_results=tuple(subresults),
            )
        return AnswerabilityResult(
            status=Answerability.PARTIALLY_ANSWERABLE,
            subrequest_results=tuple(subresults),
        )

    def evaluate_subrequest(
        self,
        requirements: Sequence[EvidenceRequirement],
        assessments: Sequence[ClaimSupportAssessment],
        conflicts: Sequence[ConflictRecord] = (),
        *,
        subrequest_id: str | None = None,
    ) -> AnswerabilityResult:
        """计算单个 subrequest 的 answerability。"""

        assessments_by_id = {item.requirement_id: item for item in assessments}
        required_assessments = tuple(
            assessments_by_id[requirement.requirement_id]
            for requirement in requirements
            if requirement.required and requirement.requirement_id in assessments_by_id
        )
        required_ids = tuple(item.requirement_id for item in required_assessments)

        # scope 缺失/冲突/指代不唯一且无法继续 -> clarification_required；
        # 已可答的评估即使混入被拒证据的 scope 原因码也不再退回澄清。
        if any(
            item.status not in _ANSWERABLE_STATUSES
            and (
                ReasonCode.SCOPE_MISSING in item.reason_codes
                or ReasonCode.SCOPE_CONFLICT in item.reason_codes
            )
            for item in required_assessments
        ):
            return AnswerabilityResult(
                status=Answerability.CLARIFICATION_REQUIRED,
                subrequest_id=subrequest_id,
                blocking_reason_codes=(ReasonCode.SCOPE_MISSING,),
                affected_requirement_ids=required_ids,
            )

        if not required_assessments:
            return AnswerabilityResult(
                status=Answerability.ANSWERABLE,
                subrequest_id=subrequest_id,
            )

        # capability 不支持且没有可答 required -> unsupported
        if all(
            item.status is ClaimSupportStatus.UNSUPPORTED
            for item in required_assessments
        ):
            return AnswerabilityResult(
                status=Answerability.UNSUPPORTED,
                subrequest_id=subrequest_id,
                reason_codes=(ReasonCode.UNSUPPORTED_GENERATION,),
                affected_requirement_ids=required_ids,
            )

        answerable = [item for item in required_assessments if item.status in _ANSWERABLE_STATUSES]
        blocking = any(conflict.blocks_answer for conflict in conflicts)

        if len(answerable) == len(required_assessments) and not blocking:
            return AnswerabilityResult(
                status=Answerability.ANSWERABLE,
                subrequest_id=subrequest_id,
            )

        return AnswerabilityResult(
            status=Answerability.PARTIALLY_ANSWERABLE,
            subrequest_id=subrequest_id,
            affected_requirement_ids=required_ids,
        )
