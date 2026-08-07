import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class E2eCliDocsTest(unittest.TestCase):
    def setUp(self):
        acceptance_root = ROOT / "docs" / "acceptance"
        self.acceptance = (acceptance_root / "E2E_CLI_ACCEPTANCE.md").read_text(encoding="utf-8")
        self.full_acceptance = (acceptance_root / "FULL_DATA_ACCEPTANCE.md").read_text(encoding="utf-8")
        self.runbook = (acceptance_root / "USER_RUNBOOK.md").read_text(encoding="utf-8")
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.module = (ROOT / "Module.md").read_text(encoding="utf-8")

    def test_acceptance_record_captures_real_cli_chain_and_boundaries(self):
        required_phrases = (
            "e2e-cli-20260806172326",
            "scripts\\import_json.py page",
            "scripts\\enrich_block_relations.py page",
            "scripts\\drawing_graph_tool.py page-source-facts",
            "scripts\\drawing_graph_tool.py list-candidate-relations",
            "scripts\\drawing_graph_tool.py list-section-matches",
            "partial",
            "table_caption_relation_count: 1",
            "basic_info_not_evaluated",
            "不清理 Neo4j 验收数据",
        )
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.acceptance)

    def test_full_data_acceptance_records_scale_and_boundaries(self):
        required_phrases = (
            "road-full-20260807-acceptance",
            "333 个 JSON、333 个 PNG",
            "success_count: 333",
            "skipped_count: 0",
            "failed_count: 0",
            "lslq_yhd_2_1 -> 103",
            "lslq_yhd_2_2 -> 230",
            "Ran 529 tests",
            "OK",
            "未接真实多模态模型供应商",
        )
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.full_acceptance)
        self.assertNotIn("kadxj", self.full_acceptance.lower())

    def test_runbook_has_user_level_commands_without_real_secrets(self):
        required_phrases = (
            "最短运行流程",
            "NEO4J_PASSWORD",
            "<your-password>",
            "scripts\\create_schema.cypher",
            "python scripts\\import_json.py",
            "python scripts\\enrich_block_relations.py",
            "python scripts\\drawing_graph_tool.py",
            "Neo4j Browser",
            "bolt://127.0.0.1:7687",
            "http://localhost:7474/browser/",
        )
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.runbook)
        self.assertNotIn("kadxj", self.runbook.lower())
        self.assertNotIn("NEO4J_PASSWORD='", self.runbook)

    def test_standard_docs_link_to_acceptance_and_runbook(self):
        for doc_name in (
            "docs/acceptance/E2E_CLI_ACCEPTANCE.md",
            "docs/acceptance/FULL_DATA_ACCEPTANCE.md",
            "docs/acceptance/USER_RUNBOOK.md",
        ):
            with self.subTest(doc_name=doc_name):
                self.assertIn(doc_name, self.readme)
                self.assertIn(doc_name, self.module)


if __name__ == "__main__":
    unittest.main()
