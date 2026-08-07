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


if __name__ == "__main__":
    unittest.main()
