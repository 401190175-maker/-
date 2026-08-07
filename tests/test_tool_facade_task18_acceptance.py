import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ToolFacadeTask18AcceptanceTest(unittest.TestCase):
    def test_task18_records_regression_and_boundary_status(self):
        tasks = (ROOT / "changes" / "tool-facade" / "tasks.md").read_text(encoding="utf-8")

        for phrase in (
            "Task 18 验收记录",
            "python -m unittest discover tests -v",
            "NEO4J_TEST_URI",
            "跳过不等于通过",
            "ImportService",
            "RelationEnrichmentService",
            "没有新增 HTTP API",
            "没有新增 Agent Skill",
            "没有默认调用真实云模型",
            "没有新增全量自动语义扫描",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, tasks)


if __name__ == "__main__":
    unittest.main()
