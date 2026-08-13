"""Offline contract tests for usage and actual-cost summarization."""

from __future__ import annotations

import unittest

from drawing_graph.recognition_metrics import RecognitionRateCard, RecognitionUsageMeter
from drawing_graph.recognition_models import (
    CostStatus,
    RecognitionAttempt,
    RecognitionAttemptStatus,
    RecognitionProviderUsage,
    UsageStatus,
)


def _attempt(
    *,
    attempt_number: int = 1,
    status: str = "succeeded",
    usage: RecognitionProviderUsage | None = None,
    latency_ms: float = 10.0,
) -> RecognitionAttempt:
    return RecognitionAttempt(
        attempt_id=f"attempt-{attempt_number}",
        recognition_run_id="run-1",
        attempt_number=attempt_number,
        task_type="page_summary",
        provider="qwen",
        model_name="qwen3-vl-plus",
        request_fingerprint=f"fp-{attempt_number}",
        prompt_version="prompt-v1",
        output_contract_version="1",
        status=RecognitionAttemptStatus(status),
        latency_ms=latency_ms,
        usage=usage,
    )


def _usage(input_tokens: int | None, output_tokens: int | None, image_units: int | None = None) -> RecognitionProviderUsage:
    return RecognitionProviderUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        image_units=image_units,
        status=UsageStatus.AVAILABLE,
    )


class RecognitionUsageCostTests(unittest.TestCase):
    """Usage and cost must be aggregated across all attempts."""

    def test_usage_is_aggregated_across_all_attempts(self) -> None:
        attempts = (
            _attempt(attempt_number=1, usage=_usage(10, 5, 1)),
            _attempt(attempt_number=2, status="retryable_failed", usage=_usage(20, 10, 0)),
            _attempt(attempt_number=3, usage=_usage(30, 15, 2)),
        )
        usage = RecognitionUsageMeter().summarize_usage(attempts)
        self.assertEqual(60, usage.input_tokens)
        self.assertEqual(30, usage.output_tokens)
        self.assertEqual(3, usage.image_units)
        self.assertIs(UsageStatus.AVAILABLE, usage.status)

    def test_retried_and_repaired_attempts_all_count_toward_cost(self) -> None:
        attempts = (
            _attempt(attempt_number=1, status="retryable_failed", usage=_usage(100, 50)),
            _attempt(attempt_number=2, status="contract_failed", usage=_usage(100, 50)),
            _attempt(attempt_number=3, usage=_usage(10, 5)),
        )
        card = RecognitionRateCard(
            provider="qwen",
            model="qwen3-vl-plus",
            currency="USD",
            version_id="rate-v1",
            input_token_rate=0.001,
            output_token_rate=0.002,
        )
        cost, _ = RecognitionUsageMeter().summarize(attempts, card)
        self.assertIs(CostStatus.CALCULATED, cost.status)
        self.assertAlmostEqual(0.2 + 0.2 + 0.02, cost.actual_cost, places=9)

    def test_rate_card_with_rates_calculates_actual_cost(self) -> None:
        card = RecognitionRateCard(
            provider="qwen",
            model="qwen3-vl-plus",
            currency="USD",
            version_id="rate-v1",
            input_token_rate=0.001,
            output_token_rate=0.002,
            image_unit_rate=0.01,
        )
        cost, _ = RecognitionUsageMeter().summarize(
            (_attempt(usage=_usage(100, 50, 2)),),
            card,
        )
        self.assertIs(CostStatus.CALCULATED, cost.status)
        self.assertAlmostEqual(0.1 + 0.1 + 0.02, cost.actual_cost, places=9)
        self.assertEqual("USD", cost.currency)
        self.assertEqual("rate-v1", cost.rate_card_version)

    def test_missing_usage_yields_unavailable_null_cost(self) -> None:
        attempts = (_attempt(usage=None),)
        card = RecognitionRateCard(
            provider="qwen",
            model="qwen3-vl-plus",
            currency="USD",
            version_id="rate-v1",
            input_token_rate=0.001,
            output_token_rate=0.002,
        )
        usage = RecognitionUsageMeter().summarize_usage(attempts)
        self.assertIs(UsageStatus.UNAVAILABLE, usage.status)
        cost, _ = RecognitionUsageMeter().summarize(attempts, card)
        self.assertIs(CostStatus.UNAVAILABLE, cost.status)
        self.assertIsNone(cost.actual_cost)
        self.assertTrue(cost.reason)

    def test_missing_rate_yields_unavailable_null_cost(self) -> None:
        card = RecognitionRateCard(
            provider="qwen",
            model="qwen3-vl-plus",
            currency="USD",
            version_id="rate-v1",
        )
        cost, _ = RecognitionUsageMeter().summarize(
            (_attempt(usage=_usage(100, 50)),),
            card,
        )
        self.assertIs(CostStatus.UNAVAILABLE, cost.status)
        self.assertIsNone(cost.actual_cost)

    def test_partial_usage_status_when_some_attempts_miss_usage(self) -> None:
        usage = RecognitionUsageMeter().summarize_usage(
            (
                _attempt(attempt_number=1, usage=_usage(10, 5)),
                _attempt(attempt_number=2, usage=None),
            )
        )
        self.assertIs(UsageStatus.PARTIAL, usage.status)
        self.assertEqual(10, usage.input_tokens)

    def test_meter_does_not_accept_or_overwrite_estimate(self) -> None:
        card = RecognitionRateCard(provider="qwen", model="m", currency="USD", version_id="rate-v1")
        with self.assertRaises(TypeError):
            RecognitionUsageMeter().summarize((), card, estimate=1.0)

    def test_rate_card_validation(self) -> None:
        with self.assertRaises(ValueError):
            RecognitionRateCard(
                provider="qwen",
                model="m",
                currency="USD",
                version_id="",
            )
        with self.assertRaises(ValueError):
            RecognitionRateCard(
                provider="qwen",
                model="m",
                currency="USD",
                version_id="rate-v1",
                input_token_rate=-0.1,
            )


class RecognitionLatencyTests(unittest.TestCase):
    """Latency segments must be individually traceable and sum to total."""

    def _card(self) -> RecognitionRateCard:
        return RecognitionRateCard(provider="qwen", model="m", currency="USD", version_id="rate-v1")

    def test_total_equals_sum_of_stages_with_fixed_clock(self) -> None:
        attempts = (
            _attempt(attempt_number=1, latency_ms=10.0),
            _attempt(attempt_number=2, latency_ms=20.0),
        )
        _, latency = RecognitionUsageMeter().summarize(
            attempts,
            self._card(),
            validation_ms=2.0,
            preprocessing_ms=3.0,
            backoff_segments=(1.5, 2.5),
            output_validation_ms=1.0,
        )
        self.assertEqual(30.0, latency.provider_ms)
        self.assertEqual(4.0, latency.backoff_ms)
        self.assertEqual(2.0, latency.validation_ms)
        self.assertEqual(3.0, latency.preprocessing_ms)
        self.assertEqual(1.0, latency.output_validation_ms)
        self.assertEqual(40.0, latency.total_ms)

    def test_per_attempt_provider_latency_is_individually_traceable(self) -> None:
        attempts = (
            _attempt(attempt_number=1, latency_ms=10.0),
            _attempt(attempt_number=2, status="retryable_failed", latency_ms=15.0),
            _attempt(attempt_number=3, latency_ms=25.0),
        )
        _, latency = RecognitionUsageMeter().summarize(attempts, self._card())
        self.assertEqual([10.0, 15.0, 25.0], [attempt.latency_ms for attempt in attempts])
        self.assertEqual(50.0, latency.provider_ms)

    def test_cache_hit_has_no_provider_or_backoff_latency(self) -> None:
        _, latency = RecognitionUsageMeter().summarize(
            (),
            self._card(),
            validation_ms=1.0,
            preprocessing_ms=2.0,
            backoff_segments=(),
            output_validation_ms=0.5,
        )
        self.assertEqual(0.0, latency.provider_ms)
        self.assertEqual(0.0, latency.backoff_ms)
        self.assertEqual(3.5, latency.total_ms)

    def test_latency_summary_contains_no_prompt_images_or_payload(self) -> None:
        _, latency = RecognitionUsageMeter().summarize((), self._card())
        self.assertFalse(hasattr(latency, "prompt"))
        self.assertFalse(hasattr(latency, "images"))
        self.assertFalse(hasattr(latency, "payload"))

    def test_negative_backoff_segments_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RecognitionUsageMeter().summarize(
                (),
                self._card(),
                backoff_segments=(-1.0,),
            )


if __name__ == "__main__":
    unittest.main()
