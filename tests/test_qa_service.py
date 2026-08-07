import unittest

from drawing_graph.tool_models import (
    BBox,
    BlockRelations,
    BlockTrace,
    CandidateRelationSummary,
    ElementEvidence,
    PageSourceFacts,
    SectionMatchSummary,
    SemanticInterpretationSummary,
    SemanticObservationSummary,
    ToolModelError,
)
from drawing_graph.qa_models import (
    QAAnswer,
    QAAnswerStatus,
    QAError,
    QAErrorCode,
    QARequest,
    QAScope,
    QuestionType,
)
from drawing_graph.qa_service import DrawingGraphQAService


class FakeFacade:
    """Facade double that records calls and returns configured fixtures."""

    def __init__(
        self,
        *,
        page_facts=None,
        observations=(),
        interpretations=(),
        page_error=None,
        observation_error=None,
        interpretation_error=None,
        block_trace=None,
        block_relations=None,
        candidates=(),
        trace_error=None,
        relations_error=None,
        candidates_error=None,
        section_matches=(),
        section_matches_error=None,
        match_decision=None,
        match_error=None,
    ):
        self.calls = []
        self.page_facts = page_facts
        self.observations = observations
        self.interpretations = interpretations
        self.page_error = page_error
        self.observation_error = observation_error
        self.interpretation_error = interpretation_error
        self.block_trace = block_trace
        self.block_relations = block_relations
        self.candidates = candidates
        self.trace_error = trace_error
        self.relations_error = relations_error
        self.candidates_error = candidates_error
        self.section_matches = section_matches
        self.section_matches_error = section_matches_error
        self.match_decision = match_decision
        self.match_error = match_error

    def get_page_source_facts(self, page_id, element_types=None, include_image_meta=True):
        self.calls.append(("get_page_source_facts", page_id))
        if self.page_error is not None:
            raise self.page_error
        return self.page_facts

    def list_text_observations(self, page_id=None, element_id=None, recognition_run_id=None, statuses=None):
        self.calls.append(("list_text_observations", page_id))
        if self.observation_error is not None:
            raise self.observation_error
        if not self.observations:
            raise ToolModelError("NOT_FOUND", "text observations were not found")
        return self.observations

    def list_interpretations(self, page_id=None, element_id=None, recognition_run_id=None, statuses=None):
        self.calls.append(("list_interpretations", page_id))
        if self.interpretation_error is not None:
            raise self.interpretation_error
        if not self.interpretations:
            raise ToolModelError("NOT_FOUND", "semantic interpretations were not found")
        return self.interpretations

    def get_block_trace(self, block_id, write_back=False):
        self.calls.append(("get_block_trace", block_id))
        if self.trace_error is not None:
            raise self.trace_error
        return self.block_trace

    def get_block_relations(self, block_id, write_back=False):
        self.calls.append(("get_block_relations", block_id))
        if self.relations_error is not None:
            raise self.relations_error
        return self.block_relations

    def list_candidate_relations(self, page_id=None, block_id=None, relation_type=None, status=None, write_back=False):
        self.calls.append(("list_candidate_relations", page_id, block_id))
        if self.candidates_error is not None:
            raise self.candidates_error
        if not self.candidates:
            raise ToolModelError("NOT_FOUND", "candidate relations were not found")
        return self.candidates

    def list_section_matches(self, cross_section_id=None, page_id=None, statuses=None, write_back=False):
        self.calls.append(("list_section_matches", cross_section_id, page_id, statuses))
        if self.section_matches_error is not None:
            raise self.section_matches_error
        if not self.section_matches:
            raise ToolModelError("NOT_FOUND", "section matches were not found")
        return self.section_matches

    def match_section_caption(self, cross_section_id, page_id=None, write_back=False, rule_version="section-match-v1"):
        self.calls.append(("match_section_caption", cross_section_id, page_id, write_back))
        if self.match_error is not None:
            raise self.match_error
        return self.match_decision


def _request(question_type, **scope_values):
    return QARequest(question_type=question_type, scope=QAScope(**scope_values))


def _canned_answer(request):
    return QAAnswer(
        question_type=request.question_type,
        scope=request.scope,
        status=QAAnswerStatus.ANSWERED,
        summary="handled",
    )


def _bbox(x_min=1, y_min=2, x_max=3, y_max=4):
    return BBox(x_min, y_min, x_max, y_max)


def _normalized_bbox():
    return BBox(0.1, 0.2, 0.3, 0.4)


def _element(element_id="block:1", element_type="DrawingBlock", source_label="block"):
    return ElementEvidence(
        element_id=element_id,
        element_type=element_type,
        bbox=_bbox(),
        normalized_bbox=_normalized_bbox(),
        source_label=source_label,
    )


def _page_facts(page_id="page:1", elements=()):
    return PageSourceFacts(
        page_id=page_id,
        image_path="data/road_24.png",
        elements=tuple(elements),
        image_size=(1000, 800),
    )


def _observation(observation_id="obs:1", element_id="caption:1", page_id="page:1", status="confirmed"):
    return SemanticObservationSummary(
        observation_id=observation_id,
        recognition_run_id="run:1",
        target_element_id=element_id,
        target_element_type="BlockCaption",
        page_id=page_id,
        raw_text="1-1",
        normalized_text="SECTION_1",
        bbox=_bbox(),
        normalized_bbox=_normalized_bbox(),
        confidence=0.88,
        status=status,
        persisted=True,
    )


def _interpretation(
    interpretation_id="interp:1",
    element_id="caption:1",
    page_id="page:1",
    payload_ref=None,
    status="confirmed",
):
    return SemanticInterpretationSummary(
        interpretation_id=interpretation_id,
        recognition_run_id="run:1",
        element_id=element_id,
        element_type="BlockCaption",
        page_id=page_id,
        summary="断面标题 1-1",
        analysis_status=status,
        payload_ref=payload_ref,
        persisted=True,
    )


def _block_trace(block_id="block:1", page_id="page:1"):
    return BlockTrace(
        block_id=block_id,
        project_id="project:road",
        drawing_set_id="set:road:1",
        page_id=page_id,
        page_number=24,
        image_path="data/road_24.png",
        bbox=_bbox(),
        normalized_bbox=_normalized_bbox(),
        citation_ref="json:road_24",
    )


def _block_relations(
    block_id="block:1",
    relation_status="enhanced",
    caption_ids=(),
    basic_info_ids=(),
    annotation_ids=(),
    section_mark_ids=(),
    candidate_caption_ids=(),
    candidate_section_mark_ids=(),
):
    return BlockRelations(
        block_id=block_id,
        caption_ids=caption_ids,
        basic_info_ids=basic_info_ids,
        annotation_ids=annotation_ids,
        section_mark_ids=section_mark_ids,
        candidate_caption_ids=candidate_caption_ids,
        candidate_section_mark_ids=candidate_section_mark_ids,
        relation_status=relation_status,
        basic_info_status="confirmed" if basic_info_ids else None,
        basic_info_source="page" if basic_info_ids else None,
    )


def _candidate(
    candidate_group_id="group:1",
    block_id="block:1",
    page_id="page:1",
    relation_type="candidate_caption_of",
    status="candidate",
    score=0.8,
    conflict_reason=None,
):
    return CandidateRelationSummary(
        candidate_group_id=candidate_group_id,
        page_id=page_id,
        block_id=block_id,
        relation_type=relation_type,
        status=status,
        score=score,
        conflict_reason=conflict_reason,
        evidence_ids=("crop:1",),
        recognition_run_id="run:1",
    )


def _section_match(
    cross_section_id="cross:1",
    page_id="page:1",
    match_status="candidate",
    fact_kind="candidate_relation",
    status="candidate",
    logical_key=None,
    symbol_system=None,
    matched_caption_ids=(),
    candidate_count=0,
    conflict_reason=None,
    observation_ids=(),
    rule_version=None,
    alias_rule_id=None,
):
    return SectionMatchSummary(
        cross_section_id=cross_section_id,
        match_status=match_status,
        logical_key=logical_key,
        symbol_system=symbol_system,
        matched_caption_ids=matched_caption_ids,
        candidate_count=candidate_count,
        conflict_reason=conflict_reason,
        observation_ids=observation_ids,
        rule_version=rule_version,
        alias_rule_id=alias_rule_id,
        fact_kind=fact_kind,
        status=status,
        evidence={"page_id": page_id},
    )


class DrawingGraphQAServiceEntryTests(unittest.TestCase):
    def setUp(self):
        self.facade = FakeFacade()
        self.service = DrawingGraphQAService(self.facade)

    def test_write_back_true_is_rejected_without_facade_call(self):
        request = _request(QuestionType.PAGE_SUMMARY, page_id="page:1")
        request = QARequest(
            question_type=QuestionType.PAGE_SUMMARY,
            scope=QAScope(page_id="page:1"),
            write_back=True,
        )
        with self.assertRaises(QAError) as context:
            self.service.ask(request)
        self.assertEqual(QAErrorCode.WRITE_BACK_FORBIDDEN, context.exception.category)
        self.assertEqual([], self.facade.calls)

    def test_unknown_or_unsupported_returns_unsupported_answer(self):
        request = _request(QuestionType.UNKNOWN_OR_UNSUPPORTED)
        answer = self.service.ask(request)
        self.assertEqual(QAAnswerStatus.UNSUPPORTED, answer.status)
        self.assertTrue(answer.unsupported_parts)
        self.assertEqual([], self.facade.calls)

    def test_unknown_or_unsupported_reason_is_preserved(self):
        request = _request(QuestionType.UNKNOWN_OR_UNSUPPORTED)
        answer = self.service.ask(request)
        self.assertIn("不受支持", answer.summary)
        self.assertIn("不受支持", answer.unsupported_parts[0])

    def test_facade_is_required(self):
        with self.assertRaises(QAError):
            DrawingGraphQAService(None)


class ScopeValidationTests(unittest.TestCase):
    def setUp(self):
        self.facade = FakeFacade()
        self.service = DrawingGraphQAService(self.facade)

    def _assert_invalid_scope(self, question_type, scope, expected_code=QAErrorCode.INVALID_ARGUMENT):
        with self.assertRaises(QAError) as context:
            self.service.ask(_request(question_type, **scope))
        self.assertEqual(expected_code, context.exception.category)
        self.assertEqual([], self.facade.calls)

    def test_page_summary_requires_page_id(self):
        self._assert_invalid_scope(QuestionType.PAGE_SUMMARY, {})

    def test_block_relations_requires_block_id(self):
        self._assert_invalid_scope(QuestionType.BLOCK_RELATIONS, {})

    def test_candidate_relations_requires_page_or_block(self):
        self._assert_invalid_scope(QuestionType.CANDIDATE_RELATIONS, {})

    def test_section_matches_requires_cross_section_or_page(self):
        self._assert_invalid_scope(QuestionType.SECTION_MATCHES, {})

    def test_section_matches_rejects_block_only_scope(self):
        self._assert_invalid_scope(
            QuestionType.SECTION_MATCHES,
            {"block_id": "block:1"},
            expected_code=QAErrorCode.UNSUPPORTED_SCOPE,
        )

    def test_table_caption_status_requires_supported_scope(self):
        self._assert_invalid_scope(QuestionType.TABLE_CAPTION_STATUS, {})

    def test_table_caption_status_rejects_block_only_scope(self):
        self._assert_invalid_scope(
            QuestionType.TABLE_CAPTION_STATUS,
            {"block_id": "block:1"},
            expected_code=QAErrorCode.UNSUPPORTED_SCOPE,
        )

    def test_diagnostic_status_requires_page_or_block(self):
        self._assert_invalid_scope(QuestionType.DIAGNOSTIC_STATUS, {})


class DispatchBranchTests(unittest.TestCase):
    def test_legal_request_reaches_corresponding_handler(self):
        class DispatchRecorder(DrawingGraphQAService):
            def __init__(self, facade):
                super().__init__(facade)
                self.handlers = []

            def _answer_page_summary(self, request):
                self.handlers.append("page_summary")
                return _canned_answer(request)

            def _answer_block_relations(self, request):
                self.handlers.append("block_relations")
                return _canned_answer(request)

            def _answer_candidate_relations(self, request):
                self.handlers.append("candidate_relations")
                return _canned_answer(request)

            def _answer_section_matches(self, request):
                self.handlers.append("section_matches")
                return _canned_answer(request)

            def _answer_table_caption_status(self, request):
                self.handlers.append("table_caption_status")
                return _canned_answer(request)

            def _answer_diagnostic_status(self, request):
                self.handlers.append("diagnostic_status")
                return _canned_answer(request)

        cases = (
            (QuestionType.PAGE_SUMMARY, {"page_id": "page:1"}, "page_summary"),
            (QuestionType.BLOCK_RELATIONS, {"block_id": "block:1"}, "block_relations"),
            (QuestionType.CANDIDATE_RELATIONS, {"block_id": "block:1"}, "candidate_relations"),
            (QuestionType.SECTION_MATCHES, {"cross_section_id": "cross:1"}, "section_matches"),
            (QuestionType.TABLE_CAPTION_STATUS, {"table_id": "table:1"}, "table_caption_status"),
            (QuestionType.DIAGNOSTIC_STATUS, {"page_id": "page:1"}, "diagnostic_status"),
        )
        recorder = DispatchRecorder(FakeFacade())
        for question_type, scope, expected in cases:
            with self.subTest(question_type=question_type):
                answer = recorder.ask(_request(question_type, **scope))
                self.assertEqual("handled", answer.summary)
                self.assertEqual([expected], recorder.handlers)
                recorder.handlers.clear()

class PageSummaryTests(unittest.TestCase):
    def test_page_summary_returns_source_facts_and_element_stats(self):
        elements = (
            _element("block:1", "DrawingBlock"),
            _element("caption:1", "BlockCaption", source_label="caption"),
            _element("table:1", "Table", source_label="table"),
        )
        facade = FakeFacade(page_facts=_page_facts(elements=elements))
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.PAGE_SUMMARY, page_id="page:1")
        )

        self.assertEqual(QAAnswerStatus.ANSWERED, answer.status)
        self.assertEqual(
            [
                ("get_page_source_facts", "page:1"),
                ("list_text_observations", "page:1"),
                ("list_interpretations", "page:1"),
            ],
            facade.calls,
        )
        labels = [fact.label for fact in answer.facts]
        self.assertIn("页面图片", labels)
        self.assertIn("页面元素", labels)
        self.assertIn("元素类型统计", labels)
        self.assertTrue(all(fact.fact_kind == "source_fact" for fact in answer.facts))

        stats = next(fact for fact in answer.facts if fact.label == "元素类型统计")
        self.assertEqual({"DrawingBlock": 1, "BlockCaption": 1, "Table": 1}, stats.value)
        page_elements = next(fact for fact in answer.facts if fact.label == "页面元素")
        self.assertEqual(3, page_elements.value)
        evidence_ids = {ref.element_id for ref in page_elements.evidence}
        self.assertEqual({"block:1", "caption:1", "table:1"}, evidence_ids)
        self.assertTrue(all(ref.page_id == "page:1" for ref in page_elements.evidence))
        self.assertTrue(all(ref.image_path == "data/road_24.png" for ref in page_elements.evidence))
        self.assertTrue(all(ref.bbox is not None for ref in page_elements.evidence))
        self.assertTrue(all(ref.normalized_bbox is not None for ref in page_elements.evidence))

    def test_page_summary_includes_semantic_facts_when_requested(self):
        observation = _observation(observation_id="obs:1", element_id="caption:1")
        interpretation = _interpretation(
            interpretation_id="interp:1",
            element_id="caption:1",
            payload_ref="payload:1",
        )
        facade = FakeFacade(
            page_facts=_page_facts(),
            observations=(observation,),
            interpretations=(interpretation,),
        )
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.PAGE_SUMMARY, page_id="page:1")
        )

        observation_fact = next(
            fact for fact in answer.facts if fact.fact_kind == "semantic_observation"
        )
        self.assertEqual("obs:1", observation_fact.ids["observation_id"])
        self.assertEqual("run:1", observation_fact.evidence[0].recognition_run_id)

        interpretation_fact = next(
            fact for fact in answer.facts if fact.fact_kind == "semantic_interpretation"
        )
        self.assertEqual("interp:1", interpretation_fact.ids["interpretation_id"])
        self.assertEqual("payload:1", interpretation_fact.evidence[0].payload_ref)

    def test_page_summary_not_found(self):
        facade = FakeFacade(
            page_facts=None,
            page_error=ToolModelError("NOT_FOUND", "page source facts were not found"),
        )
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.PAGE_SUMMARY, page_id="page:missing")
        )
        self.assertEqual(QAAnswerStatus.NOT_FOUND, answer.status)
        self.assertEqual([("get_page_source_facts", "page:missing")], facade.calls)

    def test_page_summary_empty_semantic_evidence_is_warning_not_failure(self):
        facade = FakeFacade(page_facts=_page_facts())
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.PAGE_SUMMARY, page_id="page:1")
        )
        self.assertEqual(QAAnswerStatus.ANSWERED, answer.status)
        self.assertTrue(answer.warnings)
        self.assertTrue(any(fact.fact_kind == "source_fact" for fact in answer.facts))

    def test_page_summary_semantic_unavailable_is_partial(self):
        facade = FakeFacade(
            page_facts=_page_facts(),
            observation_error=ToolModelError(
                "SEMANTIC_EVIDENCE_UNAVAILABLE",
                "semantic evidence repository is not configured",
            ),
        )
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.PAGE_SUMMARY, page_id="page:1")
        )
        self.assertEqual(QAAnswerStatus.PARTIAL, answer.status)
        self.assertTrue(any("不可用" in warning for warning in answer.warnings))
        self.assertTrue(any(fact.fact_kind == "source_fact" for fact in answer.facts))

    def test_page_summary_include_semantics_false_skips_semantic_queries(self):
        facade = FakeFacade(page_facts=_page_facts(), observations=(_observation(),))
        request = QARequest(
            question_type=QuestionType.PAGE_SUMMARY,
            scope=QAScope(page_id="page:1"),
            include_semantics=False,
        )
        answer = DrawingGraphQAService(facade).ask(request)
        self.assertEqual(QAAnswerStatus.ANSWERED, answer.status)
        self.assertEqual([("get_page_source_facts", "page:1")], facade.calls)
        self.assertFalse(any(fact.fact_kind.startswith("semantic_") for fact in answer.facts))


class BlockRelationsTests(unittest.TestCase):
    def test_block_relations_projects_trace_and_derived_relations(self):
        relations = _block_relations(
            relation_status="enhanced",
            caption_ids=("caption:1",),
            basic_info_ids=("basic:1",),
            annotation_ids=("annotation:1",),
            section_mark_ids=("cross:1",),
        )
        facade = FakeFacade(block_trace=_block_trace(), block_relations=relations)
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.BLOCK_RELATIONS, block_id="block:1")
        )

        self.assertEqual(QAAnswerStatus.ANSWERED, answer.status)
        self.assertEqual(
            [
                ("get_block_trace", "block:1"),
                ("get_block_relations", "block:1"),
                ("list_candidate_relations", None, "block:1"),
            ],
            facade.calls,
        )

        trace_fact = next(fact for fact in answer.facts if fact.label == "图块追溯")
        self.assertEqual("source_fact", trace_fact.fact_kind)
        self.assertEqual("block:1", trace_fact.ids["block_id"])
        self.assertEqual("project:road", trace_fact.ids["project_id"])
        self.assertEqual("set:road:1", trace_fact.ids["drawing_set_id"])
        self.assertEqual("page:1", trace_fact.ids["page_id"])
        self.assertEqual("data/road_24.png", trace_fact.evidence[0].image_path)
        self.assertIsNotNone(trace_fact.evidence[0].bbox)

        derived = [fact for fact in answer.facts if fact.fact_kind == "derived_relation"]
        self.assertEqual(4, len(derived))
        self.assertEqual({"HAS_CAPTION", "USES_BASIC_INFO", "HAS_ANNOTATION", "HAS_SECTION_MARK"}, {
            fact.relation_type for fact in derived
        })
        self.assertTrue(all(fact.status == "confirmed" for fact in derived))
        self.assertIn("enhanced", answer.summary)

    def test_block_relations_empty_derived_groups_stay_not_found(self):
        facade = FakeFacade(
            block_trace=_block_trace(),
            block_relations=_block_relations(relation_status="not_enhanced"),
        )
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.BLOCK_RELATIONS, block_id="block:1")
        )
        derived = [fact for fact in answer.facts if fact.fact_kind == "derived_relation"]
        self.assertEqual(4, len(derived))
        self.assertTrue(all(fact.status == "not_found" for fact in derived))
        self.assertIn("not_enhanced", answer.summary)

    def test_block_relations_candidates_never_become_formal(self):
        relations = _block_relations(
            relation_status="candidate",
            candidate_caption_ids=("caption:1",),
            candidate_section_mark_ids=("cross:1",),
        )
        facade = FakeFacade(
            block_trace=_block_trace(),
            block_relations=relations,
            candidates=(
                _candidate("group:1", relation_type="candidate_caption_of"),
                _candidate("group:2", relation_type="candidate_section_mark", status="unresolved"),
            ),
        )
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.BLOCK_RELATIONS, block_id="block:1")
        )

        candidate_facts = [fact for fact in answer.facts if fact.fact_kind == "candidate_relation"]
        self.assertEqual(4, len(candidate_facts))
        self.assertEqual(
            {"candidate_caption_of", "candidate_section_mark"},
            {fact.relation_type for fact in candidate_facts},
        )
        self.assertFalse(any(fact.fact_kind == "formal_relation" for fact in answer.facts))
        self.assertEqual("group:1", candidate_facts[2].ids["candidate_group_id"])
        self.assertEqual(0.8, candidate_facts[2].value["score"])

    def test_block_relations_not_found(self):
        facade = FakeFacade(
            block_trace=None,
            trace_error=ToolModelError("NOT_FOUND", "block trace was not found"),
        )
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.BLOCK_RELATIONS, block_id="block:missing")
        )
        self.assertEqual(QAAnswerStatus.NOT_FOUND, answer.status)
        self.assertEqual([("get_block_trace", "block:missing")], facade.calls)

    def test_block_relations_candidate_query_unavailable_is_partial(self):
        facade = FakeFacade(
            block_trace=_block_trace(),
            block_relations=_block_relations(relation_status="enhanced"),
            candidates_error=ToolModelError(
                "SEMANTIC_EVIDENCE_UNAVAILABLE",
                "candidate relation port is not configured",
            ),
        )
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.BLOCK_RELATIONS, block_id="block:1")
        )
        self.assertEqual(QAAnswerStatus.PARTIAL, answer.status)
        self.assertTrue(any("不可用" in warning for warning in answer.warnings))
        self.assertTrue(any(fact.fact_kind == "derived_relation" for fact in answer.facts))

    def test_block_relations_include_candidates_false_skips_candidate_query(self):
        request = QARequest(
            question_type=QuestionType.BLOCK_RELATIONS,
            scope=QAScope(block_id="block:1"),
            include_candidates=False,
        )
        facade = FakeFacade(
            block_trace=_block_trace(),
            block_relations=_block_relations(relation_status="enhanced"),
            candidates=(_candidate(),),
        )
        answer = DrawingGraphQAService(facade).ask(request)
        self.assertEqual(QAAnswerStatus.ANSWERED, answer.status)
        self.assertEqual(
            [("get_block_trace", "block:1"), ("get_block_relations", "block:1")],
            facade.calls,
        )
        self.assertFalse(any(fact.fact_kind == "candidate_relation" for fact in answer.facts))


class CandidateRelationsTests(unittest.TestCase):
    def test_page_scope_includes_block_candidates_and_section_candidates(self):
        section_candidate = _section_match(
            cross_section_id="cross:1",
            match_status="candidate",
            fact_kind="candidate_relation",
            status="candidate",
            logical_key="SECTION_1_1",
            symbol_system="numeric",
            candidate_count=2,
            observation_ids=("obs:1", "obs:2"),
            rule_version="section-match-v1",
        )
        facade = FakeFacade(
            candidates=(_candidate("group:1"),),
            section_matches=(section_candidate,),
        )
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.CANDIDATE_RELATIONS, page_id="page:1")
        )

        self.assertEqual(QAAnswerStatus.ANSWERED, answer.status)
        self.assertEqual(
            [
                ("list_candidate_relations", "page:1", None),
                ("list_section_matches", None, "page:1", ("candidate",)),
            ],
            facade.calls,
        )
        self.assertTrue(all(fact.fact_kind == "candidate_relation" for fact in answer.facts))
        self.assertEqual(2, len(answer.facts))
        section_fact = next(fact for fact in answer.facts if "断面" in fact.label)
        self.assertEqual("SECTION_1_1", section_fact.value["logical_key"])
        self.assertEqual("section-match-v1", section_fact.evidence[0].rule_version)
        self.assertEqual(("obs:1", "obs:2"), section_fact.value["observation_ids"])

    def test_block_scope_queries_block_candidates_only(self):
        facade = FakeFacade(candidates=(_candidate("group:1"),))
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.CANDIDATE_RELATIONS, block_id="block:1")
        )
        self.assertEqual(QAAnswerStatus.ANSWERED, answer.status)
        self.assertEqual([("list_candidate_relations", None, "block:1")], facade.calls)
        self.assertEqual(1, len(answer.facts))
        self.assertEqual("candidate_relation", answer.facts[0].fact_kind)

    def test_empty_candidates_return_readable_summary_without_formal_facts(self):
        facade = FakeFacade()
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.CANDIDATE_RELATIONS, block_id="block:1")
        )
        self.assertEqual(QAAnswerStatus.ANSWERED, answer.status)
        self.assertEqual((), answer.facts)
        self.assertIn("没有找到候选关系", answer.summary)

    def test_matched_candidate_is_not_written_as_formal(self):
        matched = _section_match(
            cross_section_id="cross:1",
            match_status="candidate",
            fact_kind="candidate_relation",
            status="matched_candidate",
            matched_caption_ids=("caption:1",),
            candidate_count=1,
        )
        facade = FakeFacade(candidates=(), section_matches=(matched,))
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.CANDIDATE_RELATIONS, page_id="page:1")
        )
        self.assertEqual(1, len(answer.facts))
        self.assertEqual("candidate_relation", answer.facts[0].fact_kind)
        self.assertNotEqual("formal_relation", answer.facts[0].fact_kind)

    def test_candidate_query_unavailable_is_partial(self):
        facade = FakeFacade(
            candidates_error=ToolModelError("SEMANTIC_EVIDENCE_UNAVAILABLE", "port unavailable")
        )
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.CANDIDATE_RELATIONS, block_id="block:1")
        )
        self.assertEqual(QAAnswerStatus.PARTIAL, answer.status)
        self.assertTrue(any("不可用" in warning for warning in answer.warnings))

    def test_persisted_formal_section_match_keeps_formal_kind(self):
        formal = _section_match(
            cross_section_id="cross:1",
            match_status="formal",
            fact_kind="formal_relation",
            status="confirmed",
            matched_caption_ids=("caption:1",),
            candidate_count=1,
        )
        facade = FakeFacade(candidates=(), section_matches=(formal,))
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.CANDIDATE_RELATIONS, page_id="page:1")
        )
        self.assertEqual(1, len(answer.facts))
        self.assertEqual("formal_relation", answer.facts[0].fact_kind)


class SectionMatchesTests(unittest.TestCase):
    def test_formal_match_is_projected_as_formal_relation(self):
        formal = _section_match(
            cross_section_id="cross:1",
            match_status="formal",
            fact_kind="formal_relation",
            status="confirmed",
            logical_key="SECTION_1_1",
            symbol_system="numeric",
            matched_caption_ids=("caption:1",),
            candidate_count=1,
            observation_ids=("obs:1",),
            rule_version="section-match-v1",
            alias_rule_id="alias:1",
        )
        facade = FakeFacade(section_matches=(formal,))
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.SECTION_MATCHES, cross_section_id="cross:1")
        )

        self.assertEqual(QAAnswerStatus.ANSWERED, answer.status)
        self.assertEqual(1, len(answer.facts))
        fact = answer.facts[0]
        self.assertEqual("formal_relation", fact.fact_kind)
        self.assertEqual("断面正式匹配", fact.label)
        self.assertEqual("SECTION_1_1", fact.value["logical_key"])
        self.assertEqual("numeric", fact.value["symbol_system"])
        self.assertEqual("alias:1", fact.value["alias_rule_id"])
        self.assertEqual("section-match-v1", fact.evidence[0].rule_version)

    def test_ambiguous_match_is_candidate_and_conservative(self):
        ambiguous = _section_match(
            cross_section_id="cross:1",
            match_status="ambiguous",
            fact_kind="candidate_relation",
            status="ambiguous",
            candidate_count=2,
            conflict_reason="multiple same-key captions",
        )
        facade = FakeFacade(section_matches=(ambiguous,))
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.SECTION_MATCHES, cross_section_id="cross:1")
        )
        self.assertEqual(QAAnswerStatus.ANSWERED, answer.status)
        self.assertEqual("candidate_relation", answer.facts[0].fact_kind)
        self.assertEqual("ambiguous", answer.facts[0].status)
        self.assertIn("歧义", answer.summary)

    def test_no_persisted_match_runs_dry_run_without_write_back(self):
        decision = _section_match(
            cross_section_id="cross:1",
            match_status="formal",
            fact_kind="formal_relation",
            status="confirmed",
            matched_caption_ids=("caption:1",),
            candidate_count=1,
        )
        facade = FakeFacade(section_matches=(), match_decision=decision)
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.SECTION_MATCHES, cross_section_id="cross:1")
        )
        self.assertEqual(QAAnswerStatus.ANSWERED, answer.status)
        self.assertEqual(
            [
                ("list_section_matches", "cross:1", None, None),
                ("match_section_caption", "cross:1", None, False),
            ],
            facade.calls,
        )
        self.assertEqual("formal_relation", answer.facts[0].fact_kind)

    def test_dry_run_no_match_returns_conservative_summary(self):
        decision = _section_match(
            cross_section_id="cross:1",
            match_status="match_not_found",
            fact_kind="candidate_relation",
            status="match_not_found",
            candidate_count=0,
        )
        facade = FakeFacade(section_matches=(), match_decision=decision)
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.SECTION_MATCHES, cross_section_id="cross:1")
        )
        self.assertEqual(QAAnswerStatus.ANSWERED, answer.status)
        self.assertEqual((), answer.facts)
        self.assertIn("没有找到", answer.summary)

    def test_page_only_no_matches_is_not_found_without_dry_run(self):
        facade = FakeFacade(section_matches=())
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.SECTION_MATCHES, page_id="page:1")
        )
        self.assertEqual(QAAnswerStatus.NOT_FOUND, answer.status)
        self.assertEqual([("list_section_matches", None, "page:1", None)], facade.calls)
        self.assertTrue(answer.warnings)


class TableCaptionStatusTests(unittest.TestCase):
    def test_page_scope_reports_tables_captions_and_unsupported_derived_status(self):
        elements = (
            _element("table:1", "Table", source_label="table"),
            _element("table:2", "Table", source_label="table"),
            _element("caption:1", "TableCaption", source_label="table_caption"),
        )
        facade = FakeFacade(page_facts=_page_facts(elements=elements))
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.TABLE_CAPTION_STATUS, page_id="page:1")
        )

        self.assertEqual(QAAnswerStatus.PARTIAL, answer.status)
        self.assertEqual([("get_page_source_facts", "page:1")], facade.calls)
        self.assertTrue(answer.unsupported_parts)
        self.assertTrue(any("HAS_CAPTION" in part or "facade" in part for part in answer.unsupported_parts))

        table_facts = [fact for fact in answer.facts if fact.label == "表格"]
        caption_facts = [fact for fact in answer.facts if fact.label == "表格标题"]
        self.assertEqual(2, len(table_facts))
        self.assertEqual(1, len(caption_facts))
        self.assertTrue(all(fact.fact_kind == "source_fact" for fact in answer.facts))
        self.assertTrue(all(fact.evidence[0].bbox is not None for fact in table_facts + caption_facts))

        stats = next(fact for fact in answer.facts if fact.label == "表格统计")
        self.assertEqual({"table_count": 2, "table_caption_count": 1}, stats.value)
        self.assertIn("2", answer.summary)
        self.assertIn("1", answer.summary)

    def test_page_without_tables_is_still_conservative(self):
        facade = FakeFacade(page_facts=_page_facts(elements=(_element("block:1", "DrawingBlock"),)))
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.TABLE_CAPTION_STATUS, page_id="page:1")
        )
        self.assertEqual(QAAnswerStatus.PARTIAL, answer.status)
        self.assertTrue(answer.unsupported_parts)
        self.assertIn("没有表格", answer.summary)
        self.assertFalse(any(fact.label in {"表格", "表格标题"} for fact in answer.facts))

    def test_table_id_only_scope_returns_partial_without_facade_call(self):
        facade = FakeFacade()
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.TABLE_CAPTION_STATUS, table_id="table:1")
        )
        self.assertEqual(QAAnswerStatus.PARTIAL, answer.status)
        self.assertEqual([], facade.calls)
        self.assertTrue(any("page_id" in part for part in answer.unsupported_parts))

    def test_table_caption_id_only_scope_returns_partial_without_facade_call(self):
        facade = FakeFacade()
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.TABLE_CAPTION_STATUS, table_caption_id="caption:1")
        )
        self.assertEqual(QAAnswerStatus.PARTIAL, answer.status)
        self.assertEqual([], facade.calls)
        self.assertTrue(answer.unsupported_parts)

    def test_page_not_found_is_not_found(self):
        facade = FakeFacade(
            page_error=ToolModelError("NOT_FOUND", "page source facts were not found")
        )
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.TABLE_CAPTION_STATUS, page_id="page:missing")
        )
        self.assertEqual(QAAnswerStatus.NOT_FOUND, answer.status)
        self.assertEqual([("get_page_source_facts", "page:missing")], facade.calls)


class DiagnosticStatusTests(unittest.TestCase):
    def test_page_diagnostic_reports_import_semantics_and_candidates(self):
        facade = FakeFacade(
            page_facts=_page_facts(
                elements=(_element("block:1", "DrawingBlock"), _element("table:1", "Table"))
            ),
            observations=(_observation(),),
            interpretations=(_interpretation(),),
            candidates=(_candidate("group:1"),),
        )
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.DIAGNOSTIC_STATUS, page_id="page:1")
        )

        self.assertEqual(QAAnswerStatus.ANSWERED, answer.status)
        diagnostic = [fact for fact in answer.facts if fact.fact_kind == "diagnostic"]
        labels = {fact.label for fact in diagnostic}
        self.assertEqual({"导入可见性", "语义证据", "候选状态"}, labels)
        import_fact = next(fact for fact in diagnostic if fact.label == "导入可见性")
        self.assertEqual("confirmed", import_fact.status)
        semantic_fact = next(fact for fact in diagnostic if fact.label == "语义证据")
        self.assertEqual(1, semantic_fact.value["observation_count"])
        self.assertEqual(1, semantic_fact.value["interpretation_count"])
        candidate_fact = next(fact for fact in diagnostic if fact.label == "候选状态")
        self.assertEqual(1, candidate_fact.value["candidate_count"])
        self.assertNotIn("live Neo4j", answer.summary)

    def test_block_diagnostic_reports_import_enhancement_and_candidates(self):
        facade = FakeFacade(
            block_trace=_block_trace(),
            block_relations=_block_relations(relation_status="enhanced"),
            candidates=(_candidate("group:1"),),
        )
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.DIAGNOSTIC_STATUS, block_id="block:1")
        )

        self.assertEqual(QAAnswerStatus.ANSWERED, answer.status)
        diagnostic = {fact.label: fact for fact in answer.facts if fact.fact_kind == "diagnostic"}
        self.assertEqual({"导入可见性", "增强状态", "候选状态"}, set(diagnostic))
        self.assertEqual("enhanced", diagnostic["增强状态"].value["relation_status"])
        self.assertEqual(1, diagnostic["候选状态"].value["candidate_count"])

    def test_page_diagnostic_not_found(self):
        facade = FakeFacade(
            page_error=ToolModelError("NOT_FOUND", "page source facts were not found")
        )
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.DIAGNOSTIC_STATUS, page_id="page:missing")
        )
        self.assertEqual(QAAnswerStatus.NOT_FOUND, answer.status)
        self.assertEqual([("get_page_source_facts", "page:missing")], facade.calls)

    def test_block_diagnostic_not_found(self):
        facade = FakeFacade(
            trace_error=ToolModelError("NOT_FOUND", "block trace was not found")
        )
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.DIAGNOSTIC_STATUS, block_id="block:missing")
        )
        self.assertEqual(QAAnswerStatus.NOT_FOUND, answer.status)

    def test_page_diagnostic_degrades_when_semantics_unavailable(self):
        facade = FakeFacade(
            page_facts=_page_facts(),
            observation_error=ToolModelError("SEMANTIC_EVIDENCE_UNAVAILABLE", "unavailable"),
        )
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.DIAGNOSTIC_STATUS, page_id="page:1")
        )
        self.assertEqual(QAAnswerStatus.PARTIAL, answer.status)
        self.assertTrue(any("不可用" in warning for warning in answer.warnings))

    def test_page_diagnostic_degrades_when_candidates_unavailable(self):
        facade = FakeFacade(
            page_facts=_page_facts(),
            candidates_error=ToolModelError("SEMANTIC_EVIDENCE_UNAVAILABLE", "unavailable"),
        )
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.DIAGNOSTIC_STATUS, page_id="page:1")
        )
        self.assertEqual(QAAnswerStatus.PARTIAL, answer.status)
        self.assertTrue(any("不可用" in warning for warning in answer.warnings))

    def test_section_match_query_unavailable_is_partial(self):
        facade = FakeFacade(
            section_matches_error=ToolModelError("SEMANTIC_EVIDENCE_UNAVAILABLE", "port unavailable")
        )
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.SECTION_MATCHES, cross_section_id="cross:1")
        )
        self.assertEqual(QAAnswerStatus.PARTIAL, answer.status)
        self.assertTrue(any("不可用" in warning for warning in answer.warnings))

    def test_cross_section_not_found_is_not_found(self):
        facade = FakeFacade(
            section_matches=(),
            match_error=ToolModelError("NOT_FOUND", "cross-section observation was not found"),
        )
        answer = DrawingGraphQAService(facade).ask(
            _request(QuestionType.SECTION_MATCHES, cross_section_id="cross:missing")
        )
        self.assertEqual(QAAnswerStatus.NOT_FOUND, answer.status)


if __name__ == "__main__":
    unittest.main()
