import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = PROJECT_ROOT / ".codex" / "skills" / "drawing-graph-operator"


class SkillDocsTest(unittest.TestCase):
    """Static boundary tests for the drawing-graph-operator Codex Skill.

    The tests only read Skill document files. They never connect to Neo4j,
    never call a real cloud model, and never run import or enrichment scripts.
    """

    REQUIRED_FILES = (
        "SKILL.md",
        "agents/openai.yaml",
        "references/project-boundaries.md",
        "references/facade-workflows.md",
        "references/verification.md",
        "references/output-contract.md",
    )

    def setUp(self):
        self.paths = {name: SKILL_DIR / name for name in self.REQUIRED_FILES}
        self.docs = {name: path.read_text(encoding="utf-8") for name, path in self.paths.items()}
        self.all_docs = "\n".join(self.docs.values())

    def test_skill_files_exist(self):
        for name, path in self.paths.items():
            with self.subTest(name=name):
                self.assertTrue(path.is_file(), f"missing skill file: {path}")

    def test_skill_frontmatter_and_ui_metadata(self):
        self.assertIn("name: drawing-graph-operator", self.docs["SKILL.md"])
        self.assertIn("description:", self.docs["SKILL.md"])
        for phrase in ("图块图谱", "DrawingGraphToolFacade", "write_back"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.docs["SKILL.md"])
        openai = self.docs["agents/openai.yaml"]
        for field in ("display_name", "short_description", "default_prompt"):
            with self.subTest(field=field):
                self.assertIn(field, openai)

    def test_skill_docs_contain_core_terms(self):
        for phrase in (
            "DrawingGraphToolFacade",
            "write_back=false",
            "candidate_relation",
            "formal_relation",
            "RecognitionRun",
            "TextObservation",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.all_docs)

    def test_skill_docs_contain_boundary_statements(self):
        for phrase in (
            "不封装 data",
            "不保存密钥",
            "不直接写 Cypher",
            "MCP Tool adapter",
            "HTTP API",
            "文件 watcher",
            "不把候选关系",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.all_docs)

    def test_skill_docs_do_not_contain_secret_values(self):
        secret_patterns = (
            re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
            re.compile(r"api_key\s*[:=]\s*['\"][^'\"]{8,}['\"]", re.IGNORECASE),
            re.compile(r"NEO4J_(TEST_)?PASSWORD\s*[:=]\s*['\"](?![<>])[^'\"]{6,}['\"]"),
        )
        for pattern in secret_patterns:
            for name, text in self.docs.items():
                with self.subTest(pattern=pattern.pattern, name=name):
                    self.assertIsNone(pattern.search(text), f"possible secret value in {name}")

    def test_skill_docs_do_not_bundle_real_data_paths(self):
        forbidden = (
            "\\data\\",
            "/data/",
            "C:\\Users",
        )
        for phrase in forbidden:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, self.all_docs)


class DrawingGraphSkillQaWorkflowTests(unittest.TestCase):
    """qa-workflows.md must map six intents to MCP tools and QA types."""

    REFERENCE = "references/qa-workflows.md"

    def setUp(self):
        self.path = SKILL_DIR / self.REFERENCE
        self.text = self.path.read_text(encoding="utf-8")

    def test_reference_exists(self):
        self.assertTrue(self.path.is_file(), f"missing skill file: {self.path}")

    def test_six_tools_and_question_types_are_mapped(self):
        expected = {
            "ask_drawing_page": "page_summary",
            "ask_drawing_block": "block_relations",
            "list_drawing_candidates": "candidate_relations",
            "get_section_match_status": "section_matches",
            "get_table_caption_status": "table_caption_status",
            "get_drawing_diagnostics": "diagnostic_status",
        }
        for tool_name, question_type in expected.items():
            with self.subTest(tool=tool_name):
                self.assertIn(tool_name, self.text)
                self.assertIn(question_type, self.text)

    def test_required_ids_and_mutually_exclusive_scopes_are_documented(self):
        for phrase in (
            "page_id",
            "block_id",
            "cross_section_id",
            "table_caption_id",
            "互斥",
            "只能提供一个",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_multi_intent_and_missing_id_rules_are_documented(self):
        for phrase in (
            "拆分",
            "缺少",
            "询问用户",
            "不猜测",
            "不扩大到全库",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_partial_results_cannot_be_merged_into_formal_conclusion(self):
        self.assertIn("partial", self.text)
        self.assertIn("不能拼接", self.text)

    def test_reference_does_not_contain_code_secrets_or_cypher(self):
        import re

        self.assertNotIn("```python", self.text)
        self.assertNotIn("sk-", self.text)
        for pattern in (
            re.compile(r"password\s*[:=]\s*['\"][^'\"]{4,}['\"]", re.IGNORECASE),
            re.compile(r"token\s*[:=]\s*['\"][^'\"]{4,}['\"]", re.IGNORECASE),
            re.compile(r"api[_-]?key\s*[:=]\s*['\"][^'\"]{4,}['\"]", re.IGNORECASE),
        ):
            self.assertIsNone(pattern.search(self.text), pattern.pattern)


if __name__ == "__main__":
    unittest.main()
