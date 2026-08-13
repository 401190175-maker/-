"""Multimodal recognition execution service: the single 04 orchestration entry."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .recognition_image_preprocessing import PreparedRecognitionImage, RegionImagePreprocessor
from .recognition_input_validation import RecognitionInputError, RecognitionInputValidator
from .recognition_metrics import RecognitionRateCard, RecognitionUsageMeter
from .recognition_models import (
    RecognitionAttemptStatus,
    RecognitionExecutionPolicy,
    RecognitionExecutionRequest,
    RecognitionExecutionResult,
    RecognitionExecutionStatus,
    ValidatedRecognitionRequest,
)
from .recognition_output_validation import RecognitionOutputValidator
from .recognition_prompting import RecognitionPromptError, RecognitionPromptRenderer, RenderedRecognitionPrompt
from .recognition_redaction import RecognitionRedactor
from .recognition_retry import RecognitionAttemptExecutor, RecognitionBudgetError
from .recognition_tasks import RecognitionTaskRegistry, RecognitionTaskSpec, build_default_task_registry
from .semantic_client import MultimodalRecognitionClient, RecognitionClientRequest
from .tool_models import PageSourceFacts, ToolModelError


_DEFAULT_SINGLE_CALL_TIMEOUT_SECONDS = 60.0


class MultimodalRecognitionExecutionService:
    """Orchestrate one execution compatibility group end to end.

    The service wires task resolution, input validation, image preparation,
    prompt rendering, provider attempts/retry, output validation, metrics and
    redaction. It never writes cache, run logs, attempt logs, payload stores
    or Neo4j; persistence stays with the semantic service.
    """

    def __init__(
        self,
        provider: MultimodalRecognitionClient,
        *,
        registry: RecognitionTaskRegistry | None = None,
        validator: RecognitionInputValidator | None = None,
        preprocessor: RegionImagePreprocessor | None = None,
        prompt_renderer: RecognitionPromptRenderer | None = None,
        output_validator: RecognitionOutputValidator | None = None,
        attempt_executor: RecognitionAttemptExecutor | None = None,
        usage_meter: RecognitionUsageMeter | None = None,
        redactor: RecognitionRedactor | None = None,
        rate_card: RecognitionRateCard | None = None,
    ):
        self.provider = provider
        self.registry = registry or build_default_task_registry()
        self.validator = validator or RecognitionInputValidator()
        self.preprocessor = preprocessor or RegionImagePreprocessor()
        self.output_validator = output_validator or RecognitionOutputValidator()
        self.prompt_renderer = prompt_renderer or RecognitionPromptRenderer()
        self.attempt_executor = attempt_executor or RecognitionAttemptExecutor(
            output_validator=self.output_validator,
        )
        self.usage_meter = usage_meter or RecognitionUsageMeter()
        self.redactor = redactor or RecognitionRedactor()
        self.rate_card = rate_card or RecognitionRateCard(
            provider="unknown",
            model="unknown",
            currency="USD",
            version_id="unversioned",
        )

    def execute(
        self,
        request: RecognitionExecutionRequest,
        page_facts: PageSourceFacts,
        execution_policy: RecognitionExecutionPolicy | None = None,
    ) -> RecognitionExecutionResult:
        """Return a safe execution result or a classified failure summary."""

        policy = execution_policy or RecognitionExecutionPolicy()
        _require_instance(request, RecognitionExecutionRequest, "request")
        _require_instance(page_facts, PageSourceFacts, "page_facts")
        _require_instance(policy, RecognitionExecutionPolicy, "execution_policy")
        try:
            task_spec = self.registry.get(request.task_type)
            validated = self.validator.validate(request, page_facts, task_spec, server_policy=policy)
            prepared_images = self.preprocessor.prepare(validated, task_spec)
            rendered = self.prompt_renderer.render(task_spec, validated, prepared_images)
            provider_request = self._provider_request(validated, rendered, prepared_images)
            output, attempts = self.attempt_executor.execute(
                self.provider,
                provider_request,
                task_spec,
                validated,
                policy,
            )
            status = self._status(output, attempts)
            validated_outputs = self._all_outputs(output, task_spec, validated)
            usage = self.usage_meter.summarize_usage(attempts)
            cost, latency = self.usage_meter.summarize(attempts, self.rate_card)
            return RecognitionExecutionResult(
                recognition_run_id=request.recognition_run_id,
                status=status,
                validated_outputs=validated_outputs,
                attempts=attempts,
                usage_summary=usage,
                cost_summary=cost,
                latency_summary=latency,
                persisted=False,
            )
        except RecognitionBudgetError as exc:
            status = (
                RecognitionExecutionStatus.DEADLINE_EXCEEDED
                if exc.category == "deadline_exceeded"
                else RecognitionExecutionStatus.RECOGNITION_FAILED
            )
            return self._failure(request, status, exc)
        except (RecognitionInputError, RecognitionPromptError, ToolModelError) as exc:
            return self._failure(request, RecognitionExecutionStatus.RECOGNITION_FAILED, exc)
        except Exception as exc:
            return self._failure(request, RecognitionExecutionStatus.RECOGNITION_FAILED, exc)

    @staticmethod
    def _status(output, attempts) -> RecognitionExecutionStatus:
        if output is None:
            if not attempts:
                return RecognitionExecutionStatus.RECOGNITION_FAILED
            last_status = attempts[-1].status
            if last_status is RecognitionAttemptStatus.CONTRACT_FAILED:
                return RecognitionExecutionStatus.CONTRACT_FAILED
            if last_status in {
                RecognitionAttemptStatus.RETRYABLE_FAILED,
                RecognitionAttemptStatus.TERMINAL_FAILED,
            }:
                return RecognitionExecutionStatus.PROVIDER_FAILED
            return RecognitionExecutionStatus.RECOGNITION_FAILED
        if output.status is RecognitionExecutionStatus.AMBIGUOUS:
            return RecognitionExecutionStatus.AMBIGUOUS
        if output.status is RecognitionExecutionStatus.NOT_FOUND:
            return RecognitionExecutionStatus.NOT_FOUND
        return RecognitionExecutionStatus.SUCCEEDED

    def _all_outputs(self, output, task_spec: RecognitionTaskSpec, validated: ValidatedRecognitionRequest):
        if output is None:
            return ()
        payload = getattr(self.attempt_executor, "last_successful_payload", None)
        if payload is not None:
            try:
                return self.output_validator.validate(task_spec, validated, payload)
            except Exception:
                return (output,)
        return (output,)

    @staticmethod
    def _provider_request(
        validated: ValidatedRecognitionRequest,
        rendered: RenderedRecognitionPrompt,
        prepared_images: tuple[PreparedRecognitionImage, ...],
    ) -> RecognitionClientRequest:
        return RecognitionClientRequest(
            model_profile=validated.model_profile,
            rendered_prompt=rendered,
            prepared_images=prepared_images,
            output_contract_version=validated.output_contract_version,
            request_fingerprint=rendered.fingerprint,
            timeout_seconds=min(validated.deadline_seconds, _DEFAULT_SINGLE_CALL_TIMEOUT_SECONDS),
        )

    def _failure(self, request: RecognitionExecutionRequest, status, error: Exception) -> RecognitionExecutionResult:
        safe_error = asdict(self.redactor.redact_error(error))
        return RecognitionExecutionResult(
            recognition_run_id=request.recognition_run_id,
            status=status,
            safe_error=safe_error,
            persisted=False,
        )


def _require_instance(value: Any, expected: type, field_name: str) -> None:
    if not isinstance(value, expected):
        raise ToolModelError("INVALID_ARGUMENT", f"{field_name} must be a {expected.__name__}")


__all__ = ("MultimodalRecognitionExecutionService",)
