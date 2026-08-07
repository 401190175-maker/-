import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.query_ports import FakeDrawingGraphReadPort
from drawing_graph.tool_facade import DrawingGraphToolFacade
from drawing_graph.tool_models import ToolModelError


class SpyRepository:
    def __init__(self):
        self.calls = []

    def update_candidate_review(self, **kwargs):
        self.calls.append(("update_candidate_review", kwargs))

    def promote_candidate_relation(self, **kwargs):
        self.calls.append(("promote_candidate_relation", kwargs))


def review_kwargs(decision="accepted", candidates=None, relation_spec="candidate_caption_of", repository=None):
    return {
        "candidate_group_id": "group:1",
        "decision": decision,
        "reviewer": "human:1",
        "reason": "checked",
        "relation_spec": relation_spec,
        "page_id": "page:1",
        "source_element_id": "caption:1",
        "rule_version": "r1",
        "candidates": candidates
        or (
            {
                "candidate_id": "cand:1",
                "start_id": "caption:1",
                "end_id": "block:1",
                "page_id": "page:1",
                "relation_spec": "candidate_caption_of",
            },
        ),
        "evidence_refs": ("obs:1",),
        "repository": repository,
        "write_back": True,
    }


class ToolFacadeCandidateReviewWriteBackTest(unittest.TestCase):
    def test_accepted_updates_review_and_promotes_through_service_rules(self):
        repository = SpyRepository()
        result = DrawingGraphToolFacade(FakeDrawingGraphReadPort()).review_candidate_relation(
            **review_kwargs(repository=repository)
        )

        self.assertTrue(result.persisted)
        self.assertTrue(result.promoted)
        self.assertEqual(["update_candidate_review", "promote_candidate_relation"], [call[0] for call in repository.calls])

    def test_rejected_and_unresolved_update_without_promotion(self):
        for decision in ("rejected", "unresolved"):
            with self.subTest(decision=decision):
                repository = SpyRepository()
                result = DrawingGraphToolFacade(FakeDrawingGraphReadPort()).review_candidate_relation(
                    **review_kwargs(decision=decision, repository=repository)
                )

                self.assertTrue(result.persisted)
                self.assertFalse(result.promoted)
                self.assertEqual(["update_candidate_review"], [call[0] for call in repository.calls])

    def test_hard_rule_failure_is_classified(self):
        repository = SpyRepository()
        bad_candidates = (
            {
                "candidate_id": "cand:1",
                "start_id": "block:1",
                "end_id": "caption:1",
                "page_id": "page:1",
                "relation_spec": "candidate_caption_of",
            },
        )

        with self.assertRaises(ToolModelError) as error:
            DrawingGraphToolFacade(FakeDrawingGraphReadPort()).review_candidate_relation(
                **review_kwargs(candidates=bad_candidates, repository=repository)
            )

        self.assertEqual("CANDIDATE_REVIEW_REJECTED", error.exception.category)
        self.assertEqual([], repository.calls)

    def test_unknown_relation_spec_is_rejected_before_repository_write(self):
        repository = SpyRepository()

        with self.assertRaises(Exception):
            DrawingGraphToolFacade(FakeDrawingGraphReadPort()).review_candidate_relation(
                **review_kwargs(relation_spec="anything", repository=repository)
            )

        self.assertEqual([], repository.calls)


if __name__ == "__main__":
    unittest.main()
