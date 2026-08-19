"""Static dependency boundary tests for the 07 orchestration layer."""

import ast
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src" / "drawing_graph"

ORCHESTRATION_MODULES = (
    "drawing_assistant_service",
    "drawing_assistant_factory",
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
    "qa_service",
    "qa_http",
    "qa_mcp",
    "import_service",
    "assistant_semantic_write_back",
    "recognition_execution",
    "tool_factory",
)

ALLOWED_PUBLIC_CONTRACTS = (
    "assistant_models",
    "assistant_evidence_fusion_models",
    "assistant_question_understanding",
    "assistant_retrieval_service",
    "assistant_semantic_gap_decision",
    "assistant_answer_generation",
    "assistant_evidence_fusion",
    "tool_models",
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


class OrchestrationBoundaryTests(unittest.TestCase):
    def test_orchestration_modules_do_not_import_forbidden_backends(self):
        for module_name in ORCHESTRATION_MODULES:
            with self.subTest(module=module_name):
                imported = _module_imports(module_name)
                for forbidden in FORBIDDEN_MODULES:
                    self.assertNotIn(forbidden, imported)

    def test_orchestration_modules_import_only_public_contracts(self):
        for module_name in ORCHESTRATION_MODULES:
            with self.subTest(module=module_name):
                imported = _module_imports(module_name)
                self.assertTrue(set(ALLOWED_PUBLIC_CONTRACTS) & imported)


if __name__ == "__main__":
    unittest.main()
