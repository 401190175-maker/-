import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = PROJECT_ROOT / ".codex" / "skills" / "drawing-graph-operator"

DOC_PATHS = {
    "readme": PROJECT_ROOT / "README.md",
    "module": PROJECT_ROOT / "Module.md",
    "architecture": PROJECT_ROOT / "architecture.md",
}

SKILL_REFERENCE_PATHS = (
    "SKILL.md",
    "references/qa-workflows.md",
    "references/mcp-boundaries.md",
    "references/output-contract.md",
    "references/verification.md",
    "references/project-boundaries.md",
)

TOOL_NAMES = (
    "ask_drawing_page",
    "ask_drawing_block",
    "list_drawing_candidates",
    "get_section_match_status",
    "get_table_caption_status",
    "get_drawing_diagnostics",
)


class ThirdPhaseDocConsistencyTests(unittest.TestCase):
    """Task 46: third-phase docs must agree on tools, boundaries and status."""

    def setUp(self):
        self.docs = {
            name: path.read_text(encoding="utf-8")
            for name, path in DOC_PATHS.items()
        }
        self.skill_docs = {
            name: (SKILL_DIR / name).read_text(encoding="utf-8")
            for name in SKILL_REFERENCE_PATHS
        }

    def test_six_tools_consistent_across_readme_module_and_skill(self):
        for tool in TOOL_NAMES:
            with self.subTest(tool=tool):
                self.assertIn(tool, self.docs["readme"])
                self.assertIn(tool, self.docs["module"])
                self.assertTrue(
                    any(tool in text for text in self.skill_docs.values()),
                    f"{tool} missing from every Skill reference",
                )

    def test_stable_dependency_direction_is_consistent(self):
        phrase = "MCP adapter -> DrawingGraphQAService -> DrawingGraphToolFacade"
        for name, text in self.docs.items():
            with self.subTest(name=name):
                self.assertIn(phrase, text)

    def test_readonly_stdio_and_first_version_are_consistent(self):
        for name, text in self.docs.items():
            with self.subTest(name=name):
                self.assertIn("只读", text)
                self.assertIn("STDIO", text)
        self.assertIn("首版", self.docs["readme"])
        self.assertIn("首版", self.docs["module"])
        self.assertIn("首版", self.skill_docs["references/mcp-boundaries.md"])

    def test_candidate_not_formal_and_skipped_not_live(self):
        for name, text in self.docs.items():
            with self.subTest(name=name):
                self.assertIn("不是正式事实", text)
                self.assertIn("不等于 live Neo4j 验证", text)
        self.assertIn("skipped", self.skill_docs["references/verification.md"])
        self.assertIn("正式图谱关系", self.skill_docs["references/output-contract.md"])

    def test_unimplemented_remote_features_remain_marked(self):
        for phrase in ("Streamable HTTP", "OAuth", "远程"):
            for name, text in self.docs.items():
                with self.subTest(name=name, phrase=phrase):
                    self.assertIn(phrase, text)
        self.assertIn("plugin 发布", self.docs["module"])
        self.assertIn("plugin 发布", self.docs["architecture"])
        self.assertIn("插件发布", self.docs["readme"])
        for name, text in self.docs.items():
            with self.subTest(name=name):
                self.assertIn("未实现", text)

    def test_skill_has_single_authority_and_docs_have_no_machine_paths(self):
        candidates = (
            PROJECT_ROOT / ".codex" / "skills" / "drawing-graph-operator",
            PROJECT_ROOT / ".agents" / "skills" / "drawing-graph-operator",
        )
        present = [path for path in candidates if (path / "SKILL.md").is_file()]
        self.assertEqual(1, len(present), f"skill copies present: {present}")
        for name, text in {**self.docs, **self.skill_docs}.items():
            with self.subTest(name=name):
                self.assertNotIn("C:\\Users", text)


if __name__ == "__main__":
    unittest.main()
