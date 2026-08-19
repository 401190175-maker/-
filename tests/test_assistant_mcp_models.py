"""Tests for the product MCP input/output protocol models."""

import unittest

from pydantic import ValidationError


class AskDrawingAssistantInputTests(unittest.TestCase):
    def test_question_is_required(self):
        from drawing_graph.assistant_mcp_models import AskDrawingAssistantInput

        with self.assertRaises(ValidationError):
            AskDrawingAssistantInput.model_validate({})
        with self.assertRaises(ValidationError):
            AskDrawingAssistantInput.model_validate({"question": ""})
        with self.assertRaises(ValidationError):
            AskDrawingAssistantInput.model_validate({"question": "   "})

    def test_question_is_length_limited(self):
        from drawing_graph.assistant_mcp_models import AskDrawingAssistantInput

        with self.assertRaises(ValidationError):
            AskDrawingAssistantInput.model_validate({"question": "x" * 2001})

    def test_supported_fields_are_accepted(self):
        from drawing_graph.assistant_mcp_models import AskDrawingAssistantInput

        tool_input = AskDrawingAssistantInput.model_validate(
            {
                "question": "这张图主要讲什么",
                "request_id": "req:1",
                "language": "en",
                "scope_hint": {"page_id": "page:1"},
                "allow_recognition": False,
                "answer_format": "json",
            }
        )
        self.assertEqual("这张图主要讲什么", tool_input.question)
        self.assertEqual("req:1", tool_input.request_id)
        self.assertEqual("en", tool_input.language)
        self.assertFalse(tool_input.allow_recognition)
        self.assertEqual("page:1", tool_input.scope_hint.page_id)

    def test_converts_to_read_only_assistant_request(self):
        from drawing_graph.assistant_mcp_models import AskDrawingAssistantInput

        request = AskDrawingAssistantInput.model_validate(
            {"question": "q", "scope_hint": {"block_id": "block:1"}}
        ).to_assistant_request()

        self.assertEqual("q", request.question)
        self.assertFalse(request.allow_write_back)
        self.assertEqual("block:1", request.scope_hint.block_id)

    def test_request_id_is_generated_when_missing(self):
        from drawing_graph.assistant_mcp_models import AskDrawingAssistantInput

        request = AskDrawingAssistantInput.model_validate({"question": "q"}).to_assistant_request()
        self.assertTrue(request.request_id)

    def test_forbidden_fields_are_rejected(self):
        from drawing_graph.assistant_mcp_models import AskDrawingAssistantInput

        for forbidden in (
            {"write_back": True},
            {"allow_write_back": True},
            {"cypher": "MATCH (n) RETURN n"},
            {"neo4j_uri": "bolt://host"},
            {"password": "secret"},
            {"api_key": "key"},
            {"file_path": "/etc/passwd"},
            {"driver": object()},
            {"session": object()},
            {"repository": object()},
        ):
            with self.subTest(forbidden=forbidden):
                with self.assertRaises(ValidationError):
                    AskDrawingAssistantInput.model_validate({"question": "q", **forbidden})

    def test_unknown_fields_are_rejected(self):
        from drawing_graph.assistant_mcp_models import AskDrawingAssistantInput

        with self.assertRaises(ValidationError):
            AskDrawingAssistantInput.model_validate({"question": "q", "unknown": "x"})

    def test_empty_scope_hint_is_rejected(self):
        from drawing_graph.assistant_mcp_models import AskDrawingAssistantInput

        with self.assertRaises(ValidationError):
            AskDrawingAssistantInput.model_validate({"question": "q", "scope_hint": {}})

    def test_scope_hint_unknown_field_is_rejected(self):
        from drawing_graph.assistant_mcp_models import AskDrawingAssistantInput

        with self.assertRaises(ValidationError):
            AskDrawingAssistantInput.model_validate(
                {"question": "q", "scope_hint": {"database_id": "n:1"}}
            )

    def test_invalid_language_is_rejected(self):
        from drawing_graph.assistant_mcp_models import AskDrawingAssistantInput

        with self.assertRaises(ValidationError):
            AskDrawingAssistantInput.model_validate({"question": "q", "language": "fr"})


class AssistantScopeHintTests(unittest.TestCase):
    def test_empty_detection(self):
        from drawing_graph.assistant_mcp_models import AssistantScopeHint

        self.assertTrue(AssistantScopeHint().is_empty())
        self.assertFalse(AssistantScopeHint(page_id="page:1").is_empty())

    def test_to_assistant_scope(self):
        from drawing_graph.assistant_mcp_models import AssistantScopeHint

        scope = AssistantScopeHint(project_id="project:1", claim_id="claim:1").to_assistant_scope()
        self.assertEqual("project:1", scope.project_id)
        self.assertEqual("claim:1", scope.claim_id)


class McpAssistantResultMetaTests(unittest.TestCase):
    def test_meta_defaults(self):
        from drawing_graph.assistant_mcp_models import McpAssistantResultMeta

        meta = McpAssistantResultMeta(tool_name="ask_drawing_assistant", call_id="call-1")
        self.assertEqual("drawing-assistant-mcp-v1", meta.contract_version)
        self.assertEqual("ask_drawing_assistant", meta.tool_name)
        self.assertEqual("call-1", meta.call_id)


if __name__ == "__main__":
    unittest.main()
