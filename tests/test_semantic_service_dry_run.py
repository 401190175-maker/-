"""Dry-run contracts: temporary evidence only, zero persistence writes."""

from __future__ import annotations

import unittest

from drawing_graph.query_ports import FakeDrawingGraphReadPort
from drawing_graph.recognition_models import RecognitionExecutionResult, ValidatedRecognitionOutput
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


def _element(element_id: str = "block:1", element_type: str = "DrawingBlock") -> ElementEvidence:
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
        elements=tuple(elements or (_element(),)),
        image_size=(10, 10),
        image_hash="hash:provided",
    )


class StubExecutionService:
    def __init__(self, results=None):
        self.calls = []
        self.results = list(results or [])

    def execute(self, request, page_facts, execution_policy=None):
        self.calls.append(request)
        if self.results:
            return self.results.pop(0)
        return RecognitionExecutionResult(
            recognition_run_id=request.recognition_run_id,
            status="succeeded",
        )


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


def observation_output() -> ValidatedRecognitionOutput:
    return ValidatedRecognitionOutput(
        task_type="element_text_observation",
        target_id="target:block:1",
        target_type="DrawingBlock",
        status="succeeded",
        output={
            "observations": [
                {
                    "raw_text": "A1",
                    "normalized_text": "A1",
                    "confidence": 0.9,
                    "status": "confirmed",
                }
            ]
        },
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
            model_version="unknown",
            prompt_version="p1",
            preprocessing_version="preprocess-v1",
            normalization_rule_version="normalize-v1",
            contract_version="1",
        )
    )


class SemanticServiceDryRunTest(unittest.TestCase):
    def _service(self, stub, *, cache=None, input_builder=None, run_log=None, repository=None):
        return SemanticRecognitionService(
            client=None,
            run_log=run_log or SpyRepository(),
            semantic_repository=repository or SpyRepository(),
            input_builder=input_builder,
            cache_service=cache,
            execution_service=stub,
        )

    def test_dry_run_returns_temporary_observations_without_persistence(self):
        stub = StubExecutionService(
            results=(RecognitionExecutionResult(recognition_run_id="run:temp:1", status="succeeded", validated_outputs=(observation_output(),)),)
        )
        service = self._service(stub)

        result = service.recognize_page(page_facts(), ("DrawingBlock",), "default", "p1")

        self.assertFalse(result.persisted)
        self.assertTrue(result.recognition_run_id.startswith("run:temp:"))
        self.assertEqual("block:1", result.observations[0].target_element_id)
        self.assertEqual([], service.run_log.calls)
        self.assertEqual([], service.semantic_repository.calls)

    def test_facade_can_run_dry_run_recognition_through_injected_service(self):
        stub = StubExecutionService()
        facade = DrawingGraphToolFacade(
            read_port=FakeDrawingGraphReadPort(source_facts={"page:1": page_facts()}),
            semantic_service=SemanticRecognitionService(client=None, execution_service=stub),
        )

        result = facade.recognize_page_semantics("page:1", target_types=("DrawingBlock",))

        self.assertFalse(result.persisted)
        self.assertEqual("succeeded", result.status)

    def test_dry_run_builds_image_inputs_and_returns_temporary_evidence_without_writes(self):
        stub = StubExecutionService(
            results=(RecognitionExecutionResult(recognition_run_id="run:temp:1", status="succeeded", validated_outputs=(observation_output(),)),)
        )
        input_builder = RecordingInputBuilder()
        service = self._service(stub, input_builder=input_builder)

        result = service.recognize_page(page_facts(), ("DrawingBlock",), "default", "p1")

        self.assertFalse(result.persisted)
        self.assertEqual(["block:1"], input_builder.build_calls)
        self.assertEqual("A1", result.observations[0].raw_text)
        self.assertEqual([], service.run_log.calls)
        self.assertEqual([], service.semantic_repository.calls)

    def test_dry_run_does_not_persist_to_cross_request_cache(self):
        stub = StubExecutionService(
            results=(RecognitionExecutionResult(recognition_run_id="run:temp:1", status="succeeded", validated_outputs=(observation_output(),)),)
        )
        cache = InMemorySemanticCacheService()
        service = self._service(stub, cache=cache, input_builder=RecordingInputBuilder())

        first = service.recognize_page(page_facts(), ("DrawingBlock",), "default", "p1")
        self.assertEqual(1, len(stub.calls))
        second = service.recognize_page(page_facts(), ("DrawingBlock",), "default", "p1")

        self.assertFalse(second.persisted)
        self.assertEqual(2, len(stub.calls))
        self.assertEqual("block:1", first.observations[0].target_element_id)

    def test_dry_run_allows_read_only_cache_lookup(self):
        cache = InMemorySemanticCacheService()
        cache.put(expected_cache_key(), (cached_observation(),))
        stub = StubExecutionService()
        service = self._service(stub, cache=cache, input_builder=RecordingInputBuilder())

        result = service.recognize_page(page_facts(), ("DrawingBlock",), "default", "p1")

        self.assertEqual([], stub.calls)
        self.assertFalse(result.persisted)
        self.assertEqual("obs:cached:block:1", result.observations[0].observation_id)

    def test_dry_run_cache_hit_never_calls_execution_or_writes(self):
        cache = InMemorySemanticCacheService()
        cache.put(expected_cache_key(), (cached_observation(),))
        stub = StubExecutionService()
        service = self._service(stub, cache=cache, input_builder=RecordingInputBuilder())

        result = service.recognize_page(page_facts(), ("DrawingBlock",), "default", "p1")

        self.assertEqual([], stub.calls)
        self.assertFalse(result.persisted)
        self.assertEqual("obs:cached:block:1", result.observations[0].observation_id)
        self.assertEqual([], service.run_log.calls)
        self.assertEqual([], service.semantic_repository.calls)


class SemanticWriteBatchTests(unittest.TestCase):
    def _service(self, stub):
        return SemanticRecognitionService(
            client=None,
            run_log=SpyRepository(),
            semantic_repository=SpyRepository(),
            input_builder=RecordingInputBuilder(),
            execution_service=stub,
        )

    def test_dry_run_produces_write_batch_without_persistence(self):
        stub = StubExecutionService(
            results=(
                RecognitionExecutionResult(
                    recognition_run_id="run:temp:1",
                    status="succeeded",
                    validated_outputs=(observation_output(),),
                ),
            )
        )
        service = self._service(stub)
        result = service.recognize_page(page_facts(), ("DrawingBlock",), "default", "p1")

        self.assertFalse(result.persisted)
        self.assertIsNotNone(result.write_batch)
        batch = result.write_batch
        self.assertTrue(batch.recognition_run_id.startswith("run:temp:"))
        self.assertTrue(batch.schema_valid)
        self.assertTrue(batch.scope_valid)
        self.assertTrue(batch.payload_sanitized)
        self.assertTrue(batch.audit_material_complete)
        self.assertEqual(1, len(batch.observations))
        self.assertIsNotNone(batch.sanitized_payload_envelope)
        self.assertEqual([], service.run_log.calls)
        self.assertEqual([], service.semantic_repository.calls)

    def test_write_batch_uses_stable_run_id(self):
        stub = StubExecutionService(
            results=(
                RecognitionExecutionResult(
                    recognition_run_id="run:temp:1",
                    status="succeeded",
                    validated_outputs=(observation_output(),),
                ),
            )
        )
        service = self._service(stub)
        result = service.recognize_page(page_facts(), ("DrawingBlock",), "default", "p1")
        self.assertEqual(result.recognition_run_id, result.write_batch.recognition_run_id)


if __name__ == "__main__":
    unittest.main()
