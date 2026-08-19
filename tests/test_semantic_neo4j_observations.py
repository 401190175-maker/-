import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.semantic_models import TextObservation
from drawing_graph.semantic_neo4j_repository import SemanticNeo4jRepository
from drawing_graph.tool_models import BBox, ToolModelError


class FakeTransaction:
    def __init__(self, read_results=()):
        self.calls = []
        self.read_results = list(read_results)

    def run(self, cypher, **parameters):
        self.calls.append((cypher, parameters))
        if self.read_results:
            return self.read_results.pop(0)
        return []


class FakeSession:
    def __init__(self, read_results=()):
        self.transaction = FakeTransaction(read_results)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute_write(self, callback):
        return callback(self.transaction)

    def execute_read(self, callback):
        return callback(self.transaction)


class FakeDriver:
    def __init__(self, read_results=()):
        self.sessions = []
        self.read_results = list(read_results)

    def session(self):
        session = FakeSession(self.read_results)
        self.sessions.append(session)
        return session


class FakeRecord:
    def __init__(self, values):
        self.values = values

    def __getitem__(self, key):
        return self.values[key]


def observation(observation_id="obs:1", element_type="DrawingBlock", element_id="block:1"):
    return TextObservation(
        observation_id=observation_id,
        recognition_run_id="run:1",
        target_element_id=element_id,
        target_element_type=element_type,
        page_id="page:1",
        raw_text="A1",
        normalized_text="A1",
        bbox=BBox(1, 2, 3, 4),
        normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
        confidence=0.9,
        status="confirmed",
        image_hash="image-hash",
        cache_key="cache-key",
        model_profile="vision-v1",
        prompt_version="prompt-v1",
        created_at="2026-08-06T00:00:00Z",
    )


class SemanticNeo4jObservationsTest(unittest.TestCase):
    def test_writes_observation_node_and_has_observation_edge_with_parameters(self):
        driver = FakeDriver()
        repository = SemanticNeo4jRepository(driver)

        repository.save_observations((observation(),))

        cypher, parameters = driver.sessions[0].transaction.calls[0]
        self.assertIn("UNWIND $observations AS observation", cypher)
        self.assertIn("MATCH (source:DrawingBlock {id: observation.target_element_id})", cypher)
        self.assertIn("MERGE (text_observation:TextObservation {id: observation.id})", cypher)
        self.assertIn("SET text_observation += observation", cypher)
        self.assertIn("MERGE (source)-[r:HAS_OBSERVATION]->(text_observation)", cypher)
        self.assertNotIn("obs:1", cypher)
        self.assertNotIn("run:1", cypher)
        self.assertNotIn("A1", cypher)
        self.assertNotIn("RecognitionRun", cypher)
        self.assertNotIn("id(start)", cypher)
        self.assertNotIn("elementId", cypher)
        payload = parameters["observations"][0]
        self.assertEqual("obs:1", payload["id"])
        self.assertEqual("run:1", payload["recognition_run_id"])
        self.assertEqual("block:1", payload["target_element_id"])
        self.assertEqual("confirmed", payload["status"])
        self.assertEqual("vision-v1", payload["model_profile"])
        self.assertEqual([1, 2, 3, 4], payload["bbox"])

    def test_groups_observations_by_controlled_source_label(self):
        driver = FakeDriver()
        repository = SemanticNeo4jRepository(driver)

        repository.save_observations(
            (
                observation("obs:1", "DrawingBlock", "block:1"),
                observation("obs:2", "BlockCaption", "caption:1"),
            )
        )

        calls = driver.sessions[0].transaction.calls
        self.assertEqual(2, len(calls))
        self.assertIn("MATCH (source:DrawingBlock", calls[0][0])
        self.assertIn("MATCH (source:BlockCaption", calls[1][0])
        self.assertEqual("caption:1", calls[1][1]["observations"][0]["target_element_id"])

    def test_rejects_unknown_source_label_before_query_runs(self):
        driver = FakeDriver()
        repository = SemanticNeo4jRepository(driver)

        with self.assertRaises(ToolModelError) as error:
            repository.save_observations((observation("obs:1", "UnknownLabel", "unknown:1"),))

        self.assertEqual("invalid_target_element_type", error.exception.category)
        self.assertEqual([], driver.sessions)

    def test_empty_input_does_not_open_session_and_invalid_input_is_rejected(self):
        driver = FakeDriver()
        repository = SemanticNeo4jRepository(driver)

        repository.save_observations(())
        self.assertEqual([], driver.sessions)

        with self.assertRaises(ToolModelError):
            repository.save_observations((observation(), "not-an-observation"))
        self.assertEqual([], driver.sessions)

    def test_queries_observations_by_page_element_and_run_as_dtos(self):
        rows = [
            FakeRecord(
                {
                    "id": "obs:1",
                    "recognition_run_id": "run:1",
                    "target_element_id": "block:1",
                    "target_element_type": "DrawingBlock",
                    "page_id": "page:1",
                    "raw_text": "A1",
                    "normalized_text": "A1",
                    "bbox": [1, 2, 3, 4],
                    "normalized_bbox": [0.1, 0.2, 0.3, 0.4],
                    "confidence": 0.9,
                    "status": "confirmed",
                    "image_hash": "image-hash",
                    "cache_key": "cache-key",
                    "model_profile": "vision-v1",
                    "prompt_version": "prompt-v1",
                    "created_at": "2026-08-06T00:00:00Z",
                }
            )
        ]
        driver = FakeDriver(read_results=(rows,))
        repository = SemanticNeo4jRepository(driver)

        observations = repository.find_by_page("page:1")

        cypher, parameters = driver.sessions[0].transaction.calls[0]
        self.assertIn("MATCH (text_observation:TextObservation)", cypher)
        self.assertIn("text_observation.page_id = $page_id", cypher)
        self.assertEqual("page:1", parameters["page_id"])
        self.assertEqual("obs:1", observations[0].observation_id)
        self.assertEqual(BBox(1, 2, 3, 4), observations[0].bbox)
        self.assertEqual("confirmed", observations[0].status.value)


class SemanticObservationLineageWriteTests(unittest.TestCase):
    def test_marks_observation_stale_with_parameterized_cypher(self):
        driver = FakeDriver()
        repository = SemanticNeo4jRepository(driver)

        repository.mark_evidence_stale(
            ("obs:1",),
            superseded_by_evidence_id="obs:2",
            stale_reason="newer-evidence",
            stale_at="2026-08-13T00:00:00Z",
            evidence_family_key="family:1",
        )

        cypher, parameters = driver.sessions[0].transaction.calls[0]
        self.assertIn("any(label IN labels(n) WHERE label IN $allowed_labels)", cypher)
        self.assertIn("TextObservation", parameters["allowed_labels"])
        self.assertNotIn("obs:1", cypher)
        self.assertNotIn("family:1", cypher)
        self.assertNotIn("newer-evidence", cypher)
        self.assertEqual(["obs:1"], parameters["evidence_ids"])
        self.assertEqual("obs:2", parameters["superseded_by_evidence_id"])
        self.assertEqual("family:1", parameters["evidence_family_key"])

    def test_rejects_invalid_inputs(self):
        driver = FakeDriver()
        repository = SemanticNeo4jRepository(driver)
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

    def test_empty_ids_do_not_open_session(self):
        driver = FakeDriver()
        repository = SemanticNeo4jRepository(driver)
        repository.mark_evidence_stale(
            (),
            superseded_by_evidence_id="obs:2",
            stale_reason="r",
            stale_at="t",
            evidence_family_key="family:1",
        )
        self.assertEqual([], driver.sessions)


if __name__ == "__main__":
    unittest.main()
