"""Documentation contract tests for the multimodal recognition productization."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLAN_DIR = ROOT / "changes" / "产品实现层" / "多模态识别产品化"


class MultimodalRecognitionDocsTests(unittest.TestCase):
    """The four plan documents exist and keep consistent boundaries."""

    def test_plan_documents_exist(self) -> None:
        for name in ("proposal.md", "design.md", "Feature_Analysis_Report.md", "tasks.md"):
            with self.subTest(name=name):
                self.assertTrue((PLAN_DIR / name).is_file())

    def test_proposal_declares_local_bbox_and_write_back_default(self) -> None:
        proposal = (PLAN_DIR / "proposal.md").read_text(encoding="utf-8")
        for phrase in ("局部 bbox", "write_back=false", "candidate 只能保持候选语义", "不引入 PaddleOCR"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, proposal)

    def test_design_declares_attempt_candidate_and_offline_contracts(self) -> None:
        design = (PLAN_DIR / "design.md").read_text(encoding="utf-8")
        for phrase in ("局部 bbox", "RecognitionAttempt", "candidate_relation", "离线合同测试", "实施状态"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, design)

    def test_tasks_cover_acceptance_and_candidate_boundary(self) -> None:
        tasks = (PLAN_DIR / "tasks.md").read_text(encoding="utf-8")
        for phrase in ("Task 43", "candidate_relation", "专项回归验收", "write_back=false"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, tasks)

    def test_feature_report_records_implementation_status(self) -> None:
        report = (PLAN_DIR / "Feature_Analysis_Report.md").read_text(encoding="utf-8")
        for phrase in ("实施状态", "candidate_relation", "离线单元/合同测试"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, report)

    def test_standard_docs_sync_recognition_execution_layer(self) -> None:
        architecture = (ROOT / "architecture.md").read_text(encoding="utf-8")
        module = (ROOT / "Module.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for phrase in ("多模态识别执行层", "candidate_relation", "未声称通过"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, architecture)
                self.assertIn(phrase, module)
                self.assertIn(phrase, readme)


if __name__ == "__main__":
    unittest.main()
