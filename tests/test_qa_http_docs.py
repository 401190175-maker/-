"""Docs tests protecting the phase-two HTTP API current implementation boundaries."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class QaHttpDocsTests(unittest.TestCase):
    """README/Module/architecture must describe the implemented HTTP adapter truthfully."""

    def setUp(self):
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.module_doc = (ROOT / "Module.md").read_text(encoding="utf-8")
        self.architecture = (ROOT / "architecture.md").read_text(encoding="utf-8")

    def test_readme_documents_http_startup_and_env(self):
        for phrase in (
            "serve_drawing_graph_qa.py",
            "DRAWING_GRAPH_QA_HTTP_HOST",
            "DRAWING_GRAPH_QA_HTTP_API_TOKEN",
            "/api/v1/drawing-qa/ask",
            "/health/live",
            "/health/ready",
            "127.0.0.1",
            "单 worker",
        ):
            self.assertIn(phrase, self.readme)

    def test_readme_documents_read_only_and_health_boundary(self):
        for phrase in (
            "write_back=false",
            "CORS",
            "docs",
            "外部 TLS",
            "not_checked",
            "不等于 live Neo4j 验证",
        ):
            self.assertIn(phrase, self.readme)

    def test_module_doc_records_http_modules_and_dependencies(self):
        for phrase in (
            "src/drawing_graph/qa_serialization.py",
            "src/drawing_graph/qa_http_models.py",
            "src/drawing_graph/qa_http_runtime.py",
            "src/drawing_graph/qa_http.py",
            "scripts/serve_drawing_graph_qa.py",
            "FastAPI",
            "Uvicorn",
            "HTTPX",
            "lifespan",
        ):
            self.assertIn(phrase, self.module_doc)

    def test_architecture_records_http_dependency_direction(self):
        self.assertIn(
            "HTTP adapter -> DrawingGraphQAService -> DrawingGraphToolFacade -> ports/services -> repository/Neo4j",
            self.architecture,
        )

    def test_architecture_keeps_unimplemented_boundaries(self):
        for phrase in ("MCP Tool adapter", "Ava", "OCR", "全量自动语义扫描", "HTTP 写回"):
            self.assertIn(phrase, self.architecture)

    def test_docs_do_not_claim_health_as_live_neo4j_verification(self):
        for document in (self.readme, self.module_doc, self.architecture):
            self.assertIn("不等于 live Neo4j 验证", document)


if __name__ == "__main__":
    unittest.main()
