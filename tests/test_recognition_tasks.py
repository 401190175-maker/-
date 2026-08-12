"""Offline contract tests for the recognition task registry."""

from __future__ import annotations

import unittest

from dataclasses import replace

from drawing_graph.recognition_models import RecognitionTaskType
from drawing_graph.recognition_tasks import (
    RecognitionTaskRegistry,
    RecognitionTaskSpec,
    page_summary_spec,
)
from drawing_graph.tool_models import ToolModelError


def _spec(task_type: RecognitionTaskType | str = RecognitionTaskType.PAGE_SUMMARY) -> RecognitionTaskSpec:
    return RecognitionTaskSpec(
        task_type=task_type,
        allowed_target_types=("DrawingPage",),
        required_context_types=(),
        prompt_template_id="prompt/page-summary",
        prompt_version="prompt-v1",
        input_contract_id="input/page-summary",
        input_contract_version="1",
        output_schema_id="output/page-summary",
        output_contract_version="1",
        crop_policy_id="crop/page-summary",
        preprocessing_version="preprocess-v1",
        max_targets_per_request=1,
        required_outputs=("summary", "key_elements", "uncertainties"),
        allow_structure_repair=False,
        allowed_write_back=("run", "payload"),
    )


class RecognitionTaskSpecTests(unittest.TestCase):
    """RecognitionTaskSpec must bind one immutable task contract."""

    def test_valid_spec(self) -> None:
        spec = _spec()
        self.assertIs(RecognitionTaskType.PAGE_SUMMARY, spec.task_type)
        self.assertEqual(("DrawingPage",), spec.allowed_target_types)
        self.assertEqual("prompt/page-summary", spec.prompt_template_id)
        self.assertEqual("1", spec.output_contract_version)
        self.assertEqual(("run", "payload"), spec.allowed_write_back)

    def test_unknown_task_type_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _spec("unknown_task")

    def test_empty_allowed_target_types_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            replace(_spec(), allowed_target_types=())

    def test_empty_version_or_schema_id_is_rejected(self) -> None:
        for field_name in (
            "prompt_template_id",
            "prompt_version",
            "input_contract_id",
            "input_contract_version",
            "output_schema_id",
            "output_contract_version",
            "crop_policy_id",
            "preprocessing_version",
        ):
            with self.subTest(field=field_name):
                with self.assertRaises(ValueError):
                    replace(_spec(), **{field_name: ""})

    def test_duplicate_allowed_target_type_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            replace(_spec(), allowed_target_types=("DrawingPage", "DrawingPage"))

    def test_max_targets_per_request_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            replace(_spec(), max_targets_per_request=0)

    def test_empty_required_outputs_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            replace(_spec(), required_outputs=())

    def test_allow_structure_repair_must_be_boolean(self) -> None:
        with self.assertRaises(ValueError):
            replace(_spec(), allow_structure_repair="yes")

    def test_allowed_write_back_must_include_run_and_payload(self) -> None:
        with self.assertRaises(ValueError):
            replace(_spec(), allowed_write_back=("TextObservation",))

    def test_spec_is_immutable(self) -> None:
        spec = _spec()
        with self.assertRaises(Exception):
            spec.task_type = RecognitionTaskType.TABLE_INTERPRETATION


class RecognitionTaskRegistryTests(unittest.TestCase):
    """RecognitionTaskRegistry exposes stable get/list/validate contracts."""

    def test_empty_registry_fails_validation(self) -> None:
        registry = RecognitionTaskRegistry(specs=())
        with self.assertRaises(ToolModelError):
            registry.validate_registry()

    def test_get_returns_registered_spec(self) -> None:
        spec = _spec()
        registry = RecognitionTaskRegistry(specs=(spec,))
        self.assertIs(spec, registry.get(RecognitionTaskType.PAGE_SUMMARY))
        self.assertIs(spec, registry.get("page_summary"))

    def test_get_unknown_task_raises_not_found(self) -> None:
        registry = RecognitionTaskRegistry(specs=(_spec(),))
        with self.assertRaises(ToolModelError):
            registry.get("table_interpretation")

    def test_duplicate_task_type_is_rejected(self) -> None:
        with self.assertRaises(ToolModelError):
            RecognitionTaskRegistry(specs=(_spec(), _spec()))

    def test_mutable_sequence_input_is_rejected(self) -> None:
        with self.assertRaises(ToolModelError):
            RecognitionTaskRegistry(specs=[_spec()])

    def test_registry_is_immutable(self) -> None:
        registry = RecognitionTaskRegistry(specs=(_spec(),))
        with self.assertRaises(Exception):
            registry.specs = ()

    def test_list_specs_keeps_registration_order(self) -> None:
        first = _spec(RecognitionTaskType.PAGE_SUMMARY)
        second = replace(
            _spec(RecognitionTaskType.TABLE_INTERPRETATION),
            allowed_target_types=("Table",),
            required_outputs=("summary", "caption_ref", "uncertainties"),
        )
        registry = RecognitionTaskRegistry(specs=(first, second))
        self.assertEqual((first, second), registry.list_specs())

    def test_registry_is_pure(self) -> None:
        from pathlib import Path

        import drawing_graph.recognition_tasks as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        import_lines = "\n".join(
            line.strip().lower()
            for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))
        )
        for forbidden in ("neo4j", "repository", "cypher", "httpx", "qwen", "facade", "os.environ", "pathlib"):
            self.assertNotIn(forbidden, import_lines)


class PageSummarySpecTests(unittest.TestCase):
    """page_summary binds the full-page controlled-resize contract."""

    def test_page_summary_spec(self) -> None:
        spec = page_summary_spec()
        self.assertIs(RecognitionTaskType.PAGE_SUMMARY, spec.task_type)
        self.assertEqual(("DrawingPage",), spec.allowed_target_types)
        self.assertEqual(("summary", "key_elements", "uncertainties"), spec.required_outputs)
        self.assertTrue(spec.crop_policy_id.startswith("crop/"))
        self.assertIn("full-page", spec.crop_policy_id)
        self.assertEqual(("run", "payload"), spec.allowed_write_back)
        self.assertNotIn("PageInterpretation", spec.allowed_write_back)
        self.assertTrue(spec.prompt_template_id)
        self.assertTrue(spec.prompt_version)
        self.assertTrue(spec.input_contract_id)
        self.assertTrue(spec.input_contract_version)
        self.assertTrue(spec.output_schema_id)
        self.assertTrue(spec.output_contract_version)
        self.assertGreaterEqual(spec.max_targets_per_request, 1)


if __name__ == "__main__":
    unittest.main()
