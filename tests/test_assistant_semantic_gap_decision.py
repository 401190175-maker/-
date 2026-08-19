"""Tests for semantic gap decision service validation and orchestration."""

from types import SimpleNamespace
import unittest

from drawing_graph.assistant_models import (
    AssistantScope,
    AssistantSubrequest,
    EvidenceItem,
    EvidenceRequirement,
    EvidenceType,
    FactKind,
    QuestionUnderstandingResult,
    ReasonCode,
    RecognitionPolicy,
    RetrievalBundle,
    SemanticGapDecisionType,
)
from drawing_graph.assistant_semantic_gap_decision import SemanticGapDecisionService


def make_result(
    *requirements: EvidenceRequirement,
    request_id: str = "req:1",
    subrequests: tuple[AssistantSubrequest, ...] = (),
) -> QuestionUnderstandingResult:
    return QuestionUnderstandingResult(
        request_id=request_id,
        question_type="page_summary",
        required_evidence=requirements,
        subrequests=subrequests,
    )


def make_bundle(request_id: str = "req:1", subrequest_id: str | None = None) -> RetrievalBundle:
    return RetrievalBundle(request_id=request_id, subrequest_id=subrequest_id)


def make_requirement(requirement_id: str = "req:1") -> EvidenceRequirement:
    return EvidenceRequirement(
        requirement_id=requirement_id,
        evidence_type=EvidenceType.PAGE_SOURCE_FACTS,
        target_scope=AssistantScope(page_id="page:1"),
    )


class SemanticGapDecisionValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = SemanticGapDecisionService()

    def test_decide_interface_exists_and_accepts_policy_none(self):
        decision = self.service.decide(
            make_result(),
            make_bundle(),
            recognition_policy=None,
        )
        self.assertIsNotNone(decision)
        self.assertEqual("req:1", decision.request_id)

    def test_request_id_mismatch_raises_stable_value_error(self):
        with self.assertRaises(ValueError) as error:
            self.service.decide(
                make_result(request_id="req:1"),
                make_bundle(request_id="req:2"),
            )
        self.assertIn("request_id mismatch", str(error.exception))

    def test_subrequest_id_mismatch_raises_value_error(self):
        subrequest = AssistantSubrequest(
            subrequest_id="sub:1",
            question_type="page_summary",
        )
        with self.assertRaises(ValueError) as error:
            self.service.decide(
                make_result(subrequests=(subrequest,)),
                make_bundle(subrequest_id="sub:2"),
            )
        self.assertIn("subrequest_id", str(error.exception))

    def test_matching_subrequest_id_is_accepted(self):
        subrequest = AssistantSubrequest(
            subrequest_id="sub:1",
            question_type="page_summary",
        )
        decision = self.service.decide(
            make_result(subrequests=(subrequest,)),
            make_bundle(subrequest_id="sub:1"),
        )
        self.assertEqual("sub:1", decision.subrequest_id)

    def test_empty_requirement_id_is_rejected(self):
        invalid = SimpleNamespace(requirement_id="")
        with self.assertRaises(ValueError) as error:
            self.service.decide(
                make_result(invalid),
                make_bundle(),
            )
        self.assertIn("requirement_id", str(error.exception))

    def test_non_policy_recognition_policy_is_rejected(self):
        with self.assertRaises(ValueError) as error:
            self.service.decide(
                make_result(),
                make_bundle(),
                recognition_policy=object(),
            )
        self.assertIn("recognition_policy", str(error.exception))

    def test_invalid_policy_fields_are_rejected(self):
        with self.assertRaises(ValueError):
            RecognitionPolicy(allow_recognition="yes")
        with self.assertRaises(ValueError):
            RecognitionPolicy(max_estimated_cost=-1)
        with self.assertRaises(ValueError):
            RecognitionPolicy(max_latency_seconds=-1)
        with self.assertRaises(ValueError):
            RecognitionPolicy(max_targets=0)

    def test_valid_requirement_is_accepted(self):
        decision = self.service.decide(
            make_result(make_requirement()),
            make_bundle(),
        )
        self.assertEqual(1, len(decision.requirement_assessments))


class SemanticGapDecisionOrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = SemanticGapDecisionService()

    def source_fact_bundle(self) -> RetrievalBundle:
        source = EvidenceItem(
            evidence_id="evidence:source:1",
            fact_kind=FactKind.SOURCE_FACT,
            scope=AssistantScope(page_id="page:1"),
            value={},
            evidence_metadata={
                "page_id": "page:1",
                "image_path": "data/road_24.png",
                "image_hash": "hash:1",
                "bbox": {"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
            },
        )
        return RetrievalBundle(
            request_id="req:1",
            source_facts=(source,),
        )

    def element_location_bundle(self) -> RetrievalBundle:
        source = EvidenceItem(
            evidence_id="evidence:source:element:1",
            fact_kind=FactKind.SOURCE_FACT,
            scope=AssistantScope(page_id="page:1", element_id="element:1"),
            value={},
            evidence_metadata={
                "page_id": "page:1",
                "element_id": "element:1",
                "element_type": "DrawingBlock",
                "image_path": "data/road_24.png",
                "image_hash": "hash:1",
                "bbox": {"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
                "normalized_bbox": {
                    "x_min": 0.1,
                    "y_min": 0.2,
                    "x_max": 0.2,
                    "y_max": 0.3,
                },
            },
        )
        return RetrievalBundle(
            request_id="req:1",
            source_facts=(source,),
        )

    def test_all_satisfied_returns_reuse_existing(self):
        requirement = EvidenceRequirement(
            requirement_id="req:source",
            evidence_type=EvidenceType.PAGE_SOURCE_FACTS,
            target_scope=AssistantScope(page_id="page:1"),
        )
        decision = self.service.decide(
            make_result(requirement),
            self.source_fact_bundle(),
        )
        self.assertEqual(SemanticGapDecisionType.REUSE_EXISTING, decision.decision)
        self.assertEqual((), decision.missing_requirements)
        self.assertFalse(decision.write_back_recommendation)

    def test_formal_review_only_returns_reuse_existing_with_warning(self):
        requirement = EvidenceRequirement(
            requirement_id="req:match",
            evidence_type=EvidenceType.SECTION_MATCHES,
            target_scope=AssistantScope(cross_section_id="section:1"),
        )
        candidate = EvidenceItem(
            evidence_id="evidence:candidate:1",
            fact_kind=FactKind.CANDIDATE_RELATION,
            scope=AssistantScope(cross_section_id="section:1"),
            status="candidate",
            value={},
        )
        bundle = RetrievalBundle(
            request_id="req:1",
            candidate_relations=(candidate,),
        )
        decision = self.service.decide(make_result(requirement), bundle)
        self.assertEqual(SemanticGapDecisionType.REUSE_EXISTING, decision.decision)
        self.assertIn(ReasonCode.FORMAL_REVIEW_REQUIRED, decision.reason_codes)

    def test_generatable_gap_with_selected_target_returns_recognize_required(self):
        requirement = EvidenceRequirement(
            requirement_id="req:obs",
            evidence_type=EvidenceType.TEXT_OBSERVATIONS,
            target_scope=AssistantScope(page_id="page:1", element_id="element:1"),
            allow_model_generation=True,
        )
        decision = self.service.decide(
            make_result(requirement),
            self.element_location_bundle(),
        )
        self.assertEqual(SemanticGapDecisionType.RECOGNIZE_REQUIRED, decision.decision)
        self.assertIn("req:obs", decision.missing_requirements)
        self.assertEqual(1, len(decision.selected_targets))
        self.assertEqual(1, decision.estimate.selected_target_count)

    def test_missing_scope_returns_clarification_required(self):
        requirement = EvidenceRequirement(
            requirement_id="req:noscope",
            evidence_type=EvidenceType.TEXT_OBSERVATIONS,
            target_scope=AssistantScope(),
            allow_model_generation=True,
        )
        decision = self.service.decide(
            make_result(requirement),
            RetrievalBundle(request_id="req:1"),
        )
        self.assertEqual(
            SemanticGapDecisionType.CLARIFICATION_REQUIRED,
            decision.decision,
        )
        self.assertTrue(decision.warnings)
        self.assertEqual((), decision.selected_targets)

    def test_ungeneratable_gap_returns_unsupported(self):
        requirement = EvidenceRequirement(
            requirement_id="req:unsupported",
            evidence_type=EvidenceType.PAGE_SOURCE_FACTS,
            target_scope=AssistantScope(page_id="page:1"),
        )
        decision = self.service.decide(
            make_result(requirement),
            RetrievalBundle(request_id="req:1"),
        )
        self.assertEqual(SemanticGapDecisionType.UNSUPPORTED, decision.decision)
        self.assertIn("req:unsupported", decision.missing_requirements)
        self.assertIn(ReasonCode.UNSUPPORTED_GENERATION, decision.reason_codes)

    def test_reuse_existing_keeps_downstream_gap_info(self):
        requirement = EvidenceRequirement(
            requirement_id="req:source",
            evidence_type=EvidenceType.PAGE_SOURCE_FACTS,
            target_scope=AssistantScope(page_id="page:1"),
        )
        decision = self.service.decide(
            make_result(requirement),
            self.source_fact_bundle(),
        )
        self.assertEqual(1, len(decision.requirement_assessments))
        self.assertEqual(1, len(decision.cache_candidates))
        self.assertEqual((), decision.selected_targets)
        self.assertEqual((), decision.deferred_targets)


class SemanticGapSubrequestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = SemanticGapDecisionService()

    def test_consistent_projected_subrequest_id_is_preserved(self):
        question_result = QuestionUnderstandingResult(
            request_id="req:1",
            question_type="page_summary",
            subrequest_id="sub:1",
        )
        decision = self.service.decide(
            question_result,
            make_bundle(subrequest_id="sub:1"),
        )
        self.assertEqual("sub:1", decision.subrequest_id)

    def test_inconsistent_projected_subrequest_id_fails_closed(self):
        question_result = QuestionUnderstandingResult(
            request_id="req:1",
            question_type="page_summary",
            subrequest_id="sub:1",
        )
        with self.assertRaises(ValueError) as error:
            self.service.decide(
                question_result,
                make_bundle(subrequest_id="sub:2"),
            )
        self.assertIn("subrequest_id", str(error.exception))

    def test_projected_question_with_missing_bundle_subrequest_fails_closed(self):
        question_result = QuestionUnderstandingResult(
            request_id="req:1",
            question_type="page_summary",
            subrequest_id="sub:1",
        )
        with self.assertRaises(ValueError) as error:
            self.service.decide(question_result, make_bundle())
        self.assertIn("subrequest_id", str(error.exception))

    def test_top_level_none_remains_compatible(self):
        decision = self.service.decide(make_result(), make_bundle())
        self.assertIsNone(decision.subrequest_id)

    def test_subrequest_validation_does_not_change_decision_algorithm(self):
        question_result = QuestionUnderstandingResult(
            request_id="req:1",
            question_type="page_summary",
            subrequest_id="sub:1",
            required_evidence=(make_requirement(),),
        )
        decision = self.service.decide(
            question_result,
            make_bundle(subrequest_id="sub:1"),
        )
        self.assertEqual("sub:1", decision.subrequest_id)
        self.assertEqual(1, len(decision.requirement_assessments))
        self.assertFalse(decision.write_back_recommendation)


if __name__ == "__main__":
    unittest.main()
