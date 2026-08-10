"""Tests for the framework-independent QA JSON serialization module."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import MappingProxyType

from drawing_graph.qa_models import (
    AnswerFact,
    EvidenceRef,
    QAAnswer,
    QAAnswerStatus,
    QAScope,
    QuestionType,
)


class QaJsonableTests(unittest.TestCase):
    """to_jsonable() must convert QA DTOs to JSON-encodable values."""

    def test_dataclass_with_nested_dto_becomes_dict(self):
        answer = QAAnswer(
            question_type=QuestionType.PAGE_SUMMARY,
            scope=QAScope(page_id="page:1"),
            status=QAAnswerStatus.ANSWERED,
            summary="页面存在，共 3 个元素",
            facts=(
                AnswerFact(
                    fact_kind="source_fact",
                    label="页面",
                    status="confirmed",
                    ids={"page_id": "page:1"},
                    evidence=(
                        EvidenceRef(
                            page_id="page:1",
                            image_path="data/road_24.png",
                            bbox={"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
                        ),
                    ),
                ),
            ),
        )

        from drawing_graph.qa_serialization import to_jsonable

        converted = to_jsonable(answer)

        self.assertEqual("page_summary", converted["question_type"])
        self.assertEqual("answered", converted["status"])
        self.assertEqual("page:1", converted["scope"]["page_id"])
        self.assertEqual("source_fact", converted["facts"][0]["fact_kind"])
        self.assertEqual("confirmed", converted["facts"][0]["status"])
        self.assertEqual("page:1", converted["facts"][0]["ids"]["page_id"])
        self.assertEqual("data/road_24.png", converted["facts"][0]["evidence"][0]["image_path"])
        self.assertEqual(3.0, converted["facts"][0]["evidence"][0]["bbox"]["x_max"])

    def test_enum_values_are_converted_to_strings(self):
        from drawing_graph.qa_serialization import to_jsonable

        self.assertEqual("page_summary", to_jsonable(QuestionType.PAGE_SUMMARY))
        self.assertEqual("partial", to_jsonable(QAAnswerStatus.PARTIAL))

    def test_tuple_and_list_are_converted_to_lists(self):
        from drawing_graph.qa_serialization import to_jsonable

        self.assertEqual(["a", "b"], to_jsonable(("a", "b")))
        self.assertEqual([1, 2], to_jsonable([1, 2]))
        self.assertEqual([[1], [2]], to_jsonable(((1,), (2,))))

    def test_path_is_converted_to_string(self):
        from drawing_graph.qa_serialization import to_jsonable

        converted = to_jsonable(Path("data/scan.png"))
        self.assertIsInstance(converted, str)
        self.assertEqual(Path("data/scan.png"), Path(converted))

    def test_mapping_proxy_and_plain_dict_are_converted(self):
        from drawing_graph.qa_serialization import to_jsonable

        proxy = MappingProxyType({"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4})
        self.assertEqual(
            {"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
            to_jsonable(proxy),
        )
        self.assertEqual({"nested": ["v"]}, to_jsonable({"nested": ("v",)}))

    def test_primitives_and_none_are_preserved(self):
        from drawing_graph.qa_serialization import to_jsonable

        self.assertIsNone(to_jsonable(None))
        self.assertEqual(1, to_jsonable(1))
        self.assertEqual(1.5, to_jsonable(1.5))
        self.assertIs(True, to_jsonable(True))
        self.assertEqual("text", to_jsonable("text"))
        self.assertEqual([], to_jsonable(()))
        self.assertEqual({}, to_jsonable({}))

    def test_candidate_relation_kind_is_preserved(self):
        fact = AnswerFact(
            fact_kind="candidate_relation",
            label="候选关系",
            status="candidate",
            relation_type="CANDIDATE_CAPTION_OF",
        )

        from drawing_graph.qa_serialization import to_jsonable

        converted = to_jsonable(fact)
        self.assertEqual("candidate_relation", converted["fact_kind"])
        self.assertEqual("CANDIDATE_CAPTION_OF", converted["relation_type"])
        self.assertEqual("candidate", converted["status"])

    def test_full_answer_is_json_serializable(self):
        answer = QAAnswer(
            question_type=QuestionType.DIAGNOSTIC_STATUS,
            scope=QAScope(page_id="page:1", block_id="block:1"),
            status=QAAnswerStatus.PARTIAL,
            summary="部分诊断可用",
            warnings=("语义证据不可用",),
            unsupported_parts=("live Neo4j 验证未执行",),
            source_calls=("read_page_source_facts",),
        )

        from drawing_graph.qa_serialization import to_jsonable

        encoded = json.dumps(to_jsonable(answer), ensure_ascii=False)
        self.assertIn('"warnings": ["语义证据不可用"]', encoded)
        self.assertIn('"question_type": "diagnostic_status"', encoded)


class QaEnvelopeTests(unittest.TestCase):
    """Envelope builders must keep CLI/HTTP top-level contracts stable."""

    def test_success_envelope_without_meta_keeps_cli_shape(self):
        from drawing_graph.qa_serialization import build_success_envelope

        envelope = build_success_envelope({"question_type": "page_summary"})
        self.assertEqual("ok", envelope["status"])
        self.assertEqual({"question_type": "page_summary"}, envelope["data"])
        self.assertNotIn("meta", envelope)

    def test_success_envelope_with_meta(self):
        from drawing_graph.qa_serialization import build_success_envelope

        envelope = build_success_envelope(
            {"question_type": "page_summary"},
            meta={"request_id": "req-1", "contract_version": "drawing-qa-http-v1"},
        )
        self.assertEqual("ok", envelope["status"])
        self.assertEqual("req-1", envelope["meta"]["request_id"])

    def test_error_envelope_structure(self):
        from drawing_graph.qa_serialization import build_error_envelope

        envelope = build_error_envelope(
            "NOT_FOUND",
            "page not found",
            retryable=False,
            meta={"request_id": "req-2"},
        )
        self.assertEqual("failed", envelope["status"])
        self.assertEqual("NOT_FOUND", envelope["error"]["category"])
        self.assertEqual("page not found", envelope["error"]["message"])
        self.assertIs(False, envelope["error"]["retryable"])
        self.assertEqual("req-2", envelope["meta"]["request_id"])

    def test_error_envelope_without_details_omits_details(self):
        from drawing_graph.qa_serialization import build_error_envelope

        envelope = build_error_envelope("INVALID_ARGUMENT", "invalid", retryable=False)
        self.assertNotIn("details", envelope["error"])

    def test_error_envelope_with_details(self):
        from drawing_graph.qa_serialization import build_error_envelope

        envelope = build_error_envelope(
            "INVALID_ARGUMENT",
            "invalid",
            retryable=False,
            details=[{"field": "page_id", "type": "missing"}],
        )
        self.assertEqual([{"field": "page_id", "type": "missing"}], envelope["error"]["details"])

    def test_envelopes_are_json_serializable(self):
        from drawing_graph.qa_serialization import build_error_envelope, build_success_envelope

        success = build_success_envelope({"status": "answered"}, meta={"request_id": "r1"})
        failure = build_error_envelope("INTERNAL_ERROR", "boom", retryable=False)
        json.dumps(success)
        json.dumps(failure)


class QaSanitizationTests(unittest.TestCase):
    """sanitize_error_message() must hide secrets and backend internals."""

    def test_password_secret_and_token_are_removed(self):
        from drawing_graph.qa_serialization import sanitize_error_message

        message = "login failed: password=sup3rS3cret api_token=abc123"
        sanitized = sanitize_error_message(message)
        self.assertNotIn("sup3rS3cret", sanitized)
        self.assertNotIn("abc123", sanitized)
        self.assertNotIn("password", sanitized)
        self.assertNotIn("token", sanitized)

    def test_bolt_neo4j_and_cypher_details_are_removed(self):
        from drawing_graph.qa_serialization import sanitize_error_message

        message = "bolt://neo4j:secret@localhost:7687 failed; cypher MATCH (n) RETURN n"
        sanitized = sanitize_error_message(message)
        self.assertNotIn("neo4j:secret@localhost", sanitized)
        self.assertNotIn("MATCH (n)", sanitized)
        self.assertNotIn("bolt://", sanitized)
        self.assertNotIn("cypher", sanitized)

    def test_driver_session_transaction_and_traceback_are_removed(self):
        from drawing_graph.qa_serialization import sanitize_error_message

        message = "driver session transaction Traceback (most recent call last) at 0x7f00"
        sanitized = sanitize_error_message(message)
        self.assertNotIn("driver", sanitized)
        self.assertNotIn("session", sanitized)
        self.assertNotIn("transaction", sanitized)
        self.assertNotIn("Traceback", sanitized)

    def test_safe_business_message_stays_readable(self):
        from drawing_graph.qa_serialization import sanitize_error_message

        message = "page_id is required for page_summary"
        self.assertEqual(message, sanitize_error_message(message))

    def test_input_is_not_mutated_and_result_is_string(self):
        from drawing_graph.qa_serialization import sanitize_error_message

        message = "password=secret value"
        sanitized = sanitize_error_message(message)
        self.assertIsInstance(sanitized, str)
        self.assertEqual("password=secret value", message)


if __name__ == "__main__":
    unittest.main()
