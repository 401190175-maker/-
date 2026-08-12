"""Tests for the graph retrieval service orchestration."""

from pathlib import Path
import inspect
import unittest

from drawing_graph.assistant_models import (
    AssistantScope,
    EvidenceRequirement,
    EvidenceType,
    QuestionUnderstandingResult,
    RawRetrievalResult,
    RetrievalPlan,
    RetrievalStatus,
)
from drawing_graph.assistant_retrieval_service import GraphRetrievalService
from drawing_graph.tool_models import BlockTrace, BBox


class FakeFacade:
    def __init__(self):
        self.calls = []

    def get_block_trace(self, block_id):
        self.calls.append(("get_block_trace", block_id))
        return BlockTrace(
            block_id=block_id,
            project_id="project:1",
            drawing_set_id="set:1",
            page_id="page:1",
            bbox=BBox(1, 2, 3, 4),
            normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
        )

    def recognize_page_semantics(self, *args, **kwargs):
        self.calls.append(("recognize_page_semantics", args, kwargs))
        return object()

    def review_candidate_relation(self, *args, **kwargs):
        self.calls.append(("review_candidate_relation", args, kwargs))
        return object()

    def match_section_caption(self, *args, **kwargs):
        self.calls.append(("match_section_caption", args, kwargs))
        return object()


def make_result() -> QuestionUnderstandingResult:
    requirement = EvidenceRequirement(
        requirement_id="req:block-trace",
        evidence_type=EvidenceType.BLOCK_TRACE,
        target_scope=AssistantScope(block_id="block:1"),
    )
    return QuestionUnderstandingResult(
        request_id="req:1",
        question_type="block_relations",
        scope=AssistantScope(block_id="block:1"),
        required_evidence=(requirement,),
    )


class RecordingPlanner:
    def __init__(self):
        self.events = []

    def plan(self, question_result, policy=None):
        self.events.append("plan")
        requirement = question_result.required_evidence[0]
        from drawing_graph.assistant_models import RetrievalStep

        step = RetrievalStep(
            step_id="step:1",
            facade_method="get_block_trace",
            parameters={"block_id": "block:1"},
            requirement_ids=(requirement.requirement_id,),
            dedupe_key="get_block_trace:block:1",
        )
        return RetrievalPlan(request_id="req:1", steps=(step,))


class RecordingExecutor:
    def __init__(self):
        self.events = []

    def execute(self, plan, facade):
        self.events.append("execute")
        return (
            RawRetrievalResult(
                results={"step:1": facade.get_block_trace("block:1")},
                truncated_step_ids=(),
            ),
            (),
        )


class RecordingBundleBuilder:
    def __init__(self):
        self.events = []

    def build(self, question_result, plan, raw_result, source_calls):
        self.events.append("build")
        from drawing_graph.assistant_models import RetrievalBundle

        return RetrievalBundle(
            request_id=question_result.request_id,
            status=RetrievalStatus.OK,
        )


class GraphRetrievalServiceTests(unittest.TestCase):
    def test_retrieve_completes_full_loop_with_default_dependencies(self):
        service = GraphRetrievalService(FakeFacade())
        bundle = service.retrieve(make_result())
        self.assertEqual("req:1", bundle.request_id)
        self.assertEqual(1, len(bundle.source_facts))
        self.assertEqual("block:1", bundle.source_facts[0].scope.block_id)

    def test_retrieve_orchestrates_plan_execute_build_in_order(self):
        planner = RecordingPlanner()
        executor = RecordingExecutor()
        builder = RecordingBundleBuilder()
        service = GraphRetrievalService(
            FakeFacade(),
            planner=planner,
            executor=executor,
            bundle_builder=builder,
        )
        service.retrieve(make_result())
        self.assertEqual(["plan", "execute", "build"], planner.events + executor.events + builder.events)

    def test_retrieve_never_invokes_write_or_recognition_capabilities(self):
        facade = FakeFacade()
        service = GraphRetrievalService(facade)
        service.retrieve(make_result())
        called = [name for name, *_ in facade.calls]
        self.assertNotIn("recognize_page_semantics", called)
        self.assertNotIn("review_candidate_relation", called)
        self.assertNotIn("match_section_caption", called)

    def test_service_source_does_not_import_driver_or_read_environment(self):
        module_path = Path(inspect.getfile(GraphRetrievalService))
        source = module_path.read_text(encoding="utf-8").lower()
        self.assertNotIn("neo4j", source)
        self.assertNotIn("graphdatabase", source)
        self.assertNotIn("environ", source)


if __name__ == "__main__":
    unittest.main()
