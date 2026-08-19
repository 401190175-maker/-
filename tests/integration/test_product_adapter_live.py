"""Optional live Neo4j integration test for the product assistant MCP chain.

未配置 ``NEO4J_TEST_URI``、``NEO4J_TEST_USER``、``NEO4J_TEST_PASSWORD`` 时
按设计跳过，跳过不等于 live Neo4j 已验证。配置 disposable 测试库后，本测试
通过官方 MCP 内存会话调用只读 ``ask_drawing_assistant``，链路为 MCP tool ->
``DrawingAssistantService.answer()`` -> ``DrawingGraphToolFacade`` -> 受控查询。
测试本身只做一次性测试数据创建与清理；被测产品链路不执行任意 Cypher、
不修改 Schema、不触发 write-back、不调用 DashScope、不写业务事实。
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
class ProductAdapterLiveNeo4jTest(unittest.TestCase):
    """One read-only product assistant MCP call against a disposable Neo4j test DB."""

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
        self.project_slug = f"product-adapter-live-{uuid4().hex}"
        self.project_id = f"project:{self.project_slug}"
        self.drawing_set_id = f"set:{self.project_slug}:sample_set"
        self.page_id = f"page:{self.project_slug}:sample_set:road_1"
        self.block_id = f"block:{self.project_slug}:sample_set:road_1:block"
        self._create_source_graph()

    def tearDown(self):
        self._cleanup_test_data()

    def test_product_mcp_reads_through_service_and_facade(self):
        from drawing_graph.assistant_mcp_runtime import create_assistant_mcp_runtime
        from drawing_graph.assistant_mcp_server import create_mcp_server
        from drawing_graph.assistant_mcp_tools import DrawingAssistantMCPTools
        from drawing_graph.config import AssistantMcpConfig
        from mcp.shared.memory import create_connected_server_and_client_session

        config = AssistantMcpConfig(
            neo4j_uri=str(NEO4J_TEST_URI),
            neo4j_user=str(NEO4J_TEST_USER),
            neo4j_password=str(NEO4J_TEST_PASSWORD),
            log_level="INFO",
        )
        runtime = create_assistant_mcp_runtime(config)
        try:
            tools = DrawingAssistantMCPTools(runtime.service)
            server = create_mcp_server(tools)

            async def call_assistant():
                async with create_connected_server_and_client_session(server) as client:
                    await client.initialize()
                    return await client.call_tool(
                        "ask_drawing_assistant",
                        {
                            "question": f"{self.page_id} 这张图主要讲什么",
                            "scope_hint": {"page_id": self.page_id},
                        },
                    )

            result = asyncio.run(call_assistant())
            self.assertFalse(result.isError, result)
            structured = result.structuredContent
            self.assertIsNotNone(structured)
            self.assertIn("status", structured)
            self.assertTrue(structured.get("request_id"))
            self.assertIn(
                structured["status"],
                ("answered", "partial", "clarification_required", "unsupported", "recognition_failed"),
            )
            texts = [item.text for item in result.content if item.type == "text"]
            self.assertTrue(texts)
        finally:
            runtime.close()

    def _create_source_graph(self):
        bbox = [10.0, 10.0, 80.0, 90.0]
        normalized_bbox = [0.1, 0.1, 0.8, 0.9]
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
                    SET block.bbox = $bbox,
                        block.normalized_bbox = $normalized_bbox
                    MERGE (project)-[:HAS_SET]->(drawing_set)
                    MERGE (drawing_set)-[:HAS_PAGE]->(page)
                    MERGE (page)-[:HAS_BLOCK]->(block)
                    """,
                    project_id=self.project_id,
                    drawing_set_id=self.drawing_set_id,
                    page_id=self.page_id,
                    block_id=self.block_id,
                    bbox=bbox,
                    normalized_bbox=normalized_bbox,
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
