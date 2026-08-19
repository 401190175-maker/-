"""Tests for the product trace DTO contracts (trace models)."""

import unittest

from drawing_graph.assistant_models import (
    AssistantScope,
    FactKind,
    SemanticGapDecision,
    SourceCallRecord,
)
from drawing_graph.assistant_trace_models import (
    ClaimTrace,
    TraceCostSummary,
    TraceLatencySummary,
    TraceModuleEvent,
    TraceQueryResult,
    TraceRecord,
    TraceWriteResult,
    TraceWriteStatus,
)


class TraceModuleEventTests(unittest.TestCase):
    def test_event_carries_module_and_status(self):
        event = TraceModuleEvent(
            event_id="event:req:1:1",
            module="retrieval",
            status="ok",
            detail="3 source calls",
            reason_codes=(),
        )
        self.assertEqual("retrieval", event.module)
        self.assertEqual("ok", event.status)

    def test_event_requires_event_id_and_module(self):
        with self.assertRaises(ValueError):
            TraceModuleEvent(event_id="", module="retrieval", status="ok")
        with self.assertRaises(ValueError):
            TraceModuleEvent(event_id="event:1", module="", status="ok")


class TraceCostSummaryTests(unittest.TestCase):
    def test_cost_summary_carries_estimate(self):
        summary = TraceCostSummary(estimated_cost=1.25, currency="CNY", selected_target_count=2)
        self.assertEqual(1.25, summary.estimated_cost)
        self.assertEqual("CNY", summary.currency)
        self.assertEqual(2, summary.selected_target_count)

    def test_cost_summary_rejects_negative(self):
        with self.assertRaises(ValueError):
            TraceCostSummary(estimated_cost=-1.0)


class TraceLatencySummaryTests(unittest.TestCase):
    def test_latency_summary_carries_estimate(self):
        summary = TraceLatencySummary(estimated_latency_ms=500.0)
        self.assertEqual(500.0, summary.estimated_latency_ms)

    def test_latency_summary_rejects_negative(self):
        with self.assertRaises(ValueError):
            TraceLatencySummary(estimated_latency_ms=-1.0)


class TraceRecordTests(unittest.TestCase):
    def test_trace_record_carries_thin_compatible_fields(self):
        call = SourceCallRecord(
            source_call_id="call:1",
            step_id="step:1",
            facade_method="get_page_source_facts",
            status="ok",
        )
        record = TraceRecord(
            request_id="req:1",
            question="q",
            question_type="page_summary",
            scope=AssistantScope(page_id="page:1"),
            module_events=(TraceModuleEvent(event_id="e1", module="retrieval", status="ok"),),
            retrieval_calls=(call,),
            recognition_run_ids=("run:1",),
            evidence_ids=("evidence:1",),
            claim_ids=("claim:1",),
            answer_status="answered",
        )
        self.assertEqual("req:1", record.request_id)
        self.assertEqual("page_summary", record.question_type)
        self.assertEqual(("call:1",), tuple(item.source_call_id for item in record.retrieval_calls))
        self.assertEqual(("evidence:1",), record.evidence_ids)
        self.assertEqual("answered", record.answer_status)

    def test_trace_record_requires_request_id(self):
        with self.assertRaises(ValueError):
            TraceRecord(request_id="")

    def test_trace_record_rejects_non_event_module_events(self):
        with self.assertRaises(ValueError):
            TraceRecord(request_id="req:1", module_events=("not-an-event",))

    def test_trace_record_holds_semantic_gap_decision_and_summaries(self):
        decision = SemanticGapDecision(request_id="req:1")
        cost = TraceCostSummary(estimated_cost=2.0)
        latency = TraceLatencySummary(estimated_latency_ms=10.0)
        record = TraceRecord(
            request_id="req:1",
            semantic_gap_decision=decision,
            cost_summary=cost,
            latency_summary=latency,
            cache_status="miss",
            model_profiles=("vision-model-v1",),
            prompt_versions=("recognition-v1",),
        )
        self.assertIs(decision, record.semantic_gap_decision)
        self.assertIs(cost, record.cost_summary)
        self.assertEqual("miss", record.cache_status)
        self.assertEqual(("vision-model-v1",), record.model_profiles)

    def test_trace_record_defaults_are_empty_tuples(self):
        record = TraceRecord(request_id="req:1")
        self.assertEqual((), record.module_events)
        self.assertEqual((), record.retrieval_calls)
        self.assertEqual((), record.evidence_ids)
        self.assertEqual((), record.claim_ids)


class TraceWriteResultTests(unittest.TestCase):
    def test_recorded_result(self):
        result = TraceWriteResult(request_id="req:1", status=TraceWriteStatus.RECORDED)
        self.assertEqual("recorded", result.status.value)

    def test_unavailable_result_has_warning(self):
        result = TraceWriteResult(
            request_id="req:1",
            status=TraceWriteStatus.UNAVAILABLE,
            warning="trace store unavailable",
        )
        self.assertEqual("trace store unavailable", result.warning)

    def test_duplicate_is_not_silent(self):
        result = TraceWriteResult(request_id="req:1", status=TraceWriteStatus.DUPLICATE)
        self.assertEqual("duplicate", result.status.value)


class ClaimTraceTests(unittest.TestCase):
    def test_claim_trace_carries_citation_and_evidence_refs(self):
        trace = ClaimTrace(
            claim_id="claim:1",
            request_id="req:1",
            claim_status="supported",
            statement="block is a table",
            fact_kinds=(FactKind.CANDIDATE_RELATION,),
            evidence_ids=("evidence:1",),
            citation_ids=("citation:1",),
            page_ids=("page:1",),
            block_ids=("block:1",),
            recognition_run_ids=("run:1",),
            candidate_group_ids=("candidate-group:1",),
            payload_refs=("payload:1",),
        )
        self.assertEqual("claim:1", trace.claim_id)
        self.assertEqual("supported", trace.claim_status)
        self.assertEqual((FactKind.CANDIDATE_RELATION,), trace.fact_kinds)
        self.assertEqual(("citation:1",), trace.citation_ids)

    def test_claim_trace_requires_claim_id_and_request_id(self):
        with self.assertRaises(ValueError):
            ClaimTrace(claim_id="", request_id="req:1")
        with self.assertRaises(ValueError):
            ClaimTrace(claim_id="claim:1", request_id="")

    def test_claim_trace_coerces_fact_kinds(self):
        trace = ClaimTrace(claim_id="claim:1", request_id="req:1", fact_kinds=("candidate_relation",))
        self.assertEqual((FactKind.CANDIDATE_RELATION,), trace.fact_kinds)


class TraceQueryResultTests(unittest.TestCase):
    def test_found_result_holds_record(self):
        record = TraceRecord(request_id="req:1")
        result = TraceQueryResult(request_id="req:1", found=True, record=record)
        self.assertTrue(result.found)
        self.assertIs(record, result.record)

    def test_not_found_result(self):
        result = TraceQueryResult(request_id="req:1", found=False, record=None)
        self.assertFalse(result.found)
        self.assertIsNone(result.record)


if __name__ == "__main__":
    unittest.main()
