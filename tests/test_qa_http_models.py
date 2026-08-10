"""Tests for HTTP request/response protocol models."""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from drawing_graph.qa_models import (
    AnswerFact,
    EvidenceRef,
    QAAnswer,
    QAAnswerStatus,
    QAScope,
    QuestionType,
)


class HttpQARequestTests(unittest.TestCase):
    """HttpQARequest must whitelist fields and convert to the domain QARequest."""

    def test_valid_page_summary_maps_to_domain_request(self):
        from drawing_graph.qa_http_models import HttpQARequest

        http_request = HttpQARequest(
            question_type="page_summary",
            scope={"page_id": "page:1"},
            language="zh",
            include_semantics=True,
            include_candidates=True,
            include_payload=False,
            write_back=False,
        )

        request = http_request.to_domain()

        self.assertIs(QuestionType.PAGE_SUMMARY, request.question_type)
        self.assertEqual("page:1", request.scope.page_id)
        self.assertIsNone(request.scope.block_id)
        self.assertEqual("zh", request.language)
        self.assertFalse(request.write_back)
        self.assertEqual("json", request.format_hint)

    def test_all_six_question_types_are_accepted(self):
        from drawing_graph.qa_http_models import HttpQARequest

        for question_type in (
            "page_summary",
            "block_relations",
            "candidate_relations",
            "section_matches",
            "table_caption_status",
            "diagnostic_status",
        ):
            http_request = HttpQARequest(
                question_type=question_type,
                scope={"page_id": "page:1"},
            )
            self.assertEqual(question_type, http_request.question_type.value)

    def test_unknown_or_unsupported_is_not_exposed_to_clients(self):
        from drawing_graph.qa_http_models import HttpQARequest

        with self.assertRaises(ValidationError):
            HttpQARequest(
                question_type="unknown_or_unsupported",
                scope={"page_id": "page:1"},
            )

    def test_extra_fields_and_sensitive_fields_are_rejected(self):
        from drawing_graph.qa_http_models import HttpQARequest

        for extra in (
            {"neo4j_password": "secret"},
            {"api_token": "token"},
            {"cypher": "MATCH (n)"},
            {"driver": object()},
            {"unexpected": "value"},
        ):
            payload = {
                "question_type": "page_summary",
                "scope": {"page_id": "page:1"},
                **extra,
            }
            with self.assertRaises(ValidationError):
                HttpQARequest(**payload)

    def test_language_is_restricted_to_zh_or_en(self):
        from drawing_graph.qa_http_models import HttpQARequest

        with self.assertRaises(ValidationError):
            HttpQARequest(
                question_type="page_summary",
                scope={"page_id": "page:1"},
                language="fr",
            )

    def test_include_flags_and_write_back_must_be_boolean(self):
        from drawing_graph.qa_http_models import HttpQARequest

        for field_name in ("include_semantics", "include_candidates", "include_payload", "write_back"):
            with self.assertRaises(ValidationError):
                HttpQARequest(
                    question_type="page_summary",
                    scope={"page_id": "page:1"},
                    **{field_name: "yes"},
                )

    def test_blank_or_overlong_scope_ids_are_rejected(self):
        from drawing_graph.qa_http_models import HttpQARequest

        for scope in ({"page_id": ""}, {"page_id": "   "}, {"page_id": "x" * 201}):
            with self.assertRaises(ValidationError):
                HttpQARequest(question_type="page_summary", scope=scope)

    def test_write_back_true_is_parseable_for_service_enforcement(self):
        from drawing_graph.qa_http_models import HttpQARequest

        http_request = HttpQARequest(
            question_type="page_summary",
            scope={"page_id": "page:1"},
            write_back=True,
        )
        self.assertTrue(http_request.write_back)
        self.assertTrue(http_request.to_domain().write_back)

    def test_request_model_exposes_no_sensitive_fields(self):
        from drawing_graph.qa_http_models import HttpQARequest, HttpQAScope

        for model in (HttpQARequest, HttpQAScope):
            field_names = set(model.model_fields)
            for forbidden in ("uri", "user", "password", "token", "cypher", "driver", "session", "transaction"):
                self.assertFalse(
                    any(forbidden in name.lower() for name in field_names),
                    f"{model.__name__} exposes forbidden field {forbidden}",
                )


class HttpQAResponseTests(unittest.TestCase):
    """Response models must validate serialized answers without upgrading facts."""

    def test_qa_answer_roundtrip_preserves_fact_kinds_and_evidence(self):
        from drawing_graph.qa_http_models import http_answer_from_qa_answer

        answer = QAAnswer(
            question_type=QuestionType.CANDIDATE_RELATIONS,
            scope=QAScope(page_id="page:1"),
            status=QAAnswerStatus.PARTIAL,
            summary="候选关系部分可用",
            facts=(
                AnswerFact(
                    fact_kind="source_fact",
                    label="页面",
                    status="confirmed",
                    ids={"page_id": "page:1"},
                ),
                AnswerFact(
                    fact_kind="candidate_relation",
                    label="候选关系",
                    status="matched_candidate",
                    relation_type="CANDIDATE_MATCHES_SECTION_CAPTION",
                    evidence=(
                        EvidenceRef(
                            page_id="page:1",
                            image_path="data/road_24.png",
                            bbox={"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
                            recognition_run_id="run:1",
                        ),
                    ),
                ),
                AnswerFact(
                    fact_kind="formal_relation",
                    label="正式匹配",
                    status="confirmed",
                    relation_type="MATCHES_SECTION_CAPTION",
                ),
            ),
            warnings=("语义证据不可用",),
            unsupported_parts=("live Neo4j 验证未执行",),
            source_calls=("list_candidate_relations",),
        )

        http_answer = http_answer_from_qa_answer(answer)

        self.assertEqual("candidate_relations", http_answer.question_type)
        self.assertEqual("page:1", http_answer.scope.page_id)
        self.assertEqual("partial", http_answer.status)
        self.assertEqual(
            ["source_fact", "candidate_relation", "formal_relation"],
            [fact.fact_kind for fact in http_answer.facts],
        )
        self.assertEqual(
            "CANDIDATE_MATCHES_SECTION_CAPTION",
            http_answer.facts[1].relation_type,
        )
        self.assertEqual("run:1", http_answer.facts[1].evidence[0].recognition_run_id)
        self.assertEqual(3.0, http_answer.facts[1].evidence[0].bbox["x_max"])
        self.assertEqual(["live Neo4j 验证未执行"], http_answer.unsupported_parts)

    def test_candidate_relation_keeps_candidate_kind(self):
        from drawing_graph.qa_http_models import HttpAnswerFact

        fact = HttpAnswerFact(
            fact_kind="candidate_relation",
            label="候选",
            status="matched_candidate",
            relation_type="CANDIDATE_CAPTION_OF",
        )
        self.assertEqual("candidate_relation", fact.fact_kind)

    def test_candidate_relation_type_cannot_be_formal(self):
        from drawing_graph.qa_http_models import HttpAnswerFact

        with self.assertRaises(ValidationError):
            HttpAnswerFact(
                fact_kind="formal_relation",
                label="正式",
                status="confirmed",
                relation_type="CANDIDATE_CAPTION_OF",
            )

    def test_matched_candidate_status_cannot_be_formal(self):
        from drawing_graph.qa_http_models import HttpAnswerFact

        with self.assertRaises(ValidationError):
            HttpAnswerFact(
                fact_kind="formal_relation",
                label="正式",
                status="matched_candidate",
                relation_type="MATCHES_SECTION_CAPTION",
            )

    def test_success_and_error_envelopes_validate(self):
        from drawing_graph.qa_http_models import (
            HttpErrorEnvelope,
            HttpSuccessEnvelope,
            http_answer_from_qa_answer,
        )

        answer = QAAnswer(
            question_type=QuestionType.PAGE_SUMMARY,
            scope=QAScope(page_id="page:1"),
            status=QAAnswerStatus.ANSWERED,
            summary="页面存在",
        )
        success = HttpSuccessEnvelope(
            status="ok",
            data=http_answer_from_qa_answer(answer).model_dump(),
            meta={"request_id": "req-1", "contract_version": "drawing-qa-http-v1"},
        )
        self.assertEqual("ok", success.status)
        self.assertEqual("req-1", success.meta.request_id)

        failure = HttpErrorEnvelope(
            status="failed",
            error={"category": "NOT_FOUND", "message": "not found", "retryable": False},
            meta={"request_id": "req-2"},
        )
        self.assertEqual("NOT_FOUND", failure.error.category)
        self.assertIsNone(failure.error.details)

    def test_health_response_carries_not_checked_neo4j_status(self):
        from drawing_graph.qa_http_models import HttpHealthResponse

        ready = HttpHealthResponse(
            status="ready",
            service="drawing-graph-qa-http",
            contract_version="drawing-qa-http-v1",
            neo4j_status="not_checked",
        )
        self.assertEqual("not_checked", ready.neo4j_status)

    def test_evidence_model_exposes_no_neo4j_internal_fields(self):
        from drawing_graph.qa_http_models import HttpEvidenceRef

        field_names = set(HttpEvidenceRef.model_fields)
        for forbidden in ("node_id", "neo4j_id", "driver", "session", "transaction", "cypher", "password"):
            self.assertFalse(
                any(forbidden in name.lower() for name in field_names),
                f"HttpEvidenceRef exposes forbidden field {forbidden}",
            )


if __name__ == "__main__":
    unittest.main()
