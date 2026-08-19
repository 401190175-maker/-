"""Tests for the deterministic claim builder."""

import unittest

from drawing_graph.assistant_claim_builder import ClaimBuilder, build_claim_id
from drawing_graph.assistant_evidence_fusion_models import (
    ClaimCapability,
    ClaimSupportAssessment,
    ClaimSupportStatus,
    ConflictRecord,
    ConflictSeverity,
    ConflictType,
    EvidenceBundle,
    FusionEvidence,
    FusionMetadata,
)
from drawing_graph.assistant_models import (
    AssistantScope,
    ClaimStatus,
    EvidenceItem,
    EvidenceRequirement,
    EvidenceType,
    FactKind,
    QuestionUnderstandingResult,
    ReasonCode,
)


def make_requirement(
    requirement_id="req:1",
    evidence_type=EvidenceType.TEXT_OBSERVATIONS,
    scope=None,
):
    return EvidenceRequirement(
        requirement_id=requirement_id,
        evidence_type=evidence_type,
        target_scope=scope or AssistantScope(page_id="page:1"),
    )


def make_fusion(evidence_id, fact_kind=FactKind.SEMANTIC_OBSERVATION, page_id="page:1", confidence=None):
    return FusionEvidence(
        item=EvidenceItem(
            evidence_id=evidence_id,
            fact_kind=fact_kind,
            scope=AssistantScope(page_id=page_id),
            value={},
            confidence=confidence,
        ),
        metadata=FusionMetadata(),
    )


def make_assessment(
    requirement_id="req:1",
    status=ClaimSupportStatus.SUPPORTED,
    supporting=(),
    qualifying=(),
    confidence=None,
    capability=ClaimCapability.OBSERVED_TEXT_OR_SYMBOL,
    conflict_ids=(),
    qualifiers=(),
):
    return ClaimSupportAssessment(
        requirement_id=requirement_id,
        claim_capability=capability,
        status=status,
        supporting_evidence_ids=supporting,
        qualifying_evidence_ids=qualifying,
        conflict_ids=conflict_ids,
        qualifiers=qualifiers,
        confidence=confidence,
    )


def make_question_result(request_id="req:1", requirements=()):
    return QuestionUnderstandingResult(
        request_id=request_id,
        question_type="page_summary",
        required_evidence=requirements,
    )


def make_bundle(assessments=(), evidence=(), conflicts=()):
    return EvidenceBundle(
        request_id="req:1",
        claim_support=assessments,
        accepted_evidence=evidence,
        conflicts=conflicts,
    )


class StableClaimIdTests(unittest.TestCase):
    def _base_kwargs(self):
        return dict(
            request_id="req:1",
            subrequest_id="sub:1",
            capability=ClaimCapability.OBSERVED_TEXT_OR_SYMBOL,
            scope=AssistantScope(page_id="page:1"),
            evidence_ids=("evidence:1", "evidence:2"),
            status=ClaimStatus.SUPPORTED,
        )

    def test_same_semantic_input_produces_same_id(self):
        first = build_claim_id(**self._base_kwargs())
        second = build_claim_id(**self._base_kwargs())
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("claim:"))

    def test_evidence_input_order_does_not_affect_id(self):
        base = self._base_kwargs()
        forward = build_claim_id(**base)
        reversed_kwargs = dict(base, evidence_ids=("evidence:2", "evidence:1"))
        reversed_id = build_claim_id(**reversed_kwargs)
        self.assertEqual(forward, reversed_id)

    def test_key_field_change_changes_id(self):
        base = self._base_kwargs()
        original = build_claim_id(**base)
        self.assertNotEqual(original, build_claim_id(**dict(base, request_id="req:2")))
        self.assertNotEqual(original, build_claim_id(**dict(base, subrequest_id="sub:2")))
        self.assertNotEqual(
            original,
            build_claim_id(**dict(base, capability=ClaimCapability.SEMANTIC_MEANING)),
        )
        self.assertNotEqual(
            original,
            build_claim_id(**dict(base, scope=AssistantScope(page_id="page:2"))),
        )
        self.assertNotEqual(
            original,
            build_claim_id(**dict(base, evidence_ids=("evidence:3",))),
        )
        self.assertNotEqual(original, build_claim_id(**dict(base, status=ClaimStatus.QUALIFIED)))

    def test_id_contains_no_timestamp_or_randomness(self):
        ids = {build_claim_id(**self._base_kwargs()) for _ in range(5)}
        self.assertEqual(1, len(ids))

    def test_scope_with_same_semantics_same_id(self):
        base = self._base_kwargs()
        first = build_claim_id(**base)
        scope_a = AssistantScope(project_id="project:1", page_id="page:1")
        scope_b = AssistantScope(page_id="page:1", project_id="project:1")
        self.assertEqual(
            build_claim_id(**dict(base, scope=scope_a)),
            build_claim_id(**dict(base, scope=scope_b)),
        )


class SupportedClaimTests(unittest.TestCase):
    def test_supported_assessment_builds_claim(self):
        builder = ClaimBuilder()
        requirement = make_requirement("req:1")
        evidence = (make_fusion("evidence:1", confidence=0.9),)
        assessment = make_assessment(
            "req:1",
            status=ClaimSupportStatus.SUPPORTED,
            supporting=("evidence:1",),
            confidence=0.9,
        )
        claims = builder.build(
            make_question_result(requirements=(requirement,)),
            make_bundle(assessments=(assessment,), evidence=evidence),
        )
        self.assertEqual(1, len(claims))
        claim = claims[0]
        self.assertTrue(claim.claim_id.startswith("claim:"))
        self.assertEqual("supported", claim.status)
        self.assertEqual("observed_text_or_symbol", claim.claim_type)
        self.assertEqual(("evidence:1",), claim.evidence_ids)
        self.assertEqual((FactKind.SEMANTIC_OBSERVATION,), claim.fact_kinds)
        self.assertEqual("page:1", claim.scope.page_id)
        self.assertEqual(0.9, claim.confidence)
        self.assertTrue(claim.statement)

    def test_supported_statement_is_deterministic(self):
        builder = ClaimBuilder()
        requirement = make_requirement("req:1")
        evidence = (make_fusion("evidence:1"),)
        assessment = make_assessment("req:1", supporting=("evidence:1",))
        first = builder.build(
            make_question_result(requirements=(requirement,)),
            make_bundle(assessments=(assessment,), evidence=evidence),
        )[0]
        second = builder.build(
            make_question_result(requirements=(requirement,)),
            make_bundle(assessments=(assessment,), evidence=evidence),
        )[0]
        self.assertEqual(first.statement, second.statement)
        self.assertEqual(first.claim_id, second.claim_id)

    def test_no_supporting_evidence_produces_no_claim(self):
        builder = ClaimBuilder()
        requirement = make_requirement("req:1")
        assessment = make_assessment("req:1", status=ClaimSupportStatus.SUPPORTED)
        claims = builder.build(
            make_question_result(requirements=(requirement,)),
            make_bundle(assessments=(assessment,), evidence=()),
        )
        self.assertEqual((), claims)

    def test_fact_kinds_follow_stable_hierarchy_order(self):
        builder = ClaimBuilder()
        requirement = make_requirement("req:1")
        evidence = (
            make_fusion("evidence:1", fact_kind=FactKind.SEMANTIC_OBSERVATION),
            make_fusion("evidence:2", fact_kind=FactKind.SOURCE_FACT),
        )
        assessment = make_assessment("req:1", supporting=("evidence:1", "evidence:2"))
        claims = builder.build(
            make_question_result(requirements=(requirement,)),
            make_bundle(assessments=(assessment,), evidence=evidence),
        )
        self.assertEqual(
            (FactKind.SOURCE_FACT, FactKind.SEMANTIC_OBSERVATION),
            claims[0].fact_kinds,
        )


class QualifiedClaimTests(unittest.TestCase):
    def test_supported_with_qualifier_builds_qualified_claim(self):
        builder = ClaimBuilder()
        requirement = make_requirement("req:1")
        evidence = (make_fusion("evidence:1", confidence=0.3),)
        assessment = make_assessment(
            "req:1",
            status=ClaimSupportStatus.SUPPORTED_WITH_QUALIFIER,
            supporting=("evidence:1",),
            confidence=0.3,
            qualifiers=("low_confidence", "partial"),
        )
        claims = builder.build(
            make_question_result(requirements=(requirement,)),
            make_bundle(assessments=(assessment,), evidence=evidence),
        )
        self.assertEqual(1, len(claims))
        claim = claims[0]
        self.assertEqual("qualified", claim.status)
        self.assertEqual(("low_confidence", "partial"), claim.qualifiers)

    def test_qualifiers_are_sorted(self):
        builder = ClaimBuilder()
        requirement = make_requirement("req:1")
        evidence = (make_fusion("evidence:1"),)
        assessment = make_assessment(
            "req:1",
            status=ClaimSupportStatus.SUPPORTED_WITH_QUALIFIER,
            supporting=("evidence:1",),
            qualifiers=("partial", "ambiguous"),
        )
        claim = builder.build(
            make_question_result(requirements=(requirement,)),
            make_bundle(assessments=(assessment,), evidence=evidence),
        )[0]
        self.assertEqual(("ambiguous", "partial"), claim.qualifiers)

    def test_qualified_statement_is_not_unconditional(self):
        builder = ClaimBuilder()
        requirement = make_requirement("req:1")
        evidence = (make_fusion("evidence:1"),)
        assessment = make_assessment(
            "req:1",
            status=ClaimSupportStatus.SUPPORTED_WITH_QUALIFIER,
            supporting=("evidence:1",),
        )
        claim = builder.build(
            make_question_result(requirements=(requirement,)),
            make_bundle(assessments=(assessment,), evidence=evidence),
        )[0]
        self.assertIn("限定", claim.statement)
        self.assertNotEqual("图中识别到的文字与符号已确认", claim.statement)


class ConflictingClaimTests(unittest.TestCase):
    def test_conflicting_assessment_builds_conflict_claim(self):
        builder = ClaimBuilder()
        requirement = make_requirement("req:1")
        evidence = (
            make_fusion("evidence:1", confidence=0.9),
            make_fusion("evidence:2", confidence=0.8),
        )
        conflict = ConflictRecord(
            conflict_id="conflict:1",
            conflict_type=ConflictType.HARD_CONFLICT,
            severity=ConflictSeverity.BLOCKING,
            evidence_ids=("evidence:1", "evidence:2"),
        )
        assessment = make_assessment(
            "req:1",
            status=ClaimSupportStatus.CONFLICTING,
            conflict_ids=("conflict:1",),
        )
        claims = builder.build(
            make_question_result(requirements=(requirement,)),
            make_bundle(assessments=(assessment,), evidence=evidence, conflicts=(conflict,)),
        )
        self.assertEqual(1, len(claims))
        claim = claims[0]
        self.assertEqual("conflicting", claim.status)
        self.assertEqual(("evidence:1", "evidence:2"), claim.evidence_ids)
        self.assertIn("冲突", claim.statement)

    def test_conflicting_claim_makes_no_formal_conclusion(self):
        builder = ClaimBuilder()
        requirement = make_requirement("req:1")
        evidence = (make_fusion("evidence:1"),)
        conflict = ConflictRecord(
            conflict_id="conflict:2",
            conflict_type=ConflictType.HARD_CONFLICT,
            severity=ConflictSeverity.BLOCKING,
            evidence_ids=("evidence:1",),
        )
        assessment = make_assessment(
            "req:1",
            status=ClaimSupportStatus.CONFLICTING,
            conflict_ids=("conflict:2",),
        )
        claim = builder.build(
            make_question_result(requirements=(requirement,)),
            make_bundle(assessments=(assessment,), evidence=evidence, conflicts=(conflict,)),
        )[0]
        self.assertNotIn("已确认", claim.statement)


class FormalReviewClaimTests(unittest.TestCase):
    def _candidate(self):
        return FusionEvidence(
            item=EvidenceItem(
                evidence_id="candidate:1",
                fact_kind=FactKind.CANDIDATE_RELATION,
                scope=AssistantScope(cross_section_id="section:1"),
                value={},
            ),
            metadata=FusionMetadata(),
        )

    def _build(self):
        builder = ClaimBuilder()
        requirement = make_requirement(
            "req:match",
            evidence_type=EvidenceType.SECTION_MATCHES,
            scope=AssistantScope(cross_section_id="section:1"),
        )
        assessment = make_assessment(
            "req:match",
            status=ClaimSupportStatus.FORMAL_REVIEW_REQUIRED,
            capability=ClaimCapability.CONFIRMED_RELATION,
        )
        return builder.build(
            make_question_result(requirements=(requirement,)),
            make_bundle(assessments=(assessment,), evidence=(self._candidate(),)),
        )

    def test_formal_review_required_builds_candidate_claim(self):
        claims = self._build()
        self.assertEqual(1, len(claims))
        claim = claims[0]
        self.assertEqual("formal_review_required", claim.status)
        self.assertEqual(("待复核",), claim.qualifiers)
        self.assertEqual(("candidate:1",), claim.evidence_ids)
        self.assertEqual((FactKind.CANDIDATE_RELATION,), claim.fact_kinds)

    def test_candidate_is_not_written_as_confirmed(self):
        claim = self._build()[0]
        self.assertIn("待复核", claim.statement)
        self.assertNotIn("已确认", claim.statement)
        self.assertNotEqual(ClaimStatus.SUPPORTED.value, claim.status)

    def test_no_candidate_promotion_or_write_back(self):
        claim = self._build()[0]
        self.assertEqual("formal_review_required", claim.status)
        self.assertFalse(hasattr(claim, "write_back"))
        self.assertFalse(hasattr(claim, "promote"))


class NonGeneratingStatusTests(unittest.TestCase):
    def test_missing_produces_no_claim(self):
        builder = ClaimBuilder()
        requirement = make_requirement("req:1")
        assessment = make_assessment("req:1", status=ClaimSupportStatus.MISSING)
        claims = builder.build(
            make_question_result(requirements=(requirement,)),
            make_bundle(assessments=(assessment,), evidence=()),
        )
        self.assertEqual((), claims)

    def test_stale_only_produces_no_claim(self):
        builder = ClaimBuilder()
        requirement = make_requirement("req:1")
        evidence = (make_fusion("evidence:1"),)
        assessment = make_assessment(
            "req:1",
            status=ClaimSupportStatus.STALE_ONLY,
            qualifying=("evidence:1",),
        )
        claims = builder.build(
            make_question_result(requirements=(requirement,)),
            make_bundle(assessments=(assessment,), evidence=evidence),
        )
        self.assertEqual((), claims)

    def test_unsupported_produces_no_claim(self):
        builder = ClaimBuilder()
        requirement = make_requirement("req:1")
        assessment = make_assessment("req:1", status=ClaimSupportStatus.UNSUPPORTED)
        claims = builder.build(
            make_question_result(requirements=(requirement,)),
            make_bundle(assessments=(assessment,), evidence=()),
        )
        self.assertEqual((), claims)

    def test_non_generating_statuses_never_fabricate_claims(self):
        builder = ClaimBuilder()
        requirement = make_requirement("req:1")
        for status in (
            ClaimSupportStatus.MISSING,
            ClaimSupportStatus.STALE_ONLY,
            ClaimSupportStatus.UNSUPPORTED,
        ):
            assessment = make_assessment("req:1", status=status)
            claims = builder.build(
                make_question_result(requirements=(requirement,)),
                make_bundle(assessments=(assessment,), evidence=()),
            )
            self.assertEqual((), claims, f"status {status} should produce no claim")


class DiagnosticClaimTests(unittest.TestCase):
    def test_diagnostic_claim_carries_reason_code(self):
        claim = ClaimBuilder.build_diagnostic_claim(
            "req:1",
            "sub:1",
            AssistantScope(page_id="page:1"),
            ReasonCode.RECOGNITION_FAILED,
        )
        self.assertEqual("diagnostic", claim.status)
        self.assertEqual((FactKind.DIAGNOSTIC,), claim.fact_kinds)
        self.assertEqual((ReasonCode.RECOGNITION_FAILED,), claim.reason_codes)
        self.assertEqual(("recognition_failed",), claim.qualifiers)
        self.assertEqual((), claim.evidence_ids)
        self.assertEqual("sub:1", claim.subrequest_id)
        self.assertTrue(claim.claim_id.startswith("claim:"))

    def test_diagnostic_statement_marks_runtime_status(self):
        claim = ClaimBuilder.build_diagnostic_claim(
            "req:1",
            None,
            None,
            ReasonCode.INTERNAL_ERROR,
        )
        self.assertIn("运行状态", claim.statement)
        self.assertNotIn("已确认", claim.statement)

    def test_diagnostic_claim_accepts_stable_reason_string(self):
        claim = ClaimBuilder.build_diagnostic_claim(
            "req:1",
            None,
            None,
            "recognition_failed",
        )
        self.assertEqual((ReasonCode.RECOGNITION_FAILED,), claim.reason_codes)

    def test_diagnostic_without_reason_code_is_rejected(self):
        with self.assertRaises(ValueError):
            ClaimBuilder.build_diagnostic_claim("req:1", None, None, None)
        with self.assertRaises(ValueError):
            ClaimBuilder.build_diagnostic_claim("req:1", None, None, " ")

    def test_diagnostic_claim_is_not_engineering_fact(self):
        claim = ClaimBuilder.build_diagnostic_claim(
            "req:1",
            None,
            None,
            ReasonCode.RECOGNITION_FAILED,
        )
        self.assertNotEqual(ClaimStatus.SUPPORTED.value, claim.status)
        self.assertEqual("runtime_or_cache_status", claim.claim_type)
        self.assertEqual((), claim.evidence_ids)


if __name__ == "__main__":
    unittest.main()
