"""Static dependency boundary tests for the 06 answer-generation layer."""

import ast
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src" / "drawing_graph"

ANSWER_MODULES = (
    "assistant_answer_generation",
    "assistant_claim_builder",
    "assistant_citation_builder",
    "assistant_answer_templates",
    "assistant_answer_text",
)

FORBIDDEN_MODULES = (
    "neo4j",
    "neo4j_repository",
    "relation_repository",
    "semantic_neo4j_repository",
    "semantic_repository",
    "candidate_review",
    "qwen_semantic_client",
    "semantic_client",
    "semantic_service",
    "tool_facade",
    "tool_factory",
    "assistant_semantic_write_back",
    "qa_service",
    "qa_http",
    "qa_mcp",
    "import_service",
    "recognition_execution",
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


class AnswerGenerationBoundaryTests(unittest.TestCase):
    def test_answer_modules_do_not_import_forbidden_backends(self):
        for module_name in ANSWER_MODULES:
            with self.subTest(module=module_name):
                imported = _module_imports(module_name)
                for forbidden in FORBIDDEN_MODULES:
                    self.assertNotIn(forbidden, imported)

    def test_answer_modules_consume_only_public_contracts(self):
        for module_name in ANSWER_MODULES:
            with self.subTest(module=module_name):
                imported = _module_imports(module_name)
                self.assertTrue(
                    {"assistant_models", "assistant_evidence_fusion_models"} & imported
                )

    def test_answer_generation_does_not_import_facade_or_repository(self):
        imported = _module_imports("assistant_answer_generation")
        self.assertNotIn("tool_facade", imported)
        self.assertNotIn("neo4j_repository", imported)
        self.assertNotIn("assistant_semantic_write_back", imported)


if __name__ == "__main__":
    unittest.main()
