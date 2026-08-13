import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.semantic_models import (
    BasicInfoInterpretation,
    BlockInterpretation,
    InterpretationStatus,
    ObservationStatus,
    RecognitionRunSummary,
    TableInterpretation,
    TextObservation,
)
from drawing_graph.tool_models import BBox, ToolModelError


class SemanticModelsTest(unittest.TestCase):
    def test_text_observation_contains_source_element_and_run_reference(self):
        observation = TextObservation(
            observation_id="obs:1",
            recognition_run_id="run:1",
            target_element_id="block:1",
            target_element_type="DrawingBlock",
            page_id="page:1",
            raw_text="  A1  ",
            normalized_text="A1",
            bbox=BBox(1, 2, 3, 4),
            normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
            confidence=0.8,
            status="confirmed",
            image_hash="hash",
            cache_key="cache",
        )

        self.assertEqual("run:1", observation.recognition_run_id)
        self.assertEqual("block:1", observation.target_element_id)

    def test_text_observation_contains_model_prompt_and_creation_trace(self):
        observation = TextObservation(
            observation_id="obs:1",
            recognition_run_id="run:1",
            target_element_id="block:1",
            target_element_type="DrawingBlock",
            page_id="page:1",
            raw_text="A1",
            normalized_text="A1",
            bbox=BBox(1, 2, 3, 4),
            normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
            confidence=0.8,
            status="confirmed",
            image_hash="image-hash",
            cache_key="cache-key",
            model_profile="vision-v1",
            prompt_version="prompt-v1",
            created_at="2026-08-06T00:00:00Z",
        )

        self.assertEqual("vision-v1", observation.model_profile)
        self.assertEqual("prompt-v1", observation.prompt_version)
        self.assertEqual("2026-08-06T00:00:00Z", observation.created_at)
        self.assertEqual("matched_candidate", ObservationStatus.MATCHED_CANDIDATE.value)
        self.assertIn("not a formal graph fact", TextObservation.__doc__)

    def test_rejects_invalid_status_missing_element_confidence_and_bbox(self):
        base = {
            "observation_id": "obs:1",
            "recognition_run_id": "run:1",
            "target_element_id": "block:1",
            "target_element_type": "DrawingBlock",
            "page_id": "page:1",
            "raw_text": "A1",
            "normalized_text": "A1",
            "bbox": BBox(1, 2, 3, 4),
            "normalized_bbox": BBox(0.1, 0.2, 0.3, 0.4),
            "confidence": 0.8,
            "status": "confirmed",
        }
        invalid_cases = [
            {"status": "fact"},
            {"target_element_id": ""},
            {"confidence": 1.2},
            {"normalized_bbox": BBox(1, 2, 3, 4)},
        ]

        for overrides in invalid_cases:
            with self.subTest(overrides=overrides):
                values = {**base, **overrides}
                with self.assertRaises(ToolModelError):
                    TextObservation(**values)

    def test_recognition_run_summary_is_not_a_graph_node_model(self):
        run = RecognitionRunSummary(
            recognition_run_id="run:1",
            run_type="recognition",
            page_id="page:1",
            model_profile="default",
            prompt_version="p1",
            status="succeeded",
            write_back=False,
        )

        self.assertFalse(hasattr(run, "labels"))
        self.assertFalse(hasattr(run, "cypher"))
        self.assertEqual("run:1", run.recognition_run_id)

    def test_block_interpretation_keeps_ai_type_out_of_source_facts(self):
        interpretation = BlockInterpretation(
            interpretation_id="interpretation:1",
            recognition_run_id="run:1",
            block_id="block:1",
            summary="A structural wall block",
            interpreted_type="structural_wall",
            components=("wall", "opening"),
            materials=("concrete",),
            dimensions=("240x3000",),
            construction_features=("cast_in_place",),
            spatial_relations=("above foundation",),
            analysis_status="interpreted",
            uncertainties=("opening size uncertain",),
            payload_ref="payload:1",
            cache_key="cache:1",
            contract_version="2",
        )

        self.assertEqual("structural_wall", interpretation.interpreted_type)
        self.assertEqual(("wall", "opening"), interpretation.components)
        self.assertEqual("2", interpretation.contract_version)
        self.assertIn("interpreted_type", BlockInterpretation.__dataclass_fields__)
        self.assertNotIn("block_type", BlockInterpretation.__dataclass_fields__)
        self.assertIn("never be", BlockInterpretation.__doc__)

    def test_basic_info_interpretation_contains_field_level_uncertainties_and_versions(self):
        interpretation = BasicInfoInterpretation(
            interpretation_id="interpretation:2",
            recognition_run_id="run:1",
            basic_info_id="basic-info:1",
            raw_text="项目名称：某道路工程",
            summary="Drawing basic info",
            project_name="某道路工程",
            drawing_name="道路平面图",
            discipline="road",
            drawing_number="RD-01",
            scale="1:500",
            date="2026-08-06",
            analysis_status="partial",
            uncertainties=("scale possibly 1:1000",),
            payload_ref="payload:2",
            cache_key="cache:2",
            contract_version="1",
        )

        self.assertEqual("某道路工程", interpretation.project_name)
        self.assertEqual("RD-01", interpretation.drawing_number)
        self.assertEqual(InterpretationStatus.PARTIAL, interpretation.analysis_status)
        self.assertEqual(("scale possibly 1:1000",), interpretation.uncertainties)
        self.assertEqual("payload:2", interpretation.payload_ref)
        self.assertEqual("1", interpretation.contract_version)

    def test_table_interpretation_contains_caption_ref_payload_and_status(self):
        interpretation = TableInterpretation(
            interpretation_id="interpretation:3",
            recognition_run_id="run:1",
            table_id="table:1",
            caption_ref="table-caption:1",
            summary="Material schedule table",
            analysis_status="interpreted",
            uncertainties=(),
            payload_ref="payload:3",
            cache_key="cache:3",
            contract_version="1",
        )

        self.assertEqual("table-caption:1", interpretation.caption_ref)
        self.assertEqual("Material schedule table", interpretation.summary)
        self.assertEqual("payload:3", interpretation.payload_ref)
        self.assertEqual(InterpretationStatus.INTERPRETED, interpretation.analysis_status)

    def test_interpretations_reject_invalid_status_and_required_fields(self):
        with self.assertRaises(ToolModelError):
            BlockInterpretation(
                interpretation_id="interpretation:1",
                recognition_run_id="run:1",
                block_id="block:1",
                summary="summary",
                analysis_status="unknown_status",
            )
        with self.assertRaises(ToolModelError):
            BasicInfoInterpretation(
                interpretation_id="interpretation:2",
                recognition_run_id="run:1",
                basic_info_id="basic-info:1",
                raw_text="",
                summary="summary",
            )
        with self.assertRaises(ToolModelError):
            TableInterpretation(
                interpretation_id="interpretation:3",
                recognition_run_id="run:1",
                table_id="table:1",
                summary="",
            )


class SemanticProjectionProvenanceTests(unittest.TestCase):
    """Semantic DTOs carry execution provenance with backward-compatible defaults."""

    def test_text_observation_provenance_defaults(self):
        observation = TextObservation(
            observation_id="obs:1",
            recognition_run_id="run:1",
            target_element_id="block:1",
            target_element_type="DrawingBlock",
            page_id="page:1",
            raw_text="A1",
            normalized_text="A1",
            bbox=BBox(1, 2, 3, 4),
            normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
            confidence=0.9,
            status="confirmed",
        )

        self.assertEqual("1", observation.input_contract_version)
        self.assertEqual("1", observation.output_contract_version)
        self.assertEqual("preprocess-v1", observation.preprocessing_version)

    def test_text_observation_accepts_custom_provenance(self):
        observation = TextObservation(
            observation_id="obs:1",
            recognition_run_id="run:1",
            target_element_id="block:1",
            target_element_type="DrawingBlock",
            page_id="page:1",
            raw_text="A1",
            normalized_text="A1",
            bbox=BBox(1, 2, 3, 4),
            normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
            confidence=0.9,
            status="confirmed",
            input_contract_version="2",
            output_contract_version="3",
            preprocessing_version="preprocess-v2",
        )

        self.assertEqual("2", observation.input_contract_version)
        self.assertEqual("3", observation.output_contract_version)
        self.assertEqual("preprocess-v2", observation.preprocessing_version)

    def test_text_observation_rejects_empty_provenance_versions(self):
        with self.assertRaises(ToolModelError):
            TextObservation(
                observation_id="obs:1",
                recognition_run_id="run:1",
                target_element_id="block:1",
                target_element_type="DrawingBlock",
                page_id="page:1",
                raw_text="A1",
                normalized_text="A1",
                bbox=BBox(1, 2, 3, 4),
                normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
                confidence=0.9,
                status="confirmed",
                preprocessing_version="",
            )

    def test_interpretation_dtos_carry_execution_provenance_defaults(self):
        block = BlockInterpretation(
            interpretation_id="interpretation:1",
            recognition_run_id="run:1",
            block_id="block:1",
            summary="beam",
        )
        basic = BasicInfoInterpretation(
            interpretation_id="interpretation:2",
            recognition_run_id="run:1",
            basic_info_id="basic:1",
            raw_text="DWG-1",
            summary="info",
        )
        table = TableInterpretation(
            interpretation_id="interpretation:3",
            recognition_run_id="run:1",
            table_id="table:1",
            summary="table",
        )

        for interpretation in (block, basic, table):
            with self.subTest(kind=type(interpretation).__name__):
                self.assertEqual("default", interpretation.model_profile)
                self.assertEqual("default", interpretation.prompt_version)
                self.assertEqual("1", interpretation.input_contract_version)
                self.assertEqual("preprocess-v1", interpretation.preprocessing_version)


if __name__ == "__main__":
    unittest.main()
