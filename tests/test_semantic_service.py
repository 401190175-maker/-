"""Semantic service execution-grouping and cache-order contract tests."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from drawing_graph.recognition_execution import MultimodalRecognitionExecutionService
from drawing_graph.recognition_models import RecognitionExecutionResult
from drawing_graph.semantic_cache import (
    InMemorySemanticCacheService,
    SemanticCacheKeyInput,
    build_semantic_cache_key,
)
from drawing_graph.semantic_client import FakeMultimodalRecognitionClient
from drawing_graph.semantic_image_inputs import SemanticImageInputBuilder
from drawing_graph.semantic_models import TextObservation
from drawing_graph.semantic_service import SemanticRecognitionService
from drawing_graph.tool_models import BBox, ElementEvidence, PageSourceFacts, SemanticTargetInput


class SpyRunLog:
    def __init__(self):
        self.calls = []

    def create_run(self, *args, **kwargs):
        self.calls.append(("create_run", args, kwargs))
        return SimpleNamespace(recognition_run_id="run:1")

    def complete_run(self, *args, **kwargs):
        self.calls.append(("complete_run", args, kwargs))

    def fail_run(self, *args, **kwargs):
        self.calls.append(("fail_run", args, kwargs))


class RecordingInputBuilder:
    def __init__(self):
        self.builder = SemanticImageInputBuilder(
            image_hash_provider=lambda image_path: "hash:provided"
        )

    def build_input(self, page_facts, element_id):
        return self.builder.build_input(page_facts, element_id)


class StubExecutionService:
    def __init__(self, results=None):
        self.calls = []
        self.results = list(results or [])

    def execute(self, request, page_facts, execution_policy=None):
        self.calls.append((request, page_facts, execution_policy))
        if self.results:
            return self.results.pop(0)
        return RecognitionExecutionResult(
            recognition_run_id=request.recognition_run_id,
            status="succeeded",
        )


class FailingClientOnCall:
    def __init__(self):
        self.requests = []
        self.model_name = "fake-multimodal"
        self.model_version = "fake-v1"

    def recognize(self, request):
        self.requests.append(request)
        raise AssertionError("client must not be called on cache hit")


def _element(element_id: str, element_type: str = "DrawingBlock") -> ElementEvidence:
    return ElementEvidence(
        element_id=element_id,
        element_type=element_type,
        source_label=element_id,
        bbox=BBox(1, 2, 3, 4),
        normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
    )


def page_facts(*elements: ElementEvidence) -> PageSourceFacts:
    return PageSourceFacts(
        page_id="page:1",
        image_path="road_24.png",
        elements=tuple(elements),
        image_size=(10, 10),
        image_hash="hash:provided",
    )


def target(
    *,
    target_id: str,
    element_id: str,
    element_type: str = "DrawingBlock",
    task_type: str = "block_semantic_identification",
    output_contract_version: str = "1",
) -> SemanticTargetInput:
    return SemanticTargetInput(
        target_id=target_id,
        page_id="page:1",
        target_element_id=element_id,
        target_type=element_type,
        task_type=task_type,
        required_outputs=("observation",),
        bbox=BBox(1, 2, 3, 4),
        normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
        output_contract_version=output_contract_version,
    )


def cached_observation() -> TextObservation:
    return TextObservation(
        observation_id="obs:cached:block:1",
        recognition_run_id="run:cached",
        target_element_id="block:1",
        target_element_type="DrawingBlock",
        page_id="page:1",
        raw_text="A1",
        normalized_text="A1",
        bbox=BBox(1, 2, 3, 4),
        normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
        confidence=0.9,
        status="confirmed",
        image_hash="hash:provided",
        cache_key="cache:1",
        model_profile="default",
        prompt_version="p1",
        created_at="2026-08-06T00:00:00Z",
    )


def expected_cache_key() -> str:
    return build_semantic_cache_key(
        SemanticCacheKeyInput(
            image_hash="hash:provided",
            bbox=(1, 2, 3, 4),
            target_element_id="block:1",
            task_type="element_text_observation",
            model_profile="default",
            model_version="fake-v1",
            prompt_version="p1",
            preprocessing_version="preprocess-v1",
            normalization_rule_version="normalize-v1",
            contract_version="1",
        )
    )


class SemanticExecutionGroupingTests(unittest.TestCase):
    """Cache-miss targets group by the execution compatibility key."""

    def _service(self, stub: StubExecutionService) -> SemanticRecognitionService:
        return SemanticRecognitionService(
            client=None,
            run_log=SpyRunLog(),
            cache_service=None,
            execution_service=stub,
        )

    def test_same_task_compatible_targets_share_one_group(self) -> None:
        facts = page_facts(_element("block:1"), _element("block:2"))
        targets = (
            target(target_id="t1", element_id="block:1"),
            target(target_id="t2", element_id="block:2"),
        )
        stub = StubExecutionService()
        self._service(stub).recognize_targets(facts, targets, "default", "prompt-v1")

        self.assertEqual(1, len(stub.calls))
        request = stub.calls[0][0]
        self.assertEqual(2, len(request.targets))
        self.assertEqual(("t1", "t2"), tuple(item.target_id for item in request.targets))

    def test_different_task_types_are_not_merged(self) -> None:
        facts = page_facts(
            _element("block:1", "DrawingBlock"),
            _element("caption:1", "BlockCaption"),
        )
        targets = (
            target(target_id="t1", element_id="block:1", task_type="block_semantic_identification"),
            target(
                target_id="t2",
                element_id="caption:1",
                element_type="BlockCaption",
                task_type="element_text_observation",
            ),
        )
        stub = StubExecutionService()
        self._service(stub).recognize_targets(facts, targets, "default", "prompt-v1")

        self.assertEqual(2, len(stub.calls))
        self.assertEqual(
            {"block_semantic_identification", "element_text_observation"},
            {call[0].task_type.value for call in stub.calls},
        )

    def test_different_contract_versions_are_not_merged(self) -> None:
        facts = page_facts(_element("block:1"), _element("block:2"))
        targets = (
            target(target_id="t1", element_id="block:1", output_contract_version="1"),
            target(target_id="t2", element_id="block:2", output_contract_version="2"),
        )
        stub = StubExecutionService()
        self._service(stub).recognize_targets(facts, targets, "default", "prompt-v1")

        self.assertEqual(2, len(stub.calls))

    def test_groups_are_ordered_by_compatibility_key_and_target_id(self) -> None:
        facts = page_facts(
            _element("block:1", "DrawingBlock"),
            _element("caption:1", "BlockCaption"),
        )
        targets = (
            target(
                target_id="t-caption",
                element_id="caption:1",
                element_type="BlockCaption",
                task_type="element_text_observation",
            ),
            target(target_id="t-block", element_id="block:1"),
        )
        stub = StubExecutionService()
        self._service(stub).recognize_targets(facts, targets, "default", "prompt-v1")

        self.assertEqual(2, len(stub.calls))
        task_order = [call[0].task_type.value for call in stub.calls]
        self.assertEqual(sorted(task_order), task_order)

    def test_all_groups_share_one_logical_run_id(self) -> None:
        facts = page_facts(
            _element("block:1", "DrawingBlock"),
            _element("caption:1", "BlockCaption"),
        )
        targets = (
            target(target_id="t1", element_id="block:1"),
            target(
                target_id="t2",
                element_id="caption:1",
                element_type="BlockCaption",
                task_type="element_text_observation",
            ),
        )
        stub = StubExecutionService()
        self._service(stub).recognize_targets(facts, targets, "default", "prompt-v1")

        run_ids = {call[0].recognition_run_id for call in stub.calls}
        self.assertEqual(1, len(run_ids))

    def test_service_does_not_render_prompts_or_crop_images(self) -> None:
        service = self._service(StubExecutionService())
        self.assertFalse(hasattr(service, "prompt_renderer"))
        self.assertFalse(hasattr(service, "preprocessor"))


class PreExecutionCacheCheckTests(unittest.TestCase):
    """Cache hits must never reach the execution service or run log."""

    def setUp(self) -> None:
        self.cache = InMemorySemanticCacheService()
        self.run_log = SpyRunLog()
        self.failing_client = FailingClientOnCall()

    def _service(self):
        return SemanticRecognitionService(
            client=self.failing_client,
            run_log=self.run_log,
            cache_service=self.cache,
            input_builder=RecordingInputBuilder(),
        )

    def test_cache_hit_uses_same_key_as_semantic_cache_contract(self) -> None:
        self.cache.put(expected_cache_key(), (cached_observation(),))
        result = self._service().recognize_page(
            page_facts(_element("block:1")),
            ("DrawingBlock",),
            "default",
            "p1",
            write_back=True,
        )

        self.assertEqual("obs:cached:block:1", result.observations[0].observation_id)
        self.assertEqual([], self.failing_client.requests)
        self.assertEqual([], self.run_log.calls)
        self.assertFalse(result.persisted)


if __name__ == "__main__":
    unittest.main()
