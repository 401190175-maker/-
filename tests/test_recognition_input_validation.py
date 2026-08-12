"""Offline contract tests for recognition input validation."""

from __future__ import annotations

import unittest

from drawing_graph.recognition_input_validation import RecognitionInputError, RecognitionInputValidator
from drawing_graph.recognition_models import (
    RecognitionExecutionRequest,
    RecognitionTaskType,
    ValidatedRecognitionRequest,
)
from drawing_graph.recognition_tasks import (
    block_semantic_identification_spec,
    page_summary_spec,
    table_interpretation_spec,
)
from drawing_graph.tool_models import BBox, ElementEvidence, PageSourceFacts, SemanticTargetInput


def _element(
    element_id: str = "block-1",
    element_type: str = "DrawingBlock",
) -> ElementEvidence:
    return ElementEvidence(
        element_id=element_id,
        element_type=element_type,
        bbox=BBox(10, 10, 100, 100),
        normalized_bbox=BBox(0.01, 0.01, 0.1, 0.1),
        source_label=element_id,
    )


def _page_facts(*elements: ElementEvidence) -> PageSourceFacts:
    return PageSourceFacts(
        page_id="page-1",
        image_path=r"C:\drawings\page-1.png",
        elements=tuple(elements),
        image_size=(1000, 800),
        image_hash="hash-1",
    )


def _target(
    *,
    target_id: str = "target-1",
    page_id: str = "page-1",
    target_type: str = "DrawingBlock",
    task_type: str = "block_semantic_identification",
    target_element_id: str | None = "block-1",
) -> SemanticTargetInput:
    return SemanticTargetInput(
        target_id=target_id,
        page_id=page_id,
        target_type=target_type,
        task_type=task_type,
        target_element_id=target_element_id,
    )


def _request(target: SemanticTargetInput, *, task_type: str | None = None) -> RecognitionExecutionRequest:
    return RecognitionExecutionRequest(
        request_id="req-1",
        recognition_run_id="run-1",
        page_id=target.page_id,
        task_type=task_type or target.task_type,
        targets=(target,),
        model_profile="default",
        prompt_version="prompt-v1",
        input_contract_version="1",
        output_contract_version="1",
        preprocessing_version="preprocess-v1",
        write_back=False,
        deadline_seconds=60.0,
    )


class RecognitionIdentityValidationTests(unittest.TestCase):
    """Provider-call identity and task-type validation."""

    def test_valid_page_summary_target(self) -> None:
        target = _target(
            target_id="target-page",
            target_type="DrawingPage",
            task_type="page_summary",
            target_element_id=None,
        )
        validated = RecognitionInputValidator().validate(_request(target), _page_facts(), page_summary_spec())
        self.assertIsInstance(validated, ValidatedRecognitionRequest)
        self.assertEqual("page-1", validated.page_id)
        self.assertEqual(RecognitionTaskType.PAGE_SUMMARY, validated.task_type)
        self.assertEqual(r"C:\drawings\page-1.png", validated.image_path)
        self.assertEqual((1000, 800), validated.image_size)

    def test_valid_block_target(self) -> None:
        validated = RecognitionInputValidator().validate(
            _request(_target()),
            _page_facts(_element()),
            block_semantic_identification_spec(),
        )
        self.assertEqual(1, len(validated.targets))

    def test_page_id_mismatch_is_rejected(self) -> None:
        target = _target(page_id="other-page")
        with self.assertRaises(RecognitionInputError):
            RecognitionInputValidator().validate(
                _request(target),
                _page_facts(_element()),
                block_semantic_identification_spec(),
            )

    def test_target_page_id_mismatch_is_rejected(self) -> None:
        target = _target(page_id="other-page")
        request = _request(target)
        with self.assertRaises(RecognitionInputError):
            RecognitionInputValidator().validate(request, _page_facts(_element()), block_semantic_identification_spec())

    def test_task_type_mismatch_with_spec_is_rejected(self) -> None:
        target = _target(task_type="page_summary", target_type="DrawingPage", target_element_id=None)
        with self.assertRaises(RecognitionInputError):
            RecognitionInputValidator().validate(_request(target), _page_facts(), table_interpretation_spec())

    def test_disallowed_target_type_is_rejected(self) -> None:
        target = _target(target_type="Table")
        with self.assertRaises(RecognitionInputError):
            RecognitionInputValidator().validate(
                _request(target),
                _page_facts(_element()),
                block_semantic_identification_spec(),
            )

    def test_element_task_without_element_id_is_rejected(self) -> None:
        target = _target(target_element_id=None)
        with self.assertRaises(RecognitionInputError):
            RecognitionInputValidator().validate(
                _request(target),
                _page_facts(_element()),
                block_semantic_identification_spec(),
            )

    def test_unknown_element_id_is_rejected(self) -> None:
        target = _target(target_element_id="missing")
        with self.assertRaises(RecognitionInputError):
            RecognitionInputValidator().validate(
                _request(target),
                _page_facts(_element()),
                block_semantic_identification_spec(),
            )

    def test_element_type_mismatch_is_rejected(self) -> None:
        target = _target(target_element_id="caption-1", target_type="DrawingBlock")
        facts = _page_facts(_element("caption-1", "BlockCaption"))
        with self.assertRaises(RecognitionInputError):
            RecognitionInputValidator().validate(
                _request(target),
                facts,
                block_semantic_identification_spec(),
            )

    def test_page_target_with_element_id_is_rejected(self) -> None:
        target = _target(
            target_type="DrawingPage",
            task_type="page_summary",
            target_element_id="block-1",
        )
        with self.assertRaises(RecognitionInputError):
            RecognitionInputValidator().validate(
                _request(target),
                _page_facts(_element()),
                page_summary_spec(),
            )

    def test_validation_module_is_pure(self) -> None:
        from pathlib import Path

        import drawing_graph.recognition_input_validation as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        import_lines = "\n".join(
            line.strip().lower()
            for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))
        )
        for forbidden in ("neo4j", "repository", "cypher", "httpx", "qwen", "facade", "os.environ", "pathlib"):
            self.assertNotIn(forbidden, import_lines)


if __name__ == "__main__":
    unittest.main()
