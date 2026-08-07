import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.semantic_models import (
    BasicInfoInterpretation,
    BlockInterpretation,
    TableInterpretation,
)
from drawing_graph.semantic_neo4j_repository import SemanticNeo4jRepository
from drawing_graph.tool_models import ToolModelError


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


def block_interpretation(interpretation_id="interpretation:1"):
    return BlockInterpretation(
        interpretation_id=interpretation_id,
        recognition_run_id="run:1",
        block_id="block:1",
        page_id="page:1",
        summary="wall block",
        interpreted_type="structural_wall",
        components=("wall",),
        analysis_status="interpreted",
        uncertainties=(),
        supported_by_observation_ids=("obs:1", "obs:2"),
        payload_ref="payload:1",
        cache_key="cache:1",
        contract_version="1",
    )


def basic_info_interpretation():
    return BasicInfoInterpretation(
        interpretation_id="interpretation:2",
        recognition_run_id="run:1",
        basic_info_id="basic-info:1",
        page_id="page:1",
        raw_text="项目名称：某道路工程",
        summary="basic info",
        project_name="某道路工程",
        analysis_status="partial",
        supported_by_observation_ids=("obs:3",),
        payload_ref="payload:2",
        contract_version="1",
    )


def table_interpretation():
    return TableInterpretation(
        interpretation_id="interpretation:3",
        recognition_run_id="run:1",
        table_id="table:1",
        page_id="page:1",
        summary="material schedule",
        caption_ref="table-caption:1",
        analysis_status="interpreted",
        supported_by_observation_ids=(),
        payload_ref="payload:3",
        contract_version="1",
    )


class SemanticNeo4jInterpretationsTest(unittest.TestCase):
    def test_writes_block_interpretation_with_edges_and_supported_by(self):
        driver = FakeDriver()
        repository = SemanticNeo4jRepository(driver)

        repository.save_interpretations((block_interpretation(),))

        cypher, parameters = driver.sessions[0].transaction.calls[0]
        self.assertIn("MATCH (source:DrawingBlock {id: interpretation.source_element_id})", cypher)
        self.assertIn("MERGE (node:BlockInterpretation {id: interpretation.id})", cypher)
        self.assertIn("MERGE (source)-[r:HAS_INTERPRETATION]->(node)", cypher)
        self.assertIn("MERGE (text_observation:TextObservation {id: observation_id})", cypher)
        self.assertIn("MERGE (node)-[s:SUPPORTED_BY]->(text_observation)", cypher)
        self.assertIn("SET old.analysis_status = 'stale'", cypher)
        self.assertNotIn("block:1", cypher)
        self.assertNotIn("obs:1", cypher)
        self.assertNotIn("RecognitionRun", cypher)
        payload = parameters["interpretations"][0]
        self.assertEqual("interpretation:1", payload["id"])
        self.assertEqual("block:1", payload["source_element_id"])
        self.assertEqual("structural_wall", payload["interpreted_type"])
        self.assertEqual(["obs:1", "obs:2"], payload["supported_by_observation_ids"])
        self.assertEqual("cache:1", payload["stale_cache_key"])

    def test_groups_interpretations_by_controlled_source_labels(self):
        driver = FakeDriver()
        repository = SemanticNeo4jRepository(driver)

        repository.save_interpretations(
            (
                block_interpretation(),
                basic_info_interpretation(),
                table_interpretation(),
            )
        )

        calls = driver.sessions[0].transaction.calls
        self.assertEqual(3, len(calls))
        self.assertIn("MATCH (source:DrawingBlock", calls[0][0])
        self.assertIn("MERGE (node:BlockInterpretation", calls[0][0])
        self.assertIn("MATCH (source:DrawingBasicInfo", calls[1][0])
        self.assertIn("MERGE (node:BasicInfoInterpretation", calls[1][0])
        self.assertIn("MATCH (source:Table", calls[2][0])
        self.assertIn("MERGE (node:TableInterpretation", calls[2][0])
        self.assertEqual("某道路工程", calls[1][1]["interpretations"][0]["project_name"])
        self.assertEqual("table-caption:1", calls[2][1]["interpretations"][0]["caption_ref"])

    def test_stale_marker_is_only_emitted_when_cache_key_exists(self):
        driver = FakeDriver()
        repository = SemanticNeo4jRepository(driver)

        repository.save_interpretations((basic_info_interpretation(),))

        payload = driver.sessions[0].transaction.calls[0][1]["interpretations"][0]
        self.assertNotIn("stale_cache_key", payload)

    def test_rejects_unknown_interpretation_type_before_query_runs(self):
        driver = FakeDriver()
        repository = SemanticNeo4jRepository(driver)

        with self.assertRaises(ToolModelError):
            repository.save_interpretations((block_interpretation(), "not-an-interpretation"))

        self.assertEqual([], driver.sessions)

    def test_empty_input_does_not_open_session(self):
        driver = FakeDriver()
        repository = SemanticNeo4jRepository(driver)

        repository.save_interpretations(())

        self.assertEqual([], driver.sessions)

    def test_queries_interpretations_by_element_and_status_as_dtos(self):
        rows = [
            FakeRecord(
                {
                    "labels": ["BlockInterpretation"],
                    "id": "interpretation:1",
                    "recognition_run_id": "run:1",
                    "source_element_id": "block:1",
                    "page_id": "page:1",
                    "summary": "wall block",
                    "analysis_status": "partial",
                    "uncertainties": ["needs review"],
                    "supported_by_observation_ids": ["obs:1", "obs:2"],
                    "payload_ref": "payload:1",
                    "cache_key": "cache:1",
                    "contract_version": "1",
                    "interpreted_type": "structural_wall",
                    "components": ["wall"],
                    "materials": ["concrete"],
                    "dimensions": ["200"],
                    "construction_features": ["cast-in-place"],
                    "spatial_relations": ["below beam"],
                    "raw_text": None,
                    "project_name": None,
                    "drawing_name": None,
                    "discipline": None,
                    "drawing_number": None,
                    "scale": None,
                    "date": None,
                    "caption_ref": None,
                }
            )
        ]
        driver = FakeDriver(read_results=(rows,))
        repository = SemanticNeo4jRepository(driver)

        interpretations = repository.find_interpretations(element_id="block:1", statuses=("partial",))

        cypher, parameters = driver.sessions[0].transaction.calls[0]
        self.assertIn("MATCH (source)-[:HAS_INTERPRETATION]->(interpretation)", cypher)
        self.assertIn("source.id = $element_id", cypher)
        self.assertIn("interpretation.analysis_status IN $statuses", cypher)
        self.assertEqual("block:1", parameters["element_id"])
        self.assertEqual(("partial",), parameters["statuses"])
        self.assertEqual("interpretation:1", interpretations[0].interpretation_id)
        self.assertEqual("structural_wall", interpretations[0].interpreted_type)
        self.assertEqual(("obs:1", "obs:2"), interpretations[0].supported_by_observation_ids)


if __name__ == "__main__":
    unittest.main()
