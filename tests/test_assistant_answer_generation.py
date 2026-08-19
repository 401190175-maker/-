"""Tests for the answer-generation service collaborators."""

import unittest

from drawing_graph.assistant_answer_generation import (
    AnswerGenerationService,
    AnswerPackageValidator,
    AnswerStatusResolver,
    AnswerValidationError,
    MachineAnswerBuilder,
)
from drawing_graph.assistant_evidence_fusion_models import (
    Answerability,
    AnswerabilityResult,
    ClaimCapability,
    ClaimSupportAssessment,
    ClaimSupportStatus,
    EvidenceBundle,
    FusionEvidence,
    FusionMetadata,
)
from drawing_graph.assistant_models import (
    ANSWER_CONTRACT_VERSION,
    AnswerGenerationPolicy,
    AnswerGenerationRequest,
    AnswerPackage,
    AnswerStatus,
    AssistantRequest,
    AssistantScope,
    Citation,
    Claim,
    EvidenceItem,
    EvidenceRequirement,
    EvidenceType,
    FactKind,
    MachineAnswer,
    QuestionType,
    QuestionUnderstandingResult,
    ReasonCode,
    RecognitionFailure,
    TextRenderMode,
)


def make_answerability(status):
    return AnswerabilityResult(status=status)


def make_claim(claim_id="claim:1", status="supported", fact_kinds=(FactKind.SEMANTIC_OBSERVATION,)):
    return Claim(
        claim_id=claim_id,
        statement="图中识别到的文字与符号已确认",
        claim_type="observed_text_or_symbol",
        status=status,
        evidence_ids=("evidence:1",),
        fact_kinds=fact_kinds,
    )


def make_failure(reason_code=ReasonCode.RECOGNITION_FAILED):
    return RecognitionFailure(page_id="page:1", reason_code=reason_code, message="recognition failed")


class AnswerStatusResolverTests(unittest.TestCase):
    def setUp(self):
        self.resolver = AnswerStatusResolver()

    def test_answerable_with_claims_is_answered(self):
        status = self.resolver.resolve(
            make_answerability(Answerability.ANSWERABLE),
            (make_claim(),),
        )
        self.assertEqual(AnswerStatus.ANSWERED, status)

    def test_partially_answerable_is_partial(self):
        status = self.resolver.resolve(
            make_answerability(Answerability.PARTIALLY_ANSWERABLE),
            (make_claim(),),
        )
        self.assertEqual(AnswerStatus.PARTIAL, status)

    def test_clarification_without_claims_is_clarification(self):
        status = self.resolver.resolve(
            make_answerability(Answerability.CLARIFICATION_REQUIRED),
            (),
        )
        self.assertEqual(AnswerStatus.CLARIFICATION_REQUIRED, status)

    def test_unsupported_without_claims_is_unsupported(self):
        status = self.resolver.resolve(
            make_answerability(Answerability.UNSUPPORTED),
            (),
        )
        self.assertEqual(AnswerStatus.UNSUPPORTED, status)

    def test_recognition_failed_without_semantic_claim(self):
        status = self.resolver.resolve(
            make_answerability(Answerability.PARTIALLY_ANSWERABLE),
            (make_claim(fact_kinds=(FactKind.SOURCE_FACT,)),),
            recognition_failures=(make_failure(),),
        )
        self.assertEqual(AnswerStatus.RECOGNITION_FAILED, status)

    def test_recognition_failure_with_semantic_claim_is_partial(self):
        status = self.resolver.resolve(
            make_answerability(Answerability.PARTIALLY_ANSWERABLE),
            (make_claim(fact_kinds=(FactKind.SEMANTIC_OBSERVATION,)),),
            recognition_failures=(make_failure(),),
        )
        self.assertEqual(AnswerStatus.PARTIAL, status)

    def test_blocking_conflict_is_partial(self):
        status = self.resolver.resolve(
            make_answerability(Answerability.ANSWERABLE),
            (make_claim(),),
            blocking_conflicts=True,
        )
        self.assertEqual(AnswerStatus.PARTIAL, status)

    def test_clarification_with_claims_is_partial(self):
        status = self.resolver.resolve(
            make_answerability(Answerability.CLARIFICATION_REQUIRED),
            (make_claim(),),
        )
        self.assertEqual(AnswerStatus.PARTIAL, status)

    def test_unsupported_with_claims_is_partial(self):
        status = self.resolver.resolve(
            make_answerability(Answerability.UNSUPPORTED),
            (make_claim(),),
        )
        self.assertEqual(AnswerStatus.PARTIAL, status)

    def test_priority_clarification_before_recognition(self):
        status = self.resolver.resolve(
            make_answerability(Answerability.CLARIFICATION_REQUIRED),
            (),
            recognition_failures=(make_failure(),),
        )
        self.assertEqual(AnswerStatus.CLARIFICATION_REQUIRED, status)

    def test_diagnostic_claim_is_not_engineering(self):
        diagnostic = make_claim(status="diagnostic", fact_kinds=(FactKind.DIAGNOSTIC,))
        status = self.resolver.resolve(
            make_answerability(Answerability.ANSWERABLE),
            (diagnostic,),
        )
        self.assertEqual(AnswerStatus.ANSWERED, status)


class MachineAnswerBuilderTests(unittest.TestCase):
    def test_builds_machine_answer_from_approved_outputs(self):
        builder = MachineAnswerBuilder()
        claim = make_claim()
        citation = Citation(
            citation_id="citation:1",
            evidence_id="evidence:1",
            claim_ids=("claim:1",),
        )
        machine = builder.build(
            request_id="req:1",
            question_type="page_summary",
            scope=AssistantScope(page_id="page:1"),
            status=AnswerStatus.ANSWERED,
            claims=(claim,),
            citations=(citation,),
            recognition_run_ids=("run:1",),
        )
        self.assertEqual(ANSWER_CONTRACT_VERSION, machine.answer_contract_version)
        self.assertEqual("req:1", machine.request_id)
        self.assertEqual("page_summary", machine.question_type)
        self.assertEqual(AnswerStatus.ANSWERED, machine.status)
        self.assertEqual((claim,), machine.claims)
        self.assertEqual((citation,), machine.citations)
        self.assertEqual(("run:1",), machine.recognition_run_ids)

    def test_scalar_collections_are_deduped_and_sorted(self):
        builder = MachineAnswerBuilder()
        machine = builder.build(
            request_id="req:1",
            question_type="page_summary",
            status=AnswerStatus.PARTIAL,
            warnings=("b", "a", "b"),
            unsupported_parts=("z", "a"),
            recognition_run_ids=("run:2", "run:1", "run:1"),
            follow_up_actions=("y", "x"),
            reason_codes=(
                ReasonCode.INTERNAL_ERROR,
                ReasonCode.RESULT_TRUNCATED,
                ReasonCode.INTERNAL_ERROR,
            ),
        )
        self.assertEqual(("a", "b"), machine.warnings)
        self.assertEqual(("a", "z"), machine.unsupported_parts)
        self.assertEqual(("run:1", "run:2"), machine.recognition_run_ids)
        self.assertEqual(("x", "y"), machine.follow_up_actions)
        self.assertEqual(
            ("internal_error", "result_truncated"),
            tuple(code.value for code in machine.reason_codes),
        )

    def test_claims_sorted_by_subrequest_then_claim_id(self):
        builder = MachineAnswerBuilder()
        claim_a = make_claim(claim_id="claim:a")
        claim_b = make_claim(claim_id="claim:b")
        machine = builder.build(
            request_id="req:1",
            question_type="page_summary",
            status=AnswerStatus.ANSWERED,
            claims=(claim_b, claim_a),
        )
        self.assertEqual(("claim:a", "claim:b"), tuple(c.claim_id for c in machine.claims))

    def test_no_runtime_or_sensitive_fields(self):
        builder = MachineAnswerBuilder()
        machine = builder.build(
            request_id="req:1",
            question_type="page_summary",
            status=AnswerStatus.ANSWERED,
        )
        self.assertFalse(hasattr(machine, "session"))
        self.assertFalse(hasattr(machine, "driver"))
        self.assertFalse(hasattr(machine, "api_key"))


class AnswerPackageValidatorTests(unittest.TestCase):
    def _claim(self, citation_ids=("citation:1",), fact_kinds=(FactKind.SEMANTIC_OBSERVATION,), claim_type="observed_text_or_symbol", status="supported"):
        return Claim(
            claim_id="claim:1",
            statement="s",
            claim_type=claim_type,
            status=status,
            evidence_ids=("evidence:1",),
            fact_kinds=fact_kinds,
            citation_ids=citation_ids,
        )

    def _citation(self, claim_ids=("claim:1",)):
        return Citation(
            citation_id="citation:1",
            evidence_id="evidence:1",
            claim_ids=claim_ids,
        )

    def _package(self, claim=None, citation=None, status="answered", machine_status=AnswerStatus.ANSWERED):
        claim = claim or self._claim()
        citation = citation or self._citation()
        machine = MachineAnswer(
            answer_contract_version=ANSWER_CONTRACT_VERSION,
            request_id="req:1",
            question_type="page_summary",
            status=machine_status,
            claims=(claim,),
            citations=(citation,),
        )
        return AnswerPackage(
            request_id="req:1",
            question_type="page_summary",
            status=status,
            machine_answer=machine,
            claims=(claim,),
            citations=(citation,),
        )

    def test_valid_package_passes(self):
        package = self._package()
        AnswerPackageValidator().validate(package)

    def test_status_mismatch_fails(self):
        package = self._package(status="partial", machine_status=AnswerStatus.ANSWERED)
        with self.assertRaises(AnswerValidationError):
            AnswerPackageValidator().validate(package)

    def test_claims_mismatch_fails(self):
        package = self._package()
        other_claim = Claim(
            claim_id="claim:2",
            statement="s",
            evidence_ids=("evidence:2",),
            fact_kinds=(FactKind.SEMANTIC_OBSERVATION,),
        )
        machine = MachineAnswer(
            answer_contract_version=ANSWER_CONTRACT_VERSION,
            request_id="req:1",
            question_type="page_summary",
            status=AnswerStatus.ANSWERED,
            claims=(other_claim,),
            citations=package.citations,
        )
        package = AnswerPackage(
            request_id="req:1",
            question_type="page_summary",
            status="answered",
            machine_answer=machine,
            claims=package.claims,
            citations=package.citations,
        )
        with self.assertRaises(AnswerValidationError):
            AnswerPackageValidator().validate(package)

    def test_orphan_citation_fails(self):
        package = self._package(citation=self._citation(claim_ids=("claim:missing",)))
        with self.assertRaises(AnswerValidationError):
            AnswerPackageValidator().validate(package)

    def test_non_diagnostic_claim_without_citation_fails(self):
        claim = self._claim(citation_ids=())
        package = self._package(claim=claim)
        with self.assertRaises(AnswerValidationError):
            AnswerPackageValidator().validate(package)

    def test_candidate_promoted_to_confirmed_fails(self):
        claim = self._claim(
            fact_kinds=(FactKind.CANDIDATE_RELATION,),
            claim_type="confirmed_relation",
            status="supported",
        )
        package = self._package(claim=claim)
        with self.assertRaises(AnswerValidationError):
            AnswerPackageValidator().validate(package)

    def test_valid_package_is_not_modified(self):
        package = self._package()
        before_claims = package.claims
        before_status = package.status
        AnswerPackageValidator().validate(package)
        self.assertEqual(before_claims, package.claims)
        self.assertEqual(before_status, package.status)


class TerminalAnswerTests(unittest.TestCase):
    def _request(self, question_type, evidence_bundle=None):
        return AnswerGenerationRequest(
            assistant_request=AssistantRequest(request_id="req:1", question="q"),
            question_result=QuestionUnderstandingResult(
                request_id="req:1",
                question_type=question_type,
            ),
            evidence_bundle=evidence_bundle,
        )

    def test_clarification_terminal_answer(self):
        package = AnswerGenerationService().generate(
            self._request(QuestionType.CLARIFICATION_REQUIRED.value)
        )
        self.assertEqual(AnswerStatus.CLARIFICATION_REQUIRED.value, package.status)
        self.assertIsInstance(package.machine_answer, MachineAnswer)
        self.assertEqual(TextRenderMode.TEMPLATE, package.render_mode)

    def test_unsupported_terminal_answer(self):
        package = AnswerGenerationService().generate(
            self._request(QuestionType.UNKNOWN_OR_UNSUPPORTED.value)
        )
        self.assertEqual(AnswerStatus.UNSUPPORTED.value, package.status)

    def test_non_terminal_without_bundle_is_rejected(self):
        with self.assertRaises(AnswerValidationError):
            AnswerGenerationService().generate(self._request("page_summary"))

    def test_terminal_answer_does_not_call_claim_or_citation_builders(self):
        from drawing_graph.assistant_answer_generation import AnswerGenerationService

        class Recording:
            def __init__(self):
                self.calls = 0

            def build(self, *args, **kwargs):
                self.calls += 1
                return ()

        claim_recorder = Recording()
        citation_recorder = Recording()
        service = AnswerGenerationService(
            claim_builder=claim_recorder,
            citation_builder=citation_recorder,
        )
        service.generate(self._request(QuestionType.CLARIFICATION_REQUIRED.value))
        self.assertEqual(0, claim_recorder.calls)
        self.assertEqual(0, citation_recorder.calls)


class AnswerGenerationPipelineTests(unittest.TestCase):
    def _request(self, bundle=None):
        requirement = EvidenceRequirement(
            requirement_id="req:1",
            evidence_type=EvidenceType.TEXT_OBSERVATIONS,
            target_scope=AssistantScope(page_id="page:1", element_id="element:1"),
        )
        fusion = FusionEvidence(
            item=EvidenceItem(
                evidence_id="evidence:1",
                fact_kind=FactKind.SEMANTIC_OBSERVATION,
                scope=AssistantScope(page_id="page:1", element_id="element:1"),
                value={"observation_id": "obs:1"},
            ),
            metadata=FusionMetadata(),
        )
        assessment = ClaimSupportAssessment(
            requirement_id="req:1",
            claim_capability=ClaimCapability.OBSERVED_TEXT_OR_SYMBOL,
            status=ClaimSupportStatus.SUPPORTED,
            supporting_evidence_ids=("evidence:1",),
        )
        bundle = bundle or EvidenceBundle(
            request_id="req:1",
            accepted_evidence=(fusion,),
            claim_support=(assessment,),
            answerability=AnswerabilityResult(status=Answerability.ANSWERABLE),
        )
        question_result = QuestionUnderstandingResult(
            request_id="req:1",
            question_type="page_summary",
            required_evidence=(requirement,),
        )
        return AnswerGenerationRequest(
            assistant_request=AssistantRequest(request_id="req:1", question="q"),
            question_result=question_result,
            evidence_bundle=bundle,
        )

    def test_pipeline_produces_answered_package(self):
        package = AnswerGenerationService().generate(self._request())
        self.assertEqual(AnswerStatus.ANSWERED.value, package.status)
        self.assertEqual(1, len(package.claims))
        self.assertEqual(1, len(package.citations))
        self.assertIsInstance(package.machine_answer, MachineAnswer)
        self.assertEqual(TextRenderMode.TEMPLATE, package.render_mode)
        self.assertTrue(package.text_answer)

    def test_pipeline_output_is_deterministic(self):
        service = AnswerGenerationService()
        first = service.generate(self._request())
        second = service.generate(self._request())
        self.assertEqual(first.claims, second.claims)
        self.assertEqual(first.citations, second.citations)
        self.assertEqual(first.text_answer, second.text_answer)

    def test_claim_citation_bidirectional(self):
        package = AnswerGenerationService().generate(self._request())
        claim = package.claims[0]
        citation = package.citations[0]
        self.assertEqual(claim.citation_ids, (citation.citation_id,))
        self.assertEqual(citation.claim_ids, (claim.claim_id,))

    def test_machine_answer_and_package_share_same_claims(self):
        package = AnswerGenerationService().generate(self._request())
        self.assertEqual(package.machine_answer.claims, package.claims)
        self.assertEqual(package.machine_answer.citations, package.citations)

    def test_pipeline_preserves_warnings_as_contract_tuple(self):
        bundle = EvidenceBundle(
            request_id="req:1",
            accepted_evidence=(
                FusionEvidence(
                    item=EvidenceItem(
                        evidence_id="evidence:1",
                        fact_kind=FactKind.SEMANTIC_OBSERVATION,
                        scope=AssistantScope(page_id="page:1", element_id="element:1"),
                        value={"observation_id": "obs:1"},
                    ),
                    metadata=FusionMetadata(),
                ),
            ),
            claim_support=(
                ClaimSupportAssessment(
                    requirement_id="req:1",
                    claim_capability=ClaimCapability.OBSERVED_TEXT_OR_SYMBOL,
                    status=ClaimSupportStatus.SUPPORTED,
                    supporting_evidence_ids=("evidence:1",),
                ),
            ),
            answerability=AnswerabilityResult(status=Answerability.ANSWERABLE),
            warnings=("bundle-warning",),
        )
        package = AnswerGenerationService().generate(self._request(bundle=bundle))

        self.assertEqual(("bundle-warning",), package.warnings)

    def test_unknown_evidence_reference_fails_closed(self):
        from drawing_graph.assistant_citation_builder import CitationIntegrityError

        requirement = EvidenceRequirement(
            requirement_id="req:1",
            evidence_type=EvidenceType.TEXT_OBSERVATIONS,
            target_scope=AssistantScope(page_id="page:1", element_id="element:1"),
        )
        assessment = ClaimSupportAssessment(
            requirement_id="req:1",
            claim_capability=ClaimCapability.OBSERVED_TEXT_OR_SYMBOL,
            status=ClaimSupportStatus.SUPPORTED,
            supporting_evidence_ids=("evidence:missing",),
        )
        bundle = EvidenceBundle(
            request_id="req:1",
            accepted_evidence=(),
            claim_support=(assessment,),
            answerability=AnswerabilityResult(status=Answerability.ANSWERABLE),
        )
        with self.assertRaises(CitationIntegrityError):
            AnswerGenerationService().generate(self._request(bundle=bundle))


def make_multi_request(n):
    evidence = tuple(
        FusionEvidence(
            item=EvidenceItem(
                evidence_id=f"evidence:{index}",
                fact_kind=FactKind.SEMANTIC_OBSERVATION,
                scope=AssistantScope(page_id="page:1", element_id=f"element:{index}"),
                value={},
            ),
            metadata=FusionMetadata(),
        )
        for index in range(n)
    )
    assessments = tuple(
        ClaimSupportAssessment(
            requirement_id=f"req:{index}",
            claim_capability=ClaimCapability.OBSERVED_TEXT_OR_SYMBOL,
            status=ClaimSupportStatus.SUPPORTED,
            supporting_evidence_ids=(f"evidence:{index}",),
        )
        for index in range(n)
    )
    bundle = EvidenceBundle(
        request_id="req:1",
        accepted_evidence=evidence,
        claim_support=assessments,
        answerability=AnswerabilityResult(status=Answerability.ANSWERABLE),
    )
    return AnswerGenerationRequest(
        assistant_request=AssistantRequest(request_id="req:1", question="q"),
        question_result=QuestionUnderstandingResult(request_id="req:1", question_type="page_summary"),
        evidence_bundle=bundle,
    )


class AnswerGenerationLimitTests(unittest.TestCase):
    def test_claim_limit_exceeded_rejected(self):
        with self.assertRaises(AnswerValidationError) as error:
            AnswerGenerationService().generate(
                make_multi_request(3),
                AnswerGenerationPolicy(max_claims=2),
            )
        self.assertEqual(ReasonCode.MAX_CLAIMS_EXCEEDED, error.exception.reason_code)

    def test_citation_limit_exceeded_rejected(self):
        with self.assertRaises(AnswerValidationError) as error:
            AnswerGenerationService().generate(
                make_multi_request(3),
                AnswerGenerationPolicy(max_citations=2),
            )
        self.assertEqual(ReasonCode.MAX_CITATIONS_EXCEEDED, error.exception.reason_code)

    def test_within_limit_passes(self):
        package = AnswerGenerationService().generate(
            make_multi_request(2),
            AnswerGenerationPolicy(max_claims=2, max_citations=2),
        )
        self.assertEqual(2, len(package.claims))

    def test_text_length_is_truncated_with_warning(self):
        package = AnswerGenerationService().generate(
            make_multi_request(1),
            AnswerGenerationPolicy(max_text_length=10),
        )
        self.assertLessEqual(len(package.text_answer), 10)
        self.assertIn(ReasonCode.RESULT_TRUNCATED.value, package.warnings)


if __name__ == "__main__":
    unittest.main()
