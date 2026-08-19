"""Static dependency and redaction boundary tests for trace modules."""

import ast
import unittest
from pathlib import Path

from drawing_graph.assistant_models import (
    AssistantRequest,
    QuestionUnderstandingResult,
)
from drawing_graph.assistant_trace_builder import TraceRecordBuilder

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src" / "drawing_graph"

TRACE_MODULES = (
    "assistant_trace_models",
    "assistant_trace_store",
    "assistant_trace_builder",
    "assistant_claim_trace",
    "assistant_traceability_service",
)

FORBIDDEN_MODULES = (
    "neo4j",
    "neo4j_repository",
    "relation_repository",
    "semantic_repository",
    "semantic_neo4j_repository",
    "qa_service",
    "qa_http",
    "qa_mcp",
    "import_service",
    "qwen_semantic_client",
    "semantic_client",
    "semantic_service",
    "recognition_execution",
    "tool_factory",
    "assistant_semantic_write_back",
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


class TraceModuleBoundaryTests(unittest.TestCase):
    def test_trace_modules_do_not_import_forbidden_backends(self):
        for module_name in TRACE_MODULES:
            with self.subTest(module=module_name):
                imported = _module_imports(module_name)
                for forbidden in FORBIDDEN_MODULES:
                    self.assertNotIn(forbidden, imported)

    def test_trace_output_does_not_leak_sensitive_fields(self):
        class _SensitiveRecognitionResult:
            recognition_run_id = "run:1"
            payload = "Bearer secret-token-123"

        builder = TraceRecordBuilder()
        record = builder.build(
            request=AssistantRequest(request_id="req:1", question="q"),
            question_result=QuestionUnderstandingResult(
                request_id="req:1",
                question_type="page_summary",
            ),
            recognition_results=(_SensitiveRecognitionResult(),),
        )
        serialized = repr(record)
        for token in (
            "secret-token-123",
            "Bearer",
            "neo4j://",
            "MATCH",
            "traceback",
            "C:\\",
            "/home/",
        ):
            self.assertNotIn(token, serialized)


if __name__ == "__main__":
    unittest.main()
