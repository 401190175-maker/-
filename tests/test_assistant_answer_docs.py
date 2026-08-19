"""Documentation tests for the answer-generation and read-only orchestration change."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGE_DIR = ROOT / "changes" / "产品实现层" / "答案生成与只读总编排MVP"


class ArchitectureDocumentationTests(unittest.TestCase):
    def setUp(self):
        self.architecture = (ROOT / "architecture.md").read_text(encoding="utf-8")

    def test_documents_product_dependency_direction(self):
        for phrase in (
            "Product CLI (scripts/drawing_assistant.py)",
            "DrawingAssistantService (07)",
            "AnswerGenerationService(06)",
            "AnswerPackage",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.architecture)

    def test_documents_qa_chain_independence(self):
        for phrase in (
            "QA CLI/HTTP/MCP 链路保持独立",
            "产品 CLI 是同级 adapter",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.architecture)

    def test_documents_no_schema_or_write_back_expansion(self):
        for phrase in (
            "无 schema/写回扩张",
            "write_back=false",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.architecture)

    def test_documents_unverified_live_boundaries(self):
        for phrase in ("live Neo4j", "live DashScope", "均未验证"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.architecture)


class ChangeDocumentationTests(unittest.TestCase):
    def test_change_docs_record_implementation_status(self):
        for name in ("proposal.md", "design.md", "tasks.md"):
            with self.subTest(name=name):
                doc = (CHANGE_DIR / name).read_text(encoding="utf-8")
                self.assertIn("已实现", doc)

    def test_change_docs_do_not_claim_live_verification(self):
        for name in ("proposal.md", "design.md", "tasks.md"):
            with self.subTest(name=name):
                doc = (CHANGE_DIR / name).read_text(encoding="utf-8")
                self.assertIn("未验证", doc)


if __name__ == "__main__":
    unittest.main()
