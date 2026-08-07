from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SemanticDocsTest(unittest.TestCase):
    def setUp(self):
        self.architecture = (ROOT / "architecture.md").read_text(encoding="utf-8")
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.module = (ROOT / "Module.md").read_text(encoding="utf-8")
        self.design = (ROOT / "changes" / "语义证据层" / "design.md").read_text(encoding="utf-8")

    def test_docs_record_semantic_evidence_boundaries(self):
        for phrase in (
            "`RecognitionRun` 图谱外",
            "`TextObservation` 图谱内",
            "write_back=false",
            "dry-run",
            "候选关系不是正式事实",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.architecture)
                self.assertIn(phrase, self.readme)
                self.assertIn(phrase, self.module)

    def test_docs_do_not_claim_unimplemented_capabilities(self):
        forbidden_claims = (
            "HTTP API 已完成",
            "Agent Skill 已完成",
            "MCP Tool adapter 已完成",
            "全量自动语义扫描已完成",
            "默认真实云模型调用已完成",
        )
        all_docs = "\n".join((self.architecture, self.readme, self.module, self.design))
        for phrase in forbidden_claims:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, all_docs)

    def test_docs_report_neo4j_integration_boundary(self):
        self.assertIn("跳过不等于通过", self.readme)
        self.assertIn("跳过不等于通过", self.design)
        self.assertIn("NEO4J_TEST_URI", self.module)

    def test_design_records_current_implementation_status(self):
        self.assertIn("## 10. 当前实现状态", self.design)
        self.assertIn("尚未实现", self.design)
        self.assertIn("SemanticNeo4jRepository", self.design)

    def test_module_registers_semantic_layer_modules(self):
        for module_name in (
            "semantic_cache.py",
            "semantic_payload_store.py",
            "semantic_image_inputs.py",
            "semantic_neo4j_repository.py",
            "semantic_query_projection.py",
            "section_label_normalization.py",
            "section_alias_rules.py",
            "section_match_service.py",
        ):
            with self.subTest(module_name=module_name):
                self.assertIn(module_name, self.module)

    def test_docs_register_guarded_section_match_rule(self):
        guarded_phrase = "只有在双方存在可比较 `TextObservation`"
        self.assertIn(guarded_phrase, self.architecture)
        self.assertIn(guarded_phrase, self.readme)
        self.assertIn("CANDIDATE_MATCHES_SECTION_CAPTION", self.module)


if __name__ == "__main__":
    unittest.main()
