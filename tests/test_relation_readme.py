import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
README_PATH = PROJECT_ROOT / "README.md"


class RelationReadmeTest(unittest.TestCase):
    def setUp(self):
        self.readme = README_PATH.read_text(encoding="utf-8")

    def test_documents_relation_enrichment_cli_scopes_and_rule_version(self):
        self.assertRegex(self.readme, r"python\s+scripts\\enrich_block_relations\.py\s+project\s+--rule-version")
        self.assertRegex(self.readme, r"python\s+scripts\\enrich_block_relations\.py\s+drawing-set\s+set:")
        self.assertRegex(self.readme, r"python\s+scripts\\enrich_block_relations\.py\s+page\s+page:")
        self.assertIn("规则版本", self.readme)
        self.assertIn("rule_version", self.readme)
        self.assertIn("relation_batch_id", self.readme)
        self.assertRegex(self.readme, r"python\s+scripts\\review_candidate_relations\.py\s+candidate-group")
        self.assertIn("review_run_id", self.readme)

    def test_documents_relation_status_and_query_interface(self):
        required_phrases = (
            "get_block_relations",
            "caption_ids",
            "basic_info_ids",
            "basic_info_status",
            "basic_info_source",
            "annotation_ids",
            "section_mark_ids",
            "candidate_caption_ids",
            "candidate_section_mark_ids",
            "relation_status",
            "not_enhanced",
            "enhanced",
            "partial",
            "candidate",
        )
        for phrase in required_phrases:
            self.assertIn(phrase, self.readme)

    def test_documents_derived_relation_rules_and_warning_categories(self):
        required_phrases = (
            "Table -[:HAS_CAPTION]-> TableCaption",
            "table_caption_bbox_distance_v1",
            "DrawingBlock -[:HAS_CAPTION]-> BlockCaption",
            "DrawingPage -[:USES_BASIC_INFO]-> DrawingBasicInfo",
            "DrawingBlock -[:HAS_ANNOTATION]-> DrawingAnnotation",
            "DrawingBlock -[:HAS_SECTION_MARK]-> CrossSection",
            "BlockCaption -[:CANDIDATE_CAPTION_OF]-> DrawingBlock",
            "DrawingBlock -[:CANDIDATE_HAS_SECTION_MARK]-> CrossSection",
            "table_count",
            "table_caption_count",
            "table_caption_relation_count",
            "uses_basic_info_count",
            "candidate_count",
            "ambiguous_count",
            "not_evaluated_count",
            "reviewing_count",
            "accepted_count",
            "rejected_count",
            "unresolved_count",
            "table_caption_invalid_input",
            "table_caption_legacy_conflict",
            "table_caption_write_failed",
            "caption_candidate_not_found",
            "caption_candidate_ambiguous",
            "basic_info_not_evaluated",
            "basic_info_partial",
            "basic_info_ambiguous",
            "annotation_not_found",
            "cross_section_unmatched",
            "section_candidate_ambiguous",
            "section_candidate_low_evidence",
            "section_mark_write_failed",
            "candidate_review_unavailable",
            "candidate_review_invalid_output",
            "candidate_promotion_rule_failed",
            "candidate_review_write_failed",
            "relation_write_failed",
        )
        for phrase in required_phrases:
            self.assertIn(phrase, self.readme)

    def test_documents_design_boundaries_and_keeps_secrets_out(self):
        for phrase in (
            "不做 OCR",
            "MATCHES_SECTION_CAPTION",
            "Agent Skill",
            "HTTP API",
            "NEAR",
            "block_type",
            "基础导入不会自动触发离线派生关系增强",
            "离线派生关系增强不会自动触发候选关系 AI 复核",
            "accepted",
            "rejected",
            "unresolved",
            "合法中间状态",
        ):
            self.assertIn(phrase, self.readme)

        suspicious_secret_patterns = (
            r"(?i)password\s*=\s*['\"][^<\s][^'\"]+['\"]",
            r"(?i)token\s*=\s*['\"][^<\s][^'\"]+['\"]",
            r"(?i)secret\s*=\s*['\"][^<\s][^'\"]+['\"]",
        )
        for pattern in suspicious_secret_patterns:
            self.assertIsNone(re.search(pattern, self.readme))


if __name__ == "__main__":
    unittest.main()
