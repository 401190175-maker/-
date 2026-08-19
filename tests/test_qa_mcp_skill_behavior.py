import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = PROJECT_ROOT / ".codex" / "skills" / "drawing-graph-operator"


# 固定提示集：代表六类自然语言意图，每项对应 Skill 资料中的工具、
# QuestionType 与必需 scope ID。测试只读 Skill 文档，不调用模型或数据库。
ROUTE_PROMPTS = (
    ("看某页整体信息", "ask_drawing_page", "page_summary", "page_id"),
    ("看图块关系", "ask_drawing_block", "block_relations", "block_id"),
    ("看候选关系", "list_drawing_candidates", "candidate_relations", "page_id"),
    ("看断面匹配", "get_section_match_status", "section_matches", "cross_section_id"),
    ("看表格/表题状态", "get_table_caption_status", "table_caption_status", "table_caption_id"),
    ("排查页面或图块", "get_drawing_diagnostics", "diagnostic_status", "page_id"),
)


class DrawingGraphSkillRoutingBehaviorTests(unittest.TestCase):
    """Task 41: Skill docs must route fixed prompts safely and layer facts."""

    def setUp(self):
        self.qa = (SKILL_DIR / "references/qa-workflows.md").read_text(encoding="utf-8")
        self.boundaries = (SKILL_DIR / "references/mcp-boundaries.md").read_text(encoding="utf-8")
        self.output = (SKILL_DIR / "references/output-contract.md").read_text(encoding="utf-8")
        self.verification = (SKILL_DIR / "references/verification.md").read_text(encoding="utf-8")
        self.product = (SKILL_DIR / "references/product-test-workflows.md").read_text(encoding="utf-8")
        self.skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

    def test_six_intent_prompts_route_to_six_tools(self):
        for intent, tool, question_type, required_id in ROUTE_PROMPTS:
            with self.subTest(intent=intent):
                self.assertIn(intent, self.qa)
                self.assertIn(tool, self.qa)
                self.assertIn(question_type, self.qa)
                self.assertIn(required_id, self.qa)

    def test_missing_id_requires_asking_user_not_guessing(self):
        for phrase in ("询问用户", "不猜测", "不扩大 scope", "不扩大到全库"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.qa)

    def test_mcp_unavailable_falls_back_transparently_to_readonly_cli(self):
        for phrase in (
            "MCP 未成功使用",
            "QA CLI",
            "write_back=false",
            "不把 CLI 结果标记为 MCP 已验证",
            "禁止静默降级",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.boundaries)

    def test_candidate_is_not_formal_in_output_contract(self):
        for phrase in ("candidate_relation", "formal_relation", "正式图谱关系"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.output)

    def test_partial_is_not_complete_in_output_contract(self):
        for phrase in ("partial", "不能伪装为完整成功", "unsupported_parts"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.output)

    def test_smoke_does_not_prove_live_neo4j(self):
        for phrase in ("STDIO smoke", "不能证明 live Neo4j", "未验证"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.verification)

    def test_product_natural_language_tests_route_to_product_assistant_tool(self):
        for phrase in (
            "ask_drawing_assistant",
            "DrawingAssistantService.answer()",
            "scripts/drawing_assistant.py",
            "write_back=false",
            "不得写成 MCP 已验证",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.product)


if __name__ == "__main__":
    unittest.main()
