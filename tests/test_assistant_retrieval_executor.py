"""Tests for the read-only graph retrieval executor."""

import unittest

from drawing_graph.assistant_models import (
    ReasonCode,
    RetrievalPlan,
    RetrievalStatus,
    RetrievalStep,
)
from drawing_graph.assistant_retrieval_executor import RetrievalExecutor
from drawing_graph.tool_models import (
    BlockTrace,
    BBox,
    CandidateRelationSummary,
    ElementEvidence,
    PageSourceFacts,
    ToolModelError,
)


class FakeFacade:
    def __init__(self, returns=None, errors=None):
        self.calls = []
        self.returns = returns or {}
        self.errors = errors or {}

    def _maybe_raise(self, name):
        if name in self.errors:
            raise self.errors[name]

    def _record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))

    def _return(self, name, default):
        return self.returns.get(name, default)

    def list_drawing_sets(self, *args, **kwargs):
        self._record("list_drawing_sets", *args, **kwargs)
        self._maybe_raise("list_drawing_sets")
        return self._return("list_drawing_sets", [])

    def list_pages(self, *args, **kwargs):
        self._record("list_pages", *args, **kwargs)
        self._maybe_raise("list_pages")
        return self._return("list_pages", [])

    def get_page_source_facts(self, *args, **kwargs):
        self._record("get_page_source_facts", *args, **kwargs)
        self._maybe_raise("get_page_source_facts")
        return self._return("get_page_source_facts", None)

    def get_block_trace(self, *args, **kwargs):
        self._record("get_block_trace", *args, **kwargs)
        self._maybe_raise("get_block_trace")
        return self._return("get_block_trace", None)

    def get_block_relations(self, *args, **kwargs):
        self._record("get_block_relations", *args, **kwargs)
        self._maybe_raise("get_block_relations")
        return self._return("get_block_relations", None)

    def list_text_observations(self, *args, **kwargs):
        self._record("list_text_observations", *args, **kwargs)
        self._maybe_raise("list_text_observations")
        return self._return("list_text_observations", ())

    def list_interpretations(self, *args, **kwargs):
        self._record("list_interpretations", *args, **kwargs)
        self._maybe_raise("list_interpretations")
        return self._return("list_interpretations", ())

    def get_semantic_payload(self, *args, **kwargs):
        self._record("get_semantic_payload", *args, **kwargs)
        self._maybe_raise("get_semantic_payload")
        return self._return("get_semantic_payload", None)

    def list_candidate_relations(self, *args, **kwargs):
        self._record("list_candidate_relations", *args, **kwargs)
        self._maybe_raise("list_candidate_relations")
        return self._return("list_candidate_relations", ())

    def list_section_matches(self, *args, **kwargs):
        self._record("list_section_matches", *args, **kwargs)
        self._maybe_raise("list_section_matches")
        return self._return("list_section_matches", ())

    def recognize_page_semantics(self, *args, **kwargs):
        self._record("recognize_page_semantics", *args, **kwargs)
        return object()

    def review_candidate_relation(self, *args, **kwargs):
        self._record("review_candidate_relation", *args, **kwargs)
        return object()

    def match_section_caption(self, *args, **kwargs):
        self._record("match_section_caption", *args, **kwargs)
        return object()


def make_plan(*steps: RetrievalStep) -> RetrievalPlan:
    return RetrievalPlan(request_id="req:1", steps=steps)


class RetrievalExecutorWhitelistTests(unittest.TestCase):
    def test_whitelist_contains_only_read_only_facade_methods(self):
        self.assertEqual(
            {
                "list_drawing_sets",
                "list_pages",
                "get_page_source_facts",
                "get_block_trace",
                "get_block_relations",
                "list_text_observations",
                "list_interpretations",
                "get_semantic_payload",
                "list_candidate_relations",
                "list_section_matches",
            },
            RetrievalExecutor.ALLOWED_FACADE_METHODS,
        )

    def test_non_whitelist_method_is_never_called(self):
        step = RetrievalStep(
            step_id="step:1",
            facade_method="recognize_page_semantics",
            parameters={},
        )
        facade = FakeFacade()
        raw, calls = RetrievalExecutor().execute(make_plan(step), facade)
        self.assertEqual({}, dict(raw.results))
        self.assertEqual([], facade.calls)
        self.assertEqual(1, len(calls))
        self.assertEqual(RetrievalStatus.ERROR, calls[0].status)
        self.assertEqual(ReasonCode.UNSUPPORTED_EVIDENCE_TYPE, calls[0].reason_code)

    def test_review_and_match_methods_are_also_blocked(self):
        steps = (
            RetrievalStep(step_id="step:1", facade_method="review_candidate_relation", parameters={}),
            RetrievalStep(step_id="step:2", facade_method="match_section_caption", parameters={}),
        )
        facade = FakeFacade()
        raw, calls = RetrievalExecutor().execute(make_plan(*steps), facade)
        self.assertEqual({}, dict(raw.results))
        self.assertEqual([], facade.calls)
        self.assertEqual(2, len(calls))
        self.assertTrue(all(call.status == RetrievalStatus.ERROR for call in calls))
        self.assertTrue(
            all(call.reason_code == ReasonCode.UNSUPPORTED_EVIDENCE_TYPE for call in calls)
        )


class RetrievalExecutorSuccessCallTests(unittest.TestCase):
    def test_get_page_source_facts_success_is_recorded(self):
        page_facts = PageSourceFacts(
            page_id="page:1",
            image_path="data/road_24.png",
            elements=(),
        )
        step = RetrievalStep(
            step_id="step:1",
            facade_method="get_page_source_facts",
            parameters={"page_id": "page:1", "element_types": None, "include_image_meta": True},
            dedupe_key="get_page_source_facts:page:1",
        )
        facade = FakeFacade(returns={"get_page_source_facts": page_facts})
        raw, calls = RetrievalExecutor().execute(make_plan(step), facade)
        self.assertIs(page_facts, raw.results["step:1"])
        self.assertEqual(1, len(calls))
        self.assertEqual("call:step:1", calls[0].source_call_id)
        self.assertEqual("step:1", calls[0].step_id)
        self.assertEqual("get_page_source_facts", calls[0].facade_method)
        self.assertEqual(RetrievalStatus.OK, calls[0].status)
        self.assertEqual(1, calls[0].result_count)

    def test_get_block_trace_success_preserves_step_to_result_mapping(self):
        trace = BlockTrace(
            block_id="block:1",
            project_id="project:1",
            drawing_set_id="set:1",
            page_id="page:1",
            bbox=BBox(1, 2, 3, 4),
            normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
        )
        step = RetrievalStep(
            step_id="step:2",
            facade_method="get_block_trace",
            parameters={"block_id": "block:1"},
            dedupe_key="get_block_trace:block:1",
        )
        facade = FakeFacade(returns={"get_block_trace": trace})
        raw, calls = RetrievalExecutor().execute(make_plan(step), facade)
        self.assertIs(trace, raw.results["step:2"])
        self.assertEqual(RetrievalStatus.OK, calls[0].status)
        self.assertEqual(1, calls[0].result_count)

    def test_list_candidate_relations_counts_results(self):
        candidates = (
            CandidateRelationSummary(
                candidate_group_id="group:1",
                page_id="page:1",
                block_id="block:1",
                relation_type="candidate_caption_of",
                status="matched_candidate",
            ),
            CandidateRelationSummary(
                candidate_group_id="group:2",
                page_id="page:1",
                block_id="block:2",
                relation_type="candidate_caption_of",
                status="ambiguous",
            ),
        )
        step = RetrievalStep(
            step_id="step:3",
            facade_method="list_candidate_relations",
            parameters={"page_id": "page:1", "block_id": None, "relation_type": None, "status": None},
            dedupe_key="list_candidate_relations:page:1",
        )
        facade = FakeFacade(returns={"list_candidate_relations": candidates})
        raw, calls = RetrievalExecutor().execute(make_plan(step), facade)
        self.assertIs(candidates, raw.results["step:3"])
        self.assertEqual(2, calls[0].result_count)

    def test_same_dedupe_key_calls_facade_only_once(self):
        trace = BlockTrace(
            block_id="block:1",
            project_id="project:1",
            drawing_set_id="set:1",
            page_id="page:1",
            bbox=BBox(1, 2, 3, 4),
            normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
        )
        steps = (
            RetrievalStep(
                step_id="step:4",
                facade_method="get_block_trace",
                parameters={"block_id": "block:1"},
                dedupe_key="dup:1",
            ),
            RetrievalStep(
                step_id="step:5",
                facade_method="get_block_trace",
                parameters={"block_id": "block:1"},
                dedupe_key="dup:1",
            ),
        )
        facade = FakeFacade(returns={"get_block_trace": trace})
        raw, calls = RetrievalExecutor().execute(make_plan(*steps), facade)
        self.assertEqual(1, sum(1 for name, _, _ in facade.calls if name == "get_block_trace"))
        self.assertIs(raw.results["step:4"], raw.results["step:5"])
        self.assertEqual(2, len(calls))
        self.assertTrue(all(call.status == RetrievalStatus.OK for call in calls))


class RetrievalExecutorErrorHandlingTests(unittest.TestCase):
    def test_required_step_exception_becomes_facade_call_failed(self):
        step = RetrievalStep(
            step_id="step:1",
            facade_method="get_block_trace",
            parameters={"block_id": "block:1"},
            required=True,
        )
        facade = FakeFacade(
            errors={"get_block_trace": RuntimeError("backend unavailable")}
        )
        raw, calls = RetrievalExecutor().execute(make_plan(step), facade)
        self.assertEqual({}, dict(raw.results))
        self.assertEqual(RetrievalStatus.ERROR, calls[0].status)
        self.assertEqual(ReasonCode.FACADE_CALL_FAILED, calls[0].reason_code)

    def test_optional_step_exception_does_not_block_other_steps(self):
        failing = RetrievalStep(
            step_id="step:1",
            facade_method="get_block_trace",
            parameters={"block_id": "block:1"},
            required=False,
        )
        succeeding = RetrievalStep(
            step_id="step:2",
            facade_method="get_page_source_facts",
            parameters={"page_id": "page:1", "element_types": None, "include_image_meta": True},
            required=True,
        )
        page_facts = PageSourceFacts(page_id="page:1", image_path=None, elements=())
        facade = FakeFacade(
            returns={"get_page_source_facts": page_facts},
            errors={"get_block_trace": RuntimeError("boom")},
        )
        raw, calls = RetrievalExecutor().execute(make_plan(failing, succeeding), facade)
        self.assertIn("step:2", raw.results)
        self.assertEqual(2, len(calls))
        self.assertEqual(ReasonCode.FACADE_CALL_FAILED, calls[0].reason_code)
        self.assertIsNotNone(calls[0].warning)
        self.assertEqual(RetrievalStatus.OK, calls[1].status)

    def test_error_message_is_sanitized(self):
        sensitive = (
            "password=secret token=abc Authorization: Bearer x "
            "MATCH (n) Traceback (most recent call last)"
        )
        step = RetrievalStep(
            step_id="step:1",
            facade_method="get_block_trace",
            parameters={"block_id": "block:1"},
        )
        facade = FakeFacade(errors={"get_block_trace": RuntimeError(sensitive)})
        raw, calls = RetrievalExecutor().execute(make_plan(step), facade)
        warning = calls[0].warning
        for forbidden in ("password", "token", "Authorization", "MATCH (", "Traceback"):
            self.assertNotIn(forbidden, warning)

    def test_payload_failure_is_classified_as_payload_unavailable(self):
        step = RetrievalStep(
            step_id="step:1",
            facade_method="get_semantic_payload",
            parameters={"payload_ref": "payload:1"},
        )
        facade = FakeFacade(
            errors={
                "get_semantic_payload": ToolModelError(
                    "PAYLOAD_UNAVAILABLE",
                    "semantic payload store is not configured",
                )
            }
        )
        raw, calls = RetrievalExecutor().execute(make_plan(step), facade)
        self.assertEqual(ReasonCode.PAYLOAD_UNAVAILABLE, calls[0].reason_code)
        self.assertEqual(RetrievalStatus.ERROR, calls[0].status)


if __name__ == "__main__":
    unittest.main()
