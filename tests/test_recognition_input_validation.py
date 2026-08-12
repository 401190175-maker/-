"""Offline contract tests for recognition input validation."""

from __future__ import annotations

import unittest

from drawing_graph.recognition_input_validation import RecognitionInputError, RecognitionInputValidator
from drawing_graph.recognition_models import (
    RecognitionExecutionPolicy,
    RecognitionExecutionRequest,
    RecognitionTaskType,
    ValidatedRecognitionRequest,
)
from drawing_graph.recognition_tasks import (
    block_semantic_identification_spec,
    page_summary_spec,
    section_label_observation_spec,
    table_interpretation_spec,
)
from drawing_graph.tool_models import BBox, ElementEvidence, PageSourceFacts, SemanticTargetInput


def _element(
    element_id: str = "block-1",
    element_type: str = "DrawingBlock",
    bbox: BBox | None = None,
    normalized_bbox: BBox | None = None,
) -> ElementEvidence:
    return ElementEvidence(
        element_id=element_id,
        element_type=element_type,
        bbox=bbox or BBox(10, 10, 100, 100),
        normalized_bbox=normalized_bbox or BBox(0.01, 0.0125, 0.1, 0.125),
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


_MISSING = object()


def _target(
    *,
    target_id: str = "target-1",
    page_id: str = "page-1",
    target_type: str = "DrawingBlock",
    task_type: str = "block_semantic_identification",
    target_element_id: str | None = "block-1",
    bbox: BBox | None | object = _MISSING,
    normalized_bbox: BBox | None | object = _MISSING,
    context_element_ids: tuple[str, ...] = (),
) -> SemanticTargetInput:
    if bbox is _MISSING:
        bbox = None if task_type == "page_summary" else BBox(10, 10, 100, 100)
    if normalized_bbox is _MISSING:
        normalized_bbox = None if task_type == "page_summary" else BBox(0.01, 0.0125, 0.1, 0.125)
    return SemanticTargetInput(
        target_id=target_id,
        page_id=page_id,
        target_type=target_type,
        task_type=task_type,
        target_element_id=target_element_id,
        bbox=bbox,
        normalized_bbox=normalized_bbox,
        context_element_ids=context_element_ids,
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


class RecognitionSpatialValidationTests(unittest.TestCase):
    """bbox, normalized bbox and same-page context validation."""

    def test_element_task_without_bbox_is_rejected(self) -> None:
        target = _target(bbox=None, normalized_bbox=None)
        with self.assertRaises(RecognitionInputError):
            RecognitionInputValidator().validate(
                _request(target),
                _page_facts(_element()),
                block_semantic_identification_spec(),
            )

    def test_nan_bbox_coordinate_is_rejected(self) -> None:
        target = _target(bbox=BBox(float("nan"), 10, 100, 100))
        with self.assertRaises(RecognitionInputError):
            RecognitionInputValidator().validate(
                _request(target),
                _page_facts(_element()),
                block_semantic_identification_spec(),
            )

    def test_infinite_bbox_coordinate_is_rejected(self) -> None:
        target = _target(bbox=BBox(10, 10, 100, float("inf")))
        with self.assertRaises(RecognitionInputError):
            RecognitionInputValidator().validate(
                _request(target),
                _page_facts(_element()),
                block_semantic_identification_spec(),
            )

    def test_bbox_outside_image_size_is_rejected(self) -> None:
        target = _target(bbox=BBox(10, 10, 1200, 100))
        with self.assertRaises(RecognitionInputError):
            RecognitionInputValidator().validate(
                _request(target),
                _page_facts(_element()),
                block_semantic_identification_spec(),
            )

    def test_normalized_bbox_outside_unit_range_is_rejected(self) -> None:
        target = _target(normalized_bbox=BBox(-0.1, 0.01, 0.1, 0.1))
        with self.assertRaises(RecognitionInputError):
            RecognitionInputValidator().validate(
                _request(target),
                _page_facts(_element()),
                block_semantic_identification_spec(),
            )

    def test_normalized_bbox_inconsistent_with_pixel_bbox_is_rejected(self) -> None:
        target = _target(normalized_bbox=BBox(0.5, 0.5, 0.6, 0.6))
        with self.assertRaises(RecognitionInputError):
            RecognitionInputValidator().validate(
                _request(target),
                _page_facts(_element()),
                block_semantic_identification_spec(),
            )

    def test_bbox_inconsistent_with_source_fact_is_rejected(self) -> None:
        target = _target(bbox=BBox(20, 20, 120, 120))
        with self.assertRaises(RecognitionInputError):
            RecognitionInputValidator().validate(
                _request(target),
                _page_facts(_element()),
                block_semantic_identification_spec(),
            )

    def test_missing_image_size_is_rejected_for_element_task(self) -> None:
        facts = PageSourceFacts(
            page_id="page-1",
            image_path=r"C:\drawings\page-1.png",
            elements=(_element(),),
            image_hash="hash-1",
        )
        with self.assertRaises(RecognitionInputError):
            RecognitionInputValidator().validate(
                _request(_target()),
                facts,
                block_semantic_identification_spec(),
            )

    def test_page_target_with_bbox_is_rejected(self) -> None:
        target = _target(
            target_type="DrawingPage",
            task_type="page_summary",
            target_element_id=None,
            bbox=BBox(0, 0, 100, 100),
            normalized_bbox=BBox(0, 0, 0.1, 0.1),
        )
        with self.assertRaises(RecognitionInputError):
            RecognitionInputValidator().validate(
                _request(target),
                _page_facts(),
                page_summary_spec(),
            )

    def test_context_id_must_exist_on_same_page(self) -> None:
        target = _target(context_element_ids=("missing-caption",))
        with self.assertRaises(RecognitionInputError):
            RecognitionInputValidator().validate(
                _request(target),
                _page_facts(_element()),
                block_semantic_identification_spec(),
            )

    def test_context_type_must_be_in_task_whitelist(self) -> None:
        target = _target(context_element_ids=("caption-1",))
        facts = _page_facts(_element(), _element("caption-1", "TableCaption"))
        with self.assertRaises(RecognitionInputError):
            RecognitionInputValidator().validate(
                _request(target),
                facts,
                block_semantic_identification_spec(),
            )

    def test_context_is_rejected_when_task_has_no_context_whitelist(self) -> None:
        target = _target(context_element_ids=("block-2",))
        facts = _page_facts(_element(), _element("block-2", "DrawingBlock"))
        with self.assertRaises(RecognitionInputError):
            RecognitionInputValidator().validate(
                _request(target),
                facts,
                block_semantic_identification_spec(),
            )

    def test_valid_whitelisted_context_passes(self) -> None:
        target = _target(
            target_type="Table",
            task_type="table_interpretation",
            target_element_id="table-1",
            bbox=BBox(10, 10, 200, 100),
            normalized_bbox=BBox(0.01, 0.0125, 0.2, 0.125),
            context_element_ids=("caption-1",),
        )
        facts = _page_facts(
            _element(
                "table-1",
                "Table",
                bbox=BBox(10, 10, 200, 100),
                normalized_bbox=BBox(0.01, 0.0125, 0.2, 0.125),
            ),
            _element("caption-1", "TableCaption"),
        )
        validated = RecognitionInputValidator().validate(
            _request(target, task_type="table_interpretation"),
            facts,
            table_interpretation_spec(),
        )
        self.assertEqual(("caption-1",), validated.targets[0].context_element_ids)

    def test_element_task_without_image_size_is_rejected_for_section_label(self) -> None:
        target = _target(
            target_type="CrossSection",
            task_type="section_label_observation",
            target_element_id="section-1",
        )
        facts = PageSourceFacts(
            page_id="page-1",
            image_path=r"C:\drawings\page-1.png",
            elements=(_element("section-1", "CrossSection"),),
            image_hash="hash-1",
        )
        with self.assertRaises(RecognitionInputError):
            RecognitionInputValidator().validate(
                _request(target),
                facts,
                section_label_observation_spec(),
            )


class RecognitionSecurityValidationTests(unittest.TestCase):
    """Input safety, version binding and execution-policy tightening checks."""

    def _validate(
        self,
        target: SemanticTargetInput,
        *,
        task_type: str | None = None,
        server_policy: RecognitionExecutionPolicy | None = None,
        prompt_version: str = "prompt-v1",
    ) -> ValidatedRecognitionRequest:
        request = _request(target, task_type=task_type)
        return RecognitionInputValidator().validate(
            request,
            _page_facts(_element()),
            block_semantic_identification_spec(),
            server_policy=server_policy,
        )

    def test_secret_keyword_in_request_field_is_rejected(self) -> None:
        request = _request(_target())
        request = RecognitionExecutionRequest(
            request_id="api_key_leak",
            recognition_run_id=request.recognition_run_id,
            page_id=request.page_id,
            task_type=request.task_type,
            targets=request.targets,
            model_profile=request.model_profile,
            prompt_version=request.prompt_version,
        )
        with self.assertRaises(RecognitionInputError):
            RecognitionInputValidator().validate(
                request,
                _page_facts(_element()),
                block_semantic_identification_spec(),
            )

    def test_authorization_in_model_profile_is_rejected(self) -> None:
        target = _target()
        request = _request(target)
        request = RecognitionExecutionRequest(
            request_id=request.request_id,
            recognition_run_id=request.recognition_run_id,
            page_id=request.page_id,
            task_type=request.task_type,
            targets=request.targets,
            model_profile="Authorization: Bearer xyz",
            prompt_version=request.prompt_version,
        )
        with self.assertRaises(RecognitionInputError):
            RecognitionInputValidator().validate(
                request,
                _page_facts(_element()),
                block_semantic_identification_spec(),
            )

    def test_token_in_target_id_is_rejected(self) -> None:
        target = _target(target_id="token-abc")
        with self.assertRaises(RecognitionInputError):
            self._validate(target)

    def test_absolute_path_in_page_id_is_rejected(self) -> None:
        target = _target(page_id=r"C:\Users\me\drawings\page-1")
        with self.assertRaises(RecognitionInputError):
            self._validate(target)

    def test_secret_in_context_element_id_is_rejected(self) -> None:
        target = _target(context_element_ids=("secret-context",))
        with self.assertRaises(RecognitionInputError):
            self._validate(target)

    def test_unknown_context_fields_are_rejected_at_dto_boundary(self) -> None:
        with self.assertRaises(TypeError):
            SemanticTargetInput(
                target_id="target-1",
                page_id="page-1",
                target_type="DrawingBlock",
                task_type="block_semantic_identification",
                target_element_id="block-1",
                context={"api_key": "secret"},
            )

    def test_prompt_version_must_match_spec(self) -> None:
        target = _target()
        request = _request(target)
        request = RecognitionExecutionRequest(
            request_id=request.request_id,
            recognition_run_id=request.recognition_run_id,
            page_id=request.page_id,
            task_type=request.task_type,
            targets=request.targets,
            model_profile=request.model_profile,
            prompt_version="prompt-v2",
        )
        with self.assertRaises(RecognitionInputError):
            RecognitionInputValidator().validate(
                request,
                _page_facts(_element()),
                block_semantic_identification_spec(),
            )

    def test_input_contract_version_must_match_spec(self) -> None:
        target = _target()
        request = _request(target)
        request = RecognitionExecutionRequest(
            request_id=request.request_id,
            recognition_run_id=request.recognition_run_id,
            page_id=request.page_id,
            task_type=request.task_type,
            targets=request.targets,
            model_profile=request.model_profile,
            prompt_version=request.prompt_version,
            input_contract_version="2",
        )
        with self.assertRaises(RecognitionInputError):
            RecognitionInputValidator().validate(
                request,
                _page_facts(_element()),
                block_semantic_identification_spec(),
            )

    def test_output_contract_version_must_match_spec(self) -> None:
        target = _target()
        request = _request(target)
        request = RecognitionExecutionRequest(
            request_id=request.request_id,
            recognition_run_id=request.recognition_run_id,
            page_id=request.page_id,
            task_type=request.task_type,
            targets=request.targets,
            model_profile=request.model_profile,
            prompt_version=request.prompt_version,
            output_contract_version="3",
        )
        with self.assertRaises(RecognitionInputError):
            RecognitionInputValidator().validate(
                request,
                _page_facts(_element()),
                block_semantic_identification_spec(),
            )

    def test_preprocessing_version_must_match_spec(self) -> None:
        target = _target()
        request = _request(target)
        request = RecognitionExecutionRequest(
            request_id=request.request_id,
            recognition_run_id=request.recognition_run_id,
            page_id=request.page_id,
            task_type=request.task_type,
            targets=request.targets,
            model_profile=request.model_profile,
            prompt_version=request.prompt_version,
            preprocessing_version="preprocess-v2",
        )
        with self.assertRaises(RecognitionInputError):
            RecognitionInputValidator().validate(
                request,
                _page_facts(_element()),
                block_semantic_identification_spec(),
            )

    def test_caller_deadline_cannot_relax_server_policy(self) -> None:
        target = _target()
        request = _request(target)
        request = RecognitionExecutionRequest(
            request_id=request.request_id,
            recognition_run_id=request.recognition_run_id,
            page_id=request.page_id,
            task_type=request.task_type,
            targets=request.targets,
            model_profile=request.model_profile,
            prompt_version=request.prompt_version,
            deadline_seconds=120.0,
        )
        with self.assertRaises(RecognitionInputError):
            RecognitionInputValidator().validate(
                request,
                _page_facts(_element()),
                block_semantic_identification_spec(),
                server_policy=RecognitionExecutionPolicy(deadline_seconds=60.0),
            )

    def test_caller_attempts_cannot_relax_server_policy(self) -> None:
        target = _target()
        request = _request(target)
        request = RecognitionExecutionRequest(
            request_id=request.request_id,
            recognition_run_id=request.recognition_run_id,
            page_id=request.page_id,
            task_type=request.task_type,
            targets=request.targets,
            model_profile=request.model_profile,
            prompt_version=request.prompt_version,
            execution_policy=RecognitionExecutionPolicy(max_attempts=5),
        )
        with self.assertRaises(RecognitionInputError):
            RecognitionInputValidator().validate(
                request,
                _page_facts(_element()),
                block_semantic_identification_spec(),
                server_policy=RecognitionExecutionPolicy(max_attempts=3),
            )

    def test_caller_repair_cannot_relax_server_policy(self) -> None:
        target = _target()
        request = _request(target)
        request = RecognitionExecutionRequest(
            request_id=request.request_id,
            recognition_run_id=request.recognition_run_id,
            page_id=request.page_id,
            task_type=request.task_type,
            targets=request.targets,
            model_profile=request.model_profile,
            prompt_version=request.prompt_version,
            execution_policy=RecognitionExecutionPolicy(max_attempts=3, structure_repair_attempts=2),
        )
        with self.assertRaises(RecognitionInputError):
            RecognitionInputValidator().validate(
                request,
                _page_facts(_element()),
                block_semantic_identification_spec(),
                server_policy=RecognitionExecutionPolicy(max_attempts=3, structure_repair_attempts=1),
            )

    def test_caller_budget_cannot_relax_server_policy(self) -> None:
        target = _target()
        request = _request(target)
        request = RecognitionExecutionRequest(
            request_id=request.request_id,
            recognition_run_id=request.recognition_run_id,
            page_id=request.page_id,
            task_type=request.task_type,
            targets=request.targets,
            model_profile=request.model_profile,
            prompt_version=request.prompt_version,
            execution_policy=RecognitionExecutionPolicy(estimated_cost_budget=2.0),
        )
        with self.assertRaises(RecognitionInputError):
            RecognitionInputValidator().validate(
                request,
                _page_facts(_element()),
                block_semantic_identification_spec(),
                server_policy=RecognitionExecutionPolicy(estimated_cost_budget=1.0),
            )

    def test_tightening_limits_are_accepted(self) -> None:
        target = _target()
        request = _request(target)
        request = RecognitionExecutionRequest(
            request_id=request.request_id,
            recognition_run_id=request.recognition_run_id,
            page_id=request.page_id,
            task_type=request.task_type,
            targets=request.targets,
            model_profile=request.model_profile,
            prompt_version=request.prompt_version,
            deadline_seconds=30.0,
            execution_policy=RecognitionExecutionPolicy(
                max_attempts=2,
                structure_repair_attempts=1,
                estimated_cost_budget=0.5,
            ),
        )
        validated = RecognitionInputValidator().validate(
            request,
            _page_facts(_element()),
            block_semantic_identification_spec(),
            server_policy=RecognitionExecutionPolicy(
                max_attempts=3,
                structure_repair_attempts=1,
                deadline_seconds=60.0,
                estimated_cost_budget=1.0,
            ),
        )
        self.assertEqual(30.0, validated.deadline_seconds)
        self.assertEqual(2, validated.execution_policy.max_attempts)

    def test_write_back_defaults_to_false_in_validation(self) -> None:
        validated = self._validate(_target())
        self.assertIs(False, validated.write_back)


if __name__ == "__main__":
    unittest.main()
