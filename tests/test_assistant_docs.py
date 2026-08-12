"""Documentation contract tests for the product assistant layer."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PRODUCT_DOC_DIR = ROOT / "changes" / "产品实现层" / "产品公共合同与通用检索闭环"

PRODUCT_MODULE_NAMES = (
    "assistant_models.py",
    "assistant_retrieval_planner.py",
    "assistant_retrieval_executor.py",
    "assistant_retrieval_projection.py",
    "assistant_retrieval_service.py",
    "assistant_qa_mapping.py",
)

BOUNDARY_PHRASES = (
    "默认只读",
    "write_back=false",
    "不调用 Qwen",
    "不创建 RecognitionRun",
    "不写 Neo4j",
    "候选关系不是正式事实",
    "跳过不等于 live Neo4j 通过",
)


class AssistantDocsTests(unittest.TestCase):
    def setUp(self):
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.module_doc = (ROOT / "Module.md").read_text(encoding="utf-8")
        self.architecture = (ROOT / "architecture.md").read_text(encoding="utf-8")
        self.design = (PRODUCT_DOC_DIR / "design.md").read_text(encoding="utf-8")
        self.feature_report = (PRODUCT_DOC_DIR / "Feature_Analysis_Report.md").read_text(encoding="utf-8")

    def test_readme_documents_product_retrieval_boundaries(self):
        for phrase in BOUNDARY_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.readme)

    def test_readme_names_product_modules_and_does_not_claim_full_assistant(self):
        for name in ("GraphRetrievalService", "assistant_qa_mapping.py"):
            with self.subTest(name=name):
                self.assertIn(name, self.readme)
        self.assertIn("完整 DrawingAssistantService 尚未实现", self.readme)

    def test_module_doc_records_product_modules(self):
        for name in PRODUCT_MODULE_NAMES:
            with self.subTest(name=name):
                self.assertIn(f"src/drawing_graph/{name}", self.module_doc)
        for name in (
            "GraphRetrievalService",
            "RetrievalPlanner",
            "RetrievalExecutor",
            "RetrievalBundleBuilder",
        ):
            with self.subTest(name=name):
                self.assertIn(name, self.module_doc)

    def test_module_doc_declares_product_read_only_boundaries(self):
        for phrase in BOUNDARY_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.module_doc)

    def test_architecture_records_product_layer_chain_and_boundaries(self):
        self.assertIn("产品公共合同与通用检索闭环", self.architecture)
        self.assertIn("GraphRetrievalService", self.architecture)
        self.assertIn("DrawingAssistantService（后续完整产品编排，当前未实现）", self.architecture)
        for phrase in BOUNDARY_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.architecture)
        self.assertIn("tests/test_assistant_retrieval_boundaries.py", self.architecture)

    def test_design_frozen_module_names_match_implementation(self):
        for name in PRODUCT_MODULE_NAMES:
            with self.subTest(name=name):
                self.assertIn(f"已冻结模块名：`{name}`", self.design)

    def test_design_test_file_list_matches_implementation(self):
        for test_file in (
            "tests/test_assistant_models_contract.py",
            "tests/test_assistant_retrieval_planner.py",
            "tests/test_assistant_retrieval_executor.py",
            "tests/test_assistant_retrieval_projection.py",
            "tests/test_assistant_retrieval_service.py",
            "tests/test_assistant_qa_mapping.py",
            "tests/test_assistant_retrieval_boundaries.py",
            "tests/test_assistant_docs.py",
        ):
            with self.subTest(test_file=test_file):
                self.assertIn(test_file, self.design)

    def test_feature_report_names_match_implementation(self):
        for name in PRODUCT_MODULE_NAMES:
            with self.subTest(name=name):
                self.assertIn(name, self.feature_report)
        self.assertIn("实施命名已冻结", self.feature_report)


if __name__ == "__main__":
    unittest.main()
