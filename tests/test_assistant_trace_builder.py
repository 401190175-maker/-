"""Tests for the trace record builder (07 traceability loop)."""

import unittest

from drawing_graph.assistant_models import (
    AssistantRequest,
    AssistantScope,
    CacheDisposition,
    EvidenceItem,
    FactKind,
    QuestionUnderstandingResult,
    RecognitionEstimate,
    RetrievalBundle,
    RetrievalStatus,
    SemanticGapDecision,
    SourceCallRecord,
)
from drawing_graph.assistant_evidence_fusion_models import (
    Answerability,
    AnswerabilityResult,
    CacheSummary,
    EvidenceBundle,
    FusionEvidence,
    FusionMetadata,
)
from drawing_graph.assistant_trace_builder import TraceRecordBuilder
from drawing_graph.assistant_trace_models import TraceCostSummary, TraceLatencySummary, TraceRecord


class _FakeRecognitionResult:
    def __init__(self, recognition_run_id):
        self.recognition_run_id = recognition_run_id
        self.payload = "secret-token-do-not-leak"


class TraceRecordBuilderTests(unittest.TestCase):
    def _request(self):
        return AssistantRequest(request_id="req:1", question="这个块是什么")

    def _question_result(self):
        return QuestionUnderstandingResult(
            request_id="req:1",
            question_type="page_summary",
            scope=AssistantScope(page_id="page:1"),
        )

    def _retrieval_bundle(self):
        call = SourceCallRecord(
            source_call_id="call:1",
            step_id="step:1",
            facade_method="get_page_source_facts",
            status="ok",
            result_count=1,
        )
        item = EvidenceItem(
            evidence_id="evidence:1",
            fact_kind=FactKind.SOURCE_FACT,
            scope=AssistantScope(page_id="page:1"),
            model_profile="vision-model-v1",
            prompt_version="recognition-v1",
        )
        return RetrievalBundle(
            request_id="req:1",
            source_facts=(item,),
            source_calls=(call,),
            status=RetrievalStatus.OK,
        )

    def _decision(self):
        return SemanticGapDecision(
            request_id="req:1",
            estimate=RecognitionEstimate(
                estimated_cost=1.5,
                estimated_latency_ms=250.0,
                currency="CNY",
                selected_target_count=1,
            ),
        )

    def _bundle(self):
        return EvidenceBundle(
            request_id="req:1",
            accepted_evidence=(
                FusionEvidence(
                    item=EvidenceItem(evidence_id="evidence:2", fact_kind=FactKind.SOURCE_FACT),
                    metadata=FusionMetadata(),
                ),
            ),
            cache_summary=CacheSummary(),
            answerability=AnswerabilityResult(status=Answerability.ANSWERABLE),
        )

    def _package(self):
        from drawing_graph.assistant_models import AnswerPackage, Claim

        claim = Claim(claim_id="claim:1", statement="s")
        return AnswerPackage(
            request_id="req:1",
            question_type="page_summary",
            status="answered",
            claims=(claim,),
            recognition_run_ids=("run:1",),
        )

    def test_build_extracts_request_and_question_type_and_scope(self):
        builder = TraceRecordBuilder()
        record = builder.build(
            request=self._request(),
            question_result=self._question_result(),
            retrieval_bundle=self._retrieval_bundle(),
            gap_decision=self._decision(),
            evidence_bundle=self._bundle(),
            answer_package=self._package(),
        )
        self.assertIsInstance(record, TraceRecord)
        self.assertEqual("req:1", record.request_id)
        self.assertEqual("这个块是什么", record.question)
        self.assertEqual("page_summary", record.question_type)
        self.assertEqual("page:1", record.scope.page_id)

    def test_build_copies_retrieval_calls_and_evidence_and_claim_ids(self):
        builder = TraceRecordBuilder()
        record = builder.build(
            request=self._request(),
            question_result=self._question_result(),
            retrieval_bundle=self._retrieval_bundle(),
            gap_decision=self._decision(),
            evidence_bundle=self._bundle(),
            answer_package=self._package(),
        )
        self.assertEqual(("call:1",), tuple(call.source_call_id for call in record.retrieval_calls))
        self.assertIn("evidence:1", record.evidence_ids)
        self.assertIn("evidence:2", record.evidence_ids)
        self.assertEqual(("claim:1",), record.claim_ids)
        self.assertEqual(("run:1",), record.recognition_run_ids)

    def test_build_emits_module_events_for_each_stage(self):
        builder = TraceRecordBuilder()
        record = builder.build(
            request=self._request(),
            question_result=self._question_result(),
            retrieval_bundle=self._retrieval_bundle(),
            gap_decision=self._decision(),
            evidence_bundle=self._bundle(),
            answer_package=self._package(),
        )
        modules = {event.module for event in record.module_events}
        self.assertIn("question_understanding", modules)
        self.assertIn("retrieval", modules)
        self.assertIn("semantic_gap_decision", modules)
        self.assertIn("evidence_fusion", modules)
        self.assertIn("answer_generation", modules)

    def test_build_sets_answer_status_and_cost_latency_summaries(self):
        builder = TraceRecordBuilder()
        record = builder.build(
            request=self._request(),
            question_result=self._question_result(),
            retrieval_bundle=self._retrieval_bundle(),
            gap_decision=self._decision(),
            evidence_bundle=self._bundle(),
            answer_package=self._package(),
        )
        self.assertEqual("answered", record.answer_status)
        self.assertIsInstance(record.cost_summary, TraceCostSummary)
        self.assertEqual(1.5, record.cost_summary.estimated_cost)
        self.assertIsInstance(record.latency_summary, TraceLatencySummary)
        self.assertEqual(250.0, record.latency_summary.estimated_latency_ms)

    def test_build_does_not_leak_recognition_payload(self):
        builder = TraceRecordBuilder()
        record = builder.build(
            request=self._request(),
            question_result=self._question_result(),
            retrieval_bundle=self._retrieval_bundle(),
            gap_decision=self._decision(),
            recognition_results=(_FakeRecognitionResult("run:1"),),
            evidence_bundle=self._bundle(),
            answer_package=self._package(),
        )
        self.assertIn("run:1", record.recognition_run_ids)
        serialized = repr(record)
        self.assertNotIn("secret-token", serialized)

    def test_build_tolerates_missing_stages(self):
        builder = TraceRecordBuilder()
        record = builder.build(
            request=self._request(),
            question_result=self._question_result(),
        )
        self.assertEqual("req:1", record.request_id)
        self.assertEqual((), record.retrieval_calls)
        self.assertEqual((), record.evidence_ids)

    def test_builder_has_no_side_effects(self):
        builder = TraceRecordBuilder()
        record = builder.build(
            request=self._request(),
            question_result=self._question_result(),
            retrieval_bundle=self._retrieval_bundle(),
            gap_decision=self._decision(),
            evidence_bundle=self._bundle(),
            answer_package=self._package(),
        )
        self.assertIsInstance(record, TraceRecord)
        self.assertEqual((), record.warnings if hasattr(record, "warnings") else ())


if __name__ == "__main__":
    unittest.main()
