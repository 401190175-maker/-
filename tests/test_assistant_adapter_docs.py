"""Documentation contract tests for the product adapter acceptance record."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE_PATH = ROOT / "docs" / "acceptance" / "PRODUCT_ADAPTER_ACCEPTANCE.md"


class ProductAdapterAcceptanceDocTests(unittest.TestCase):
    def setUp(self):
        if not ACCEPTANCE_PATH.exists():
            self.fail("missing acceptance doc: PRODUCT_ADAPTER_ACCEPTANCE.md")
        self.doc = ACCEPTANCE_PATH.read_text(encoding="utf-8")

    def test_documents_all_three_entrances(self):
        for phrase in ("CLI", "HTTP", "MCP"):
            self.assertIn(phrase, self.doc)

    def test_documents_adapter_modules_and_scripts(self):
        for name in (
            "assistant_adapter_serialization.py",
            "assistant_http.py",
            "assistant_http_models.py",
            "assistant_http_runtime.py",
            "assistant_mcp_models.py",
            "assistant_mcp_tools.py",
            "assistant_mcp_runtime.py",
            "assistant_mcp_server.py",
            "serve_drawing_assistant.py",
            "serve_drawing_assistant_mcp.py",
        ):
            with self.subTest(name=name):
                self.assertIn(name, self.doc)

    def test_documents_verification_commands(self):
        for phrase in (
            "test_assistant_adapter_serialization",
            "test_assistant_http",
            "test_assistant_mcp_server",
            "test_product_adapter_e2e",
            "test_product_adapter_qa_compatibility",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.doc)

    def test_documents_status_layering(self):
        for phrase in (
            "unit/fake/offline",
            "HTTP TestClient",
            "MCP in-memory",
            "MCP STDIO",
            "live Neo4j",
            "live DashScope",
            "真实文本 provider",
            "真实 MCP 宿主注册",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.doc)

    def test_documents_skipped_is_not_live_neo4j_pass(self):
        self.assertIn("skipped 不等于 live Neo4j 通过", self.doc)
        self.assertIn("未验证", self.doc)

    def test_does_not_claim_unverified_live_as_verified(self):
        for phrase in (
            "live Neo4j",
            "live DashScope",
            "真实 MCP 宿主注册",
        ):
            self.assertNotIn(f"{phrase} | 已通过", self.doc)
            self.assertNotIn(f"{phrase} | 通过", self.doc)


if __name__ == "__main__":
    unittest.main()
