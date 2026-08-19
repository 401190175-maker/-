"""Tests for evidence fusion orchestration and input validation (Task 46-47)."""

import unittest

from drawing_graph.assistant_evidence_fusion import FusionInputError, validate_fusion_input
from drawing_graph.assistant_evidence_fusion_factory import create_evidence_fusion_service
from drawing_graph.assistant_evidence_fusion_models import (
    ClaimCapability,
    ClaimSupportAssessment,
    ClaimSupportStatus,
    ConflictRecord,
    ConflictSeverity,
    ConflictType,
    EvidenceFusionRequest,
    FusionEvidence,
    FusionMetadata,
    WriteBackPolicy,
)
from drawing_graph.assistant_models import (
    AssistantRequest,
    AssistantScope,
    EvidenceItem,
    EvidenceRequirement,
    EvidenceType,
    FactKind,
    FreshnessRequirement,
    QuestionUnderstandingResult,
    ReasonCode,
    RetrievalBundle,
    SemanticGapDecision,
)
from drawing_graph.semantic_models import ObservationStatus, TextObservation
from drawing_graph.semantic_service import SemanticRecognitionResult
from drawing_graph.tool_models import BBox

def make_request(**overrides):
    values = dict(
        assistant_request=AssistantRequest(request_id="req:1", question="q"),
        question_result=QuestionUnderstandingResult(request_id="req:1", question_type="page_summary"),
        retrieval_bundle=RetrievalBundle(request_id="req:1"),
        semantic_gap_decision=SemanticGapDecision(request_id="req:1"),
    )
    values.update(overrides)
    return EvidenceFusionRequest(**values)


def make_fusion_evidence(
    evidence_id: str,
    fact_kind: FactKind = FactKind.SEMANTIC_OBSERVATION,
    confidence=None,
    source_call_id=None,
    recognition_run_id=None,
    payload_ref=None,
    rule_version=None,
) -> FusionEvidence:
    return FusionEvidence(
        item=EvidenceItem(
            evidence_id=evidence_id,
            fact_kind=fact_kind,
            scope=AssistantScope(page_id="page:1"),
            value={},
            confidence=confidence,
            source_call_id=source_call_id,
            recognition_run_id=recognition_run_id,
            payload_ref=payload_ref,
            rule_version=rule_version,
        ),
        metadata=FusionMetadata(),
    )


class _FakeNormalizer:
    def __init__(self, fused):
        self._fused = tuple(fused)

    def normalize(self, evidence):
        from drawing_graph.assistant_evidence_normalization import NormalizationResult

        return NormalizationResult(normalized=self._fused, isolated=(), reason_codes=())


class _FakeDeduplicator:
    def deduplicate(self, evidence):
        from drawing_graph.assistant_evidence_deduplication import DeduplicationResult

        return DeduplicationResult(
            deduplicated=tuple(evidence),
            groups=tuple((item.item.evidence_id,) for item in evidence),
        )


class _FakeConflictDetector:
    def __init__(self, conflicts):
        self._conflicts = tuple(conflicts)

    def detect(self, evidence):
        return self._conflicts


class _FakeClaimEvaluator:
    def __init__(self, assessments):
        self._assessments = tuple(assessments)

    def evaluate(self, requirements, evidence, conflicts=(), prior_assessments=(), subrequest_id=None):
        return self._assessments


def build_fusion_service(evidence, conflicts=(), claim_evaluator=None):
    from drawing_graph.assistant_evidence_fusion import EvidenceFusionService

    return EvidenceFusionService(
        normalizer=_FakeNormalizer(evidence),
        deduplicator=_FakeDeduplicator(),
        conflict_detector=_FakeConflictDetector(conflicts),
        claim_evaluator=claim_evaluator,
    )


class FusionInputValidationTests(unittest.TestCase):
    def test_consistent_request_ids_validate(self):
        validate_fusion_input(make_request())

    def test_mismatched_request_id_raises(self):
        request = make_request(
            retrieval_bundle=RetrievalBundle(request_id="req:other"),
        )
        with self.assertRaises(FusionInputError) as error:
            validate_fusion_input(request)
        self.assertEqual(ReasonCode.FUSION_INPUT_INVALID, error.exception.reason_code)

    def test_policy_cannot_broaden_authorization(self):
        request = make_request(
            assistant_request=AssistantRequest(request_id="req:1", question="q", allow_write_back=False),
            write_back_policy=WriteBackPolicy(request_allow_write_back=True),
        )
        with self.assertRaises(FusionInputError):
            validate_fusion_input(request)

    def test_duplicate_subrequest_raises(self):
        from drawing_graph.assistant_models import AssistantSubrequest

        question_result = QuestionUnderstandingResult(
            request_id="req:1",
            question_type="multi_intent",
            subrequests=(
                AssistantSubrequest(subrequest_id="sub:1", question_type="page_summary"),
                AssistantSubrequest(subrequest_id="sub:1", question_type="block_relations"),
            ),
        )
        with self.assertRaises(FusionInputError):
            validate_fusion_input(make_request(question_result=question_result))

    def test_contradictory_run_status_raises(self):
        from drawing_graph.semantic_service import SemanticRecognitionResult

        results = (
            SemanticRecognitionResult(recognition_run_id="run:1", status="succeeded", observations=(), persisted=False),
            SemanticRecognitionResult(recognition_run_id="run:1", status="failed", observations=(), persisted=False),
        )
        with self.assertRaises(FusionInputError):
            validate_fusion_input(make_request(recognition_results=results))


class EvidenceFusionPipelineTests(unittest.TestCase):
    def test_write_back_false_produces_bundle_without_persistence(self):
        from drawing_graph.assistant_evidence_fusion import EvidenceFusionService
        from drawing_graph.assistant_evidence_fusion_models import WriteBackStatus

        service = EvidenceFusionService()
        bundle = service.fuse(make_request())

        self.assertEqual("req:1", bundle.request_id)
        self.assertIsNotNone(bundle.answerability)
        self.assertEqual(WriteBackStatus.NOT_REQUESTED, bundle.write_back_result.status)

    def test_write_back_request_without_port_is_skipped(self):
        from drawing_graph.assistant_evidence_fusion import EvidenceFusionService
        from drawing_graph.assistant_evidence_fusion_models import WriteBackStatus

        service = EvidenceFusionService()
        request = make_request(
            assistant_request=AssistantRequest(request_id="req:1", question="q", allow_write_back=True),
            write_back_policy=WriteBackPolicy(request_allow_write_back=True),
        )
        bundle = service.fuse(request)
        self.assertEqual(WriteBackStatus.SKIPPED, bundle.write_back_result.status)

    def test_fatal_input_error_fails_closed(self):
        from drawing_graph.assistant_evidence_fusion import EvidenceFusionService

        service = EvidenceFusionService()
        request = make_request(retrieval_bundle=RetrievalBundle(request_id="req:other"))
        with self.assertRaises(FusionInputError):
            service.fuse(request)


class EvidenceBundleSubrequestTests(unittest.TestCase):
    def test_bundle_carries_retrieval_subrequest_id(self):
        from drawing_graph.assistant_evidence_fusion import EvidenceFusionService

        request = make_request(
            question_result=QuestionUnderstandingResult(
                request_id="req:1",
                question_type="page_summary",
                subrequest_id="sub:1",
            ),
            retrieval_bundle=RetrievalBundle(request_id="req:1", subrequest_id="sub:1"),
            semantic_gap_decision=SemanticGapDecision(request_id="req:1", subrequest_id="sub:1"),
        )
        bundle = EvidenceFusionService().fuse(request)
        self.assertEqual("sub:1", bundle.subrequest_id)

    def test_top_level_bundle_keeps_subrequest_id_none(self):
        from drawing_graph.assistant_evidence_fusion import EvidenceFusionService

        bundle = EvidenceFusionService().fuse(make_request())
        self.assertIsNone(bundle.subrequest_id)


class EvidenceBucketTests(unittest.TestCase):
    def test_no_conflicts_keeps_all_evidence_accepted(self):
        evidence = (
            make_fusion_evidence("evidence:1"),
            make_fusion_evidence("evidence:2"),
        )
        bundle = build_fusion_service(evidence).fuse(make_request())
        self.assertEqual(
            ("evidence:1", "evidence:2"),
            tuple(item.item.evidence_id for item in bundle.accepted_evidence),
        )
        self.assertEqual((), bundle.conflicting_evidence)

    def test_blocking_conflict_members_are_conflicting_not_accepted(self):
        evidence = (
            make_fusion_evidence("evidence:1"),
            make_fusion_evidence("evidence:2"),
            make_fusion_evidence("evidence:3"),
        )
        conflict = ConflictRecord(
            conflict_id="conflict:1",
            comparison_key="comparison:1",
            conflict_type=ConflictType.HARD_CONFLICT,
            severity=ConflictSeverity.BLOCKING,
            evidence_ids=("evidence:1", "evidence:2"),
        )
        bundle = build_fusion_service(evidence, conflicts=(conflict,)).fuse(make_request())
        self.assertEqual(
            ("evidence:3",),
            tuple(item.item.evidence_id for item in bundle.accepted_evidence),
        )
        self.assertEqual(
            ("evidence:1", "evidence:2"),
            tuple(item.item.evidence_id for item in bundle.conflicting_evidence),
        )

    def test_non_blocking_conflict_members_stay_accepted(self):
        evidence = (
            make_fusion_evidence("evidence:1"),
            make_fusion_evidence("evidence:2"),
        )
        conflict = ConflictRecord(
            conflict_id="conflict:2",
            comparison_key="comparison:1",
            conflict_type=ConflictType.PEER_CONFLICT,
            severity=ConflictSeverity.WARNING,
            evidence_ids=("evidence:1", "evidence:2"),
        )
        bundle = build_fusion_service(evidence, conflicts=(conflict,)).fuse(make_request())
        self.assertEqual(2, len(bundle.accepted_evidence))
        self.assertEqual((), bundle.conflicting_evidence)

    def test_unconflicting_evidence_never_enters_conflicting(self):
        evidence = (
            make_fusion_evidence("evidence:1"),
            make_fusion_evidence("evidence:2"),
        )
        conflict = ConflictRecord(
            conflict_id="conflict:3",
            comparison_key="comparison:1",
            conflict_type=ConflictType.HARD_CONFLICT,
            severity=ConflictSeverity.BLOCKING,
            evidence_ids=("evidence:1",),
        )
        bundle = build_fusion_service(evidence, conflicts=(conflict,)).fuse(make_request())
        self.assertEqual(
            ("evidence:2",),
            tuple(item.item.evidence_id for item in bundle.accepted_evidence),
        )
        self.assertEqual(
            ("evidence:1",),
            tuple(item.item.evidence_id for item in bundle.conflicting_evidence),
        )


class EvidenceProvenanceOutputTests(unittest.TestCase):
    def test_provenance_projects_surviving_evidence_source(self):
        evidence = (
            make_fusion_evidence(
                "evidence:1",
                source_call_id="call:1",
                recognition_run_id="run:1",
                payload_ref="payload:1",
                rule_version="v1",
            ),
            make_fusion_evidence("evidence:2", source_call_id="call:2"),
        )
        bundle = build_fusion_service(evidence).fuse(make_request())
        self.assertEqual(2, len(bundle.provenance))
        first = bundle.provenance[0]
        self.assertEqual("call:1", first.source_call_id)
        self.assertEqual("run:1", first.recognition_run_id)
        self.assertEqual("payload:1", first.payload_ref)
        self.assertEqual("v1", first.rule_version)
        self.assertEqual("call:2", bundle.provenance[1].source_call_id)

    def test_provenance_order_follows_evidence_order(self):
        evidence = (
            make_fusion_evidence("evidence:b", source_call_id="call:b"),
            make_fusion_evidence("evidence:a", source_call_id="call:a"),
        )
        bundle = build_fusion_service(evidence).fuse(make_request())
        self.assertEqual(
            ("call:b", "call:a"),
            tuple(item.source_call_id for item in bundle.provenance),
        )

    def test_provenance_does_not_copy_payload_body(self):
        evidence = (make_fusion_evidence("evidence:1", payload_ref="payload:1"),)
        bundle = build_fusion_service(evidence).fuse(make_request())
        self.assertEqual("payload:1", bundle.provenance[0].payload_ref)
        self.assertFalse(hasattr(bundle.provenance[0], "payload"))


class EvidenceConfidenceOutputTests(unittest.TestCase):
    def test_empty_evidence_has_no_confidence(self):
        bundle = build_fusion_service(()).fuse(make_request())
        self.assertIsNone(bundle.overall_confidence)

    def test_single_confidence_is_preserved(self):
        evidence = (make_fusion_evidence("evidence:1", confidence=0.9),)
        bundle = build_fusion_service(evidence).fuse(make_request())
        self.assertEqual(0.9, bundle.overall_confidence)

    def test_multiple_confidences_are_averaged(self):
        evidence = (
            make_fusion_evidence("evidence:1", confidence=0.9),
            make_fusion_evidence("evidence:2", confidence=0.7),
        )
        bundle = build_fusion_service(evidence).fuse(make_request())
        self.assertEqual(0.8, bundle.overall_confidence)

    def test_evidence_without_confidence_is_ignored(self):
        evidence = (
            make_fusion_evidence("evidence:1", confidence=0.9),
            make_fusion_evidence("evidence:2"),
        )
        bundle = build_fusion_service(evidence).fuse(make_request())
        self.assertEqual(0.9, bundle.overall_confidence)

    def test_blocking_conflict_reduces_confidence_basis(self):
        evidence = (
            make_fusion_evidence("evidence:1", confidence=0.9),
            make_fusion_evidence("evidence:2", confidence=0.7),
        )
        conflict = ConflictRecord(
            conflict_id="conflict:1",
            comparison_key="comparison:1",
            conflict_type=ConflictType.HARD_CONFLICT,
            severity=ConflictSeverity.BLOCKING,
            evidence_ids=("evidence:1", "evidence:2"),
        )
        bundle = build_fusion_service(evidence, conflicts=(conflict,)).fuse(make_request())
        self.assertIsNone(bundle.overall_confidence)

    def test_high_confidence_candidate_is_not_promoted_to_formal(self):
        evidence = (
            make_fusion_evidence(
                "candidate:1",
                fact_kind=FactKind.CANDIDATE_RELATION,
                confidence=0.99,
            ),
        )
        bundle = build_fusion_service(evidence).fuse(make_request())
        self.assertEqual(0.99, bundle.overall_confidence)
        self.assertEqual(
            FactKind.CANDIDATE_RELATION,
            bundle.accepted_evidence[0].item.fact_kind,
        )


class UnsupportedClaimOutputTests(unittest.TestCase):
    def _assessments(self):
        return (
            ClaimSupportAssessment(
                requirement_id="req:1",
                claim_capability=ClaimCapability.OBSERVED_TEXT_OR_SYMBOL,
                status=ClaimSupportStatus.MISSING,
            ),
            ClaimSupportAssessment(
                requirement_id="req:2",
                claim_capability=ClaimCapability.SEMANTIC_MEANING,
                status=ClaimSupportStatus.STALE_ONLY,
            ),
            ClaimSupportAssessment(
                requirement_id="req:3",
                claim_capability=ClaimCapability.OBSERVED_TEXT_OR_SYMBOL,
                status=ClaimSupportStatus.UNSUPPORTED,
            ),
            ClaimSupportAssessment(
                requirement_id="req:4",
                claim_capability=ClaimCapability.OBSERVED_TEXT_OR_SYMBOL,
                status=ClaimSupportStatus.SUPPORTED,
            ),
        )

    def test_unsupported_missing_stale_are_projected(self):
        bundle = build_fusion_service(
            (),
            claim_evaluator=_FakeClaimEvaluator(self._assessments()),
        ).fuse(make_request())
        self.assertEqual(
            (
                "req:1:observed_text_or_symbol",
                "req:2:semantic_meaning",
                "req:3:observed_text_or_symbol",
            ),
            bundle.unsupported_claims,
        )

    def test_supported_never_enters_unsupported_claims(self):
        bundle = build_fusion_service(
            (),
            claim_evaluator=_FakeClaimEvaluator(self._assessments()),
        ).fuse(make_request())
        self.assertNotIn("req:4:observed_text_or_symbol", bundle.unsupported_claims)
        self.assertNotIn("req:4", bundle.unsupported_claims)

    def test_identifiers_are_deduplicated_and_sorted(self):
        assessments = (
            ClaimSupportAssessment(
                requirement_id="req:2",
                claim_capability=ClaimCapability.SEMANTIC_MEANING,
                status=ClaimSupportStatus.MISSING,
            ),
            ClaimSupportAssessment(
                requirement_id="req:1",
                claim_capability=ClaimCapability.OBSERVED_TEXT_OR_SYMBOL,
                status=ClaimSupportStatus.MISSING,
            ),
        )
        bundle = build_fusion_service(
            (),
            claim_evaluator=_FakeClaimEvaluator(assessments),
        ).fuse(make_request())
        self.assertEqual(
            ("req:1:observed_text_or_symbol", "req:2:semantic_meaning"),
            bundle.unsupported_claims,
        )

    def test_no_assessments_yields_empty_unsupported_claims(self):
        bundle = build_fusion_service(()).fuse(make_request())
        self.assertEqual((), bundle.unsupported_claims)


class EvidenceWarningOutputTests(unittest.TestCase):
    def test_basic_fusion_produces_no_warnings(self):
        bundle = build_fusion_service(()).fuse(make_request())
        self.assertEqual((), bundle.warnings)

    def test_write_back_not_requested_produces_no_write_back_warning(self):
        from drawing_graph.assistant_evidence_fusion import EvidenceFusionService
        from drawing_graph.assistant_evidence_fusion_models import WriteBackStatus

        bundle = EvidenceFusionService().fuse(make_request())
        self.assertEqual(WriteBackStatus.NOT_REQUESTED, bundle.write_back_result.status)
        self.assertEqual((), bundle.warnings)

    def test_normalization_isolation_produces_safe_warning(self):
        from drawing_graph.assistant_evidence_fusion import EvidenceFusionService
        from drawing_graph.assistant_evidence_normalization import NormalizationResult

        class IsolatingNormalizer:
            def normalize(self, evidence):
                isolated = (
                    EvidenceItem(
                        evidence_id="evidence:bad",
                        fact_kind=FactKind.SEMANTIC_OBSERVATION,
                        value={"secret": "C:/secret.png"},
                        evidence_metadata={"traceback": "boom"},
                    ),
                )
                return NormalizationResult(
                    normalized=(),
                    isolated=isolated,
                    reason_codes=(ReasonCode.EVIDENCE_NORMALIZATION_FAILED,),
                )

        bundle = EvidenceFusionService(normalizer=IsolatingNormalizer()).fuse(make_request())
        self.assertEqual(1, len(bundle.warnings))
        self.assertIn("could not be normalized", bundle.warnings[0])
        self.assertNotIn("secret", bundle.warnings[0])
        self.assertNotIn("C:/", bundle.warnings[0])
        self.assertNotIn("traceback", bundle.warnings[0])


class RequestCurrentMarkingTests(unittest.TestCase):
    """05 必须在请求内把证据标记为 current，否则 claim support 全部判 stale。"""

    @staticmethod
    def _source_fact_item():
        return EvidenceItem(
            evidence_id="evidence:src:1",
            fact_kind=FactKind.SOURCE_FACT,
            scope=AssistantScope(page_id="page:1", element_id="element:1"),
            value={
                "page_id": "page:1",
                "element_id": "element:1",
                "element_type": "Table",
                "bbox": {"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
            },
        )

    @staticmethod
    def _observation_item(evidence_id="evidence:obs:1"):
        bbox = {"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4}
        return EvidenceItem(
            evidence_id=evidence_id,
            fact_kind=FactKind.SEMANTIC_OBSERVATION,
            status="confirmed",
            scope=AssistantScope(page_id="page:1", element_id="element:1"),
            value={"raw_text": "A-A", "normalized_text": "A-A", "bbox": bbox},
            evidence_metadata={"image_hash": None, "bbox": bbox, "prompt_version": None},
        )

    @staticmethod
    def _page_source_requirement():
        return EvidenceRequirement(
            requirement_id="understanding:page_summary:page_source_facts",
            evidence_type=EvidenceType.PAGE_SOURCE_FACTS,
            target_scope=AssistantScope(page_id="page:1"),
        )

    @staticmethod
    def _observation_requirement():
        return EvidenceRequirement(
            requirement_id="understanding:q:text_observations",
            evidence_type=EvidenceType.TEXT_OBSERVATIONS,
            target_scope=AssistantScope(page_id="page:1"),
            freshness_requirement=FreshnessRequirement(
                require_current_image=True,
                require_current_bbox=True,
                require_current_prompt=True,
            ),
        )

    def _request(self, *, bundle, requirements, recognition_results=()):
        question_result = QuestionUnderstandingResult(
            request_id="req:1",
            question_type="page_summary",
            required_evidence=requirements,
        )
        return EvidenceFusionRequest(
            assistant_request=AssistantRequest(request_id="req:1", question="q"),
            question_result=question_result,
            retrieval_bundle=bundle,
            semantic_gap_decision=SemanticGapDecision(request_id="req:1"),
            recognition_results=recognition_results,
            write_back_policy=None,
        )

    def test_live_source_fact_is_current_and_supports_claim(self):
        service = create_evidence_fusion_service()
        bundle = RetrievalBundle(request_id="req:1", source_facts=(self._source_fact_item(),))
        result = service.fuse(
            self._request(bundle=bundle, requirements=(self._page_source_requirement(),))
        )
        self.assertEqual(1, len(result.accepted_evidence))
        self.assertTrue(result.accepted_evidence[0].metadata.is_current_for_request)
        self.assertEqual(ClaimSupportStatus.SUPPORTED, result.claim_support[0].status)

    def test_cached_observation_without_freshness_metadata_is_not_current(self):
        service = create_evidence_fusion_service()
        bundle = RetrievalBundle(
            request_id="req:1",
            semantic_observations=(self._observation_item(),),
        )
        result = service.fuse(
            self._request(bundle=bundle, requirements=(self._observation_requirement(),))
        )
        self.assertEqual(ClaimSupportStatus.STALE_ONLY, result.claim_support[0].status)
        self.assertEqual((), result.claim_support[0].supporting_evidence_ids)

    def test_fresh_recognition_observation_is_current(self):
        service = create_evidence_fusion_service()
        observation = TextObservation(
            observation_id="obs:run:1",
            recognition_run_id="run:1",
            target_element_id="element:1",
            target_element_type="BlockCaption",
            page_id="page:1",
            raw_text="A-A",
            normalized_text="A-A",
            bbox=BBox(1.0, 2.0, 3.0, 4.0),
            normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
            confidence=0.9,
            status=ObservationStatus.CONFIRMED,
        )
        recognition = SemanticRecognitionResult(
            recognition_run_id="run:1",
            status="succeeded",
            observations=(observation,),
            persisted=False,
        )
        bundle = RetrievalBundle(request_id="req:1")
        result = service.fuse(
            self._request(
                bundle=bundle,
                requirements=(self._observation_requirement(),),
                recognition_results=(recognition,),
            )
        )
        self.assertEqual(ClaimSupportStatus.SUPPORTED, result.claim_support[0].status)


if __name__ == "__main__":
    unittest.main()
