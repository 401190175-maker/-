"""Static safety boundary tests for the product read-only CLI."""

import ast
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "drawing_assistant.py"

FORBIDDEN_IMPORTS = (
    "neo4j_repository",
    "relation_repository",
    "semantic_neo4j_repository",
    "semantic_repository",
    "candidate_review",
    "qwen_semantic_client",
    "semantic_client",
    "semantic_service",
    "assistant_semantic_write_back",
    "query_service",
    "query_ports",
    "query_port_adapter",
    "qa_service",
    "qa_http",
    "qa_mcp",
    "import_service",
    "block_relation_enrichment",
    "caption_matching",
    "section_match_service",
    "section_alias_rules",
)


def _cli_imports():
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


class CliBoundaryTests(unittest.TestCase):
    def test_cli_does_not_import_forbidden_backends(self):
        imported = _cli_imports()
        for forbidden in FORBIDDEN_IMPORTS:
            self.assertNotIn(forbidden, imported)

    def test_cli_imports_only_adapter_dependencies(self):
        imported = _cli_imports()
        self.assertIn("drawing_assistant_factory", imported | {"drawing_assistant_factory"})
        self.assertFalse({"neo4j_repository", "query_service", "candidate_review"} & imported)

    def test_cli_has_no_hardcoded_credentials_or_uri(self):
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertNotIn("bolt://", source)
        self.assertNotIn("neo4j://", source)
        self.assertNotIn("password=", source)
        self.assertNotIn("api_key=", source)

    def test_cli_has_no_write_back_argument(self):
        import importlib.util
        import sys

        if str(PROJECT_ROOT / "src") not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT / "src"))
        spec = importlib.util.spec_from_file_location("drawing_assistant_boundary_under_test", SCRIPT_PATH)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        dests = {action.dest for action in module.build_parser()._actions}
        for forbidden in ("write_back", "password", "token", "uri", "user", "api_key", "neo4j"):
            self.assertNotIn(forbidden, dests)


if __name__ == "__main__":
    unittest.main()
