"""Static boundary tests for the 03 semantic gap decision modules."""

from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "src" / "drawing_graph"

GAP_MODULES = (
    "assistant_evidence_sufficiency.py",
    "assistant_evidence_freshness.py",
    "assistant_recognition_target_planner.py",
    "assistant_recognition_budget.py",
    "assistant_semantic_gap_decision.py",
)

FORBIDDEN_IMPORT_TOKENS = (
    "import neo4j",
    "from neo4j",
    "from .neo4j",
    "import repository",
    "from .repository",
    "import tool_facade",
    "from .tool_facade",
    "import semantic_service",
    "from .semantic_service",
    "import qwen",
    "from .qwen",
    "import qa_http",
    "from .qa_http",
    "import qa_mcp",
    "from .qa_mcp",
    "import scripts",
    "from scripts",
)

FORBIDDEN_OPERATION_TOKENS = (
    "MATCH (",
    "MERGE (",
    "CREATE (",
    "RecognitionRun(",
    "cache.put(",
    ".put(",
    "write_back=True",
)


class SemanticGapBoundaryTests(unittest.TestCase):
    def test_gap_modules_never_import_execution_backend(self):
        for module_name in GAP_MODULES:
            source = (SOURCE_DIR / module_name).read_text(encoding="utf-8")
            for token in FORBIDDEN_IMPORT_TOKENS:
                self.assertNotIn(
                    token,
                    source,
                    f"{module_name} must not import {token!r}",
                )

    def test_gap_modules_never_use_execution_operations(self):
        for module_name in GAP_MODULES:
            source = (SOURCE_DIR / module_name).read_text(encoding="utf-8")
            for token in FORBIDDEN_OPERATION_TOKENS:
                self.assertNotIn(
                    token,
                    source,
                    f"{module_name} must not contain {token!r}",
                )

    def test_gap_modules_import_contract_and_read_only_cache_helpers(self):
        for module_name in GAP_MODULES:
            source = (SOURCE_DIR / module_name).read_text(encoding="utf-8")
            self.assertIn(
                "assistant_models",
                source,
                f"{module_name} must import assistant_models",
            )

    def test_gap_modules_never_call_facade_target_entry(self):
        for module_name in GAP_MODULES:
            source = (SOURCE_DIR / module_name).read_text(encoding="utf-8")
            self.assertNotIn(
                "recognize_semantic_targets(",
                source,
                f"{module_name} must not call the facade target entry",
            )


if __name__ == "__main__":
    unittest.main()
