import dataclasses
import unittest
from types import MappingProxyType

from drawing_graph.qa_models import (
    ALLOWED_FACT_KINDS,
    AnswerFact,
    EvidenceRef,
    QAAnswer,
    QAAnswerStatus,
    QAError,
    QAErrorCode,
    QARequest,
    QAScope,
    QuestionType,
)


class QuestionTypeTests(unittest.TestCase):
    def test_question_type_contains_all_phase_one_values(self):
        values = {item.value for item in QuestionType}
        self.assertEqual(
            {
                "page_summary",
                "block_relations",
                "candidate_relations",
                "section_matches",
                "table_caption_status",
                "diagnostic_status",
                "unknown_or_unsupported",
            },
            values,
        )

    def test_unknown_question_type_is_rejected(self):
        with self.assertRaises(QAError) as context:
            QARequest(question_type="not_a_question", scope=QAScope())
        self.assertEqual(QAErrorCode.INVALID_ARGUMENT, context.exception.category)


class QAScopeTests(unittest.TestCase):
    def test_empty_scope_is_allowed(self):
        scope = QAScope()
        self.assertIsNone(scope.page_id)
        self.assertIsNone(scope.block_id)

    def test_empty_string_id_is_rejected(self):
        with self.assertRaises(QAError) as context:
            QAScope(page_id="")
        self.assertEqual(QAErrorCode.INVALID_ARGUMENT, context.exception.category)

    def test_whitespace_only_id_is_rejected(self):
        with self.assertRaises(QAError):
            QAScope(block_id="   ")


class QARequestTests(unittest.TestCase):
    def test_default_request_is_read_only(self):
        request = QARequest(question_type=QuestionType.PAGE_SUMMARY, scope=QAScope(page_id="page:1"))
        self.assertFalse(request.write_back)
        self.assertTrue(request.include_semantics)
        self.assertTrue(request.include_candidates)
        self.assertEqual("zh", request.language)

    def test_write_back_true_is_representable_for_service_enforcement(self):
        request = QARequest(
            question_type=QuestionType.PAGE_SUMMARY,
            scope=QAScope(page_id="page:1"),
            write_back=True,
        )
        self.assertTrue(request.write_back)

    def test_invalid_language_is_rejected(self):
        with self.assertRaises(QAError) as context:
            QARequest(
                question_type=QuestionType.PAGE_SUMMARY,
                scope=QAScope(page_id="page:1"),
                language="fr",
            )
        self.assertEqual(QAErrorCode.INVALID_ARGUMENT, context.exception.category)

    def test_non_boolean_include_flags_are_rejected(self):
        with self.assertRaises(QAError):
            QARequest(
                question_type=QuestionType.PAGE_SUMMARY,
                scope=QAScope(page_id="page:1"),
                include_semantics="yes",
            )
        with self.assertRaises(QAError):
            QARequest(
                question_type=QuestionType.PAGE_SUMMARY,
                scope=QAScope(page_id="page:1"),
                include_candidates=1,
            )

    def test_question_type_string_is_coerced(self):
        request = QARequest(question_type="page_summary", scope=QAScope(page_id="page:1"))
        self.assertIs(QuestionType.PAGE_SUMMARY, request.question_type)

    def test_dto_is_frozen(self):
        request = QARequest(question_type=QuestionType.PAGE_SUMMARY, scope=QAScope(page_id="page:1"))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            request.summary = "changed"


class EvidenceRefTests(unittest.TestCase):
    def test_normal_construction(self):
        evidence = EvidenceRef(
            page_id="page:1",
            element_id="caption:1",
            image_path="data/road_24.png",
            bbox={"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
            observation_id="obs:1",
            recognition_run_id="run:1",
        )
        self.assertEqual("page:1", evidence.page_id)
        self.assertEqual("obs:1", evidence.observation_id)
        self.assertIsInstance(evidence.bbox, MappingProxyType)

    def test_invalid_bbox_is_rejected(self):
        with self.assertRaises(QAError) as context:
            EvidenceRef(bbox={"x_min": 5, "y_min": 2, "x_max": 3, "y_max": 4})
        self.assertEqual(QAErrorCode.INVALID_ARGUMENT, context.exception.category)

    def test_empty_optional_id_is_rejected(self):
        with self.assertRaises(QAError):
            EvidenceRef(recognition_run_id="")


class AnswerFactTests(unittest.TestCase):
    def test_allowed_fact_kinds_are_stable(self):
        self.assertEqual(
            {
                "source_fact",
                "derived_relation",
                "semantic_observation",
                "semantic_interpretation",
                "candidate_relation",
                "formal_relation",
                "diagnostic",
                "unsupported",
            },
            set(ALLOWED_FACT_KINDS),
        )

    def test_invalid_fact_kind_is_rejected(self):
        with self.assertRaises(QAError) as context:
            AnswerFact(fact_kind="formal_fact", label="x", status="confirmed")
        self.assertEqual(QAErrorCode.INVALID_ARGUMENT, context.exception.category)

    def test_candidate_relation_cannot_impersonate_formal(self):
        with self.assertRaises(QAError):
            AnswerFact(
                fact_kind="formal_relation",
                label="候选",
                status="candidate",
                relation_type="CANDIDATE_MATCHES_SECTION_CAPTION",
            )

    def test_candidate_relation_keeps_candidate_kind(self):
        fact = AnswerFact(
            fact_kind="candidate_relation",
            label="候选关系",
            status="candidate",
            relation_type="CANDIDATE_CAPTION_OF",
        )
        self.assertEqual("candidate_relation", fact.fact_kind)

    def test_ids_mapping_is_immutable_proxy(self):
        fact = AnswerFact(
            fact_kind="source_fact",
            label="页面",
            status="confirmed",
            ids={"page_id": "page:1"},
        )
        self.assertIsInstance(fact.ids, MappingProxyType)

    def test_invalid_ids_mapping_is_rejected(self):
        with self.assertRaises(QAError):
            AnswerFact(
                fact_kind="source_fact",
                label="页面",
                status="confirmed",
                ids={"page_id": 1},
            )


class QAAnswerTests(unittest.TestCase):
    def test_normal_construction(self):
        answer = QAAnswer(
            question_type=QuestionType.PAGE_SUMMARY,
            scope=QAScope(page_id="page:1"),
            status=QAAnswerStatus.ANSWERED,
            summary="页面存在",
            facts=(),
            warnings=("无语义证据",),
            unsupported_parts=(),
        )
        self.assertEqual("answered", answer.status.value)
        self.assertEqual(("无语义证据",), answer.warnings)

    def test_invalid_status_is_rejected(self):
        with self.assertRaises(QAError) as context:
            QAAnswer(
                question_type=QuestionType.PAGE_SUMMARY,
                scope=QAScope(page_id="page:1"),
                status="unknown",
                summary="x",
            )
        self.assertEqual(QAErrorCode.INVALID_ARGUMENT, context.exception.category)

    def test_empty_summary_is_rejected(self):
        with self.assertRaises(QAError):
            QAAnswer(
                question_type=QuestionType.PAGE_SUMMARY,
                scope=QAScope(page_id="page:1"),
                status="answered",
                summary="",
            )

    def test_non_tuple_facts_are_rejected(self):
        with self.assertRaises(QAError):
            QAAnswer(
                question_type=QuestionType.PAGE_SUMMARY,
                scope=QAScope(page_id="page:1"),
                status="answered",
                summary="x",
                facts=[AnswerFact(fact_kind="source_fact", label="x", status="confirmed")],
            )


class QAErrorTests(unittest.TestCase):
    def test_required_error_codes_exist(self):
        required = {
            "INVALID_ARGUMENT",
            "UNSUPPORTED_QUESTION",
            "UNSUPPORTED_SCOPE",
            "NOT_FOUND",
            "WRITE_BACK_FORBIDDEN",
            "FACADE_UNAVAILABLE",
            "NEO4J_UNAVAILABLE",
            "SEMANTIC_EVIDENCE_UNAVAILABLE",
            "INTERNAL_ERROR",
        }
        self.assertTrue(required.issubset({item.value for item in QAErrorCode}))

    def test_category_is_coerced_to_enum(self):
        error = QAError("NOT_FOUND", "not found")
        self.assertIs(QAErrorCode.NOT_FOUND, error.category)
        self.assertEqual("not found", str(error))

    def test_invalid_category_is_rejected(self):
        with self.assertRaises(QAError):
            QAError("NO_SUCH_CODE", "bad")


class NoBackendLeakTests(unittest.TestCase):
    def test_dto_fields_do_not_expose_driver_or_cypher(self):
        dto_classes = (QAScope, QARequest, EvidenceRef, AnswerFact, QAAnswer)
        for dto in dto_classes:
            field_names = {item.name for item in dataclasses.fields(dto)}
            for forbidden in ("driver", "session", "transaction", "cypher", "neo4j_uri", "password"):
                self.assertFalse(
                    any(forbidden in name.lower() for name in field_names),
                    f"{dto.__name__} exposes forbidden field {forbidden}",
                )


if __name__ == "__main__":
    unittest.main()
