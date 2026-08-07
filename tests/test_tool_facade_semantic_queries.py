import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.query_ports import FakeDrawingGraphReadPort
from drawing_graph.semantic_payload_store import InMemorySemanticPayloadStore
from drawing_graph.recognition_run_log import InMemoryRecognitionRunLog
from drawing_graph.semantic_models import BlockInterpretation, TextObservation
from drawing_graph.semantic_repository import InMemorySemanticEvidenceRepository
from drawing_graph.tool_facade import DrawingGraphToolFacade
from drawing_graph.tool_models import BBox, ToolModelError


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
    )


def interpretation(interpretation_id="interpretation:1", status="interpreted"):
    return BlockInterpretation(
        interpretation_id=interpretation_id,
        recognition_run_id="run:1",
        block_id="block:1",
        page_id="page:1",
        summary="wall block",
        interpreted_type="structural_wall",
        analysis_status=status,
        supported_by_observation_ids=("obs:1",),
    )


class ToolFacadeSemanticQueriesTest(unittest.TestCase):
    def test_queries_run_log_and_observations_without_internal_fields(self):
        run_log = InMemoryRecognitionRunLog()
        run = run_log.create_run("page:1", "default", "p1", {"element_ids": ["block:1"]}, True)
        run_log.complete_run(run.recognition_run_id, "fake", "v1")
        repository = InMemorySemanticEvidenceRepository()
        repository.save_observations((observation(), observation("obs:2", "ambiguous")))
        facade = DrawingGraphToolFacade(FakeDrawingGraphReadPort(), run_log=run_log, semantic_repository=repository)

        run_summary = facade.get_recognition_run(run.recognition_run_id)
        by_page = facade.list_text_observations(page_id="page:1", statuses=("confirmed",))
        by_element = facade.list_text_observations(element_id="block:1")
        by_run = facade.list_text_observations(recognition_run_id="run:1")

        self.assertEqual("fake", run_summary.model_name)
        self.assertEqual("semantic_observation", by_page[0].fact_kind)
        self.assertEqual(("obs:1",), tuple(item.observation_id for item in by_page))
        self.assertEqual(2, len(by_element))
        self.assertEqual(2, len(by_run))
        self.assertNotIn("cypher", repr(by_run).lower())
        self.assertNotIn("labels", repr(run_summary).lower())

    def test_missing_run_and_missing_observations_return_not_found(self):
        facade = DrawingGraphToolFacade(
            FakeDrawingGraphReadPort(),
            run_log=InMemoryRecognitionRunLog(),
            semantic_repository=InMemorySemanticEvidenceRepository(),
        )

        with self.assertRaises(ToolModelError) as run_error:
            facade.get_recognition_run("run:missing")
        with self.assertRaises(ToolModelError) as obs_error:
            facade.list_text_observations(page_id="page:missing")

        self.assertEqual("NOT_FOUND", run_error.exception.category)
        self.assertEqual("NOT_FOUND", obs_error.exception.category)

    def test_queries_interpretations_through_projection(self):
        repository = InMemorySemanticEvidenceRepository()
        repository.save_interpretations((interpretation(), interpretation("interpretation:2", "partial")))
        facade = DrawingGraphToolFacade(
            FakeDrawingGraphReadPort(),
            semantic_repository=repository,
        )

        by_element = facade.list_interpretations(element_id="block:1")
        by_status = facade.list_interpretations(element_id="block:1", statuses=("partial",))

        self.assertEqual(2, len(by_element))
        self.assertEqual("semantic_interpretation", by_element[0].fact_kind)
        self.assertEqual("structural_wall", by_element[0].interpreted_type)
        self.assertEqual("DrawingBlock", by_element[0].element_type)
        self.assertEqual(("interpretation:2",), tuple(item.interpretation_id for item in by_status))
        self.assertNotIn("cypher", repr(by_element).lower())

    def test_missing_interpretations_return_not_found(self):
        facade = DrawingGraphToolFacade(
            FakeDrawingGraphReadPort(),
            semantic_repository=InMemorySemanticEvidenceRepository(),
        )

        with self.assertRaises(ToolModelError) as error:
            facade.list_interpretations(element_id="block:missing")

        self.assertEqual("NOT_FOUND", error.exception.category)

    def test_interpretation_query_requires_exactly_one_filter(self):
        facade = DrawingGraphToolFacade(
            FakeDrawingGraphReadPort(),
            semantic_repository=InMemorySemanticEvidenceRepository(),
        )

        with self.assertRaises(ToolModelError) as error:
            facade.list_interpretations()

        self.assertEqual("INVALID_ARGUMENT", error.exception.category)

    def test_get_semantic_payload_returns_ref_hash_version_and_payload(self):
        store = InMemorySemanticPayloadStore()
        payload_ref = store.put_payload(
            {"summary": "wall", "items": [{"name": "A"}]},
            "hash:1",
            contract_version="2",
        )
        facade = DrawingGraphToolFacade(
            FakeDrawingGraphReadPort(),
            payload_store=store,
        )

        summary = facade.get_semantic_payload(payload_ref)

        self.assertEqual("semantic_payload", summary.fact_kind)
        self.assertEqual(payload_ref, summary.payload_ref)
        self.assertEqual("hash:1", summary.content_hash)
        self.assertEqual("2", summary.contract_version)
        self.assertEqual("wall", summary.payload["summary"])

    def test_get_semantic_payload_missing_returns_not_found_and_write_back_is_rejected(self):
        store = InMemorySemanticPayloadStore()
        facade = DrawingGraphToolFacade(
            FakeDrawingGraphReadPort(),
            payload_store=store,
        )

        with self.assertRaises(ToolModelError) as not_found:
            facade.get_semantic_payload("payload:missing")
        with self.assertRaises(ToolModelError) as forbidden:
            facade.get_semantic_payload("payload:missing", write_back=True)

        self.assertEqual("NOT_FOUND", not_found.exception.category)
        self.assertEqual("WRITE_BACK_FORBIDDEN", forbidden.exception.category)

    def test_payload_query_does_not_trigger_model_or_run_log(self):
        store = InMemorySemanticPayloadStore()
        payload_ref = store.put_payload({"summary": "wall"}, "hash:1")
        run_log = InMemoryRecognitionRunLog()
        facade = DrawingGraphToolFacade(
            FakeDrawingGraphReadPort(),
            run_log=run_log,
            payload_store=store,
        )

        facade.get_semantic_payload(payload_ref)

        self.assertEqual({}, run_log._runs)


if __name__ == "__main__":
    unittest.main()
