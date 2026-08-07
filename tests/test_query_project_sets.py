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


class QueryProjectSetsTest(unittest.TestCase):
    def test_get_project_sets_returns_stable_business_fields(self):
        from drawing_graph.query_service import QueryService

        driver = FakeDriver(
            records=(
                {"id": "set:road-project:lslq_yhd_2_1", "name": "lslq_yhd_2_1", "page_count": 103, "node_id": 9},
                {"id": "set:road-project:lslq_yhd_2_2", "name": "lslq_yhd_2_2", "page_count": 230, "node_id": 10},
            )
        )
        service = QueryService(driver)

        result = service.get_project_sets("project:road-project", limit=25)

        self.assertEqual(
            [
                {"id": "set:road-project:lslq_yhd_2_1", "name": "lslq_yhd_2_1", "page_count": 103},
                {"id": "set:road-project:lslq_yhd_2_2", "name": "lslq_yhd_2_2", "page_count": 230},
            ],
            result,
        )
        self.assertNotIn("node_id", result[0])

    def test_get_project_sets_returns_empty_list_when_project_has_no_sets(self):
        from drawing_graph.query_service import QueryService

        service = QueryService(FakeDriver(records=()))

        self.assertEqual([], service.get_project_sets("project:missing", limit=10))

    def test_get_project_sets_rejects_invalid_limit_before_query_runs(self):
        from drawing_graph.query_service import QueryError, QueryService

        for invalid_limit in (0, -1, True, "10"):
            driver = FakeDriver(records=())
            service = QueryService(driver)
            with self.subTest(invalid_limit=invalid_limit):
                with self.assertRaises(QueryError) as context:
                    service.get_project_sets("project:road-project", invalid_limit)
                self.assertEqual("invalid_limit", context.exception.category)
                self.assertEqual([], driver.sessions)

    def test_get_project_sets_requires_project_id_before_query_runs(self):
        from drawing_graph.query_service import QueryError, QueryService

        driver = FakeDriver(records=())
        service = QueryService(driver)

        with self.assertRaises(QueryError) as context:
            service.get_project_sets(" ", limit=10)

        self.assertEqual("missing_required_field", context.exception.category)
        self.assertEqual([], driver.sessions)

    def test_get_project_sets_uses_parameterized_query_without_internal_ids(self):
        from drawing_graph.query_service import QueryService

        driver = FakeDriver(records=())
        service = QueryService(driver)

        service.get_project_sets("project:road-project", limit=5)

        cypher, parameters = driver.sessions[0].transaction.calls[0]
        self.assertIn("MATCH (project:Project {id: $project_id})-[:HAS_SET]->(drawing_set:DrawingSet)", cypher)
        self.assertIn("OPTIONAL MATCH (drawing_set)-[:HAS_PAGE]->(page:DrawingPage)", cypher)
        self.assertIn("RETURN drawing_set.id AS id", cypher)
        self.assertIn("drawing_set.name AS name", cypher)
        self.assertIn("count(DISTINCT page) AS page_count", cypher)
        self.assertIn("LIMIT $limit", cypher)
        self.assertNotIn("project:road-project", cypher)
        self.assertNotIn("drawing_set.page_count", cypher)
        self.assertNotIn("id(drawing_set)", cypher)
        self.assertNotIn("elementId", cypher)
        self.assertEqual({"project_id": "project:road-project", "limit": 5}, parameters)


if __name__ == "__main__":
    unittest.main()
