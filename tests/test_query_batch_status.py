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


class QueryBatchStatusTest(unittest.TestCase):
    def test_get_batch_status_returns_running_batch(self):
        from drawing_graph.query_service import QueryService

        driver = FakeDriver(
            records=(
                {
                    "id": "batch:running",
                    "status": "running",
                    "started_at": "2026-07-24T10:00:00Z",
                    "finished_at": None,
                    "total_files": 0,
                    "success_count": 0,
                    "skipped_count": 0,
                    "failed_count": 0,
                    "warning_count": 0,
                    "error_summary": [],
                    "node_id": 99,
                },
            )
        )
        service = QueryService(driver)

        result = service.get_batch_status("batch:running")

        self.assertEqual(
            {
                "id": "batch:running",
                "status": "running",
                "started_at": "2026-07-24T10:00:00Z",
                "finished_at": None,
                "total_files": 0,
                "success_count": 0,
                "skipped_count": 0,
                "failed_count": 0,
                "warning_count": 0,
                "error_summary": [],
            },
            result,
        )
        self.assertNotIn("node_id", result)

    def test_get_batch_status_returns_success_batch_statistics(self):
        from drawing_graph.query_service import QueryService

        service = QueryService(
            FakeDriver(
                records=(
                    {
                        "id": "batch:success",
                        "status": "success",
                        "started_at": "2026-07-24T10:00:00Z",
                        "finished_at": "2026-07-24T10:05:00Z",
                        "total_files": 3,
                        "success_count": 2,
                        "skipped_count": 1,
                        "failed_count": 0,
                        "warning_count": 4,
                        "error_summary": [],
                    },
                )
            )
        )

        result = service.get_batch_status("batch:success")

        self.assertEqual("success", result["status"])
        self.assertEqual(3, result["total_files"])
        self.assertEqual(2, result["success_count"])
        self.assertEqual(1, result["skipped_count"])
        self.assertEqual(0, result["failed_count"])
        self.assertEqual(4, result["warning_count"])

    def test_get_batch_status_returns_failed_batch_error_summary(self):
        from drawing_graph.query_service import QueryService

        service = QueryService(
            FakeDriver(
                records=(
                    {
                        "id": "batch:failed",
                        "status": "failed",
                        "started_at": "2026-07-24T10:00:00Z",
                        "finished_at": "2026-07-24T10:06:00Z",
                        "total_files": 2,
                        "success_count": 1,
                        "skipped_count": 0,
                        "failed_count": 1,
                        "warning_count": 0,
                        "error_summary": ["database_unavailable"],
                    },
                )
            )
        )

        result = service.get_batch_status("batch:failed")

        self.assertEqual("failed", result["status"])
        self.assertEqual(["database_unavailable"], result["error_summary"])

    def test_get_batch_status_returns_none_when_batch_is_missing(self):
        from drawing_graph.query_service import QueryService

        service = QueryService(FakeDriver(records=()))

        self.assertIsNone(service.get_batch_status("batch:missing"))

    def test_get_batch_status_requires_batch_id_before_query_runs(self):
        from drawing_graph.query_service import QueryError, QueryService

        driver = FakeDriver(records=())
        service = QueryService(driver)

        with self.assertRaises(QueryError) as context:
            service.get_batch_status(" ")

        self.assertEqual("missing_required_field", context.exception.category)
        self.assertEqual([], driver.sessions)

    def test_get_batch_status_uses_parameterized_query_without_internal_ids(self):
        from drawing_graph.query_service import QueryService

        driver = FakeDriver(records=())
        service = QueryService(driver)

        service.get_batch_status("batch:success")

        cypher, parameters = driver.sessions[0].transaction.calls[0]
        self.assertIn("MATCH (batch:ImportBatch {id: $import_batch_id})", cypher)
        self.assertIn("RETURN batch.id AS id", cypher)
        self.assertIn("batch.status AS status", cypher)
        self.assertIn("batch.started_at AS started_at", cypher)
        self.assertIn("batch.finished_at AS finished_at", cypher)
        self.assertIn("batch.total_files AS total_files", cypher)
        self.assertIn("batch.success_count AS success_count", cypher)
        self.assertIn("batch.skipped_count AS skipped_count", cypher)
        self.assertIn("batch.failed_count AS failed_count", cypher)
        self.assertIn("batch.warning_count AS warning_count", cypher)
        self.assertIn("batch.error_summary AS error_summary", cypher)
        self.assertIn("LIMIT 1", cypher)
        self.assertNotIn("batch:success", cypher)
        self.assertNotIn("id(batch)", cypher)
        self.assertNotIn("elementId", cypher)
        self.assertEqual({"import_batch_id": "batch:success"}, parameters)

    def test_get_batch_status_rejects_invalid_count_values(self):
        from drawing_graph.query_service import QueryError, QueryService

        service = QueryService(
            FakeDriver(
                records=(
                    {
                        "id": "batch:bad",
                        "status": "failed",
                        "started_at": "2026-07-24T10:00:00Z",
                        "finished_at": "2026-07-24T10:06:00Z",
                        "total_files": -1,
                        "success_count": 0,
                        "skipped_count": 0,
                        "failed_count": 0,
                        "warning_count": 0,
                        "error_summary": [],
                    },
                )
            )
        )

        with self.assertRaises(QueryError) as context:
            service.get_batch_status("batch:bad")

        self.assertEqual("invalid_batch_count", context.exception.category)

    def test_get_batch_status_rejects_invalid_error_summary(self):
        from drawing_graph.query_service import QueryError, QueryService

        service = QueryService(
            FakeDriver(
                records=(
                    {
                        "id": "batch:bad",
                        "status": "failed",
                        "started_at": "2026-07-24T10:00:00Z",
                        "finished_at": "2026-07-24T10:06:00Z",
                        "total_files": 1,
                        "success_count": 0,
                        "skipped_count": 0,
                        "failed_count": 1,
                        "warning_count": 0,
                        "error_summary": "database_unavailable",
                    },
                )
            )
        )

        with self.assertRaises(QueryError) as context:
            service.get_batch_status("batch:bad")

        self.assertEqual("invalid_error_summary", context.exception.category)


if __name__ == "__main__":
    unittest.main()
