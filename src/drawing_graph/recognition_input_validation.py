"""Pre-provider input contract validation for the 04 execution layer."""

from __future__ import annotations

import math
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
            element = _validate_target_identity(target, page_facts, task_spec, task_type)
            _validate_target_spatial(target, page_facts, task_spec, task_type, element)
            _validate_context(target, page_facts, task_spec)
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
) -> ElementEvidence | None:
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
        return None

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
    return element


def _validate_target_spatial(
    target: SemanticTargetInput,
    page_facts: PageSourceFacts,
    task_spec: RecognitionTaskSpec,
    task_type: RecognitionTaskType,
    element: ElementEvidence | None,
) -> None:
    """Validate bbox coordinates against image bounds and source facts."""

    if task_type is RecognitionTaskType.PAGE_SUMMARY:
        if target.bbox is not None or target.normalized_bbox is not None:
            raise RecognitionInputError(
                "page_target_with_bbox",
                "page_summary targets must not carry a bbox; the full page is the input",
            )
        return
    if target.bbox is None or target.normalized_bbox is None:
        raise RecognitionInputError(
            "missing_bbox",
            f"task {task_type.value} requires bbox and normalized_bbox",
        )
    _require_finite_bbox(target.bbox, "bbox")
    _require_finite_bbox(target.normalized_bbox, "normalized_bbox")
    if page_facts.image_size is None:
        raise RecognitionInputError(
            "image_size_missing",
            "page image size is required to validate element bbox bounds",
        )
    width, height = page_facts.image_size
    if (
        target.bbox.x_min < 0
        or target.bbox.y_min < 0
        or target.bbox.x_max > width
        or target.bbox.y_max > height
    ):
        raise RecognitionInputError(
            "bbox_out_of_bounds",
            "bbox must lie inside the page image bounds",
        )
    for coordinate in (
        target.normalized_bbox.x_min,
        target.normalized_bbox.y_min,
        target.normalized_bbox.x_max,
        target.normalized_bbox.y_max,
    ):
        if not 0 <= coordinate <= 1:
            raise RecognitionInputError(
                "normalized_bbox_out_of_range",
                "normalized_bbox values must be between 0 and 1",
            )
    expected = (
        target.bbox.x_min / width,
        target.bbox.y_min / height,
        target.bbox.x_max / width,
        target.bbox.y_max / height,
    )
    actual = (
        target.normalized_bbox.x_min,
        target.normalized_bbox.y_min,
        target.normalized_bbox.x_max,
        target.normalized_bbox.y_max,
    )
    if not all(math.isclose(exp, act, abs_tol=1e-3) for exp, act in zip(expected, actual)):
        raise RecognitionInputError(
            "normalized_bbox_mismatch",
            "normalized_bbox must be consistent with the pixel bbox and image size",
        )
    if element is None:
        raise RecognitionInputError(
            "element_not_found",
            "target element must exist for spatial validation",
        )
    source_bbox = (element.bbox.x_min, element.bbox.y_min, element.bbox.x_max, element.bbox.y_max)
    target_bbox = (target.bbox.x_min, target.bbox.y_min, target.bbox.x_max, target.bbox.y_max)
    if not all(math.isclose(exp, act, abs_tol=1e-6) for exp, act in zip(source_bbox, target_bbox)):
        raise RecognitionInputError(
            "bbox_mismatch",
            "target bbox must match the source fact bbox",
        )
    source_normalized = (
        element.normalized_bbox.x_min,
        element.normalized_bbox.y_min,
        element.normalized_bbox.x_max,
        element.normalized_bbox.y_max,
    )
    target_normalized = (
        target.normalized_bbox.x_min,
        target.normalized_bbox.y_min,
        target.normalized_bbox.x_max,
        target.normalized_bbox.y_max,
    )
    if not all(math.isclose(exp, act, abs_tol=1e-6) for exp, act in zip(source_normalized, target_normalized)):
        raise RecognitionInputError(
            "normalized_bbox_mismatch",
            "target normalized_bbox must match the source fact normalized_bbox",
        )


def _validate_context(
    target: SemanticTargetInput,
    page_facts: PageSourceFacts,
    task_spec: RecognitionTaskSpec,
) -> None:
    """Validate context IDs are same-page and inside the task whitelist."""

    seen: set[str] = set()
    for context_id in target.context_element_ids:
        if context_id in seen:
            raise RecognitionInputError(
                "duplicate_context",
                "context element ids must be unique",
            )
        seen.add(context_id)
        if not task_spec.required_context_types:
            raise RecognitionInputError(
                "context_not_allowed",
                f"task {task_spec.task_type.value} does not allow context elements",
            )
        element = _find_element(page_facts, context_id)
        if element is None:
            raise RecognitionInputError(
                "context_not_found",
                f"context element {context_id!r} was not found on the page",
            )
        if element.element_type not in task_spec.required_context_types:
            raise RecognitionInputError(
                "context_type_not_allowed",
                f"context element type {element.element_type!r} is not allowed by the task",
            )


def _require_finite_bbox(bbox: Any, field_name: str) -> None:
    for coordinate in (bbox.x_min, bbox.y_min, bbox.x_max, bbox.y_max):
        if not isinstance(coordinate, (int, float)) or isinstance(coordinate, bool) or not math.isfinite(coordinate):
            raise RecognitionInputError(
                "invalid_bbox",
                f"{field_name} coordinates must be finite numbers",
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
