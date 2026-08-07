import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.section_alias_rules import SectionAliasRuleStore, SectionLabelAliasRule
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


def cross_section_observation(raw_text="1-1", element_id="cross-section:1"):
    return observation("obs:cross", element_id, "CrossSection", raw_text)


def caption_observation(caption_id="caption:1", raw_text="1-1", observation_id="obs:caption:1"):
    return observation(observation_id, caption_id, "BlockCaption", raw_text)


def alias_rule():
    return SectionLabelAliasRule(
        alias_rule_id="alias:1",
        alias_rule_version="v1",
        scope="page:1",
        from_symbol_system="numeric",
        to_symbol_system="alphabetic",
        mapping={"SECTION_NUMERIC_1": "SECTION_ALPHA_A"},
        status="confirmed",
        evidence_ref="evidence:1",
    )


class SectionMatchServiceFormalTest(unittest.TestCase):
    def test_unique_same_key_caption_returns_formal_match(self):
        service = SectionMatchService()

        decision = service.evaluate_formal_match(
            cross_section_observation=cross_section_observation(),
            caption_observations=(caption_observation(),),
            page_id="page:1",
            rule_version="match-v1",
        )

        self.assertEqual("formal", decision.status)
        self.assertEqual("formal_relation", decision.fact_kind)
        self.assertEqual("caption:1", decision.matched_caption_id)
        self.assertEqual("SECTION_NUMERIC_1", decision.logical_key)
        self.assertEqual(("obs:cross", "obs:caption:1"), decision.observation_ids)
        self.assertEqual(1, decision.candidate_count)
        self.assertIsNone(decision.alias_rule_id)

    def test_missing_cross_section_observation_is_not_formal(self):
        service = SectionMatchService()

        decision = service.evaluate_formal_match(
            cross_section_observation=None,
            caption_observations=(caption_observation(),),
            page_id="page:1",
            rule_version="match-v1",
        )

        self.assertEqual("match_not_found", decision.status)
        self.assertNotEqual("formal_relation", decision.fact_kind)

    def test_unknown_label_is_ambiguous_not_formal(self):
        service = SectionMatchService()

        decision = service.evaluate_formal_match(
            cross_section_observation=cross_section_observation(raw_text="??"),
            caption_observations=(caption_observation(raw_text="1-1"),),
            page_id="page:1",
            rule_version="match-v1",
        )

        self.assertEqual("ambiguous", decision.status)
        self.assertNotEqual("formal", decision.status)

    def test_cross_symbol_system_requires_confirmed_alias_rule(self):
        service_with_rule = SectionMatchService(alias_rule_store=SectionAliasRuleStore((alias_rule(),)))
        service_without_rule = SectionMatchService()

        with_rule = service_with_rule.evaluate_formal_match(
            cross_section_observation=cross_section_observation(raw_text="1-1"),
            caption_observations=(caption_observation(raw_text="A-A"),),
            page_id="page:1",
            rule_version="match-v1",
        )
        without_rule = service_without_rule.evaluate_formal_match(
            cross_section_observation=cross_section_observation(raw_text="1-1"),
            caption_observations=(caption_observation(raw_text="A-A"),),
            page_id="page:1",
            rule_version="match-v1",
        )

        self.assertEqual("formal", with_rule.status)
        self.assertEqual("alias:1", with_rule.alias_rule_id)
        self.assertEqual("candidate", without_rule.status)
        self.assertNotEqual("formal", without_rule.status)

    def test_multiple_same_key_captions_are_ambiguous_not_formal(self):
        service = SectionMatchService()

        decision = service.evaluate_formal_match(
            cross_section_observation=cross_section_observation(),
            caption_observations=(
                caption_observation("caption:1"),
                caption_observation("caption:2", observation_id="obs:caption:2"),
            ),
            page_id="page:1",
            rule_version="match-v1",
        )

        self.assertEqual("ambiguous", decision.status)
        self.assertEqual(2, decision.candidate_count)
        self.assertEqual("multiple same-key captions", decision.conflict_reason)

    def test_conflicting_block_caption_relation_is_ambiguous_not_formal(self):
        service = SectionMatchService()

        decision = service.evaluate_formal_match(
            cross_section_observation=cross_section_observation(),
            caption_observations=(caption_observation(),),
            page_id="page:1",
            rule_version="match-v1",
            conflicting_caption_ids=("caption:1",),
        )

        self.assertEqual("ambiguous", decision.status)
        self.assertIn("conflicting block relation", decision.conflict_reason)


if __name__ == "__main__":
    unittest.main()
