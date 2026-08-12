"""Contract tests for question-understanding model additions."""

import unittest

from drawing_graph.assistant_models import (
    AssistantRequest,
    AssistantScope,
    ClarificationItem,
    EvidenceRequirement,
    EvidenceType,
    QuestionUnderstandingEvent,
    QuestionType,
    QuestionUnderstandingResult,
    ReasonCode,
    TraceRecord,
)


class QuestionTypeTests(unittest.TestCase):
    def test_question_type_contains_all_first_version_values(self):
        self.assertEqual(
            {
                "page_summary",
                "block_relations",
                "block_semantic_identification",
                "element_text_or_meaning",
                "candidate_relations",
                "section_matches",
                "table_caption_status",
                "drawing_diagnostic",
                "source_trace",
                "comparison",
                "clarification_required",
                "unknown_or_unsupported",
            },
            {item.value for item in QuestionType},
        )

    def test_question_type_values_are_stable_strings(self):
        self.assertEqual("page_summary", QuestionType.PAGE_SUMMARY.value)
        self.assertEqual(
            "block_semantic_identification",
            QuestionType.BLOCK_SEMANTIC_IDENTIFICATION.value,
        )
        self.assertEqual(
            "clarification_required",
            QuestionType.CLARIFICATION_REQUIRED.value,
        )
        self.assertEqual(
            "unknown_or_unsupported",
            QuestionType.UNKNOWN_OR_UNSUPPORTED.value,
        )


class ReasonCodeQuestionTests(unittest.TestCase):
    def test_reason_code_includes_question_understanding_codes(self):
        values = {item.value for item in ReasonCode}
        for expected in (
            "ambiguous_reference",
            "ambiguous_question_type",
            "multi_intent_ambiguous",
            "unsupported_question",
            "model_output_invalid",
        ):
            self.assertIn(expected, values)

    def test_existing_reason_codes_remain_stable(self):
        self.assertEqual("scope_missing", ReasonCode.SCOPE_MISSING.value)
        self.assertEqual("scope_conflict", ReasonCode.SCOPE_CONFLICT.value)


class ExistingContractCompatibilityTests(unittest.TestCase):
    def test_assistant_request_defaults_remain_read_only(self):
        request = AssistantRequest(request_id="req:1", question="q")
        self.assertFalse(request.allow_write_back)

    def test_evidence_requirement_defaults_remain_unchanged(self):
        requirement = EvidenceRequirement(
            requirement_id="req-ev:1",
            evidence_type=EvidenceType.PAGE_SOURCE_FACTS,
            target_scope=AssistantScope(page_id="page:1"),
        )
        self.assertTrue(requirement.required)
        self.assertFalse(requirement.include_payload)
        self.assertFalse(requirement.allow_model_generation)

    def test_question_understanding_result_still_consumes_stable_strings(self):
        result = QuestionUnderstandingResult(
            request_id="req:1",
            question_type="page_summary",
            scope=AssistantScope(page_id="page:1"),
        )
        self.assertEqual("page_summary", result.question_type)


class ClarificationItemTests(unittest.TestCase):
    def test_clarification_item_carries_all_contract_fields(self):
        item = ClarificationItem(
            clarification_id="clarify:1",
            reason_code=ReasonCode.SCOPE_MISSING,
            target_field="block_id",
            message="请补充图块 ID",
            allowed_scope_types=("block_id",),
            candidate_refs=("block:1", "上一张图"),
            required=True,
        )
        self.assertEqual("clarify:1", item.clarification_id)
        self.assertEqual(ReasonCode.SCOPE_MISSING, item.reason_code)
        self.assertEqual("block_id", item.target_field)
        self.assertEqual("请补充图块 ID", item.message)
        self.assertEqual(("block_id",), item.allowed_scope_types)
        self.assertEqual(("block:1", "上一张图"), item.candidate_refs)
        self.assertTrue(item.required)

    def test_clarification_item_accepts_stable_reason_code_string(self):
        item = ClarificationItem(
            clarification_id="clarify:2",
            reason_code="ambiguous_reference",
            target_field="page_id",
            message="请确认页面",
        )
        self.assertEqual(ReasonCode.AMBIGUOUS_REFERENCE, item.reason_code)

    def test_clarification_item_rejects_empty_clarification_id(self):
        with self.assertRaises(ValueError):
            ClarificationItem(
                clarification_id=" ",
                reason_code=ReasonCode.SCOPE_MISSING,
                target_field="block_id",
                message="请补充图块 ID",
            )

    def test_clarification_item_rejects_empty_reason_code(self):
        with self.assertRaises(ValueError):
            ClarificationItem(
                clarification_id="clarify:3",
                reason_code="",
                target_field="block_id",
                message="请补充图块 ID",
            )

    def test_clarification_item_rejects_empty_target_field(self):
        with self.assertRaises(ValueError):
            ClarificationItem(
                clarification_id="clarify:4",
                reason_code=ReasonCode.SCOPE_MISSING,
                target_field="",
                message="请补充图块 ID",
            )

    def test_candidate_refs_reject_neo4j_internal_ids(self):
        with self.assertRaises(ValueError):
            ClarificationItem(
                clarification_id="clarify:5",
                reason_code=ReasonCode.AMBIGUOUS_REFERENCE,
                target_field="page_id",
                message="请确认页面",
                candidate_refs=(1, 2),
            )

    def test_candidate_refs_default_to_empty_tuple(self):
        item = ClarificationItem(
            clarification_id="clarify:6",
            reason_code=ReasonCode.SCOPE_MISSING,
            target_field="block_id",
            message="请补充图块 ID",
        )
        self.assertEqual((), item.candidate_refs)
        self.assertEqual((), item.allowed_scope_types)


class QuestionUnderstandingEventTests(unittest.TestCase):
    def test_event_carries_decision_trace_fields(self):
        event = QuestionUnderstandingEvent(
            event_id="event:1",
            request_id="req:1",
            stage="route",
            question_type=QuestionType.PAGE_SUMMARY,
            confidence=0.9,
            reason_codes=(ReasonCode.SCOPE_MISSING,),
            details={"rule_id": "rule:page_summary"},
        )
        self.assertEqual("event:1", event.event_id)
        self.assertEqual("req:1", event.request_id)
        self.assertEqual("route", event.stage)
        self.assertEqual("page_summary", event.question_type)
        self.assertEqual(0.9, event.confidence)
        self.assertEqual((ReasonCode.SCOPE_MISSING,), event.reason_codes)
        self.assertEqual({"rule_id": "rule:page_summary"}, dict(event.details))

    def test_event_can_be_placed_in_trace_record_module_events(self):
        event = QuestionUnderstandingEvent(
            event_id="event:2",
            request_id="req:1",
            stage="clarify",
            question_type="clarification_required",
            reason_codes=("scope_missing",),
        )
        trace = TraceRecord(
            request_id="req:1",
            question="q",
            module_events=(event,),
        )
        self.assertIs(event, trace.module_events[0])

    def test_event_sensitive_fields_are_not_required(self):
        event = QuestionUnderstandingEvent(
            event_id="event:3",
            request_id="req:1",
            stage="normalize",
            question_type="page_summary",
        )
        self.assertIsNone(event.details)
        self.assertIsNone(event.confidence)
        self.assertEqual((), event.reason_codes)

    def test_event_accepts_reason_code_strings(self):
        event = QuestionUnderstandingEvent(
            event_id="event:4",
            request_id="req:1",
            stage="route",
            question_type="page_summary",
            reason_codes=("ambiguous_reference", "unsupported_question"),
        )
        self.assertEqual(
            (ReasonCode.AMBIGUOUS_REFERENCE, ReasonCode.UNSUPPORTED_QUESTION),
            event.reason_codes,
        )


if __name__ == "__main__":
    unittest.main()
