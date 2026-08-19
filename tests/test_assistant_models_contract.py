"""Contract tests for the product assistant public contract module."""

import dataclasses
import unittest

from drawing_graph.assistant_models import (
    AnswerPackage,
    AssistantRequest,
    AssistantScope,
    AssistantSubrequest,
    Citation,
    Claim,
    CONTRACT_VERSION,
    EvidenceItem,
    EvidenceRef,
    EvidenceType,
    EvidenceRequirement,
    FactKind,
    FeedbackEvent,
    FreshnessPolicy,
    MissingEvidence,
    QuestionUnderstandingResult,
    RETRIEVAL_CONTRACT_VERSION,
    ReasonCode,
    RetrievalBundle,
    RetrievalPolicy,
    RetrievalPlan,
    RetrievalStatus,
    RetrievalStep,
    SourceCallRecord,
    TraceRecord,
)


class ContractVersionTests(unittest.TestCase):
    def test_contract_versions_match_design_values(self):
        self.assertEqual("drawing-assistant-contract-v1", CONTRACT_VERSION)
        self.assertEqual("drawing-assistant-retrieval-v1", RETRIEVAL_CONTRACT_VERSION)

    def test_contract_versions_are_non_empty_strings(self):
        self.assertIsInstance(CONTRACT_VERSION, str)
        self.assertIsInstance(RETRIEVAL_CONTRACT_VERSION, str)
        self.assertTrue(CONTRACT_VERSION)
        self.assertTrue(RETRIEVAL_CONTRACT_VERSION)


class FactKindTests(unittest.TestCase):
    def test_fact_kind_contains_all_required_kinds(self):
        self.assertEqual(
            {
                "source_fact",
                "derived_relation",
                "semantic_observation",
                "semantic_interpretation",
                "candidate_relation",
                "formal_relation",
                "diagnostic",
                "unsupported",
            },
            {item.value for item in FactKind},
        )

    def test_fact_kind_values_are_stable_strings(self):
        self.assertEqual("source_fact", FactKind.SOURCE_FACT.value)
        self.assertEqual("formal_relation", FactKind.FORMAL_RELATION.value)
        self.assertEqual("unsupported", FactKind.UNSUPPORTED.value)


class RetrievalStatusTests(unittest.TestCase):
    def test_retrieval_status_contains_all_required_values(self):
        self.assertEqual(
            {"ok", "partial", "error", "unsupported", "clarification_required"},
            {item.value for item in RetrievalStatus},
        )

    def test_retrieval_status_values_are_stable_strings(self):
        self.assertEqual("ok", RetrievalStatus.OK.value)
        self.assertEqual("clarification_required", RetrievalStatus.CLARIFICATION_REQUIRED.value)


class EvidenceTypeTests(unittest.TestCase):
    def test_evidence_type_covers_all_planned_capabilities(self):
        self.assertEqual(
            {
                "project_drawing_sets",
                "drawing_set_pages",
                "page_source_facts",
                "block_trace",
                "block_relations",
                "text_observations",
                "structured_interpretations",
                "semantic_payload",
                "candidate_relations",
                "section_matches",
            },
            {item.value for item in EvidenceType},
        )

    def test_evidence_type_values_are_stable_strings(self):
        self.assertEqual("page_source_facts", EvidenceType.PAGE_SOURCE_FACTS.value)
        self.assertEqual("section_matches", EvidenceType.SECTION_MATCHES.value)


class ReasonCodeTests(unittest.TestCase):
    def test_reason_code_contains_all_required_values(self):
        self.assertEqual(
            {
                "scope_missing",
                "scope_conflict",
                "unsupported_evidence_type",
                "target_not_found",
                "empty_result",
                "facade_call_failed",
                "payload_unavailable",
                "result_truncated",
                "ambiguous_reference",
                "ambiguous_question_type",
                "multi_intent_ambiguous",
                "unsupported_question",
                "model_output_invalid",
                "evidence_complete",
                "evidence_missing",
                "observation_missing",
                "interpretation_missing",
                "evidence_stale",
                "image_changed",
                "bbox_changed",
                "model_profile_changed",
                "prompt_version_changed",
                "contract_version_changed",
                "preprocessing_version_changed",
                "normalization_rule_changed",
                "evidence_conflict",
                "status_insufficient",
                "evidence_kind_mismatch",
                "recognition_forbidden",
                "budget_exceeded",
                "latency_exceeded",
                "estimate_unavailable",
                "formal_review_required",
                "unsupported_generation",
                "cache_key_unavailable",
                "target_location_missing",
                "fusion_input_invalid",
                "evidence_projection_failed",
                "evidence_normalization_failed",
                "conflict_policy_invalid",
                "claim_support_failed",
                "cache_closure_inconsistent",
                "write_back_denied",
                "persistence_unavailable",
                "write_back_partial",
                "lineage_write_failed",
                "internal_error",
                "recognition_scope_mismatch",
                "text_generation_failed",
                "text_output_invalid",
                "answer_validation_failed",
                "recognition_failed",
                "max_subrequests_exceeded",
                "max_page_groups_exceeded",
                "max_claims_exceeded",
                "max_citations_exceeded",
            },
            {item.value for item in ReasonCode},
        )

    def test_reason_code_values_are_stable_strings(self):
        self.assertEqual("scope_missing", ReasonCode.SCOPE_MISSING.value)
        self.assertEqual("result_truncated", ReasonCode.RESULT_TRUNCATED.value)


class AssistantScopeTests(unittest.TestCase):
    def test_empty_scope_is_constructible_with_all_none(self):
        scope = AssistantScope()
        self.assertIsNone(scope.project_id)
        self.assertIsNone(scope.drawing_set_id)
        self.assertIsNone(scope.page_id)
        self.assertIsNone(scope.block_id)
        self.assertIsNone(scope.element_id)
        self.assertIsNone(scope.cross_section_id)
        self.assertIsNone(scope.table_id)
        self.assertIsNone(scope.table_caption_id)
        self.assertIsNone(scope.claim_id)

    def test_scope_carries_all_stable_business_ids(self):
        scope = AssistantScope(
            project_id="project:1",
            drawing_set_id="set:1",
            page_id="page:1",
            block_id="block:1",
            element_id="element:1",
            cross_section_id="section:1",
            table_id="table:1",
            table_caption_id="caption:1",
            claim_id="claim:1",
        )
        self.assertEqual("page:1", scope.page_id)
        self.assertEqual("claim:1", scope.claim_id)

    def test_scope_serializes_to_stable_mapping(self):
        scope = AssistantScope(page_id="page:1", block_id="block:1")
        serialized = dataclasses.asdict(scope)
        self.assertEqual("page:1", serialized["page_id"])
        self.assertEqual("block:1", serialized["block_id"])
        self.assertIsNone(serialized["project_id"])


class AssistantRequestTests(unittest.TestCase):
    def test_default_request_is_read_only_with_zh_cn_language(self):
        request = AssistantRequest(request_id="req:1", question="该页面包含哪些图块？")
        self.assertFalse(request.allow_write_back)
        self.assertTrue(request.allow_recognition)
        self.assertEqual("zh-CN", request.language)
        self.assertIsNone(request.conversation_context)
        self.assertIsNone(request.scope_hint)
        self.assertIsNone(request.answer_format)

    def test_allow_write_back_never_becomes_true_from_question_text(self):
        request = AssistantRequest(
            request_id="req:2",
            question="请把这段结论写入 Neo4j 并提升为正式关系",
        )
        self.assertFalse(request.allow_write_back)

    def test_scope_hint_is_preserved_on_request(self):
        scope = AssistantScope(page_id="page:9")
        request = AssistantRequest(request_id="req:3", question="q", scope_hint=scope)
        self.assertEqual("page:9", request.scope_hint.page_id)


class AssistantSubrequestTests(unittest.TestCase):
    def test_subrequest_carries_question_type_and_scope(self):
        subrequest = AssistantSubrequest(
            subrequest_id="sub:1",
            question_type="page_summary",
            scope=AssistantScope(page_id="page:1"),
            confidence=0.9,
        )
        self.assertEqual("sub:1", subrequest.subrequest_id)
        self.assertEqual("page_summary", subrequest.question_type)
        self.assertEqual("page:1", subrequest.scope.page_id)

    def test_default_collections_are_not_shared_between_subrequests(self):
        first = AssistantSubrequest(subrequest_id="sub:1", question_type="page_summary")
        second = AssistantSubrequest(subrequest_id="sub:2", question_type="block_relations")
        self.assertEqual((), first.ambiguities)
        self.assertEqual((), first.unsupported_parts)
        self.assertEqual((), second.ambiguities)
        self.assertEqual((), second.unsupported_parts)
        self.assertIsInstance(first.ambiguities, tuple)
        self.assertIsInstance(first.unsupported_parts, tuple)

    def test_explicit_ambiguities_are_kept_per_subrequest(self):
        first = AssistantSubrequest(
            subrequest_id="sub:1",
            question_type="page_summary",
            ambiguities=("ambiguous",),
        )
        second = AssistantSubrequest(subrequest_id="sub:2", question_type="page_summary")
        self.assertEqual(("ambiguous",), first.ambiguities)
        self.assertEqual((), second.ambiguities)


class QuestionUnderstandingResultTests(unittest.TestCase):
    def test_single_intent_allows_empty_subrequests(self):
        result = QuestionUnderstandingResult(
            request_id="req:1",
            question_type="page_summary",
            scope=AssistantScope(page_id="page:1"),
        )
        self.assertEqual("req:1", result.request_id)
        self.assertEqual((), result.subrequests)
        self.assertEqual((), result.ambiguities)
        self.assertEqual((), result.unsupported_parts)

    def test_multi_intent_subrequests_keep_parent_request_traceability(self):
        subrequests = (
            AssistantSubrequest(subrequest_id="sub:1", question_type="page_summary"),
            AssistantSubrequest(subrequest_id="sub:2", question_type="candidate_relations"),
        )
        result = QuestionUnderstandingResult(
            request_id="req:9",
            question_type="multi_intent",
            scope=AssistantScope(page_id="page:1"),
            subrequests=subrequests,
        )
        self.assertEqual("req:9", result.request_id)
        self.assertEqual("sub:1", result.subrequests[0].subrequest_id)
        self.assertEqual("sub:2", result.subrequests[1].subrequest_id)

    def test_default_collections_are_not_shared_between_results(self):
        first = QuestionUnderstandingResult(request_id="req:1", question_type="page_summary")
        second = QuestionUnderstandingResult(request_id="req:2", question_type="page_summary")
        self.assertEqual((), first.ambiguities)
        self.assertEqual((), first.unsupported_parts)
        self.assertEqual((), second.ambiguities)
        self.assertEqual((), second.unsupported_parts)
        self.assertIsInstance(first.ambiguities, tuple)
        self.assertIsInstance(first.unsupported_parts, tuple)

    def test_explicit_unsupported_parts_are_kept_per_result(self):
        first = QuestionUnderstandingResult(
            request_id="req:1",
            question_type="page_summary",
            unsupported_parts=("ocr",),
        )
        second = QuestionUnderstandingResult(request_id="req:2", question_type="page_summary")
        self.assertEqual(("ocr",), first.unsupported_parts)
        self.assertEqual((), second.unsupported_parts)


class FreshnessPolicyTests(unittest.TestCase):
    def test_freshness_policy_contains_all_required_values(self):
        self.assertEqual(
            {"any", "current_image", "current_prompt", "current_contract"},
            {item.value for item in FreshnessPolicy},
        )


class EvidenceRequirementTests(unittest.TestCase):
    def test_defaults_are_required_without_payload_and_without_model_generation(self):
        requirement = EvidenceRequirement(
            requirement_id="req-ev:1",
            evidence_type=EvidenceType.PAGE_SOURCE_FACTS,
            target_scope=AssistantScope(page_id="page:1"),
        )
        self.assertTrue(requirement.required)
        self.assertFalse(requirement.include_payload)
        self.assertFalse(requirement.allow_model_generation)
        self.assertEqual(FreshnessPolicy.ANY, requirement.freshness_policy)
        self.assertIsNone(requirement.minimum_status)
        self.assertIsNone(requirement.limit)
        self.assertIsNone(requirement.payload_ref)

    def test_model_generation_authorization_does_not_change_write_back(self):
        requirement = EvidenceRequirement(
            requirement_id="req-ev:2",
            evidence_type=EvidenceType.TEXT_OBSERVATIONS,
            target_scope=AssistantScope(page_id="page:1"),
            allow_model_generation=True,
        )
        request = AssistantRequest(request_id="req:1", question="q")
        self.assertTrue(requirement.allow_model_generation)
        self.assertFalse(request.allow_write_back)

    def test_limit_cap_is_enforced_by_policy_not_by_requirement(self):
        requirement = EvidenceRequirement(
            requirement_id="req-ev:3",
            evidence_type=EvidenceType.PAGE_SOURCE_FACTS,
            target_scope=AssistantScope(page_id="page:1"),
            limit=1000,
        )
        policy = RetrievalPolicy(default_limit=100, max_limit=100)
        self.assertEqual(1000, requirement.limit)
        self.assertEqual(100, policy.max_limit)

    def test_payload_ref_is_optional_and_preserved(self):
        requirement = EvidenceRequirement(
            requirement_id="req-ev:4",
            evidence_type=EvidenceType.SEMANTIC_PAYLOAD,
            target_scope=AssistantScope(page_id="page:1"),
            include_payload=True,
            payload_ref="payload:1",
        )
        self.assertEqual("payload:1", requirement.payload_ref)


class RetrievalPolicyTests(unittest.TestCase):
    def test_default_policy_is_bounded_and_payload_off(self):
        policy = RetrievalPolicy()
        self.assertEqual(100, policy.default_limit)
        self.assertEqual(500, policy.max_limit)
        self.assertFalse(policy.include_payload_by_default)


class RetrievalStepTests(unittest.TestCase):
    def test_step_carries_facade_method_scope_and_parameters(self):
        step = RetrievalStep(
            step_id="step:1",
            facade_method="get_page_source_facts",
            scope=AssistantScope(page_id="page:1"),
            parameters={"page_id": "page:1", "include_image_meta": True},
            required=True,
            depends_on=("step:0",),
            limit=50,
            include_payload=False,
            requirement_ids=("req-ev:1",),
            dedupe_key="get_page_source_facts:page:1",
        )
        self.assertEqual("step:1", step.step_id)
        self.assertEqual("get_page_source_facts", step.facade_method)
        self.assertEqual("page:1", step.parameters["page_id"])
        self.assertEqual(("step:0",), step.depends_on)
        self.assertEqual(("req-ev:1",), step.requirement_ids)
        self.assertEqual(50, step.limit)
        self.assertFalse(step.include_payload)

    def test_step_parameters_with_plain_values_are_readable_as_mapping(self):
        step = RetrievalStep(
            step_id="step:2",
            facade_method="list_drawing_sets",
            parameters={"project_id": "project:1"},
        )
        self.assertEqual({"project_id": "project:1"}, dict(step.parameters))

    def test_dependency_and_requirement_defaults_are_immutable_tuples(self):
        first = RetrievalStep(step_id="step:1", facade_method="get_block_trace")
        second = RetrievalStep(step_id="step:2", facade_method="get_block_trace")
        self.assertEqual((), first.depends_on)
        self.assertEqual((), first.requirement_ids)
        self.assertIsInstance(first.depends_on, tuple)
        self.assertIsInstance(first.requirement_ids, tuple)
        self.assertEqual((), second.depends_on)
        self.assertEqual((), second.requirement_ids)


class RetrievalPlanTests(unittest.TestCase):
    def test_plan_carries_request_and_step_list(self):
        step = RetrievalStep(step_id="step:1", facade_method="get_page_source_facts")
        plan = RetrievalPlan(
            request_id="req:1",
            subrequest_id="sub:1",
            steps=(step,),
            dedupe_keys=("get_page_source_facts:page:1",),
        )
        self.assertEqual("req:1", plan.request_id)
        self.assertEqual("sub:1", plan.subrequest_id)
        self.assertEqual(("step:1",), tuple(item.step_id for item in plan.steps))
        self.assertEqual(("get_page_source_facts:page:1",), plan.dedupe_keys)

    def test_plan_defaults_are_empty_tuples(self):
        plan = RetrievalPlan(request_id="req:1")
        self.assertEqual((), plan.steps)
        self.assertEqual((), plan.dedupe_keys)
        self.assertEqual((), plan.warnings)


class SourceCallRecordTests(unittest.TestCase):
    def test_successful_call_record_carries_status_and_count(self):
        record = SourceCallRecord(
            source_call_id="call:1",
            step_id="step:1",
            facade_method="get_block_trace",
            status="ok",
            result_count=1,
        )
        self.assertEqual("call:1", record.source_call_id)
        self.assertEqual("ok", record.status.value)
        self.assertEqual(1, record.result_count)
        self.assertIsNone(record.reason_code)
        self.assertIsNone(record.warning)

    def test_failed_call_record_carries_reason_code(self):
        record = SourceCallRecord(
            source_call_id="call:2",
            step_id="step:2",
            facade_method="get_block_trace",
            status="error",
            reason_code=ReasonCode.FACADE_CALL_FAILED,
        )
        self.assertEqual(ReasonCode.FACADE_CALL_FAILED, record.reason_code)
        self.assertEqual("error", record.status.value)


class EvidenceRefTests(unittest.TestCase):
    def test_evidence_ref_carries_ids_bbox_and_rule_version(self):
        ref = EvidenceRef(
            project_id="project:1",
            drawing_set_id="set:1",
            page_id="page:1",
            block_id="block:1",
            element_id="element:1",
            bbox={"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
            recognition_run_id="run:1",
            payload_ref="payload:1",
            rule_version="v1",
        )
        self.assertEqual("page:1", ref.page_id)
        self.assertEqual("run:1", ref.recognition_run_id)
        self.assertEqual({"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4}, dict(ref.bbox))
        self.assertEqual("v1", ref.rule_version)

    def test_evidence_ref_defaults_are_none(self):
        ref = EvidenceRef()
        self.assertIsNone(ref.page_id)
        self.assertIsNone(ref.bbox)
        self.assertIsNone(ref.payload_ref)


class EvidenceItemTests(unittest.TestCase):
    def test_evidence_item_carries_fact_kind_scope_and_refs(self):
        item = EvidenceItem(
            evidence_id="evidence:1",
            fact_kind=FactKind.SOURCE_FACT,
            scope=AssistantScope(page_id="page:1"),
            value={"page_id": "page:1"},
            source_call_id="call:1",
            evidence_refs=(EvidenceRef(page_id="page:1"),),
        )
        self.assertEqual("evidence:1", item.evidence_id)
        self.assertEqual(FactKind.SOURCE_FACT, item.fact_kind)
        self.assertEqual("page:1", item.scope.page_id)
        self.assertEqual("call:1", item.source_call_id)
        self.assertEqual(1, len(item.evidence_refs))

    def test_evidence_item_accepts_stable_fact_kind_string(self):
        item = EvidenceItem(
            evidence_id="evidence:2",
            fact_kind="candidate_relation",
            value={},
        )
        self.assertEqual(FactKind.CANDIDATE_RELATION, item.fact_kind)


class MissingEvidenceTests(unittest.TestCase):
    def test_missing_evidence_carries_reason_code_and_message(self):
        missing = MissingEvidence(
            requirement_id="req-ev:1",
            evidence_type=EvidenceType.PAGE_SOURCE_FACTS,
            target_scope=AssistantScope(page_id="page:1"),
            reason_code=ReasonCode.EMPTY_RESULT,
            message="page source facts were not found",
        )
        self.assertEqual("req-ev:1", missing.requirement_id)
        self.assertEqual(EvidenceType.PAGE_SOURCE_FACTS, missing.evidence_type)
        self.assertEqual(ReasonCode.EMPTY_RESULT, missing.reason_code)


class RetrievalBundleTests(unittest.TestCase):
    def test_candidate_and_formal_evidence_go_to_their_own_buckets(self):
        candidate = EvidenceItem(
            evidence_id="evidence:candidate:1",
            fact_kind=FactKind.CANDIDATE_RELATION,
            value={},
        )
        formal = EvidenceItem(
            evidence_id="evidence:formal:1",
            fact_kind=FactKind.FORMAL_RELATION,
            value={},
        )
        bundle = RetrievalBundle(
            request_id="req:1",
            candidate_relations=(candidate,),
            formal_relations=(formal,),
        )
        self.assertEqual(("evidence:candidate:1",), tuple(item.evidence_id for item in bundle.candidate_relations))
        self.assertEqual(("evidence:formal:1",), tuple(item.evidence_id for item in bundle.formal_relations))
        self.assertEqual(RetrievalStatus.OK, bundle.status)

    def test_candidate_evidence_cannot_be_placed_in_formal_bucket(self):
        candidate = EvidenceItem(
            evidence_id="evidence:candidate:2",
            fact_kind=FactKind.CANDIDATE_RELATION,
            value={},
        )
        with self.assertRaises(ValueError):
            RetrievalBundle(request_id="req:2", formal_relations=(candidate,))

    def test_formal_evidence_cannot_be_placed_in_candidate_bucket(self):
        formal = EvidenceItem(
            evidence_id="evidence:formal:2",
            fact_kind=FactKind.FORMAL_RELATION,
            value={},
        )
        with self.assertRaises(ValueError):
            RetrievalBundle(request_id="req:3", candidate_relations=(formal,))


class ClaimTests(unittest.TestCase):
    def test_claim_carries_evidence_ids_and_fact_kinds(self):
        claim = Claim(
            claim_id="claim:1",
            statement="该图块包含一个标题",
            claim_type="derived",
            status="supported",
            confidence=0.9,
            evidence_ids=("evidence:1",),
            fact_kinds=(FactKind.DERIVED_RELATION,),
            scope=AssistantScope(page_id="page:1"),
            qualifiers=("same_page",),
        )
        self.assertEqual("claim:1", claim.claim_id)
        self.assertEqual(("evidence:1",), claim.evidence_ids)
        self.assertEqual((FactKind.DERIVED_RELATION,), claim.fact_kinds)
        self.assertEqual(("same_page",), claim.qualifiers)

    def test_claim_defaults_are_empty_tuples(self):
        claim = Claim(claim_id="claim:2", statement="s")
        self.assertEqual((), claim.evidence_ids)
        self.assertEqual((), claim.fact_kinds)
        self.assertEqual((), claim.qualifiers)


class CitationTests(unittest.TestCase):
    def test_citation_carries_all_trace_fields(self):
        citation = Citation(
            page_id="page:1",
            block_id="block:1",
            element_id="element:1",
            bbox={"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
            observation_id="obs:1",
            interpretation_id="interp:1",
            candidate_group_id="group:1",
            recognition_run_id="run:1",
            payload_ref="payload:1",
            rule_version="v1",
        )
        self.assertEqual("page:1", citation.page_id)
        self.assertEqual("obs:1", citation.observation_id)
        self.assertEqual("group:1", citation.candidate_group_id)
        self.assertEqual({"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4}, dict(citation.bbox))


class AnswerPackageTests(unittest.TestCase):
    def test_answer_package_carries_claims_and_citations(self):
        claim = Claim(claim_id="claim:1", statement="s")
        citation = Citation(page_id="page:1")
        package = AnswerPackage(
            request_id="req:1",
            question_type="page_summary",
            scope=AssistantScope(page_id="page:1"),
            status="answered",
            machine_answer={"summary": "..."},
            text_answer="文本答案",
            claims=(claim,),
            citations=(citation,),
            recognition_run_ids=("run:1",),
        )
        self.assertEqual("req:1", package.request_id)
        self.assertEqual("answered", package.status)
        self.assertEqual(("claim:1",), tuple(item.claim_id for item in package.claims))
        self.assertEqual(("run:1",), package.recognition_run_ids)

    def test_answer_package_defaults_are_empty_tuples(self):
        package = AnswerPackage(request_id="req:2", question_type="page_summary")
        self.assertEqual((), package.claims)
        self.assertEqual((), package.citations)
        self.assertEqual((), package.warnings)
        self.assertEqual((), package.unsupported_parts)
        self.assertEqual((), package.follow_up_actions)


class TraceRecordTests(unittest.TestCase):
    def test_trace_record_carries_module_events_and_retrieval_calls(self):
        call = SourceCallRecord(
            source_call_id="call:1",
            step_id="step:1",
            facade_method="get_page_source_facts",
            status="ok",
        )
        trace = TraceRecord(
            request_id="req:1",
            question="q",
            question_type="page_summary",
            scope=AssistantScope(page_id="page:1"),
            module_events=({"module": "retrieval", "status": "ok"},),
            retrieval_calls=(call,),
            recognition_run_ids=("run:1",),
            evidence_ids=("evidence:1",),
            claim_ids=("claim:1",),
            answer_status="answered",
        )
        self.assertEqual("req:1", trace.request_id)
        self.assertEqual(("call:1",), tuple(item.source_call_id for item in trace.retrieval_calls))
        self.assertEqual(("evidence:1",), trace.evidence_ids)
        self.assertEqual("answered", trace.answer_status)


class FeedbackEventTests(unittest.TestCase):
    def test_feedback_event_carries_action_and_correction(self):
        event = FeedbackEvent(
            feedback_id="feedback:1",
            request_id="req:1",
            claim_id="claim:1",
            action="reject",
            reason="证据不足",
            correction="改为候选关系",
            user_id="user:1",
            created_at="2026-08-11T00:00:00Z",
        )
        self.assertEqual("feedback:1", event.feedback_id)
        self.assertEqual("reject", event.action)
        self.assertEqual("改为候选关系", event.correction)

    def test_feedback_event_is_data_only(self):
        event = FeedbackEvent(feedback_id="feedback:2", request_id="req:2")
        self.assertIsNone(event.claim_id)
        self.assertIsNone(event.user_id)


class DataOnlyDtosTests(unittest.TestCase):
    def test_answer_contract_dtos_construct_without_side_effects(self):
        scope = AssistantScope(page_id="page:1")
        claim = Claim(claim_id="claim:1", statement="s", scope=scope)
        citation = Citation(page_id="page:1")
        package = AnswerPackage(
            request_id="req:1",
            question_type="page_summary",
            scope=scope,
            claims=(claim,),
            citations=(citation,),
        )
        trace = TraceRecord(request_id="req:1", question="q", answer_status="answered")
        event = FeedbackEvent(feedback_id="feedback:1", request_id="req:1")
        self.assertEqual("req:1", package.request_id)
        self.assertEqual("req:1", trace.request_id)
        self.assertEqual("feedback:1", event.feedback_id)


if __name__ == "__main__":
    unittest.main()
