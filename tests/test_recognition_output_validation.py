"""Offline contract tests for recognition output schema validation."""

from __future__ import annotations

import unittest
from pathlib import Path

from drawing_graph.recognition_models import (
    RecognitionTaskType,
    ValidatedRecognitionOutput,
    ValidatedRecognitionRequest,
)
from drawing_graph.recognition_output_validation import (
    RecognitionOutputContractError,
    RecognitionOutputValidator,
)
from drawing_graph.recognition_tasks import build_default_task_registry
from drawing_graph.tool_models import SemanticTargetInput


def _request(task_type: str) -> ValidatedRecognitionRequest:
    return ValidatedRecognitionRequest(
        request_id="req-1",
        recognition_run_id="run-1",
        page_id="page-1",
        task_type=RecognitionTaskType(task_type),
        targets=(_target(task_type),),
        model_profile="default",
        prompt_version="prompt-v1",
        input_contract_version="1",
        output_contract_version="1",
        preprocessing_version="preprocess-v1",
        write_back=False,
        deadline_seconds=60.0,
        image_path=None,
    )


def _target(task_type: str) -> SemanticTargetInput:
    if task_type == "page_summary":
        return SemanticTargetInput(
            target_id="target-page",
            page_id="page-1",
            target_type="DrawingPage",
            task_type=task_type,
        )
    target_type = {
        "element_text_observation": "BlockCaption",
        "block_semantic_identification": "DrawingBlock",
        "basic_info_interpretation": "DrawingBasicInfo",
        "table_interpretation": "Table",
        "section_label_observation": "CrossSection",
        "relation_evidence_extraction": "DrawingBlock",
    }[task_type]
    context_ids = ()
    if task_type == "relation_evidence_extraction":
        context_ids = ("caption-1",)
    return SemanticTargetInput(
        target_id="target-1",
        page_id="page-1",
        target_type=target_type,
        task_type=task_type,
        target_element_id="element-1",
        context_element_ids=context_ids,
    )


def _valid_payload(task_type: str) -> dict:
    payloads = {
        "page_summary": {
            "target_id": "target-page",
            "target_type": "DrawingPage",
            "status": "succeeded",
            "summary": "page text",
            "key_elements": ["title"],
            "uncertainties": [],
        },
        "element_text_observation": {
            "target_id": "target-1",
            "target_type": "BlockCaption",
            "status": "succeeded",
            "observations": [{"raw_text": "caption", "normalized_text": "caption"}],
        },
        "block_semantic_identification": {
            "target_id": "target-1",
            "target_type": "DrawingBlock",
            "status": "succeeded",
            "interpretation": {"summary": "a block"},
            "observations": [],
        },
        "basic_info_interpretation": {
            "target_id": "target-1",
            "target_type": "DrawingBasicInfo",
            "status": "succeeded",
            "raw_text": "DWG-001",
            "summary": "drawing info",
        },
        "table_interpretation": {
            "target_id": "target-1",
            "target_type": "Table",
            "status": "succeeded",
            "summary": "a table",
            "caption_ref": "caption-1",
            "uncertainties": [],
        },
        "section_label_observation": {
            "target_id": "target-1",
            "target_type": "CrossSection",
            "status": "succeeded",
            "raw_label": "A-A",
            "normalized_label": "A-A",
        },
        "relation_evidence_extraction": {
            "target_id": "target-1",
            "target_type": "DrawingBlock",
            "status": "succeeded",
            "candidate_evidence": [
                {"relation_type": "CANDIDATE_CAPTION_OF", "supporting_ids": ["caption-1"]}
            ],
            "supporting_ids": ["caption-1"],
            "uncertainties": [],
        },
    }
    return payloads[task_type]


class OutputSchemaTests(unittest.TestCase):
    """Provider payloads must satisfy strict per-task output schemas."""

    def test_valid_page_summary_payload_passes(self) -> None:
        result = RecognitionOutputValidator().validate(
            build_default_task_registry().get("page_summary"),
            _request("page_summary"),
            _valid_payload("page_summary"),
        )
        self.assertEqual(1, len(result))
        self.assertIsInstance(result[0], ValidatedRecognitionOutput)
        self.assertEqual("page text", result[0].output["summary"])

    def test_top_level_must_be_json_object(self) -> None:
        validator = RecognitionOutputValidator()
        spec = build_default_task_registry().get("page_summary")
        request = _request("page_summary")
        with self.assertRaises(RecognitionOutputContractError):
            validator.validate(spec, request, "[1, 2]")
        with self.assertRaises(RecognitionOutputContractError):
            validator.validate(spec, request, "not-json")

    def test_malformed_json_raises_contract_error(self) -> None:
        with self.assertRaises(RecognitionOutputContractError):
            RecognitionOutputValidator().validate(
                build_default_task_registry().get("page_summary"),
                _request("page_summary"),
                '{"summary": "x"',
            )

    def test_unknown_fields_are_rejected(self) -> None:
        payload = _valid_payload("page_summary")
        payload["hack_field"] = True
        with self.assertRaises(RecognitionOutputContractError):
            RecognitionOutputValidator().validate(
                build_default_task_registry().get("page_summary"),
                _request("page_summary"),
                payload,
            )

    def test_required_outputs_must_be_present(self) -> None:
        payload = _valid_payload("page_summary")
        del payload["summary"]
        with self.assertRaises(RecognitionOutputContractError):
            RecognitionOutputValidator().validate(
                build_default_task_registry().get("page_summary"),
                _request("page_summary"),
                payload,
            )

    def test_field_types_are_validated(self) -> None:
        payload = _valid_payload("page_summary")
        payload["summary"] = 123
        with self.assertRaises(RecognitionOutputContractError):
            RecognitionOutputValidator().validate(
                build_default_task_registry().get("page_summary"),
                _request("page_summary"),
                payload,
            )

    def test_status_enum_is_validated(self) -> None:
        payload = _valid_payload("page_summary")
        payload["status"] = "unknown"
        with self.assertRaises(RecognitionOutputContractError):
            RecognitionOutputValidator().validate(
                build_default_task_registry().get("page_summary"),
                _request("page_summary"),
                payload,
            )

    def test_ambiguous_and_not_found_are_allowed_output_statuses(self) -> None:
        validator = RecognitionOutputValidator()
        spec = build_default_task_registry().get("page_summary")
        request = _request("page_summary")
        for status in ("ambiguous", "not_found"):
            payload = {
                "target_id": "target-page",
                "target_type": "DrawingPage",
                "status": status,
            }
            with self.subTest(status=status):
                result = validator.validate(spec, request, payload)
                self.assertEqual(status, result[0].status.value)
        for status in ("partial", "succeeded"):
            payload = _valid_payload("page_summary")
            payload["status"] = status
            with self.subTest(status=status):
                result = validator.validate(spec, request, payload)
                self.assertEqual(status, result[0].status.value)

    def test_confidence_must_be_in_unit_range(self) -> None:
        payload = _valid_payload("page_summary")
        payload["confidence"] = 1.5
        with self.assertRaises(RecognitionOutputContractError):
            RecognitionOutputValidator().validate(
                build_default_task_registry().get("page_summary"),
                _request("page_summary"),
                payload,
            )

    def test_max_return_count_is_enforced(self) -> None:
        payload = _valid_payload("page_summary")
        wrapped = {"outputs": [payload, payload]}
        with self.assertRaises(RecognitionOutputContractError):
            RecognitionOutputValidator().validate(
                build_default_task_registry().get("page_summary"),
                _request("page_summary"),
                wrapped,
            )

    def test_wrapped_single_output_is_accepted(self) -> None:
        result = RecognitionOutputValidator().validate(
            build_default_task_registry().get("page_summary"),
            _request("page_summary"),
            {"outputs": [_valid_payload("page_summary")]},
        )
        self.assertEqual(1, len(result))

    def test_each_task_accepts_its_valid_minimal_output(self) -> None:
        validator = RecognitionOutputValidator()
        registry = build_default_task_registry()
        for task_type in RecognitionTaskType:
            with self.subTest(task=task_type.value):
                result = validator.validate(
                    registry.get(task_type.value),
                    _request(task_type.value),
                    _valid_payload(task_type.value),
                )
                self.assertEqual(1, len(result))
                self.assertEqual(task_type, result[0].task_type)

    def test_validator_module_is_pure(self) -> None:
        import drawing_graph.recognition_output_validation as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        import_lines = "\n".join(
            line.strip().lower()
            for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))
        )
        for forbidden in ("neo4j", "repository", "cypher", "httpx", "qwen", "facade", "os.environ", "pathlib"):
            self.assertNotIn(forbidden, import_lines)


class OutputAuthorityTests(unittest.TestCase):
    """Outputs must bind to request targets and stay below formal facts."""

    def _page_context(self):
        return RecognitionOutputValidator(), build_default_task_registry(), _request("page_summary")

    def test_target_not_in_request_is_rejected(self) -> None:
        validator, registry, request = self._page_context()
        payload = _valid_payload("page_summary")
        payload["target_id"] = "other-target"
        with self.assertRaises(RecognitionOutputContractError):
            validator.validate(registry.get("page_summary"), request, payload)

    def test_target_type_mismatch_is_rejected(self) -> None:
        validator, registry, request = self._page_context()
        payload = _valid_payload("page_summary")
        payload["target_type"] = "DrawingBlock"
        with self.assertRaises(RecognitionOutputContractError):
            validator.validate(registry.get("page_summary"), request, payload)

    def test_source_fact_declaration_is_rejected(self) -> None:
        validator, registry, request = self._page_context()
        payload = _valid_payload("page_summary")
        payload["source_fact"] = "confirmed"
        with self.assertRaises(RecognitionOutputContractError):
            validator.validate(registry.get("page_summary"), request, payload)

    def test_nested_derived_relation_key_is_rejected(self) -> None:
        validator, registry, request = self._page_context()
        payload = _valid_payload("page_summary")
        payload["key_elements"] = [{"derived_relation": "HAS_CAPTION"}]
        with self.assertRaises(RecognitionOutputContractError):
            validator.validate(registry.get("page_summary"), request, payload)

    def test_formal_declaration_is_rejected(self) -> None:
        validator, registry, request = self._page_context()
        payload = _valid_payload("page_summary")
        payload["formal_relation"] = "MATCHES_SECTION_CAPTION"
        with self.assertRaises(RecognitionOutputContractError):
            validator.validate(registry.get("page_summary"), request, payload)

    def test_relation_supporting_ids_must_come_from_allowed_context(self) -> None:
        validator = RecognitionOutputValidator()
        registry = build_default_task_registry()
        request = _request("relation_evidence_extraction")
        payload = _valid_payload("relation_evidence_extraction")
        payload["supporting_ids"] = ["outside-id"]
        payload["candidate_evidence"][0]["supporting_ids"] = ["outside-id"]
        with self.assertRaises(RecognitionOutputContractError):
            validator.validate(registry.get("relation_evidence_extraction"), request, payload)

    def test_relation_evidence_entries_require_supporting_ids(self) -> None:
        validator = RecognitionOutputValidator()
        registry = build_default_task_registry()
        request = _request("relation_evidence_extraction")
        payload = _valid_payload("relation_evidence_extraction")
        del payload["candidate_evidence"][0]["supporting_ids"]
        with self.assertRaises(RecognitionOutputContractError):
            validator.validate(registry.get("relation_evidence_extraction"), request, payload)

    def test_ambiguous_output_with_business_fields_is_rejected(self) -> None:
        validator, registry, request = self._page_context()
        payload = _valid_payload("page_summary")
        payload["status"] = "ambiguous"
        with self.assertRaises(RecognitionOutputContractError):
            validator.validate(registry.get("page_summary"), request, payload)

    def test_not_found_output_with_business_fields_is_rejected(self) -> None:
        validator, registry, request = self._page_context()
        payload = _valid_payload("page_summary")
        payload["status"] = "not_found"
        with self.assertRaises(RecognitionOutputContractError):
            validator.validate(registry.get("page_summary"), request, payload)

    def test_ambiguous_minimal_payload_passes(self) -> None:
        validator, registry, request = self._page_context()
        payload = {
            "target_id": "target-page",
            "target_type": "DrawingPage",
            "status": "ambiguous",
        }
        result = validator.validate(registry.get("page_summary"), request, payload)
        self.assertEqual("ambiguous", result[0].status.value)
        self.assertEqual({}, result[0].output)


if __name__ == "__main__":
    unittest.main()
