"""Offline contract tests for task-specific prompt rendering."""

from __future__ import annotations

import unittest
from pathlib import Path

from drawing_graph.recognition_image_preprocessing import PreparedRecognitionImage
from drawing_graph.recognition_models import (
    RecognitionImageRole,
    RecognitionTaskType,
    ValidatedRecognitionRequest,
)
from drawing_graph.recognition_prompting import (
    RecognitionPromptError,
    RecognitionPromptRenderer,
    RenderedRecognitionPrompt,
)
from drawing_graph.recognition_tasks import (
    build_default_task_registry,
    element_text_observation_spec,
    page_summary_spec,
)
from drawing_graph.tool_models import BBox, SemanticTargetInput


def _prepared_image(role: str = "target") -> PreparedRecognitionImage:
    return PreparedRecognitionImage(
        role=RecognitionImageRole(role),
        mime="image/png",
        content=b"\x89PNG\r\n\x1a\n",
        source_hash="a" * 64,
        prepared_hash="b" * 64,
        source_size=(100, 80),
        crop_bbox=BBox(0, 0, 62, 52),
        padding=12,
        output_size=(62, 52),
        scale=1.0,
        preprocessing_version="preprocess-v1",
    )


def _target(
    *,
    target_id: str = "target-1",
    target_type: str = "DrawingBlock",
    task_type: str = "block_semantic_identification",
    target_element_id: str | None = "block-1",
    context_element_ids: tuple[str, ...] = (),
) -> SemanticTargetInput:
    return SemanticTargetInput(
        target_id=target_id,
        page_id="page-1",
        target_type=target_type,
        task_type=task_type,
        target_element_id=target_element_id,
        bbox=BBox(10, 10, 50, 40),
        normalized_bbox=BBox(0.1, 0.125, 0.5, 0.5),
        context_element_ids=context_element_ids,
    )


def _request(
    *,
    task_type: str = "block_semantic_identification",
    targets: tuple[SemanticTargetInput, ...] | None = None,
) -> ValidatedRecognitionRequest:
    return ValidatedRecognitionRequest(
        request_id="req-1",
        recognition_run_id="run-1",
        page_id="page-1",
        task_type=RecognitionTaskType(task_type),
        targets=targets or (_target(),),
        model_profile="default",
        prompt_version="prompt-v1",
        input_contract_version="1",
        output_contract_version="1",
        preprocessing_version="preprocess-v1",
        write_back=False,
        deadline_seconds=60.0,
        image_path=r"C:\secrets\drawings\page-1.png",
        image_size=(100, 80),
    )


class RecognitionPromptRenderingTests(unittest.TestCase):
    """Rendered prompts are task-specific, safe and versioned."""

    def test_page_summary_prompt_binds_schema_and_version(self) -> None:
        target = SemanticTargetInput(
            target_id="target-page",
            page_id="page-1",
            target_type="DrawingPage",
            task_type="page_summary",
        )
        rendered = RecognitionPromptRenderer().render(
            page_summary_spec(),
            _request(task_type="page_summary", targets=(target,)),
            (_prepared_image("page"),),
        )
        self.assertIsInstance(rendered, RenderedRecognitionPrompt)
        self.assertEqual("output/page-summary", rendered.schema_id)
        self.assertEqual("1", rendered.schema_version)
        self.assertEqual("prompt-v1", rendered.prompt_version)
        self.assertEqual(("page",), rendered.image_role_order)

    def test_each_task_renders_own_instruction(self) -> None:
        renderer = RecognitionPromptRenderer()
        instructions: set[str] = set()
        for spec in build_default_task_registry().list_specs():
            with self.subTest(task=spec.task_type.value):
                rendered = renderer.render(spec, _request(task_type=spec.task_type.value), (_prepared_image(),))
                self.assertTrue(rendered.system_instruction)
                self.assertEqual(spec.output_schema_id, rendered.schema_id)
                self.assertEqual(spec.output_contract_version, rendered.schema_version)
                self.assertEqual(spec.prompt_version, rendered.prompt_version)
                instructions.add(rendered.system_instruction)
        self.assertEqual(7, len(instructions))

    def test_image_text_is_declared_as_data_not_instruction(self) -> None:
        rendered = RecognitionPromptRenderer().render(
            page_summary_spec(),
            _request(task_type="page_summary", targets=(_page_target(),)),
            (_prepared_image("page"),),
        )
        self.assertIn("数据", rendered.system_instruction)
        self.assertIn("指令", rendered.system_instruction)

    def test_uncertainty_convention_is_present(self) -> None:
        rendered = RecognitionPromptRenderer().render(
            page_summary_spec(),
            _request(task_type="page_summary", targets=(_page_target(),)),
            (_prepared_image("page"),),
        )
        self.assertIn("ambiguous", rendered.system_instruction)
        self.assertIn("not_found", rendered.system_instruction)

    def test_relation_task_requires_candidate_marking(self) -> None:
        spec = build_default_task_registry().get("relation_evidence_extraction")
        rendered = RecognitionPromptRenderer().render(
            spec,
            _request(task_type="relation_evidence_extraction"),
            (_prepared_image(),),
        )
        self.assertIn("candidate_relation", rendered.system_instruction)

    def test_user_instruction_contains_only_whitelisted_fields(self) -> None:
        target = _target(context_element_ids=("caption-1",))
        rendered = RecognitionPromptRenderer().render(
            element_text_observation_spec(),
            _request(task_type="element_text_observation", targets=(target,)),
            (_prepared_image("target"), _prepared_image("context")),
        )
        self.assertIn("page-1", rendered.user_instruction)
        self.assertIn("target-1", rendered.user_instruction)
        self.assertIn("caption-1", rendered.user_instruction)
        self.assertNotIn("secrets", rendered.user_instruction)
        self.assertNotIn("page-1.png", rendered.user_instruction)
        self.assertNotIn("api_key", rendered.user_instruction.lower())
        self.assertNotIn("authorization", rendered.user_instruction.lower())

    def test_image_role_order_reflects_prepared_images(self) -> None:
        rendered = RecognitionPromptRenderer().render(
            element_text_observation_spec(),
            _request(task_type="element_text_observation", targets=(_target(),)),
            (_prepared_image("target"), _prepared_image("context"), _prepared_image("page")),
        )
        self.assertEqual(("target", "context", "page"), rendered.image_role_order)

    def test_fingerprint_is_deterministic_for_same_input(self) -> None:
        renderer = RecognitionPromptRenderer()
        first = renderer.render(
            page_summary_spec(),
            _request(task_type="page_summary", targets=(_page_target(),)),
            (_prepared_image("page"),),
        )
        second = renderer.render(
            page_summary_spec(),
            _request(task_type="page_summary", targets=(_page_target(),)),
            (_prepared_image("page"),),
        )
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(64, len(first.fingerprint))

    def test_fingerprint_changes_when_prompt_version_changes(self) -> None:
        renderer = RecognitionPromptRenderer()
        base = renderer.render(
            page_summary_spec(),
            _request(task_type="page_summary", targets=(_page_target(),)),
            (_prepared_image("page"),),
        )
        from dataclasses import replace

        changed_spec = replace(page_summary_spec(), prompt_version="prompt-v2")
        changed = renderer.render(
            changed_spec,
            _request(task_type="page_summary", targets=(_page_target(),)),
            (_prepared_image("page"),),
        )
        self.assertNotEqual(base.fingerprint, changed.fingerprint)

    def test_fingerprint_changes_when_target_changes(self) -> None:
        renderer = RecognitionPromptRenderer()
        first = renderer.render(
            element_text_observation_spec(),
            _request(task_type="element_text_observation", targets=(_target(target_id="target-1"),)),
            (_prepared_image(),),
        )
        second = renderer.render(
            element_text_observation_spec(),
            _request(task_type="element_text_observation", targets=(_target(target_id="target-2"),)),
            (_prepared_image(),),
        )
        self.assertNotEqual(first.fingerprint, second.fingerprint)

    def test_invalid_inputs_raise_recognition_prompt_error(self) -> None:
        renderer = RecognitionPromptRenderer()
        with self.assertRaises(RecognitionPromptError):
            renderer.render(None, _request(), (_prepared_image(),))
        with self.assertRaises(RecognitionPromptError):
            renderer.render(page_summary_spec(), _request(task_type="page_summary", targets=(_page_target(),)), [])

    def test_renderer_module_is_pure(self) -> None:
        import drawing_graph.recognition_prompting as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        import_lines = "\n".join(
            line.strip().lower()
            for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))
        )
        for forbidden in ("neo4j", "repository", "cypher", "httpx", "qwen", "facade", "os.environ", "pathlib"):
            self.assertNotIn(forbidden, import_lines)


def _page_target() -> SemanticTargetInput:
    return SemanticTargetInput(
        target_id="target-page",
        page_id="page-1",
        target_type="DrawingPage",
        task_type="page_summary",
    )


if __name__ == "__main__":
    unittest.main()
