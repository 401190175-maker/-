from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ModuleDocsTest(unittest.TestCase):
    def setUp(self):
        module_path = ROOT / "Module.md"
        if not module_path.exists():
            self.fail("missing module document: Module.md")
        self.module_doc = module_path.read_text(encoding="utf-8")
        self.architecture = (ROOT / "architecture.md").read_text(encoding="utf-8")
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")

    def test_module_document_records_required_sections(self):
        for heading in (
            "## 1. 新模块职责",
            "## 2. 新接口",
            "## 3. 新依赖",
            "## 4. 数据变化",
            "## 5. 架构变化",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, self.module_doc)

    def test_module_document_matches_current_code_boundaries(self):
        for phrase in (
            "src/drawing_graph/block_relation_enrichment.py",
            "src/drawing_graph/relation_repository.py",
            "src/drawing_graph/relation_service.py",
            "src/drawing_graph/candidate_review.py",
            "scripts/review_candidate_relations.py",
            "RelationRepository.update_candidate_review",
            "RelationRepository.promote_candidate_relation",
            "CandidateReviewService.review_candidate_group",
            "DrawingPage -[:USES_BASIC_INFO]-> DrawingBasicInfo",
            "BlockCaption -[:CANDIDATE_CAPTION_OF]-> DrawingBlock",
            "DrawingBlock -[:CANDIDATE_HAS_SECTION_MARK]-> CrossSection",
            "review_run_id",
            "不自动触发候选关系 AI 复核",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.module_doc)

    def test_standard_docs_link_to_module_document(self):
        self.assertIn("Module.md", self.architecture)
        self.assertIn("Module.md", self.readme)


if __name__ == "__main__":
    unittest.main()
