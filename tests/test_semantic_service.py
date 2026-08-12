"""Tests for pre-execution second cache check in the semantic service."""

from types import SimpleNamespace
import unittest

from drawing_graph.semantic_client import FakeMultimodalRecognitionClient
from drawing_graph.semantic_cache import (
    InMemorySemanticCacheService,
    SemanticCacheKeyInput,
    build_semantic_cache_key,
)
from drawing_graph.semantic_image_inputs import SemanticImageInputBuilder
from drawing_graph.semantic_models import TextObservation
from drawing_graph.semantic_repository import InMemorySemanticEvidenceRepository
from drawing_graph.semantic_service import SemanticRecognitionService
from drawing_graph.tool_models import BBox, ElementEvidence, PageSourceFacts


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


class FailingClientOnCall:
    def __init__(self):
        self.requests = []
        self.model_name = "fake-multimodal"
        self.model_version = "fake-v1"

    def recognize(self, request):
        self.requests.append(request)
        raise AssertionError("client must not be called on cache hit")


def page_facts() -> PageSourceFacts:
    return PageSourceFacts(
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
            task_type="text_observation",
            model_profile="default",
            model_version="fake-v1",
            prompt_version="p1",
            preprocessing_version="preprocess-v1",
            normalization_rule_version="normalize-v1",
            contract_version="1",
        )
    )


class PreExecutionCacheCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cache = InMemorySemanticCacheService()
        self.client = FailingClientOnCall()
        self.run_log = SpyRunLog()

    def service(self):
        return SemanticRecognitionService(
            client=self.client,
            run_log=self.run_log,
            semantic_repository=None,
            input_builder=RecordingInputBuilder(),
            cache_service=self.cache,
        )

    def test_cache_hit_uses_same_key_as_semantic_cache_contract(self):
        self.cache.put(expected_cache_key(), (cached_observation(),))
        service = self.service()

        result = service.recognize_page(
            page_facts(),
            ("DrawingBlock",),
            "default",
            "p1",
            write_back=True,
        )

        self.assertEqual("obs:cached:block:1", result.observations[0].observation_id)
        self.assertEqual([], self.client.requests)

    def test_write_back_cache_hit_never_creates_persistent_run_log(self):
        self.cache.put(expected_cache_key(), (cached_observation(),))
        service = self.service()

        result = service.recognize_page(
            page_facts(),
            ("DrawingBlock",),
            "default",
            "p1",
            write_back=True,
        )

        self.assertFalse(result.persisted)
        self.assertEqual([], self.run_log.calls)
        self.assertEqual([], self.client.requests)

    def test_cache_miss_still_calls_client_and_creates_run_log(self):
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
        service = SemanticRecognitionService(
            client=client,
            run_log=self.run_log,
            semantic_repository=InMemorySemanticEvidenceRepository(),
            input_builder=RecordingInputBuilder(),
            cache_service=self.cache,
        )

        result = service.recognize_page(
            page_facts(),
            ("DrawingBlock",),
            "default",
            "p1",
            write_back=True,
        )

        self.assertTrue(result.persisted)
        self.assertEqual(1, len(client.requests))
        self.assertEqual(("create_run",), self.run_log.calls[0][:1])

    def test_cache_hit_does_not_call_model_or_persist_run(self):
        self.cache.put(expected_cache_key(), (cached_observation(),))
        service = self.service()

        result = service.recognize_page(
            page_facts(),
            ("DrawingBlock",),
            "default",
            "p1",
        )

        self.assertFalse(result.persisted)
        self.assertEqual([], self.client.requests)
        self.assertEqual([], self.run_log.calls)


if __name__ == "__main__":
    unittest.main()
