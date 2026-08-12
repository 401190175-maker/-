"""Strict task-schema output validation for the 04 execution layer."""

from __future__ import annotations

import json
from typing import Any, Mapping

from .recognition_models import (
    RecognitionExecutionStatus,
    RecognitionTaskType,
    ValidatedRecognitionOutput,
    ValidatedRecognitionRequest,
)
from .recognition_tasks import RecognitionTaskSpec


class RecognitionOutputContractError(ValueError):
    """Stable output-contract error raised when a provider payload is invalid."""

    def __init__(self, category: str, message: str):
        self.category = category
        super().__init__(message)


_COMMON_FIELDS = frozenset({"target_id", "target_type", "status", "confidence"})

_ALLOWED_OUTPUT_STATUSES = frozenset({"succeeded", "partial", "ambiguous", "not_found"})


_SCHEMA_FIELDS: dict[RecognitionTaskType, dict[str, str]] = {
    RecognitionTaskType.PAGE_SUMMARY: {
        "summary": "str",
        "key_elements": "str_list",
        "uncertainties": "str_list",
    },
    RecognitionTaskType.ELEMENT_TEXT_OBSERVATION: {
        "observations": "mapping_list",
    },
    RecognitionTaskType.BLOCK_SEMANTIC_IDENTIFICATION: {
        "interpretation": "mapping",
        "observations": "mapping_list",
    },
    RecognitionTaskType.BASIC_INFO_INTERPRETATION: {
        "raw_text": "str",
        "summary": "str",
        "project_name": "opt_str",
        "drawing_name": "opt_str",
        "discipline": "opt_str",
        "drawing_number": "opt_str",
        "scale": "opt_str",
        "date": "opt_str",
        "uncertainties": "str_list",
    },
    RecognitionTaskType.TABLE_INTERPRETATION: {
        "summary": "str",
        "caption_ref": "opt_str",
        "uncertainties": "str_list",
    },
    RecognitionTaskType.SECTION_LABEL_OBSERVATION: {
        "raw_label": "str",
        "normalized_label": "str",
        "uncertainties": "str_list",
    },
    RecognitionTaskType.RELATION_EVIDENCE_EXTRACTION: {
        "candidate_evidence": "mapping_list",
        "supporting_ids": "str_list",
        "uncertainties": "str_list",
    },
}


class RecognitionOutputValidator:
    """Validate provider payloads against one task's output schema."""

    def validate(
        self,
        task_spec: RecognitionTaskSpec,
        validated_request: ValidatedRecognitionRequest,
        provider_result: str | Mapping[str, Any],
    ) -> tuple[ValidatedRecognitionOutput, ...]:
        """Return validated outputs or raise RecognitionOutputContractError."""

        _require_instance(task_spec, RecognitionTaskSpec, "task_spec")
        _require_instance(validated_request, ValidatedRecognitionRequest, "validated_request")
        payload = _parse_payload(provider_result)
        if not isinstance(payload, Mapping):
            raise RecognitionOutputContractError("not_json_object", "provider result must be a JSON object")

        if "outputs" in payload:
            unknown_wrapper = set(payload) - {"outputs"}
            if unknown_wrapper:
                raise RecognitionOutputContractError(
                    "unknown_wrapper_field",
                    "provider wrapper only allows an outputs list",
                )
            items = payload["outputs"]
            if not isinstance(items, (list, tuple)):
                raise RecognitionOutputContractError("invalid_outputs_list", "outputs must be a list")
            if len(items) > task_spec.max_targets_per_request:
                raise RecognitionOutputContractError(
                    "too_many_outputs",
                    "provider returned more outputs than the task allows",
                )
            return tuple(self._validate_item(item, task_spec, validated_request) for item in items)

        return (self._validate_item(payload, task_spec, validated_request),)

    def _validate_item(
        self,
        item: Any,
        task_spec: RecognitionTaskSpec,
        validated_request: ValidatedRecognitionRequest,
    ) -> ValidatedRecognitionOutput:
        if not isinstance(item, Mapping):
            raise RecognitionOutputContractError("not_json_object", "each output must be a JSON object")
        _reject_forbidden_fact_keys(item, ())
        schema = _SCHEMA_FIELDS[task_spec.task_type]
        allowed = _COMMON_FIELDS | frozenset(schema)
        unknown = set(item) - allowed
        if unknown:
            raise RecognitionOutputContractError(
                "unknown_field",
                f"unknown output field(s): {sorted(unknown)}",
            )

        target_id = item.get("target_id")
        target_type = item.get("target_type")
        status = item.get("status")
        _require_text(target_id, "target_id")
        _require_text(target_type, "target_type")
        _validate_target_ownership(target_id, target_type, validated_request)
        if not isinstance(status, str) or status not in _ALLOWED_OUTPUT_STATUSES:
            raise RecognitionOutputContractError("invalid_status", "output status is not allowed")
        confidence = item.get("confidence")
        if confidence is not None and (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not 0 <= confidence <= 1
        ):
            raise RecognitionOutputContractError("invalid_confidence", "confidence must be between 0 and 1")

        if status in {"succeeded", "partial"}:
            for required in task_spec.required_outputs:
                if required not in item:
                    raise RecognitionOutputContractError(
                        "missing_required_output",
                        f"required output field {required!r} is missing",
                    )
            for field_name, tag in schema.items():
                if field_name in item:
                    _check_field_type(field_name, item[field_name], tag)
        else:
            business_fields = [key for key in item if key not in _COMMON_FIELDS]
            if business_fields:
                raise RecognitionOutputContractError(
                    "no_writable_evidence_for_status",
                    "ambiguous/not_found outputs must not carry business evidence",
                )
        if task_spec.task_type is RecognitionTaskType.RELATION_EVIDENCE_EXTRACTION:
            _validate_relation_evidence(item, validated_request)

        business_output = {key: value for key, value in item.items() if key not in _COMMON_FIELDS}
        uncertainties = item.get("uncertainties")
        uncertainties_tuple = tuple(uncertainties) if isinstance(uncertainties, (list, tuple)) else ()
        return ValidatedRecognitionOutput(
            task_type=task_spec.task_type,
            target_id=target_id,
            target_type=target_type,
            status=RecognitionExecutionStatus(status),
            output=business_output,
            confidence=confidence,
            uncertainties=uncertainties_tuple,
        )


def _validate_target_ownership(
    target_id: str,
    target_type: str,
    validated_request: ValidatedRecognitionRequest,
) -> None:
    expected_type = None
    for target in validated_request.targets:
        if target.target_id == target_id:
            expected_type = target.target_type
            break
    if expected_type is None:
        raise RecognitionOutputContractError("target_not_in_request", "output target_id is not part of the request")
    if expected_type != target_type:
        raise RecognitionOutputContractError(
            "target_type_mismatch",
            "output target_type must match the request target",
        )


def _reject_forbidden_fact_keys(value: Any, path: tuple[str, ...]) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            lowered = str(key).lower()
            if (
                "source_fact" in lowered
                or "derived_relation" in lowered
                or "formal_relation" in lowered
                or lowered in {"source", "derived", "formal"}
            ):
                raise RecognitionOutputContractError(
                    "fact_level_escalation",
                    f"output field {key!r} escalates fact level",
                )
            _reject_forbidden_fact_keys(child, path + (str(key),))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_forbidden_fact_keys(child, path + (str(index),))


def _validate_relation_evidence(
    item: Mapping[str, Any],
    validated_request: ValidatedRecognitionRequest,
) -> None:
    allowed_context: set[str] = set()
    for target in validated_request.targets:
        allowed_context.update(target.context_element_ids)
    evidence = item.get("candidate_evidence")
    if not isinstance(evidence, (list, tuple)):
        raise RecognitionOutputContractError(
            "invalid_relation_evidence",
            "candidate_evidence must be a list",
        )
    for entry in evidence:
        if not isinstance(entry, Mapping):
            raise RecognitionOutputContractError(
                "invalid_relation_evidence",
                "candidate evidence entries must be objects",
            )
        supporting_ids = entry.get("supporting_ids")
        if not isinstance(supporting_ids, (list, tuple)) or not supporting_ids:
            raise RecognitionOutputContractError(
                "invalid_relation_evidence",
                "candidate evidence entries require supporting_ids",
            )
        for supporting_id in supporting_ids:
            if supporting_id not in allowed_context:
                raise RecognitionOutputContractError(
                    "supporting_id_outside_context",
                    "supporting_ids must come from the request context whitelist",
                )


def _parse_payload(provider_result: str | Mapping[str, Any]) -> Any:
    if isinstance(provider_result, str):
        try:
            return json.loads(provider_result)
        except (ValueError, TypeError) as exc:
            raise RecognitionOutputContractError("malformed_json", "provider returned malformed JSON") from exc
    return provider_result


def _check_field_type(field_name: str, value: Any, tag: str) -> None:
    if tag == "str":
        _require_text(value, field_name)
    elif tag == "opt_str":
        if value is not None:
            _require_text(value, field_name)
    elif tag == "str_list":
        if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
            raise RecognitionOutputContractError("invalid_field_type", f"{field_name} must be a list of strings")
        for item in value:
            _require_text(item, field_name)
    elif tag == "mapping":
        if not isinstance(value, Mapping):
            raise RecognitionOutputContractError("invalid_field_type", f"{field_name} must be an object")
    elif tag == "mapping_list":
        if isinstance(value, Mapping) or not isinstance(value, (list, tuple)):
            raise RecognitionOutputContractError("invalid_field_type", f"{field_name} must be a list of objects")
        for item in value:
            if not isinstance(item, Mapping):
                raise RecognitionOutputContractError("invalid_field_type", f"{field_name} must contain objects")
    else:
        raise RecognitionOutputContractError("invalid_schema", f"unsupported schema tag {tag!r}")


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecognitionOutputContractError("invalid_field_type", f"{field_name} must be a non-empty string")
    return value


def _require_instance(value: Any, expected: type, field_name: str) -> None:
    if not isinstance(value, expected):
        raise RecognitionOutputContractError("invalid_input", f"{field_name} must be a {expected.__name__}")


__all__ = ("RecognitionOutputContractError", "RecognitionOutputValidator")
