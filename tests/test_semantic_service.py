"""Semantic service execution-grouping and cache-order contract tests."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from drawing_graph.recognition_execution import MultimodalRecognitionExecutionService
from drawing_graph.recognition_models import (
    RecognitionAttempt,
    RecognitionExecutionResult,
    RecognitionProviderUsage,
    ValidatedRecognitionOutput,
)
from drawing_graph.semantic_cache import (
    InMemorySemanticCacheService,
    SemanticCacheKeyInput,
    build_semantic_cache_key,
)
from drawing_graph.semantic_client import FakeMultimodalRecognitionClient
from drawing_graph.semantic_image_inputs import SemanticImageInputBuilder
from drawing_graph.semantic_models import (
    BasicInfoInterpretation,
    BlockInterpretation,
    TableInterpretation,
    TextObservation,
)
from drawing_graph.semantic_models import PageSummaryResult
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


def expected_cache_key_for_block(element_id: str) -> str:
    return build_semantic_cache_key(
        SemanticCacheKeyInput(
            image_hash="hash:provided",
            bbox=(1, 2, 3, 4),
            target_element_id=element_id,
            task_type="element_text_observation",
            model_profile="default",
            model_version="fake-v1",
            prompt_version="prompt-v1",
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


class SemanticExecutionCacheOrderTests(unittest.TestCase):
    """Cache hits precede run, attempt and provider; failures never cached."""

    def _service(self, stub: StubExecutionService, cache=None, run_log=None, client=None) -> SemanticRecognitionService:
        return SemanticRecognitionService(
            client=client or FailingClientOnCall(),
            run_log=run_log or SpyRunLog(),
            cache_service=cache or InMemorySemanticCacheService(),
            execution_service=stub,
            input_builder=RecordingInputBuilder(),
        )

    def test_cache_hit_never_calls_execution_service_or_run_log(self) -> None:
        cache = InMemorySemanticCacheService()
        cache.put(expected_cache_key(), (cached_observation(),))
        stub = StubExecutionService()
        run_log = SpyRunLog()
        result = self._service(stub, cache, run_log).recognize_page(
            page_facts(_element("block:1")),
            ("DrawingBlock",),
            "default",
            "p1",
            write_back=True,
        )

        self.assertEqual([], stub.calls)
        self.assertEqual([], run_log.calls)
        self.assertFalse(result.persisted)

    def test_only_cache_misses_are_sent_to_execution_service(self) -> None:
        cache = InMemorySemanticCacheService()
        cache.put(expected_cache_key(), (cached_observation(),))
        stub = StubExecutionService()
        result = self._service(stub, cache).recognize_page(
            page_facts(_element("block:1"), _element("block:2")),
            ("DrawingBlock",),
            "default",
            "p1",
        )

        self.assertEqual(1, len(stub.calls))
        request = stub.calls[0][0]
        self.assertEqual(("block:2",), tuple(item.target_element_id for item in request.targets))
        self.assertEqual("obs:cached:block:1", result.observations[0].observation_id)

    def test_contract_failed_result_never_enters_success_cache(self) -> None:
        cache = InMemorySemanticCacheService()
        stub = StubExecutionService(
            results=(
                RecognitionExecutionResult(recognition_run_id="run:1", status="contract_failed"),
            )
        )
        self._service(stub, cache).recognize_targets(
            page_facts(_element("block:1")),
            (target(target_id="t1", element_id="block:1"),),
            "default",
            "prompt-v1",
        )

        self.assertIsNone(cache.get(expected_cache_key_for_block("block:1")))

    def test_failed_group_does_not_create_persistent_run_in_dry_run(self) -> None:
        stub = StubExecutionService(
            results=(RecognitionExecutionResult(recognition_run_id="run:1", status="provider_failed"),)
        )
        run_log = SpyRunLog()
        result = self._service(stub, run_log=run_log).recognize_targets(
            page_facts(_element("block:1")),
            (target(target_id="t1", element_id="block:1"),),
            "default",
            "prompt-v1",
        )

        self.assertFalse(result.persisted)
        self.assertEqual([], run_log.calls)


class SemanticOutputProjectionTests(unittest.TestCase):
    """Contract-valid outputs project to existing semantic DTOs with provenance."""

    def _result(self, *validated_outputs, status: str = "succeeded") -> RecognitionExecutionResult:
        return RecognitionExecutionResult(
            recognition_run_id="run:1",
            status=status,
            validated_outputs=validated_outputs,
        )

    def test_block_output_projects_to_block_interpretation(self) -> None:
        facts = page_facts(_element("block:1"))
        stub = StubExecutionService(
            results=(
                self._result(
                    ValidatedRecognitionOutput(
                        task_type="block_semantic_identification",
                        target_id="t1",
                        target_type="DrawingBlock",
                        status="succeeded",
                        output={
                            "interpretation": {
                                "summary": "beam",
                                "interpreted_type": "structural",
                            }
                        },
                    )
                ),
            )
        )
        service = SemanticRecognitionService(client=None, cache_service=None, execution_service=stub)
        result = service.recognize_targets(
            facts,
            (target(target_id="t1", element_id="block:1"),),
            "default",
            "prompt-v1",
        )

        self.assertEqual(1, len(result.interpretations))
        interpretation = result.interpretations[0]
        self.assertIsInstance(interpretation, BlockInterpretation)
        self.assertEqual("beam", interpretation.summary)
        self.assertEqual("block:1", interpretation.block_id)
        self.assertEqual("run:1", interpretation.recognition_run_id)
        self.assertEqual("default", interpretation.model_profile)
        self.assertEqual("prompt-v1", interpretation.prompt_version)
        self.assertEqual("1", interpretation.input_contract_version)
        self.assertEqual("preprocess-v1", interpretation.preprocessing_version)

    def test_block_projection_normalizes_structured_list_items_to_text(self) -> None:
        facts = page_facts(_element("block:1"))
        stub = StubExecutionService(
            results=(
                self._result(
                    ValidatedRecognitionOutput(
                        task_type="block_semantic_identification",
                        target_id="t1",
                        target_type="DrawingBlock",
                        status="succeeded",
                        output={
                            "interpretation": {
                                "summary": "beam",
                                "components": [
                                    {"name": "wall", "count": 2},
                                    "",
                                    "cap beam",
                                ],
                            }
                        },
                    )
                ),
            )
        )
        service = SemanticRecognitionService(client=None, cache_service=None, execution_service=stub)

        result = service.recognize_targets(
            facts,
            (target(target_id="t1", element_id="block:1"),),
            "default",
            "prompt-v1",
        )

        self.assertEqual(('{"count":2,"name":"wall"}', "cap beam"), result.interpretations[0].components)

    def test_block_projection_normalizes_provider_analysis_status(self) -> None:
        facts = page_facts(_element("block:1"))
        stub = StubExecutionService(
            results=(
                self._result(
                    ValidatedRecognitionOutput(
                        task_type="block_semantic_identification",
                        target_id="t1",
                        target_type="DrawingBlock",
                        status="succeeded",
                        output={
                            "interpretation": {
                                "summary": "beam",
                                "analysis_status": "complete",
                            }
                        },
                    )
                ),
            )
        )
        service = SemanticRecognitionService(client=None, cache_service=None, execution_service=stub)

        result = service.recognize_targets(
            facts,
            (target(target_id="t1", element_id="block:1"),),
            "default",
            "prompt-v1",
        )

        self.assertEqual("interpreted", result.interpretations[0].analysis_status.value)

    def test_block_observations_link_to_interpretation_support_chain(self) -> None:
        facts = page_facts(_element("block:1"))
        stub = StubExecutionService(
            results=(
                self._result(
                    ValidatedRecognitionOutput(
                        task_type="block_semantic_identification",
                        target_id="t1",
                        target_type="DrawingBlock",
                        status="succeeded",
                        output={
                            "interpretation": {
                                "summary": "beam",
                                "interpreted_type": "structural",
                            },
                            "observations": [
                                {
                                    "raw_text": "W250x89",
                                    "normalized_text": "W250x89",
                                    "status": "succeeded",
                                    "confidence": 0.9,
                                },
                                {
                                    "raw_text": "A-A",
                                    "normalized_text": "A-A",
                                    "status": "succeeded",
                                    "confidence": 0.8,
                                },
                            ],
                        },
                    )
                ),
            )
        )
        service = SemanticRecognitionService(client=None, cache_service=None, execution_service=stub)

        result = service.recognize_targets(
            facts,
            (target(target_id="t1", element_id="block:1"),),
            "default",
            "prompt-v1",
        )

        self.assertEqual(2, len(result.observations))
        self.assertEqual(
            ("obs:run:1:block:1:0", "obs:run:1:block:1:1"),
            tuple(observation.observation_id for observation in result.observations),
        )
        self.assertEqual(
            ("obs:run:1:block:1:0", "obs:run:1:block:1:1"),
            result.interpretations[0].supported_by_observation_ids,
        )

    def test_element_text_output_projects_to_text_observation(self) -> None:
        facts = page_facts(_element("caption:1", "BlockCaption"))
        stub = StubExecutionService(
            results=(
                self._result(
                    ValidatedRecognitionOutput(
                        task_type="element_text_observation",
                        target_id="t1",
                        target_type="BlockCaption",
                        status="succeeded",
                        output={
                            "observations": [
                                {"raw_text": "A1", "normalized_text": "A1", "confidence": 0.9, "status": "confirmed"}
                            ]
                        },
                    )
                ),
            )
        )
        service = SemanticRecognitionService(client=None, cache_service=None, execution_service=stub)
        result = service.recognize_targets(
            facts,
            (
                target(
                    target_id="t1",
                    element_id="caption:1",
                    element_type="BlockCaption",
                    task_type="element_text_observation",
                ),
            ),
            "default",
            "prompt-v1",
        )

        self.assertEqual(1, len(result.observations))
        observation = result.observations[0]
        self.assertIsInstance(observation, TextObservation)
        self.assertEqual("A1", observation.raw_text)
        self.assertEqual("caption:1", observation.target_element_id)
        self.assertEqual("hash:provided", observation.image_hash)
        self.assertEqual("default", observation.model_profile)
        self.assertEqual("prompt-v1", observation.prompt_version)
        self.assertEqual("1", observation.input_contract_version)
        self.assertEqual("preprocess-v1", observation.preprocessing_version)

    def test_section_label_output_projects_to_text_observation(self) -> None:
        facts = page_facts(_element("section:1", "CrossSection"))
        stub = StubExecutionService(
            results=(
                self._result(
                    ValidatedRecognitionOutput(
                        task_type="section_label_observation",
                        target_id="t1",
                        target_type="CrossSection",
                        status="succeeded",
                        output={"raw_label": "A-A", "normalized_label": "A-A"},
                        confidence=0.8,
                    )
                ),
            )
        )
        service = SemanticRecognitionService(client=None, cache_service=None, execution_service=stub)
        result = service.recognize_targets(
            facts,
            (
                target(
                    target_id="t1",
                    element_id="section:1",
                    element_type="CrossSection",
                    task_type="section_label_observation",
                ),
            ),
            "default",
            "prompt-v1",
        )

        self.assertEqual(1, len(result.observations))
        self.assertEqual("A-A", result.observations[0].raw_text)
        self.assertEqual("A-A", result.observations[0].normalized_text)

    def test_ambiguous_output_is_not_projected(self) -> None:
        facts = page_facts(_element("block:1"))
        stub = StubExecutionService(
            results=(
                self._result(
                    ValidatedRecognitionOutput(
                        task_type="block_semantic_identification",
                        target_id="t1",
                        target_type="DrawingBlock",
                        status="ambiguous",
                        output={},
                    )
                ),
            )
        )
        service = SemanticRecognitionService(client=None, cache_service=None, execution_service=stub)
        result = service.recognize_targets(
            facts,
            (target(target_id="t1", element_id="block:1"),),
            "default",
            "prompt-v1",
        )

        self.assertEqual((), result.observations)
        self.assertEqual((), result.interpretations)

    def test_contract_failed_group_is_not_projected(self) -> None:
        facts = page_facts(_element("block:1"))
        stub = StubExecutionService(results=(self._result(status="contract_failed"),))
        service = SemanticRecognitionService(client=None, cache_service=None, execution_service=stub)
        result = service.recognize_targets(
            facts,
            (target(target_id="t1", element_id="block:1"),),
            "default",
            "prompt-v1",
        )

        self.assertEqual((), result.observations)
        self.assertEqual((), result.interpretations)

    def test_source_facts_are_not_modified_by_projection(self) -> None:
        facts = page_facts(_element("block:1"))
        stub = StubExecutionService(
            results=(
                self._result(
                    ValidatedRecognitionOutput(
                        task_type="block_semantic_identification",
                        target_id="t1",
                        target_type="DrawingBlock",
                        status="succeeded",
                        output={"interpretation": {"summary": "beam"}},
                    )
                ),
            )
        )
        service = SemanticRecognitionService(client=None, cache_service=None, execution_service=stub)
        result = service.recognize_targets(
            facts,
            (target(target_id="t1", element_id="block:1"),),
            "default",
            "prompt-v1",
        )

        self.assertEqual("block:1", facts.elements[0].source_label)
        self.assertFalse(hasattr(result.interpretations[0], "block_type"))


class SemanticTransientOutputTests(unittest.TestCase):
    """Page summaries and relation evidence stay transient, never graph nodes."""

    def _result(self, *validated_outputs, status: str = "succeeded", attempts=()) -> RecognitionExecutionResult:
        return RecognitionExecutionResult(
            recognition_run_id="run:1",
            status=status,
            validated_outputs=validated_outputs,
            attempts=attempts,
        )

    def test_page_summary_output_is_carried_as_transient_summary(self) -> None:
        facts = page_facts()
        stub = StubExecutionService(
            results=(
                self._result(
                    ValidatedRecognitionOutput(
                        task_type="page_summary",
                        target_id="t-page",
                        target_type="DrawingPage",
                        status="succeeded",
                        output={
                            "summary": "page text",
                            "key_elements": ["title"],
                            "uncertainties": [],
                        },
                    )
                ),
            )
        )
        service = SemanticRecognitionService(client=None, cache_service=None, execution_service=stub)
        page_target = SemanticTargetInput(
            target_id="t-page",
            page_id="page:1",
            target_type="DrawingPage",
            task_type="page_summary",
        )
        result = service.recognize_targets(
            facts,
            (page_target,),
            "default",
            "prompt-v1",
        )

        self.assertIsInstance(result.summary, PageSummaryResult)
        self.assertEqual("page text", result.summary.summary)
        self.assertEqual(("title",), result.summary.key_elements)
        self.assertEqual("run:1", result.summary.recognition_run_id)
        self.assertEqual((), result.observations)
        self.assertEqual((), result.interpretations)

    def test_relation_evidence_is_candidate_only_and_never_writes(self) -> None:
        facts = page_facts(_element("block:1"), _element("caption:1", "BlockCaption"))
        stub = StubExecutionService(
            results=(
                self._result(
                    ValidatedRecognitionOutput(
                        task_type="relation_evidence_extraction",
                        target_id="t1",
                        target_type="DrawingBlock",
                        status="succeeded",
                        output={
                            "candidate_evidence": [
                                {
                                    "relation_type": "CANDIDATE_CAPTION_OF",
                                    "supporting_ids": ["caption:1"],
                                }
                            ],
                            "supporting_ids": ["caption:1"],
                            "uncertainties": [],
                        },
                    )
                ),
            )
        )
        service = SemanticRecognitionService(client=None, cache_service=None, execution_service=stub)
        result = service.recognize_targets(
            facts,
            (
                target(
                    target_id="t1",
                    element_id="block:1",
                    task_type="relation_evidence_extraction",
                ),
            ),
            "default",
            "prompt-v1",
        )

        self.assertEqual(1, len(result.candidate_evidence))
        evidence = result.candidate_evidence[0]
        self.assertEqual("candidate_relation", evidence.status)
        self.assertEqual("CANDIDATE_CAPTION_OF", evidence.relation_type)
        self.assertEqual("t1", evidence.source_target_id)
        self.assertEqual(("caption:1",), evidence.supporting_target_ids)
        self.assertEqual((), result.interpretations)

    def test_result_metrics_aggregate_attempts_usage_cost_latency(self) -> None:
        attempt = RecognitionAttempt(
            attempt_id="attempt:1",
            recognition_run_id="run:1",
            attempt_number=1,
            task_type="block_semantic_identification",
            provider="fake",
            model_name="fake-multimodal",
            request_fingerprint="fp-1",
            prompt_version="prompt-v1",
            output_contract_version="1",
            status="succeeded",
            latency_ms=10.0,
            usage=RecognitionProviderUsage(input_tokens=10, output_tokens=5, status="available"),
        )
        stub = StubExecutionService(
            results=(self._result(attempts=(attempt,)),),
        )
        service = SemanticRecognitionService(client=None, cache_service=None, execution_service=stub)
        result = service.recognize_targets(
            page_facts(_element("block:1")),
            (target(target_id="t1", element_id="block:1"),),
            "default",
            "prompt-v1",
        )

        self.assertEqual((attempt,), result.attempts)
        self.assertEqual(10, result.usage_summary.input_tokens)
        self.assertIsNotNone(result.cost_summary)
        self.assertEqual(10.0, result.latency_summary.provider_ms)

    def test_existing_result_construction_keeps_new_defaults(self) -> None:
        from drawing_graph.semantic_service import SemanticRecognitionResult

        result = SemanticRecognitionResult(
            recognition_run_id="run:1",
            status="succeeded",
            observations=(),
            persisted=False,
        )
        self.assertIsNone(result.summary)
        self.assertEqual((), result.candidate_evidence)
        self.assertEqual((), result.attempts)
        self.assertIsNone(result.payload_ref)
        self.assertEqual((), result.warnings)


class SemanticPartialResultTests(unittest.TestCase):
    """Partial runs keep successful evidence and never fabricate failures."""

    def test_mixed_groups_yield_partial_and_keep_success_evidence(self) -> None:
        facts = page_facts(_element("block:1"), _element("caption:1", "BlockCaption"))
        stub = StubExecutionService(
            results=(
                RecognitionExecutionResult(
                    recognition_run_id="run:1",
                    status="succeeded",
                    validated_outputs=(
                        ValidatedRecognitionOutput(
                            task_type="block_semantic_identification",
                            target_id="t1",
                            target_type="DrawingBlock",
                            status="succeeded",
                            output={"interpretation": {"summary": "beam"}},
                        ),
                    ),
                ),
                RecognitionExecutionResult(recognition_run_id="run:1", status="contract_failed"),
            )
        )
        cache = InMemorySemanticCacheService()
        service = SemanticRecognitionService(
            client=None,
            cache_service=cache,
            execution_service=stub,
        )
        result = service.recognize_targets(
            facts,
            (
                target(target_id="t1", element_id="block:1"),
                target(
                    target_id="t2",
                    element_id="caption:1",
                    element_type="BlockCaption",
                    task_type="element_text_observation",
                ),
            ),
            "default",
            "prompt-v1",
        )

        self.assertEqual("partial", result.status)
        self.assertEqual(1, len(result.interpretations))
        self.assertEqual("beam", result.interpretations[0].summary)
        self.assertEqual((), result.observations)

    def test_all_failed_groups_use_first_failure_status(self) -> None:
        facts = page_facts(_element("block:1"), _element("caption:1", "BlockCaption"))
        stub = StubExecutionService(
            results=(
                RecognitionExecutionResult(recognition_run_id="run:1", status="contract_failed"),
                RecognitionExecutionResult(recognition_run_id="run:1", status="provider_failed"),
            )
        )
        service = SemanticRecognitionService(client=None, cache_service=None, execution_service=stub)
        result = service.recognize_targets(
            facts,
            (
                target(target_id="t1", element_id="block:1"),
                target(
                    target_id="t2",
                    element_id="caption:1",
                    element_type="BlockCaption",
                    task_type="element_text_observation",
                ),
            ),
            "default",
            "prompt-v1",
        )

        self.assertEqual("contract_failed", result.status)
        self.assertEqual((), result.interpretations)

    def test_success_plus_ambiguous_is_partial(self) -> None:
        facts = page_facts(_element("block:1"), _element("caption:1", "BlockCaption"))
        stub = StubExecutionService(
            results=(
                RecognitionExecutionResult(
                    recognition_run_id="run:1",
                    status="succeeded",
                    validated_outputs=(
                        ValidatedRecognitionOutput(
                            task_type="block_semantic_identification",
                            target_id="t1",
                            target_type="DrawingBlock",
                            status="succeeded",
                            output={"interpretation": {"summary": "beam"}},
                        ),
                    ),
                ),
                RecognitionExecutionResult(
                    recognition_run_id="run:1",
                    status="ambiguous",
                    validated_outputs=(
                        ValidatedRecognitionOutput(
                            task_type="element_text_observation",
                            target_id="t2",
                            target_type="BlockCaption",
                            status="ambiguous",
                            output={},
                        ),
                    ),
                ),
            )
        )
        service = SemanticRecognitionService(client=None, cache_service=None, execution_service=stub)
        result = service.recognize_targets(
            facts,
            (
                target(target_id="t1", element_id="block:1"),
                target(
                    target_id="t2",
                    element_id="caption:1",
                    element_type="BlockCaption",
                    task_type="element_text_observation",
                ),
            ),
            "default",
            "prompt-v1",
        )

        self.assertEqual("partial", result.status)
        self.assertEqual(1, len(result.interpretations))


class SemanticServiceCacheOutcomeTests(unittest.TestCase):
    def _service(self, *, stub, cache, input_builder=None):
        return SemanticRecognitionService(
            client=None,
            run_log=SpyRunLog(),
            cache_service=cache,
            execution_service=stub,
            input_builder=input_builder or RecordingInputBuilder(),
        )

    def test_cache_hit_reports_hit_with_reused_evidence_ids(self):
        cache = InMemorySemanticCacheService()
        cache_key = build_semantic_cache_key(
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
        cache.put(cache_key, (cached_observation(),))
        stub = StubExecutionService()
        service = self._service(stub=stub, cache=cache)

        result = service.recognize_page(
            page_facts(_element("block:1")),
            ("DrawingBlock",),
            "default",
            "p1",
        )

        self.assertEqual(1, len(result.cache_outcomes))
        outcome = result.cache_outcomes[0]
        self.assertEqual("hit", outcome.disposition)
        self.assertEqual(("obs:cached:block:1",), outcome.reused_evidence_ids)
        self.assertFalse(outcome.provider_called)
        self.assertEqual([], stub.calls)

    def test_cache_miss_reports_miss_and_provider_called(self):
        cache = InMemorySemanticCacheService()
        stub = StubExecutionService(
            results=(
                RecognitionExecutionResult(
                    recognition_run_id="run:temp:1",
                    status="succeeded",
                    validated_outputs=(),
                ),
            )
        )
        service = self._service(stub=stub, cache=cache)

        result = service.recognize_targets(
            page_facts(_element("block:1")),
            (target(target_id="t1", element_id="block:1", task_type="element_text_observation"),),
            "default",
            "prompt-v1",
        )

        self.assertEqual(1, len(result.cache_outcomes))
        outcome = result.cache_outcomes[0]
        self.assertEqual("miss", outcome.disposition)
        self.assertTrue(outcome.provider_called)
        self.assertEqual((), outcome.reused_evidence_ids)

    def test_result_without_cache_outcomes_is_backward_compatible(self):
        from drawing_graph.semantic_service import SemanticRecognitionResult

        result = SemanticRecognitionResult(
            recognition_run_id="run:1",
            status="succeeded",
            observations=(),
            persisted=False,
        )
        self.assertEqual((), result.cache_outcomes)


if __name__ == "__main__":
    unittest.main()
