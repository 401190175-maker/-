import os
import sys
import unittest
from pathlib import Path
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


NEO4J_TEST_URI = os.environ.get("NEO4J_TEST_URI")
NEO4J_TEST_USER = os.environ.get("NEO4J_TEST_USER")
NEO4J_TEST_PASSWORD = os.environ.get("NEO4J_TEST_PASSWORD")


@unittest.skipUnless(
    NEO4J_TEST_URI and NEO4J_TEST_USER and NEO4J_TEST_PASSWORD,
    "NEO4J_TEST_URI, NEO4J_TEST_USER, and NEO4J_TEST_PASSWORD are required",
)
class Neo4jImportIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from neo4j import GraphDatabase
        except ImportError as error:
            raise unittest.SkipTest("neo4j package is required for integration tests") from error

        cls.driver = GraphDatabase.driver(
            NEO4J_TEST_URI,
            auth=(NEO4J_TEST_USER, NEO4J_TEST_PASSWORD),
        )
        cls.driver.verify_connectivity()

    @classmethod
    def tearDownClass(cls):
        cls.driver.close()

    def setUp(self):
        self.project_slug = f"integration-{uuid4().hex}"
        self.fixture_root = PROJECT_ROOT / "tests" / "fixtures"
        self.batch_ids = []
        self._run_schema()

    def tearDown(self):
        self._cleanup_test_data()

    def test_schema_import_idempotency_and_query_closed_loop(self):
        from drawing_graph.config import ImportConfig
        from drawing_graph.import_service import ImportService
        from drawing_graph.neo4j_repository import Neo4jRepository
        from drawing_graph.query_service import QueryService

        config = ImportConfig(
            data_root=self.fixture_root,
            project_slug=self.project_slug,
            neo4j_uri=NEO4J_TEST_URI,
            neo4j_user=NEO4J_TEST_USER,
            neo4j_password=NEO4J_TEST_PASSWORD,
            batch_size=25,
        )
        repository = Neo4jRepository(self.driver, batch_size=config.batch_size)
        import_service = ImportService(config, repository)
        query_service = QueryService(self.driver)

        first_result = import_service.import_all()
        self.batch_ids.append(first_result.batch_id)

        self.assertEqual("success", first_result.status)
        self.assertEqual(1, first_result.total_count)
        self.assertEqual(1, first_result.success_count)
        self.assertEqual(0, first_result.skipped_count)
        self.assertEqual(0, first_result.failed_count)

        project_id = f"project:{self.project_slug}"
        set_id = f"set:{self.project_slug}:sample_page"
        page_id = f"page:{self.project_slug}:sample_page:road_24"

        sets = query_service.get_project_sets(project_id, limit=10)
        self.assertEqual([{"id": set_id, "name": "sample_page", "page_count": 1}], sets)

        pages = query_service.get_set_pages(set_id, limit=10)
        self.assertEqual(1, len(pages))
        self.assertEqual(page_id, pages[0]["id"])
        self.assertEqual("road_24.json", pages[0]["file_name"])
        self.assertEqual(24, pages[0]["page_number"])
        self.assertTrue(str(pages[0]["image_path"]).endswith("road_24.png"))

        blocks = query_service.get_page_blocks(page_id, limit=10)
        self.assertEqual(1, len(blocks))
        self.assertEqual("block", blocks[0]["label"])
        self.assertEqual({"x_min": 10.0, "y_min": 10.0, "x_max": 50.0, "y_max": 60.0}, blocks[0]["bbox"])
        self.assertEqual({"x_min": 0.05, "y_min": 0.1, "x_max": 0.25, "y_max": 0.6}, blocks[0]["normalized_bbox"])

        trace = query_service.get_block_trace(blocks[0]["id"])
        self.assertEqual(project_id, trace["project_id"])
        self.assertEqual(set_id, trace["drawing_set_id"])
        self.assertEqual(page_id, trace["page_id"])
        self.assertEqual(24, trace["page_number"])
        self.assertTrue(str(trace["image_path"]).endswith("road_24.png"))
        self.assertEqual(blocks[0]["bbox"], trace["bbox"])
        self.assertEqual(blocks[0]["normalized_bbox"], trace["normalized_bbox"])
        self.assertEqual("sample_page/road_24#shape-0", trace["citation_ref"])

        batch_status = query_service.get_batch_status(first_result.batch_id)
        self.assertEqual("success", batch_status["status"])
        self.assertEqual(1, batch_status["total_files"])
        self.assertEqual(1, batch_status["success_count"])
        self.assertEqual(0, batch_status["failed_count"])

        source_fact_counts = self._source_fact_table_counts(page_id)
        self.assertEqual(
            {
                "table_count": 1,
                "table_caption_count": 1,
                "table_caption_page_relation_count": 1,
                "table_caption_derived_relation_count": 0,
            },
            source_fact_counts,
        )

        business_counts_before = self._business_counts()
        second_result = import_service.import_all()
        self.batch_ids.append(second_result.batch_id)
        business_counts_after = self._business_counts()

        self.assertEqual("success", second_result.status)
        self.assertEqual(business_counts_before, business_counts_after)

    def _run_schema(self):
        statements = _schema_statements(PROJECT_ROOT / "scripts" / "create_schema.cypher")
        with self.driver.session() as session:
            for statement in statements:
                session.execute_write(lambda transaction, cypher=statement: transaction.run(cypher).consume())

    def _business_counts(self):
        with self.driver.session() as session:
            return session.execute_read(lambda transaction: _business_counts(transaction, self.project_slug))

    def _source_fact_table_counts(self, page_id):
        with self.driver.session() as session:
            return session.execute_read(lambda transaction: _source_fact_table_counts(transaction, page_id))

    def _cleanup_test_data(self):
        with self.driver.session() as session:
            session.execute_write(lambda transaction: _cleanup_test_data(transaction, self.project_slug, self.batch_ids))


def _schema_statements(schema_path):
    text = schema_path.read_text(encoding="utf-8")
    return tuple(statement.strip() for statement in text.split(";") if statement.strip())


def _business_counts(transaction, project_slug):
    result = transaction.run(
        """
        MATCH (project:Project {id: $project_id})-[:HAS_SET]->(drawing_set:DrawingSet)
        OPTIONAL MATCH (drawing_set)-[:HAS_PAGE]->(page:DrawingPage)
        OPTIONAL MATCH (page)-[containment]->(element)
        WHERE type(containment) <> 'IMPORTED_IN'
        OPTIONAL MATCH (table:Table)-[caption:HAS_CAPTION]->(:TableCaption)
        WHERE table.id STARTS WITH $element_prefix
        RETURN count(DISTINCT drawing_set) AS drawing_set_count,
               count(DISTINCT page) AS page_count,
               count(DISTINCT element) AS element_count,
               count(DISTINCT containment) AS containment_count,
               count(DISTINCT caption) AS caption_count
        """,
        project_id=f"project:{project_slug}",
        element_prefix=f"element:{project_slug}:",
    )
    record = result.single()
    return {
        "drawing_set_count": record["drawing_set_count"],
        "page_count": record["page_count"],
        "element_count": record["element_count"],
        "containment_count": record["containment_count"],
        "caption_count": record["caption_count"],
    }


def _source_fact_table_counts(transaction, page_id):
    result = transaction.run(
        """
        MATCH (page:DrawingPage {id: $page_id})
        OPTIONAL MATCH (page)-[:HAS_TABLE]->(table:Table)
        OPTIONAL MATCH (page)-[table_caption_page_relation:HAS_ELEMENT]->(table_caption:TableCaption)
        OPTIONAL MATCH (:Table)-[derived_caption:HAS_CAPTION]->(:TableCaption)
        WHERE startNode(derived_caption).id STARTS WITH $element_prefix
        RETURN count(DISTINCT table) AS table_count,
               count(DISTINCT table_caption) AS table_caption_count,
               count(DISTINCT table_caption_page_relation) AS table_caption_page_relation_count,
               count(DISTINCT derived_caption) AS table_caption_derived_relation_count
        """,
        page_id=page_id,
        element_prefix=_element_prefix_from_page_id(page_id),
    )
    record = result.single()
    return {
        "table_count": record["table_count"],
        "table_caption_count": record["table_caption_count"],
        "table_caption_page_relation_count": record["table_caption_page_relation_count"],
        "table_caption_derived_relation_count": record["table_caption_derived_relation_count"],
    }


def _element_prefix_from_page_id(page_id):
    _, project_slug, drawing_set_name, file_stem = page_id.split(":", 3)
    return f"element:{project_slug}:{drawing_set_name}:{file_stem}:"


def _cleanup_test_data(transaction, project_slug, batch_ids):
    transaction.run(
        """
        MATCH (node)
        WHERE node.id STARTS WITH $project_prefix
           OR node.id STARTS WITH $set_prefix
           OR node.id STARTS WITH $page_prefix
           OR node.id STARTS WITH $block_prefix
           OR node.id STARTS WITH $element_prefix
           OR node.id IN $batch_ids
        DETACH DELETE node
        """,
        project_prefix=f"project:{project_slug}",
        set_prefix=f"set:{project_slug}:",
        page_prefix=f"page:{project_slug}:",
        block_prefix=f"block:{project_slug}:",
        element_prefix=f"element:{project_slug}:",
        batch_ids=[batch_id for batch_id in batch_ids if batch_id],
    ).consume()


if __name__ == "__main__":
    unittest.main()
