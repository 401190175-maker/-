"""Tests for question understanding trace builder."""

import unittest

from drawing_graph.assistant_models import ReasonCode, TraceRecord
from drawing_graph.assistant_question_trace import QuestionUnderstandingTraceBuilder


class QuestionUnderstandingTraceBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = QuestionUnderstandingTraceBuilder()

    def test_builds_event_with_stable_fields(self):
        event = self.builder.build_event(
            request_id="req:1",
            stage="route",
            question_type="page_summary",
            confidence=0.9,
            reason_codes=(ReasonCode.SCOPE_MISSING,),
            details={"rule_id": "rule:page_summary"},
        )
        self.assertEqual("req:1", event.request_id)
        self.assertEqual("route", event.stage)
        self.assertEqual("page_summary", event.question_type)
        self.assertEqual(0.9, event.confidence)
        self.assertEqual((ReasonCode.SCOPE_MISSING,), event.reason_codes)
        self.assertEqual({"rule_id": "rule:page_summary"}, dict(event.details))

    def test_event_ids_are_unique_across_calls(self):
        first = self.builder.build_event("req:1", "normalize", "page_summary")
        second = self.builder.build_event("req:1", "scope", "page_summary")
        self.assertNotEqual(first.event_id, second.event_id)

    def test_event_can_be_placed_in_trace_record_module_events(self):
        event = self.builder.build_event("req:1", "route", "page_summary")
        trace = TraceRecord(request_id="req:1", question="q", module_events=(event,))
        self.assertIs(event, trace.module_events[0])

    def test_details_sanitize_sensitive_fields(self):
        event = self.builder.build_event(
            "req:1",
            "model",
            "page_summary",
            details={
                "authorization": "Bearer secret",
                "traceback": "Traceback ...",
                "cypher": "return all nodes",
                "api_key": "sk-123",
                "prompt_version": "v1",
            },
        )
        details = dict(event.details)
        self.assertNotIn("authorization", details)
        self.assertNotIn("traceback", details)
        self.assertNotIn("cypher", details)
        self.assertNotIn("api_key", details)
        self.assertEqual("v1", details["prompt_version"])

    def test_details_redact_sensitive_string_values(self):
        event = self.builder.build_event(
            "req:1",
            "model",
            "page_summary",
            details={"message": "Authorization: Bearer abc", "note": "普通说明"},
        )
        details = dict(event.details)
        self.assertEqual("[redacted]", details["message"])
        self.assertEqual("普通说明", details["note"])


if __name__ == "__main__":
    unittest.main()
