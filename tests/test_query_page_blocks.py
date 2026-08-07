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


class QueryPageBlocksTest(unittest.TestCase):
    def test_get_page_blocks_returns_block_geometry_without_non_design_fields(self):
        from drawing_graph.query_service import QueryService

        driver = FakeDriver(
            records=(
                {
                    "id": "block:road-project:set-a:road_1:abc",
                    "label": "block",
                    "confidence": 0.91,
                    "bbox": {"x_min": 10, "y_min": 20, "x_max": 100, "y_max": 120, "width": 90},
                    "normalized_bbox": {"x_min": 0.1, "y_min": 0.2, "x_max": 0.5, "y_max": 0.6},
                    "caption_text": "not available in task 23",
                    "reason": "not available in task 23",
                    "node_id": 9,
                },
            )
        )
        service = QueryService(driver)

        result = service.get_page_blocks("page:road-project:set-a:road_1", limit=25)

        self.assertEqual(
            [
                {
                    "id": "block:road-project:set-a:road_1:abc",
                    "label": "block",
                    "confidence": 0.91,
                    "bbox": {"x_min": 10, "y_min": 20, "x_max": 100, "y_max": 120},
                    "normalized_bbox": {"x_min": 0.1, "y_min": 0.2, "x_max": 0.5, "y_max": 0.6},
                }
            ],
            result,
        )
        self.assertNotIn("caption_text", result[0])
        self.assertNotIn("reason", result[0])
        self.assertNotIn("node_id", result[0])

    def test_get_page_blocks_returns_empty_list_when_page_has_no_blocks(self):
        from drawing_graph.query_service import QueryService

        service = QueryService(FakeDriver(records=()))

        self.assertEqual([], service.get_page_blocks("page:missing", limit=10))

    def test_get_page_blocks_rejects_invalid_limit_before_query_runs(self):
        from drawing_graph.query_service import QueryError, QueryService

        for invalid_limit in (0, -1, True, "10"):
            driver = FakeDriver(records=())
            service = QueryService(driver)
            with self.subTest(invalid_limit=invalid_limit):
                with self.assertRaises(QueryError) as context:
                    service.get_page_blocks("page:road-project:set-a:road_1", invalid_limit)
                self.assertEqual("invalid_limit", context.exception.category)
                self.assertEqual([], driver.sessions)

    def test_get_page_blocks_requires_page_id_before_query_runs(self):
        from drawing_graph.query_service import QueryError, QueryService

        driver = FakeDriver(records=())
        service = QueryService(driver)

        with self.assertRaises(QueryError) as context:
            service.get_page_blocks(" ", limit=10)

        self.assertEqual("missing_required_field", context.exception.category)
        self.assertEqual([], driver.sessions)

    def test_get_page_blocks_uses_limit_and_parameterized_query(self):
        from drawing_graph.query_service import QueryService

        driver = FakeDriver(records=())
        service = QueryService(driver)

        service.get_page_blocks("page:road-project:set-a:road_1", limit=5)

        cypher, parameters = driver.sessions[0].transaction.calls[0]
        self.assertIn("MATCH (page:DrawingPage {id: $page_id})-[:HAS_BLOCK]->(block:DrawingBlock)", cypher)
        self.assertIn("RETURN block.id AS id", cypher)
        self.assertIn("block.label AS label", cypher)
        self.assertIn("block.confidence AS confidence", cypher)
        self.assertIn("block.bbox AS bbox", cypher)
        self.assertIn("block.normalized_bbox AS normalized_bbox", cypher)
        self.assertIn("LIMIT $limit", cypher)
        self.assertNotIn("page:road-project:set-a:road_1", cypher)
        self.assertNotIn("caption_text", cypher)
        self.assertNotIn("reason", cypher)
        self.assertNotIn("id(block)", cypher)
        self.assertNotIn("elementId", cypher)
        self.assertEqual({"page_id": "page:road-project:set-a:road_1", "limit": 5}, parameters)

    def test_get_page_blocks_rejects_missing_bbox_fields(self):
        from drawing_graph.query_service import QueryError, QueryService

        service = QueryService(
            FakeDriver(
                records=(
                    {
                        "id": "block:1",
                        "label": "block",
                        "confidence": None,
                        "bbox": {"x_min": 1, "y_min": 2, "x_max": 3},
                        "normalized_bbox": {"x_min": 0.1, "y_min": 0.2, "x_max": 0.3, "y_max": 0.4},
                    },
                )
            )
        )

        with self.assertRaises(QueryError) as context:
            service.get_page_blocks("page:1", limit=10)

        self.assertEqual("invalid_bbox", context.exception.category)

    def test_get_page_blocks_rejects_normalized_bbox_outside_zero_to_one(self):
        from drawing_graph.query_service import QueryError, QueryService

        service = QueryService(
            FakeDriver(
                records=(
                    {
                        "id": "block:1",
                        "label": "block",
                        "confidence": None,
                        "bbox": {"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
                        "normalized_bbox": {"x_min": 0.1, "y_min": 0.2, "x_max": 1.2, "y_max": 0.4},
                    },
                )
            )
        )

        with self.assertRaises(QueryError) as context:
            service.get_page_blocks("page:1", limit=10)

        self.assertEqual("invalid_normalized_bbox", context.exception.category)


if __name__ == "__main__":
    unittest.main()
