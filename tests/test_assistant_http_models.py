"""Tests for the product HTTP request/response protocol models."""

import unittest

from pydantic import ValidationError


class HttpAssistantRequestTests(unittest.TestCase):
    def test_question_is_required_and_non_empty(self):
        from drawing_graph.assistant_http_models import HttpAssistantRequest

        with self.assertRaises(ValidationError):
            HttpAssistantRequest.model_validate({})
        with self.assertRaises(ValidationError):
            HttpAssistantRequest.model_validate({"question": ""})
        with self.assertRaises(ValidationError):
            HttpAssistantRequest.model_validate({"question": "   "})

    def test_question_is_length_limited(self):
        from drawing_graph.assistant_http_models import HttpAssistantRequest

        with self.assertRaises(ValidationError):
            HttpAssistantRequest.model_validate({"question": "x" * 2001})

    def test_converts_to_read_only_assistant_request(self):
        from drawing_graph.assistant_http_models import HttpAssistantRequest

        request = HttpAssistantRequest.model_validate(
            {
                "question": "这张图主要讲什么",
                "language": "zh-CN",
                "allow_recognition": True,
                "scope_hint": {"page_id": "page:1"},
            }
        ).to_assistant_request("req:1")

        self.assertEqual("req:1", request.request_id)
        self.assertEqual("这张图主要讲什么", request.question)
        self.assertFalse(request.allow_write_back)
        self.assertTrue(request.allow_recognition)
        self.assertEqual("page:1", request.scope_hint.page_id)

    def test_unknown_fields_are_rejected(self):
        from drawing_graph.assistant_http_models import HttpAssistantRequest

        with self.assertRaises(ValidationError):
            HttpAssistantRequest.model_validate({"question": "q", "unknown": "x"})

    def test_forbidden_fields_are_rejected(self):
        from drawing_graph.assistant_http_models import HttpAssistantRequest

        for forbidden in (
            {"write_back": True},
            {"allow_write_back": True},
            {"cypher": "MATCH (n) RETURN n"},
            {"neo4j_uri": "bolt://host"},
            {"password": "secret"},
            {"token": "abc"},
            {"api_key": "key"},
            {"driver": object()},
            {"session": object()},
            {"repository": object()},
        ):
            with self.subTest(forbidden=forbidden):
                with self.assertRaises(ValidationError):
                    HttpAssistantRequest.model_validate({"question": "q", **forbidden})

    def test_scope_hint_rejects_unknown_ids(self):
        from drawing_graph.assistant_http_models import HttpAssistantRequest

        with self.assertRaises(ValidationError):
            HttpAssistantRequest.model_validate(
                {"question": "q", "scope_hint": {"database_id": "n:1"}}
            )

    def test_empty_scope_hint_gives_none_scope(self):
        from drawing_graph.assistant_http_models import HttpAssistantRequest

        request = HttpAssistantRequest.model_validate(
            {"question": "q", "scope_hint": {}}
        ).to_assistant_request("req:1")
        self.assertIsNone(request.scope_hint)

    def test_no_scope_hint_gives_none_scope(self):
        from drawing_graph.assistant_http_models import HttpAssistantRequest

        request = HttpAssistantRequest.model_validate({"question": "q"}).to_assistant_request("req:1")
        self.assertIsNone(request.scope_hint)


class HttpAssistantScopeHintTests(unittest.TestCase):
    def test_scope_hint_maps_all_stable_ids(self):
        from drawing_graph.assistant_http_models import HttpAssistantScopeHint

        scope = HttpAssistantScopeHint.model_validate(
            {
                "project_id": "project:1",
                "drawing_set_id": "set:1",
                "page_id": "page:1",
                "block_id": "block:1",
                "element_id": "element:1",
                "cross_section_id": "cs:1",
                "table_id": "table:1",
                "table_caption_id": "caption:1",
                "claim_id": "claim:1",
            }
        ).to_assistant_scope()

        self.assertEqual("project:1", scope.project_id)
        self.assertEqual("claim:1", scope.claim_id)

    def test_scope_hint_rejects_blank_ids(self):
        from drawing_graph.assistant_http_models import HttpAssistantScopeHint

        with self.assertRaises(ValidationError):
            HttpAssistantScopeHint.model_validate({"page_id": "  "})


class HttpAssistantEnvelopeTests(unittest.TestCase):
    def test_http_answer_validates_projection(self):
        from drawing_graph.assistant_http_models import http_answer_from_package

        answer = http_answer_from_package(
            {
                "answer_contract_version": "drawing-assistant-answer-v1",
                "request_id": "req:1",
                "status": "answered",
                "machine_answer": {"status": "answered"},
                "text_answer": "答案",
                "claims": [{"claim_id": "claim:1", "statement": "s"}],
                "citations": [],
                "warnings": ["warn-a"],
                "unsupported_parts": [],
                "recognition_run_ids": ["run:1"],
            }
        )
        self.assertEqual("answered", answer.status)
        self.assertEqual("答案", answer.text_answer)
        self.assertEqual("claim:1", answer.claims[0]["claim_id"])


if __name__ == "__main__":
    unittest.main()
