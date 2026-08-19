import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.semantic_models import (
    BasicInfoInterpretation,
    BlockInterpretation,
    ObservationStatus,
    TableInterpretation,
    TextObservation,
)
from drawing_graph.semantic_repository import InMemorySemanticEvidenceRepository
from drawing_graph.tool_models import BBox, ToolModelError


def observation(observation_id="obs:1", page_id="page:1", element_id="block:1", run_id="run:1"):
    return TextObservation(
        observation_id=observation_id,
        recognition_run_id=run_id,
        target_element_id=element_id,
        target_element_type="DrawingBlock",
        page_id=page_id,
        raw_text="A1",
        normalized_text="A1",
        bbox=BBox(1, 2, 3, 4),
        normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
        confidence=0.9,
        status="confirmed",
    )


def block_interpretation(
    interpretation_id="interpretation:1",
    page_id="page:1",
    run_id="run:1",
    block_id="block:1",
):
    return BlockInterpretation(
        interpretation_id=interpretation_id,
        recognition_run_id=run_id,
        block_id=block_id,
        page_id=page_id,
        summary="wall block",
        interpreted_type="structural_wall",
        analysis_status="interpreted",
    )


def basic_info_interpretation(interpretation_id="interpretation:2", page_id="page:1", run_id="run:1"):
    return BasicInfoInterpretation(
        interpretation_id=interpretation_id,
        recognition_run_id=run_id,
        basic_info_id="basic-info:1",
        page_id=page_id,
        raw_text="项目名称：某道路工程",
        summary="basic info",
        analysis_status="partial",
    )


def table_interpretation(interpretation_id="interpretation:3", page_id="page:1", run_id="run:1"):
    return TableInterpretation(
        interpretation_id=interpretation_id,
        recognition_run_id=run_id,
        table_id="table:1",
        page_id=page_id,
        summary="material schedule",
        analysis_status="interpreted",
    )


class SemanticRepositoryTest(unittest.TestCase):
    def test_saves_and_queries_observations_by_page_element_and_run(self):
        repository = InMemorySemanticEvidenceRepository()
        first = observation()
        second = observation("obs:2", "page:1", "caption:1", "run:2")

        repository.save_observations((first, second))

        self.assertEqual(("obs:1", "obs:2"), tuple(item.observation_id for item in repository.find_by_page("page:1")))
        self.assertEqual(("obs:1",), tuple(item.observation_id for item in repository.find_by_element("block:1")))
        self.assertEqual(("obs:2",), tuple(item.observation_id for item in repository.find_by_run("run:2")))
        self.assertEqual("run:1", repository.find_by_page("page:1")[0].recognition_run_id)
        self.assertFalse(hasattr(repository.find_by_run("run:1")[0], "labels"))

    def test_write_failure_is_classified_as_semantic_evidence_unavailable(self):
        repository = InMemorySemanticEvidenceRepository(fail_writes=True)

        with self.assertRaises(ToolModelError) as error:
            repository.save_observations((observation(),))

        self.assertEqual("SEMANTIC_EVIDENCE_UNAVAILABLE", error.exception.category)

    def test_saves_and_queries_interpretations_by_page_element_run_and_status(self):
        repository = InMemorySemanticEvidenceRepository()
        interpretations = (
            block_interpretation(),
            basic_info_interpretation(),
            table_interpretation(),
            block_interpretation("interpretation:4", page_id="page:2", run_id="run:2", block_id="block:2"),
        )

        repository.save_interpretations(interpretations)

        self.assertEqual(
            ("interpretation:1", "interpretation:2", "interpretation:3"),
            tuple(item.interpretation_id for item in repository.find_interpretations(page_id="page:1")),
        )
        self.assertEqual(
            ("interpretation:1",),
            tuple(item.interpretation_id for item in repository.find_interpretations(element_id="block:1")),
        )
        self.assertEqual(
            ("interpretation:2",),
            tuple(item.interpretation_id for item in repository.find_interpretations(recognition_run_id="run:1", statuses=("partial",))),
        )
        self.assertEqual(
            ("interpretation:4",),
            tuple(item.interpretation_id for item in repository.find_interpretations(page_id="page:2", recognition_run_id="run:2")),
        )
        self.assertEqual("run:1", repository.find_interpretations(element_id="table:1")[0].recognition_run_id)

    def test_interpretation_write_failure_is_classified_and_never_creates_graph_node(self):
        repository = InMemorySemanticEvidenceRepository(fail_writes=True)

        with self.assertRaises(ToolModelError) as error:
            repository.save_interpretations((block_interpretation(),))

        self.assertEqual("SEMANTIC_EVIDENCE_UNAVAILABLE", error.exception.category)
        with self.assertRaises(ToolModelError):
            repository.save_interpretations((block_interpretation(), "not-an-interpretation"))

    def test_interpretation_dtos_are_not_graph_node_models(self):
        repository = InMemorySemanticEvidenceRepository()
        repository.save_interpretations((block_interpretation(),))

        interpretation = repository.find_interpretations(element_id="block:1")[0]

        self.assertFalse(hasattr(interpretation, "labels"))
        self.assertFalse(hasattr(interpretation, "cypher"))
        self.assertEqual("run:1", interpretation.recognition_run_id)


class SemanticLineagePortTests(unittest.TestCase):
    def test_marks_observation_stale(self):
        repository = InMemorySemanticEvidenceRepository()
        repository.save_observations((observation(),))

        updated = repository.mark_evidence_stale(
            ("obs:1",),
            superseded_by_evidence_id="obs:2",
            stale_reason="superseded",
            stale_at="2026-08-13T00:00:00Z",
            evidence_family_key="family:1",
        )

        self.assertEqual(("obs:1",), updated)
        stored = repository.find_by_run("run:1")[0]
        self.assertEqual(ObservationStatus.STALE, stored.status)
        self.assertEqual("obs:2", stored.superseded_by_evidence_id)
        self.assertEqual("family:1", stored.evidence_family_key)

    def test_marks_interpretation_stale(self):
        repository = InMemorySemanticEvidenceRepository()
        repository.save_interpretations((block_interpretation(),))

        updated = repository.mark_evidence_stale(
            ("interpretation:1",),
            superseded_by_evidence_id="interpretation:2",
            stale_reason="superseded",
            stale_at="2026-08-13T00:00:00Z",
            evidence_family_key="family:1",
        )

        self.assertEqual(("interpretation:1",), updated)
        stored = repository.find_interpretations(element_id="block:1")[0]
        self.assertEqual("stale", stored.analysis_status.value)

    def test_rejects_invalid_inputs(self):
        repository = InMemorySemanticEvidenceRepository()
        repository.save_observations((observation(),))
        with self.assertRaises(ToolModelError):
            repository.mark_evidence_stale(
                "obs:1",
                superseded_by_evidence_id="obs:2",
                stale_reason="r",
                stale_at="t",
                evidence_family_key="family:1",
            )
        with self.assertRaises(ToolModelError):
            repository.mark_evidence_stale(
                ("obs:1",),
                superseded_by_evidence_id="obs:2",
                stale_reason="",
                stale_at="t",
                evidence_family_key="family:1",
            )

    def test_unknown_evidence_ids_are_skipped(self):
        repository = InMemorySemanticEvidenceRepository()
        updated = repository.mark_evidence_stale(
            ("obs:missing",),
            superseded_by_evidence_id="obs:2",
            stale_reason="r",
            stale_at="t",
            evidence_family_key="family:1",
        )
        self.assertEqual((), updated)


if __name__ == "__main__":
    unittest.main()
