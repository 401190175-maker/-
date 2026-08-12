"""Tests for constrained model client protocol and fake client."""

from pathlib import Path
import inspect
import unittest

from drawing_graph.assistant_models import ReasonCode
from drawing_graph.assistant_question_llm import (
    FakeQuestionUnderstandingModelClient,
    QuestionUnderstandingCandidate,
    QuestionUnderstandingModelClient,
    validate_model_output,
)


class QuestionUnderstandingModelProtocolTests(unittest.TestCase):
    def test_protocol_declares_understand_method(self):
        self.assertTrue(hasattr(QuestionUnderstandingModelClient, "understand"))

    def test_candidate_carries_constrained_fields(self):
        candidate = QuestionUnderstandingCandidate(
            question_type="page_summary",
            confidence=0.8,
            ambiguities=("ambiguous",),
            unsupported_parts=("ocr",),
        )
        self.assertEqual("page_summary", candidate.question_type)
        self.assertEqual(0.8, candidate.confidence)
        self.assertEqual(("ambiguous",), candidate.ambiguities)
        self.assertEqual(("ocr",), candidate.unsupported_parts)

    def test_candidate_defaults_to_empty_tuples(self):
        candidate = QuestionUnderstandingCandidate(
            question_type="unknown_or_unsupported",
            confidence=0.0,
        )
        self.assertEqual((), candidate.ambiguities)
        self.assertEqual((), candidate.unsupported_parts)

    def test_candidate_rejects_invalid_confidence(self):
        with self.assertRaises(ValueError):
            QuestionUnderstandingCandidate(question_type="page_summary", confidence=1.5)

    def test_module_does_not_import_external_clients_or_read_env(self):
        module_path = Path(inspect.getfile(QuestionUnderstandingModelClient))
        source = module_path.read_text(encoding="utf-8").lower()
        for token in (
            "import dashscope",
            "import openai",
            "import requests",
            "import urllib",
            "import httpx",
            "environ",
            "getenv",
            "api_key",
        ):
            self.assertNotIn(token, source)


class FakeQuestionUnderstandingModelClientTests(unittest.TestCase):
    def test_fake_client_returns_configured_candidate_without_network(self):
        candidate = QuestionUnderstandingCandidate(
            question_type="page_summary",
            confidence=0.9,
        )
        client = FakeQuestionUnderstandingModelClient(candidate)
        result = client.understand("问题", None)
        self.assertIs(candidate, result)

    def test_fake_client_defaults_to_unknown_candidate(self):
        client = FakeQuestionUnderstandingModelClient()
        result = client.understand("问题", None)
        self.assertEqual("unknown_or_unsupported", result.question_type)

    def test_fake_client_source_has_no_network_or_env_dependency(self):
        module_path = Path(inspect.getfile(FakeQuestionUnderstandingModelClient))
        source = module_path.read_text(encoding="utf-8").lower()
        for token in (
            "import requests",
            "import urllib",
            "import httpx",
            "import socket",
            "environ",
        ):
            self.assertNotIn(token, source)


class ModelOutputValidationTests(unittest.TestCase):
    def test_valid_output_returns_candidate(self):
        validation = validate_model_output(
            {"question_type": "page_summary", "confidence": 0.9}
        )
        self.assertIsNotNone(validation.candidate)
        self.assertEqual("page_summary", validation.candidate.question_type)
        self.assertEqual((), validation.reason_codes)

    def test_invalid_question_type_returns_model_output_invalid(self):
        validation = validate_model_output(
            {"question_type": "formal_relation", "confidence": 0.9}
        )
        self.assertIsNone(validation.candidate)
        self.assertIn(
            ReasonCode.MODEL_OUTPUT_INVALID.value,
            validation.reason_codes,
        )

    def test_output_with_forbidden_keys_is_rejected(self):
        for extra_key in ("write_back", "cypher", "source_fact", "formal_relation"):
            with self.subTest(key=extra_key):
                raw = {
                    "question_type": "page_summary",
                    "confidence": 0.9,
                    extra_key: True,
                }
                validation = validate_model_output(raw)
                self.assertIsNone(validation.candidate)
                self.assertIn("model_output_invalid", validation.reason_codes)

    def test_invalid_confidence_is_rejected(self):
        validation = validate_model_output(
            {"question_type": "page_summary", "confidence": 2.0}
        )
        self.assertIsNone(validation.candidate)
        self.assertIn("model_output_invalid", validation.reason_codes)

    def test_invalid_output_never_produces_facts_or_queries(self):
        validation = validate_model_output(
            {"question_type": "formal_relation", "confidence": 0.9}
        )
        self.assertIsNone(validation.candidate)


if __name__ == "__main__":
    unittest.main()
