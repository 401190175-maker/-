import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.semantic_models import BlockInterpretation, RecognitionRunSummary, TextObservation
from drawing_graph.semantic_query_projection import SemanticQueryProjection
from drawing_graph.tool_models import (
    BBox,
    BlockRelations,
    ElementEvidence,
    PageSourceFacts,
    SectionMatchSummary,
    SemanticCandidateRelationSummary,
)


def observation(observation_id="obs:1", status="confirmed"):
    return TextObservation(
        observation_id=observation_id,
        recognition_run_id="run:1",
        target_element_id="block:1",
        target_element_type="DrawingBlock",
        page_id="page:1",
        raw_text="A1",
        normalized_text="A1",
        bbox=BBox(1, 2, 3, 4),
        normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
        confidence=0.9,
        status=status,
        model_profile="vision-v1",
        prompt_version="prompt-v1",
        created_at="2026-08-06T00:00:00Z",
    )


def interpretation():
    return BlockInterpretation(
        interpretation_id="interpretation:1",
        recognition_run_id="run:1",
        block_id="block:1",
        page_id="page:1",
        summary="wall block",
        interpreted_type="structural_wall",
        analysis_status="interpreted",
        supported_by_observation_ids=("obs:1",),
    )


def run_summary():
    return RecognitionRunSummary(
        recognition_run_id="run:1",
        run_type="recognition",
        page_id="page:1",
        model_profile="vision-v1",
        prompt_version="prompt-v1",
        status="succeeded",
        write_back=True,
    )


def page_facts():
    return PageSourceFacts(
        page_id="page:1",
        image_path="road_24.png",
        elements=(
            ElementEvidence(
                element_id="block:1",
                element_type="DrawingBlock",
                source_label="block",
                bbox=BBox(1, 2, 3, 4),
                normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
            ),
        ),
    )


class SemanticQueryProjectionTest(unittest.TestCase):
    def test_project_observations_and_interpretations_with_fact_kinds(self):
        projection = SemanticQueryProjection()

        observations = projection.project_observations((observation(),))
        interpretations = projection.project_interpretations((interpretation(),))

        self.assertEqual("semantic_observation", observations[0].fact_kind)
        self.assertEqual("obs:1", observations[0].observation_id)
        self.assertEqual("semantic_interpretation", interpretations[0].fact_kind)
        self.assertEqual("structural_wall", interpretations[0].interpreted_type)
        self.assertEqual("DrawingBlock", interpretations[0].element_type)

    def test_project_page_without_evidence_returns_not_recognized_and_not_interpreted(self):
        projection = SemanticQueryProjection().project_page(page_id="page:1")

        self.assertEqual("not_recognized", projection.observation_status)
        self.assertEqual("not_interpreted", projection.interpretation_status)
        self.assertEqual((), projection.observations)
        self.assertEqual((), projection.interpretations)

    def test_project_page_distinguishes_source_derived_and_semantic_fact_kinds(self):
        relations = BlockRelations(
            block_id="block:1",
            caption_ids=("caption:1",),
            candidate_section_mark_ids=("cross-section:1",),
        )
        candidate = SemanticCandidateRelationSummary(
            candidate_group_id="group:1",
            cross_section_id="cross-section:1",
            block_caption_id="caption:1",
            page_id="page:1",
            status="candidate",
        )
        formal = SectionMatchSummary(
            cross_section_id="cross-section:1",
            match_status="confirmed",
            matched_caption_ids=("caption:1",),
            candidate_count=1,
            fact_kind="formal_relation",
            status="confirmed",
        )

        projection = SemanticQueryProjection().project_page(
            page_facts=page_facts(),
            block_relations=relations,
            observations=(observation(),),
            interpretations=(interpretation(),),
            run_summary=run_summary(),
            candidate_relations=(candidate,),
            formal_relations=(formal,),
        )

        self.assertEqual("recognized", projection.observation_status)
        self.assertEqual("interpreted", projection.interpretation_status)
        self.assertEqual("source_fact", projection.source_facts[0].fact_kind)
        self.assertEqual("derived_relation", projection.derived_relations[0].fact_kind)
        self.assertEqual("semantic_observation", projection.observations[0].fact_kind)
        self.assertEqual("semantic_interpretation", projection.interpretations[0].fact_kind)
        self.assertEqual("candidate_relation", projection.candidate_relations[0].fact_kind)
        self.assertEqual("formal_relation", projection.formal_relations[0].fact_kind)
        self.assertEqual("run:1", projection.run_summary.recognition_run_id)

    def test_candidate_relation_is_never_projected_as_formal(self):
        candidate = SemanticCandidateRelationSummary(
            candidate_group_id="group:1",
            cross_section_id="cross-section:1",
            block_caption_id="caption:1",
            page_id="page:1",
            status="candidate",
        )

        projection = SemanticQueryProjection().project_page(
            page_id="page:1",
            candidate_relations=(candidate,),
        )

        self.assertEqual(1, len(projection.candidate_relations))
        self.assertEqual((), projection.formal_relations)
        self.assertEqual("candidate_relation", projection.candidate_relations[0].fact_kind)

    def test_rejects_invalid_inputs(self):
        projection = SemanticQueryProjection()

        with self.assertRaises(Exception):
            projection.project_observations((observation(), "not-an-observation"))
        with self.assertRaises(Exception):
            projection.project_interpretations((interpretation(), "not-an-interpretation"))
        with self.assertRaises(Exception):
            SemanticQueryProjection().project_page(page_id="")


if __name__ == "__main__":
    unittest.main()
