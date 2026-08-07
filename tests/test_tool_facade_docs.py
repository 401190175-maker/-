import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ToolFacadeDocsTest(unittest.TestCase):
    def setUp(self):
        self.architecture = (ROOT / "architecture.md").read_text(encoding="utf-8")
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.module = (ROOT / "Module.md").read_text(encoding="utf-8")

    def test_docs_record_real_tool_facade_boundaries(self):
        required_phrases = (
            "DrawingGraphToolFacade",
            "write_back=false",
            "dry-run",
            "`RecognitionRun` 图谱外",
            "`TextObservation` 图谱内",
            "候选关系不是正式事实",
        )
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.architecture)
                self.assertIn(phrase, self.readme)
                self.assertIn(phrase, self.module)

    def test_docs_do_not_claim_external_adapters_are_done(self):
        forbidden_claims = (
            "HTTP API 已完成",
            "Agent Skill 已完成",
            "MCP Tool adapter 已完成",
            "全量自动语义扫描已完成",
        )
        all_docs = "\n".join((self.architecture, self.readme, self.module))
        for phrase in forbidden_claims:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, all_docs)

    def test_docs_record_cli_tool_adapter_without_expanding_product_scope(self):
        required_phrases = (
            "scripts\\drawing_graph_tool.py",
            "薄 CLI adapter",
            "不提供 HTTP API",
            "不保存 Neo4j 密码",
        )
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.readme)
                self.assertIn(phrase, self.module)

    def test_docs_report_neo4j_integration_boundary(self):
        self.assertIn("跳过不等于通过", self.readme)
        self.assertIn("NEO4J_TEST_URI", self.module)


if __name__ == "__main__":
    unittest.main()
