import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.section_match_service import SectionMatchService
from drawing_graph.semantic_models import TextObservation
from drawing_graph.tool_models import BBox


def observation(
    observation_id,
    element_id,
    element_type,
    raw_text,
    confidence=0.9,
):
    return TextObservation(
        observation_id=observation_id,
        recognition_run_id="run:1",
        target_element_id=element_id,
        target_element_type=element_type,
        page_id="page:1",
        raw_text=raw_text,
        normalized_text=raw_text,
        bbox=BBox(1, 2, 3, 4),
        normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
        confidence=confidence,
        status="confirmed",
    )


def cross_section_observation(raw_text="1-1", observation_id="obs:cross", element_id="cross-section:1"):
    return observation(observation_id, element_id, "CrossSection", raw_text)


def caption_observation(caption_id="caption:1", observation_id="obs:caption:1", raw_text="1-1", confidence=0.9):
    return observation(observation_id, caption_id, "BlockCaption", raw_text, confidence)


class SectionMatchServiceCandidatesTest(unittest.TestCase):
    def setUp(self):
        self.service = SectionMatchService()

    def test_missing_cross_section_observation_returns_no_candidates(self):
        candidates = self.service.generate_candidates(
            cross_section_observation=None,
            caption_observations=(caption_observation(),),
            page_id="page:1",
            rule_version="match-v1",
        )

        self.assertEqual((), candidates)

    def test_missing_or_mismatched_caption_observations_return_no_candidates(self):
        no_captions = self.service.generate_candidates(
            cross_section_observation=cross_section_observation(),
            caption_observations=(),
            page_id="page:1",
            rule_version="match-v1",
        )
        mismatched = self.service.generate_candidates(
            cross_section_observation=cross_section_observation(),
            caption_observations=(caption_observation(raw_text="2-2"),),
            page_id="page:1",
            rule_version="match-v1",
        )

        self.assertEqual((), no_captions)
        self.assertEqual((), mismatched)

    def test_multiple_same_key_captions_produce_one_candidate_each_with_shared_group(self):
        candidates = self.service.generate_candidates(
            cross_section_observation=cross_section_observation(),
            caption_observations=(
                caption_observation("caption:1", "obs:caption:1", "1-1", 0.8),
                caption_observation("caption:2", "obs:caption:2", "1-1", 0.7),
            ),
            page_id="page:1",
            rule_version="match-v1",
        )

        self.assertEqual(2, len(candidates))
        self.assertEqual("candidate", candidates[0].status)
        self.assertEqual(candidates[0].candidate_group_id, candidates[1].candidate_group_id)
        self.assertEqual(2, candidates[0].candidate_count)
        self.assertEqual("multiple same-key captions", candidates[0].conflict_reason)
        self.assertEqual(("obs:cross", "obs:caption:1"), candidates[0].observation_ids)
        self.assertEqual("SECTION_NUMERIC_1", candidates[0].logical_key)
        self.assertEqual("numeric", candidates[0].symbol_system)
        self.assertEqual("match-v1", candidates[0].rule_version)

    def test_single_unique_caption_has_no_conflict(self):
        candidates = self.service.generate_candidates(
            cross_section_observation=cross_section_observation(),
            caption_observations=(caption_observation(confidence=0.85),),
            page_id="page:1",
            rule_version="match-v1",
        )

        self.assertEqual(1, len(candidates))
        self.assertEqual(1, candidates[0].candidate_count)
        self.assertIsNone(candidates[0].conflict_reason)
        self.assertEqual(0.85, candidates[0].score)

    def test_spatial_proximity_is_not_used_as_evidence(self):
        far_caption = caption_observation("caption:far", "obs:caption:far", "1-1")
        near_caption = caption_observation("caption:near", "obs:caption:near", "1-1")

        candidates = self.service.generate_candidates(
            cross_section_observation=cross_section_observation(),
            caption_observations=(far_caption, near_caption),
            page_id="page:1",
            rule_version="match-v1",
        )

        self.assertEqual(2, len(candidates))
        self.assertEqual({"caption:far", "caption:near"}, {item.block_caption_id for item in candidates})

    def test_cross_symbol_system_does_not_form_candidate_without_alias_rule(self):
        candidates = self.service.generate_candidates(
            cross_section_observation=cross_section_observation(raw_text="I-I"),
            caption_observations=(caption_observation(raw_text="1-1"),),
            page_id="page:1",
            rule_version="match-v1",
        )

        self.assertEqual((), candidates)


if __name__ == "__main__":
    unittest.main()
