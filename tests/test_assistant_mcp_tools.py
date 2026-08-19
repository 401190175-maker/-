"""Tests for the product MCP tool handler and result mapping."""

import unittest


def _make_package(status="answered", request_id="req:1", text="答案文本", **kwargs):
    from drawing_graph.assistant_models import (
        AnswerPackage,
        AnswerStatus,
        Claim,
        MachineAnswer,
    )

    claims = kwargs.pop("claims", ())
    warnings = kwargs.pop("warnings", ())
    unsupported = kwargs.pop("unsupported_parts", ())
    machine = MachineAnswer(
        answer_contract_version="drawing-assistant-answer-v1",
        request_id=request_id,
        question_type="page_summary",
        status=AnswerStatus(status),
        claims=claims,
    )
    return AnswerPackage(
        request_id=request_id,
        question_type="page_summary",
        status=status,
        machine_answer=machine,
        text_answer=text,
        claims=claims,
        warnings=warnings,
        unsupported_parts=unsupported,
    )


class _FakeService:
    def __init__(self, package=None, error=None):
        self.package = package or _make_package()
        self.error = error
        self.answer_calls = 0
        self.last_request = None

    def answer(self, request, policy=None):
        self.answer_calls += 1
        self.last_request = request
        if self.error is not None:
            raise self.error
        return self.package


class AskDrawingAssistantToolTests(unittest.TestCase):
    def test_handler_calls_service_once_with_read_only_request(self):
        from drawing_graph.assistant_mcp_models import AskDrawingAssistantInput
        from drawing_graph.assistant_mcp_tools import DrawingAssistantMCPTools

        service = _FakeService()
        tools = DrawingAssistantMCPTools(service)

        outcome = tools.ask_drawing_assistant(
            AskDrawingAssistantInput.model_validate({"question": "q", "scope_hint": {"page_id": "page:1"}})
        )

        self.assertEqual(1, service.answer_calls)
        self.assertFalse(service.last_request.allow_write_back)
        self.assertEqual("page:1", service.last_request.scope_hint.page_id)
        self.assertEqual("ok", outcome.status)

    def test_structured_content_comes_from_answer_package(self):
        from drawing_graph.assistant_models import Claim
        from drawing_graph.assistant_mcp_models import AskDrawingAssistantInput
        from drawing_graph.assistant_mcp_tools import DrawingAssistantMCPTools

        claim = Claim(claim_id="claim:1", statement="标题关系", fact_kinds=("derived_relation",))
        service = _FakeService(
            package=_make_package(
                claims=(claim,),
                warnings=("warn-a",),
                unsupported_parts=("part-b",),
            )
        )
        tools = DrawingAssistantMCPTools(service)

        outcome = tools.ask_drawing_assistant(
            AskDrawingAssistantInput.model_validate({"question": "q"})
        )

        self.assertEqual("answered", outcome.data["status"])
        self.assertEqual("答案文本", outcome.data["text_answer"])
        self.assertEqual("claim:1", outcome.data["claims"][0]["claim_id"])
        self.assertEqual(["warn-a"], outcome.data["warnings"])
        self.assertEqual(["part-b"], outcome.data["unsupported_parts"])

    def test_all_business_statuses_are_success(self):
        from drawing_graph.assistant_mcp_models import AskDrawingAssistantInput
        from drawing_graph.assistant_mcp_tools import DrawingAssistantMCPTools

        for status in ("answered", "partial", "clarification_required", "unsupported", "recognition_failed"):
            with self.subTest(status=status):
                tools = DrawingAssistantMCPTools(_FakeService(package=_make_package(status=status)))
                outcome = tools.ask_drawing_assistant(
                    AskDrawingAssistantInput.model_validate({"question": "q"})
                )
                self.assertEqual("ok", outcome.status)
                self.assertEqual(status, outcome.data["status"])

    def test_partial_is_not_a_tool_error(self):
        from drawing_graph.assistant_mcp_models import AskDrawingAssistantInput
        from drawing_graph.assistant_mcp_tools import DrawingAssistantMCPTools

        tools = DrawingAssistantMCPTools(_FakeService(package=_make_package(status="partial")))
        outcome = tools.ask_drawing_assistant(AskDrawingAssistantInput.model_validate({"question": "q"}))

        self.assertEqual("ok", outcome.status)
        self.assertEqual("partial", outcome.data["status"])

    def test_text_summary_does_not_add_facts(self):
        from drawing_graph.assistant_mcp_models import AskDrawingAssistantInput
        from drawing_graph.assistant_mcp_tools import (
            DrawingAssistantMCPTools,
            build_assistant_text_summary,
        )

        service = _FakeService(package=_make_package(warnings=("warn-a",), unsupported_parts=("part-b",)))
        tools = DrawingAssistantMCPTools(service)
        outcome = tools.ask_drawing_assistant(AskDrawingAssistantInput.model_validate({"question": "q"}))

        text = build_assistant_text_summary(outcome)
        self.assertIn("answered", text)
        self.assertIn("答案文本", text)
        self.assertIn("warnings=1", text)
        self.assertIn("unsupported=1", text)

    def test_unexpected_error_is_sanitized_internal_error(self):
        from drawing_graph.assistant_mcp_models import AskDrawingAssistantInput
        from drawing_graph.assistant_mcp_tools import DrawingAssistantMCPTools

        tools = DrawingAssistantMCPTools(
            _FakeService(error=RuntimeError("bolt://user:secret@host traceback"))
        )
        outcome = tools.ask_drawing_assistant(AskDrawingAssistantInput.model_validate({"question": "q"}))

        self.assertEqual("error", outcome.status)
        self.assertEqual("internal_error", outcome.error.category)
        self.assertNotIn("secret", outcome.error.message)
        self.assertNotIn("bolt://", outcome.error.message)

    def test_read_only_violation_maps_to_stable_category(self):
        from drawing_graph.assistant_mcp_models import AskDrawingAssistantInput
        from drawing_graph.assistant_mcp_tools import DrawingAssistantMCPTools
        from drawing_graph.drawing_assistant_service import ReadOnlyViolationError

        tools = DrawingAssistantMCPTools(_FakeService(error=ReadOnlyViolationError("forbidden")))
        outcome = tools.ask_drawing_assistant(AskDrawingAssistantInput.model_validate({"question": "q"}))

        self.assertEqual("error", outcome.status)
        self.assertEqual("read_only_violation", outcome.error.category)


class McpAssistantMappingTests(unittest.TestCase):
    def test_map_package_to_success_preserves_candidate_kind(self):
        from drawing_graph.assistant_models import Claim
        from drawing_graph.assistant_mcp_tools import map_package_to_success

        claim = Claim(claim_id="claim:1", statement="候选", fact_kinds=("candidate_relation",))
        package = _make_package(claims=(claim,))
        outcome = map_package_to_success("ask_drawing_assistant", "call-1", package)

        self.assertEqual("candidate_relation", outcome.data["claims"][0]["fact_kinds"][0])
        self.assertNotIn("formal_relation", outcome.data["claims"][0]["fact_kinds"])

    def test_map_exception_to_failure_uses_internal_error_fallback(self):
        from drawing_graph.assistant_mcp_tools import map_exception_to_failure

        outcome = map_exception_to_failure("ask_drawing_assistant", "call-1", RuntimeError("boom"))
        self.assertEqual("internal_error", outcome.error.category)
        self.assertEqual("call-1", outcome.meta.call_id)


class McpAssistantBoundaryTests(unittest.TestCase):
    def test_tools_module_does_not_import_http_cli_facade_or_repository(self):
        import ast
        from pathlib import Path

        source = Path("src/drawing_graph/assistant_mcp_tools.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        forbidden = {
            "drawing_graph.assistant_http",
            "drawing_graph.assistant_http_models",
            "drawing_graph.assistant_http_runtime",
            "drawing_graph.query_service",
            "drawing_graph.relation_repository",
            "drawing_graph.tool_facade",
            "drawing_graph.tool_factory",
            "drawing_graph.qa_http",
            "drawing_graph.qa_mcp",
            "drawing_graph.assistant_semantic_write_back",
            "neo4j",
            "fastapi",
            "uvicorn",
        }
        self.assertFalse(imported.intersection(forbidden))


if __name__ == "__main__":
    unittest.main()
