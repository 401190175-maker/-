"""Contract tests for the answer-generation public contract additions."""

import dataclasses
import unittest

from drawing_graph.assistant_models import (
    ANSWER_CONTRACT_VERSION,
    AnswerGenerationPolicy,
    AnswerGenerationRequest,
    AnswerPackage,
    AnswerStatus,
    AssistantExecutionPolicy,
    AssistantRequest,
    AssistantScope,
    Citation,
    Claim,
    ClaimStatus,
    MachineAnswer,
    QuestionUnderstandingResult,
    ReasonCode,
    RecognitionFailure,
    RecognitionPolicy,
    RetrievalPolicy,
    Subanswer,
    TextRenderMode,
)


class AnswerEnumContractTests(unittest.TestCase):
    def test_answer_contract_version_matches_design_value(self):
        self.assertEqual("drawing-assistant-answer-v1", ANSWER_CONTRACT_VERSION)

    def test_answer_contract_version_is_non_empty_string(self):
        self.assertIsInstance(ANSWER_CONTRACT_VERSION, str)
        self.assertTrue(ANSWER_CONTRACT_VERSION)

    def test_answer_status_contains_all_design_values(self):
        self.assertEqual(
            {
                "answered",
                "partial",
                "clarification_required",
                "unsupported",
                "recognition_failed",
            },
            {item.value for item in AnswerStatus},
        )

    def test_answer_status_values_are_stable_english_strings(self):
        self.assertEqual("answered", AnswerStatus.ANSWERED.value)
        self.assertEqual("partial", AnswerStatus.PARTIAL.value)
        self.assertEqual("clarification_required", AnswerStatus.CLARIFICATION_REQUIRED.value)
        self.assertEqual("unsupported", AnswerStatus.UNSUPPORTED.value)
        self.assertEqual("recognition_failed", AnswerStatus.RECOGNITION_FAILED.value)

    def test_answer_status_rejects_unknown_value(self):
        with self.assertRaises(ValueError):
            AnswerStatus("not_a_status")

    def test_claim_status_contains_all_design_values(self):
        self.assertEqual(
            {
                "supported",
                "qualified",
                "conflicting",
                "formal_review_required",
                "diagnostic",
            },
            {item.value for item in ClaimStatus},
        )

    def test_claim_status_values_are_stable_english_strings(self):
        self.assertEqual("supported", ClaimStatus.SUPPORTED.value)
        self.assertEqual("qualified", ClaimStatus.QUALIFIED.value)
        self.assertEqual("conflicting", ClaimStatus.CONFLICTING.value)
        self.assertEqual("formal_review_required", ClaimStatus.FORMAL_REVIEW_REQUIRED.value)
        self.assertEqual("diagnostic", ClaimStatus.DIAGNOSTIC.value)

    def test_claim_status_rejects_unknown_value(self):
        with self.assertRaises(ValueError):
            ClaimStatus("not_a_status")

    def test_text_render_mode_contains_all_design_values(self):
        self.assertEqual(
            {"template", "constrained_text"},
            {item.value for item in TextRenderMode},
        )

    def test_text_render_mode_values_are_stable_english_strings(self):
        self.assertEqual("template", TextRenderMode.TEMPLATE.value)
        self.assertEqual("constrained_text", TextRenderMode.CONSTRAINED_TEXT.value)

    def test_text_render_mode_rejects_unknown_value(self):
        with self.assertRaises(ValueError):
            TextRenderMode("not_a_mode")

    def test_answer_and_claim_status_reason_codes_are_present(self):
        values = {item.value for item in ReasonCode}
        for expected in (
            "text_generation_failed",
            "text_output_invalid",
            "answer_validation_failed",
            "recognition_failed",
            "max_subrequests_exceeded",
            "max_page_groups_exceeded",
            "max_claims_exceeded",
            "max_citations_exceeded",
        ):
            self.assertIn(expected, values)

    def test_existing_reason_codes_are_not_removed_or_renamed(self):
        values = {item.value for item in ReasonCode}
        for expected in (
            "scope_missing",
            "result_truncated",
            "write_back_denied",
            "internal_error",
        ):
            self.assertIn(expected, values)


class ClaimContractTests(unittest.TestCase):
    def test_legacy_claim_construction_still_works(self):
        claim = Claim(claim_id="claim:1", statement="s")
        self.assertEqual("claim:1", claim.claim_id)
        self.assertIsNone(claim.subrequest_id)
        self.assertEqual((), claim.reason_codes)
        self.assertEqual((), claim.citation_ids)

    def test_new_fields_are_preserved(self):
        claim = Claim(
            claim_id="claim:2",
            statement="s",
            subrequest_id="sub:1",
            reason_codes=(ReasonCode.FORMAL_REVIEW_REQUIRED,),
            citation_ids=("citation:1", "citation:2"),
        )
        self.assertEqual("sub:1", claim.subrequest_id)
        self.assertEqual((ReasonCode.FORMAL_REVIEW_REQUIRED,), claim.reason_codes)
        self.assertEqual(("citation:1", "citation:2"), claim.citation_ids)

    def test_new_collections_are_immutable_tuples(self):
        claim = Claim(claim_id="claim:3", statement="s")
        self.assertIsInstance(claim.reason_codes, tuple)
        self.assertIsInstance(claim.citation_ids, tuple)
        self.assertEqual((), claim.reason_codes)
        self.assertEqual((), claim.citation_ids)

    def test_reason_codes_accept_stable_strings(self):
        claim = Claim(claim_id="claim:4", statement="s", reason_codes=("formal_review_required",))
        self.assertEqual((ReasonCode.FORMAL_REVIEW_REQUIRED,), claim.reason_codes)

    def test_blank_subrequest_id_is_rejected(self):
        with self.assertRaises(ValueError):
            Claim(claim_id="claim:5", statement="s", subrequest_id=" ")

    def test_non_tuple_citation_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            Claim(claim_id="claim:6", statement="s", citation_ids=["citation:1"])

    def test_empty_string_citation_id_is_rejected(self):
        with self.assertRaises(ValueError):
            Claim(claim_id="claim:7", statement="s", citation_ids=("",))

    def test_reason_codes_reject_non_tuple(self):
        with self.assertRaises(ValueError):
            Claim(claim_id="claim:8", statement="s", reason_codes="formal_review_required")

    def test_claim_is_frozen(self):
        claim = Claim(claim_id="claim:9", statement="s", citation_ids=("citation:1",))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            claim.citation_ids = ("citation:2",)


class CitationContractTests(unittest.TestCase):
    def test_legacy_citation_construction_still_works(self):
        citation = Citation(page_id="page:1", block_id="block:1")
        self.assertEqual("page:1", citation.page_id)
        self.assertIsNone(citation.citation_id)
        self.assertIsNone(citation.evidence_id)
        self.assertEqual((), citation.claim_ids)
        self.assertIsNone(citation.project_id)
        self.assertIsNone(citation.drawing_set_id)

    def test_new_fields_are_preserved(self):
        citation = Citation(
            citation_id="citation:1",
            evidence_id="evidence:1",
            claim_ids=("claim:1", "claim:2"),
            project_id="project:1",
            drawing_set_id="set:1",
            page_id="page:1",
        )
        self.assertEqual("citation:1", citation.citation_id)
        self.assertEqual("evidence:1", citation.evidence_id)
        self.assertEqual(("claim:1", "claim:2"), citation.claim_ids)
        self.assertEqual("project:1", citation.project_id)
        self.assertEqual("set:1", citation.drawing_set_id)

    def test_claim_ids_are_immutable_tuple(self):
        citation = Citation(citation_id="citation:1", evidence_id="evidence:1")
        self.assertIsInstance(citation.claim_ids, tuple)
        self.assertEqual((), citation.claim_ids)

    def test_bbox_remains_immutable_mapping(self):
        citation = Citation(bbox={"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4})
        self.assertEqual(
            {"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
            dict(citation.bbox),
        )
        with self.assertRaises(TypeError):
            citation.bbox["x_min"] = 99

    def test_new_fields_serialize_stably(self):
        citation = Citation(
            citation_id="citation:1",
            evidence_id="evidence:1",
            claim_ids=("claim:1",),
            project_id="project:1",
            drawing_set_id="set:1",
            page_id="page:1",
        )
        serialized = dataclasses.asdict(citation)
        self.assertEqual("citation:1", serialized["citation_id"])
        self.assertEqual("evidence:1", serialized["evidence_id"])
        self.assertEqual(("claim:1",), serialized["claim_ids"])
        self.assertEqual("project:1", serialized["project_id"])
        self.assertEqual("set:1", serialized["drawing_set_id"])

    def test_non_tuple_claim_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            Citation(citation_id="citation:1", evidence_id="evidence:1", claim_ids=["claim:1"])

    def test_empty_string_claim_id_is_rejected(self):
        with self.assertRaises(ValueError):
            Citation(citation_id="citation:1", evidence_id="evidence:1", claim_ids=("",))

    def test_blank_citation_id_is_rejected(self):
        with self.assertRaises(ValueError):
            Citation(citation_id=" ", evidence_id="evidence:1")

    def test_citation_is_frozen(self):
        citation = Citation(citation_id="citation:1", evidence_id="evidence:1")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            citation.evidence_id = "evidence:2"


class SubanswerContractTests(unittest.TestCase):
    def test_subanswer_carries_all_contract_fields(self):
        subanswer = Subanswer(
            subrequest_id="sub:1",
            question_type="page_summary",
            scope=AssistantScope(page_id="page:1"),
            status=AnswerStatus.ANSWERED,
            claim_ids=("claim:1",),
            citation_ids=("citation:1",),
            warnings=("warning",),
            unsupported_parts=("ocr",),
        )
        self.assertEqual("sub:1", subanswer.subrequest_id)
        self.assertEqual("page_summary", subanswer.question_type)
        self.assertEqual("page:1", subanswer.scope.page_id)
        self.assertEqual(AnswerStatus.ANSWERED, subanswer.status)
        self.assertEqual(("claim:1",), subanswer.claim_ids)
        self.assertEqual(("citation:1",), subanswer.citation_ids)
        self.assertEqual(("warning",), subanswer.warnings)
        self.assertEqual(("ocr",), subanswer.unsupported_parts)

    def test_default_collections_are_empty_tuples(self):
        subanswer = Subanswer(subrequest_id="sub:1", question_type="page_summary")
        self.assertEqual((), subanswer.claim_ids)
        self.assertEqual((), subanswer.citation_ids)
        self.assertEqual((), subanswer.warnings)
        self.assertEqual((), subanswer.unsupported_parts)

    def test_status_accepts_stable_string(self):
        subanswer = Subanswer(
            subrequest_id="sub:1",
            question_type="page_summary",
            status="answered",
        )
        self.assertEqual(AnswerStatus.ANSWERED, subanswer.status)

    def test_empty_subrequest_id_is_rejected(self):
        with self.assertRaises(ValueError):
            Subanswer(subrequest_id=" ", question_type="page_summary")

    def test_invalid_status_is_rejected(self):
        with self.assertRaises(ValueError):
            Subanswer(subrequest_id="sub:1", question_type="page_summary", status="not_a_status")

    def test_subanswer_has_no_execution_logic(self):
        subanswer = Subanswer(subrequest_id="sub:1", question_type="page_summary")
        self.assertFalse(hasattr(subanswer, "execute"))
        self.assertFalse(hasattr(subanswer, "run"))

    def test_subanswer_is_frozen(self):
        subanswer = Subanswer(subrequest_id="sub:1", question_type="page_summary")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            subanswer.claim_ids = ("claim:1",)


class MachineAnswerContractTests(unittest.TestCase):
    def test_field_order_matches_design(self):
        names = [item.name for item in dataclasses.fields(MachineAnswer)]
        self.assertEqual(
            [
                "answer_contract_version",
                "request_id",
                "question_type",
                "scope",
                "status",
                "subanswers",
                "claims",
                "citations",
                "warnings",
                "unsupported_parts",
                "recognition_run_ids",
                "follow_up_actions",
                "reason_codes",
            ],
            names,
        )

    def test_contract_version_is_required(self):
        with self.assertRaises(TypeError):
            MachineAnswer(request_id="req:1", question_type="page_summary")

    def test_request_id_and_question_type_are_required(self):
        with self.assertRaises(TypeError):
            MachineAnswer(
                answer_contract_version=ANSWER_CONTRACT_VERSION,
                question_type="page_summary",
            )

    def test_machine_answer_carries_authoritative_fields(self):
        claim = Claim(claim_id="claim:1", statement="s")
        citation = Citation(citation_id="citation:1", evidence_id="evidence:1")
        subanswer = Subanswer(subrequest_id="sub:1", question_type="page_summary", status="answered")
        machine = MachineAnswer(
            answer_contract_version=ANSWER_CONTRACT_VERSION,
            request_id="req:1",
            question_type="page_summary",
            scope=AssistantScope(page_id="page:1"),
            status=AnswerStatus.ANSWERED,
            subanswers=(subanswer,),
            claims=(claim,),
            citations=(citation,),
            recognition_run_ids=("run:1",),
            reason_codes=(ReasonCode.RESULT_TRUNCATED,),
        )
        self.assertEqual(ANSWER_CONTRACT_VERSION, machine.answer_contract_version)
        self.assertEqual("req:1", machine.request_id)
        self.assertEqual(AnswerStatus.ANSWERED, machine.status)
        self.assertEqual((subanswer,), machine.subanswers)
        self.assertEqual((claim,), machine.claims)
        self.assertEqual((citation,), machine.citations)
        self.assertEqual(("run:1",), machine.recognition_run_ids)
        self.assertEqual((ReasonCode.RESULT_TRUNCATED,), machine.reason_codes)

    def test_subanswers_reject_non_subanswer(self):
        with self.assertRaises(ValueError):
            MachineAnswer(
                answer_contract_version=ANSWER_CONTRACT_VERSION,
                request_id="req:1",
                question_type="page_summary",
                subanswers=("sub:1",),
            )

    def test_claims_reject_non_claim(self):
        with self.assertRaises(ValueError):
            MachineAnswer(
                answer_contract_version=ANSWER_CONTRACT_VERSION,
                request_id="req:1",
                question_type="page_summary",
                claims=("claim:1",),
            )

    def test_citations_reject_non_citation(self):
        with self.assertRaises(ValueError):
            MachineAnswer(
                answer_contract_version=ANSWER_CONTRACT_VERSION,
                request_id="req:1",
                question_type="page_summary",
                citations=("citation:1",),
            )

    def test_unknown_fields_are_not_accepted(self):
        with self.assertRaises(TypeError):
            MachineAnswer(
                answer_contract_version=ANSWER_CONTRACT_VERSION,
                request_id="req:1",
                question_type="page_summary",
                unknown_field="x",
            )

    def test_status_accepts_stable_string(self):
        machine = MachineAnswer(
            answer_contract_version=ANSWER_CONTRACT_VERSION,
            request_id="req:1",
            question_type="page_summary",
            status="partial",
        )
        self.assertEqual(AnswerStatus.PARTIAL, machine.status)

    def test_invalid_status_is_rejected(self):
        with self.assertRaises(ValueError):
            MachineAnswer(
                answer_contract_version=ANSWER_CONTRACT_VERSION,
                request_id="req:1",
                question_type="page_summary",
                status="not_a_status",
            )

    def test_default_collections_are_empty_tuples(self):
        machine = MachineAnswer(
            answer_contract_version=ANSWER_CONTRACT_VERSION,
            request_id="req:1",
            question_type="page_summary",
        )
        self.assertEqual((), machine.subanswers)
        self.assertEqual((), machine.claims)
        self.assertEqual((), machine.citations)
        self.assertEqual((), machine.warnings)
        self.assertEqual((), machine.unsupported_parts)
        self.assertEqual((), machine.recognition_run_ids)
        self.assertEqual((), machine.follow_up_actions)
        self.assertEqual((), machine.reason_codes)


class AnswerPackageContractTests(unittest.TestCase):
    def test_legacy_construction_still_works(self):
        package = AnswerPackage(request_id="req:1", question_type="page_summary")
        self.assertEqual(ANSWER_CONTRACT_VERSION, package.answer_contract_version)
        self.assertEqual((), package.subanswers)
        self.assertEqual((), package.reason_codes)
        self.assertEqual(TextRenderMode.TEMPLATE, package.render_mode)

    def test_new_fields_are_preserved(self):
        subanswer = Subanswer(subrequest_id="sub:1", question_type="page_summary")
        package = AnswerPackage(
            request_id="req:1",
            question_type="page_summary",
            answer_contract_version=ANSWER_CONTRACT_VERSION,
            subanswers=(subanswer,),
            reason_codes=(ReasonCode.RESULT_TRUNCATED,),
            render_mode="constrained_text",
        )
        self.assertEqual(ANSWER_CONTRACT_VERSION, package.answer_contract_version)
        self.assertEqual((subanswer,), package.subanswers)
        self.assertEqual((ReasonCode.RESULT_TRUNCATED,), package.reason_codes)
        self.assertEqual(TextRenderMode.CONSTRAINED_TEXT, package.render_mode)

    def test_machine_answer_accepts_mapping(self):
        package = AnswerPackage(
            request_id="req:1",
            question_type="page_summary",
            machine_answer={"summary": "..."},
        )
        self.assertEqual({"summary": "..."}, package.machine_answer)

    def test_machine_answer_accepts_machine_answer_dto(self):
        machine = MachineAnswer(
            answer_contract_version=ANSWER_CONTRACT_VERSION,
            request_id="req:1",
            question_type="page_summary",
        )
        package = AnswerPackage(
            request_id="req:1",
            question_type="page_summary",
            machine_answer=machine,
        )
        self.assertIs(machine, package.machine_answer)

    def test_render_mode_accepts_stable_string(self):
        package = AnswerPackage(
            request_id="req:1",
            question_type="page_summary",
            render_mode="constrained_text",
        )
        self.assertEqual(TextRenderMode.CONSTRAINED_TEXT, package.render_mode)

    def test_invalid_render_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            AnswerPackage(
                request_id="req:1",
                question_type="page_summary",
                render_mode="not_a_mode",
            )

    def test_subanswers_reject_non_subanswer(self):
        with self.assertRaises(ValueError):
            AnswerPackage(
                request_id="req:1",
                question_type="page_summary",
                subanswers=("sub:1",),
            )

    def test_package_is_frozen(self):
        package = AnswerPackage(request_id="req:1", question_type="page_summary")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            package.reason_codes = (ReasonCode.RESULT_TRUNCATED,)


class AnswerGenerationInputContractTests(unittest.TestCase):
    def test_recognition_failure_carries_minimal_fields(self):
        failure = RecognitionFailure(
            page_id="page:1",
            target_ids=("target:1",),
            reason_code=ReasonCode.RECOGNITION_FAILED,
            message="recognition failed for page",
        )
        self.assertEqual("page:1", failure.page_id)
        self.assertEqual(("target:1",), failure.target_ids)
        self.assertEqual(ReasonCode.RECOGNITION_FAILED, failure.reason_code)
        self.assertEqual("recognition failed for page", failure.message)

    def test_recognition_failure_has_no_traceback_or_provider_fields(self):
        names = {item.name for item in dataclasses.fields(RecognitionFailure)}
        self.assertFalse(
            names
            & {
                "traceback",
                "provider_response",
                "raw_response",
                "credentials",
                "api_key",
            }
        )

    def test_recognition_failure_rejects_non_tuple_target_ids(self):
        with self.assertRaises(ValueError):
            RecognitionFailure(
                page_id="page:1",
                reason_code=ReasonCode.RECOGNITION_FAILED,
                message="m",
                target_ids=["target:1"],
            )

    def test_recognition_failure_rejects_invalid_reason_code(self):
        with self.assertRaises(ValueError):
            RecognitionFailure(page_id="page:1", reason_code="not_a_code", message="m")

    def test_answer_generation_policy_defaults_are_read_only(self):
        policy = AnswerGenerationPolicy()
        self.assertFalse(policy.enable_constrained_text)
        self.assertIsNone(policy.max_claims)
        self.assertIsNone(policy.max_citations)
        self.assertIsNone(policy.max_text_length)
        self.assertIsNone(policy.text_generation_timeout_seconds)

    def test_answer_generation_policy_resource_limits_must_be_positive(self):
        with self.assertRaises(ValueError):
            AnswerGenerationPolicy(max_claims=0)
        with self.assertRaises(ValueError):
            AnswerGenerationPolicy(max_citations=-1)

    def test_answer_generation_policy_has_no_write_back_or_fact_override_fields(self):
        names = {item.name for item in dataclasses.fields(AnswerGenerationPolicy)}
        self.assertFalse(
            names
            & {
                "allow_write_back",
                "write_back",
                "fact_kind",
                "status_override",
            }
        )

    def test_answer_generation_request_carries_required_inputs(self):
        request = AssistantRequest(request_id="req:1", question="q")
        question_result = QuestionUnderstandingResult(
            request_id="req:1",
            question_type="page_summary",
        )
        failure = RecognitionFailure(reason_code=ReasonCode.RECOGNITION_FAILED, message="m")
        generation_request = AnswerGenerationRequest(
            assistant_request=request,
            question_result=question_result,
            subrequest_id="sub:1",
            stage_warnings=("w",),
            recognition_failures=(failure,),
        )
        self.assertIs(request, generation_request.assistant_request)
        self.assertIs(question_result, generation_request.question_result)
        self.assertIsNone(generation_request.evidence_bundle)
        self.assertEqual("sub:1", generation_request.subrequest_id)
        self.assertEqual(("w",), generation_request.stage_warnings)
        self.assertEqual((failure,), generation_request.recognition_failures)

    def test_answer_generation_request_rejects_wrong_assistant_request(self):
        question_result = QuestionUnderstandingResult(
            request_id="req:1",
            question_type="page_summary",
        )
        with self.assertRaises(ValueError):
            AnswerGenerationRequest(assistant_request="req:1", question_result=question_result)

    def test_answer_generation_request_rejects_non_tuple_recognition_failures(self):
        request = AssistantRequest(request_id="req:1", question="q")
        question_result = QuestionUnderstandingResult(
            request_id="req:1",
            question_type="page_summary",
        )
        with self.assertRaises(ValueError):
            AnswerGenerationRequest(
                assistant_request=request,
                question_result=question_result,
                recognition_failures=(object(),),
            )

    def test_answer_generation_request_rejects_blank_subrequest_id(self):
        request = AssistantRequest(request_id="req:1", question="q")
        question_result = QuestionUnderstandingResult(
            request_id="req:1",
            question_type="page_summary",
        )
        with self.assertRaises(ValueError):
            AnswerGenerationRequest(
                assistant_request=request,
                question_result=question_result,
                subrequest_id=" ",
            )


class AssistantExecutionPolicyTests(unittest.TestCase):
    def test_defaults_are_read_only_and_bounded(self):
        policy = AssistantExecutionPolicy()
        self.assertIsInstance(policy.retrieval_policy, RetrievalPolicy)
        self.assertIsInstance(policy.recognition_policy, RecognitionPolicy)
        self.assertFalse(policy.enable_constrained_text)
        self.assertIsNone(policy.max_subrequests)
        self.assertIsNone(policy.max_page_groups)
        self.assertIsNone(policy.max_claims)
        self.assertIsNone(policy.max_citations)

    def test_no_write_back_field_exists(self):
        names = {item.name for item in dataclasses.fields(AssistantExecutionPolicy)}
        self.assertFalse(names & {"allow_write_back", "write_back", "write_back_policy"})

    def test_policy_has_no_independent_recognition_authorization(self):
        names = {item.name for item in dataclasses.fields(AssistantExecutionPolicy)}
        self.assertNotIn("allow_recognition", names)
        self.assertNotIn("allow_write_back", names)

    def test_invalid_limits_are_rejected(self):
        for kwargs in (
            {"max_subrequests": 0},
            {"max_page_groups": -1},
            {"max_claims": 0},
            {"max_citations": -2},
        ):
            with self.assertRaises(ValueError):
                AssistantExecutionPolicy(**kwargs)

    def test_custom_policies_are_preserved(self):
        retrieval = RetrievalPolicy(default_limit=10, max_limit=20)
        recognition = RecognitionPolicy(allow_recognition=False, max_targets=5)
        policy = AssistantExecutionPolicy(
            retrieval_policy=retrieval,
            recognition_policy=recognition,
            enable_constrained_text=True,
            max_subrequests=4,
        )
        self.assertIs(retrieval, policy.retrieval_policy)
        self.assertIs(recognition, policy.recognition_policy)
        self.assertTrue(policy.enable_constrained_text)
        self.assertEqual(4, policy.max_subrequests)

    def test_no_fact_level_or_status_override_field(self):
        names = {item.name for item in dataclasses.fields(AssistantExecutionPolicy)}
        self.assertFalse(names & {"fact_kind", "status_override", "claim_status_override"})

    def test_policy_is_frozen(self):
        policy = AssistantExecutionPolicy()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            policy.max_subrequests = 10


if __name__ == "__main__":
    unittest.main()
