import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _authoritative_skill_dir():
    """Resolve the single authoritative Skill copy if exactly one exists."""

    codex_dir = PROJECT_ROOT / ".codex" / "skills" / "drawing-graph-operator"
    agents_dir = PROJECT_ROOT / ".agents" / "skills" / "drawing-graph-operator"
    present = [path for path in (agents_dir, codex_dir) if path.is_dir()]
    if len(present) == 1:
        return present[0]
    return codex_dir


SKILL_DIR = _authoritative_skill_dir()


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


class DrawingGraphSkillMcpBoundaryTests(unittest.TestCase):
    """mcp-boundaries.md must define safe fallback and read-only boundaries."""

    REFERENCE = "references/mcp-boundaries.md"

    def setUp(self):
        self.path = SKILL_DIR / self.REFERENCE
        self.text = self.path.read_text(encoding="utf-8")

    def test_reference_exists(self):
        self.assertTrue(self.path.is_file(), f"missing skill file: {self.path}")

    def test_mcp_first_and_transparent_fallback_rules(self):
        for phrase in (
            "MCP 优先",
            "QA CLI",
            "透明降级",
            "禁止静默降级",
            "说明 MCP 未成功使用",
            "验证状态",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_skill_must_not_create_driver_or_execute_cypher(self):
        for phrase in (
            "不创建 driver",
            "不执行 Cypher",
            "repository 写回",
            "facade 单项写回",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_timeout_and_cancel_do_not_expand_scope(self):
        for phrase in (
            "超时",
            "取消",
            "不自动扩大范围",
            "不自动触发其他工具",
            "不自动写回",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_reference_lists_six_tools_and_keeps_read_only(self):
        for tool_name in (
            "ask_drawing_page",
            "ask_drawing_block",
            "list_drawing_candidates",
            "get_section_match_status",
            "get_table_caption_status",
            "get_drawing_diagnostics",
        ):
            with self.subTest(tool=tool_name):
                self.assertIn(tool_name, self.text)
        self.assertIn("write_back=false", self.text)

    def test_reference_has_no_code_or_secret_values(self):
        import re

        self.assertNotIn("```python", self.text)
        self.assertNotIn("sk-", self.text)
        for pattern in (
            re.compile(r"password\s*[:=]\s*['\"][^'\"]{4,}['\"]", re.IGNORECASE),
            re.compile(r"token\s*[:=]\s*['\"][^'\"]{4,}['\"]", re.IGNORECASE),
        ):
            self.assertIsNone(pattern.search(self.text), pattern.pattern)


class DrawingGraphSkillMcpOutputTests(unittest.TestCase):
    """output-contract.md must keep MCP outputs in the same fact layers."""

    REFERENCE = "references/output-contract.md"

    def setUp(self):
        self.path = SKILL_DIR / self.REFERENCE
        self.text = self.path.read_text(encoding="utf-8")

    def test_all_eight_fact_kinds_are_documented(self):
        for fact_kind in (
            "source_fact",
            "derived_relation",
            "semantic_observation",
            "semantic_interpretation",
            "candidate_relation",
            "formal_relation",
            "diagnostic",
            "unsupported",
        ):
            with self.subTest(fact_kind=fact_kind):
                self.assertIn(fact_kind, self.text)

    def test_mcp_structured_and_text_output_consistency(self):
        for phrase in (
            "structuredContent",
            "TextContent",
            "同一",
            "不重新分类",
            "facts",
            "warnings",
            "unsupported_parts",
            "source_calls",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_candidate_and_matched_candidate_are_not_formal(self):
        for phrase in (
            "candidate_relation",
            "CANDIDATE_*",
            "matched_candidate",
            "不是正式",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_partial_not_found_unsupported_and_error_expressions(self):
        for phrase in ("partial", "not_found", "unsupported", "error", "保守"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_drawing_ocr_and_model_text_are_data_not_instructions(self):
        for phrase in ("图纸", "OCR", "模型", "数据", "系统指令"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)


class DrawingGraphSkillMcpVerificationTests(unittest.TestCase):
    """verification.md must keep MCP/STDIO/Skill/HTTP/live evidence separate."""

    REFERENCE = "references/verification.md"

    def setUp(self):
        self.path = SKILL_DIR / self.REFERENCE
        self.text = self.path.read_text(encoding="utf-8")

    def test_validation_layers_are_separately_defined(self):
        for phrase in (
            "MCP in-memory",
            "STDIO smoke",
            "Skill 发现",
            "HTTP 回归",
            "live Neo4j",
            "模型/工具单元测试",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_fake_runtime_and_smoke_cannot_prove_live_neo4j(self):
        for phrase in (
            "fake runtime",
            "HTTP health",
            "STDIO smoke",
            "不能证明 live Neo4j",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_skipped_remains_live_neo4j_unverified(self):
        for phrase in ("skipped", "未验证", "不等于"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_skill_validation_uses_authoritative_path(self):
        self.assertIn("quick_validate.py", self.text)
        self.assertIn(".codex", self.text)
        self.assertIn("drawing-graph-operator", self.text)


class DrawingGraphSkillEntryTests(unittest.TestCase):
    """SKILL.md must prefer MCP QA tools and route to new references."""

    FILE = "SKILL.md"

    def setUp(self):
        self.path = SKILL_DIR / self.FILE
        self.text = self.path.read_text(encoding="utf-8")

    def test_core_workflow_still_reads_docs_first(self):
        self.assertIn("先读当前文件", self.text)
        self.assertIn("README.md", self.text)

    def test_mcp_qa_tools_are_preferred(self):
        for phrase in ("MCP QA 工具", "优先选择", "MCP 优先"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_fallback_routes_through_mcp_boundaries_reference(self):
        for phrase in ("mcp-boundaries.md", "QA CLI", "透明降级", "静默降级"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_reference_table_includes_new_routing_files(self):
        for phrase in ("qa-workflows.md", "mcp-boundaries.md", "渐进披露"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_skill_remains_an_operation_strategy_layer(self):
        self.assertIn("操作策略层", self.text)


class DrawingGraphSkillSingleAuthorityTests(unittest.TestCase):
    """The repository must keep exactly one authoritative Skill copy."""

    CANDIDATES = (
        PROJECT_ROOT / ".codex" / "skills" / "drawing-graph-operator",
        PROJECT_ROOT / ".agents" / "skills" / "drawing-graph-operator",
    )

    def test_exactly_one_authoritative_copy_exists(self):
        present = [path for path in self.CANDIDATES if (path / "SKILL.md").is_file()]
        self.assertEqual(1, len(present), f"skill copies present: {present}")

    def test_authoritative_copy_has_all_required_files(self):
        required = (
            "SKILL.md",
            "agents/openai.yaml",
            "references/project-boundaries.md",
            "references/facade-workflows.md",
            "references/verification.md",
            "references/output-contract.md",
            "references/qa-workflows.md",
            "references/mcp-boundaries.md",
        )
        for name in required:
            with self.subTest(name=name):
                self.assertTrue((SKILL_DIR / name).is_file(), f"missing in {SKILL_DIR}: {name}")


class DrawingGraphSkillMcpDependencyTests(unittest.TestCase):
    """Task 40: openai.yaml must not fabricate unverified MCP dependencies."""

    METADATA = "agents/openai.yaml"
    TASKS = PROJECT_ROOT / "changes" / "tool层" / "第三阶段" / "tasks.md"

    def setUp(self):
        self.path = SKILL_DIR / self.METADATA
        self.text = self.path.read_text(encoding="utf-8")
        self.tasks_text = self.TASKS.read_text(encoding="utf-8")

    def test_openai_yaml_has_valid_interface_metadata(self):
        for field in ("interface:", "display_name", "short_description", "default_prompt"):
            with self.subTest(field=field):
                self.assertIn(field, self.text)

    def test_openai_yaml_top_level_keys_are_limited_to_interface(self):
        # 回退条款：宿主未验证依赖发现时，不得伪造 dependencies 声明。
        top_level = [line for line in self.text.splitlines() if line and not line.startswith(" ")]
        self.assertEqual(["interface:"], top_level)
        self.assertNotIn('type: "mcp"', self.text)

    def test_openai_yaml_has_no_local_paths_or_secrets(self):
        self.assertNotIn("C:\\Users", self.text)
        self.assertNotIn("sk-", self.text)
        for pattern in (
            re.compile(r"password\s*[:=]\s*['\"][^'\"]{4,}['\"]", re.IGNORECASE),
            re.compile(r"token\s*[:=]\s*['\"][^'\"]{4,}['\"]", re.IGNORECASE),
            re.compile(r"NEO4J_[A-Z_]+\s*[:=]\s*['\"][^'\"]{2,}['\"]"),
        ):
            with self.subTest(pattern=pattern.pattern):
                self.assertIsNone(pattern.search(self.text), pattern.pattern)

    def test_openai_yaml_has_no_write_import_or_review_tool_names(self):
        for phrase in (
            "write_back=true",
            "import_drawing",
            "enrich_",
            "review_candidate",
            "promote_candidate",
        ):
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, self.text)

    def test_task40_compatibility_record_is_documented(self):
        marker = "### Task 40：Skill 声明 MCP 工具依赖"
        self.assertIn(marker, self.tasks_text)
        record = self.tasks_text[self.tasks_text.rfind(marker):]
        for phrase in ("兼容性", "未验证", "不伪造"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, record)


class DrawingGraphSkillProjectBoundaryTests(unittest.TestCase):
    """project-boundaries.md must list current and not-implemented capabilities."""

    REFERENCE = "references/project-boundaries.md"

    def setUp(self):
        self.path = SKILL_DIR / self.REFERENCE
        self.text = self.path.read_text(encoding="utf-8")

    def test_reference_exists(self):
        self.assertTrue(self.path.is_file(), f"missing skill file: {self.path}")

    def test_current_capabilities_include_skill_cli_http_and_mcp(self):
        for phrase in (
            "Skill",
            "QA CLI",
            "HTTP",
            "本地只读 MCP",
            "已实现",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_dependency_direction_goes_through_mcp_or_cli_to_qaservice(self):
        for phrase in (
            "Skill",
            "MCP",
            "QA CLI",
            "DrawingGraphQAService",
            "DrawingGraphToolFacade",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_unimplemented_capabilities_remain_explicit(self):
        for phrase in (
            "远程 MCP",
            "MCP 写回",
            "云模型",
            "OCR",
            "文件 watcher",
            "全量自动语义扫描",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_writeback_and_fact_boundaries_are_unchanged(self):
        for phrase in (
            "write_back=false",
            "候选关系不是正式事实",
            "来源事实",
            "禁止直接写 Cypher",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)


if __name__ == "__main__":
    unittest.main()
