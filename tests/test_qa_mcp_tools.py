import unittest


class McpSuccessMappingTests(unittest.TestCase):
    """QAAnswer -> MCP success structured content and same-source text summary."""

    def test_success_mapping_preserves_full_qa_answer(self):
        from drawing_graph.qa_mcp_tools import map_qa_answer_to_success
        from drawing_graph.qa_models import (
            AnswerFact,
            EvidenceRef,
            QAAnswer,
            QAAnswerStatus,
            QAScope,
            QuestionType,
        )

        answer = QAAnswer(
            question_type=QuestionType.BLOCK_RELATIONS,
            scope=QAScope(block_id="block:1"),
            status=QAAnswerStatus.ANSWERED,
            summary="图块关系可用",
            facts=(
                AnswerFact(
                    fact_kind="derived_relation",
                    label="标题关系",
                    status="confirmed",
                    ids={"block_id": "block:1", "page_id": "page:1"},
                    relation_type="HAS_CAPTION",
                    value=("caption:1",),
                    evidence=(EvidenceRef(block_id="block:1", page_id="page:1"),),
                ),
            ),
            warnings=("warn-a",),
            unsupported_parts=("part-b",),
            source_calls=("get_block_trace",),
        )

        outcome = map_qa_answer_to_success("ask_drawing_block", "call-1", answer)

        self.assertEqual("ok", outcome.status)
        self.assertEqual("call-1", outcome.meta.call_id)
        self.assertEqual("ask_drawing_block", outcome.meta.tool_name)
        self.assertEqual("drawing-qa-mcp-v1", outcome.meta.contract_version)
        self.assertEqual("answered", outcome.data["status"])
        self.assertEqual("图块关系可用", outcome.data["summary"])
        self.assertEqual("block:1", outcome.data["scope"]["block_id"])
        self.assertEqual("HAS_CAPTION", outcome.data["facts"][0]["relation_type"])
        self.assertEqual("derived_relation", outcome.data["facts"][0]["fact_kind"])
        evidence = outcome.data["facts"][0]["evidence"][0]
        self.assertEqual("block:1", evidence["block_id"])
        self.assertEqual("page:1", evidence["page_id"])
        self.assertEqual(["warn-a"], outcome.data["warnings"])
        self.assertEqual(["part-b"], outcome.data["unsupported_parts"])
        self.assertEqual(["get_block_trace"], outcome.data["source_calls"])

    def test_text_summary_is_generated_from_same_structured_content(self):
        from drawing_graph.qa_mcp_tools import build_mcp_text_summary, map_qa_answer_to_success
        from drawing_graph.qa_models import QAAnswer, QAAnswerStatus, QAScope, QuestionType

        answer = QAAnswer(
            question_type=QuestionType.PAGE_SUMMARY,
            scope=QAScope(page_id="page:1"),
            status=QAAnswerStatus.ANSWERED,
            summary="页面摘要可用",
            warnings=("warn-a",),
            unsupported_parts=("part-b",),
            source_calls=("get_page_source_facts",),
        )
        outcome = map_qa_answer_to_success("ask_drawing_page", "call-2", answer)

        text = build_mcp_text_summary(outcome)

        self.assertIn("answered", text)
        self.assertIn("页面摘要可用", text)
        self.assertIn("facts=0", text)
        self.assertIn("warnings=1", text)
        self.assertIn("unsupported=1", text)

    def test_partial_answer_remains_success_and_text_mentions_partial(self):
        from drawing_graph.qa_mcp_tools import build_mcp_text_summary, map_qa_answer_to_success
        from drawing_graph.qa_models import QAAnswer, QAAnswerStatus, QAScope, QuestionType

        answer = QAAnswer(
            question_type=QuestionType.TABLE_CAPTION_STATUS,
            scope=QAScope(page_id="page:1"),
            status=QAAnswerStatus.PARTIAL,
            summary="仅返回来源元素",
            unsupported_parts=("表格标题派生状态未查询",),
        )

        outcome = map_qa_answer_to_success("get_table_caption_status", "call-3", answer)

        self.assertEqual("ok", outcome.status)
        self.assertEqual("partial", outcome.data["status"])
        text = build_mcp_text_summary(outcome)
        self.assertIn("partial", text)
        self.assertIn("部分回答", text)
        self.assertIn("unsupported=1", text)


class McpErrorMappingTests(unittest.TestCase):
    """Stable sanitized MCP tool errors for QAError, failed answers, and exceptions."""

    def test_explicit_mapping_covers_all_nine_stable_categories(self):
        from drawing_graph.qa_mcp_tools import map_qa_error_to_failure
        from drawing_graph.qa_models import QAError, QAErrorCode

        expected = {
            QAErrorCode.INVALID_ARGUMENT: "invalid_argument",
            QAErrorCode.UNSUPPORTED_QUESTION: "unsupported_question",
            QAErrorCode.UNSUPPORTED_SCOPE: "unsupported_scope",
            QAErrorCode.NOT_FOUND: "not_found",
            QAErrorCode.WRITE_BACK_FORBIDDEN: "write_back_forbidden",
            QAErrorCode.FACADE_UNAVAILABLE: "facade_unavailable",
            QAErrorCode.NEO4J_UNAVAILABLE: "neo4j_unavailable",
            QAErrorCode.SEMANTIC_EVIDENCE_UNAVAILABLE: "semantic_evidence_unavailable",
            QAErrorCode.INTERNAL_ERROR: "internal_error",
        }
        for error_code, expected_category in expected.items():
            with self.subTest(error_code=error_code):
                error = QAError(error_code, "business message")
                outcome = map_qa_error_to_failure("ask_drawing_page", "call-err-1", error)
                self.assertEqual("error", outcome.status)
                self.assertEqual(expected_category, outcome.error.category)
                self.assertEqual("call-err-1", outcome.meta.call_id)

    def test_not_found_answer_becomes_failure(self):
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools
        from drawing_graph.qa_models import QAAnswer, QAAnswerStatus, QAScope, QuestionType

        answer = QAAnswer(
            question_type=QuestionType.PAGE_SUMMARY,
            scope=QAScope(page_id="page:missing"),
            status=QAAnswerStatus.NOT_FOUND,
            summary="页面不存在或来源事实不可用",
        )
        service = _FakeQAService(result=answer)
        tools = DrawingGraphMCPTools(service)

        outcome = tools._invoke(
            "ask_drawing_page",
            _InputStub(request=None),
        )

        self.assertEqual("error", outcome.status)
        self.assertEqual("not_found", outcome.error.category)
        self.assertFalse(outcome.error.retryable)
        self.assertIn("页面不存在", outcome.error.message)

    def test_unsupported_answer_becomes_failure(self):
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools
        from drawing_graph.qa_models import QAAnswer, QAAnswerStatus, QAScope, QuestionType

        answer = QAAnswer(
            question_type=QuestionType.UNKNOWN_OR_UNSUPPORTED,
            scope=QAScope(),
            status=QAAnswerStatus.UNSUPPORTED,
            summary="该问题类型当前不受支持",
        )
        tools = DrawingGraphMCPTools(_FakeQAService(result=answer))

        outcome = tools._invoke(
            "ask_drawing_page",
            _InputStub(request=None),
        )

        self.assertEqual("error", outcome.status)
        self.assertEqual("unsupported_question", outcome.error.category)

    def test_partial_answer_is_not_mapped_to_error(self):
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools
        from drawing_graph.qa_models import QAAnswer, QAAnswerStatus, QAScope, QuestionType

        answer = QAAnswer(
            question_type=QuestionType.TABLE_CAPTION_STATUS,
            scope=QAScope(page_id="page:1"),
            status=QAAnswerStatus.PARTIAL,
            summary="仅返回来源元素",
            unsupported_parts=("表格标题派生状态未查询",),
        )
        tools = DrawingGraphMCPTools(_FakeQAService(result=answer))

        outcome = tools._invoke(
            "get_table_caption_status",
            _InputStub(request=None),
        )

        self.assertEqual("ok", outcome.status)
        self.assertEqual("partial", outcome.data["status"])
        self.assertEqual(["表格标题派生状态未查询"], outcome.data["unsupported_parts"])

    def test_unexpected_exception_returns_safe_internal_error_and_logs_call_id(self):
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools

        tools = DrawingGraphMCPTools(
            _FakeQAService(error=RuntimeError("bolt://user:secret@host:7687 traceback"))
        )

        with self.assertLogs("drawing_graph.qa_mcp_tools", level="ERROR") as logs:
            outcome = tools._invoke(
                "ask_drawing_page",
                _InputStub(request=None),
            )

        self.assertEqual("error", outcome.status)
        self.assertEqual("internal_error", outcome.error.category)
        self.assertFalse(outcome.error.retryable)
        self.assertNotIn("secret", outcome.error.message)
        self.assertNotIn("bolt://", outcome.error.message)
        self.assertNotIn("traceback", outcome.error.message)
        self.assertTrue(outcome.meta.call_id)
        self.assertIn(outcome.meta.call_id, "".join(logs.output))
        log_text = "".join(logs.output)
        self.assertNotIn("secret", log_text)
        self.assertNotIn("bolt://", log_text)
        self.assertNotIn("Traceback", log_text)
        self.assertNotIn("traceback", log_text)

    def test_qa_error_message_is_sanitized(self):
        from drawing_graph.qa_mcp_tools import map_qa_error_to_failure
        from drawing_graph.qa_models import QAError, QAErrorCode

        error = QAError(
            QAErrorCode.NEO4J_UNAVAILABLE,
            "failed bolt://user:secret@host:7687 neo4j://driver",
            retryable=True,
        )
        outcome = map_qa_error_to_failure("ask_drawing_page", "call-sec", error)

        self.assertEqual("neo4j_unavailable", outcome.error.category)
        self.assertTrue(outcome.error.retryable)
        self.assertNotIn("secret", outcome.error.message)
        self.assertNotIn("bolt://", outcome.error.message)

    def test_input_conversion_failure_does_not_call_service(self):
        from drawing_graph.qa_mcp_models import McpInputError
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools

        service = _FakeQAService(result=None)
        tools = DrawingGraphMCPTools(service)

        outcome = tools._invoke(
            "ask_drawing_page",
            _InputStub(request=None, conversion_error=McpInputError("page_id is required")),
        )

        self.assertEqual("error", outcome.status)
        self.assertEqual("invalid_argument", outcome.error.category)
        self.assertEqual([], service.asked_requests)


class AskDrawingPageToolTests(unittest.TestCase):
    """ask_drawing_page must map narrowly and call QAService exactly once."""

    def test_handler_calls_service_once_with_task4_request(self):
        from drawing_graph.qa_mcp_models import AskDrawingPageInput
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools
        from drawing_graph.qa_models import QAAnswer, QAAnswerStatus, QAScope, QuestionType

        answer = QAAnswer(
            question_type=QuestionType.PAGE_SUMMARY,
            scope=QAScope(page_id="page:road:24"),
            status=QAAnswerStatus.ANSWERED,
            summary="页面摘要可用",
        )
        service = _FakeQAService(result=answer)
        tools = DrawingGraphMCPTools(service)

        tool_input = AskDrawingPageInput(
            page_id="page:road:24",
            language="en",
            include_semantics=False,
        )
        outcome = tools.ask_drawing_page(tool_input)

        self.assertEqual(1, len(service.asked_requests))
        request = service.asked_requests[0]
        self.assertEqual(QuestionType.PAGE_SUMMARY, request.question_type)
        self.assertEqual("page:road:24", request.scope.page_id)
        self.assertIsNone(request.scope.block_id)
        self.assertFalse(request.write_back)
        self.assertFalse(request.include_payload)
        self.assertEqual("en", request.language)
        self.assertFalse(request.include_semantics)

        self.assertEqual("ok", outcome.status)
        self.assertEqual("answered", outcome.data["status"])
        self.assertEqual("页面摘要可用", outcome.data["summary"])
        self.assertEqual("ask_drawing_page", outcome.meta.tool_name)

    def test_partial_answer_remains_ok(self):
        from drawing_graph.qa_mcp_models import AskDrawingPageInput
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools
        from drawing_graph.qa_models import QAAnswer, QAAnswerStatus, QAScope, QuestionType

        answer = QAAnswer(
            question_type=QuestionType.PAGE_SUMMARY,
            scope=QAScope(page_id="page:1"),
            status=QAAnswerStatus.PARTIAL,
            summary="语义证据降级",
            warnings=("语义证据查询不可用，已降级",),
        )
        tools = DrawingGraphMCPTools(_FakeQAService(result=answer))

        outcome = tools.ask_drawing_page(AskDrawingPageInput(page_id="page:1"))

        self.assertEqual("ok", outcome.status)
        self.assertEqual("partial", outcome.data["status"])
        self.assertEqual(["语义证据查询不可用，已降级"], outcome.data["warnings"])

    def test_not_found_answer_is_error(self):
        from drawing_graph.qa_mcp_models import AskDrawingPageInput
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools
        from drawing_graph.qa_models import QAAnswer, QAAnswerStatus, QAScope, QuestionType

        answer = QAAnswer(
            question_type=QuestionType.PAGE_SUMMARY,
            scope=QAScope(page_id="page:missing"),
            status=QAAnswerStatus.NOT_FOUND,
            summary="页面不存在或来源事实不可用",
        )
        tools = DrawingGraphMCPTools(_FakeQAService(result=answer))

        outcome = tools.ask_drawing_page(AskDrawingPageInput(page_id="page:missing"))

        self.assertEqual("error", outcome.status)
        self.assertEqual("not_found", outcome.error.category)
        self.assertIn("页面不存在", outcome.error.message)

    def test_service_exception_is_mapped_to_internal_error(self):
        from drawing_graph.qa_mcp_models import AskDrawingPageInput
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools

        tools = DrawingGraphMCPTools(
            _FakeQAService(error=RuntimeError("bolt://user:secret@host"))
        )

        with self.assertLogs("drawing_graph.qa_mcp_tools", level="ERROR"):
            outcome = tools.ask_drawing_page(AskDrawingPageInput(page_id="page:1"))

        self.assertEqual("error", outcome.status)
        self.assertEqual("internal_error", outcome.error.category)
        self.assertNotIn("secret", outcome.error.message)
        self.assertNotIn("bolt://", outcome.error.message)

    def test_module_does_not_import_http_cli_facade_or_repository(self):
        import ast
        from pathlib import Path

        source = Path("src/drawing_graph/qa_mcp_tools.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        forbidden = {
            "drawing_graph.qa_http",
            "drawing_graph.qa_http_models",
            "drawing_graph.qa_http_runtime",
            "drawing_graph.query_service",
            "drawing_graph.relation_repository",
            "drawing_graph.tool_facade",
            "drawing_graph.tool_factory",
            "drawing_graph.qa_cli",
            "neo4j",
            "fastapi",
            "uvicorn",
        }
        self.assertFalse(imported.intersection(forbidden))


class AskDrawingBlockToolTests(unittest.TestCase):
    """ask_drawing_block must preserve fact kinds and pass read switches through."""

    def test_handler_calls_service_once_with_task5_request(self):
        from drawing_graph.qa_mcp_models import AskDrawingBlockInput
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools
        from drawing_graph.qa_models import QAAnswer, QAAnswerStatus, QAScope, QuestionType

        answer = QAAnswer(
            question_type=QuestionType.BLOCK_RELATIONS,
            scope=QAScope(block_id="block:road:24:abc"),
            status=QAAnswerStatus.ANSWERED,
            summary="图块关系可用",
        )
        service = _FakeQAService(result=answer)
        tools = DrawingGraphMCPTools(service)

        tool_input = AskDrawingBlockInput(
            block_id="block:road:24:abc",
            language="en",
            include_candidates=False,
        )
        outcome = tools.ask_drawing_block(tool_input)

        self.assertEqual(1, len(service.asked_requests))
        request = service.asked_requests[0]
        self.assertEqual(QuestionType.BLOCK_RELATIONS, request.question_type)
        self.assertEqual("block:road:24:abc", request.scope.block_id)
        self.assertIsNone(request.scope.page_id)
        self.assertFalse(request.write_back)
        self.assertFalse(request.include_payload)
        self.assertEqual("en", request.language)
        self.assertFalse(request.include_candidates)
        self.assertEqual("ok", outcome.status)
        self.assertEqual("ask_drawing_block", outcome.meta.tool_name)

    def test_structured_content_preserves_derived_candidate_and_formal_kinds(self):
        from drawing_graph.qa_mcp_models import AskDrawingBlockInput
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools
        from drawing_graph.qa_models import (
            AnswerFact,
            QAAnswer,
            QAAnswerStatus,
            QAScope,
            QuestionType,
        )

        answer = QAAnswer(
            question_type=QuestionType.BLOCK_RELATIONS,
            scope=QAScope(block_id="block:1"),
            status=QAAnswerStatus.ANSWERED,
            summary="图块关系可用",
            facts=(
                AnswerFact(
                    fact_kind="derived_relation",
                    label="标题关系",
                    status="confirmed",
                    ids={"block_id": "block:1"},
                    relation_type="HAS_CAPTION",
                ),
                AnswerFact(
                    fact_kind="candidate_relation",
                    label="候选标题关系",
                    status="candidate",
                    ids={"block_id": "block:1"},
                    relation_type="CANDIDATE_CAPTION_OF",
                ),
                AnswerFact(
                    fact_kind="formal_relation",
                    label="正式关系",
                    status="confirmed",
                    ids={"block_id": "block:1"},
                    relation_type="MATCHES_SECTION_CAPTION",
                ),
            ),
        )
        tools = DrawingGraphMCPTools(_FakeQAService(result=answer))

        outcome = tools.ask_drawing_block(AskDrawingBlockInput(block_id="block:1"))

        self.assertEqual("ok", outcome.status)
        kinds = [fact["fact_kind"] for fact in outcome.data["facts"]]
        self.assertEqual(
            ["derived_relation", "candidate_relation", "formal_relation"],
            kinds,
        )

    def test_text_summary_does_not_claim_candidate_as_formal(self):
        from drawing_graph.qa_mcp_tools import build_mcp_text_summary
        from drawing_graph.qa_mcp_models import AskDrawingBlockInput
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools
        from drawing_graph.qa_models import (
            AnswerFact,
            QAAnswer,
            QAAnswerStatus,
            QAScope,
            QuestionType,
        )

        answer = QAAnswer(
            question_type=QuestionType.BLOCK_RELATIONS,
            scope=QAScope(block_id="block:1"),
            status=QAAnswerStatus.ANSWERED,
            summary="图块关系可用",
            facts=(
                AnswerFact(
                    fact_kind="candidate_relation",
                    label="候选标题关系",
                    status="candidate",
                    ids={"block_id": "block:1"},
                    relation_type="CANDIDATE_CAPTION_OF",
                ),
            ),
        )
        tools = DrawingGraphMCPTools(_FakeQAService(result=answer))

        outcome = tools.ask_drawing_block(AskDrawingBlockInput(block_id="block:1"))
        text = build_mcp_text_summary(outcome)

        self.assertNotIn("正式", text)
        self.assertNotIn("formal", text)
        self.assertNotIn("matched_candidate", text)

    def test_include_candidates_false_passes_through_without_filtering(self):
        from drawing_graph.qa_mcp_models import AskDrawingBlockInput
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools
        from drawing_graph.qa_models import (
            AnswerFact,
            QAAnswer,
            QAAnswerStatus,
            QAScope,
            QuestionType,
        )

        answer = QAAnswer(
            question_type=QuestionType.BLOCK_RELATIONS,
            scope=QAScope(block_id="block:1"),
            status=QAAnswerStatus.ANSWERED,
            summary="图块关系可用",
            facts=(
                AnswerFact(
                    fact_kind="candidate_relation",
                    label="候选标题关系",
                    status="candidate",
                    ids={"block_id": "block:1"},
                    relation_type="CANDIDATE_CAPTION_OF",
                ),
            ),
        )
        service = _FakeQAService(result=answer)
        tools = DrawingGraphMCPTools(service)

        outcome = tools.ask_drawing_block(
            AskDrawingBlockInput(block_id="block:1", include_candidates=False)
        )

        self.assertFalse(service.asked_requests[0].include_candidates)
        self.assertEqual("candidate_relation", outcome.data["facts"][0]["fact_kind"])


class ListDrawingCandidatesToolTests(unittest.TestCase):
    """list_drawing_candidates must stay read-only and preserve candidate kinds."""

    def test_page_scope_calls_service_once(self):
        from drawing_graph.qa_mcp_models import ListDrawingCandidatesInput
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools
        from drawing_graph.qa_models import QAAnswer, QAAnswerStatus, QAScope, QuestionType

        answer = QAAnswer(
            question_type=QuestionType.CANDIDATE_RELATIONS,
            scope=QAScope(page_id="page:road:24"),
            status=QAAnswerStatus.ANSWERED,
            summary="找到 1 条候选关系",
        )
        service = _FakeQAService(result=answer)
        tools = DrawingGraphMCPTools(service)

        outcome = tools.list_drawing_candidates(
            ListDrawingCandidatesInput(page_id="page:road:24", language="en")
        )

        self.assertEqual(1, len(service.asked_requests))
        request = service.asked_requests[0]
        self.assertEqual(QuestionType.CANDIDATE_RELATIONS, request.question_type)
        self.assertEqual("page:road:24", request.scope.page_id)
        self.assertIsNone(request.scope.block_id)
        self.assertFalse(request.write_back)
        self.assertFalse(request.include_payload)
        self.assertEqual("en", request.language)
        self.assertEqual("ok", outcome.status)
        self.assertEqual("list_drawing_candidates", outcome.meta.tool_name)

    def test_block_scope_calls_service_once(self):
        from drawing_graph.qa_mcp_models import ListDrawingCandidatesInput
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools
        from drawing_graph.qa_models import QAAnswer, QAAnswerStatus, QAScope, QuestionType

        answer = QAAnswer(
            question_type=QuestionType.CANDIDATE_RELATIONS,
            scope=QAScope(block_id="block:road:24:abc"),
            status=QAAnswerStatus.ANSWERED,
            summary="没有找到候选关系",
        )
        service = _FakeQAService(result=answer)
        tools = DrawingGraphMCPTools(service)

        outcome = tools.list_drawing_candidates(
            ListDrawingCandidatesInput(block_id="block:road:24:abc")
        )

        self.assertEqual(1, len(service.asked_requests))
        request = service.asked_requests[0]
        self.assertEqual("block:road:24:abc", request.scope.block_id)
        self.assertIsNone(request.scope.page_id)
        self.assertEqual("ok", outcome.status)

    def test_candidate_facts_stay_candidate_and_no_formal_is_generated(self):
        from drawing_graph.qa_mcp_models import ListDrawingCandidatesInput
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools
        from drawing_graph.qa_models import (
            AnswerFact,
            QAAnswer,
            QAAnswerStatus,
            QAScope,
            QuestionType,
        )

        answer = QAAnswer(
            question_type=QuestionType.CANDIDATE_RELATIONS,
            scope=QAScope(page_id="page:1"),
            status=QAAnswerStatus.ANSWERED,
            summary="找到 2 条候选关系",
            facts=(
                AnswerFact(
                    fact_kind="candidate_relation",
                    label="候选断面标记关系",
                    status="candidate",
                    ids={"candidate_group_id": "group:1", "page_id": "page:1"},
                    relation_type="CANDIDATE_HAS_SECTION_MARK",
                ),
                AnswerFact(
                    fact_kind="candidate_relation",
                    label="候选标题关系",
                    status="candidate",
                    ids={"candidate_group_id": "group:2", "page_id": "page:1"},
                    relation_type="CANDIDATE_CAPTION_OF",
                ),
            ),
        )
        tools = DrawingGraphMCPTools(_FakeQAService(result=answer))

        outcome = tools.list_drawing_candidates(
            ListDrawingCandidatesInput(page_id="page:1")
        )

        kinds = [fact["fact_kind"] for fact in outcome.data["facts"]]
        self.assertEqual(["candidate_relation", "candidate_relation"], kinds)
        self.assertNotIn("formal_relation", kinds)
        self.assertEqual(
            ["CANDIDATE_HAS_SECTION_MARK", "CANDIDATE_CAPTION_OF"],
            [fact["relation_type"] for fact in outcome.data["facts"]],
        )

    def test_scope_validation_failure_does_not_call_service(self):
        from drawing_graph.qa_mcp_models import ListDrawingCandidatesInput
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools
        from pydantic import ValidationError

        service = _FakeQAService(result=None)
        tools = DrawingGraphMCPTools(service)

        with self.assertRaises(ValidationError):
            tools.list_drawing_candidates(
                ListDrawingCandidatesInput(page_id="page:1", block_id="block:1")
            )
        with self.assertRaises(ValidationError):
            tools.list_drawing_candidates(ListDrawingCandidatesInput())

        self.assertEqual([], service.asked_requests)


class GetSectionMatchStatusToolTests(unittest.TestCase):
    """get_section_match_status must use QA only and keep candidate semantics."""

    def test_cross_section_scope_calls_service_once(self):
        from drawing_graph.qa_mcp_models import GetSectionMatchStatusInput
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools
        from drawing_graph.qa_models import QAAnswer, QAAnswerStatus, QAScope, QuestionType

        answer = QAAnswer(
            question_type=QuestionType.SECTION_MATCHES,
            scope=QAScope(cross_section_id="element:road:24:cs1"),
            status=QAAnswerStatus.ANSWERED,
            summary="找到 1 条断面匹配（0 正式，1 候选）",
        )
        service = _FakeQAService(result=answer)
        tools = DrawingGraphMCPTools(service)

        outcome = tools.get_section_match_status(
            GetSectionMatchStatusInput(cross_section_id="element:road:24:cs1")
        )

        self.assertEqual(1, len(service.asked_requests))
        request = service.asked_requests[0]
        self.assertEqual(QuestionType.SECTION_MATCHES, request.question_type)
        self.assertEqual("element:road:24:cs1", request.scope.cross_section_id)
        self.assertIsNone(request.scope.page_id)
        self.assertFalse(request.write_back)
        self.assertFalse(request.include_payload)
        self.assertEqual("ok", outcome.status)
        self.assertEqual("get_section_match_status", outcome.meta.tool_name)

    def test_page_scope_calls_service_once(self):
        from drawing_graph.qa_mcp_models import GetSectionMatchStatusInput
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools
        from drawing_graph.qa_models import QAAnswer, QAAnswerStatus, QAScope, QuestionType

        answer = QAAnswer(
            question_type=QuestionType.SECTION_MATCHES,
            scope=QAScope(page_id="page:road:24"),
            status=QAAnswerStatus.ANSWERED,
            summary="没有找到已持久化的断面匹配",
        )
        service = _FakeQAService(result=answer)
        tools = DrawingGraphMCPTools(service)

        outcome = tools.get_section_match_status(
            GetSectionMatchStatusInput(page_id="page:road:24", language="en")
        )

        self.assertEqual(1, len(service.asked_requests))
        request = service.asked_requests[0]
        self.assertEqual("page:road:24", request.scope.page_id)
        self.assertIsNone(request.scope.cross_section_id)
        self.assertEqual("en", request.language)
        self.assertEqual("ok", outcome.status)

    def test_handler_calls_qa_service_and_never_facade_match_method(self):
        from drawing_graph.qa_mcp_models import GetSectionMatchStatusInput
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools
        from drawing_graph.qa_models import QAAnswer, QAAnswerStatus, QAScope, QuestionType

        answer = QAAnswer(
            question_type=QuestionType.SECTION_MATCHES,
            scope=QAScope(cross_section_id="element:1"),
            status=QAAnswerStatus.ANSWERED,
            summary="没有找到断面匹配候选",
        )
        service = _FakeQAService(result=answer)
        service.match_section_caption = _ForbiddenFacadeMethod()
        tools = DrawingGraphMCPTools(service)

        outcome = tools.get_section_match_status(
            GetSectionMatchStatusInput(cross_section_id="element:1")
        )

        self.assertEqual("ok", outcome.status)
        self.assertEqual(1, len(service.asked_requests))

    def test_matched_candidate_stays_candidate_and_text_does_not_promote_it(self):
        from drawing_graph.qa_mcp_models import GetSectionMatchStatusInput
        from drawing_graph.qa_mcp_tools import build_mcp_text_summary, DrawingGraphMCPTools
        from drawing_graph.qa_models import (
            AnswerFact,
            QAAnswer,
            QAAnswerStatus,
            QAScope,
            QuestionType,
        )

        answer = QAAnswer(
            question_type=QuestionType.SECTION_MATCHES,
            scope=QAScope(cross_section_id="element:1"),
            status=QAAnswerStatus.ANSWERED,
            summary="找到 1 条断面候选匹配",
            facts=(
                AnswerFact(
                    fact_kind="candidate_relation",
                    label="断面候选匹配",
                    status="candidate",
                    ids={"cross_section_id": "element:1"},
                    relation_type="CANDIDATE_MATCHES_SECTION_CAPTION",
                    value={"matched_caption_ids": ("caption:1",)},
                ),
            ),
        )
        tools = DrawingGraphMCPTools(_FakeQAService(result=answer))

        outcome = tools.get_section_match_status(
            GetSectionMatchStatusInput(cross_section_id="element:1")
        )

        self.assertEqual("candidate_relation", outcome.data["facts"][0]["fact_kind"])
        text = build_mcp_text_summary(outcome)
        self.assertNotIn("正式", text)
        self.assertNotIn("formal", text)

    def test_not_found_partial_unsupported_use_unified_mapping(self):
        from drawing_graph.qa_mcp_models import GetSectionMatchStatusInput
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools
        from drawing_graph.qa_models import QAAnswer, QAAnswerStatus, QAScope, QuestionType

        cases = (
            (
                QAAnswerStatus.NOT_FOUND,
                QAAnswer(
                    question_type=QuestionType.SECTION_MATCHES,
                    scope=QAScope(cross_section_id="element:1"),
                    status=QAAnswerStatus.NOT_FOUND,
                    summary="断面或标题观测不存在，无法判断匹配",
                ),
                "error",
                "not_found",
            ),
            (
                QAAnswerStatus.PARTIAL,
                QAAnswer(
                    question_type=QuestionType.SECTION_MATCHES,
                    scope=QAScope(cross_section_id="element:1"),
                    status=QAAnswerStatus.PARTIAL,
                    summary="断面匹配查询不可用",
                    warnings=("断面匹配查询不可用，已降级",),
                ),
                "ok",
                None,
            ),
            (
                QAAnswerStatus.UNSUPPORTED,
                QAAnswer(
                    question_type=QuestionType.SECTION_MATCHES,
                    scope=QAScope(cross_section_id="element:1"),
                    status=QAAnswerStatus.UNSUPPORTED,
                    summary="该问题类型当前不受支持",
                    unsupported_parts=("该问题类型当前不受支持",),
                ),
                "error",
                "unsupported_question",
            ),
        )
        for status, answer, expected_status, expected_category in cases:
            with self.subTest(status=status):
                tools = DrawingGraphMCPTools(_FakeQAService(result=answer))
                outcome = tools.get_section_match_status(
                    GetSectionMatchStatusInput(cross_section_id="element:1")
                )
                self.assertEqual(expected_status, outcome.status)
                if expected_category is not None:
                    self.assertEqual(expected_category, outcome.error.category)
                else:
                    self.assertEqual("partial", outcome.data["status"])


class GetTableCaptionStatusToolTests(unittest.TestCase):
    """get_table_caption_status must keep partial semantics without inventing relations."""

    def test_page_scope_calls_service_once(self):
        from drawing_graph.qa_mcp_models import GetTableCaptionStatusInput
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools
        from drawing_graph.qa_models import QAAnswer, QAAnswerStatus, QAScope, QuestionType

        answer = QAAnswer(
            question_type=QuestionType.TABLE_CAPTION_STATUS,
            scope=QAScope(page_id="page:road:24"),
            status=QAAnswerStatus.PARTIAL,
            summary="页面有表格来源元素",
        )
        service = _FakeQAService(result=answer)
        tools = DrawingGraphMCPTools(service)

        outcome = tools.get_table_caption_status(
            GetTableCaptionStatusInput(page_id="page:road:24")
        )

        self.assertEqual(1, len(service.asked_requests))
        request = service.asked_requests[0]
        self.assertEqual(QuestionType.TABLE_CAPTION_STATUS, request.question_type)
        self.assertEqual("page:road:24", request.scope.page_id)
        self.assertIsNone(request.scope.table_id)
        self.assertIsNone(request.scope.table_caption_id)
        self.assertFalse(request.write_back)
        self.assertFalse(request.include_payload)
        self.assertEqual("ok", outcome.status)
        self.assertEqual("get_table_caption_status", outcome.meta.tool_name)

    def test_table_scope_calls_service_once(self):
        from drawing_graph.qa_mcp_models import GetTableCaptionStatusInput
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools
        from drawing_graph.qa_models import QAAnswer, QAAnswerStatus, QAScope, QuestionType

        answer = QAAnswer(
            question_type=QuestionType.TABLE_CAPTION_STATUS,
            scope=QAScope(table_id="table:road:24:t1"),
            status=QAAnswerStatus.PARTIAL,
            summary="缺少 page_id，无法通过现有 facade 反查页面",
            unsupported_parts=("缺少 page_id，无法回答表格标题派生状态",),
        )
        service = _FakeQAService(result=answer)
        tools = DrawingGraphMCPTools(service)

        outcome = tools.get_table_caption_status(
            GetTableCaptionStatusInput(table_id="table:road:24:t1", language="en")
        )

        self.assertEqual(1, len(service.asked_requests))
        request = service.asked_requests[0]
        self.assertEqual("table:road:24:t1", request.scope.table_id)
        self.assertIsNone(request.scope.page_id)
        self.assertEqual("en", request.language)
        self.assertEqual("ok", outcome.status)

    def test_table_caption_scope_calls_service_once(self):
        from drawing_graph.qa_mcp_models import GetTableCaptionStatusInput
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools
        from drawing_graph.qa_models import QAAnswer, QAAnswerStatus, QAScope, QuestionType

        answer = QAAnswer(
            question_type=QuestionType.TABLE_CAPTION_STATUS,
            scope=QAScope(table_caption_id="caption:road:24:c1"),
            status=QAAnswerStatus.PARTIAL,
            summary="缺少 page_id，无法回答表格标题派生状态",
        )
        service = _FakeQAService(result=answer)
        tools = DrawingGraphMCPTools(service)

        outcome = tools.get_table_caption_status(
            GetTableCaptionStatusInput(table_caption_id="caption:road:24:c1")
        )

        self.assertEqual(1, len(service.asked_requests))
        request = service.asked_requests[0]
        self.assertEqual("caption:road:24:c1", request.scope.table_caption_id)
        self.assertIsNone(request.scope.page_id)
        self.assertEqual("ok", outcome.status)

    def test_table_single_id_partial_unsupported_remains_ok(self):
        from drawing_graph.qa_mcp_tools import build_mcp_text_summary
        from drawing_graph.qa_mcp_models import GetTableCaptionStatusInput
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools
        from drawing_graph.qa_models import QAAnswer, QAAnswerStatus, QAScope, QuestionType

        answer = QAAnswer(
            question_type=QuestionType.TABLE_CAPTION_STATUS,
            scope=QAScope(table_id="table:1"),
            status=QAAnswerStatus.PARTIAL,
            summary="缺少 page_id，无法回答表格标题派生状态",
            unsupported_parts=("表格标题派生状态缺少 facade 只读接口",),
        )
        tools = DrawingGraphMCPTools(_FakeQAService(result=answer))

        outcome = tools.get_table_caption_status(
            GetTableCaptionStatusInput(table_id="table:1")
        )

        self.assertEqual("ok", outcome.status)
        self.assertEqual("partial", outcome.data["status"])
        self.assertEqual(
            ["表格标题派生状态缺少 facade 只读接口"],
            outcome.data["unsupported_parts"],
        )
        text = build_mcp_text_summary(outcome)
        self.assertIn("部分回答", text)

    def test_output_does_not_present_source_elements_as_confirmed_derived_relation(self):
        from drawing_graph.qa_mcp_models import GetTableCaptionStatusInput
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools
        from drawing_graph.qa_models import (
            AnswerFact,
            QAAnswer,
            QAAnswerStatus,
            QAScope,
            QuestionType,
        )

        answer = QAAnswer(
            question_type=QuestionType.TABLE_CAPTION_STATUS,
            scope=QAScope(page_id="page:1"),
            status=QAAnswerStatus.PARTIAL,
            summary="页面有 1 个表格、1 个表格标题来源元素",
            facts=(
                AnswerFact(
                    fact_kind="source_fact",
                    label="表格",
                    status="confirmed",
                    ids={"page_id": "page:1", "table_id": "table:1"},
                    value="table:1",
                ),
                AnswerFact(
                    fact_kind="source_fact",
                    label="表格标题",
                    status="confirmed",
                    ids={"page_id": "page:1", "table_caption_id": "caption:1"},
                    value="caption:1",
                ),
            ),
            unsupported_parts=("表格标题派生状态未查询",),
        )
        tools = DrawingGraphMCPTools(_FakeQAService(result=answer))

        outcome = tools.get_table_caption_status(
            GetTableCaptionStatusInput(page_id="page:1")
        )

        kinds = [fact["fact_kind"] for fact in outcome.data["facts"]]
        self.assertEqual(["source_fact", "source_fact"], kinds)
        self.assertFalse(
            any(
                fact["relation_type"] == "HAS_CAPTION" and fact["fact_kind"] == "derived_relation"
                for fact in outcome.data["facts"]
            )
        )


class GetDrawingDiagnosticsToolTests(unittest.TestCase):
    """get_drawing_diagnostics must be read-only and preserve fact kinds."""

    def test_page_scope_calls_service_once_with_read_switches(self):
        from drawing_graph.qa_mcp_models import GetDrawingDiagnosticsInput
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools
        from drawing_graph.qa_models import QAAnswer, QAAnswerStatus, QAScope, QuestionType

        answer = QAAnswer(
            question_type=QuestionType.DIAGNOSTIC_STATUS,
            scope=QAScope(page_id="page:road:24"),
            status=QAAnswerStatus.ANSWERED,
            summary="页面诊断：导入可见",
        )
        service = _FakeQAService(result=answer)
        tools = DrawingGraphMCPTools(service)

        outcome = tools.get_drawing_diagnostics(
            GetDrawingDiagnosticsInput(
                page_id="page:road:24",
                language="en",
                include_semantics=False,
                include_candidates=False,
            )
        )

        self.assertEqual(1, len(service.asked_requests))
        request = service.asked_requests[0]
        self.assertEqual(QuestionType.DIAGNOSTIC_STATUS, request.question_type)
        self.assertEqual("page:road:24", request.scope.page_id)
        self.assertIsNone(request.scope.block_id)
        self.assertEqual("en", request.language)
        self.assertFalse(request.include_semantics)
        self.assertFalse(request.include_candidates)
        self.assertFalse(request.write_back)
        self.assertFalse(request.include_payload)
        self.assertEqual("ok", outcome.status)
        self.assertEqual("get_drawing_diagnostics", outcome.meta.tool_name)

    def test_block_scope_calls_service_once(self):
        from drawing_graph.qa_mcp_models import GetDrawingDiagnosticsInput
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools
        from drawing_graph.qa_models import QAAnswer, QAAnswerStatus, QAScope, QuestionType

        answer = QAAnswer(
            question_type=QuestionType.DIAGNOSTIC_STATUS,
            scope=QAScope(block_id="block:road:24:abc"),
            status=QAAnswerStatus.ANSWERED,
            summary="图块诊断：已导入",
        )
        service = _FakeQAService(result=answer)
        tools = DrawingGraphMCPTools(service)

        outcome = tools.get_drawing_diagnostics(
            GetDrawingDiagnosticsInput(block_id="block:road:24:abc")
        )

        self.assertEqual(1, len(service.asked_requests))
        request = service.asked_requests[0]
        self.assertEqual("block:road:24:abc", request.scope.block_id)
        self.assertIsNone(request.scope.page_id)
        self.assertTrue(request.include_semantics)
        self.assertTrue(request.include_candidates)
        self.assertEqual("ok", outcome.status)

    def test_diagnostic_and_existing_fact_kinds_are_preserved(self):
        from drawing_graph.qa_mcp_models import GetDrawingDiagnosticsInput
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools
        from drawing_graph.qa_models import (
            AnswerFact,
            QAAnswer,
            QAAnswerStatus,
            QAScope,
            QuestionType,
        )

        answer = QAAnswer(
            question_type=QuestionType.DIAGNOSTIC_STATUS,
            scope=QAScope(page_id="page:1"),
            status=QAAnswerStatus.ANSWERED,
            summary="页面诊断：导入可见，语义证据与候选状态以查询结果为准",
            facts=(
                AnswerFact(
                    fact_kind="diagnostic",
                    label="导入可见性",
                    status="confirmed",
                    ids={"page_id": "page:1"},
                    value="已导入",
                ),
                AnswerFact(
                    fact_kind="source_fact",
                    label="页面元素",
                    status="confirmed",
                    ids={"page_id": "page:1"},
                    value=2,
                ),
                AnswerFact(
                    fact_kind="candidate_relation",
                    label="候选标题关系",
                    status="candidate",
                    ids={"candidate_group_id": "group:1", "page_id": "page:1"},
                    relation_type="CANDIDATE_CAPTION_OF",
                ),
            ),
        )
        tools = DrawingGraphMCPTools(_FakeQAService(result=answer))

        outcome = tools.get_drawing_diagnostics(
            GetDrawingDiagnosticsInput(page_id="page:1")
        )

        kinds = [fact["fact_kind"] for fact in outcome.data["facts"]]
        self.assertEqual(
            ["diagnostic", "source_fact", "candidate_relation"],
            kinds,
        )

    def test_handler_does_not_trigger_write_or_fix_capabilities(self):
        from drawing_graph.qa_mcp_models import GetDrawingDiagnosticsInput
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools
        from drawing_graph.qa_models import QAAnswer, QAAnswerStatus, QAScope, QuestionType

        answer = QAAnswer(
            question_type=QuestionType.DIAGNOSTIC_STATUS,
            scope=QAScope(block_id="block:1"),
            status=QAAnswerStatus.ANSWERED,
            summary="图块诊断：已导入",
        )
        service = _FakeQAService(result=answer)
        for method_name in (
            "run_import",
            "run_enhancement",
            "recognize",
            "auto_fix",
            "review_candidate",
            "write_back",
        ):
            setattr(service, method_name, _ForbiddenFacadeMethod())
        tools = DrawingGraphMCPTools(service)

        outcome = tools.get_drawing_diagnostics(
            GetDrawingDiagnosticsInput(block_id="block:1")
        )

        self.assertEqual("ok", outcome.status)
        self.assertEqual(1, len(service.asked_requests))


class _ForbiddenFacadeMethod:
    """Marker that fails the test if a handler calls a facade single method."""

    def __call__(self, *args, **kwargs):
        raise AssertionError("handler must not call facade single methods")


class _FakeQAService:
    """Minimal QA service double recording ask() calls for tool tests."""

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.asked_requests = []

    def ask(self, request):
        self.asked_requests.append(request)
        if self.error is not None:
            raise self.error
        return self.result


class _InputStub:
    """Input double with an optional conversion failure for dispatcher tests."""

    def __init__(self, request, conversion_error=None):
        self.request = request
        self.conversion_error = conversion_error

    def to_qa_request(self):
        if self.conversion_error is not None:
            raise self.conversion_error
        return self.request


if __name__ == "__main__":
    unittest.main()
