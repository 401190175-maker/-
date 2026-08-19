"""Tests for answerability evaluation (Task 31-32)."""

import unittest

from drawing_graph.assistant_answerability import AnswerabilityEvaluator
from drawing_graph.assistant_evidence_fusion_models import (
    Answerability,
    AnswerabilityResult,
    ClaimCapability,
    ClaimSupportAssessment,
    ClaimSupportStatus,
    ConflictRecord,
    ConflictSeverity,
    ConflictType,
)
from drawing_graph.assistant_models import (
    AssistantScope,
    AssistantSubrequest,
    EvidenceRequirement,
    EvidenceType,
    QuestionUnderstandingResult,
    ReasonCode,
)


def requirement(requirement_id, required=True, evidence_type=EvidenceType.TEXT_OBSERVATIONS):
    return EvidenceRequirement(
        requirement_id=requirement_id,
        evidence_type=evidence_type,
        target_scope=AssistantScope(page_id="page:1"),
        required=required,
    )


def assessment(requirement_id, status, reason_codes=(), subrequest_id=None):
    return ClaimSupportAssessment(
        requirement_id=requirement_id,
        claim_capability=ClaimCapability.OBSERVED_TEXT_OR_SYMBOL,
        status=status,
        reason_codes=reason_codes,
        subrequest_id=subrequest_id,
    )


class SubrequestAnswerabilityTests(unittest.TestCase):
    def test_all_required_supported_is_answerable(self):
        evaluator = AnswerabilityEvaluator()
        result = evaluator.evaluate_subrequest(
            (requirement("req:1"),),
            (assessment("req:1", ClaimSupportStatus.SUPPORTED),),
        )
        self.assertEqual(Answerability.ANSWERABLE, result.status)

    def test_supported_with_qualifier_is_answerable(self):
        evaluator = AnswerabilityEvaluator()
        result = evaluator.evaluate_subrequest(
            (requirement("req:1"),),
            (assessment("req:1", ClaimSupportStatus.SUPPORTED_WITH_QUALIFIER),),
        )
        self.assertEqual(Answerability.ANSWERABLE, result.status)

    def test_missing_required_is_partially_answerable(self):
        evaluator = AnswerabilityEvaluator()
        result = evaluator.evaluate_subrequest(
            (requirement("req:1"),),
            (assessment("req:1", ClaimSupportStatus.MISSING),),
        )
        self.assertEqual(Answerability.PARTIALLY_ANSWERABLE, result.status)

    def test_stale_only_is_not_answerable(self):
        evaluator = AnswerabilityEvaluator()
        result = evaluator.evaluate_subrequest(
            (requirement("req:1"),),
            (assessment("req:1", ClaimSupportStatus.STALE_ONLY),),
        )
        self.assertEqual(Answerability.PARTIALLY_ANSWERABLE, result.status)

    def test_formal_review_required_is_at_most_partially(self):
        evaluator = AnswerabilityEvaluator()
        result = evaluator.evaluate_subrequest(
            (requirement("req:1", evidence_type=EvidenceType.SECTION_MATCHES),),
            (assessment("req:1", ClaimSupportStatus.FORMAL_REVIEW_REQUIRED),),
        )
        self.assertEqual(Answerability.PARTIALLY_ANSWERABLE, result.status)

    def test_scope_missing_prioritizes_clarification(self):
        evaluator = AnswerabilityEvaluator()
        result = evaluator.evaluate_subrequest(
            (requirement("req:1"),),
            (assessment("req:1", ClaimSupportStatus.MISSING, reason_codes=(ReasonCode.SCOPE_MISSING,)),),
        )
        self.assertEqual(Answerability.CLARIFICATION_REQUIRED, result.status)

    def test_scope_conflict_prioritizes_clarification(self):
        evaluator = AnswerabilityEvaluator()
        result = evaluator.evaluate_subrequest(
            (requirement("req:1"),),
            (assessment("req:1", ClaimSupportStatus.MISSING, reason_codes=(ReasonCode.SCOPE_CONFLICT,)),),
        )
        self.assertEqual(Answerability.CLARIFICATION_REQUIRED, result.status)

    def test_supported_with_scope_conflict_noise_is_answerable(self):
        evaluator = AnswerabilityEvaluator()
        result = evaluator.evaluate_subrequest(
            (requirement("req:1"),),
            (
                assessment(
                    "req:1",
                    ClaimSupportStatus.SUPPORTED,
                    reason_codes=(ReasonCode.SCOPE_CONFLICT, ReasonCode.EVIDENCE_KIND_MISMATCH),
                ),
            ),
        )
        self.assertEqual(Answerability.ANSWERABLE, result.status)

    def test_unsupported_capability_is_unsupported(self):
        evaluator = AnswerabilityEvaluator()
        result = evaluator.evaluate_subrequest(
            (requirement("req:1"),),
            (assessment("req:1", ClaimSupportStatus.UNSUPPORTED),),
        )
        self.assertEqual(Answerability.UNSUPPORTED, result.status)

    def test_blocking_conflict_prevents_answerable(self):
        evaluator = AnswerabilityEvaluator()
        conflict = ConflictRecord(
            conflict_id="conflict:1",
            comparison_key="comparison:1",
            conflict_type=ConflictType.HARD_CONFLICT,
            severity=ConflictSeverity.BLOCKING,
            evidence_ids=("e:1", "e:2"),
        )
        result = evaluator.evaluate_subrequest(
            (requirement("req:1"),),
            (assessment("req:1", ClaimSupportStatus.SUPPORTED),),
            (conflict,),
        )
        self.assertEqual(Answerability.PARTIALLY_ANSWERABLE, result.status)

    def test_partial_requirement_is_partially_answerable(self):
        evaluator = AnswerabilityEvaluator()
        result = evaluator.evaluate_subrequest(
            (requirement("req:1"), requirement("req:2")),
            (
                assessment("req:1", ClaimSupportStatus.SUPPORTED),
                assessment("req:2", ClaimSupportStatus.MISSING),
            ),
        )
        self.assertEqual(Answerability.PARTIALLY_ANSWERABLE, result.status)

    def test_no_required_assessments_is_answerable(self):
        evaluator = AnswerabilityEvaluator()
        result = evaluator.evaluate_subrequest((), ())
        self.assertEqual(Answerability.ANSWERABLE, result.status)

    def test_optional_only_missing_does_not_block_answerable(self):
        evaluator = AnswerabilityEvaluator()
        result = evaluator.evaluate_subrequest(
            (requirement("req:1", required=False),),
            (assessment("req:1", ClaimSupportStatus.MISSING),),
        )
        self.assertEqual(Answerability.ANSWERABLE, result.status)


class RequestAnswerabilityTests(unittest.TestCase):
    def _question_result(self, subrequests):
        return QuestionUnderstandingResult(
            request_id="req:1",
            question_type="multi_intent",
            subrequests=subrequests,
        )

    def _subrequest(self, subrequest_id, requirement_ids):
        return AssistantSubrequest(
            subrequest_id=subrequest_id,
            question_type="page_summary",
            required_evidence=tuple(requirement(rid) for rid in requirement_ids),
        )

    def test_all_subrequests_answerable_is_answerable(self):
        evaluator = AnswerabilityEvaluator()
        question_result = self._question_result(
            (self._subrequest("sub:1", ("req:1",)), self._subrequest("sub:2", ("req:2",)))
        )
        assessments = (
            assessment("req:1", ClaimSupportStatus.SUPPORTED, subrequest_id="sub:1"),
            assessment("req:2", ClaimSupportStatus.SUPPORTED, subrequest_id="sub:2"),
        )
        result = evaluator.evaluate(question_result, assessments)
        self.assertEqual(Answerability.ANSWERABLE, result.status)
        self.assertEqual(2, len(result.subrequest_results))

    def test_any_clarification_prioritizes_clarification(self):
        evaluator = AnswerabilityEvaluator()
        question_result = self._question_result(
            (self._subrequest("sub:1", ("req:1",)), self._subrequest("sub:2", ("req:2",)))
        )
        assessments = (
            assessment("req:1", ClaimSupportStatus.SUPPORTED, subrequest_id="sub:1"),
            assessment("req:2", ClaimSupportStatus.MISSING, reason_codes=(ReasonCode.SCOPE_MISSING,), subrequest_id="sub:2"),
        )
        result = evaluator.evaluate(question_result, assessments)
        self.assertEqual(Answerability.CLARIFICATION_REQUIRED, result.status)

    def test_all_unsupported_is_unsupported(self):
        evaluator = AnswerabilityEvaluator()
        question_result = self._question_result((self._subrequest("sub:1", ("req:1",)),))
        assessments = (assessment("req:1", ClaimSupportStatus.UNSUPPORTED, subrequest_id="sub:1"),)
        result = evaluator.evaluate(question_result, assessments)
        self.assertEqual(Answerability.UNSUPPORTED, result.status)

    def test_mixed_states_are_partially_answerable(self):
        evaluator = AnswerabilityEvaluator()
        question_result = self._question_result(
            (self._subrequest("sub:1", ("req:1",)), self._subrequest("sub:2", ("req:2",)))
        )
        assessments = (
            assessment("req:1", ClaimSupportStatus.SUPPORTED, subrequest_id="sub:1"),
            assessment("req:2", ClaimSupportStatus.UNSUPPORTED, subrequest_id="sub:2"),
        )
        result = evaluator.evaluate(question_result, assessments)
        self.assertEqual(Answerability.PARTIALLY_ANSWERABLE, result.status)

    def test_single_intent_uses_required_evidence(self):
        evaluator = AnswerabilityEvaluator()
        question_result = QuestionUnderstandingResult(
            request_id="req:1",
            question_type="page_summary",
            required_evidence=(requirement("req:1"),),
        )
        assessments = (assessment("req:1", ClaimSupportStatus.SUPPORTED),)
        result = evaluator.evaluate(question_result, assessments)
        self.assertEqual(Answerability.ANSWERABLE, result.status)


class AnswerabilitySubrequestTests(unittest.TestCase):
    def test_single_intent_projected_result_preserves_subrequest_id(self):
        evaluator = AnswerabilityEvaluator()
        question_result = QuestionUnderstandingResult(
            request_id="req:1",
            question_type="page_summary",
            subrequest_id="sub:1",
            required_evidence=(requirement("req:1"),),
        )
        result = evaluator.evaluate(
            question_result,
            (assessment("req:1", ClaimSupportStatus.SUPPORTED),),
        )
        self.assertEqual(Answerability.ANSWERABLE, result.status)
        self.assertEqual("sub:1", result.subrequest_id)

    def test_single_intent_top_level_preserves_none(self):
        evaluator = AnswerabilityEvaluator()
        question_result = QuestionUnderstandingResult(
            request_id="req:1",
            question_type="page_summary",
            required_evidence=(requirement("req:1"),),
        )
        result = evaluator.evaluate(
            question_result,
            (assessment("req:1", ClaimSupportStatus.SUPPORTED),),
        )
        self.assertIsNone(result.subrequest_id)

    def test_multi_intent_subrequest_results_keep_ids(self):
        evaluator = AnswerabilityEvaluator()
        question_result = QuestionUnderstandingResult(
            request_id="req:1",
            question_type="multi_intent",
            subrequests=(
                AssistantSubrequest(
                    subrequest_id="sub:1",
                    question_type="page_summary",
                    required_evidence=(requirement("req:1"),),
                ),
            ),
        )
        result = evaluator.evaluate(
            question_result,
            (assessment("req:1", ClaimSupportStatus.SUPPORTED, subrequest_id="sub:1"),),
        )
        self.assertEqual(1, len(result.subrequest_results))
        self.assertEqual("sub:1", result.subrequest_results[0].subrequest_id)

    def test_mismatched_subrequest_assessment_is_not_merged(self):
        evaluator = AnswerabilityEvaluator()
        question_result = QuestionUnderstandingResult(
            request_id="req:1",
            question_type="multi_intent",
            subrequests=(
                AssistantSubrequest(
                    subrequest_id="sub:1",
                    question_type="page_summary",
                    required_evidence=(requirement("req:1"),),
                ),
            ),
        )
        result = evaluator.evaluate(
            question_result,
            (assessment("req:1", ClaimSupportStatus.SUPPORTED, subrequest_id="sub:other"),),
        )
        self.assertEqual(1, len(result.subrequest_results))
        self.assertEqual("sub:1", result.subrequest_results[0].subrequest_id)
        self.assertEqual(Answerability.ANSWERABLE, result.subrequest_results[0].status)


if __name__ == "__main__":
    unittest.main()
