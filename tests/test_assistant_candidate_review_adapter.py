"""Tests for the candidate review feedback adapter (08 feedback loop)."""

import ast
import unittest
from pathlib import Path

from drawing_graph.assistant_models import FeedbackEvent, FactKind
from drawing_graph.assistant_trace_models import ClaimTrace
from drawing_graph.assistant_candidate_review_adapter import (
    CandidateReviewAdapter,
    CandidateReviewAdapterError,
)
from drawing_graph.candidate_review import CandidateReviewRequest, CandidateReviewResult

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src" / "drawing_graph"


def _candidate(candidate_id="candidate:caption:1:block:1", **overrides):
    values = {
        "candidate_id": candidate_id,
        "start_id": "caption:1",
        "end_id": "block:1",
        "page_id": "page:1",
        "relation_spec": "candidate_caption_of",
        "rule_version": "relation-rules-v1",
    }
    values.update(overrides)
    return values


def _claim_trace(**overrides):
    values = {
        "claim_id": "claim:1",
        "request_id": "req:1",
        "fact_kinds": (FactKind.CANDIDATE_RELATION,),
        "candidate_group_ids": ("candidate-group:1",),
        "relation_spec": "candidate_caption_of",
        "rule_version": "relation-rules-v1",
        "candidates": (_candidate(),),
        "evidence_refs": ("crop:caption:1",),
    }
    values.update(overrides)
    return ClaimTrace(**values)


def _feedback_event():
    return FeedbackEvent(feedback_id="feedback:1", request_id="req:1", claim_id="claim:1", action="request_review")


class _RecordingReviewService:
    def __init__(self, result=None):
        self.result = result or CandidateReviewResult(
            review_run_id="review-run:1",
            relation_spec="candidate_caption_of",
            status="unresolved",
        )
        self.requests = []

    def review_candidate_group(self, request):
        self.requests.append(request)
        return self.result


class CandidateReviewAdapterTests(unittest.TestCase):
    def test_build_review_request_from_valid_candidate_claim(self):
        adapter = CandidateReviewAdapter(_RecordingReviewService())
        request = adapter.build_review_request(_feedback_event(), _claim_trace())
        self.assertIsInstance(request, CandidateReviewRequest)
        self.assertEqual("candidate_caption_of", request.relation_spec)
        self.assertEqual("page:1", request.page_id)
        self.assertEqual("relation-rules-v1", request.rule_version)
        self.assertEqual(("crop:caption:1",), request.evidence_refs)
        self.assertEqual(1, request.candidate_count)

    def test_non_candidate_claim_is_rejected(self):
        adapter = CandidateReviewAdapter(_RecordingReviewService())
        with self.assertRaises(CandidateReviewAdapterError) as error:
            adapter.build_review_request(
                _feedback_event(),
                _claim_trace(fact_kinds=(FactKind.SOURCE_FACT,)),
            )
        self.assertEqual("not_candidate_claim", error.exception.category)

    def test_incomplete_candidates_rejected(self):
        adapter = CandidateReviewAdapter(_RecordingReviewService())
        with self.assertRaises(CandidateReviewAdapterError) as error:
            adapter.build_review_request(_feedback_event(), _claim_trace(candidates=()))
        self.assertEqual("incomplete_candidates", error.exception.category)

    def test_cross_page_candidates_rejected(self):
        adapter = CandidateReviewAdapter(_RecordingReviewService())
        cross_page = (_candidate(), _candidate("candidate:2", page_id="page:2"))
        with self.assertRaises(CandidateReviewAdapterError) as error:
            adapter.build_review_request(_feedback_event(), _claim_trace(candidates=cross_page))
        self.assertEqual("cross_page", error.exception.category)

    def test_direction_unknown_rejected(self):
        adapter = CandidateReviewAdapter(_RecordingReviewService())
        reversed_direction = _candidate(start_id="block:1", end_id="caption:1")
        with self.assertRaises(CandidateReviewAdapterError) as error:
            adapter.build_review_request(_feedback_event(), _claim_trace(candidates=(reversed_direction,)))
        self.assertEqual("direction_unknown", error.exception.category)

    def test_missing_evidence_refs_rejected(self):
        adapter = CandidateReviewAdapter(_RecordingReviewService())
        with self.assertRaises(CandidateReviewAdapterError) as error:
            adapter.build_review_request(_feedback_event(), _claim_trace(evidence_refs=()))
        self.assertEqual("missing_evidence_refs", error.exception.category)

    def test_request_review_delegates_to_injected_service(self):
        service = _RecordingReviewService()
        adapter = CandidateReviewAdapter(service)
        result = adapter.request_review(_feedback_event(), _claim_trace())
        self.assertEqual(service.result, result)
        self.assertEqual(1, len(service.requests))
        self.assertIsInstance(service.requests[0], CandidateReviewRequest)

    def test_adapter_does_not_call_repository_directly(self):
        service = _RecordingReviewService()
        adapter = CandidateReviewAdapter(service)
        adapter.request_review(_feedback_event(), _claim_trace())
        self.assertEqual(1, len(service.requests))


class CandidateReviewAdapterBoundaryTests(unittest.TestCase):
    def test_adapter_does_not_import_forbidden_backends(self):
        source = (SRC_DIR / "assistant_candidate_review_adapter.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        for name in ("neo4j", "neo4j_repository", "relation_repository", "semantic_repository"):
            self.assertNotIn(name, imported)


if __name__ == "__main__":
    unittest.main()
