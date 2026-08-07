import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.query_ports import FakeDrawingGraphReadPort
from drawing_graph.tool_facade import DrawingGraphToolFacade


class SpyRepository:
    def __init__(self):
        self.calls = []

    def update_candidate_review(self, *args, **kwargs):
        self.calls.append(("update_candidate_review", args, kwargs))

    def promote_candidate_relation(self, *args, **kwargs):
        self.calls.append(("promote_candidate_relation", args, kwargs))


class ToolFacadeCandidateReviewDryRunTest(unittest.TestCase):
    def test_dry_run_returns_expected_review_without_repository_write(self):
        repository = SpyRepository()
        facade = DrawingGraphToolFacade(FakeDrawingGraphReadPort())

        result = facade.review_candidate_relation(
            candidate_group_id="group:1",
            decision="accepted",
            reviewer="human:1",
            reason="matches source",
            relation_spec="candidate_caption_of",
            page_id="page:1",
            source_element_id="caption:1",
            rule_version="r1",
            candidates=(
                {
                    "candidate_id": "cand:1",
                    "start_id": "caption:1",
                    "end_id": "block:1",
                    "page_id": "page:1",
                    "relation_spec": "candidate_caption_of",
                },
            ),
            evidence_refs=("obs:1",),
            repository=repository,
            write_back=False,
        )

        self.assertFalse(result.persisted)
        self.assertEqual("accepted", result.status)
        self.assertEqual([], repository.calls)


if __name__ == "__main__":
    unittest.main()
