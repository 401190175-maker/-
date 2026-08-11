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
            "MCP Tool adapter",
            "serve_drawing_graph_qa.py",
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
            "MCP Tool adapter",
            "OCR",
            "单 worker",
            "loopback",
        ):
            self.assertIn(phrase, self.architecture)

    def test_docs_do_not_claim_unimplemented_capabilities_completed(self):
        for document in (self.readme, self.module_doc, self.architecture):
            self.assertNotIn("MCP Tool adapter 已完成", document)
            self.assertNotIn("Ava 专有 adapter 已完成", document)
            self.assertNotIn("HTTP 写回已完成", document)


class QaMcpArchitectureDocsTests(unittest.TestCase):
    """Task 44: architecture.md must record the third-phase MCP adapter."""

    def setUp(self):
        self.architecture = (ROOT / "architecture.md").read_text(encoding="utf-8")

    def test_architecture_records_mcp_dataflow(self):
        for phrase in (
            "Skill -> MCP client -> STDIO MCP adapter -> DrawingGraphQAService",
            "MCP adapter -> DrawingGraphQAService -> DrawingGraphToolFacade",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.architecture)

    def test_architecture_declares_adapters_are_peers(self):
        for phrase in ("CLI、HTTP 与 MCP 是同级 adapter", "MCP 不调用 HTTP", "QA CLI"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.architecture)

    def test_architecture_declares_local_mcp_implemented_and_remote_not(self):
        for phrase in ("本地只读 MCP", "已实现", "远程 MCP", "未实现", "OAuth", "多 worker"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.architecture)

    def test_architecture_keeps_neo4j_boundaries_unchanged(self):
        for phrase in ("Neo4j 节点、关系、约束、索引保持不变", "RecognitionRun", "TextObservation"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.architecture)


if __name__ == "__main__":
    unittest.main()
