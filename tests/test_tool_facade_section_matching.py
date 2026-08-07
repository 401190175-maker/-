import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.query_ports import FakeDrawingGraphReadPort
from drawing_graph.section_match_service import SectionMatchService
from drawing_graph.semantic_models import TextObservation
from drawing_graph.tool_facade import DrawingGraphToolFacade
from drawing_graph.tool_models import BBox, SectionMatchSummary, ToolModelError


def observation(
    observation_id,
    element_id,
    element_type,
    raw_text,
    page_id="page:1",
):
    return TextObservation(
        observation_id=observation_id,
        recognition_run_id="run:1",
        target_element_id=element_id,
        target_element_type=element_type,
        page_id=page_id,
        raw_text=raw_text,
        normalized_text=raw_text,
        bbox=BBox(1, 2, 3, 4),
        normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
        confidence=0.9,
        status="confirmed",
    )


def cross_observation(element_id="cross-section:1", raw_text="1-1"):
    return observation("obs:cross", element_id, "CrossSection", raw_text)


def caption_observation(caption_id="caption:1", raw_text="1-1", observation_id="obs:caption:1"):
    return observation(observation_id, caption_id, "BlockCaption", raw_text)


class FakeSemanticRepository:
    def __init__(self, observations):
        self._observations = tuple(observations)

    def find_by_element(self, element_id):
        return tuple(item for item in self._observations if item.target_element_id == element_id)

    def find_by_page(self, page_id):
        return tuple(item for item in self._observations if item.page_id == page_id)


class SpySectionWritePort:
    def __init__(self):
        self.calls = []

    def write_section_relation(self, **kwargs):
        self.calls.append(kwargs)


class FakeSectionMatchQueryPort:
    def __init__(self, matches):
        self._matches = tuple(matches)

    def list_section_matches(self, **kwargs):
        return self._matches


def facade_with(observations, write_port=None, query_port=None):
    return DrawingGraphToolFacade(
        read_port=FakeDrawingGraphReadPort(),
        semantic_repository=FakeSemanticRepository(observations),
        section_match_service=SectionMatchService(),
        section_match_write_port=write_port,
        section_match_query_port=query_port,
    )


class ToolFacadeSectionMatchingTest(unittest.TestCase):
    def test_dry_run_returns_formal_judgment_without_writing(self):
        write_port = SpySectionWritePort()
        facade = facade_with(
            (cross_observation(), caption_observation()),
            write_port=write_port,
        )

        summary = facade.match_section_caption("cross-section:1", write_back=False)

        self.assertEqual("formal", summary.match_status)
        self.assertEqual("formal_relation", summary.fact_kind)
        self.assertEqual("confirmed", summary.status)
        self.assertEqual(("caption:1",), summary.matched_caption_ids)
        self.assertFalse(summary.persisted)
        self.assertEqual([], write_port.calls)

    def test_write_back_formal_writes_matches_section_caption(self):
        write_port = SpySectionWritePort()
        facade = facade_with(
            (cross_observation(), caption_observation()),
            write_port=write_port,
        )

        summary = facade.match_section_caption("cross-section:1", write_back=True)

        self.assertTrue(summary.persisted)
        self.assertEqual(1, len(write_port.calls))
        call = write_port.calls[0]
        self.assertEqual("MATCHES_SECTION_CAPTION", call["relation_type"])
        self.assertEqual("cross-section:1", call["start_id"])
        self.assertEqual("caption:1", call["end_id"])
        self.assertEqual("deterministic_rule", call["properties"]["confirmation_method"])
        self.assertEqual(["obs:cross", "obs:caption:1"], call["properties"]["observation_ids"])

    def test_write_back_ambiguous_writes_one_candidate_per_caption(self):
        write_port = SpySectionWritePort()
        facade = facade_with(
            (
                cross_observation(),
                caption_observation("caption:1"),
                caption_observation("caption:2", observation_id="obs:caption:2"),
            ),
            write_port=write_port,
        )

        summary = facade.match_section_caption("cross-section:1", write_back=True)

        self.assertEqual("ambiguous", summary.match_status)
        self.assertEqual("candidate_relation", summary.fact_kind)
        self.assertTrue(summary.persisted)
        self.assertEqual(2, len(write_port.calls))
        self.assertTrue(all(call["relation_type"] == "CANDIDATE_MATCHES_SECTION_CAPTION" for call in write_port.calls))
        self.assertEqual(
            {"caption:1", "caption:2"},
            {call["end_id"] for call in write_port.calls},
        )
        self.assertEqual("multiple same-key captions", write_port.calls[0]["properties"]["conflict_reason"])

    def test_write_back_without_match_writes_nothing(self):
        write_port = SpySectionWritePort()
        facade = facade_with(
            (cross_observation(),),
            write_port=write_port,
        )

        summary = facade.match_section_caption("cross-section:1", write_back=True)

        self.assertEqual("candidate", summary.match_status)
        self.assertFalse(summary.persisted)
        self.assertEqual([], write_port.calls)

    def test_page_id_is_derived_from_observation_when_omitted(self):
        write_port = SpySectionWritePort()
        facade = facade_with(
            (cross_observation(), caption_observation()),
            write_port=write_port,
        )

        summary = facade.match_section_caption("cross-section:1", write_back=True)

        self.assertEqual("formal", summary.match_status)
        self.assertEqual("page:1", summary.evidence["page_id"])
        self.assertEqual(1, len(write_port.calls))

    def test_missing_cross_section_observation_returns_not_found(self):
        facade = facade_with(())

        with self.assertRaises(ToolModelError) as error:
            facade.match_section_caption("cross-section:missing")

        self.assertEqual("NOT_FOUND", error.exception.category)

    def test_lists_section_match_projections_read_only(self):
        projected = SectionMatchSummary(
            cross_section_id="cross-section:1",
            match_status="formal",
            matched_caption_ids=("caption:1",),
            candidate_count=1,
            fact_kind="formal_relation",
            status="confirmed",
        )
        facade = DrawingGraphToolFacade(
            read_port=FakeDrawingGraphReadPort(),
            section_match_query_port=FakeSectionMatchQueryPort((projected,)),
        )

        matches = facade.list_section_matches(cross_section_id="cross-section:1")

        self.assertEqual(1, len(matches))
        self.assertEqual("formal_relation", matches[0].fact_kind)
        with self.assertRaises(ToolModelError) as error:
            facade.list_section_matches(cross_section_id="cross-section:1", write_back=True)
        self.assertEqual("WRITE_BACK_FORBIDDEN", error.exception.category)


if __name__ == "__main__":
    unittest.main()
