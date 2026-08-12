"""Documentation contract tests for the semantic gap decision loop."""

from pathlib import Path
import re
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOC_DIR = PROJECT_ROOT / "changes" / "产品实现层" / "语义缺口决策闭环"
REQUIRED_DOCS = (
    "proposal.md",
    "design.md",
    "Feature_Analysis_Report.md",
    "tasks.md",
)
TASK_SECTION_FIELDS = (
    "明确目标",
    "指定修改文件",
    "可独立测试",
    "完成标准",
)
BOUNDARY_PHRASES = (
    "不调用模型",
    "不写 Neo4j",
    "write_back=false",
    "candidate 不等于 formal",
)


class SemanticGapDocsTests(unittest.TestCase):
    def test_required_docs_exist(self):
        for name in REQUIRED_DOCS:
            with self.subTest(name=name):
                self.assertTrue((DOC_DIR / name).is_file(), name)

    def test_each_task_has_required_sections(self):
        tasks_text = (DOC_DIR / "tasks.md").read_text(encoding="utf-8")
        blocks = re.split(r"^## Task \d+：", tasks_text, flags=re.MULTILINE)
        task_blocks = [block for block in blocks[1:] if block.strip()]
        self.assertGreater(len(task_blocks), 0)
        for index, block in enumerate(task_blocks, start=1):
            for field in TASK_SECTION_FIELDS:
                with self.subTest(task=index, field=field):
                    self.assertIn(
                        field,
                        block,
                        f"Task {index} missing {field!r}",
                    )

    def test_docs_declare_core_boundaries(self):
        combined = "\n".join(
            (DOC_DIR / name).read_text(encoding="utf-8")
            for name in REQUIRED_DOCS
        )
        for phrase in BOUNDARY_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)

    def test_docs_do_not_claim_live_verification(self):
        for name in REQUIRED_DOCS:
            text = (DOC_DIR / name).read_text(encoding="utf-8")
            with self.subTest(name=name):
                self.assertNotIn("live Neo4j 验证通过", text)
                self.assertNotIn("live DashScope 验证通过", text)


if __name__ == "__main__":
    unittest.main()
