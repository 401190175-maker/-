import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.query_ports import FakeDrawingGraphReadPort
from drawing_graph.tool_facade import DrawingGraphToolFacade
from drawing_graph.tool_models import CandidateRelationSummary


class FakeCandidateRelationPort:
    def __init__(self):
        self.candidates = (
            CandidateRelationSummary(
                candidate_group_id="group:1",
                page_id="page:1",
                block_id="block:1",
                relation_type="candidate_caption_of",
                status="matched_candidate",
                score=0.8,
                conflict_reason=None,
                evidence_ids=("obs:1",),
                recognition_run_id="run:1",
            ),
            CandidateRelationSummary(
                candidate_group_id="group:2",
                page_id="page:1",
                block_id="block:2",
                relation_type="candidate_section_mark",
                status="ambiguous",
                score=0.4,
                conflict_reason="tie",
            ),
        )

    def list_candidate_relations(self, page_id=None, block_id=None, relation_type=None, status=None):
        result = self.candidates
        if page_id is not None:
            result = tuple(item for item in result if item.page_id == page_id)
        if block_id is not None:
            result = tuple(item for item in result if item.block_id == block_id)
        if relation_type is not None:
            result = tuple(item for item in result if item.relation_type == relation_type)
        if status is not None:
            result = tuple(item for item in result if item.status == status)
        return result


class ToolFacadeCandidateQueriesTest(unittest.TestCase):
    def test_queries_candidate_relations_without_formal_projection(self):
        facade = DrawingGraphToolFacade(
            FakeDrawingGraphReadPort(),
            candidate_relation_port=FakeCandidateRelationPort(),
        )

        candidates = facade.list_candidate_relations(page_id="page:1", status="matched_candidate")

        self.assertEqual(("group:1",), tuple(item.candidate_group_id for item in candidates))
        self.assertEqual("candidate", candidates[0].fact_kind)
        self.assertNotEqual("formal", candidates[0].fact_kind)

    def test_filters_by_block_and_relation_type(self):
        facade = DrawingGraphToolFacade(
            FakeDrawingGraphReadPort(),
            candidate_relation_port=FakeCandidateRelationPort(),
        )

        candidates = facade.list_candidate_relations(block_id="block:2", relation_type="candidate_section_mark")

        self.assertEqual(("group:2",), tuple(item.candidate_group_id for item in candidates))


if __name__ == "__main__":
    unittest.main()
