import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class QaDocsBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.module_doc = (ROOT / "Module.md").read_text(encoding="utf-8")
        self.architecture = (ROOT / "architecture.md").read_text(encoding="utf-8")

    def test_readme_documents_qa_cli_usage(self):
        for phrase in (
            "drawing_graph_qa.py",
            "ask-page",
            "ask-block",
            "ask-candidates",
        ):
            self.assertIn(phrase, self.readme)

    def test_readme_declares_qa_read_only_boundary(self):
        for phrase in (
            "默认只读",
            "write_back=false",
            "候选关系不是正式事实",
            "不直接写 Cypher",
            "HTTP API",
            "MCP Tool adapter",
            "第一阶段不实现 HTTP API",
        ):
            self.assertIn(phrase, self.readme)

    def test_module_doc_records_qa_modules(self):
        for phrase in (
            "src/drawing_graph/qa_models.py",
            "src/drawing_graph/qa_service.py",
            "src/drawing_graph/qa_rendering.py",
            "scripts/drawing_graph_qa.py",
            "DrawingGraphQAService",
            "DrawingGraphToolFacade",
        ):
            self.assertIn(phrase, self.module_doc)

    def test_architecture_records_qa_dependency_direction(self):
        self.assertIn(
            "QA adapter -> DrawingGraphQAService -> DrawingGraphToolFacade -> ports/services -> repository/Neo4j",
            self.architecture,
        )

    def test_architecture_declares_phase_one_boundaries(self):
        for phrase in (
            "write_back=false",
            "候选关系不是正式事实",
            "第一阶段不实现 HTTP API",
            "MCP Tool adapter",
            "OCR",
        ):
            self.assertIn(phrase, self.architecture)

    def test_docs_do_not_claim_http_or_mcp_completed(self):
        for document in (self.readme, self.module_doc, self.architecture):
            self.assertNotIn("HTTP API 已完成", document)
            self.assertNotIn("MCP Tool adapter 已完成", document)


if __name__ == "__main__":
    unittest.main()
