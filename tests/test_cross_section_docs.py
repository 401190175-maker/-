from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CrossSectionDocsTest(unittest.TestCase):
    def setUp(self):
        self.architecture = (ROOT / "architecture.md").read_text(encoding="utf-8")
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")

    def test_architecture_registers_section_mark_as_current_offline_enrichment(self):
        self.assertIn(
            "离线派生关系增强流程：在页面级图谱已经入库后显式运行，为 `Table` 补写表格标题关系，为 `DrawingPage` 补写基础信息上下文关系，并为 `DrawingBlock` 补写标题、注释、cross section 几何归属正式关系或空间候选关系。",
            self.architecture,
        )
        self.assertIn("DrawingBlock -[:HAS_SECTION_MARK]-> CrossSection", self.architecture)
        self.assertIn("DrawingPage -[:USES_BASIC_INFO]-> DrawingBasicInfo", self.architecture)
        self.assertIn("BlockCaption -[:CANDIDATE_CAPTION_OF]-> DrawingBlock", self.architecture)
        self.assertIn("DrawingBlock -[:CANDIDATE_HAS_SECTION_MARK]-> CrossSection", self.architecture)
        self.assertIn("候选关系 AI 复核是独立显式流程", self.architecture)
        self.assertIn("`section_mark_ids`", self.architecture)
        self.assertNotIn("不建立 `DrawingBlock -[:HAS_SECTION_MARK]-> CrossSection`", self.architecture)

    def test_architecture_registers_semantic_section_caption_match_boundaries(self):
        self.assertIn("`MATCHES_SECTION_CAPTION`", self.architecture)
        self.assertIn("`CANDIDATE_MATCHES_SECTION_CAPTION`", self.architecture)
        self.assertIn("只有在双方存在可比较 `TextObservation`", self.architecture)
        self.assertIn("不做 OCR", self.architecture)
        self.assertIn("不实现 Agent Skill", self.architecture)
        self.assertIn("不提供 HTTP 写回、任意 Cypher HTTP 接口或 MCP Tool adapter", self.architecture)
        self.assertIn("不建立 `NEAR` 空间关系网络", self.architecture)
        self.assertIn("不生成或推断 `block_type`", self.architecture)

    def test_standard_docs_register_cross_section_rule_interfaces_data_and_architecture(self):
        required_phrases = [
            "`enrich_cross_sections(scope, page)`",
            "`RelationRepository.read_pages(scope, limit=100)`",
            "`get_block_relations(block_id)`：查询单个图块的 `caption_ids`、`basic_info_ids`、`basic_info_status`、`basic_info_source`、`annotation_ids`、`section_mark_ids`、`candidate_caption_ids`、`candidate_section_mark_ids` 和 `relation_status`。",
            "`DrawingBlock -[:HAS_SECTION_MARK]-> CrossSection`",
            "`DrawingPage -[:USES_BASIC_INFO]-> DrawingBasicInfo`",
            "`BlockCaption -[:CANDIDATE_CAPTION_OF]-> DrawingBlock`",
            "`DrawingBlock -[:CANDIDATE_HAS_SECTION_MARK]-> CrossSection`",
            "`overlap_area`",
            "`overlap_ratio`",
            "`containment_status`",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.architecture)

    def test_standard_docs_boundary_excludes_deferred_or_unsupported_capabilities(self):
        self.assertIn("只有在双方存在可比较 `TextObservation`", self.readme)
        self.assertIn("不跨页面自动匹配断面", self.readme)
        self.assertIn("不返回 OCR 文本", self.readme)
        self.assertIn("不返回 Agent 推理字段", self.readme)
        self.assertIn("不提供 HTTP API", self.readme)
        self.assertIn("不新增 HTTP 写回或 `NEAR` 空间关系", self.readme)
        self.assertIn("不设置或推断 `DrawingBlock.block_type`", self.readme)


if __name__ == "__main__":
    unittest.main()
