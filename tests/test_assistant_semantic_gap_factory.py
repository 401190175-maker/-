"""Tests for the semantic gap decision service factory wiring."""

import unittest

from drawing_graph.assistant_evidence_freshness import EvidenceFreshnessEvaluator
from drawing_graph.assistant_evidence_sufficiency import EvidenceSufficiencyEvaluator
from drawing_graph.assistant_models import (
    AssistantScope,
    EvidenceRequirement,
    EvidenceType,
    QuestionUnderstandingResult,
    RetrievalBundle,
)
from drawing_graph.assistant_recognition_budget import RecognitionBudgetEvaluator
from drawing_graph.assistant_recognition_target_planner import RecognitionTargetPlanner
from drawing_graph.assistant_semantic_gap_decision import SemanticGapDecisionService
from drawing_graph.tool_factory import create_semantic_gap_decision_service


class SemanticGapFactoryTests(unittest.TestCase):
    def test_factory_creates_fully_wired_decision_service(self):
        service = create_semantic_gap_decision_service()
        self.assertIsInstance(service, SemanticGapDecisionService)
        self.assertIsInstance(
            service.sufficiency_evaluator,
            EvidenceSufficiencyEvaluator,
        )
        self.assertIsInstance(
            service.freshness_evaluator,
            EvidenceFreshnessEvaluator,
        )
        self.assertIsInstance(service.target_planner, RecognitionTargetPlanner)
        self.assertIsInstance(service.budget_evaluator, RecognitionBudgetEvaluator)

    def test_factory_service_runs_with_fake_inputs(self):
        service = create_semantic_gap_decision_service()
        requirement = EvidenceRequirement(
            requirement_id="req:1",
            evidence_type=EvidenceType.PAGE_SOURCE_FACTS,
            target_scope=AssistantScope(page_id="page:1"),
        )
        question_result = QuestionUnderstandingResult(
            request_id="req:1",
            question_type="page_summary",
            required_evidence=(requirement,),
        )
        bundle = RetrievalBundle(request_id="req:1")

        decision = service.decide(question_result, bundle)

        self.assertEqual("req:1", decision.request_id)
        self.assertEqual(1, len(decision.requirement_assessments))

    def test_factory_creation_does_not_require_database_or_credentials(self):
        # No driver, env credentials, or network are touched during creation;
        # construction and a fake-input run must succeed without them.
        service = create_semantic_gap_decision_service()
        requirement = EvidenceRequirement(
            requirement_id="req:2",
            evidence_type=EvidenceType.TEXT_OBSERVATIONS,
            target_scope=AssistantScope(page_id="page:1", element_id="element:1"),
            allow_model_generation=True,
        )
        question_result = QuestionUnderstandingResult(
            request_id="req:2",
            question_type="element_text_or_meaning",
            required_evidence=(requirement,),
        )
        decision = service.decide(
            question_result,
            RetrievalBundle(request_id="req:2"),
        )
        self.assertTrue(decision.requirement_assessments)


if __name__ == "__main__":
    unittest.main()
