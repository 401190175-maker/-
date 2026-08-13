"""Usage, actual-cost and latency summarization for the 04 execution layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .recognition_models import (
    CostStatus,
    RecognitionAttempt,
    RecognitionCostSummary,
    RecognitionLatencySummary,
    RecognitionProviderUsage,
    UsageStatus,
)


@dataclass(frozen=True)
class RecognitionRateCard:
    """Versioned per-model pricing snapshot used to calculate actual cost."""

    provider: str
    model: str
    currency: str
    version_id: str
    input_token_rate: float | None = None
    output_token_rate: float | None = None
    image_unit_rate: float | None = None

    def __post_init__(self) -> None:
        for field_name in ("provider", "model", "currency", "version_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        for field_name in ("input_token_rate", "output_token_rate", "image_unit_rate"):
            value = getattr(self, field_name)
            if value is not None and (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or value < 0
            ):
                raise ValueError(f"{field_name} must be a non-negative number or None")


class RecognitionUsageMeter:
    """Summarize provider usage, actual cost and staged latency."""

    def summarize_usage(self, attempts: tuple[RecognitionAttempt, ...]) -> RecognitionProviderUsage:
        """Aggregate usage across all attempts, counting retries and repairs."""

        _require_attempts(attempts)
        input_tokens = 0
        output_tokens = 0
        image_units = 0
        attempts_with_usage = 0
        attempts_available = 0
        for attempt in attempts:
            if attempt.usage is None:
                continue
            attempts_with_usage += 1
            if attempt.usage.status is UsageStatus.AVAILABLE:
                attempts_available += 1
            input_tokens += attempt.usage.input_tokens or 0
            output_tokens += attempt.usage.output_tokens or 0
            image_units += attempt.usage.image_units or 0
        if attempts_with_usage == 0:
            return RecognitionProviderUsage(status=UsageStatus.UNAVAILABLE)
        status = (
            UsageStatus.PARTIAL
            if attempts_with_usage < len(attempts) or attempts_available < attempts_with_usage
            else UsageStatus.AVAILABLE
        )
        return RecognitionProviderUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            image_units=image_units,
            status=status,
        )

    def summarize(
        self,
        attempts: tuple[RecognitionAttempt, ...],
        rate_card: RecognitionRateCard,
        *,
        validation_ms: float = 0.0,
        preprocessing_ms: float = 0.0,
        backoff_ms: float = 0.0,
        output_validation_ms: float = 0.0,
    ) -> tuple[RecognitionCostSummary, RecognitionLatencySummary]:
        """Return actual-cost and staged-latency summaries."""

        _require_attempts(attempts)
        _require_rate_card(rate_card)
        usage = self.summarize_usage(attempts)
        cost = self._cost(usage, rate_card)
        provider_ms = sum(attempt.latency_ms for attempt in attempts)
        total_ms = (
            validation_ms
            + preprocessing_ms
            + provider_ms
            + backoff_ms
            + output_validation_ms
        )
        latency = RecognitionLatencySummary(
            validation_ms=validation_ms,
            preprocessing_ms=preprocessing_ms,
            provider_ms=provider_ms,
            backoff_ms=backoff_ms,
            output_validation_ms=output_validation_ms,
            total_ms=total_ms,
        )
        return cost, latency

    @staticmethod
    def _cost(
        usage: RecognitionProviderUsage,
        rate_card: RecognitionRateCard,
    ) -> RecognitionCostSummary:
        if usage.status is not UsageStatus.AVAILABLE:
            return RecognitionCostSummary(
                status=CostStatus.UNAVAILABLE,
                actual_cost=None,
                currency=rate_card.currency,
                rate_card_version=rate_card.version_id,
                reason="provider usage is not fully available",
            )
        required_rates = (
            rate_card.input_token_rate,
            rate_card.output_token_rate,
        )
        if usage.image_units is not None and usage.image_units > 0 and rate_card.image_unit_rate is None:
            required_rates = (*required_rates, rate_card.image_unit_rate)
        if any(rate is None for rate in required_rates):
            return RecognitionCostSummary(
                status=CostStatus.UNAVAILABLE,
                actual_cost=None,
                currency=rate_card.currency,
                rate_card_version=rate_card.version_id,
                reason="rate card is missing a required price",
            )
        actual_cost = (
            (usage.input_tokens or 0) * (rate_card.input_token_rate or 0.0)
            + (usage.output_tokens or 0) * (rate_card.output_token_rate or 0.0)
            + (usage.image_units or 0) * (rate_card.image_unit_rate or 0.0)
        )
        return RecognitionCostSummary(
            status=CostStatus.CALCULATED,
            actual_cost=actual_cost,
            currency=rate_card.currency,
            rate_card_version=rate_card.version_id,
        )


def _require_attempts(value: Any) -> None:
    if not isinstance(value, tuple) or not all(isinstance(item, RecognitionAttempt) for item in value):
        raise ValueError("attempts must be a tuple of RecognitionAttempt")


def _require_rate_card(value: Any) -> None:
    if not isinstance(value, RecognitionRateCard):
        raise ValueError("rate_card must be a RecognitionRateCard")


__all__ = ("RecognitionRateCard", "RecognitionUsageMeter")
