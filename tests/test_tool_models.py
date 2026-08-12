import dataclasses
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.tool_models import (
    BBox,
    DrawingSetSummary,
    ElementEvidence,
    PageSourceFacts,
    PageSummary,
    Pagination,
    SectionMatchSummary,
    SemanticCandidateRelationSummary,
    SemanticInterpretationSummary,
    SemanticObservationSummary,
    SemanticPayloadSummary,
    SemanticTargetInput,
    ToolError,
    ToolModelError,
)


class ToolModelsTest(unittest.TestCase):
    def test_constructs_immutable_business_dtos(self):
        bbox = BBox(x_min=1, y_min=2, x_max=3, y_max=4)
        element = ElementEvidence(
            element_id="block:project:set:road_24:0",
            element_type="DrawingBlock",
            bbox=bbox,
            normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
            source_label="block",
        )
        facts = PageSourceFacts(
            page_id="page:project:set:road_24",
            image_path="data/set/road_24.png",
            image_size=(1000, 2000),
            elements=(element,),
        )

        self.assertEqual("block:project:set:road_24:0", facts.elements[0].element_id)
        with self.assertRaises(AttributeError):
            facts.page_id = "other"
        with self.assertRaises(TypeError):
            facts.elements[0].metadata["labels"] = ["Neo4j"]

    def test_rejects_invalid_limit_empty_ids_bbox_and_error_code(self):
        invalid_cases = [
            lambda: Pagination(limit=0),
            lambda: DrawingSetSummary(project_id="", drawing_set_id="set:1", name="set", page_count=1),
            lambda: PageSummary(drawing_set_id="set:1", page_id="", file_stem="road_24", page_number=24),
            lambda: BBox(x_min=4, y_min=2, x_max=3, y_max=5),
            lambda: ToolError(code="secret cypher", message="bad"),
        ]

        for factory in invalid_cases:
            with self.subTest(factory=factory):
                with self.assertRaises(ToolModelError):
                    factory()

    def test_dtos_do_not_expose_neo4j_internal_objects(self):
        element = ElementEvidence(
            element_id="caption:1",
            element_type="BlockCaption",
            bbox=BBox(1, 2, 3, 4),
            normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
            source_label="block caption",
        )
        payload = repr(element)

        self.assertNotIn("driver", payload.lower())
        self.assertNotIn("session", payload.lower())
        self.assertNotIn("transaction", payload.lower())
        self.assertNotIn("cypher", payload.lower())

    def test_semantic_observation_summary_is_stable_and_marked_as_observation(self):
        summary = SemanticObservationSummary(
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
            model_profile="vision-v1",
            prompt_version="prompt-v1",
            created_at="2026-08-06T00:00:00Z",
            evidence={"image_path": "road_24.png"},
            persisted=False,
            warnings=("cached",),
        )

        self.assertEqual("semantic_observation", summary.fact_kind)
        self.assertEqual("road_24.png", summary.evidence["image_path"])
        self.assertFalse(summary.persisted)
        self.assertEqual(("cached",), summary.warnings)
        self.assertNotIn("cypher", repr(summary).lower())
        self.assertNotIn("driver", repr(summary).lower())

    def test_semantic_interpretation_summary_keeps_ai_type_separate(self):
        summary = SemanticInterpretationSummary(
            interpretation_id="interpretation:1",
            recognition_run_id="run:1",
            element_id="block:1",
            element_type="DrawingBlock",
            page_id="page:1",
            summary="wall block",
            analysis_status="interpreted",
            interpreted_type="structural_wall",
            payload_ref="payload:1",
            contract_version="1",
            supported_by_observation_ids=("obs:1",),
            persisted=True,
        )

        self.assertEqual("semantic_interpretation", summary.fact_kind)
        self.assertEqual("structural_wall", summary.interpreted_type)
        self.assertNotIn("block_type", SemanticInterpretationSummary.__dataclass_fields__)
        self.assertFalse(hasattr(summary, "session"))

    def test_semantic_payload_summary_returns_immutable_payload(self):
        summary = SemanticPayloadSummary(
            payload_ref="payload:1",
            content_hash="hash:1",
            contract_version="1",
            payload={"summary": "wall", "items": [{"name": "A"}]},
        )

        self.assertEqual("semantic_payload", summary.fact_kind)
        self.assertEqual("hash:1", summary.content_hash)
        self.assertEqual("wall", summary.payload["summary"])

    def test_section_match_summary_supports_candidate_and_formal_kinds(self):
        candidate = SectionMatchSummary(
            cross_section_id="cross-section:1",
            match_status="candidate",
            logical_key="SECTION_NUMERIC_1",
            symbol_system="numeric",
            matched_caption_ids=("caption:1", "caption:2"),
            candidate_count=2,
            conflict_reason="multiple same-key captions",
            observation_ids=("obs:1", "obs:2"),
            rule_version="match-v1",
            fact_kind="candidate_relation",
            status="candidate",
        )
        formal = SectionMatchSummary(
            cross_section_id="cross-section:1",
            match_status="confirmed",
            logical_key="SECTION_NUMERIC_1",
            symbol_system="numeric",
            matched_caption_ids=("caption:1",),
            candidate_count=1,
            fact_kind="formal_relation",
            status="confirmed",
        )

        self.assertEqual("candidate_relation", candidate.fact_kind)
        self.assertEqual(2, candidate.candidate_count)
        self.assertEqual("formal_relation", formal.fact_kind)
        self.assertNotIn("transaction", repr(candidate).lower())

    def test_semantic_candidate_relation_summary_fact_kind_is_fixed(self):
        summary = SemanticCandidateRelationSummary(
            candidate_group_id="group:1",
            cross_section_id="cross-section:1",
            block_caption_id="caption:1",
            page_id="page:1",
            status="candidate",
            candidate_count=1,
            score=0.8,
            observation_ids=("obs:1", "obs:2"),
            rule_version="match-v1",
            recognition_run_id="run:1",
            review_run_id="review:1",
            persisted=False,
        )

        self.assertEqual("candidate_relation", summary.fact_kind)
        with self.assertRaises(ToolModelError):
            SemanticCandidateRelationSummary(
                candidate_group_id="group:1",
                cross_section_id="cross-section:1",
                block_caption_id="caption:1",
                page_id="page:1",
                status="candidate",
                fact_kind="formal_relation",
            )

    def test_semantic_dtos_reject_invalid_inputs(self):
        with self.assertRaises(ToolModelError):
            SemanticObservationSummary(
                observation_id="",
                recognition_run_id="run:1",
                target_element_id="block:1",
                target_element_type="DrawingBlock",
                page_id="page:1",
                raw_text="A1",
                normalized_text="A1",
                bbox=BBox(1, 2, 3, 4),
                normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
                confidence=1.2,
                status="confirmed",
            )
        with self.assertRaises(ToolModelError):
            SemanticPayloadSummary(
                payload_ref="payload:1",
                content_hash="hash:1",
                contract_version="1",
                payload=[1, 2, 3],
            )


class SemanticTargetInputTests(unittest.TestCase):
    def test_target_input_carries_page_element_bbox_task_and_outputs(self):
        target = SemanticTargetInput(
            target_id="target:1",
            page_id="page:1",
            target_element_id="element:1",
            target_type="DrawingBlock",
            task_type="text_observation",
            required_outputs=("observation",),
            bbox=BBox(1, 2, 3, 4),
            normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
            context_element_ids=("element:2",),
            output_contract_version="1",
        )
        self.assertEqual("target:1", target.target_id)
        self.assertEqual("page:1", target.page_id)
        self.assertEqual("element:1", target.target_element_id)
        self.assertEqual("text_observation", target.task_type)
        self.assertEqual(("observation",), target.required_outputs)
        self.assertEqual(("element:2",), target.context_element_ids)
        self.assertEqual("1", target.output_contract_version)

    def test_target_input_serializes_without_product_decision_fields(self):
        target = SemanticTargetInput(
            target_id="target:2",
            page_id="page:1",
            target_type="page",
            task_type="page_summary",
            output_contract_version="1",
        )
        serialized = dataclasses.asdict(target)
        self.assertEqual("page:1", serialized["page_id"])
        self.assertNotIn("decision", serialized)
        self.assertNotIn("budget_exceeded", serialized)
        self.assertNotIn("answer_status", serialized)
        self.assertNotIn("covered_requirement_ids", serialized)

    def test_target_input_rejects_empty_ids_and_invalid_bbox(self):
        with self.assertRaises(ToolModelError):
            SemanticTargetInput(
                target_id="",
                page_id="page:1",
                target_type="page",
                task_type="t",
            )
        with self.assertRaises(ToolModelError):
            SemanticTargetInput(
                target_id="target:3",
                page_id="page:1",
                target_type="page",
                task_type="t",
                bbox=(1, 2, 3, 4),
            )
        with self.assertRaises(ToolModelError):
            SemanticTargetInput(
                target_id="target:4",
                page_id="page:1",
                target_type="page",
                task_type="t",
                required_outputs=("",),
            )


if __name__ == "__main__":
    unittest.main()
