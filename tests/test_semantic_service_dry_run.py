import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.query_ports import FakeDrawingGraphReadPort
from drawing_graph.semantic_client import FakeMultimodalRecognitionClient
from drawing_graph.semantic_cache import (
    InMemorySemanticCacheService,
    SemanticCacheKeyInput,
    build_semantic_cache_key,
)
from drawing_graph.semantic_image_inputs import SemanticImageInputBuilder
from drawing_graph.semantic_models import TextObservation
from drawing_graph.semantic_service import SemanticRecognitionService
from drawing_graph.tool_facade import DrawingGraphToolFacade
from drawing_graph.tool_models import BBox, ElementEvidence, PageSourceFacts


class SpyRepository:
    def __init__(self):
        self.calls = []

    def create_run(self, *args, **kwargs):
        self.calls.append(("create_run", args, kwargs))

    def save_observations(self, *args, **kwargs):
        self.calls.append(("save_observations", args, kwargs))

    def save_interpretations(self, *args, **kwargs):
        self.calls.append(("save_interpretations", args, kwargs))


class RecordingInputBuilder:
    def __init__(self):
        self.build_calls = []
        self.builder = SemanticImageInputBuilder(image_hash_provider=lambda image_path: "hash:provided")

    def build_input(self, page_facts, element_id):
        self.build_calls.append(element_id)
        return self.builder.build_input(page_facts, element_id)


class FailingClientOnCall:
    def __init__(self):
        self.requests = []
        self.model_name = "fake-multimodal"
        self.model_version = "fake-v1"

    def recognize(self, request):
        self.requests.append(request)
        raise AssertionError("client must not be called on cache hit")


def cached_observation():
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


class SemanticServiceDryRunTest(unittest.TestCase):
    def test_dry_run_returns_temporary_observations_without_persistence(self):
        facts = PageSourceFacts(
            page_id="page:1",
            image_path="road_24.png",
            elements=(
                ElementEvidence(
                    element_id="block:1",
                    element_type="DrawingBlock",
                    source_label="block",
                    bbox=BBox(1, 2, 3, 4),
                    normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
                ),
            ),
        )
        spy = SpyRepository()
        service = SemanticRecognitionService(
            client=FakeMultimodalRecognitionClient(
                outputs=[
                    {
                        "target_element_id": "block:1",
                        "target_element_type": "DrawingBlock",
                        "raw_text": "A1",
                        "normalized_text": "A1",
                        "confidence": 0.9,
                        "status": "confirmed",
                    }
                ]
            ),
            run_log=spy,
            semantic_repository=spy,
        )

        result = service.recognize_page(facts, target_types=("DrawingBlock",), model_profile="default", prompt_version="p1")

        self.assertFalse(result.persisted)
        self.assertTrue(result.recognition_run_id.startswith("run:temp:"))
        self.assertEqual("block:1", result.observations[0].target_element_id)
        self.assertEqual([], spy.calls)

    def test_facade_can_run_dry_run_recognition_through_injected_service(self):
        facts = PageSourceFacts(
            page_id="page:1",
            image_path="road_24.png",
            elements=(),
        )
        facade = DrawingGraphToolFacade(
            read_port=FakeDrawingGraphReadPort(source_facts={"page:1": facts}),
            semantic_service=SemanticRecognitionService(client=FakeMultimodalRecognitionClient()),
        )

        result = facade.recognize_page_semantics("page:1", target_types=("DrawingBlock",))

        self.assertFalse(result.persisted)
        self.assertEqual("succeeded", result.status)

    def test_dry_run_builds_image_inputs_and_returns_temporary_evidence_without_writes(self):
        facts = PageSourceFacts(
            page_id="page:1",
            image_path="road_24.png",
            elements=(
                ElementEvidence(
                    element_id="block:1",
                    element_type="DrawingBlock",
                    source_label="block",
                    bbox=BBox(1, 2, 3, 4),
                    normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
                ),
            ),
        )
        spy = SpyRepository()
        input_builder = RecordingInputBuilder()
        service = SemanticRecognitionService(
            client=FakeMultimodalRecognitionClient(
                outputs=[
                    {
                        "target_element_id": "block:1",
                        "target_element_type": "DrawingBlock",
                        "raw_text": "A1",
                        "normalized_text": "A1",
                        "confidence": 0.9,
                        "status": "confirmed",
                    }
                ],
                interpretations=[
                    {
                        "target_element_id": "block:1",
                        "target_element_type": "DrawingBlock",
                        "summary": "wall block",
                        "interpreted_type": "structural_wall",
                        "analysis_status": "interpreted",
                        "supported_by_observation_ids": ("obs:temp:1",),
                    }
                ],
            ),
            run_log=spy,
            semantic_repository=spy,
            input_builder=input_builder,
        )

        result = service.recognize_page(facts, target_types=("DrawingBlock",), model_profile="default", prompt_version="p1")

        self.assertFalse(result.persisted)
        self.assertEqual(["block:1"], input_builder.build_calls)
        self.assertEqual("block:1", result.observations[0].target_element_id)
        self.assertEqual("wall block", result.interpretations[0].summary)
        self.assertEqual("structural_wall", result.interpretations[0].interpreted_type)
        self.assertEqual([], spy.calls)

    def test_dry_run_reuses_valid_cache_without_calling_client(self):
        facts = PageSourceFacts(
            page_id="page:1",
            image_path="road_24.png",
            elements=(
                ElementEvidence(
                    element_id="block:1",
                    element_type="DrawingBlock",
                    source_label="block",
                    bbox=BBox(1, 2, 3, 4),
                    normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
                ),
            ),
        )
        client = FakeMultimodalRecognitionClient(
            outputs=[
                {
                    "target_element_id": "block:1",
                    "target_element_type": "DrawingBlock",
                    "raw_text": "A1",
                    "normalized_text": "A1",
                    "confidence": 0.9,
                    "status": "confirmed",
                }
            ]
        )
        cache = InMemorySemanticCacheService()
        input_builder = RecordingInputBuilder()
        service = SemanticRecognitionService(
            client=client,
            run_log=SpyRepository(),
            semantic_repository=SpyRepository(),
            input_builder=input_builder,
            cache_service=cache,
        )
        first = service.recognize_page(facts, ("DrawingBlock",), "default", "p1")
        self.assertEqual(1, len(client.requests))
        second = service.recognize_page(facts, ("DrawingBlock",), "default", "p1")

        self.assertFalse(second.persisted)
        self.assertEqual(1, len(client.requests))
        self.assertEqual("block:1", second.observations[0].target_element_id)
        self.assertEqual(first.observations[0].cache_key, second.observations[0].cache_key)

    def test_dry_run_cache_hit_never_calls_client_or_writes(self):
        facts = PageSourceFacts(
            page_id="page:1",
            image_path="road_24.png",
            elements=(
                ElementEvidence(
                    element_id="block:1",
                    element_type="DrawingBlock",
                    source_label="block",
                    bbox=BBox(1, 2, 3, 4),
                    normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
                ),
            ),
        )
        client = FailingClientOnCall()
        spy = SpyRepository()
        cache = InMemorySemanticCacheService()
        cache.put(
            build_semantic_cache_key(
                SemanticCacheKeyInput(
                    image_hash="hash:provided",
                    bbox=(1, 2, 3, 4),
                    target_element_id="block:1",
                    task_type="text_observation",
                    model_profile="default",
                    model_version="fake-v1",
                    prompt_version="p1",
                    preprocessing_version="preprocess-v1",
                    normalization_rule_version="normalize-v1",
                    contract_version="1",
                )
            ),
            (cached_observation(),),
        )
        service = SemanticRecognitionService(
            client=client,
            run_log=spy,
            semantic_repository=spy,
            input_builder=RecordingInputBuilder(),
            cache_service=cache,
        )
        result = service.recognize_page(facts, ("DrawingBlock",), "default", "p1")

        self.assertEqual([], client.requests)
        self.assertFalse(result.persisted)
        self.assertEqual("obs:cached:block:1", result.observations[0].observation_id)
        self.assertEqual([], spy.calls)


if __name__ == "__main__":
    unittest.main()
