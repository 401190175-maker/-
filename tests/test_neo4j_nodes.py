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


class Neo4jNodeRepositoryTest(unittest.TestCase):
    def test_merge_nodes_uses_batch_parameterized_cypher(self):
        from drawing_graph.models import GraphNode
        from drawing_graph.neo4j_repository import Neo4jRepository

        driver = FakeDriver()
        repository = Neo4jRepository(driver=driver, batch_size=2)
        nodes = (
            GraphNode(id="page:1", labels=("DrawingPage",), properties={"file_name": "road_1.json"}),
            GraphNode(id="page:2", labels=("DrawingPage",), properties={"file_name": "road_2.json"}),
            GraphNode(id="page:3", labels=("DrawingPage",), properties={"file_name": "road_3.json"}),
        )

        repository.merge_nodes(nodes)

        calls = driver.sessions[0].transaction.calls
        self.assertEqual(2, len(calls))
        first_cypher, first_parameters = calls[0]
        self.assertIn("UNWIND $nodes AS node", first_cypher)
        self.assertIn("MERGE (n:DrawingPage {id: node.id})", first_cypher)
        self.assertIn("SET n += node.properties", first_cypher)
        self.assertNotIn("road_1.json", first_cypher)
        self.assertEqual(
            [
                {"id": "page:1", "properties": {"id": "page:1", "file_name": "road_1.json"}},
                {"id": "page:2", "properties": {"id": "page:2", "file_name": "road_2.json"}},
            ],
            first_parameters["nodes"],
        )

    def test_duplicate_nodes_are_deduplicated_with_latest_properties(self):
        from drawing_graph.models import GraphNode
        from drawing_graph.neo4j_repository import Neo4jRepository

        driver = FakeDriver()
        repository = Neo4jRepository(driver=driver)
        nodes = (
            GraphNode(id="table:1", labels=("Table",), properties={"label": "old"}),
            GraphNode(id="table:1", labels=("Table",), properties={"label": "new", "confidence": 0.95}),
        )

        repository.merge_nodes(nodes)

        _, parameters = driver.sessions[0].transaction.calls[0]
        self.assertEqual(
            [{"id": "table:1", "properties": {"id": "table:1", "label": "new", "confidence": 0.95}}],
            parameters["nodes"],
        )

    def test_nodes_with_different_labels_are_written_in_separate_queries(self):
        from drawing_graph.models import GraphNode
        from drawing_graph.neo4j_repository import Neo4jRepository

        driver = FakeDriver()
        repository = Neo4jRepository(driver=driver)
        nodes = (
            GraphNode(id="page:1", labels=("DrawingPage",), properties={"file_name": "road_1.json"}),
            GraphNode(id="block:1", labels=("DrawingBlock",), properties={"label": "block"}),
        )

        repository.merge_nodes(nodes)

        cyphers = [cypher for cypher, _ in driver.sessions[0].transaction.calls]
        self.assertEqual(2, len(cyphers))
        self.assertIn("MERGE (n:DrawingPage {id: node.id})", cyphers[0])
        self.assertIn("MERGE (n:DrawingBlock {id: node.id})", cyphers[1])

    def test_invalid_label_is_rejected_before_query_runs(self):
        from drawing_graph.models import GraphNode
        from drawing_graph.neo4j_repository import Neo4jRepository, RepositoryError

        driver = FakeDriver()
        repository = Neo4jRepository(driver=driver)

        with self.assertRaises(RepositoryError) as context:
            repository.merge_nodes((GraphNode(id="bad:1", labels=("InjectedLabel",), properties={}),))

        self.assertEqual("invalid_node_label", context.exception.category)
        self.assertEqual(0, len(driver.sessions))

    def test_multi_label_node_is_rejected_for_task_14(self):
        from drawing_graph.models import GraphNode
        from drawing_graph.neo4j_repository import Neo4jRepository, RepositoryError

        repository = Neo4jRepository(driver=FakeDriver())

        with self.assertRaises(RepositoryError) as context:
            repository.merge_nodes((GraphNode(id="node:1", labels=("DrawingPage", "Table"), properties={}),))

        self.assertEqual("invalid_node_label", context.exception.category)

    def test_requirements_declares_neo4j_driver(self):
        requirements_path = PROJECT_ROOT / "requirements.txt"

        self.assertTrue(requirements_path.exists())
        self.assertIn("neo4j", requirements_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
