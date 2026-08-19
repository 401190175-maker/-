"""Tests for the read-only drawing assistant orchestration service."""

import unittest

from drawing_graph.drawing_assistant_service import (
    AnswerPackageAggregator,
    AssistantExecutionError,
    DrawingAssistantService,
    ReadOnlyViolationError,
    RecognitionTargetGrouper,
    SubrequestProjector,
)
from drawing_graph.assistant_models import (
    AnswerPackage,
    AnswerStatus,
    AssistantExecutionPolicy,
    AssistantRequest,
    AssistantScope,
    AssistantSubrequest,
    EvidenceRequirement,
    EvidenceType,
    MachineAnswer,
    QuestionUnderstandingResult,
    ReasonCode,
    RecognitionTarget,
    RetrievalBundle,
    SemanticGapDecision,
    Subanswer,
    TextRenderMode,
)
from drawing_graph.assistant_evidence_fusion_models import (
    Answerability,
    AnswerabilityResult,
    EvidenceBundle,
)
from drawing_graph.semantic_service import SemanticRecognitionResult
from drawing_graph.assistant_trace_store import InMemoryTraceStore
from drawing_graph.assistant_traceability_service import TraceabilityService


class SubrequestProjectorTests(unittest.TestCase):
    def test_project_preserves_all_fields(self):
        projector = SubrequestProjector()
        requirement = EvidenceRequirement(
            requirement_id="req:1",
            evidence_type=EvidenceType.PAGE_SOURCE_FACTS,
            target_scope=AssistantScope(page_id="page:1"),
        )
        subrequest = AssistantSubrequest(
            subrequest_id="sub:1",
            question_type="page_summary",
            scope=AssistantScope(page_id="page:1"),
            required_evidence=(requirement,),
            confidence=0.9,
            ambiguities=("ambiguous",),
            unsupported_parts=("ocr",),
        )
        result = projector.project(subrequest, "req:1")
        self.assertEqual("req:1", result.request_id)
        self.assertEqual("sub:1", result.subrequest_id)
        self.assertEqual("page_summary", result.question_type)
        self.assertEqual("page:1", result.scope.page_id)
        self.assertEqual((requirement,), result.required_evidence)
        self.assertEqual(0.9, result.confidence)
        self.assertEqual(("ambiguous",), result.ambiguities)
        self.assertEqual(("ocr",), result.unsupported_parts)

    def test_subrequests_do_not_mix_fields(self):
        projector = SubrequestProjector()
        first = AssistantSubrequest(
            subrequest_id="sub:1",
            question_type="page_summary",
            scope=AssistantScope(page_id="page:1"),
            ambiguities=("a",),
        )
        second = AssistantSubrequest(
            subrequest_id="sub:2",
            question_type="block_relations",
            scope=AssistantScope(block_id="block:1"),
        )
        r1 = projector.project(first, "req:1")
        r2 = projector.project(second, "req:1")
        self.assertEqual("sub:1", r1.subrequest_id)
        self.assertEqual("sub:2", r2.subrequest_id)
        self.assertIsNone(r2.scope.page_id)
        self.assertEqual(("a",), r1.ambiguities)
        self.assertEqual((), r2.ambiguities)

    def test_project_all_preserves_order(self):
        projector = SubrequestProjector()
        subs = (
            AssistantSubrequest(subrequest_id="sub:1", question_type="page_summary"),
            AssistantSubrequest(subrequest_id="sub:2", question_type="block_relations"),
        )
        results = projector.project_all(subs, "req:1")
        self.assertEqual(("sub:1", "sub:2"), tuple(r.subrequest_id for r in results))


class _RecordingService:
    def __init__(self, result=None):
        self.result = result
        self.calls = 0


class _FakeQuestionService(_RecordingService):
    def understand(self, request):
        self.calls += 1
        return self.result


class _FakeRetrievalService(_RecordingService):
    def __init__(self, result=None):
        super().__init__(result)
        self.question_results = []

    def retrieve(self, question_result, policy=None):
        self.calls += 1
        self.question_results.append(question_result)
        self.last_question_result = question_result
        self.last_policy = policy
        return self.result


class _FakeGapDecisionService(_RecordingService):
    def decide(self, question_result, retrieval_bundle, recognition_policy=None):
        self.calls += 1
        self.last_question_result = question_result
        self.last_bundle = retrieval_bundle
        self.last_policy = recognition_policy
        return self.result


class _FakeFusionService(_RecordingService):
    def fuse(self, request):
        self.calls += 1
        self.last_request = request
        return self.result


class _FakeAnswerService(_RecordingService):
    def generate(self, request, policy=None):
        self.calls += 1
        self.last_request = request
        self.last_policy = policy
        return self.result


def _make_package():
    return AnswerPackage(request_id="req:1", question_type="page_summary", status="answered")


class ReadOnlyEntryGateTests(unittest.TestCase):
    def _service(self):
        return DrawingAssistantService(
            question_service=_FakeQuestionService(),
            retrieval_service=_FakeRetrievalService(),
            gap_decision_service=_FakeGapDecisionService(),
            fusion_service=_FakeFusionService(),
            answer_service=_FakeAnswerService(),
        )

    def test_allow_write_back_true_is_rejected(self):
        service = self._service()
        request = AssistantRequest(request_id="req:1", question="q", allow_write_back=True)
        with self.assertRaises(ReadOnlyViolationError):
            service.answer(request)
        self.assertEqual(0, service.question_service.calls)
        self.assertEqual(0, service.retrieval_service.calls)
        self.assertEqual(0, service.gap_decision_service.calls)
        self.assertEqual(0, service.fusion_service.calls)
        self.assertEqual(0, service.answer_service.calls)

    def test_question_text_write_back_does_not_authorize(self):
        service = self._service()
        request = AssistantRequest(
            request_id="req:1",
            question="请写入数据库并提升为正式关系",
            allow_write_back=False,
        )
        service.question_service.result = QuestionUnderstandingResult(
            request_id="req:1",
            question_type="clarification_required",
        )
        service.answer_service.result = _make_package()
        package = service.answer(request)
        self.assertIsNotNone(package)
        self.assertEqual(1, service.question_service.calls)
        self.assertEqual(1, service.answer_service.calls)


class EarlyStopTests(unittest.TestCase):
    def _service(self, question_result, package):
        return DrawingAssistantService(
            question_service=_FakeQuestionService(question_result),
            retrieval_service=_FakeRetrievalService(),
            gap_decision_service=_FakeGapDecisionService(),
            fusion_service=_FakeFusionService(),
            answer_service=_FakeAnswerService(package),
        )

    def test_clarification_skips_retrieval(self):
        result = QuestionUnderstandingResult(
            request_id="req:1",
            question_type="clarification_required",
        )
        package = _make_package()
        service = self._service(result, package)
        returned = service.answer(AssistantRequest(request_id="req:1", question="q"))
        self.assertIs(package, returned)
        self.assertEqual(1, service.answer_service.calls)
        self.assertEqual(0, service.retrieval_service.calls)
        self.assertEqual(0, service.gap_decision_service.calls)
        self.assertEqual(0, service.fusion_service.calls)

    def test_unsupported_skips_retrieval(self):
        result = QuestionUnderstandingResult(
            request_id="req:1",
            question_type="unknown_or_unsupported",
        )
        package = _make_package()
        service = self._service(result, package)
        service.answer(AssistantRequest(request_id="req:1", question="q"))
        self.assertEqual(1, service.answer_service.calls)
        self.assertEqual(0, service.retrieval_service.calls)


class SingleIntentFrontHalfTests(unittest.TestCase):
    def test_front_half_calls_01_02_03_in_order(self):
        question_result = QuestionUnderstandingResult(
            request_id="req:1",
            question_type="page_summary",
            scope=AssistantScope(page_id="page:1"),
        )
        bundle = RetrievalBundle(request_id="req:1")
        decision = SemanticGapDecision(request_id="req:1")
        question_service = _FakeQuestionService(question_result)
        retrieval_service = _FakeRetrievalService(bundle)
        gap_service = _FakeGapDecisionService(decision)
        service = DrawingAssistantService(
            question_service=question_service,
            retrieval_service=retrieval_service,
            gap_decision_service=gap_service,
            fusion_service=_FakeFusionService(
                EvidenceBundle(
                    request_id="req:1",
                    answerability=AnswerabilityResult(status=Answerability.ANSWERABLE),
                )
            ),
            answer_service=_FakeAnswerService(_make_package()),
        )
        service.answer(AssistantRequest(request_id="req:1", question="q"))
        self.assertEqual(1, question_service.calls)
        self.assertEqual(1, retrieval_service.calls)
        self.assertEqual(1, gap_service.calls)
        self.assertIs(question_result, retrieval_service.last_question_result)
        self.assertIs(bundle, gap_service.last_bundle)
        self.assertEqual("req:1", gap_service.last_question_result.request_id)


class RecognitionTargetGroupingTests(unittest.TestCase):
    def _target(self, target_id, page_id):
        return RecognitionTarget(
            target_id=target_id,
            target_type="element",
            task_type="text",
            page_id=page_id,
            covered_requirement_ids=(f"req:{target_id}",),
        )

    def test_groups_by_page_and_sorts_pages(self):
        grouper = RecognitionTargetGrouper()
        targets = (
            self._target("t:2", "page:2"),
            self._target("t:1", "page:1"),
            self._target("t:3", "page:1"),
        )
        pages, failures = grouper.group(targets)
        self.assertEqual(("page:1", "page:2"), tuple(pid for pid, _ in pages))
        self.assertEqual(("t:1", "t:3"), tuple(t.target_id for t in pages[0][1]))
        self.assertEqual((), failures)

    def test_missing_page_id_is_structured_failure(self):
        grouper = RecognitionTargetGrouper()
        targets = (
            self._target("t:1", "page:1"),
            self._target("t:2", None),
        )
        pages, failures = grouper.group(targets)
        self.assertEqual(1, len(pages))
        self.assertEqual(1, len(failures))
        self.assertEqual(ReasonCode.TARGET_LOCATION_MISSING, failures[0].reason_code)
        self.assertEqual(("t:2",), failures[0].target_ids)

    def test_same_page_targets_are_not_split(self):
        grouper = RecognitionTargetGrouper()
        targets = (
            self._target("t:1", "page:1"),
            self._target("t:2", "page:1"),
        )
        pages, _ = grouper.group(targets)
        self.assertEqual(1, len(pages))
        self.assertEqual(2, len(pages[0][1]))


class _FakeFacade:
    def __init__(self, fail_pages=()):
        self.calls = []
        self.fail_pages = set(fail_pages)

    def recognize_semantic_targets(self, targets, write_back=False, **kwargs):
        self.calls.append((tuple(targets), write_back))
        page_id = targets[0].page_id
        if page_id in self.fail_pages:
            raise Exception("provider secret-token boom")
        return SemanticRecognitionResult(
            recognition_run_id=f"run:{page_id}",
            status="succeeded",
            observations=(),
            persisted=False,
        )


def _orchestrated_service(decision, facade, question_result=None):
    question_result = question_result or QuestionUnderstandingResult(
        request_id="req:1",
        question_type="page_summary",
        scope=AssistantScope(page_id="page:1"),
    )
    bundle = EvidenceBundle(
        request_id="req:1",
        answerability=AnswerabilityResult(status=Answerability.ANSWERABLE),
    )
    return DrawingAssistantService(
        question_service=_FakeQuestionService(question_result),
        retrieval_service=_FakeRetrievalService(RetrievalBundle(request_id="req:1")),
        gap_decision_service=_FakeGapDecisionService(decision),
        fusion_service=_FakeFusionService(bundle),
        answer_service=_FakeAnswerService(_make_package()),
        facade=facade,
    )


def _target(target_id, page_id):
    return RecognitionTarget(
        target_id=target_id,
        target_type="element",
        task_type="text",
        page_id=page_id,
        covered_requirement_ids=("req:1",),
    )


class PageRecognitionExecutionTests(unittest.TestCase):
    def test_each_page_called_once_with_write_back_false(self):
        facade = _FakeFacade()
        decision = SemanticGapDecision(
            request_id="req:1",
            selected_targets=(_target("t:1", "page:1"), _target("t:2", "page:2")),
        )
        service = _orchestrated_service(decision, facade)
        service.answer(AssistantRequest(request_id="req:1", question="q"))
        self.assertEqual(2, len(facade.calls))
        for _, write_back in facade.calls:
            self.assertFalse(write_back)
        pages = {targets[0].page_id for targets, _ in facade.calls}
        self.assertEqual({"page:1", "page:2"}, pages)

    def test_page_failure_recorded_without_losing_other_pages(self):
        facade = _FakeFacade(fail_pages=("page:1",))
        decision = SemanticGapDecision(
            request_id="req:1",
            selected_targets=(_target("t:1", "page:1"), _target("t:2", "page:2")),
        )
        service = _orchestrated_service(decision, facade)
        service.answer(AssistantRequest(request_id="req:1", question="q"))
        self.assertEqual(1, len(service.fusion_service.last_request.recognition_results))
        failures = service.answer_service.last_request.recognition_failures
        self.assertEqual(1, len(failures))
        self.assertEqual("page:1", failures[0].page_id)
        self.assertNotIn("secret-token", failures[0].message)


class RecognitionSkipTests(unittest.TestCase):
    def test_allow_recognition_false_skips_facade(self):
        facade = _FakeFacade()
        decision = SemanticGapDecision(
            request_id="req:1",
            selected_targets=(_target("t:1", "page:1"),),
        )
        service = _orchestrated_service(decision, facade)
        service.answer(
            AssistantRequest(request_id="req:1", question="q", allow_recognition=False)
        )
        self.assertEqual(0, len(facade.calls))

    def test_no_selected_targets_skips_facade(self):
        facade = _FakeFacade()
        decision = SemanticGapDecision(request_id="req:1")
        service = _orchestrated_service(decision, facade)
        service.answer(
            AssistantRequest(request_id="req:1", question="q", allow_recognition=True)
        )
        self.assertEqual(0, len(facade.calls))


class ReadOnlyFusionCallTests(unittest.TestCase):
    def test_fusion_called_with_write_back_policy_none_and_full_context(self):
        facade = _FakeFacade()
        decision = SemanticGapDecision(
            request_id="req:1",
            selected_targets=(_target("t:1", "page:1"),),
        )
        service = _orchestrated_service(decision, facade)
        service.answer(AssistantRequest(request_id="req:1", question="q"))
        fusion_request = service.fusion_service.last_request
        self.assertIsNone(fusion_request.write_back_policy)
        self.assertEqual("req:1", fusion_request.assistant_request.request_id)
        self.assertEqual("req:1", fusion_request.question_result.request_id)
        self.assertEqual("req:1", fusion_request.retrieval_bundle.request_id)
        self.assertEqual("req:1", fusion_request.semantic_gap_decision.request_id)
        self.assertEqual(1, len(fusion_request.recognition_results))


class MultiIntentExecutionTests(unittest.TestCase):
    def _service(self):
        subrequests = (
            AssistantSubrequest(
                subrequest_id="sub:1",
                question_type="page_summary",
                scope=AssistantScope(page_id="page:1"),
                required_evidence=(
                    EvidenceRequirement(
                        requirement_id="req:1",
                        evidence_type=EvidenceType.PAGE_SOURCE_FACTS,
                        target_scope=AssistantScope(page_id="page:1"),
                    ),
                ),
            ),
            AssistantSubrequest(
                subrequest_id="sub:2",
                question_type="block_relations",
                scope=AssistantScope(block_id="block:1"),
                required_evidence=(
                    EvidenceRequirement(
                        requirement_id="req:2",
                        evidence_type=EvidenceType.BLOCK_RELATIONS,
                        target_scope=AssistantScope(block_id="block:1"),
                    ),
                ),
            ),
        )
        question_result = QuestionUnderstandingResult(
            request_id="req:1",
            question_type="multi_intent",
            subrequests=subrequests,
        )
        retrieval = _FakeRetrievalService(RetrievalBundle(request_id="req:1"))
        gap = _FakeGapDecisionService(SemanticGapDecision(request_id="req:1"))
        bundle = EvidenceBundle(
            request_id="req:1",
            answerability=AnswerabilityResult(status=Answerability.ANSWERABLE),
        )
        return DrawingAssistantService(
            question_service=_FakeQuestionService(question_result),
            retrieval_service=retrieval,
            gap_decision_service=gap,
            fusion_service=_FakeFusionService(bundle),
            answer_service=_FakeAnswerService(_make_package()),
            facade=_FakeFacade(),
        ), retrieval

    def test_each_subrequest_projected_and_executed(self):
        service, retrieval = self._service()
        service.answer(AssistantRequest(request_id="req:1", question="q"))
        self.assertEqual(2, retrieval.calls)
        first, second = retrieval.question_results
        self.assertEqual("sub:1", first.subrequest_id)
        self.assertEqual("sub:2", second.subrequest_id)
        self.assertEqual(("req:1",), tuple(r.requirement_id for r in first.required_evidence))
        self.assertEqual(("req:2",), tuple(r.requirement_id for r in second.required_evidence))

    def test_top_level_empty_requirements_not_sent_to_retrieval(self):
        service, retrieval = self._service()
        service.answer(AssistantRequest(request_id="req:1", question="q"))
        for question_result in retrieval.question_results:
            self.assertTrue(question_result.required_evidence)
            self.assertIsNotNone(question_result.subrequest_id)


class AnswerPackageAggregatorTests(unittest.TestCase):
    def _package(self, status, subrequest_id=None):
        machine = MachineAnswer(
            answer_contract_version="drawing-assistant-answer-v1",
            request_id="req:1",
            question_type="page_summary",
            status=status,
        )
        return AnswerPackage(
            request_id="req:1",
            question_type="page_summary",
            status=status.value,
            machine_answer=machine,
            claims=(),
            citations=(),
        )

    def test_all_answered_is_answered(self):
        aggregator = AnswerPackageAggregator()
        p1 = self._package(AnswerStatus.ANSWERED)
        p2 = self._package(AnswerStatus.ANSWERED)
        result = aggregator.aggregate((("sub:1", p1), ("sub:2", p2)), "req:1", "multi_intent", None)
        self.assertEqual(AnswerStatus.ANSWERED, result.machine_answer.status)

    def test_mixed_statuses_are_partial(self):
        aggregator = AnswerPackageAggregator()
        p1 = self._package(AnswerStatus.ANSWERED)
        p2 = self._package(AnswerStatus.UNSUPPORTED)
        result = aggregator.aggregate((("sub:1", p1), ("sub:2", p2)), "req:1", "multi_intent", None)
        self.assertEqual(AnswerStatus.PARTIAL, result.machine_answer.status)

    def test_all_unsupported_is_unsupported(self):
        aggregator = AnswerPackageAggregator()
        p1 = self._package(AnswerStatus.UNSUPPORTED)
        p2 = self._package(AnswerStatus.UNSUPPORTED)
        result = aggregator.aggregate((("sub:1", p1), ("sub:2", p2)), "req:1", "multi_intent", None)
        self.assertEqual(AnswerStatus.UNSUPPORTED, result.machine_answer.status)

    def test_subanswers_preserve_order_and_ids(self):
        aggregator = AnswerPackageAggregator()
        p1 = self._package(AnswerStatus.ANSWERED)
        p2 = self._package(AnswerStatus.PARTIAL)
        result = aggregator.aggregate((("sub:1", p1), ("sub:2", p2)), "req:1", "multi_intent", None)
        self.assertEqual(("sub:1", "sub:2"), tuple(s.subrequest_id for s in result.machine_answer.subanswers))
        self.assertEqual((AnswerStatus.ANSWERED, AnswerStatus.PARTIAL), tuple(s.status for s in result.machine_answer.subanswers))


class AssistantResourceLimitTests(unittest.TestCase):
    def test_subrequest_limit_exceeded_rejected(self):
        subrequests = tuple(
            AssistantSubrequest(subrequest_id=f"sub:{i}", question_type="page_summary")
            for i in range(3)
        )
        question_result = QuestionUnderstandingResult(
            request_id="req:1", question_type="multi_intent", subrequests=subrequests
        )
        service = DrawingAssistantService(
            question_service=_FakeQuestionService(question_result),
            retrieval_service=_FakeRetrievalService(),
            gap_decision_service=_FakeGapDecisionService(),
            fusion_service=_FakeFusionService(),
            answer_service=_FakeAnswerService(),
        )
        with self.assertRaises(AssistantExecutionError) as error:
            service.answer(
                AssistantRequest(request_id="req:1", question="q"),
                AssistantExecutionPolicy(max_subrequests=2),
            )
        self.assertEqual(ReasonCode.MAX_SUBREQUESTS_EXCEEDED, error.exception.reason_code)

    def test_page_group_limit_exceeded_rejected(self):
        facade = _FakeFacade()
        decision = SemanticGapDecision(
            request_id="req:1",
            selected_targets=(
                _target("t:1", "page:1"),
                _target("t:2", "page:2"),
                _target("t:3", "page:3"),
            ),
        )
        service = _orchestrated_service(decision, facade)
        with self.assertRaises(AssistantExecutionError) as error:
            service.answer(
                AssistantRequest(request_id="req:1", question="q"),
                AssistantExecutionPolicy(max_page_groups=2),
            )
        self.assertEqual(ReasonCode.MAX_PAGE_GROUPS_EXCEEDED, error.exception.reason_code)


class AssistantErrorMappingTests(unittest.TestCase):
    def test_retrieval_failure_maps_to_execution_error(self):
        class FailingRetrieval:
            calls = 0
            def retrieve(self, question_result, policy=None):
                self.calls += 1
                raise RuntimeError("backend unavailable")

        question_result = QuestionUnderstandingResult(
            request_id="req:1", question_type="page_summary", scope=AssistantScope(page_id="page:1")
        )
        service = DrawingAssistantService(
            question_service=_FakeQuestionService(question_result),
            retrieval_service=FailingRetrieval(),
            gap_decision_service=_FakeGapDecisionService(),
            fusion_service=_FakeFusionService(),
            answer_service=_FakeAnswerService(),
        )
        with self.assertRaises(AssistantExecutionError) as error:
            service.answer(AssistantRequest(request_id="req:1", question="q"))
        self.assertEqual("retrieval_failed", error.exception.reason_code)

    def test_business_terminal_status_is_not_error(self):
        question_result = QuestionUnderstandingResult(
            request_id="req:1", question_type="clarification_required"
        )
        service = DrawingAssistantService(
            question_service=_FakeQuestionService(question_result),
            retrieval_service=_FakeRetrievalService(),
            gap_decision_service=_FakeGapDecisionService(),
            fusion_service=_FakeFusionService(),
            answer_service=_FakeAnswerService(_make_package()),
        )
        package = service.answer(AssistantRequest(request_id="req:1", question="q"))
        self.assertIsNotNone(package)
        self.assertEqual(0, service.retrieval_service.calls)


class TraceInjectionTests(unittest.TestCase):
    def _service(self, traceability_service=None):
        question_result = QuestionUnderstandingResult(
            request_id="req:1",
            question_type="page_summary",
            scope=AssistantScope(page_id="page:1"),
        )
        bundle = EvidenceBundle(
            request_id="req:1",
            answerability=AnswerabilityResult(status=Answerability.ANSWERABLE),
        )
        return DrawingAssistantService(
            question_service=_FakeQuestionService(question_result),
            retrieval_service=_FakeRetrievalService(RetrievalBundle(request_id="req:1")),
            gap_decision_service=_FakeGapDecisionService(SemanticGapDecision(request_id="req:1")),
            fusion_service=_FakeFusionService(bundle),
            answer_service=_FakeAnswerService(_make_package()),
            traceability_service=traceability_service,
        )

    def test_trace_recorded_when_service_injected(self):
        store = InMemoryTraceStore()
        service = self._service(TraceabilityService(store))
        service.answer(AssistantRequest(request_id="req:1", question="q"))
        self.assertIsNotNone(store.get_trace("req:1"))

    def test_no_trace_service_keeps_behavior_compatible(self):
        service = self._service(None)
        package = service.answer(AssistantRequest(request_id="req:1", question="q"))
        self.assertIsNotNone(package)
        self.assertEqual(1, service.question_service.calls)
        self.assertEqual(1, service.answer_service.calls)

    def test_trace_failure_does_not_fail_answer(self):
        class _FailingTraceStore:
            def append_trace(self, record):
                raise RuntimeError("store down")

            def get_trace(self, request_id):
                raise RuntimeError("store down")

            def append_claim_trace(self, claim_trace):
                raise RuntimeError("store down")

            def get_claim_trace(self, claim_id):
                raise RuntimeError("store down")

            def list_feedback_refs(self, request_id):
                raise RuntimeError("store down")

        service = self._service(TraceabilityService(_FailingTraceStore()))
        package = service.answer(AssistantRequest(request_id="req:1", question="q"))
        self.assertIsNotNone(package)
        self.assertEqual("answered", package.status)

    def test_allow_write_back_still_rejected_with_trace_service(self):
        store = InMemoryTraceStore()
        service = self._service(TraceabilityService(store))
        with self.assertRaises(ReadOnlyViolationError):
            service.answer(
                AssistantRequest(request_id="req:1", question="q", allow_write_back=True)
            )
        self.assertIsNone(store.get_trace("req:1"))


if __name__ == "__main__":
    unittest.main()
