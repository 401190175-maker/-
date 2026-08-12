"""Pre-provider input contract validation for the 04 execution layer."""

from __future__ import annotations

from typing import Any

from .recognition_models import (
    RecognitionExecutionRequest,
    RecognitionTaskType,
    ValidatedRecognitionRequest,
)
from .recognition_tasks import RecognitionTaskSpec
from .tool_models import ElementEvidence, PageSourceFacts, SemanticTargetInput


class RecognitionInputError(ValueError):
    """Stable input-contract error raised before any provider attempt."""

    def __init__(self, category: str, message: str):
        self.category = category
        super().__init__(message)


class RecognitionInputValidator:
    """Validate one execution request against trusted page source facts."""

    def validate(
        self,
        request: RecognitionExecutionRequest,
        page_facts: PageSourceFacts,
        task_spec: RecognitionTaskSpec,
    ) -> ValidatedRecognitionRequest:
        """Return the validated internal projection or raise RecognitionInputError."""

        _require_instance(request, RecognitionExecutionRequest, "request")
        _require_instance(page_facts, PageSourceFacts, "page_facts")
        _require_instance(task_spec, RecognitionTaskSpec, "task_spec")

        task_type = _task_type(request.task_type)
        if task_type is not _task_type(task_spec.task_type):
            raise RecognitionInputError(
                "task_mismatch",
                "request task_type must match the provided task spec",
            )
        if request.page_id != page_facts.page_id:
            raise RecognitionInputError(
                "page_mismatch",
                "request page_id must match page source facts",
            )

        validated_targets: list[SemanticTargetInput] = []
        for target in request.targets:
            _validate_target_identity(target, page_facts, task_spec, task_type)
            validated_targets.append(target)

        return ValidatedRecognitionRequest(
            request_id=request.request_id,
            recognition_run_id=request.recognition_run_id,
            page_id=request.page_id,
            task_type=task_type,
            targets=tuple(validated_targets),
            model_profile=request.model_profile,
            prompt_version=request.prompt_version,
            input_contract_version=request.input_contract_version,
            output_contract_version=request.output_contract_version,
            preprocessing_version=request.preprocessing_version,
            write_back=request.write_back,
            deadline_seconds=request.deadline_seconds,
            image_path=page_facts.image_path,
            image_size=page_facts.image_size,
        )


def _validate_target_identity(
    target: SemanticTargetInput,
    page_facts: PageSourceFacts,
    task_spec: RecognitionTaskSpec,
    task_type: RecognitionTaskType,
) -> None:
    if target.page_id != page_facts.page_id:
        raise RecognitionInputError(
            "page_mismatch",
            "target page_id must match page source facts",
        )
    if _task_type(target.task_type) is not task_type:
        raise RecognitionInputError(
            "task_mismatch",
            "target task_type must match the request task_type",
        )
    if target.target_type not in task_spec.allowed_target_types:
        raise RecognitionInputError(
            "target_type_not_allowed",
            f"target_type {target.target_type!r} is not allowed for task {task_type.value}",
        )
    if task_type is RecognitionTaskType.PAGE_SUMMARY:
        if target.target_element_id is not None:
            raise RecognitionInputError(
                "page_target_with_element",
                "page_summary targets must not carry an element id",
            )
        return

    if target.target_element_id is None:
        raise RecognitionInputError(
            "missing_element_id",
            f"task {task_type.value} requires a target element id",
        )
    element = _find_element(page_facts, target.target_element_id)
    if element is None:
        raise RecognitionInputError(
            "element_not_found",
            f"target element {target.target_element_id!r} was not found on the page",
        )
    if element.element_type != target.target_type:
        raise RecognitionInputError(
            "element_type_mismatch",
            "target element type must match the source fact element type",
        )


def _find_element(page_facts: PageSourceFacts, element_id: str) -> ElementEvidence | None:
    for element in page_facts.elements:
        if element.element_id == element_id:
            return element
    return None


def _task_type(value: RecognitionTaskType | str) -> RecognitionTaskType:
    try:
        return value if isinstance(value, RecognitionTaskType) else RecognitionTaskType(value)
    except ValueError as exc:
        raise RecognitionInputError("unknown_task", "unsupported recognition task type") from exc


def _require_instance(value: Any, expected: type, field_name: str) -> None:
    if not isinstance(value, expected):
        raise RecognitionInputError("invalid_input", f"{field_name} must be a {expected.__name__}")


__all__ = ("RecognitionInputError", "RecognitionInputValidator")
