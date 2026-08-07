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


class QuerySetPagesTest(unittest.TestCase):
    def test_get_set_pages_returns_page_fields_without_internal_ids(self):
        from drawing_graph.query_service import QueryService

        driver = FakeDriver(
            records=(
                {
                    "id": "page:road-project:lslq_yhd_2_1:road_1",
                    "file_name": "road_1.json",
                    "page_number": 1,
                    "image_path": "data/lslq_yhd_2_1/road_1.png",
                    "node_id": 99,
                },
                {
                    "id": "page:road-project:lslq_yhd_2_1:road_24",
                    "file_name": "road_24.json",
                    "page_number": 24,
                    "image_path": "data/lslq_yhd_2_1/road_24.png",
                    "node_id": 100,
                },
            )
        )
        service = QueryService(driver)

        result = service.get_set_pages("set:road-project:lslq_yhd_2_1", limit=50)

        self.assertEqual(
            [
                {
                    "id": "page:road-project:lslq_yhd_2_1:road_1",
                    "file_name": "road_1.json",
                    "page_number": 1,
                    "image_path": "data/lslq_yhd_2_1/road_1.png",
                },
                {
                    "id": "page:road-project:lslq_yhd_2_1:road_24",
                    "file_name": "road_24.json",
                    "page_number": 24,
                    "image_path": "data/lslq_yhd_2_1/road_24.png",
                },
            ],
            result,
        )
        self.assertNotIn("node_id", result[0])

    def test_get_set_pages_returns_empty_list_when_set_has_no_pages(self):
        from drawing_graph.query_service import QueryService

        service = QueryService(FakeDriver(records=()))

        self.assertEqual([], service.get_set_pages("set:missing", limit=10))

    def test_get_set_pages_rejects_invalid_limit_before_query_runs(self):
        from drawing_graph.query_service import QueryError, QueryService

        for invalid_limit in (0, -1, False, "10"):
            driver = FakeDriver(records=())
            service = QueryService(driver)
            with self.subTest(invalid_limit=invalid_limit):
                with self.assertRaises(QueryError) as context:
                    service.get_set_pages("set:road-project:lslq_yhd_2_1", invalid_limit)
                self.assertEqual("invalid_limit", context.exception.category)
                self.assertEqual([], driver.sessions)

    def test_get_set_pages_requires_drawing_set_id_before_query_runs(self):
        from drawing_graph.query_service import QueryError, QueryService

        driver = FakeDriver(records=())
        service = QueryService(driver)

        with self.assertRaises(QueryError) as context:
            service.get_set_pages("", limit=10)

        self.assertEqual("missing_required_field", context.exception.category)
        self.assertEqual([], driver.sessions)

    def test_get_set_pages_uses_page_number_order_limit_and_parameters(self):
        from drawing_graph.query_service import QueryService

        driver = FakeDriver(records=())
        service = QueryService(driver)

        service.get_set_pages("set:road-project:lslq_yhd_2_1", limit=5)

        cypher, parameters = driver.sessions[0].transaction.calls[0]
        self.assertIn("MATCH (drawing_set:DrawingSet {id: $drawing_set_id})-[:HAS_PAGE]->(page:DrawingPage)", cypher)
        self.assertIn("RETURN page.id AS id", cypher)
        self.assertIn("page.file_name AS file_name", cypher)
        self.assertIn("page.page_number AS page_number", cypher)
        self.assertIn("page.image_path AS image_path", cypher)
        self.assertIn("ORDER BY page.page_number ASC", cypher)
        self.assertIn("LIMIT $limit", cypher)
        self.assertNotIn("set:road-project:lslq_yhd_2_1", cypher)
        self.assertNotIn("id(page)", cypher)
        self.assertNotIn("elementId", cypher)
        self.assertEqual({"drawing_set_id": "set:road-project:lslq_yhd_2_1", "limit": 5}, parameters)


if __name__ == "__main__":
    unittest.main()
