"""Tests for the product MCP runtime."""

import unittest

from drawing_graph.config import AssistantMcpConfig


def _config():
    return AssistantMcpConfig(
        neo4j_uri="bolt://example",
        neo4j_user="neo4j",
        neo4j_password="secret",
    )


class AssistantMcpRuntimeTests(unittest.TestCase):
    def test_runtime_assembles_with_fake_factories(self):
        from drawing_graph.assistant_mcp_runtime import create_assistant_mcp_runtime

        class FakeDriver:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        class FakeFacade:
            pass

        class FakeService:
            pass

        driver = FakeDriver()
        facade = FakeFacade()
        service = FakeService()
        runtime = create_assistant_mcp_runtime(
            _config(),
            driver_factory=lambda uri, auth: driver,
            facade_factory=lambda d: facade,
            service_factory=lambda f: service,
        )
        self.assertTrue(runtime.ready)
        self.assertIs(service, runtime.service)
        runtime.close()
        self.assertTrue(driver.closed)
        self.assertFalse(runtime.ready)

    def test_close_is_idempotent(self):
        from drawing_graph.assistant_mcp_runtime import create_assistant_mcp_runtime

        class FakeDriver:
            def __init__(self):
                self.closed = 0

            def close(self):
                self.closed += 1

        driver = FakeDriver()
        runtime = create_assistant_mcp_runtime(
            _config(),
            driver_factory=lambda uri, auth: driver,
            facade_factory=lambda d: object(),
            service_factory=lambda f: object(),
        )
        runtime.close()
        runtime.close()
        self.assertEqual(1, driver.closed)

    def test_init_failure_closes_driver(self):
        from drawing_graph.assistant_mcp_runtime import create_assistant_mcp_runtime

        class FakeDriver:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        driver = FakeDriver()

        def boom_facade(d):
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            create_assistant_mcp_runtime(
                _config(),
                driver_factory=lambda uri, auth: driver,
                facade_factory=boom_facade,
                service_factory=lambda f: object(),
            )
        self.assertTrue(driver.closed)

    def test_module_import_does_not_import_http_or_neo4j(self):
        import ast
        from pathlib import Path

        source = Path("src/drawing_graph/assistant_mcp_runtime.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        forbidden = {
            "drawing_graph.assistant_http",
            "drawing_graph.assistant_http_runtime",
            "drawing_graph.qa_http",
            "drawing_graph.qa_mcp",
            "drawing_graph.assistant_semantic_write_back",
            "drawing_graph.query_service",
        }
        self.assertFalse(imported.intersection(forbidden))


if __name__ == "__main__":
    unittest.main()
