"""Optional live Neo4j integration test for the MCP -> QAService -> facade chain.

未配置 ``NEO4J_TEST_URI``、``NEO4J_TEST_USER``、``NEO4J_TEST_PASSWORD`` 时
按设计跳过，跳过不等于 live Neo4j 已验证。配置 disposable 测试库后，本测试
通过官方 MCP 内存会话调用 ``ask_drawing_page``，链路为 MCP tool ->
``DrawingGraphQAService.ask()`` -> ``DrawingGraphToolFacade`` -> 受控查询。
测试本身只做一次性测试数据创建与清理；被测 MCP 链路不执行任意 Cypher、
不修改 Schema、不触发任何 write-back。
"""

import asyncio
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
class QaMcpNeo4jIntegrationTest(unittest.TestCase):
    """One read-only MCP call against a disposable Neo4j test database."""

    @classmethod
    def setUpClass(cls):
        try:
            from neo4j import GraphDatabase
        except ImportError as error:
            raise unittest.SkipTest(
                "neo4j package is required for integration tests"
            ) from error

        cls.driver = GraphDatabase.driver(
            NEO4J_TEST_URI,
            auth=(NEO4J_TEST_USER, NEO4J_TEST_PASSWORD),
        )
        cls.driver.verify_connectivity()

    @classmethod
    def tearDownClass(cls):
        cls.driver.close()

    def setUp(self):
        self.project_slug = f"qa-mcp-integration-{uuid4().hex}"
        self.project_id = f"project:{self.project_slug}"
        self.drawing_set_id = f"set:{self.project_slug}:sample_set"
        self.page_id = f"page:{self.project_slug}:sample_set:road_1"
        self.block_id = f"block:{self.project_slug}:sample_set:road_1:block"
        self._create_source_graph()

    def tearDown(self):
        self._cleanup_test_data()

    def test_mcp_reads_controlled_scope_through_qaservice_and_facade(self):
        from drawing_graph.config import QAMcpConfig
        from drawing_graph.qa_mcp_runtime import create_qa_mcp_runtime
        from drawing_graph.qa_mcp_server import create_mcp_server
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools
        from mcp.shared.memory import create_connected_server_and_client_session

        config = QAMcpConfig(
            neo4j_uri="bolt://disposable-test",
            neo4j_user="disposable-test",
            neo4j_password="disposable-test",
            log_level="INFO",
        )
        runtime = create_qa_mcp_runtime(
            config,
            driver_factory=lambda uri, auth: self.driver,
        )
        try:
            tools = DrawingGraphMCPTools(runtime.service)
            server = create_mcp_server(tools)

            async def call_page():
                async with create_connected_server_and_client_session(server) as client:
                    await client.initialize()
                    return await client.call_tool(
                        "ask_drawing_page",
                        {"page_id": self.page_id},
                    )

            result = asyncio.run(call_page())
            self.assertFalse(result.isError, result)
            structured = result.structuredContent
            self.assertIsNotNone(structured)
            self.assertEqual("ok", structured["status"])
            self.assertEqual(
                "drawing-qa-mcp-v1",
                structured["meta"]["contract_version"],
            )
            self.assertEqual(
                "ask_drawing_page",
                structured["meta"]["tool_name"],
            )
            self.assertEqual("answered", structured["data"]["status"])
            self.assertEqual(
                self.page_id,
                structured["data"]["scope"]["page_id"],
            )
            self.assertTrue(structured["data"]["source_calls"])
            texts = [
                item.text for item in result.content if item.type == "text"
            ]
            self.assertTrue(texts)
            self.assertIn("QA 状态：answered", texts[0])
        finally:
            runtime.close()

    def _create_source_graph(self):
        bbox = [10.0, 10.0, 80.0, 90.0]
        with self.driver.session() as session:
            session.execute_write(
                lambda transaction: transaction.run(
                    """
                    MERGE (project:Project {id: $project_id})
                    MERGE (drawing_set:DrawingSet {id: $drawing_set_id})
                    MERGE (page:DrawingPage {id: $page_id})
                    SET page.page_number = 1,
                        page.file_name = 'road_1.json',
                        page.image_path = 'tests/fixtures/road_1.png'
                    MERGE (block:DrawingBlock {id: $block_id})
                    SET block.bbox = $bbox
                    MERGE (project)-[:HAS_SET]->(drawing_set)
                    MERGE (drawing_set)-[:HAS_PAGE]->(page)
                    MERGE (page)-[:HAS_BLOCK]->(block)
                    """,
                    project_id=self.project_id,
                    drawing_set_id=self.drawing_set_id,
                    page_id=self.page_id,
                    block_id=self.block_id,
                    bbox=bbox,
                ).consume()
            )

    def _cleanup_test_data(self):
        with self.driver.session() as session:
            session.execute_write(
                lambda transaction: transaction.run(
                    """
                    MATCH (node)
                    WHERE node.id STARTS WITH $project_prefix
                       OR node.id STARTS WITH $set_prefix
                       OR node.id STARTS WITH $page_prefix
                       OR node.id STARTS WITH $block_prefix
                    DETACH DELETE node
                    """,
                    project_prefix=f"project:{self.project_slug}",
                    set_prefix=f"set:{self.project_slug}:",
                    page_prefix=f"page:{self.project_slug}:",
                    block_prefix=f"block:{self.project_slug}:",
                ).consume()
            )


if __name__ == "__main__":
    unittest.main()
