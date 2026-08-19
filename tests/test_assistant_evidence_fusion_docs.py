"""Documentation contract tests for the 05 evidence fusion layer."""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CHANGE_DIR = ROOT / "changes" / "产品实现层" / "证据融合与缓存闭环"

FUSION_BOUNDARY_PHRASES = (
    "默认 `write_back=false`",
    "`candidate` 不等于 formal",
    "不新增外部 API",
    "不调用模型",
    "不查询 Neo4j",
)

FOUR_KEY_PHRASES = (
    "`cache_key` 只用于精确复用",
    "`evidence_family_key` 只用于 lineage/stale",
    "`comparison_key` 只用于可比证据分组",
    "`content_fingerprint` 只用于确定性去重",
)


class FusionDocsTests(unittest.TestCase):
    def setUp(self):
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.module_doc = (ROOT / "Module.md").read_text(encoding="utf-8")
        self.architecture = (ROOT / "architecture.md").read_text(encoding="utf-8")

    def test_root_docs_record_fusion_layer(self):
        self.assertIn("证据融合与缓存闭环（05）", self.readme)
        self.assertIn("05 证据融合与缓存闭环模块", self.module_doc)
        self.assertIn("05 证据融合与缓存闭环", self.architecture)

    def test_root_docs_lock_default_read_only_and_key_separation(self):
        for doc in (self.readme, self.module_doc, self.architecture):
            for phrase in FUSION_BOUNDARY_PHRASES:
                with self.subTest(phrase=phrase):
                    self.assertIn(phrase, doc)
        for phrase in FOUR_KEY_PHRASES:
            self.assertIn(phrase, self.readme)

    def test_root_docs_record_06_07_consumers_without_expanding_fusion_boundaries(self):
        # 06/07 已消费 05 输出，但不能反向扩大 05 的模型、查询或外部 API 边界。
        self.assertIn("06/07 已在后续 MVP 中消费本层 `EvidenceBundle`", self.readme)
        self.assertIn("06/07 已消费 05 的 `EvidenceBundle`", self.module_doc)
        self.assertIn("06/07 已消费 05 的 `EvidenceBundle`", self.architecture)
        for doc in (self.readme, self.module_doc, self.architecture):
            self.assertIn("不新增外部 API", doc)
            self.assertNotIn("完整 DrawingAssistantService 尚未实现", doc)

    def test_change_docs_mark_implemented(self):
        proposal = (CHANGE_DIR / "proposal.md").read_text(encoding="utf-8")
        design = (CHANGE_DIR / "design.md").read_text(encoding="utf-8")
        report = (CHANGE_DIR / "Feature_Analysis_Report.md").read_text(encoding="utf-8")
        self.assertIn("已实施", proposal)
        self.assertIn("已实施", design)
        self.assertIn("已实施", report)

    def test_change_docs_lock_fact_kind_invariants(self):
        design = (CHANGE_DIR / "design.md").read_text(encoding="utf-8")
        self.assertIn("candidate", design)
        self.assertIn("formal", design)
        self.assertIn("fact_kind", design)
        self.assertIn("CandidateReviewService", design)
        self.assertIn("不新增外部 API", design)


if __name__ == "__main__":
    unittest.main()
