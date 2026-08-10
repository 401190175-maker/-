import asyncio
import os
import subprocess
import sys
import unittest
from pathlib import Path


def _run(coro):
    """Run one async protocol-level check with asyncio."""

    return asyncio.run(coro)


def _client_session(server):
    """Return an in-memory MCP client session connected to the given server."""

    from mcp.shared.memory import create_connected_server_and_client_session

    return create_connected_server_and_client_session(server)


class QAMcpServerFactoryTests(unittest.TestCase):
    """create_mcp_server must build a tools-only, no-side-effect server."""

    def test_factory_creates_server_with_fixed_name_and_instructions(self):
        from drawing_graph.qa_mcp_server import (
            MCP_SERVER_INSTRUCTIONS,
            MCP_SERVER_NAME,
            create_mcp_server,
        )

        server = create_mcp_server(_StubTools())
        self.assertEqual("drawing-graph-qa", MCP_SERVER_NAME)
        self.assertLessEqual(len(MCP_SERVER_INSTRUCTIONS), 512)

        async def check():
            async with _client_session(server) as client:
                init = await client.initialize()
                return init

        init = _run(check())
        self.assertEqual("drawing-graph-qa", init.serverInfo.name)
        self.assertIsNotNone(init.instructions)
        for phrase in ("只读", "候选", "正式", "来源事实", "Cypher", "验证状态"):
            self.assertIn(phrase, MCP_SERVER_INSTRUCTIONS)

    def test_initialized_server_advertises_only_tools_capability(self):
        from drawing_graph.qa_mcp_server import create_mcp_server

        server = create_mcp_server(_StubTools())

        async def check():
            async with _client_session(server) as client:
                init = await client.initialize()
                return init

        init = _run(check())
        self.assertIsNotNone(init.capabilities.tools)
        self.assertIsNone(init.capabilities.resources)
        self.assertIsNone(init.capabilities.prompts)
        self.assertIsNone(init.capabilities.completions)
        self.assertIsNone(init.capabilities.logging)

    def test_create_mcp_server_has_no_env_driver_or_transport_side_effect(self):
        code = (
            "import sys\n"
            "import drawing_graph.qa_mcp_server as module\n"
            "assert 'neo4j' not in sys.modules\n"
            "assert 'drawing_graph.qa_http' not in sys.modules\n"
            "assert 'drawing_graph.qa_http_runtime' not in sys.modules\n"
            "print('import-ok')\n"
        )
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("NEO4J_", "DRAWING_GRAPH_QA_MCP_"))
        }
        result = subprocess.run(
            [sys.executable, "-c", code],
            env=env,
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[1]),
            timeout=30,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("import-ok", result.stdout)

    def test_server_module_does_not_import_http_cli_or_repository(self):
        import ast

        source = Path("src/drawing_graph/qa_mcp_server.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

        for forbidden in (
            "drawing_graph.qa_http",
            "drawing_graph.qa_http_runtime",
            "drawing_graph.qa_service",
            "drawing_graph.query_service",
            "drawing_graph.relation_repository",
            "drawing_graph.tool_facade",
            "neo4j",
        ):
            self.assertNotIn(forbidden, imported)

    def test_factory_creates_server_without_running_transport(self):
        from mcp.server.lowlevel import Server

        from drawing_graph.qa_mcp_server import create_mcp_server

        server = create_mcp_server(_StubTools())
        self.assertIsInstance(server, Server)


class _StubTools:
    """Minimal stand-in that server creation must not call during creation."""

    def __getattr__(self, name):
        raise AssertionError(f"server factory must not call tools.{name} during creation")


if __name__ == "__main__":
    unittest.main()
