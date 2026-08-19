"""Tests for the claim trace projection (07 traceability loop)."""

import ast
import unittest
from pathlib import Path

from drawing_graph.assistant_models import (
    AnswerPackage,
    AssistantScope,
    Claim,
    Citation,
    FactKind,
)
from drawing_graph.assistant_trace_models import ClaimTrace, TraceRecord
from drawing_graph.assistant_claim_trace import ClaimTraceProjector

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src" / "drawing_graph"


class ClaimTraceProjectorTests(unittest.TestCase):
    def _record(self):
        return TraceRecord(
            request_id="req:1",
            question_type="block_relations",
            scope=AssistantScope(block_id="block:1"),
            evidence_ids=("evidence:1",),
            claim_ids=("claim:1",),
            answer_status="answered",
        )

    def _package(self):
        claim = Claim(
            claim_id="claim:1",
            statement="caption 与 block 构成候选关系",
            status="formal_review_required",
            evidence_ids=("evidence:1",),
            fact_kinds=(FactKind.CANDIDATE_RELATION,),
            citation_ids=("citation:1",),
        )
        citation = Citation(
            citation_id="citation:1",
            evidence_id="evidence:1",
            claim_ids=("claim:1",),
            page_id="page:1",
            block_id="block:1",
            element_id="element:1",
            bbox={"x_min": 1.0, "y_min": 2.0, "x_max": 3.0, "y_max": 4.0},
            candidate_group_id="candidate-group:1",
            recognition_run_id="run:1",
            payload_ref="payload:1",
        )
        return AnswerPackage(
            request_id="req:1",
            question_type="block_relations",
            status="answered",
            claims=(claim,),
            citations=(citation,),
        )

    def test_project_builds_claim_trace_from_claim_and_citations(self):
        projector = ClaimTraceProjector()
        trace = projector.project(self._record(), self._package(), "claim:1")
        self.assertIsInstance(trace, ClaimTrace)
        self.assertEqual("claim:1", trace.claim_id)
        self.assertEqual("req:1", trace.request_id)
        self.assertEqual("formal_review_required", trace.claim_status)
        self.assertEqual("caption 与 block 构成候选关系", trace.statement)
        self.assertEqual((FactKind.CANDIDATE_RELATION,), trace.fact_kinds)
        self.assertEqual(("evidence:1",), trace.evidence_ids)
        self.assertEqual(("citation:1",), trace.citation_ids)

    def test_project_resolves_citation_location_refs(self):
        projector = ClaimTraceProjector()
        trace = projector.project(self._record(), self._package(), "claim:1")
        self.assertEqual(("page:1",), trace.page_ids)
        self.assertEqual(("block:1",), trace.block_ids)
        self.assertEqual(("element:1",), trace.element_ids)
        self.assertEqual(("run:1",), trace.recognition_run_ids)
        self.assertEqual(("candidate-group:1",), trace.candidate_group_ids)
        self.assertEqual(("payload:1",), trace.payload_refs)
        self.assertEqual(1, len(trace.bboxes))

    def test_candidate_relation_stays_candidate(self):
        projector = ClaimTraceProjector()
        trace = projector.project(self._record(), self._package(), "claim:1")
        self.assertIn(FactKind.CANDIDATE_RELATION, trace.fact_kinds)
        self.assertNotIn(FactKind.FORMAL_RELATION, trace.fact_kinds)

    def test_missing_claim_returns_none(self):
        projector = ClaimTraceProjector()
        self.assertIsNone(projector.project(self._record(), self._package(), "claim:missing"))

    def test_project_all_returns_traces_for_each_claim(self):
        package = self._package()
        projector = ClaimTraceProjector()
        traces = projector.project_all(self._record(), package)
        self.assertEqual(("claim:1",), tuple(trace.claim_id for trace in traces))


class ClaimTraceProjectorBoundaryTests(unittest.TestCase):
    def test_projector_does_not_import_neo4j(self):
        source = (SRC_DIR / "assistant_claim_trace.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        self.assertNotIn("neo4j", imported)
        self.assertNotIn("neo4j_repository", imported)


if __name__ == "__main__":
    unittest.main()
