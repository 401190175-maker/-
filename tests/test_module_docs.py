from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ModuleDocsTest(unittest.TestCase):
    def setUp(self):
        module_path = ROOT / "Module.md"
        if not module_path.exists():
            self.fail("missing module document: Module.md")
        self.module_doc = module_path.read_text(encoding="utf-8")
        self.architecture = (ROOT / "architecture.md").read_text(encoding="utf-8")
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")

    def test_module_document_records_required_sections(self):
        for heading in (
            "## 1. 新模块职责",
            "## 2. 新接口",
            "## 3. 新依赖",
            "## 4. 数据变化",
            "## 5. 架构变化",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, self.module_doc)

    def test_module_document_matches_current_code_boundaries(self):
        for phrase in (
            "src/drawing_graph/block_relation_enrichment.py",
            "src/drawing_graph/relation_repository.py",
            "src/drawing_graph/relation_service.py",
            "src/drawing_graph/candidate_review.py",
            "scripts/review_candidate_relations.py",
            "RelationRepository.update_candidate_review",
            "RelationRepository.promote_candidate_relation",
            "CandidateReviewService.review_candidate_group",
            "DrawingPage -[:USES_BASIC_INFO]-> DrawingBasicInfo",
            "BlockCaption -[:CANDIDATE_CAPTION_OF]-> DrawingBlock",
            "DrawingBlock -[:CANDIDATE_HAS_SECTION_MARK]-> CrossSection",
            "review_run_id",
            "不自动触发候选关系 AI 复核",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.module_doc)

    def test_standard_docs_link_to_module_document(self):
        self.assertIn("Module.md", self.architecture)
        self.assertIn("Module.md", self.readme)


class ModuleMcpDocsTest(unittest.TestCase):
    """Task 43: Module.md must record MCP module responsibilities."""

    def setUp(self):
        self.module_doc = (ROOT / "Module.md").read_text(encoding="utf-8")

    def test_records_all_five_mcp_files(self):
        for path in (
            "src/drawing_graph/qa_mcp_models.py",
            "src/drawing_graph/qa_mcp_tools.py",
            "src/drawing_graph/qa_mcp_runtime.py",
            "src/drawing_graph/qa_mcp_server.py",
            "scripts/serve_drawing_graph_mcp.py",
        ):
            with self.subTest(path=path):
                self.assertIn(path, self.module_doc)

    def test_records_six_readonly_tool_names(self):
        for tool_name in (
            "ask_drawing_page",
            "ask_drawing_block",
            "list_drawing_candidates",
            "get_section_match_status",
            "get_table_caption_status",
            "get_drawing_diagnostics",
        ):
            with self.subTest(tool=tool_name):
                self.assertIn(tool_name, self.module_doc)

    def test_records_mcp_dependency_direction_and_sdk(self):
        for phrase in (
            "MCP adapter -> DrawingGraphQAService -> DrawingGraphToolFacade",
            "mcp>=1.29.0,<2.0",
            "不改变 Neo4j 数据模型",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.module_doc)

    def test_records_skill_mcp_division_and_authoritative_path(self):
        for phrase in (
            ".codex/skills/drawing-graph-operator",
            "操作策略层",
            "Skill 与 MCP 分工",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.module_doc)

    def test_does_not_claim_unimplemented_mcp_capabilities(self):
        for phrase in (
            "首版不实现 Streamable HTTP",
            "远程认证",
            "写回",
            "plugin 发布",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.module_doc)


class ModuleAnswerGenerationDocsTest(unittest.TestCase):
    """Module.md must record the 06/07 answer-generation and orchestration modules."""

    def setUp(self):
        self.module_doc = (ROOT / "Module.md").read_text(encoding="utf-8")

    def test_records_answer_generation_and_orchestration_modules(self):
        for path in (
            "src/drawing_graph/assistant_claim_builder.py",
            "src/drawing_graph/assistant_citation_builder.py",
            "src/drawing_graph/assistant_answer_generation.py",
            "src/drawing_graph/assistant_answer_templates.py",
            "src/drawing_graph/assistant_answer_text.py",
            "src/drawing_graph/drawing_assistant_service.py",
            "src/drawing_graph/drawing_assistant_factory.py",
            "scripts/drawing_assistant.py",
        ):
            with self.subTest(path=path):
                self.assertIn(path, self.module_doc)

    def test_records_answer_generation_boundaries(self):
        for phrase in (
            "AnswerGenerationService.generate",
            "DrawingAssistantService.answer",
            "machine_answer",
            "candidate/interpretation 不被提升为 formal/source fact",
            "产品 CLI 是现有 QA CLI/HTTP/MCP 的同级 adapter",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.module_doc)


class ModuleProductAdapterDocsTest(unittest.TestCase):
    """Module.md must record the product HTTP/MCP adapter modules and interfaces."""

    def setUp(self):
        self.module_doc = (ROOT / "Module.md").read_text(encoding="utf-8")

    def test_records_product_adapter_modules(self):
        for path in (
            "assistant_adapter_serialization.py",
            "assistant_http.py",
            "assistant_http_models.py",
            "assistant_http_runtime.py",
            "assistant_mcp_models.py",
            "assistant_mcp_tools.py",
            "assistant_mcp_runtime.py",
            "assistant_mcp_server.py",
            "serve_drawing_assistant.py",
            "serve_drawing_assistant_mcp.py",
        ):
            with self.subTest(path=path):
                self.assertIn(path, self.module_doc)

    def test_records_product_adapter_config_and_interfaces(self):
        for phrase in (
            "AssistantHttpConfig",
            "AssistantMcpConfig",
            "answer_package_to_data",
            "create_assistant_http_runtime",
            "create_assistant_mcp_runtime",
            "ask_drawing_assistant",
            "DRAWING_GRAPH_ASSISTANT_HTTP_",
            "DRAWING_GRAPH_ASSISTANT_MCP_LOG_LEVEL",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.module_doc)

    def test_records_product_adapter_boundaries(self):
        for phrase in (
            "DrawingAssistantService.answer()",
            "write_back=false",
            "候选关系不是正式事实",
            "外部产品级 Web UI",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.module_doc)


if __name__ == "__main__":
    unittest.main()
