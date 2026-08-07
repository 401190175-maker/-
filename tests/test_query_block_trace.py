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


class QueryBlockTraceTest(unittest.TestCase):
    def test_get_block_trace_returns_complete_trace_without_internal_ids(self):
        from drawing_graph.query_service import QueryService

        driver = FakeDriver(
            records=(
                {
                    "project_id": "project:road-project",
                    "drawing_set_id": "set:road-project:lslq_yhd_2_1",
                    "page_id": "page:road-project:lslq_yhd_2_1:road_24",
                    "page_number": 24,
                    "image_path": "data/lslq_yhd_2_1/road_24.png",
                    "bbox": {"x_min": 10, "y_min": 20, "x_max": 110, "y_max": 220, "width": 100},
                    "normalized_bbox": {"x_min": 0.1, "y_min": 0.2, "x_max": 0.55, "y_max": 0.8},
                    "citation_ref": "lslq_yhd_2_1/road_24#shape-3",
                    "node_id": 42,
                },
            )
        )
        service = QueryService(driver)

        result = service.get_block_trace("block:road-project:lslq_yhd_2_1:road_24:abc")

        self.assertEqual(
            {
                "project_id": "project:road-project",
                "drawing_set_id": "set:road-project:lslq_yhd_2_1",
                "page_id": "page:road-project:lslq_yhd_2_1:road_24",
                "page_number": 24,
                "image_path": "data/lslq_yhd_2_1/road_24.png",
                "bbox": {"x_min": 10, "y_min": 20, "x_max": 110, "y_max": 220},
                "normalized_bbox": {"x_min": 0.1, "y_min": 0.2, "x_max": 0.55, "y_max": 0.8},
                "citation_ref": "lslq_yhd_2_1/road_24#shape-3",
            },
            result,
        )
        self.assertNotIn("node_id", result)

    def test_get_block_trace_returns_none_when_block_is_missing(self):
        from drawing_graph.query_service import QueryService

        service = QueryService(FakeDriver(records=()))

        self.assertIsNone(service.get_block_trace("block:missing"))

    def test_get_block_trace_returns_none_when_trace_relation_is_broken(self):
        from drawing_graph.query_service import QueryService

        service = QueryService(FakeDriver(records=()))

        self.assertIsNone(service.get_block_trace("block:orphan"))

    def test_get_block_trace_requires_block_id_before_query_runs(self):
        from drawing_graph.query_service import QueryError, QueryService

        driver = FakeDriver(records=())
        service = QueryService(driver)

        with self.assertRaises(QueryError) as context:
            service.get_block_trace(" ")

        self.assertEqual("missing_required_field", context.exception.category)
        self.assertEqual([], driver.sessions)

    def test_get_block_trace_uses_parameterized_query_and_expected_chain(self):
        from drawing_graph.query_service import QueryService

        driver = FakeDriver(records=())
        service = QueryService(driver)

        service.get_block_trace("block:road-project:lslq_yhd_2_1:road_24:abc")

        cypher, parameters = driver.sessions[0].transaction.calls[0]
        self.assertIn("MATCH (project:Project)-[:HAS_SET]->(drawing_set:DrawingSet)", cypher)
        self.assertIn("-[:HAS_PAGE]->(page:DrawingPage)-[:HAS_BLOCK]->(block:DrawingBlock {id: $block_id})", cypher)
        self.assertIn("RETURN project.id AS project_id", cypher)
        self.assertIn("drawing_set.id AS drawing_set_id", cypher)
        self.assertIn("page.id AS page_id", cypher)
        self.assertIn("page.page_number AS page_number", cypher)
        self.assertIn("page.image_path AS image_path", cypher)
        self.assertIn("block.bbox AS bbox", cypher)
        self.assertIn("block.normalized_bbox AS normalized_bbox", cypher)
        self.assertIn("block.citation_ref AS citation_ref", cypher)
        self.assertIn("LIMIT 1", cypher)
        self.assertNotIn("block:road-project:lslq_yhd_2_1:road_24:abc", cypher)
        self.assertNotIn("id(block)", cypher)
        self.assertNotIn("elementId", cypher)
        self.assertEqual({"block_id": "block:road-project:lslq_yhd_2_1:road_24:abc"}, parameters)

    def test_get_block_trace_rejects_missing_bbox_fields(self):
        from drawing_graph.query_service import QueryError, QueryService

        service = QueryService(
            FakeDriver(
                records=(
                    {
                        "project_id": "project:road-project",
                        "drawing_set_id": "set:road-project:lslq_yhd_2_1",
                        "page_id": "page:road-project:lslq_yhd_2_1:road_24",
                        "page_number": 24,
                        "image_path": "data/lslq_yhd_2_1/road_24.png",
                        "bbox": {"x_min": 10, "y_min": 20, "x_max": 110},
                        "normalized_bbox": {"x_min": 0.1, "y_min": 0.2, "x_max": 0.55, "y_max": 0.8},
                        "citation_ref": "lslq_yhd_2_1/road_24#shape-3",
                    },
                )
            )
        )

        with self.assertRaises(QueryError) as context:
            service.get_block_trace("block:1")

        self.assertEqual("invalid_bbox", context.exception.category)

    def test_get_block_trace_rejects_normalized_bbox_outside_zero_to_one(self):
        from drawing_graph.query_service import QueryError, QueryService

        service = QueryService(
            FakeDriver(
                records=(
                    {
                        "project_id": "project:road-project",
                        "drawing_set_id": "set:road-project:lslq_yhd_2_1",
                        "page_id": "page:road-project:lslq_yhd_2_1:road_24",
                        "page_number": 24,
                        "image_path": "data/lslq_yhd_2_1/road_24.png",
                        "bbox": {"x_min": 10, "y_min": 20, "x_max": 110, "y_max": 220},
                        "normalized_bbox": {"x_min": 0.1, "y_min": 0.2, "x_max": 1.2, "y_max": 0.8},
                        "citation_ref": "lslq_yhd_2_1/road_24#shape-3",
                    },
                )
            )
        )

        with self.assertRaises(QueryError) as context:
            service.get_block_trace("block:1")

        self.assertEqual("invalid_normalized_bbox", context.exception.category)


if __name__ == "__main__":
    unittest.main()
