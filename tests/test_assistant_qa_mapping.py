"""Tests for the QA-to-product retrieval mapping adapter."""

from pathlib import Path
import inspect
import unittest

from drawing_graph.assistant_models import EvidenceType, QuestionType
from drawing_graph.assistant_qa_mapping import qa_request_to_question_result
from drawing_graph.qa_models import QARequest, QAScope, QuestionType


def make_request(
    question_type: QuestionType,
    *,
    include_semantics: bool = True,
    include_candidates: bool = True,
) -> QARequest:
    return QARequest(
        question_type=question_type,
        scope=QAScope(page_id="page:1", block_id="block:1"),
        include_semantics=include_semantics,
        include_candidates=include_candidates,
    )


def evidence_types(result) -> set[EvidenceType]:
    return {requirement.evidence_type for requirement in result.required_evidence}


class QaRequestToQuestionResultTests(unittest.TestCase):
    def test_page_summary_maps_to_source_observations_and_interpretations(self):
        result = qa_request_to_question_result(
            make_request(QuestionType.PAGE_SUMMARY)
        )
        self.assertEqual("qa:page_summary", result.request_id)
        self.assertEqual(
            {
                EvidenceType.PAGE_SOURCE_FACTS,
                EvidenceType.TEXT_OBSERVATIONS,
                EvidenceType.STRUCTURED_INTERPRETATIONS,
            },
            evidence_types(result),
        )

    def test_block_relations_maps_to_trace_and_relations(self):
        result = qa_request_to_question_result(
            make_request(QuestionType.BLOCK_RELATIONS)
        )
        self.assertEqual(
            {EvidenceType.BLOCK_TRACE, EvidenceType.BLOCK_RELATIONS},
            evidence_types(result),
        )

    def test_candidate_relations_maps_to_candidate_requirement(self):
        result = qa_request_to_question_result(
            make_request(QuestionType.CANDIDATE_RELATIONS)
        )
        self.assertEqual({EvidenceType.CANDIDATE_RELATIONS}, evidence_types(result))

    def test_section_matches_maps_to_section_requirement(self):
        result = qa_request_to_question_result(
            make_request(QuestionType.SECTION_MATCHES)
        )
        self.assertEqual({EvidenceType.SECTION_MATCHES}, evidence_types(result))

    def test_table_caption_status_maps_to_page_source_facts(self):
        result = qa_request_to_question_result(
            make_request(QuestionType.TABLE_CAPTION_STATUS)
        )
        self.assertIn(EvidenceType.PAGE_SOURCE_FACTS, evidence_types(result))

    def test_diagnostic_status_maps_to_source_and_relation_status(self):
        result = qa_request_to_question_result(
            make_request(QuestionType.DIAGNOSTIC_STATUS)
        )
        types = evidence_types(result)
        self.assertIn(EvidenceType.PAGE_SOURCE_FACTS, types)
        self.assertIn(EvidenceType.CANDIDATE_RELATIONS, types)

    def test_include_semantics_false_removes_semantic_requirements(self):
        result = qa_request_to_question_result(
            make_request(QuestionType.PAGE_SUMMARY, include_semantics=False)
        )
        self.assertEqual({EvidenceType.PAGE_SOURCE_FACTS}, evidence_types(result))

    def test_include_candidates_false_removes_candidate_requirement(self):
        result = qa_request_to_question_result(
            make_request(QuestionType.CANDIDATE_RELATIONS, include_candidates=False)
        )
        self.assertEqual(set(), evidence_types(result))

    def test_scope_fields_are_mapped_to_assistant_scope(self):
        request = QARequest(
            question_type=QuestionType.BLOCK_RELATIONS,
            scope=QAScope(
                project_id="project:1",
                drawing_set_id="set:1",
                page_id="page:1",
                block_id="block:1",
                element_id="element:1",
                cross_section_id="section:1",
                table_id="table:1",
                table_caption_id="caption:1",
            ),
        )
        result = qa_request_to_question_result(request)
        scope = result.required_evidence[0].target_scope
        self.assertEqual("project:1", scope.project_id)
        self.assertEqual("page:1", scope.page_id)
        self.assertEqual("block:1", scope.block_id)
        self.assertEqual("caption:1", scope.table_caption_id)
        self.assertIsNone(scope.claim_id)


class QaServiceBoundaryTests(unittest.TestCase):
    def test_qa_service_does_not_import_assistant_modules(self):
        from drawing_graph import qa_service

        module_path = Path(inspect.getfile(qa_service))
        source = module_path.read_text(encoding="utf-8")
        self.assertNotIn("assistant_", source)


class QaQuestionTypeCompatibilityTests(unittest.TestCase):
    def test_all_six_qa_types_map_to_product_question_type_constants(self):
        expected = {
            QuestionType.PAGE_SUMMARY: "page_summary",
            QuestionType.BLOCK_RELATIONS: "block_relations",
            QuestionType.CANDIDATE_RELATIONS: "candidate_relations",
            QuestionType.SECTION_MATCHES: "section_matches",
            QuestionType.TABLE_CAPTION_STATUS: "table_caption_status",
            QuestionType.DIAGNOSTIC_STATUS: "drawing_diagnostic",
        }
        for qa_type, expected_type in expected.items():
            with self.subTest(qa_type=qa_type):
                result = qa_request_to_question_result(make_request(qa_type))
                self.assertEqual(expected_type, result.question_type)

    def test_unknown_qa_type_maps_to_product_unknown(self):
        result = qa_request_to_question_result(
            make_request(QuestionType.UNKNOWN_OR_UNSUPPORTED)
        )
        self.assertEqual("unknown_or_unsupported", result.question_type)


if __name__ == "__main__":
    unittest.main()
