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


class Neo4jRelationRepositoryTest(unittest.TestCase):
    def test_merge_relations_uses_allowed_relationship_and_parameterized_properties(self):
        from drawing_graph.models import GraphRelation
        from drawing_graph.neo4j_repository import Neo4jRepository

        driver = FakeDriver()
        repository = Neo4jRepository(driver=driver, batch_size=2)
        relations = (
            GraphRelation(
                start_id="page:1",
                end_id="block:1",
                relation_type="HAS_BLOCK",
                properties={"source": "mapping"},
            ),
            GraphRelation(
                start_id="page:1",
                end_id="table:1",
                relation_type="HAS_TABLE",
                properties={"source": "mapping"},
            ),
            GraphRelation(
                start_id="page:1",
                end_id="text:1",
                relation_type="HAS_TEXT",
                properties={"source": "mapping"},
            ),
        )

        repository.merge_relations(relations)

        calls = driver.sessions[0].transaction.calls
        self.assertEqual(3, len(calls))
        first_cypher, first_parameters = calls[0]
        self.assertIn("UNWIND $relations AS relation", first_cypher)
        self.assertIn("MATCH (start {id: relation.start_id})", first_cypher)
        self.assertIn("MATCH (end {id: relation.end_id})", first_cypher)
        self.assertIn("MERGE (start)-[r:HAS_BLOCK]->(end)", first_cypher)
        self.assertIn("SET r += relation.properties", first_cypher)
        self.assertNotIn("mapping", first_cypher)
        self.assertEqual(
            [{"start_id": "page:1", "end_id": "block:1", "properties": {"source": "mapping"}}],
            first_parameters["relations"],
        )

    def test_merge_relations_allows_section_mark_without_dynamic_cypher_values(self):
        from drawing_graph.models import GraphRelation
        from drawing_graph.neo4j_repository import Neo4jRepository

        driver = FakeDriver()
        repository = Neo4jRepository(driver=driver)

        repository.merge_relations(
            (
                GraphRelation(
                    start_id="block:1",
                    end_id="cross-section:1",
                    relation_type="HAS_SECTION_MARK",
                    properties={"rule_version": "v1", "link_rule": "cross_section_geometry_ownership_v1"},
                ),
            )
        )

        cypher, parameters = driver.sessions[0].transaction.calls[0]
        self.assertIn("MERGE (start)-[r:HAS_SECTION_MARK]->(end)", cypher)
        self.assertNotIn("cross-section:1", cypher)
        self.assertNotIn("cross_section_geometry_ownership_v1", cypher)
        self.assertEqual(
            [
                {
                    "start_id": "block:1",
                    "end_id": "cross-section:1",
                    "properties": {"rule_version": "v1", "link_rule": "cross_section_geometry_ownership_v1"},
                }
            ],
            parameters["relations"],
        )

    def test_duplicate_relations_are_deduplicated_with_latest_properties(self):
        from drawing_graph.models import GraphRelation
        from drawing_graph.neo4j_repository import Neo4jRepository

        driver = FakeDriver()
        repository = Neo4jRepository(driver=driver)
        relations = (
            GraphRelation("page:1", "block:1", "HAS_BLOCK", {"source": "old"}),
            GraphRelation("page:1", "block:1", "HAS_BLOCK", {"source": "new", "confidence": 0.95}),
        )

        repository.merge_relations(relations)

        _, parameters = driver.sessions[0].transaction.calls[0]
        self.assertEqual(
            [
                {
                    "start_id": "page:1",
                    "end_id": "block:1",
                    "properties": {"source": "new", "confidence": 0.95},
                }
            ],
            parameters["relations"],
        )

    def test_unknown_relation_type_is_rejected_before_query_runs(self):
        from drawing_graph.models import GraphRelation
        from drawing_graph.neo4j_repository import Neo4jRepository, RepositoryError

        driver = FakeDriver()
        repository = Neo4jRepository(driver=driver)

        with self.assertRaises(RepositoryError) as context:
            repository.merge_relations((GraphRelation("a", "b", "NEAR", {}),))

        self.assertEqual("invalid_relation_type", context.exception.category)
        self.assertEqual(0, len(driver.sessions))

    def test_missing_start_endpoint_is_classified(self):
        from drawing_graph.models import GraphRelation
        from drawing_graph.neo4j_repository import Neo4jRepository, RepositoryError

        repository = Neo4jRepository(driver=FakeDriver())

        with self.assertRaises(RepositoryError) as context:
            repository.merge_relations((GraphRelation(" ", "block:1", "HAS_BLOCK", {}),))

        self.assertEqual("missing_relation_endpoint", context.exception.category)

    def test_missing_end_endpoint_is_classified(self):
        from drawing_graph.models import GraphRelation
        from drawing_graph.neo4j_repository import Neo4jRepository, RepositoryError

        repository = Neo4jRepository(driver=FakeDriver())

        with self.assertRaises(RepositoryError) as context:
            repository.merge_relations((GraphRelation("page:1", " ", "HAS_BLOCK", {}),))

        self.assertEqual("missing_relation_endpoint", context.exception.category)


if __name__ == "__main__":
    unittest.main()
