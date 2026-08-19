"""Static dependency boundary tests for the product MCP adapter."""

import ast
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src" / "drawing_graph"

MCP_ADAPTER_MODULES = (
    "assistant_mcp_models",
    "assistant_mcp_tools",
    "assistant_mcp_server",
)

FORBIDDEN_IMPORTS = (
    "drawing_graph.assistant_http",
    "drawing_graph.assistant_http_models",
    "drawing_graph.assistant_http_runtime",
    "drawing_graph.qa_http",
    "drawing_graph.qa_http_models",
    "drawing_graph.qa_http_runtime",
    "drawing_graph.qa_mcp",
    "drawing_graph.query_service",
    "drawing_graph.query_ports",
    "drawing_graph.query_port_adapter",
    "drawing_graph.relation_repository",
    "drawing_graph.neo4j_repository",
    "drawing_graph.semantic_neo4j_repository",
    "drawing_graph.semantic_repository",
    "drawing_graph.candidate_review",
    "drawing_graph.qwen_semantic_client",
    "drawing_graph.semantic_client",
    "drawing_graph.semantic_service",
    "drawing_graph.assistant_semantic_write_back",
    "drawing_graph.block_relation_enrichment",
    "drawing_graph.import_service",
    "drawing_graph.recognition_execution",
    "neo4j",
    "fastapi",
    "uvicorn",
)


def _module_imports(name):
    source = (SRC_DIR / f"{name}.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


class AssistantMcpBoundaryTests(unittest.TestCase):
    def test_adapter_modules_do_not_import_forbidden_backends(self):
        for module_name in MCP_ADAPTER_MODULES:
            with self.subTest(module=module_name):
                imported = _module_imports(module_name)
                for forbidden in FORBIDDEN_IMPORTS:
                    self.assertNotIn(forbidden, imported)

    def test_runtime_imports_tool_factory_but_adapter_does_not(self):
        runtime_imports = _module_imports("assistant_mcp_runtime")
        self.assertIn("tool_factory", runtime_imports)
        for module_name in MCP_ADAPTER_MODULES:
            imported = _module_imports(module_name)
            self.assertNotIn("tool_factory", imported)
            self.assertNotIn("tool_facade", imported)

    def test_tool_handler_does_not_call_facade_directly(self):
        source = (SRC_DIR / "assistant_mcp_tools.py").read_text(encoding="utf-8")
        self.assertIn("self.service.answer(", source)
        self.assertNotIn(".facade.", source)

    def test_server_exposes_only_read_only_assistant_tool(self):
        from drawing_graph.assistant_mcp_server import _TOOL_SPECS

        names = {spec.name for spec in _TOOL_SPECS}
        self.assertEqual({"ask_drawing_assistant"}, names)

    def test_server_has_no_write_or_promote_tool(self):
        source = (SRC_DIR / "assistant_mcp_server.py").read_text(encoding="utf-8")
        for forbidden in ("promote_candidate", "review_candidate", "run_cypher"):
            self.assertNotIn(forbidden, source)

    def test_no_hardcoded_credentials_or_cypher(self):
        for module_name in MCP_ADAPTER_MODULES:
            source = (SRC_DIR / f"{module_name}.py").read_text(encoding="utf-8")
            lowered = source.lower()
            self.assertNotIn("bolt://", lowered, module_name)
            self.assertNotIn("neo4j://", lowered, module_name)
            self.assertNotIn("password=", lowered, module_name)
            self.assertNotIn("api_key=", lowered, module_name)
            self.assertNotIn("match (", lowered, module_name)


if __name__ == "__main__":
    unittest.main()
