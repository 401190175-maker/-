"""Tests for the evidence sufficiency evaluator skeleton."""

import inspect
from pathlib import Path
import unittest

from drawing_graph.assistant_evidence_sufficiency import EvidenceSufficiencyEvaluator
from drawing_graph.assistant_models import (
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


def make_result(*requirements: EvidenceRequirement) -> QuestionUnderstandingResult:
    return QuestionUnderstandingResult(
        request_id="req:1",
        question_type="page_summary",
        required_evidence=requirements,
    )


def make_requirement(evidence_type: EvidenceType) -> EvidenceRequirement:
    return EvidenceRequirement(
        requirement_id=f"req:{evidence_type.value}",
        evidence_type=evidence_type,
        target_scope=AssistantScope(page_id="page:1"),
    )


class EvidenceSufficiencyEvaluatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluator = EvidenceSufficiencyEvaluator()

    def test_every_requirement_gets_an_assessment(self):
        requirements = (
            make_requirement(EvidenceType.PAGE_SOURCE_FACTS),
            make_requirement(EvidenceType.TEXT_OBSERVATIONS),
        )
        bundle = RetrievalBundle(request_id="req:1")
        assessments = self.evaluator.evaluate(make_result(*requirements), bundle)
        self.assertEqual(2, len(assessments))
        self.assertEqual(
            ("req:page_source_facts", "req:text_observations"),
            tuple(item.requirement_id for item in assessments),
        )
        self.assertTrue(all(isinstance(item, RequirementAssessment) for item in assessments))

    def test_empty_bundle_marks_required_source_gap_unsupported(self):
        requirement = make_requirement(EvidenceType.PAGE_SOURCE_FACTS)
        bundle = RetrievalBundle(request_id="req:1")
        assessments = self.evaluator.evaluate(make_result(requirement), bundle)
        self.assertEqual(1, len(assessments))
        self.assertEqual(RequirementAssessmentStatus.UNSUPPORTED, assessments[0].status)
        self.assertEqual((ReasonCode.UNSUPPORTED_GENERATION,), assessments[0].reason_codes)
        self.assertEqual((), assessments[0].matched_evidence_ids)

    def test_matching_source_facts_satisfy_source_fact_requirement(self):
        requirement = make_requirement(EvidenceType.PAGE_SOURCE_FACTS)
        evidence = EvidenceItem(
            evidence_id="evidence:1",
            fact_kind=FactKind.SOURCE_FACT,
            scope=AssistantScope(page_id="page:1"),
            value={},
        )
        bundle = RetrievalBundle(
            request_id="req:1",
            source_facts=(evidence,),
        )
        assessments = self.evaluator.evaluate(make_result(requirement), bundle)
        self.assertEqual(RequirementAssessmentStatus.SATISFIED, assessments[0].status)
        self.assertEqual(("evidence:1",), assessments[0].matched_evidence_ids)
        self.assertEqual((ReasonCode.EVIDENCE_COMPLETE,), assessments[0].reason_codes)

    def test_observations_satisfy_observation_requirement_in_correct_bucket(self):
        requirement = make_requirement(EvidenceType.TEXT_OBSERVATIONS)
        observation = EvidenceItem(
            evidence_id="evidence:obs:1",
            fact_kind=FactKind.SEMANTIC_OBSERVATION,
            scope=AssistantScope(page_id="page:1"),
            status="confirmed",
            value={},
        )
        bundle = RetrievalBundle(
            request_id="req:1",
            semantic_observations=(observation,),
        )
        assessments = self.evaluator.evaluate(make_result(requirement), bundle)
        self.assertEqual(RequirementAssessmentStatus.SATISFIED, assessments[0].status)
        self.assertEqual(("evidence:obs:1",), assessments[0].matched_evidence_ids)

    def test_candidate_evidence_does_not_satisfy_observation_requirement(self):
        requirement = make_requirement(EvidenceType.TEXT_OBSERVATIONS)
        candidate = EvidenceItem(
            evidence_id="evidence:cand:1",
            fact_kind=FactKind.CANDIDATE_RELATION,
            scope=AssistantScope(page_id="page:1"),
            value={},
        )
        bundle = RetrievalBundle(
            request_id="req:1",
            candidate_relations=(candidate,),
        )
        assessments = self.evaluator.evaluate(make_result(requirement), bundle)
        self.assertEqual(RequirementAssessmentStatus.FORBIDDEN, assessments[0].status)
        self.assertEqual((), assessments[0].matched_evidence_ids)

    def test_assessment_keeps_rejected_evidence_ids_empty_for_missing_gap(self):
        requirement = make_requirement(EvidenceType.PAGE_SOURCE_FACTS)
        bundle = RetrievalBundle(request_id="req:1")
        assessments = self.evaluator.evaluate(make_result(requirement), bundle)
        self.assertEqual((), assessments[0].rejected_evidence_ids)
        self.assertEqual(RequirementAssessmentStatus.UNSUPPORTED, assessments[0].status)

    def test_module_does_not_import_forbidden_dependencies(self):
        module_path = Path(inspect.getfile(EvidenceSufficiencyEvaluator))
        source = module_path.read_text(encoding="utf-8")
        for forbidden in (
            "tool_facade",
            "neo4j",
            "repository",
            "qwen",
            "qa_http",
            "qa_mcp",
            "semantic_service",
        ):
            self.assertNotIn(forbidden, source)


class EvidenceSufficiencyScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluator = EvidenceSufficiencyEvaluator()

    def test_page_requirement_only_matches_same_page_evidence(self):
        requirement = EvidenceRequirement(
            requirement_id="req:page",
            evidence_type=EvidenceType.PAGE_SOURCE_FACTS,
            target_scope=AssistantScope(page_id="page:1"),
        )
        same_page = EvidenceItem(
            evidence_id="evidence:same",
            fact_kind=FactKind.SOURCE_FACT,
            scope=AssistantScope(page_id="page:1"),
            value={},
        )
        other_page = EvidenceItem(
            evidence_id="evidence:other",
            fact_kind=FactKind.SOURCE_FACT,
            scope=AssistantScope(page_id="page:2"),
            value={},
        )
        bundle = RetrievalBundle(
            request_id="req:1",
            source_facts=(same_page, other_page),
        )
        assessment = self.evaluator.evaluate(make_result(requirement), bundle)[0]
        self.assertEqual(RequirementAssessmentStatus.SATISFIED, assessment.status)
        self.assertEqual(("evidence:same",), assessment.matched_evidence_ids)
        self.assertEqual(("evidence:other",), assessment.rejected_evidence_ids)
        self.assertEqual(
            (ReasonCode.EVIDENCE_COMPLETE, ReasonCode.SCOPE_CONFLICT),
            assessment.reason_codes,
        )

    def test_block_requirement_matches_block_and_belonging_element_evidence(self):
        requirement = EvidenceRequirement(
            requirement_id="req:block",
            evidence_type=EvidenceType.BLOCK_TRACE,
            target_scope=AssistantScope(block_id="block:1"),
        )
        block = EvidenceItem(
            evidence_id="evidence:block",
            fact_kind=FactKind.SOURCE_FACT,
            scope=AssistantScope(page_id="page:1", block_id="block:1"),
            value={},
        )
        belonging_element = EvidenceItem(
            evidence_id="evidence:element-in-block",
            fact_kind=FactKind.SOURCE_FACT,
            scope=AssistantScope(page_id="page:1", block_id="block:1", element_id="element:1"),
            value={},
        )
        other_block = EvidenceItem(
            evidence_id="evidence:other-block",
            fact_kind=FactKind.SOURCE_FACT,
            scope=AssistantScope(page_id="page:1", block_id="block:2"),
            value={},
        )
        bundle = RetrievalBundle(
            request_id="req:1",
            source_facts=(block, belonging_element, other_block),
        )
        assessment = self.evaluator.evaluate(make_result(requirement), bundle)[0]
        self.assertEqual(RequirementAssessmentStatus.SATISFIED, assessment.status)
        self.assertEqual(
            ("evidence:block", "evidence:element-in-block"),
            assessment.matched_evidence_ids,
        )
        self.assertEqual(("evidence:other-block",), assessment.rejected_evidence_ids)

    def test_element_requirement_only_matches_same_element_evidence(self):
        requirement = EvidenceRequirement(
            requirement_id="req:element",
            evidence_type=EvidenceType.TEXT_OBSERVATIONS,
            target_scope=AssistantScope(element_id="element:1"),
        )
        same_element = EvidenceItem(
            evidence_id="evidence:element:1",
            fact_kind=FactKind.SEMANTIC_OBSERVATION,
            scope=AssistantScope(page_id="page:1", element_id="element:1"),
            status="confirmed",
            value={},
        )
        other_element = EvidenceItem(
            evidence_id="evidence:element:2",
            fact_kind=FactKind.SEMANTIC_OBSERVATION,
            scope=AssistantScope(page_id="page:1", element_id="element:2"),
            status="confirmed",
            value={},
        )
        bundle = RetrievalBundle(
            request_id="req:1",
            semantic_observations=(same_element, other_element),
        )
        assessment = self.evaluator.evaluate(make_result(requirement), bundle)[0]
        self.assertEqual(RequirementAssessmentStatus.SATISFIED, assessment.status)
        self.assertEqual(("evidence:element:1",), assessment.matched_evidence_ids)
        self.assertEqual(("evidence:element:2",), assessment.rejected_evidence_ids)

    def test_missing_scope_returns_scope_missing_without_guessing(self):
        requirement = EvidenceRequirement(
            requirement_id="req:noscope",
            evidence_type=EvidenceType.PAGE_SOURCE_FACTS,
            target_scope=AssistantScope(),
        )
        bundle = RetrievalBundle(request_id="req:1")
        assessment = self.evaluator.evaluate(make_result(requirement), bundle)[0]
        self.assertEqual(RequirementAssessmentStatus.MISSING, assessment.status)
        self.assertEqual((ReasonCode.SCOPE_MISSING,), assessment.reason_codes)
        self.assertEqual((), assessment.matched_evidence_ids)
        self.assertEqual((), assessment.rejected_evidence_ids)

    def test_evidence_without_scope_is_rejected(self):
        requirement = EvidenceRequirement(
            requirement_id="req:page2",
            evidence_type=EvidenceType.PAGE_SOURCE_FACTS,
            target_scope=AssistantScope(page_id="page:1"),
        )
        unscoped = EvidenceItem(
            evidence_id="evidence:unscoped",
            fact_kind=FactKind.SOURCE_FACT,
            value={},
        )
        bundle = RetrievalBundle(
            request_id="req:1",
            source_facts=(unscoped,),
        )
        assessment = self.evaluator.evaluate(make_result(requirement), bundle)[0]
        self.assertEqual(RequirementAssessmentStatus.UNSUPPORTED, assessment.status)
        self.assertEqual((), assessment.matched_evidence_ids)
        self.assertEqual(("evidence:unscoped",), assessment.rejected_evidence_ids)
        self.assertIn(ReasonCode.SCOPE_MISSING, assessment.reason_codes)


class EvidenceSufficiencyFactKindTests(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluator = EvidenceSufficiencyEvaluator()

    def test_source_fact_requirement_not_satisfied_by_semantic_evidence(self):
        requirement = EvidenceRequirement(
            requirement_id="req:source",
            evidence_type=EvidenceType.PAGE_SOURCE_FACTS,
            target_scope=AssistantScope(page_id="page:1"),
        )
        observation = EvidenceItem(
            evidence_id="evidence:obs",
            fact_kind=FactKind.SEMANTIC_OBSERVATION,
            scope=AssistantScope(page_id="page:1"),
            value={},
        )
        interpretation = EvidenceItem(
            evidence_id="evidence:interp",
            fact_kind=FactKind.SEMANTIC_INTERPRETATION,
            scope=AssistantScope(page_id="page:1"),
            value={},
        )
        bundle = RetrievalBundle(
            request_id="req:1",
            semantic_observations=(observation,),
            semantic_interpretations=(interpretation,),
        )
        assessment = self.evaluator.evaluate(make_result(requirement), bundle)[0]
        self.assertEqual(RequirementAssessmentStatus.UNSUPPORTED, assessment.status)
        self.assertEqual((), assessment.matched_evidence_ids)

    def test_interpretation_requirement_not_satisfied_by_observation(self):
        requirement = EvidenceRequirement(
            requirement_id="req:interp",
            evidence_type=EvidenceType.STRUCTURED_INTERPRETATIONS,
            target_scope=AssistantScope(page_id="page:1"),
            allow_model_generation=True,
        )
        observation = EvidenceItem(
            evidence_id="evidence:obs",
            fact_kind=FactKind.SEMANTIC_OBSERVATION,
            scope=AssistantScope(page_id="page:1"),
            value={},
        )
        bundle = RetrievalBundle(
            request_id="req:1",
            semantic_observations=(observation,),
        )
        assessment = self.evaluator.evaluate(make_result(requirement), bundle)[0]
        self.assertEqual(RequirementAssessmentStatus.MISSING, assessment.status)
        self.assertEqual((), assessment.matched_evidence_ids)

    def test_block_relations_requirement_not_satisfied_by_candidate_relations(self):
        requirement = EvidenceRequirement(
            requirement_id="req:blockrel",
            evidence_type=EvidenceType.BLOCK_RELATIONS,
            target_scope=AssistantScope(block_id="block:1"),
        )
        candidate = EvidenceItem(
            evidence_id="evidence:cand",
            fact_kind=FactKind.CANDIDATE_RELATION,
            scope=AssistantScope(block_id="block:1"),
            value={},
        )
        bundle = RetrievalBundle(
            request_id="req:1",
            candidate_relations=(candidate,),
        )
        assessment = self.evaluator.evaluate(make_result(requirement), bundle)[0]
        self.assertEqual(RequirementAssessmentStatus.UNSUPPORTED, assessment.status)
        self.assertEqual((), assessment.matched_evidence_ids)

    def test_formal_gate_returns_formal_review_required_when_only_candidate(self):
        requirement = EvidenceRequirement(
            requirement_id="req:match",
            evidence_type=EvidenceType.SECTION_MATCHES,
            target_scope=AssistantScope(cross_section_id="section:1"),
        )
        candidate = EvidenceItem(
            evidence_id="evidence:candidate-match",
            fact_kind=FactKind.CANDIDATE_RELATION,
            scope=AssistantScope(cross_section_id="section:1"),
            status="candidate",
            value={},
        )
        bundle = RetrievalBundle(
            request_id="req:1",
            candidate_relations=(candidate,),
        )
        assessment = self.evaluator.evaluate(make_result(requirement), bundle)[0]
        self.assertEqual(RequirementAssessmentStatus.FORMAL_REVIEW_REQUIRED, assessment.status)
        self.assertEqual(
            (ReasonCode.FORMAL_REVIEW_REQUIRED,),
            assessment.reason_codes,
        )
        self.assertEqual(("evidence:candidate-match",), assessment.matched_evidence_ids)
        self.assertFalse(assessment.allow_model_generation)

    def test_formal_gate_satisfied_when_formal_match_exists(self):
        requirement = EvidenceRequirement(
            requirement_id="req:match2",
            evidence_type=EvidenceType.SECTION_MATCHES,
            target_scope=AssistantScope(cross_section_id="section:1"),
        )
        formal = EvidenceItem(
            evidence_id="evidence:formal-match",
            fact_kind=FactKind.FORMAL_RELATION,
            scope=AssistantScope(cross_section_id="section:1"),
            status="formal",
            value={},
        )
        bundle = RetrievalBundle(
            request_id="req:1",
            formal_relations=(formal,),
        )
        assessment = self.evaluator.evaluate(make_result(requirement), bundle)[0]
        self.assertEqual(RequirementAssessmentStatus.SATISFIED, assessment.status)
        self.assertEqual(("evidence:formal-match",), assessment.matched_evidence_ids)

    def test_matched_candidate_status_does_not_satisfy_formal_requirement(self):
        requirement = EvidenceRequirement(
            requirement_id="req:match3",
            evidence_type=EvidenceType.SECTION_MATCHES,
            target_scope=AssistantScope(cross_section_id="section:1"),
        )
        candidate = EvidenceItem(
            evidence_id="evidence:matched-candidate",
            fact_kind=FactKind.CANDIDATE_RELATION,
            scope=AssistantScope(cross_section_id="section:1"),
            status="matched_candidate",
            value={},
        )
        bundle = RetrievalBundle(
            request_id="req:1",
            candidate_relations=(candidate,),
        )
        assessment = self.evaluator.evaluate(make_result(requirement), bundle)[0]
        self.assertEqual(RequirementAssessmentStatus.FORMAL_REVIEW_REQUIRED, assessment.status)
        self.assertNotEqual(RequirementAssessmentStatus.SATISFIED, assessment.status)

    def test_candidate_requirement_is_satisfied_by_candidate_only(self):
        requirement = EvidenceRequirement(
            requirement_id="req:cand",
            evidence_type=EvidenceType.CANDIDATE_RELATIONS,
            target_scope=AssistantScope(page_id="page:1"),
        )
        candidate = EvidenceItem(
            evidence_id="evidence:cand:1",
            fact_kind=FactKind.CANDIDATE_RELATION,
            scope=AssistantScope(page_id="page:1"),
            status="candidate",
            value={},
        )
        bundle = RetrievalBundle(
            request_id="req:1",
            candidate_relations=(candidate,),
        )
        assessment = self.evaluator.evaluate(make_result(requirement), bundle)[0]
        self.assertEqual(RequirementAssessmentStatus.SATISFIED, assessment.status)
        self.assertEqual(("evidence:cand:1",), assessment.matched_evidence_ids)


class EvidenceSufficiencyStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluator = EvidenceSufficiencyEvaluator()

    def observation(self, evidence_id: str, status: str) -> EvidenceItem:
        return EvidenceItem(
            evidence_id=evidence_id,
            fact_kind=FactKind.SEMANTIC_OBSERVATION,
            scope=AssistantScope(page_id="page:1"),
            status=status,
            value={},
        )

    def assess_observation(self, *observations: EvidenceItem):
        requirement = EvidenceRequirement(
            requirement_id="req:obs",
            evidence_type=EvidenceType.TEXT_OBSERVATIONS,
            target_scope=AssistantScope(page_id="page:1"),
            minimum_status="confirmed",
            allow_model_generation=True,
        )
        bundle = RetrievalBundle(
            request_id="req:1",
            semantic_observations=observations,
        )
        return self.evaluator.evaluate(make_result(requirement), bundle)[0]

    def test_confirmed_observation_satisfies_requirement(self):
        assessment = self.assess_observation(self.observation("evidence:ok", "confirmed"))
        self.assertEqual(RequirementAssessmentStatus.SATISFIED, assessment.status)
        self.assertEqual(("evidence:ok",), assessment.matched_evidence_ids)
        self.assertEqual((ReasonCode.EVIDENCE_COMPLETE,), assessment.reason_codes)

    def test_partial_observation_is_status_insufficient(self):
        assessment = self.assess_observation(self.observation("evidence:partial", "partial"))
        self.assertEqual(RequirementAssessmentStatus.MISSING, assessment.status)
        self.assertEqual(("evidence:partial",), assessment.rejected_evidence_ids)
        self.assertIn(ReasonCode.STATUS_INSUFFICIENT, assessment.reason_codes)

    def test_ambiguous_observation_is_status_insufficient(self):
        assessment = self.assess_observation(self.observation("evidence:ambiguous", "ambiguous"))
        self.assertEqual(RequirementAssessmentStatus.MISSING, assessment.status)
        self.assertEqual(("evidence:ambiguous",), assessment.rejected_evidence_ids)
        self.assertIn(ReasonCode.STATUS_INSUFFICIENT, assessment.reason_codes)

    def test_stale_observation_is_rejected_with_evidence_stale(self):
        assessment = self.assess_observation(self.observation("evidence:stale", "stale"))
        self.assertEqual(RequirementAssessmentStatus.MISSING, assessment.status)
        self.assertEqual(("evidence:stale",), assessment.rejected_evidence_ids)
        self.assertIn(ReasonCode.EVIDENCE_STALE, assessment.reason_codes)

    def test_rejected_observation_is_insufficient(self):
        assessment = self.assess_observation(self.observation("evidence:rejected", "rejected"))
        self.assertEqual(RequirementAssessmentStatus.MISSING, assessment.status)
        self.assertEqual(("evidence:rejected",), assessment.rejected_evidence_ids)
        self.assertIn(ReasonCode.STATUS_INSUFFICIENT, assessment.reason_codes)

    def test_recognition_failed_observation_is_insufficient(self):
        assessment = self.assess_observation(
            self.observation("evidence:failed", "recognition_failed")
        )
        self.assertEqual(RequirementAssessmentStatus.MISSING, assessment.status)
        self.assertEqual(("evidence:failed",), assessment.rejected_evidence_ids)
        self.assertIn(ReasonCode.STATUS_INSUFFICIENT, assessment.reason_codes)

    def test_matched_candidate_status_is_not_accepted_for_observation(self):
        assessment = self.assess_observation(
            self.observation("evidence:matched", "matched_candidate")
        )
        self.assertEqual(RequirementAssessmentStatus.MISSING, assessment.status)
        self.assertEqual((), assessment.matched_evidence_ids)
        self.assertIn(ReasonCode.STATUS_INSUFFICIENT, assessment.reason_codes)

    def test_minimum_status_is_interpreted_per_evidence_kind(self):
        requirement = EvidenceRequirement(
            requirement_id="req:interp",
            evidence_type=EvidenceType.STRUCTURED_INTERPRETATIONS,
            target_scope=AssistantScope(page_id="page:1"),
            minimum_status="interpreted",
            allow_model_generation=True,
        )
        partial = EvidenceItem(
            evidence_id="evidence:interp-partial",
            fact_kind=FactKind.SEMANTIC_INTERPRETATION,
            scope=AssistantScope(page_id="page:1"),
            status="partial",
            value={},
        )
        bundle = RetrievalBundle(
            request_id="req:1",
            semantic_interpretations=(partial,),
        )
        assessment = self.evaluator.evaluate(make_result(requirement), bundle)[0]
        self.assertEqual(RequirementAssessmentStatus.MISSING, assessment.status)
        self.assertEqual(("evidence:interp-partial",), assessment.rejected_evidence_ids)
        self.assertIn(ReasonCode.STATUS_INSUFFICIENT, assessment.reason_codes)

    def test_conflicting_candidate_statuses_mark_assessment_conflicting(self):
        requirement = EvidenceRequirement(
            requirement_id="req:candconflict",
            evidence_type=EvidenceType.CANDIDATE_RELATIONS,
            target_scope=AssistantScope(page_id="page:1", block_id="block:1"),
        )
        first = EvidenceItem(
            evidence_id="evidence:cand:a",
            fact_kind=FactKind.CANDIDATE_RELATION,
            scope=AssistantScope(page_id="page:1", block_id="block:1"),
            status="candidate",
            value={"relation_type": "caption"},
        )
        second = EvidenceItem(
            evidence_id="evidence:cand:b",
            fact_kind=FactKind.CANDIDATE_RELATION,
            scope=AssistantScope(page_id="page:1", block_id="block:1"),
            status="matched_candidate",
            value={"relation_type": "caption"},
        )
        bundle = RetrievalBundle(
            request_id="req:1",
            candidate_relations=(first, second),
        )
        assessment = self.evaluator.evaluate(make_result(requirement), bundle)[0]
        self.assertEqual(RequirementAssessmentStatus.CONFLICTING, assessment.status)
        self.assertEqual((ReasonCode.EVIDENCE_CONFLICT,), assessment.reason_codes)
        self.assertEqual((), assessment.matched_evidence_ids)
        self.assertEqual(
            ("evidence:cand:a", "evidence:cand:b"),
            assessment.rejected_evidence_ids,
        )

    def test_duplicate_same_status_does_not_conflict(self):
        requirement = EvidenceRequirement(
            requirement_id="req:canddup",
            evidence_type=EvidenceType.CANDIDATE_RELATIONS,
            target_scope=AssistantScope(page_id="page:1", block_id="block:1"),
        )
        first = EvidenceItem(
            evidence_id="evidence:dup:a",
            fact_kind=FactKind.CANDIDATE_RELATION,
            scope=AssistantScope(page_id="page:1", block_id="block:1"),
            status="candidate",
            value={},
        )
        second = EvidenceItem(
            evidence_id="evidence:dup:b",
            fact_kind=FactKind.CANDIDATE_RELATION,
            scope=AssistantScope(page_id="page:1", block_id="block:1"),
            status="candidate",
            value={},
        )
        bundle = RetrievalBundle(
            request_id="req:1",
            candidate_relations=(first, second),
        )
        assessment = self.evaluator.evaluate(make_result(requirement), bundle)[0]
        self.assertEqual(RequirementAssessmentStatus.SATISFIED, assessment.status)
        self.assertEqual(("evidence:dup:a", "evidence:dup:b"), assessment.matched_evidence_ids)


class EvidenceSufficiencyGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluator = EvidenceSufficiencyEvaluator()

    def assess(self, requirement: EvidenceRequirement):
        return self.evaluator.evaluate(
            make_result(requirement),
            RetrievalBundle(request_id="req:1"),
        )[0]

    def test_generatable_observation_gap_marks_assessment_generatable(self):
        requirement = EvidenceRequirement(
            requirement_id="req:obsgen",
            evidence_type=EvidenceType.TEXT_OBSERVATIONS,
            target_scope=AssistantScope(page_id="page:1"),
            allow_model_generation=True,
        )
        assessment = self.assess(requirement)
        self.assertEqual(RequirementAssessmentStatus.MISSING, assessment.status)
        self.assertEqual((ReasonCode.OBSERVATION_MISSING,), assessment.reason_codes)
        self.assertTrue(assessment.allow_model_generation)

    def test_generatable_interpretation_gap_marks_assessment_generatable(self):
        requirement = EvidenceRequirement(
            requirement_id="req:interpgen",
            evidence_type=EvidenceType.STRUCTURED_INTERPRETATIONS,
            target_scope=AssistantScope(page_id="page:1"),
            allow_model_generation=True,
        )
        assessment = self.assess(requirement)
        self.assertEqual(RequirementAssessmentStatus.MISSING, assessment.status)
        self.assertEqual((ReasonCode.INTERPRETATION_MISSING,), assessment.reason_codes)
        self.assertTrue(assessment.allow_model_generation)

    def test_observation_gap_without_permission_is_recognition_forbidden(self):
        requirement = EvidenceRequirement(
            requirement_id="req:obsforbidden",
            evidence_type=EvidenceType.TEXT_OBSERVATIONS,
            target_scope=AssistantScope(page_id="page:1"),
            allow_model_generation=False,
        )
        assessment = self.assess(requirement)
        self.assertEqual(RequirementAssessmentStatus.FORBIDDEN, assessment.status)
        self.assertEqual((ReasonCode.RECOGNITION_FORBIDDEN,), assessment.reason_codes)
        self.assertFalse(assessment.allow_model_generation)

    def test_source_fact_gap_is_unsupported_generation(self):
        requirement = EvidenceRequirement(
            requirement_id="req:sourceunsupported",
            evidence_type=EvidenceType.PAGE_SOURCE_FACTS,
            target_scope=AssistantScope(page_id="page:1"),
        )
        assessment = self.assess(requirement)
        self.assertEqual(RequirementAssessmentStatus.UNSUPPORTED, assessment.status)
        self.assertEqual((ReasonCode.UNSUPPORTED_GENERATION,), assessment.reason_codes)
        self.assertFalse(assessment.allow_model_generation)

    def test_section_match_gap_is_unsupported_generation(self):
        requirement = EvidenceRequirement(
            requirement_id="req:matchunsupported",
            evidence_type=EvidenceType.SECTION_MATCHES,
            target_scope=AssistantScope(cross_section_id="section:1"),
        )
        assessment = self.assess(requirement)
        self.assertEqual(RequirementAssessmentStatus.UNSUPPORTED, assessment.status)
        self.assertEqual((ReasonCode.UNSUPPORTED_GENERATION,), assessment.reason_codes)

    def test_optional_missing_gap_stays_missing(self):
        requirement = EvidenceRequirement(
            requirement_id="req:optional",
            evidence_type=EvidenceType.PAGE_SOURCE_FACTS,
            target_scope=AssistantScope(page_id="page:1"),
            required=False,
        )
        assessment = self.assess(requirement)
        self.assertEqual(RequirementAssessmentStatus.MISSING, assessment.status)
        self.assertEqual((ReasonCode.EVIDENCE_MISSING,), assessment.reason_codes)


if __name__ == "__main__":
    unittest.main()
