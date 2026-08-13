"""Offline contract matrix across all seven recognition tasks."""

from __future__ import annotations

import shutil
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

from PIL import Image

from drawing_graph.recognition_attempt_log import InMemoryRecognitionAttemptLog
from drawing_graph.recognition_execution import MultimodalRecognitionExecutionService
from drawing_graph.recognition_models import RecognitionExecutionPolicy
from drawing_graph.recognition_run_log import InMemoryRecognitionRunLog
from drawing_graph.semantic_cache import InMemorySemanticCacheService
from drawing_graph.semantic_client import FakeMultimodalRecognitionClient
from drawing_graph.semantic_image_inputs import SemanticImageInputBuilder
from drawing_graph.semantic_payload_store import InMemorySemanticPayloadStore
from drawing_graph.semantic_repository import InMemorySemanticEvidenceRepository
from drawing_graph.semantic_service import SemanticRecognitionService
from drawing_graph.tool_models import BBox, ElementEvidence, PageSourceFacts, SemanticTargetInput


@contextmanager
def _fixture_dir():
    base = Path(__file__).resolve().parents[1] / ".superpowers" / "sdd" / "tasks" / "contract-fixtures"
    path = base / f"case-{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _write_png(path: Path) -> None:
    Image.new("RGB", (1000, 800), "white").save(path, format="PNG")


def _element(element_id: str, element_type: str) -> ElementEvidence:
    return ElementEvidence(
        element_id=element_id,
        element_type=element_type,
        source_label=element_id,
        bbox=BBox(10, 10, 100, 100),
        normalized_bbox=BBox(0.01, 0.0125, 0.1, 0.125),
    )


_ELEMENTS = {
    "page_summary": (),
    "element_text_observation": (_element("caption:1", "BlockCaption"),),
    "block_semantic_identification": (_element("block:1", "DrawingBlock"),),
    "basic_info_interpretation": (_element("basic:1", "DrawingBasicInfo"),),
    "table_interpretation": (_element("table:1", "Table"), _element("caption:1", "TableCaption")),
    "section_label_observation": (_element("section:1", "CrossSection"),),
    "relation_evidence_extraction": (
        _element("block:1", "DrawingBlock"),
        _element("caption:1", "BlockCaption"),
    ),
}


def _facts(task_type: str, image_path: str) -> PageSourceFacts:
    return PageSourceFacts(
        page_id="page:1",
        image_path=image_path,
        elements=_ELEMENTS[task_type],
        image_size=(1000, 800),
        image_hash="hash:provided",
    )


def _target(task_type: str) -> SemanticTargetInput:
    element_id = {
        "element_text_observation": "caption:1",
        "block_semantic_identification": "block:1",
        "basic_info_interpretation": "basic:1",
        "table_interpretation": "table:1",
        "section_label_observation": "section:1",
        "relation_evidence_extraction": "block:1",
    }.get(task_type)
    target_type = {
        "page_summary": "DrawingPage",
        "element_text_observation": "BlockCaption",
        "block_semantic_identification": "DrawingBlock",
        "basic_info_interpretation": "DrawingBasicInfo",
        "table_interpretation": "Table",
        "section_label_observation": "CrossSection",
        "relation_evidence_extraction": "DrawingBlock",
    }[task_type]
    context_ids = ()
    if task_type in {"table_interpretation", "relation_evidence_extraction"}:
        context_ids = ("caption:1",)
    return SemanticTargetInput(
        target_id="t1",
        page_id="page:1",
        target_element_id=element_id,
        target_type=target_type,
        task_type=task_type,
        bbox=BBox(10, 10, 100, 100) if element_id is not None else None,
        normalized_bbox=BBox(0.01, 0.0125, 0.1, 0.125) if element_id is not None else None,
        context_element_ids=context_ids,
    )


def _payload(task_type: str) -> dict:
    return {
        "page_summary": {
            "target_id": "t1",
            "target_type": "DrawingPage",
            "status": "succeeded",
            "summary": "page text",
            "key_elements": [],
            "uncertainties": [],
        },
        "element_text_observation": {
            "target_id": "t1",
            "target_type": "BlockCaption",
            "status": "succeeded",
            "observations": [{"raw_text": "A1", "normalized_text": "A1", "confidence": 0.9, "status": "confirmed"}],
        },
        "block_semantic_identification": {
            "target_id": "t1",
            "target_type": "DrawingBlock",
            "status": "succeeded",
            "interpretation": {"summary": "beam"},
            "observations": [],
        },
        "basic_info_interpretation": {
            "target_id": "t1",
            "target_type": "DrawingBasicInfo",
            "status": "succeeded",
            "raw_text": "DWG-001",
            "summary": "drawing info",
        },
        "table_interpretation": {
            "target_id": "t1",
            "target_type": "Table",
            "status": "succeeded",
            "summary": "table summary",
            "caption_ref": "caption:1",
            "uncertainties": [],
        },
        "section_label_observation": {
            "target_id": "t1",
            "target_type": "CrossSection",
            "status": "succeeded",
            "raw_label": "A-A",
            "normalized_label": "A-A",
        },
        "relation_evidence_extraction": {
            "target_id": "t1",
            "target_type": "DrawingBlock",
            "status": "succeeded",
            "candidate_evidence": [
                {"relation_type": "CANDIDATE_CAPTION_OF", "supporting_ids": ["caption:1"]}
            ],
            "supporting_ids": ["caption:1"],
            "uncertainties": [],
        },
    }[task_type]


def _policy() -> RecognitionExecutionPolicy:
    return RecognitionExecutionPolicy(
        max_attempts=3,
        structure_repair_attempts=1,
        deadline_seconds=120.0,
    )


def _build_service(script, *, cache=None):
    client = FakeMultimodalRecognitionClient(script=script)
    run_log = InMemoryRecognitionRunLog()
    attempt_log = InMemoryRecognitionAttemptLog()
    payload_store = InMemorySemanticPayloadStore()
    repository = InMemorySemanticEvidenceRepository()
    cache_service = cache or InMemorySemanticCacheService()
    input_builder = SemanticImageInputBuilder(image_hash_provider=lambda image_path: "hash:provided")
    execution_service = MultimodalRecognitionExecutionService(provider=client)
    service = SemanticRecognitionService(
        client=client,
        run_log=run_log,
        semantic_repository=repository,
        cache_service=cache_service,
        input_builder=input_builder,
        execution_service=execution_service,
        payload_store=payload_store,
        attempt_log=attempt_log,
        execution_policy=_policy(),
    )
    return service, client, run_log, attempt_log, payload_store, repository, cache_service


class MultimodalRecognitionContractMatrixTests(unittest.TestCase):
    """All seven tasks satisfy valid/invalid/error/write-back contracts offline."""

    def test_valid_minimal_input_output_for_each_task(self) -> None:
        for task_type in _ELEMENTS:
            with self.subTest(task=task_type):
                with _fixture_dir() as tmp:
                    source = Path(tmp) / "page-1.png"
                    _write_png(source)
                    service, client, *_ = _build_service((_payload(task_type),))
                    result = service.recognize_targets(
                        _facts(task_type, str(source)),
                        (_target(task_type),),
                        "default",
                        "prompt-v1",
                        execution_policy=_policy(),
                    )
                self.assertEqual("succeeded", result.status)
                self.assertFalse(result.persisted)
                self.assertEqual(1, len(client.requests))
                if task_type == "page_summary":
                    self.assertIsNotNone(result.summary)
                elif task_type == "relation_evidence_extraction":
                    self.assertEqual(1, len(result.candidate_evidence))
                elif task_type in {"element_text_observation", "section_label_observation"}:
                    self.assertEqual(1, len(result.observations))
                else:
                    self.assertEqual(1, len(result.interpretations))

    def test_invalid_target_type_rejected_for_each_task(self) -> None:
        for task_type in _ELEMENTS:
            with self.subTest(task=task_type):
                with _fixture_dir() as tmp:
                    source = Path(tmp) / "page-1.png"
                    _write_png(source)
                    service, client, *_ = _build_service((_payload(task_type),))
                    target = _target(task_type)
                    bad_type = "Table" if task_type != "table_interpretation" else "DrawingBlock"
                    bad_target = SemanticTargetInput(
                        target_id=target.target_id,
                        page_id=target.page_id,
                        target_element_id=target.target_element_id,
                        target_type=bad_type,
                        task_type=target.task_type,
                        bbox=target.bbox,
                        normalized_bbox=target.normalized_bbox,
                        context_element_ids=target.context_element_ids,
                    )
                    result = service.recognize_targets(
                        _facts(task_type, str(source)),
                        (bad_target,),
                        "default",
                        "prompt-v1",
                        execution_policy=_policy(),
                    )
                self.assertEqual("recognition_failed", result.status)
                self.assertEqual(0, len(client.requests))
                self.assertIsNotNone(result.error_summary)

    def test_invalid_bbox_rejected_without_provider_call(self) -> None:
        with _fixture_dir() as tmp:
            source = Path(tmp) / "page-1.png"
            _write_png(source)
            service, client, *_ = _build_service((_payload("block_semantic_identification"),))
            target = _target("block_semantic_identification")
            bad_target = SemanticTargetInput(
                target_id=target.target_id,
                page_id=target.page_id,
                target_element_id=target.target_element_id,
                target_type=target.target_type,
                task_type=target.task_type,
                bbox=BBox(10, 10, 1200, 100),
                normalized_bbox=target.normalized_bbox,
            )
            result = service.recognize_targets(
                _facts("block_semantic_identification", str(source)),
                (bad_target,),
                "default",
                "prompt-v1",
                execution_policy=_policy(),
            )
        self.assertEqual("recognition_failed", result.status)
        self.assertEqual(0, len(client.requests))

    def test_invalid_context_rejected_without_provider_call(self) -> None:
        with _fixture_dir() as tmp:
            source = Path(tmp) / "page-1.png"
            _write_png(source)
            service, client, *_ = _build_service((_payload("table_interpretation"),))
            target = _target("table_interpretation")
            bad_target = SemanticTargetInput(
                target_id=target.target_id,
                page_id=target.page_id,
                target_element_id=target.target_element_id,
                target_type=target.target_type,
                task_type=target.task_type,
                bbox=target.bbox,
                normalized_bbox=target.normalized_bbox,
                context_element_ids=("missing:1",),
            )
            result = service.recognize_targets(
                _facts("table_interpretation", str(source)),
                (bad_target,),
                "default",
                "prompt-v1",
                execution_policy=_policy(),
            )
        self.assertEqual("recognition_failed", result.status)
        self.assertEqual(0, len(client.requests))

    def test_unknown_output_field_is_contract_failed(self) -> None:
        with _fixture_dir() as tmp:
            source = Path(tmp) / "page-1.png"
            _write_png(source)
            payload = _payload("block_semantic_identification")
            payload["extra_field"] = True
            service, client, *_ = _build_service((payload,))
            result = service.recognize_targets(
                _facts("block_semantic_identification", str(source)),
                (_target("block_semantic_identification"),),
                "default",
                "prompt-v1",
                execution_policy=RecognitionExecutionPolicy(
                    max_attempts=3,
                    structure_repair_attempts=0,
                    deadline_seconds=120.0,
                ),
            )
        self.assertEqual("contract_failed", result.status)
        self.assertEqual(0, len(result.interpretations))
        self.assertEqual(1, len(client.requests))

    def test_fact_level_escalation_is_contract_failed(self) -> None:
        with _fixture_dir() as tmp:
            source = Path(tmp) / "page-1.png"
            _write_png(source)
            payload = _payload("block_semantic_identification")
            payload["source_fact"] = "confirmed"
            service, client, *_ = _build_service((payload,))
            result = service.recognize_targets(
                _facts("block_semantic_identification", str(source)),
                (_target("block_semantic_identification"),),
                "default",
                "prompt-v1",
                execution_policy=_policy(),
            )
        self.assertEqual("contract_failed", result.status)
        self.assertEqual(0, len(result.interpretations))

    def test_provider_failure_modes(self) -> None:
        cases = {
            "http_429": ("provider_failed", 0),
            "http_5xx": ("provider_failed", 0),
            "timeout": ("provider_failed", 0),
            "http_401": ("provider_failed", 0),
            "schema_failure": ("provider_failed", 0),
        }
        for token, (expected_status, expected_outputs) in cases.items():
            with self.subTest(token=token):
                with _fixture_dir() as tmp:
                    source = Path(tmp) / "page-1.png"
                    _write_png(source)
                    service, _, *_ = _build_service((token,))
                    result = service.recognize_targets(
                        _facts("block_semantic_identification", str(source)),
                        (_target("block_semantic_identification"),),
                        "default",
                        "prompt-v1",
                        execution_policy=_policy(),
                    )
                self.assertEqual(expected_status, result.status)
                self.assertEqual(expected_outputs, len(result.interpretations))

    def test_429_retries_then_succeeds(self) -> None:
        with _fixture_dir() as tmp:
            source = Path(tmp) / "page-1.png"
            _write_png(source)
            service, client, *_ = _build_service(
                (("http_429", None), _payload("block_semantic_identification"))
            )
            result = service.recognize_targets(
                _facts("block_semantic_identification", str(source)),
                (_target("block_semantic_identification"),),
                "default",
                "prompt-v1",
                execution_policy=_policy(),
            )
        self.assertEqual("succeeded", result.status)
        self.assertEqual(2, len(client.requests))
        self.assertEqual(1, len(result.interpretations))

    def test_invalid_json_repairs_once_for_block_task(self) -> None:
        with _fixture_dir() as tmp:
            source = Path(tmp) / "page-1.png"
            _write_png(source)
            invalid = {"target_id": "t1", "target_type": "DrawingBlock", "status": "succeeded", "summary": "bad"}
            service, client, *_ = _build_service((invalid, _payload("block_semantic_identification")))
            result = service.recognize_targets(
                _facts("block_semantic_identification", str(source)),
                (_target("block_semantic_identification"),),
                "default",
                "prompt-v1",
                execution_policy=_policy(),
            )
        self.assertEqual("succeeded", result.status)
        self.assertEqual(2, len(client.requests))

    def test_deadline_exceeded_stops_before_provider(self) -> None:
        with _fixture_dir() as tmp:
            source = Path(tmp) / "page-1.png"
            _write_png(source)
            service, client, *_ = _build_service((_payload("block_semantic_identification"),))
            tight_policy = RecognitionExecutionPolicy(deadline_seconds=30.0)
            result = service.recognize_targets(
                _facts("block_semantic_identification", str(source)),
                (_target("block_semantic_identification"),),
                "default",
                "prompt-v1",
                execution_policy=tight_policy,
            )
        self.assertEqual("deadline_exceeded", result.status)
        self.assertEqual(0, len(client.requests))

    def test_attempts_usage_cost_and_latency_are_recorded(self) -> None:
        with _fixture_dir() as tmp:
            source = Path(tmp) / "page-1.png"
            _write_png(source)
            service, *_ = _build_service((_payload("block_semantic_identification"),))
            result = service.recognize_targets(
                _facts("block_semantic_identification", str(source)),
                (_target("block_semantic_identification"),),
                "default",
                "prompt-v1",
                execution_policy=_policy(),
            )
        self.assertEqual(1, len(result.attempts))
        self.assertIsNotNone(result.usage_summary)
        self.assertIsNotNone(result.cost_summary)
        self.assertIsNotNone(result.latency_summary)

    def test_cache_hit_does_not_call_provider_or_create_attempt(self) -> None:
        with _fixture_dir() as tmp:
            source = Path(tmp) / "page-1.png"
            _write_png(source)
            service, client, run_log, *_ = _build_service(
                (_payload("element_text_observation"),),
                cache=InMemorySemanticCacheService(),
            )
            first = service.recognize_targets(
                _facts("element_text_observation", str(source)),
                (_target("element_text_observation"),),
                "default",
                "prompt-v1",
                execution_policy=_policy(),
            )
            self.assertEqual(1, len(client.requests))
            second = service.recognize_targets(
                _facts("element_text_observation", str(source)),
                (_target("element_text_observation"),),
                "default",
                "prompt-v1",
                execution_policy=_policy(),
            )
        self.assertEqual(1, len(client.requests))
        self.assertEqual(0, len(second.attempts))
        self.assertEqual(0, len(run_log._runs))
        self.assertEqual(1, len(second.observations))
        self.assertEqual(first.observations[0].cache_key, second.observations[0].cache_key)

    def test_dry_run_is_zero_persistence(self) -> None:
        with _fixture_dir() as tmp:
            source = Path(tmp) / "page-1.png"
            _write_png(source)
            service, _, run_log, attempt_log, payload_store, repository, _ = _build_service(
                (_payload("block_semantic_identification"),)
            )
            service.recognize_targets(
                _facts("block_semantic_identification", str(source)),
                (_target("block_semantic_identification"),),
                "default",
                "prompt-v1",
                execution_policy=_policy(),
            )
        self.assertEqual(0, len(run_log._runs))
        self.assertEqual(0, len(attempt_log._attempts))
        self.assertEqual(0, len(payload_store._payloads))
        self.assertEqual(0, len(repository._observations))

    def test_write_back_matrix(self) -> None:
        for task_type in _ELEMENTS:
            with self.subTest(task=task_type):
                with _fixture_dir() as tmp:
                    source = Path(tmp) / "page-1.png"
                    _write_png(source)
                    service, _, run_log, attempt_log, payload_store, repository, _ = _build_service(
                        (_payload(task_type),)
                    )
                    result = service.recognize_targets(
                        _facts(task_type, str(source)),
                        (_target(task_type),),
                        "default",
                        "prompt-v1",
                        write_back=True,
                        execution_policy=_policy(),
                    )
                    run = run_log.get_run(result.recognition_run_id)
                    graph_evidence = repository.find_by_run(result.recognition_run_id)
                    graph_interpretations = repository.find_interpretations(
                        recognition_run_id=result.recognition_run_id,
                    )
                self.assertTrue(result.persisted)
                self.assertIsNotNone(result.payload_ref)
                self.assertEqual("succeeded", run.status)
                self.assertEqual(1, len(attempt_log.list_attempts(result.recognition_run_id)))
                if task_type in {"page_summary", "relation_evidence_extraction"}:
                    self.assertEqual(0, len(graph_evidence))
                    self.assertEqual(0, len(graph_interpretations))
                elif task_type in {"element_text_observation", "section_label_observation"}:
                    self.assertGreater(len(graph_evidence), 0)
                else:
                    self.assertGreater(len(graph_interpretations), 0)

    def test_partial_result_keeps_success_evidence(self) -> None:
        with _fixture_dir() as tmp:
            source = Path(tmp) / "page-1.png"
            _write_png(source)
            invalid_element = {
                "target_id": "t2",
                "target_type": "BlockCaption",
                "status": "succeeded",
                "summary": "unknown field",
            }
            service, *_ = _build_service(
                (_payload("block_semantic_identification"), invalid_element)
            )
            facts = PageSourceFacts(
                page_id="page:1",
                image_path=str(source),
                elements=(
                    _element("block:1", "DrawingBlock"),
                    _element("caption:1", "BlockCaption"),
                ),
                image_size=(1000, 800),
                image_hash="hash:provided",
            )
            targets = (
                SemanticTargetInput(
                    target_id="t1",
                    page_id="page:1",
                    target_element_id="block:1",
                    target_type="DrawingBlock",
                    task_type="block_semantic_identification",
                    bbox=BBox(10, 10, 100, 100),
                    normalized_bbox=BBox(0.01, 0.0125, 0.1, 0.125),
                ),
                SemanticTargetInput(
                    target_id="t2",
                    page_id="page:1",
                    target_element_id="caption:1",
                    target_type="BlockCaption",
                    task_type="element_text_observation",
                    bbox=BBox(10, 10, 100, 100),
                    normalized_bbox=BBox(0.01, 0.0125, 0.1, 0.125),
                ),
            )
            result = service.recognize_targets(
                facts,
                targets,
                "default",
                "prompt-v1",
                execution_policy=_policy(),
            )
        self.assertEqual("partial", result.status)
        self.assertEqual(1, len(result.interpretations))
        self.assertEqual(0, len(result.observations))


if __name__ == "__main__":
    unittest.main()
