import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
README_PATH = PROJECT_ROOT / "README.md"


class ReadmeTest(unittest.TestCase):
    def setUp(self):
        self.readme = README_PATH.read_text(encoding="utf-8")

    def test_documents_required_environment_variables(self):
        for name in (
            "DRAWING_GRAPH_DATA_ROOT",
            "DRAWING_GRAPH_PROJECT_SLUG",
            "NEO4J_URI",
            "NEO4J_USER",
            "NEO4J_PASSWORD",
            "DRAWING_GRAPH_BATCH_SIZE",
            "DRAWING_GRAPH_LOG_LEVEL",
        ):
            self.assertIn(name, self.readme)

    def test_documents_schema_initialization_and_import_modes(self):
        self.assertIn("scripts\\create_schema.cypher", self.readme)
        self.assertIn("cypher-shell", self.readme)
        self.assertRegex(self.readme, r"python\s+scripts\\import_json\.py\s+all")
        self.assertRegex(self.readme, r"python\s+scripts\\import_json\.py\s+drawing-set")
        self.assertRegex(self.readme, r"python\s+scripts\\import_json\.py\s+page")

    def test_documents_tests_path_rules_page_rules_queries_and_errors(self):
        required_phrases = (
            "python -m unittest tests.test_readme -v",
            "python -m unittest tests.integration.test_neo4j_import -v",
            "同目录同名 PNG",
            "original_image_path",
            "只接受 `road_<数字>.json`",
            "QueryService",
            "get_project_sets",
            "get_set_pages",
            "get_page_blocks",
            "get_block_trace",
            "get_batch_status",
            "review_candidate_relations.py",
            "常见错误",
        )
        for phrase in required_phrases:
            self.assertIn(phrase, self.readme)

    def test_documents_source_fact_import_boundary(self):
        required_phrases = (
            "来源事实导入",
            "基础导入只写来源节点、页面归属关系、稳定 ID、图片路径、bbox 和 ImportBatch 审计",
            "DrawingPage -[:HAS_ELEMENT]-> TableCaption",
            "基础导入不会自动写入 `Table -[:HAS_CAPTION]-> TableCaption`",
            "显式执行离线派生关系增强",
            "基础导入不会自动运行候选关系 AI 复核",
        )
        for phrase in required_phrases:
            self.assertIn(phrase, self.readme)

        self.assertNotIn("基础导入、表格标题最近表格匹配", self.readme)
        self.assertNotIn("结构化导入、表格标题最近表格匹配", self.readme)

    def test_does_not_contain_real_secret_values(self):
        suspicious_secret_patterns = (
            r"(?i)password\s*=\s*['\"][^<\s][^'\"]+['\"]",
            r"(?i)token\s*=\s*['\"][^<\s][^'\"]+['\"]",
            r"(?i)secret\s*=\s*['\"][^<\s][^'\"]+['\"]",
        )
        for pattern in suspicious_secret_patterns:
            self.assertIsNone(re.search(pattern, self.readme))
        self.assertIn("<your-password>", self.readme)
        self.assertIn("<test-password>", self.readme)


class ReadmeMcpTest(unittest.TestCase):
    """Task 42: README must document the local read-only MCP adapter."""

    def setUp(self):
        self.readme = README_PATH.read_text(encoding="utf-8")

    def test_documents_mcp_stdio_entry_and_stable_server_name(self):
        for phrase in ("serve_drawing_graph_mcp.py", "drawing-graph-qa", "STDIO"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.readme)

    def test_lists_all_six_readonly_tools(self):
        for tool_name in (
            "ask_drawing_page",
            "ask_drawing_block",
            "list_drawing_candidates",
            "get_section_match_status",
            "get_table_caption_status",
            "get_drawing_diagnostics",
        ):
            with self.subTest(tool=tool_name):
                self.assertIn(tool_name, self.readme)

    def test_documents_readonly_and_protocol_boundaries(self):
        for phrase in (
            "write_back=false",
            "stdout 只承载 MCP 协议帧",
            "stderr",
            "DRAWING_GRAPH_QA_MCP_LOG_LEVEL",
            "DrawingGraphQAService",
            "不调用 HTTP API 或 QA CLI",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.readme)

    def test_documents_verification_and_unimplemented_boundaries(self):
        for phrase in (
            "live Neo4j",
            "未验证",
            "Streamable HTTP",
            "未实现",
            "透明降级",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.readme)


class ReadmeAnswerGenerationTest(unittest.TestCase):
    """README must document the product read-only CLI and its boundaries."""

    def setUp(self):
        self.readme = README_PATH.read_text(encoding="utf-8")

    def test_documents_cli_entry_and_parameters(self):
        for phrase in (
            "scripts/drawing_assistant.py",
            "--allow-recognition",
            "--no-recognition",
            "--text-generation",
            "--output json|text",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.readme)

    def test_documents_output_and_exit_codes(self):
        for phrase in (
            '"ok": true',
            "answer_contract_version",
            "machine_answer",
            "text_answer",
            "退出码",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.readme)

    def test_documents_readonly_and_verification_boundaries(self):
        for phrase in (
            "write_back=false",
            "不提供 `--write-back` 参数",
            "live Neo4j",
            "均未验证",
            "回退模板",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.readme)

    def test_cli_example_has_no_secret(self):
        self.assertNotIn("password=", self.readme.split("答案生成与只读总编排")[1])


class ReadmeProductAdapterTest(unittest.TestCase):
    """README must document the product HTTP/MCP adapter and its boundaries."""

    def setUp(self):
        self.readme = README_PATH.read_text(encoding="utf-8")

    def test_documents_product_http_and_mcp_adapters(self):
        for phrase in (
            "assistant_http.py",
            "assistant_mcp_server.py",
            "serve_drawing_assistant.py",
            "serve_drawing_assistant_mcp.py",
            "ask_drawing_assistant",
            "/api/v1/drawing-assistant/ask",
            "DRAWING_GRAPH_ASSISTANT_HTTP_",
            "DRAWING_GRAPH_ASSISTANT_MCP_LOG_LEVEL",
            "DrawingAssistantService.answer()",
            "PRODUCT_ADAPTER_ACCEPTANCE.md",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.readme)

    def test_documents_readonly_and_verification_boundaries(self):
        for phrase in (
            "write_back=false",
            "候选关系不是正式事实",
            "live Neo4j",
            "live DashScope",
            "真实文本 provider",
            "均未验证",
            "skipped live 测试不等于 live 通过",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.readme)


if __name__ == "__main__":
    unittest.main()
