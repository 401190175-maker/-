import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class FakeTransaction:
    def __init__(self):
        self.calls = []

    def run(self, cypher, **parameters):
        self.calls.append((cypher, parameters))


class FakeSession:
    def __init__(self):
        self.transaction = FakeTransaction()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute_write(self, callback):
        return callback(self.transaction)


class FakeDriver:
    def __init__(self):
        self.sessions = []

    def session(self):
        session = FakeSession()
        self.sessions.append(session)
        return session


class Neo4jBatchRepositoryTest(unittest.TestCase):
    def test_create_batch_merges_running_import_batch(self):
        from drawing_graph.neo4j_repository import Neo4jRepository

        driver = FakeDriver()
        repository = Neo4jRepository(driver=driver)

        repository.create_batch(
            batch_id="batch:1",
            project_id="project:demo",
            source_root="data",
            started_at="2026-07-23T10:00:00Z",
        )

        cypher, parameters = driver.sessions[0].transaction.calls[0]
        self.assertIn("MERGE (batch:ImportBatch {id: $batch_id})", cypher)
        self.assertIn("SET batch.status = 'running'", cypher)
        self.assertIn("batch.project_id = $project_id", cypher)
        self.assertNotIn("project:demo", cypher)
        self.assertEqual("batch:1", parameters["batch_id"])
        self.assertEqual("project:demo", parameters["project_id"])
        self.assertEqual("data", parameters["source_root"])
        self.assertEqual("2026-07-23T10:00:00Z", parameters["started_at"])

    def test_finish_batch_updates_success_status_and_statistics(self):
        from drawing_graph.neo4j_repository import Neo4jRepository

        driver = FakeDriver()
        repository = Neo4jRepository(driver=driver)

        repository.finish_batch(
            batch_id="batch:1",
            status="success",
            finished_at="2026-07-23T10:05:00Z",
            total_files=3,
            success_count=2,
            skipped_count=1,
            failed_count=0,
            warning_count=4,
            error_summary=(),
        )

        cypher, parameters = driver.sessions[0].transaction.calls[0]
        self.assertIn("MATCH (batch:ImportBatch {id: $batch_id})", cypher)
        self.assertIn("SET batch.status = $status", cypher)
        self.assertNotIn("success_count: 2", cypher)
        self.assertEqual("success", parameters["status"])
        self.assertEqual(3, parameters["total_files"])
        self.assertEqual(2, parameters["success_count"])
        self.assertEqual(1, parameters["skipped_count"])
        self.assertEqual(0, parameters["failed_count"])
        self.assertEqual(4, parameters["warning_count"])
        self.assertEqual([], parameters["error_summary"])

    def test_finish_batch_accepts_failed_status_and_error_summary(self):
        from drawing_graph.neo4j_repository import Neo4jRepository

        driver = FakeDriver()
        repository = Neo4jRepository(driver=driver)

        repository.finish_batch(
            batch_id="batch:failed",
            status="failed",
            finished_at="2026-07-23T10:06:00Z",
            total_files=2,
            success_count=1,
            skipped_count=0,
            failed_count=1,
            warning_count=0,
            error_summary=("database_unavailable",),
        )

        _, parameters = driver.sessions[0].transaction.calls[0]
        self.assertEqual("failed", parameters["status"])
        self.assertEqual(1, parameters["failed_count"])
        self.assertEqual(["database_unavailable"], parameters["error_summary"])

    def test_finish_batch_rejects_non_terminal_status(self):
        from drawing_graph.neo4j_repository import Neo4jRepository, RepositoryError

        repository = Neo4jRepository(driver=FakeDriver())

        with self.assertRaises(RepositoryError) as context:
            repository.finish_batch(
                batch_id="batch:1",
                status="running",
                finished_at="2026-07-23T10:05:00Z",
                total_files=0,
                success_count=0,
                skipped_count=0,
                failed_count=0,
                warning_count=0,
                error_summary=(),
            )

        self.assertEqual("invalid_batch_status", context.exception.category)

    def test_link_page_to_batch_preserves_page_batch_history_as_relationships(self):
        from drawing_graph.neo4j_repository import Neo4jRepository

        driver = FakeDriver()
        repository = Neo4jRepository(driver=driver)

        repository.link_page_to_batch("page:1", "batch:1")
        repository.link_page_to_batch("page:1", "batch:2")

        calls = [
            call
            for session in driver.sessions
            for call in session.transaction.calls
        ]
        self.assertEqual(2, len(calls))
        first_cypher, first_parameters = calls[0]
        self.assertIn("MATCH (page:DrawingPage {id: $page_id})", first_cypher)
        self.assertIn("MATCH (batch:ImportBatch {id: $batch_id})", first_cypher)
        self.assertIn("MERGE (page)-[:IMPORTED_IN]->(batch)", first_cypher)
        self.assertNotIn("import_batch_id", first_cypher)
        self.assertEqual("batch:1", first_parameters["batch_id"])
        self.assertEqual("batch:2", calls[1][1]["batch_id"])

    def test_empty_batch_or_page_identifiers_are_rejected(self):
        from drawing_graph.neo4j_repository import Neo4jRepository, RepositoryError

        repository = Neo4jRepository(driver=FakeDriver())

        with self.assertRaises(RepositoryError) as context:
            repository.link_page_to_batch(" ", "batch:1")
        self.assertEqual("missing_required_field", context.exception.category)

        with self.assertRaises(RepositoryError) as context:
            repository.create_batch(" ", "project:demo", "data", "now")
        self.assertEqual("missing_required_field", context.exception.category)


if __name__ == "__main__":
    unittest.main()
