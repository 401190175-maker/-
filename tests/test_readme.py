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


if __name__ == "__main__":
    unittest.main()
