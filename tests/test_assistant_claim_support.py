"""Tests for claim support evaluation (Task 28-30)."""

import unittest

from drawing_graph.assistant_claim_support import (
    ClaimSupportEvaluator,
    RequirementCapabilityMapper,
)
from drawing_graph.assistant_evidence_fusion_models import (
    ClaimCapability,
    ClaimSupportStatus,
    ConflictRecord,
    ConflictSeverity,
    ConflictType,
    FusionEvidence,
    FusionMetadata,
)
from drawing_graph.assistant_models import (
    AssistantScope,
    EvidenceItem,
    EvidenceRequirement,
    EvidenceType,
    FreshnessRequirement,
    ReasonCode,
)


def requirement(evidence_type, **overrides):
    values = dict(
        requirement_id="req:1",
        evidence_type=evidence_type,
        target_scope=AssistantScope(page_id="page:1"),
    )
    values.update(overrides)
    return EvidenceRequirement(**values)


class RequirementCapabilityMappingTests(unittest.TestCase):
    def test_identity_and_location_mapping(self):
        mapper = RequirementCapabilityMapper()
        self.assertEqual(
            ClaimCapability.IDENTITY_AND_LOCATION,
            mapper.map(requirement(EvidenceType.PAGE_SOURCE_FACTS)),
        )
        self.assertEqual(
            ClaimCapability.IDENTITY_AND_LOCATION,
            mapper.map(requirement(EvidenceType.PROJECT_DRAWING_SETS)),
        )

    def test_relation_and_context_mapping(self):
        mapper = RequirementCapabilityMapper()
        self.assertEqual(
            ClaimCapability.RULE_DERIVED_CONTEXT,
            mapper.map(requirement(EvidenceType.BLOCK_RELATIONS)),
        )
        self.assertEqual(
            ClaimCapability.CONFIRMED_RELATION,
            mapper.map(requirement(EvidenceType.SECTION_MATCHES)),
        )
        self.assertEqual(
            ClaimCapability.POSSIBLE_RELATION,
            mapper.map(requirement(EvidenceType.CANDIDATE_RELATIONS)),
        )

    def test_semantic_mapping(self):
        mapper = RequirementCapabilityMapper()
        self.assertEqual(
            ClaimCapability.OBSERVED_TEXT_OR_SYMBOL,
            mapper.map(requirement(EvidenceType.TEXT_OBSERVATIONS)),
        )
        self.assertEqual(
            ClaimCapability.SEMANTIC_MEANING,
            mapper.map(requirement(EvidenceType.STRUCTURED_INTERPRETATIONS)),
        )

    def test_unknown_evidence_type_is_unsupported(self):
        mapper = RequirementCapabilityMapper()
        self.assertIsNone(mapper.map(requirement(EvidenceType.SEMANTIC_PAYLOAD)))

    def test_required_optional_and_freshness_are_preserved_on_requirement(self):
        req = requirement(
            EvidenceType.TEXT_OBSERVATIONS,
            required=False,
            minimum_status="confirmed",
            freshness_requirement=FreshnessRequirement(require_current_image=True),
            allow_model_generation=True,
        )
        self.assertFalse(req.required)
        self.assertEqual("confirmed", req.minimum_status)
        self.assertTrue(req.freshness_requirement.require_current_image)
        mapper = RequirementCapabilityMapper()
        self.assertEqual(ClaimCapability.OBSERVED_TEXT_OR_SYMBOL, mapper.map(req))

    def test_mapping_does_not_read_question_text(self):
        mapper = RequirementCapabilityMapper()
        req = requirement(EvidenceType.CANDIDATE_RELATIONS)
        self.assertEqual(ClaimCapability.POSSIBLE_RELATION, mapper.map(req))


def make_fusion(
    evidence_id,
    fact_kind="semantic_observation",
    page_id="page:1",
    element_id="element:1",
    capability=ClaimCapability.OBSERVED_TEXT_OR_SYMBOL,
    is_current=True,
    status="confirmed",
    metadata=None,
    confidence=None,
):
    scope_kwargs = {"page_id": page_id}
    if element_id is not None:
        scope_kwargs["element_id"] = element_id
    return FusionEvidence(
        item=EvidenceItem(
            evidence_id=evidence_id,
            fact_kind=fact_kind,
            scope=AssistantScope(**scope_kwargs),
            status=status,
            value={},
            confidence=confidence,
            evidence_metadata=metadata if metadata is not None else {},
        ),
        metadata=FusionMetadata(
            claim_capabilities=(capability,),
            is_current_for_request=is_current,
        ),
    )


class ClaimSupportGateTests(unittest.TestCase):
    def test_current_observation_supports_observed_text(self):
        evaluator = ClaimSupportEvaluator()
        req = requirement(EvidenceType.TEXT_OBSERVATIONS, minimum_status="confirmed")
        assessment = evaluator.evaluate(
            (req,),
            (make_fusion("evidence:1"),),
        )[0]
        self.assertEqual(ClaimSupportStatus.SUPPORTED, assessment.status)
        self.assertEqual(("evidence:1",), assessment.supporting_evidence_ids)

    def test_stale_only_observation_gets_stale_only(self):
        evaluator = ClaimSupportEvaluator()
        req = requirement(EvidenceType.TEXT_OBSERVATIONS)
        assessment = evaluator.evaluate(
            (req,),
            (make_fusion("evidence:1", is_current=False),),
        )[0]
        self.assertEqual(ClaimSupportStatus.STALE_ONLY, assessment.status)
        self.assertEqual(("evidence:1",), assessment.qualifying_evidence_ids)
        self.assertIn(ReasonCode.EVIDENCE_STALE, assessment.reason_codes)

    def test_scope_mismatch_is_rejected(self):
        evaluator = ClaimSupportEvaluator()
        req = requirement(
            EvidenceType.TEXT_OBSERVATIONS,
            target_scope=AssistantScope(page_id="page:1", element_id="element:1"),
        )
        assessment = evaluator.evaluate(
            (req,),
            (make_fusion("evidence:1", element_id="element:other"),),
        )[0]
        self.assertEqual(ClaimSupportStatus.MISSING, assessment.status)
        self.assertEqual(("evidence:1",), assessment.rejected_evidence_ids)
        self.assertIn(ReasonCode.SCOPE_CONFLICT, assessment.reason_codes)

    def test_wrong_capability_is_rejected(self):
        evaluator = ClaimSupportEvaluator()
        req = requirement(EvidenceType.TEXT_OBSERVATIONS)
        assessment = evaluator.evaluate(
            (req,),
            (make_fusion("evidence:1", fact_kind="candidate_relation", capability=ClaimCapability.POSSIBLE_RELATION),),
        )[0]
        self.assertIn("evidence:1", assessment.rejected_evidence_ids)
        self.assertIn(ReasonCode.EVIDENCE_KIND_MISMATCH, assessment.reason_codes)

    def test_status_insufficient_is_rejected(self):
        evaluator = ClaimSupportEvaluator()
        req = requirement(EvidenceType.TEXT_OBSERVATIONS, minimum_status="confirmed")
        assessment = evaluator.evaluate(
            (req,),
            (make_fusion("evidence:1", status="partial"),),
        )[0]
        self.assertIn("evidence:1", assessment.rejected_evidence_ids)
        self.assertIn(ReasonCode.STATUS_INSUFFICIENT, assessment.reason_codes)

    def test_interpretation_requires_observation_support_chain(self):
        evaluator = ClaimSupportEvaluator()
        req = requirement(EvidenceType.STRUCTURED_INTERPRETATIONS)
        interp = make_fusion(
            "interp:1",
            fact_kind="semantic_interpretation",
            capability=ClaimCapability.SEMANTIC_MEANING,
            metadata={"supported_by_observation_ids": ()},
        )
        assessment = evaluator.evaluate((req,), (interp,))[0]
        self.assertIn("interp:1", assessment.rejected_evidence_ids)
        self.assertIn(ReasonCode.OBSERVATION_MISSING, assessment.reason_codes)

    def test_rejected_evidence_ids_and_reason_codes_are_preserved(self):
        evaluator = ClaimSupportEvaluator()
        req = requirement(
            EvidenceType.TEXT_OBSERVATIONS,
            target_scope=AssistantScope(page_id="page:1", element_id="element:1"),
        )
        assessment = evaluator.evaluate(
            (req,),
            (make_fusion("evidence:rejected", element_id="element:other"),),
        )[0]
        self.assertEqual(("evidence:rejected",), assessment.rejected_evidence_ids)
        self.assertIsInstance(assessment.reason_codes, tuple)


class ClaimConflictFormalGateTests(unittest.TestCase):
    def test_blocking_conflict_marks_claim_conflicting(self):
        evaluator = ClaimSupportEvaluator()
        req = requirement(EvidenceType.TEXT_OBSERVATIONS)
        evidence = make_fusion("evidence:1")
        conflict = ConflictRecord(
            conflict_id="conflict:1",
            comparison_key="comparison:1",
            conflict_type=ConflictType.HARD_CONFLICT,
            severity=ConflictSeverity.BLOCKING,
            evidence_ids=("evidence:1", "evidence:2"),
        )
        assessment = evaluator.evaluate((req,), (evidence,), (conflict,))[0]
        self.assertEqual(ClaimSupportStatus.CONFLICTING, assessment.status)
        self.assertEqual(("conflict:1",), assessment.conflict_ids)

    def test_formal_claim_with_only_candidate_is_formal_review_required(self):
        evaluator = ClaimSupportEvaluator()
        req = requirement(EvidenceType.SECTION_MATCHES, target_scope=AssistantScope(page_id="page:1"))
        candidate = make_fusion(
            "candidate:1",
            fact_kind="candidate_relation",
            element_id=None,
            capability=ClaimCapability.POSSIBLE_RELATION,
        )
        assessment = evaluator.evaluate((req,), (candidate,))[0]
        self.assertEqual(ClaimSupportStatus.FORMAL_REVIEW_REQUIRED, assessment.status)

    def test_formal_claim_with_formal_evidence_is_supported(self):
        evaluator = ClaimSupportEvaluator()
        req = requirement(EvidenceType.SECTION_MATCHES, target_scope=AssistantScope(page_id="page:1"))
        formal = make_fusion(
            "formal:1",
            fact_kind="formal_relation",
            element_id=None,
            capability=ClaimCapability.CONFIRMED_RELATION,
            status="formal",
        )
        assessment = evaluator.evaluate((req,), (formal,))[0]
        self.assertEqual(ClaimSupportStatus.SUPPORTED, assessment.status)

    def test_low_confidence_produces_supported_with_qualifier(self):
        evaluator = ClaimSupportEvaluator()
        req = requirement(EvidenceType.TEXT_OBSERVATIONS)
        low = make_fusion("evidence:1", confidence=0.3)
        assessment = evaluator.evaluate((req,), (low,))[0]
        self.assertEqual(ClaimSupportStatus.SUPPORTED_WITH_QUALIFIER, assessment.status)
        self.assertIn("low_confidence", assessment.qualifiers)

    def test_non_blocking_ambiguity_produces_qualifier(self):
        evaluator = ClaimSupportEvaluator()
        req = requirement(EvidenceType.TEXT_OBSERVATIONS)
        evidence = make_fusion("evidence:1")
        conflict = ConflictRecord(
            conflict_id="conflict:1",
            comparison_key="comparison:1",
            conflict_type=ConflictType.PEER_CONFLICT,
            severity=ConflictSeverity.WARNING,
            evidence_ids=("evidence:1", "evidence:2"),
        )
        assessment = evaluator.evaluate((req,), (evidence,), (conflict,))[0]
        self.assertEqual(ClaimSupportStatus.SUPPORTED_WITH_QUALIFIER, assessment.status)
        self.assertIn("ambiguous", assessment.qualifiers)

    def test_supporting_evidence_ids_are_sorted(self):
        evaluator = ClaimSupportEvaluator()
        req = requirement(EvidenceType.TEXT_OBSERVATIONS)
        evidence = (
            make_fusion("evidence:z"),
            make_fusion("evidence:a"),
        )
        assessment = evaluator.evaluate((req,), evidence)[0]
        self.assertEqual(("evidence:a", "evidence:z"), assessment.supporting_evidence_ids)


class ClaimSupportSubrequestTests(unittest.TestCase):
    def test_assessment_carries_projected_subrequest_id(self):
        evaluator = ClaimSupportEvaluator()
        req = requirement(EvidenceType.TEXT_OBSERVATIONS)
        assessment = evaluator.evaluate(
            (req,),
            (make_fusion("evidence:1"),),
            subrequest_id="sub:1",
        )[0]
        self.assertEqual("sub:1", assessment.subrequest_id)

    def test_top_level_assessment_keeps_subrequest_id_none(self):
        evaluator = ClaimSupportEvaluator()
        req = requirement(EvidenceType.TEXT_OBSERVATIONS)
        assessment = evaluator.evaluate((req,), (make_fusion("evidence:1"),))[0]
        self.assertIsNone(assessment.subrequest_id)

    def test_unsupported_assessment_carries_subrequest_id(self):
        evaluator = ClaimSupportEvaluator()
        req = requirement(EvidenceType.SEMANTIC_PAYLOAD)
        assessment = evaluator.evaluate((req,), (), subrequest_id="sub:2")[0]
        self.assertEqual("sub:2", assessment.subrequest_id)
        self.assertEqual(ClaimSupportStatus.UNSUPPORTED, assessment.status)

    def test_subrequest_id_does_not_change_support_logic(self):
        evaluator = ClaimSupportEvaluator()
        req = requirement(EvidenceType.TEXT_OBSERVATIONS, minimum_status="confirmed")
        assessment = evaluator.evaluate(
            (req,),
            (make_fusion("evidence:1"),),
            subrequest_id="sub:3",
        )[0]
        self.assertEqual(ClaimSupportStatus.SUPPORTED, assessment.status)
        self.assertEqual(("evidence:1",), assessment.supporting_evidence_ids)
        self.assertEqual("sub:3", assessment.subrequest_id)


if __name__ == "__main__":
    unittest.main()
