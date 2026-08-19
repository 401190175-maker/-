"""Offline contract tests for the multimodal recognition execution service."""

from __future__ import annotations

import shutil
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

from PIL import Image

from drawing_graph.recognition_execution import MultimodalRecognitionExecutionService
from drawing_graph.recognition_models import (
    RecognitionExecutionPolicy,
    RecognitionExecutionRequest,
    RecognitionExecutionStatus,
)
from drawing_graph.recognition_retry import RecognitionAttemptExecutor
from drawing_graph.semantic_client import FakeMultimodalRecognitionClient
from drawing_graph.tool_models import BBox, ElementEvidence, PageSourceFacts, SemanticTargetInput


@contextmanager
def _fixture_dir():
    base = Path(__file__).resolve().parents[1] / ".superpowers" / "sdd" / "tasks" / "execution-fixtures"
    path = base / f"case-{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _write_png(path: Path, size: tuple[int, int] = (1000, 800)) -> None:
    Image.new("RGB", size, "white").save(path, format="PNG")


def _element() -> ElementEvidence:
    return ElementEvidence(
        element_id="block-1",
        element_type="DrawingBlock",
        bbox=BBox(10, 10, 100, 100),
        normalized_bbox=BBox(0.01, 0.0125, 0.1, 0.125),
        source_label="block-1",
    )


def _page_facts(image_path: str) -> PageSourceFacts:
    return PageSourceFacts(
        page_id="page-1",
        image_path=image_path,
        elements=(_element(),),
        image_size=(1000, 800),
        image_hash="hash-1",
    )


def _target() -> SemanticTargetInput:
    return SemanticTargetInput(
        target_id="target-1",
        page_id="page-1",
        target_type="DrawingBlock",
        task_type="block_semantic_identification",
        target_element_id="block-1",
        bbox=BBox(10, 10, 100, 100),
        normalized_bbox=BBox(0.01, 0.0125, 0.1, 0.125),
    )


def _request(
    *,
    write_back: bool = False,
    deadline_seconds: float = 120.0,
) -> RecognitionExecutionRequest:
    return RecognitionExecutionRequest(
        request_id="req-1",
        recognition_run_id="run-1",
        page_id="page-1",
        task_type="block_semantic_identification",
        targets=(_target(),),
        model_profile="default",
        prompt_version="prompt-v1",
        input_contract_version="1",
        output_contract_version="1",
        preprocessing_version="preprocess-v1",
        write_back=write_back,
        deadline_seconds=deadline_seconds,
    )


def _success_payload() -> dict:
    return {
        "target_id": "target-1",
        "target_type": "DrawingBlock",
        "status": "succeeded",
        "interpretation": {"summary": "a block"},
        "observations": [],
    }


def _invalid_payload() -> dict:
    return {
        "target_id": "target-1",
        "target_type": "DrawingBlock",
        "status": "succeeded",
        "summary": "unknown field for block task",
    }


def _service(
    provider,
    *,
    executor: RecognitionAttemptExecutor | None = None,
) -> MultimodalRecognitionExecutionService:
    return MultimodalRecognitionExecutionService(
        provider=provider,
        attempt_executor=executor,
    )


def _offline_executor() -> RecognitionAttemptExecutor:
    return RecognitionAttemptExecutor(
        clock=lambda: 100.0,
        sleeper=lambda delay: None,
        jitter=lambda: 0.0,
    )


class RecognitionExecutionServiceTests(unittest.TestCase):
    """The execution service orchestrates contract, image, prompt, attempts and metrics."""

    def test_execute_returns_outputs_attempts_and_metrics(self) -> None:
        with _fixture_dir() as tmp:
            source = Path(tmp) / "page-1.png"
            _write_png(source)
            provider = FakeMultimodalRecognitionClient(script=(_success_payload(),))
            result = _service(provider, executor=_offline_executor()).execute(
                _request(),
                _page_facts(str(source)),
                RecognitionExecutionPolicy(
                    deadline_seconds=120.0,
                    structure_repair_attempts=0,
                ),
            )
        self.assertIs(RecognitionExecutionStatus.SUCCEEDED, result.status)
        self.assertEqual(1, len(result.validated_outputs))
        self.assertEqual("a block", result.validated_outputs[0].output["interpretation"]["summary"])
        self.assertEqual(1, len(result.attempts))
        self.assertIsNotNone(result.usage_summary)
        self.assertIsNotNone(result.cost_summary)
        self.assertIsNotNone(result.latency_summary)
        self.assertFalse(result.persisted)
        self.assertIsNone(result.payload_ref)

    def test_input_failure_does_not_call_provider(self) -> None:
        with _fixture_dir() as tmp:
            source = Path(tmp) / "page-1.png"
            _write_png(source)
            provider = FakeMultimodalRecognitionClient(script=(_success_payload(),))
            request = _request()
            from drawing_graph.recognition_models import RecognitionExecutionRequest

            bad_request = RecognitionExecutionRequest(
                request_id=request.request_id,
                recognition_run_id=request.recognition_run_id,
                page_id="other-page",
                task_type=request.task_type,
                targets=request.targets,
                model_profile=request.model_profile,
                prompt_version=request.prompt_version,
            )
            result = _service(provider, executor=_offline_executor()).execute(
                bad_request,
                _page_facts(str(source)),
                RecognitionExecutionPolicy(deadline_seconds=120.0),
            )
        self.assertIs(RecognitionExecutionStatus.RECOGNITION_FAILED, result.status)
        self.assertEqual(0, len(result.attempts))
        self.assertEqual(0, len(provider.requests))
        self.assertIsNotNone(result.safe_error)

    def test_provider_retry_produces_multiple_attempts(self) -> None:
        with _fixture_dir() as tmp:
            source = Path(tmp) / "page-1.png"
            _write_png(source)
            provider = FakeMultimodalRecognitionClient(script=(("http_429", None), _success_payload()))
            result = _service(provider, executor=_offline_executor()).execute(
                _request(),
                _page_facts(str(source)),
                RecognitionExecutionPolicy(
                    max_attempts=2,
                    structure_repair_attempts=1,
                    deadline_seconds=120.0,
                ),
            )
        self.assertIs(RecognitionExecutionStatus.SUCCEEDED, result.status)
        self.assertEqual(2, len(result.attempts))
        self.assertEqual(2, len(provider.requests))

    def test_contract_failure_maps_to_contract_failed(self) -> None:
        with _fixture_dir() as tmp:
            source = Path(tmp) / "page-1.png"
            _write_png(source)
            provider = FakeMultimodalRecognitionClient(script=(_invalid_payload(),))
            result = _service(provider, executor=_offline_executor()).execute(
                _request(),
                _page_facts(str(source)),
                RecognitionExecutionPolicy(
                    deadline_seconds=120.0,
                    structure_repair_attempts=0,
                ),
            )
        self.assertIs(RecognitionExecutionStatus.CONTRACT_FAILED, result.status)
        self.assertEqual(0, len(result.validated_outputs))
        self.assertEqual(1, len(result.attempts))

    def test_deadline_exceeded_maps_to_deadline_exceeded_without_provider_call(self) -> None:
        with _fixture_dir() as tmp:
            source = Path(tmp) / "page-1.png"
            _write_png(source)
            provider = FakeMultimodalRecognitionClient(script=(_success_payload(),))
            result = _service(provider, executor=_offline_executor()).execute(
                _request(deadline_seconds=0.05),
                _page_facts(str(source)),
                RecognitionExecutionPolicy(deadline_seconds=0.05),
            )
        self.assertIs(RecognitionExecutionStatus.DEADLINE_EXCEEDED, result.status)
        self.assertEqual(0, len(result.attempts))
        self.assertEqual(0, len(provider.requests))

    def test_deadline_equal_to_single_call_timeout_still_calls_provider(self) -> None:
        """默认 60s 截止 + 60s 单次超时配置必须能发起一次 provider 调用。"""
        with _fixture_dir() as tmp:
            source = Path(tmp) / "page-1.png"
            _write_png(source)
            provider = FakeMultimodalRecognitionClient(script=(_success_payload(),))
            result = _service(provider, executor=_offline_executor()).execute(
                _request(deadline_seconds=60.0),
                _page_facts(str(source)),
                RecognitionExecutionPolicy(deadline_seconds=60.0),
            )
        self.assertIs(RecognitionExecutionStatus.SUCCEEDED, result.status)
        self.assertEqual(1, len(result.attempts))
        self.assertEqual(1, len(provider.requests))

    def test_dry_run_never_writes_persistence(self) -> None:
        service = _service(FakeMultimodalRecognitionClient(), executor=_offline_executor())
        self.assertFalse(hasattr(service, "run_log"))
        self.assertFalse(hasattr(service, "attempt_log"))
        self.assertFalse(hasattr(service, "payload_store"))
        self.assertFalse(hasattr(service, "cache_service"))

    def test_execution_module_stays_within_boundaries(self) -> None:
        import drawing_graph.recognition_execution as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        import_lines = "\n".join(
            line.strip().lower()
            for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))
        )
        for forbidden in (
            "neo4j",
            "repository",
            "cypher",
            "httpx",
            "qwen",
            "facade",
            "os.environ",
            "pathlib",
            "run_log",
            "payload_store",
            "cache",
            "semantic_service",
        ):
            self.assertNotIn(forbidden, import_lines)


class StableRunIdTests(unittest.TestCase):
    def test_result_reuses_request_run_id(self) -> None:
        with _fixture_dir() as tmp:
            source = Path(tmp) / "page-1.png"
            _write_png(source)
            provider = FakeMultimodalRecognitionClient(script=(_success_payload(),))
            result = _service(provider, executor=_offline_executor()).execute(
                _request(),
                _page_facts(str(source)),
                RecognitionExecutionPolicy(
                    deadline_seconds=120.0,
                    structure_repair_attempts=0,
                ),
            )
        self.assertEqual("run-1", result.recognition_run_id)

    def test_failure_result_reuses_request_run_id(self) -> None:
        with _fixture_dir() as tmp:
            source = Path(tmp) / "page-1.png"
            _write_png(source)
            provider = FakeMultimodalRecognitionClient(script=("http_5xx",))
            result = _service(provider, executor=_offline_executor()).execute(
                _request(),
                _page_facts(str(source)),
                RecognitionExecutionPolicy(
                    deadline_seconds=120.0,
                    structure_repair_attempts=0,
                ),
            )
        self.assertEqual("run-1", result.recognition_run_id)


if __name__ == "__main__":
    unittest.main()
