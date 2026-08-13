"""Provider error classification and bounded retry execution for the 04 layer."""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from .recognition_models import (
    ProviderErrorCategory,
    RecognitionAttempt,
    RecognitionAttemptStatus,
    RecognitionExecutionPolicy,
    ValidatedRecognitionRequest,
)
from .recognition_output_validation import RecognitionOutputContractError, RecognitionOutputValidator
from .recognition_tasks import RecognitionTaskSpec
from .tool_models import ToolModelError


_MAX_RETRY_AFTER_SECONDS = 120.0


@dataclass(frozen=True)
class RecognitionProviderError(Exception):
    """Safe provider error carrying only classification and summary fields."""

    category: ProviderErrorCategory | str
    retryable: bool
    safe_message: str
    retry_after_seconds: float | None = None

    def __post_init__(self) -> None:
        try:
            category = (
                self.category
                if isinstance(self.category, ProviderErrorCategory)
                else ProviderErrorCategory(self.category)
            )
        except ValueError as exc:
            raise ToolModelError("invalid_provider_error", "unsupported provider error category") from exc
        object.__setattr__(self, "category", category)
        if not isinstance(self.retryable, bool):
            raise ToolModelError("invalid_provider_error", "retryable must be a boolean")
        if not isinstance(self.safe_message, str) or not self.safe_message.strip():
            raise ToolModelError("invalid_provider_error", "safe_message must be a non-empty string")
        if self.retry_after_seconds is not None and (
            not isinstance(self.retry_after_seconds, (int, float))
            or isinstance(self.retry_after_seconds, bool)
            or self.retry_after_seconds <= 0
        ):
            raise ToolModelError("invalid_provider_error", "retry_after_seconds must be positive or None")

    def __str__(self) -> str:
        return self.safe_message


def parse_retry_after(value: Any, *, cap_seconds: float = _MAX_RETRY_AFTER_SECONDS) -> float | None:
    """Parse a bounded Retry-After value; return None when invalid or too large."""

    if value is None:
        return None
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed <= 0 or parsed > cap_seconds:
        return None
    return parsed


def classify_http_status(status_code: int, retry_after_header: str | None = None) -> RecognitionProviderError:
    """Map one provider HTTP status to a stable, safe provider error."""

    if status_code == 429:
        return RecognitionProviderError(
            category=ProviderErrorCategory.RATE_LIMITED,
            retryable=True,
            safe_message="provider is rate limited",
            retry_after_seconds=parse_retry_after(retry_after_header),
        )
    if status_code == 401:
        return RecognitionProviderError(
            category=ProviderErrorCategory.AUTHENTICATION,
            retryable=False,
            safe_message="provider authentication failed",
        )
    if status_code == 403:
        return RecognitionProviderError(
            category=ProviderErrorCategory.PERMISSION,
            retryable=False,
            safe_message="provider permission denied",
        )
    if status_code == 408:
        return RecognitionProviderError(
            category=ProviderErrorCategory.TIMEOUT,
            retryable=True,
            safe_message="provider request timed out",
        )
    if 500 <= status_code <= 599:
        return RecognitionProviderError(
            category=ProviderErrorCategory.TEMPORARY,
            retryable=True,
            safe_message="provider returned a temporary server error",
        )
    if 400 <= status_code <= 499:
        return RecognitionProviderError(
            category=ProviderErrorCategory.PERMANENT,
            retryable=False,
            safe_message="provider returned a permanent client error",
        )
    return RecognitionProviderError(
        category=ProviderErrorCategory.INVALID_RESPONSE,
        retryable=False,
        safe_message="provider returned an unexpected status",
    )


def classify_exception(exc: Exception) -> RecognitionProviderError:
    """Map transport/timeout exceptions to safe retryable provider errors."""

    if isinstance(exc, httpx.TimeoutException):
        return RecognitionProviderError(
            category=ProviderErrorCategory.TIMEOUT,
            retryable=True,
            safe_message="provider call timed out",
        )
    if isinstance(exc, (httpx.TransportError, ConnectionError, OSError)):
        return RecognitionProviderError(
            category=ProviderErrorCategory.TEMPORARY,
            retryable=True,
            safe_message="provider connection failed",
        )
    return RecognitionProviderError(
        category=ProviderErrorCategory.PERMANENT,
        retryable=False,
        safe_message="provider request failed",
    )


@dataclass(frozen=True)
class RecognitionRetryPolicy:
    """Bounded retry parameters derived from the execution policy."""

    max_attempts: int = 3
    structure_repair_attempts: int = 1
    base_backoff_ms: float = 250.0
    max_backoff_ms: float = 2000.0
    jitter_ratio: float = 0.1

    def __post_init__(self) -> None:
        if not isinstance(self.max_attempts, int) or isinstance(self.max_attempts, bool) or self.max_attempts < 1:
            raise ToolModelError("invalid_policy", "max_attempts must be a positive integer")
        if (
            not isinstance(self.structure_repair_attempts, int)
            or isinstance(self.structure_repair_attempts, bool)
            or self.structure_repair_attempts < 0
            or self.structure_repair_attempts >= self.max_attempts
        ):
            raise ToolModelError(
                "invalid_policy",
                "structure_repair_attempts must be non-negative and below max_attempts",
            )
        for field_name in ("base_backoff_ms", "max_backoff_ms"):
            value = getattr(self, field_name)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                raise ToolModelError("invalid_policy", f"{field_name} must be a positive number")
        if self.max_backoff_ms < self.base_backoff_ms:
            raise ToolModelError("invalid_policy", "max_backoff_ms must not be below base_backoff_ms")
        if not isinstance(self.jitter_ratio, (int, float)) or isinstance(self.jitter_ratio, bool):
            raise ToolModelError("invalid_policy", "jitter_ratio must be numeric")
        if not 0 <= self.jitter_ratio <= 1:
            raise ToolModelError("invalid_policy", "jitter_ratio must be between 0 and 1")

    @classmethod
    def from_execution_policy(cls, policy: RecognitionExecutionPolicy) -> "RecognitionRetryPolicy":
        return cls(
            max_attempts=policy.max_attempts,
            structure_repair_attempts=policy.structure_repair_attempts,
            base_backoff_ms=policy.base_backoff_ms,
            max_backoff_ms=policy.max_backoff_ms,
            jitter_ratio=policy.jitter_ratio,
        )


class RecognitionAttemptExecutor:
    """Execute one provider group with bounded retry and structure repair."""

    def __init__(
        self,
        *,
        clock=None,
        sleeper=None,
        jitter=None,
        output_validator: RecognitionOutputValidator | None = None,
        attempt_id_factory=None,
    ):
        self._clock = clock or time.time
        self._sleeper = sleeper or time.sleep
        self._jitter = jitter or (lambda: 0.0)
        self._output_validator = output_validator or RecognitionOutputValidator()
        self._attempt_id_factory = attempt_id_factory or (lambda: f"attempt:{uuid.uuid4()}")
        self.last_successful_payload: Mapping[str, Any] | None = None

    def execute(
        self,
        provider,
        provider_request,
        task_spec: RecognitionTaskSpec,
        validated_request: ValidatedRecognitionRequest,
        execution_policy: RecognitionExecutionPolicy,
    ) -> tuple[Any | None, tuple[RecognitionAttempt, ...]]:
        """Return the first validated output and all attempts, or None on failure."""

        policy = RecognitionRetryPolicy.from_execution_policy(execution_policy)
        attempts: list[RecognitionAttempt] = []
        repair_remaining = policy.structure_repair_attempts
        attempt_number = 1
        while True:
            attempt, output, retry_after = self._run_attempt(
                provider,
                provider_request,
                task_spec,
                validated_request,
                attempt_number,
            )
            attempts.append(attempt)
            if output is not None:
                return output, tuple(attempts)
            if attempt.status is RecognitionAttemptStatus.CONTRACT_FAILED:
                if (
                    repair_remaining > 0
                    and task_spec.allow_structure_repair
                    and attempt_number < policy.max_attempts
                ):
                    repair_remaining -= 1
                    attempt_number += 1
                    continue
                return None, tuple(attempts)
            if attempt.status is RecognitionAttemptStatus.RETRYABLE_FAILED and attempt_number < policy.max_attempts:
                delay = self._backoff(policy, attempt_number + 1, retry_after)
                self._sleeper(delay)
                attempt_number += 1
                continue
            return None, tuple(attempts)

    def _run_attempt(
        self,
        provider,
        provider_request,
        task_spec: RecognitionTaskSpec,
        validated_request: ValidatedRecognitionRequest,
        attempt_number: int,
    ) -> tuple[RecognitionAttempt, Any | None, float | None]:
        started = self._clock()
        try:
            result = provider.recognize(provider_request)
        except RecognitionProviderError as exc:
            status = (
                RecognitionAttemptStatus.RETRYABLE_FAILED
                if exc.retryable
                else RecognitionAttemptStatus.TERMINAL_FAILED
            )
            attempt = self._build_attempt(
                provider,
                provider_request,
                validated_request,
                attempt_number,
                started,
                status,
                error=exc,
            )
            return attempt, None, exc.retry_after_seconds
        except Exception:
            error = RecognitionProviderError(
                category=ProviderErrorCategory.PERMANENT,
                retryable=False,
                safe_message="provider request failed unexpectedly",
            )
            attempt = self._build_attempt(
                provider,
                provider_request,
                validated_request,
                attempt_number,
                started,
                RecognitionAttemptStatus.TERMINAL_FAILED,
                error=error,
            )
            return attempt, None, None

        finished = self._clock()
        try:
            outputs = self._output_validator.validate(task_spec, validated_request, result.payload)
        except RecognitionOutputContractError as exc:
            error = RecognitionProviderError(
                category=ProviderErrorCategory.INVALID_RESPONSE,
                retryable=False,
                safe_message="provider output failed schema validation",
            )
            attempt = self._build_attempt(
                provider,
                provider_request,
                validated_request,
                attempt_number,
                started,
                RecognitionAttemptStatus.CONTRACT_FAILED,
                error=error,
            )
            return attempt, None, None
        if not outputs:
            error = RecognitionProviderError(
                category=ProviderErrorCategory.INVALID_RESPONSE,
                retryable=False,
                safe_message="provider returned no validated outputs",
            )
            attempt = self._build_attempt(
                provider,
                provider_request,
                validated_request,
                attempt_number,
                started,
                RecognitionAttemptStatus.CONTRACT_FAILED,
                error=error,
            )
            return attempt, None, None
        self.last_successful_payload = result.payload
        attempt = self._build_attempt(
            provider,
            provider_request,
            validated_request,
            attempt_number,
            started,
            RecognitionAttemptStatus.SUCCEEDED,
            result=result,
            finished=finished,
        )
        return attempt, outputs[0], None

    def _build_attempt(
        self,
        provider,
        provider_request,
        validated_request: ValidatedRecognitionRequest,
        attempt_number: int,
        started: float,
        status: RecognitionAttemptStatus,
        *,
        result=None,
        error: RecognitionProviderError | None = None,
        finished: float | None = None,
    ) -> RecognitionAttempt:
        end = self._clock() if finished is None else finished
        latency_ms = max(0.0, (end - started) * 1000)
        model_name = result.model_name if result is not None else provider_request.model_profile
        return RecognitionAttempt(
            attempt_id=self._attempt_id_factory(),
            recognition_run_id=validated_request.recognition_run_id,
            attempt_number=attempt_number,
            task_type=validated_request.task_type,
            provider=_provider_name(provider),
            model_name=model_name,
            request_fingerprint=provider_request.request_fingerprint,
            prompt_version=provider_request.rendered_prompt.prompt_version,
            output_contract_version=provider_request.output_contract_version,
            status=status,
            latency_ms=latency_ms,
            provider_request_id=result.provider_request_id if result is not None else None,
            usage=result.usage if result is not None else None,
            retry_reason=error.category.value if error is not None and status is RecognitionAttemptStatus.RETRYABLE_FAILED else None,
            error_category=error.category if error is not None else None,
            safe_error_summary=error.safe_message if error is not None else None,
        )

    def _backoff(self, policy: RecognitionRetryPolicy, attempt_number: int, retry_after: float | None) -> float:
        exponent = max(0, attempt_number - 2)
        delay_ms = min(policy.max_backoff_ms, policy.base_backoff_ms * (2 ** exponent))
        jitter_range = (policy.jitter_ratio * policy.base_backoff_ms) / 1000.0
        jitter = max(-jitter_range, min(jitter_range, self._jitter()))
        delay = (delay_ms / 1000.0) + jitter
        if retry_after is not None:
            delay = max(delay, retry_after)
        return max(0.0, delay)


def _provider_name(provider) -> str:
    name = getattr(provider, "provider_name", None)
    if isinstance(name, str) and name.strip():
        return name
    return type(provider).__name__


__all__ = (
    "RecognitionAttemptExecutor",
    "RecognitionProviderError",
    "RecognitionRetryPolicy",
    "classify_exception",
    "classify_http_status",
    "parse_retry_after",
)
