import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class FakeTransaction:
    def __init__(self, records=()):
        self.records = list(records)
        self.calls = []

    def run(self, cypher, **parameters):
        self.calls.append((cypher, parameters))
        return list(self.records)


class FakeSession:
    def __init__(self, records=()):
        self.transaction = FakeTransaction(records)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute_read(self, callback):
        return callback(self.transaction)


class FakeDriver:
    def __init__(self, records=()):
        self.records = list(records)
        self.sessions = []

    def session(self):
        session = FakeSession(self.records)
        self.sessions.append(session)
        return session


class QueryBlockRelationsTest(unittest.TestCase):
    def test_get_block_relations_returns_enhanced_ids_without_non_design_fields(self):
        from drawing_graph.query_service import QueryService

        driver = FakeDriver(
            records=(
                {
                    "block_id": "block:road-project:set-a:road_1:abc",
                    "caption_ids": ["caption:z", "caption:a"],
                    "basic_info_ids": ["basic:2", "basic:1"],
                    "basic_info_status": "confirmed",
                    "basic_info_source": "current_page",
                    "annotation_ids": ["annotation:b", "annotation:a"],
                    "section_mark_ids": ["cross-section:z", "cross-section:a"],
                    "candidate_caption_ids": ["caption:candidate"],
                    "candidate_section_mark_ids": ["cross-section:candidate"],
                    "caption_text": "not available in this task",
                    "section_text": "not available in this task",
                    "reason": "not available in this task",
                    "node_id": 42,
                },
            )
        )
        service = QueryService(driver)

        result = service.get_block_relations("block:road-project:set-a:road_1:abc")

        self.assertEqual(
            {
                "block_id": "block:road-project:set-a:road_1:abc",
                "caption_ids": ["caption:a", "caption:z"],
                "basic_info_ids": ["basic:1", "basic:2"],
                "basic_info_status": "confirmed",
                "basic_info_source": "current_page",
                "annotation_ids": ["annotation:a", "annotation:b"],
                "section_mark_ids": ["cross-section:a", "cross-section:z"],
                "candidate_caption_ids": ["caption:candidate"],
                "candidate_section_mark_ids": ["cross-section:candidate"],
                "relation_status": "candidate",
            },
            result,
        )
        self.assertNotIn("caption_text", result)
        self.assertNotIn("section_text", result)
        self.assertNotIn("reason", result)
        self.assertNotIn("node_id", result)

    def test_get_block_relations_returns_not_enhanced_for_existing_block_without_relations(self):
        from drawing_graph.query_service import QueryService

        service = QueryService(
            FakeDriver(
                records=(
                    {
                        "block_id": "block:road-project:set-a:road_1:abc",
                        "caption_ids": [],
                        "basic_info_ids": [],
                        "basic_info_status": "not_evaluated",
                        "basic_info_source": None,
                        "annotation_ids": [],
                        "section_mark_ids": [],
                        "candidate_caption_ids": [],
                        "candidate_section_mark_ids": [],
                    },
                )
            )
        )

        result = service.get_block_relations("block:road-project:set-a:road_1:abc")

        self.assertEqual(
            {
                "block_id": "block:road-project:set-a:road_1:abc",
                "caption_ids": [],
                "basic_info_ids": [],
                "basic_info_status": "not_evaluated",
                "basic_info_source": None,
                "annotation_ids": [],
                "section_mark_ids": [],
                "candidate_caption_ids": [],
                "candidate_section_mark_ids": [],
                "relation_status": "not_enhanced",
            },
            result,
        )

    def test_get_block_relations_returns_partial_when_only_some_relation_types_exist(self):
        from drawing_graph.query_service import QueryService

        service = QueryService(
            FakeDriver(
                records=(
                    {
                        "block_id": "block:road-project:set-a:road_1:abc",
                        "caption_ids": ["caption:1"],
                        "basic_info_ids": [],
                        "basic_info_status": "not_evaluated",
                        "basic_info_source": None,
                        "annotation_ids": ["annotation:1"],
                        "section_mark_ids": [],
                        "candidate_caption_ids": [],
                        "candidate_section_mark_ids": [],
                    },
                )
            )
        )

        result = service.get_block_relations("block:road-project:set-a:road_1:abc")

        self.assertEqual("partial", result["relation_status"])
        self.assertEqual(["caption:1"], result["caption_ids"])
        self.assertEqual([], result["basic_info_ids"])
        self.assertEqual(["annotation:1"], result["annotation_ids"])
        self.assertEqual([], result["section_mark_ids"])

    def test_get_block_relations_returns_partial_when_only_section_marks_exist(self):
        from drawing_graph.query_service import QueryService

        service = QueryService(
            FakeDriver(
                records=(
                    {
                        "block_id": "block:road-project:set-a:road_1:abc",
                        "caption_ids": [],
                        "basic_info_ids": [],
                        "basic_info_status": "not_evaluated",
                        "basic_info_source": None,
                        "annotation_ids": [],
                        "section_mark_ids": ["cross-section:2", "cross-section:1"],
                        "candidate_caption_ids": [],
                        "candidate_section_mark_ids": [],
                    },
                )
            )
        )

        result = service.get_block_relations("block:road-project:set-a:road_1:abc")

        self.assertEqual("partial", result["relation_status"])
        self.assertEqual(["cross-section:1", "cross-section:2"], result["section_mark_ids"])

    def test_get_block_relations_returns_none_when_block_is_missing(self):
        from drawing_graph.query_service import QueryService

        service = QueryService(FakeDriver(records=()))

        self.assertIsNone(service.get_block_relations("block:missing"))

    def test_get_block_relations_requires_block_id_before_query_runs(self):
        from drawing_graph.query_service import QueryError, QueryService

        driver = FakeDriver(records=())
        service = QueryService(driver)

        with self.assertRaises(QueryError) as context:
            service.get_block_relations(" ")

        self.assertEqual("missing_required_field", context.exception.category)
        self.assertEqual([], driver.sessions)

    def test_get_block_relations_uses_parameterized_query_without_internal_ids(self):
        from drawing_graph.query_service import QueryService

        driver = FakeDriver(records=())
        service = QueryService(driver)

        service.get_block_relations("block:road-project:set-a:road_1:abc")

        cypher, parameters = driver.sessions[0].transaction.calls[0]
        self.assertIn("MATCH (page:DrawingPage)-[:HAS_BLOCK]->(block:DrawingBlock {id: $block_id})", cypher)
        self.assertIn("OPTIONAL MATCH (block)-[:HAS_CAPTION]->(caption:BlockCaption)", cypher)
        self.assertIn("OPTIONAL MATCH (page)-[basic_info_relation:HAS_BASIC_INFO|USES_BASIC_INFO]->(basic_info:DrawingBasicInfo)", cypher)
        self.assertIn("OPTIONAL MATCH (block)-[:HAS_ANNOTATION]->(annotation:DrawingAnnotation)", cypher)
        self.assertIn("OPTIONAL MATCH (block)-[:HAS_SECTION_MARK]->(section_mark:CrossSection)", cypher)
        self.assertIn("OPTIONAL MATCH (candidate_caption:BlockCaption)-[:CANDIDATE_CAPTION_OF]->(block)", cypher)
        self.assertIn("OPTIONAL MATCH (block)-[:CANDIDATE_HAS_SECTION_MARK]->(candidate_section_mark:CrossSection)", cypher)
        self.assertIn("RETURN block.id AS block_id", cypher)
        self.assertIn("caption_ids", cypher)
        self.assertIn("basic_info_ids", cypher)
        self.assertIn("basic_info_status", cypher)
        self.assertIn("candidate_caption_ids", cypher)
        self.assertIn("candidate_section_mark_ids", cypher)
        self.assertIn("annotation_ids", cypher)
        self.assertIn("section_mark_ids", cypher)
        self.assertNotIn("block:road-project:set-a:road_1:abc", cypher)
        self.assertNotIn("caption_text", cypher)
        self.assertNotIn("section_text", cypher)
        self.assertNotIn("reason", cypher)
        self.assertNotIn("id(block)", cypher)
        self.assertNotIn("elementId", cypher)
        self.assertEqual({"block_id": "block:road-project:set-a:road_1:abc"}, parameters)

    def test_get_block_relations_rejects_malformed_relation_id_lists(self):
        from drawing_graph.query_service import QueryError, QueryService

        service = QueryService(
            FakeDriver(
                records=(
                    {
                        "block_id": "block:1",
                        "caption_ids": ["caption:1", None],
                        "basic_info_ids": [],
                        "basic_info_status": "not_evaluated",
                        "basic_info_source": None,
                        "annotation_ids": [],
                        "section_mark_ids": [],
                        "candidate_caption_ids": [],
                        "candidate_section_mark_ids": [],
                    },
                )
            )
        )

        with self.assertRaises(QueryError) as context:
            service.get_block_relations("block:1")

        self.assertEqual("invalid_relation_ids", context.exception.category)


if __name__ == "__main__":
    unittest.main()
