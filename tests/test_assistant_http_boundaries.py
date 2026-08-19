"""Static dependency boundary tests for the product HTTP adapter."""

import ast
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src" / "drawing_graph"

HTTP_ADAPTER_MODULES = ("assistant_http", "assistant_http_models")

FORBIDDEN_BACKENDS = (
    "neo4j",
    "neo4j_repository",
    "relation_repository",
    "semantic_neo4j_repository",
    "semantic_repository",
    "candidate_review",
    "qwen_semantic_client",
    "semantic_client",
    "semantic_service",
    "assistant_semantic_write_back",
    "block_relation_enrichment",
    "caption_matching",
    "section_match_service",
    "query_service",
    "query_ports",
    "query_port_adapter",
    "recognition_execution",
    "import_service",
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


class AssistantHttpBoundaryTests(unittest.TestCase):
    def test_adapter_modules_do_not_import_forbidden_backends(self):
        for module_name in HTTP_ADAPTER_MODULES:
            with self.subTest(module=module_name):
                imported = _module_imports(module_name)
                for forbidden in FORBIDDEN_BACKENDS:
                    self.assertNotIn(forbidden, imported)

    def test_route_module_does_not_call_facade_or_tool_factory(self):
        imported = _module_imports("assistant_http")
        for forbidden in ("tool_factory", "tool_facade", "neo4j"):
            self.assertNotIn(forbidden, imported)
        source = (SRC_DIR / "assistant_http.py").read_text(encoding="utf-8")
        self.assertNotIn(".facade.", source)
        self.assertNotIn("create_neo4j_tool_facade(", source)
        self.assertNotIn("DrawingGraphToolFacade(", source)

    def test_models_do_not_import_factory_or_facade(self):
        imported = _module_imports("assistant_http_models")
        for forbidden in ("tool_factory", "tool_facade", "neo4j"):
            self.assertNotIn(forbidden, imported)

    def test_route_handler_uses_only_service(self):
        source = (SRC_DIR / "assistant_http.py").read_text(encoding="utf-8")
        self.assertIn("service.answer(", source)
        self.assertIn("app.state.assistant_runtime.service", source)

    def test_runtime_can_import_tool_factory_but_routes_cannot(self):
        runtime_imports = _module_imports("assistant_http_runtime")
        self.assertIn("tool_factory", runtime_imports)
        for module_name in HTTP_ADAPTER_MODULES:
            imported = _module_imports(module_name)
            self.assertNotIn("tool_factory", imported)

    def test_no_hardcoded_credentials_or_cypher(self):
        for module_name in HTTP_ADAPTER_MODULES:
            source = (SRC_DIR / f"{module_name}.py").read_text(encoding="utf-8")
            lowered = source.lower()
            self.assertNotIn("bolt://", lowered, module_name)
            self.assertNotIn("neo4j://", lowered, module_name)
            self.assertNotIn("password=", lowered, module_name)
            self.assertNotIn("api_key=", lowered, module_name)
            self.assertNotIn("match (", lowered, module_name)


if __name__ == "__main__":
    unittest.main()
