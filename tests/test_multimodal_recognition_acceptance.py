"""Minimal offline acceptance loop for the productized recognition pipeline."""

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
from drawing_graph.recognition_redaction import RecognitionRedactor
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
    base = Path(__file__).resolve().parents[1] / ".superpowers" / "sdd" / "tasks" / "acceptance-fixtures"
    path = base / f"case-{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _write_png(path: Path) -> None:
    Image.new("RGB", (1000, 800), "white").save(path, format="PNG")


def _facts(image_path: str) -> PageSourceFacts:
    return PageSourceFacts(
        page_id="page:1",
        image_path=image_path,
        elements=(
            ElementEvidence(
                element_id="block:1",
                element_type="DrawingBlock",
                source_label="block:1",
                bbox=BBox(10, 10, 100, 100),
                normalized_bbox=BBox(0.01, 0.0125, 0.1, 0.125),
            ),
        ),
        image_size=(1000, 800),
        image_hash="hash:provided",
    )


def _target() -> SemanticTargetInput:
    return SemanticTargetInput(
        target_id="t1",
        page_id="page:1",
        target_element_id="block:1",
        target_type="DrawingBlock",
        task_type="block_semantic_identification",
        bbox=BBox(10, 10, 100, 100),
        normalized_bbox=BBox(0.01, 0.0125, 0.1, 0.125),
    )


def _payload() -> dict:
    return {
        "target_id": "t1",
        "target_type": "DrawingBlock",
        "status": "succeeded",
        "interpretation": {"summary": "beam"},
        "observations": [],
    }


def _policy() -> RecognitionExecutionPolicy:
    return RecognitionExecutionPolicy(
        max_attempts=3,
        structure_repair_attempts=1,
        deadline_seconds=120.0,
    )


def _build(script):
    client = FakeMultimodalRecognitionClient(script=script)
    run_log = InMemoryRecognitionRunLog()
    attempt_log = InMemoryRecognitionAttemptLog()
    payload_store = InMemorySemanticPayloadStore()
    repository = InMemorySemanticEvidenceRepository()
    cache = InMemorySemanticCacheService()
    input_builder = SemanticImageInputBuilder(image_hash_provider=lambda image_path: "hash:provided")
    service = SemanticRecognitionService(
        client=client,
        run_log=run_log,
        semantic_repository=repository,
        cache_service=cache,
        input_builder=input_builder,
        execution_service=MultimodalRecognitionExecutionService(provider=client),
        payload_store=payload_store,
        attempt_log=attempt_log,
        execution_policy=_policy(),
    )
    return service, client, run_log, attempt_log, payload_store, repository


class MultimodalRecognitionAcceptanceTests(unittest.TestCase):
    """One offline loop proves crop, retry, metrics, redaction and dry-run."""

    def test_minimal_loop_covers_cache_bbox_retry_metrics_redaction_and_dry_run(self) -> None:
        with _fixture_dir() as tmp:
            source = Path(tmp) / "page-1.png"
            _write_png(source)
            service, client, run_log, attempt_log, payload_store, repository = _build(
                (("http_429", None), _payload())
            )

            first = service.recognize_targets(
                _facts(str(source)),
                (_target(),),
                "default",
                "prompt-v1",
                execution_policy=_policy(),
            )

            self.assertEqual("succeeded", first.status)
            self.assertEqual(2, len(client.requests))
            self.assertEqual(2, len(first.attempts))
            self.assertEqual([1, 2], [attempt.attempt_number for attempt in first.attempts])
            self.assertEqual(1, len(first.interpretations))
            self.assertIsNotNone(first.usage_summary)
            self.assertIsNotNone(first.cost_summary)
            self.assertIsNotNone(first.latency_summary)

            prepared = client.requests[0].prepared_images[0]
            self.assertLess(prepared.output_size[0], 1000)
            self.assertLess(prepared.output_size[1], 800)

            redacted = RecognitionRedactor().redact_payload(
                {"summary": "ok", "api_key": "secret"}
            )
            self.assertEqual("<redacted>", redacted["api_key"])

            second = service.recognize_targets(
                _facts(str(source)),
                (_target(),),
                "default",
                "prompt-v1",
                execution_policy=_policy(),
            )
            self.assertEqual(0, len(second.attempts))
            self.assertEqual(2, len(client.requests))
            self.assertEqual(1, len(second.observations) + len(second.interpretations))

            self.assertEqual(0, len(run_log._runs))
            self.assertEqual(0, len(attempt_log._attempts))
            self.assertEqual(0, len(payload_store._payloads))
            self.assertEqual(0, len(repository._observations))
            self.assertEqual(0, len(repository._interpretations))


if __name__ == "__main__":
    unittest.main()
