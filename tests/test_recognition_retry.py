"""Offline contract tests for provider error classification and retry."""

from __future__ import annotations

import unittest
from dataclasses import replace

import httpx

from drawing_graph.recognition_image_preprocessing import PreparedRecognitionImage
from drawing_graph.recognition_models import (
    RecognitionAttemptStatus,
    RecognitionExecutionPolicy,
    RecognitionImageRole,
    ValidatedRecognitionRequest,
)
from drawing_graph.recognition_prompting import RenderedRecognitionPrompt
from drawing_graph.recognition_retry import (
    RecognitionAttemptExecutor,
    RecognitionProviderError,
    RecognitionRetryPolicy,
    classify_http_status,
    classify_exception,
    parse_retry_after,
)
from drawing_graph.recognition_tasks import page_summary_spec
from drawing_graph.semantic_client import FakeMultimodalRecognitionClient, RecognitionClientRequest
from drawing_graph.tool_models import BBox, SemanticTargetInput


class ProviderErrorClassificationTests(unittest.TestCase):
    """HTTP, transport and timeout errors map to stable provider categories."""

    def test_429_is_retryable_rate_limited_with_retry_after(self) -> None:
        error = classify_http_status(429, retry_after_header="5")
        self.assertEqual("rate_limited", error.category.value)
        self.assertTrue(error.retryable)
        self.assertEqual(5.0, error.retry_after_seconds)

    def test_retry_after_unparseable_or_over_cap_yields_none(self) -> None:
        self.assertIsNone(parse_retry_after("abc"))
        self.assertIsNone(parse_retry_after("99999"))
        self.assertEqual(2.5, parse_retry_after("2.5"))

    def test_temporary_5xx_is_retryable(self) -> None:
        for status in (500, 502, 503, 504):
            with self.subTest(status=status):
                error = classify_http_status(status)
                self.assertEqual("temporary", error.category.value)
                self.assertTrue(error.retryable)

    def test_408_is_retryable_timeout(self) -> None:
        error = classify_http_status(408)
        self.assertEqual("timeout", error.category.value)
        self.assertTrue(error.retryable)

    def test_authentication_and_permission_are_terminal(self) -> None:
        auth = classify_http_status(401)
        self.assertEqual("authentication", auth.category.value)
        self.assertFalse(auth.retryable)
        permission = classify_http_status(403)
        self.assertEqual("permission", permission.category.value)
        self.assertFalse(permission.retryable)

    def test_other_4xx_is_permanent_terminal(self) -> None:
        for status in (400, 404, 422):
            with self.subTest(status=status):
                error = classify_http_status(status)
                self.assertEqual("permanent", error.category.value)
                self.assertFalse(error.retryable)

    def test_timeout_exception_is_retryable_timeout(self) -> None:
        error = classify_exception(httpx.TimeoutException("slow"))
        self.assertEqual("timeout", error.category.value)
        self.assertTrue(error.retryable)

    def test_connection_error_is_retryable_temporary(self) -> None:
        error = classify_exception(httpx.ConnectError("reset"))
        self.assertEqual("temporary", error.category.value)
        self.assertTrue(error.retryable)

    def test_error_object_holds_only_safe_fields(self) -> None:
        error = RecognitionProviderError(
            category="invalid_response",
            retryable=False,
            safe_message="provider returned malformed JSON",
        )
        self.assertEqual("invalid_response", error.category.value)
        self.assertFalse(error.retryable)
        self.assertIsNone(error.retry_after_seconds)
        self.assertFalse(hasattr(error, "headers"))
        self.assertFalse(hasattr(error, "body"))

    def test_error_validation_rejects_unknown_category_and_negative_retry_after(self) -> None:
        with self.assertRaises(ValueError):
            RecognitionProviderError(category="bogus", retryable=False, safe_message="x")
        with self.assertRaises(ValueError):
            RecognitionProviderError(
                category="temporary",
                retryable=True,
                safe_message="x",
                retry_after_seconds=-1,
            )


def _prompt() -> RenderedRecognitionPrompt:
    return RenderedRecognitionPrompt(
        system_instruction="system",
        user_instruction="user",
        schema_id="output/page-summary",
        schema_version="1",
        prompt_version="prompt-v1",
        fingerprint="f" * 64,
        image_role_order=("page",),
    )


def _image() -> PreparedRecognitionImage:
    return PreparedRecognitionImage(
        role=RecognitionImageRole.PAGE,
        mime="image/png",
        content=b"\x89PNG\r\n\x1a\n",
        source_hash="a" * 64,
        prepared_hash="b" * 64,
        source_size=(100, 80),
        crop_bbox=BBox(0, 0, 100, 80),
        padding=0,
        output_size=(100, 80),
        scale=1.0,
        preprocessing_version="preprocess-v1",
    )


def _provider_request() -> RecognitionClientRequest:
    return RecognitionClientRequest(
        model_profile="default",
        rendered_prompt=_prompt(),
        prepared_images=(_image(),),
        output_contract_version="1",
        request_fingerprint="fp-1",
        timeout_seconds=60.0,
    )


def _validated_request() -> ValidatedRecognitionRequest:
    return ValidatedRecognitionRequest(
        request_id="req-1",
        recognition_run_id="run-1",
        page_id="page-1",
        task_type="page_summary",
        targets=(
            SemanticTargetInput(
                target_id="target-page",
                page_id="page-1",
                target_type="DrawingPage",
                task_type="page_summary",
            ),
        ),
        model_profile="default",
        prompt_version="prompt-v1",
        input_contract_version="1",
        output_contract_version="1",
        preprocessing_version="preprocess-v1",
        write_back=False,
        deadline_seconds=60.0,
        image_path=None,
    )


def _success_payload() -> dict:
    return {
        "target_id": "target-page",
        "target_type": "DrawingPage",
        "status": "succeeded",
        "summary": "page text",
        "key_elements": [],
        "uncertainties": [],
    }


def _invalid_payload() -> dict:
    """Payload that fails page_summary output validation."""

    return {"target_id": "target-page", "target_type": "DrawingPage", "status": "succeeded", "summary": "only"}


class RecognitionAttemptExecutorTests(unittest.TestCase):
    """Attempt numbering, retry, structure repair and fingerprint stability."""

    def _execute(
        self,
        script: tuple[object, ...],
        *,
        spec=None,
        max_attempts: int = 3,
        repair: int = 1,
        base_backoff_ms: float = 250,
        max_backoff_ms: float = 2000,
        jitter_ratio: float = 0.1,
        clock=None,
        sleeper=None,
        jitter=None,
    ):
        sleeps: list[float] = []
        provider = FakeMultimodalRecognitionClient(script=script)
        executor = RecognitionAttemptExecutor(
            clock=clock or (lambda: 100.0),
            sleeper=sleeper or (lambda delay: sleeps.append(delay)),
            jitter=jitter or (lambda: 0.0),
        )
        output, attempts = executor.execute(
            provider,
            _provider_request(),
            spec or page_summary_spec(),
            _validated_request(),
            RecognitionExecutionPolicy(
                max_attempts=max_attempts,
                structure_repair_attempts=repair,
                base_backoff_ms=base_backoff_ms,
                max_backoff_ms=max_backoff_ms,
                jitter_ratio=jitter_ratio,
                deadline_seconds=60.0,
            ),
        )
        return output, attempts, sleeps, provider

    def test_attempt_numbers_increment_within_same_run(self) -> None:
        output, attempts, _, _ = self._execute(
            (("http_429", None), ("http_429", None), _success_payload()),
            max_attempts=3,
        )
        self.assertEqual("page text", output.output["summary"])
        self.assertEqual(3, len(attempts))
        self.assertEqual([1, 2, 3], [attempt.attempt_number for attempt in attempts])
        self.assertEqual({"run-1"}, {attempt.recognition_run_id for attempt in attempts})
        self.assertEqual(
            [RecognitionAttemptStatus.RETRYABLE_FAILED, RecognitionAttemptStatus.RETRYABLE_FAILED, RecognitionAttemptStatus.SUCCEEDED],
            [attempt.status for attempt in attempts],
        )

    def test_terminal_errors_are_not_retried(self) -> None:
        output, attempts, _, provider = self._execute(("schema_failure",))
        self.assertIsNone(output)
        self.assertEqual(1, len(attempts))
        self.assertEqual(RecognitionAttemptStatus.TERMINAL_FAILED, attempts[0].status)
        self.assertEqual("invalid_response", attempts[0].error_category.value)
        self.assertEqual(1, len(provider.requests))

    def test_authentication_error_is_terminal(self) -> None:
        output, attempts, _, provider = self._execute(("http_401",))
        self.assertIsNone(output)
        self.assertEqual(RecognitionAttemptStatus.TERMINAL_FAILED, attempts[0].status)
        self.assertEqual("authentication", attempts[0].error_category.value)
        self.assertEqual(1, len(provider.requests))

    def test_bounded_exponential_backoff_with_jitter(self) -> None:
        _, _, sleeps, _ = self._execute(
            (("http_429", None), ("http_429", None), _success_payload()),
            base_backoff_ms=250,
            max_backoff_ms=2000,
            jitter=lambda: 0.1,
        )
        self.assertEqual(2, len(sleeps))
        self.assertAlmostEqual(0.275, sleeps[0], places=6)
        self.assertAlmostEqual(0.525, sleeps[1], places=6)

    def test_retry_after_is_honored(self) -> None:
        _, _, sleeps, _ = self._execute(
            (("http_429", 5), _success_payload()),
            max_attempts=2,
        )
        self.assertEqual(1, len(sleeps))
        self.assertGreaterEqual(sleeps[0], 5.0)

    def test_structure_repair_retries_once_when_allowed(self) -> None:
        output, attempts, _, provider = self._execute(
            (_invalid_payload(), _success_payload()),
            repair=1,
            max_attempts=3,
            spec=replace(page_summary_spec(), allow_structure_repair=True),
        )
        self.assertEqual("page text", output.output["summary"])
        self.assertEqual(2, len(attempts))
        self.assertEqual(RecognitionAttemptStatus.CONTRACT_FAILED, attempts[0].status)
        self.assertEqual(RecognitionAttemptStatus.SUCCEEDED, attempts[1].status)
        self.assertEqual(2, len(provider.requests))

    def test_structure_repair_respects_spec_and_repair_budget(self) -> None:
        output, attempts, _, provider = self._execute(
            (_invalid_payload(), _success_payload()),
            repair=0,
            max_attempts=2,
        )
        self.assertIsNone(output)
        self.assertEqual(1, len(attempts))
        self.assertEqual(1, len(provider.requests))

        spec = replace(page_summary_spec(), allow_structure_repair=False)
        sleeps: list[float] = []
        provider = FakeMultimodalRecognitionClient(script=(_invalid_payload(), _success_payload()))
        executor = RecognitionAttemptExecutor(jitter=lambda: 0.0, sleeper=lambda delay: sleeps.append(delay))
        output, attempts = executor.execute(
            provider,
            _provider_request(),
            spec,
            _validated_request(),
            RecognitionExecutionPolicy(max_attempts=2, structure_repair_attempts=1),
        )
        self.assertIsNone(output)
        self.assertEqual(1, len(attempts))
        self.assertEqual(1, len(provider.requests))

    def test_fingerprint_prompt_and_contract_unchanged_across_attempts(self) -> None:
        _, attempts, _, provider = self._execute(
            (("http_429", None), _success_payload()),
            max_attempts=2,
        )
        self.assertEqual(["fp-1", "fp-1"], [attempt.request_fingerprint for attempt in attempts])
        self.assertEqual(["prompt-v1", "prompt-v1"], [attempt.prompt_version for attempt in attempts])
        self.assertEqual(["1", "1"], [attempt.output_contract_version for attempt in attempts])
        self.assertEqual(["fp-1", "fp-1"], [request.request_fingerprint for request in provider.requests])

    def test_attempt_records_latency(self) -> None:
        times = iter([100.0, 100.25])
        _, attempts, _, _ = self._execute(
            (_success_payload(),),
            clock=lambda: next(times),
        )
        self.assertAlmostEqual(250.0, attempts[0].latency_ms, places=6)

    def test_retry_policy_validation(self) -> None:
        with self.assertRaises(ValueError):
            RecognitionRetryPolicy(max_attempts=2, structure_repair_attempts=2)
        with self.assertRaises(ValueError):
            RecognitionRetryPolicy(base_backoff_ms=2000, max_backoff_ms=250)


if __name__ == "__main__":
    unittest.main()
