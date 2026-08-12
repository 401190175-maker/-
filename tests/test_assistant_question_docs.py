"""Documentation contract tests for the question understanding change set."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
DOC_DIR = ROOT / "changes" / "产品实现层" / "问题理解闭环"

BOUNDARY_PHRASES = (
    "不改 Neo4j schema",
    "不调用真实模型",
    "默认 write_back=false",
    "不访问 Neo4j",
    "不调用 `DrawingGraphToolFacade`",
    "不写数据库",
)


class QuestionUnderstandingDocsTests(unittest.TestCase):
    def test_proposal_design_tasks_exist(self):
        for name in ("proposal.md", "design.md", "tasks.md"):
            with self.subTest(name=name):
                self.assertTrue((DOC_DIR / name).is_file(), f"{name} must exist")

    def test_tasks_each_contain_goal_files_test_and_criteria(self):
        tasks_text = (DOC_DIR / "tasks.md").read_text(encoding="utf-8")
        task_blocks = re.split(r"\n## Task \d+：", tasks_text)[1:]
        self.assertGreaterEqual(len(task_blocks), 23)
        for block in task_blocks:
            for phrase in ("明确目标", "指定修改文件", "可独立测试", "完成标准"):
                self.assertIn(phrase, block)

    def test_documents_keep_project_boundaries(self):
        documents = tuple(
            (DOC_DIR / name).read_text(encoding="utf-8")
            for name in ("proposal.md", "design.md", "tasks.md")
        )
        for phrase in BOUNDARY_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertTrue(
                    any(phrase in text for text in documents),
                    f"{phrase} must appear in question-understanding docs",
                )


if __name__ == "__main__":
    unittest.main()
