import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.candidate_review import CandidateReviewError, CandidateReviewRequest
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


def semantic_candidate(candidate_id="candidate:1", observation_ids=("obs:1", "obs:2")):
    return {
        "candidate_id": candidate_id,
        "start_id": "cross-section:1",
        "end_id": "caption:1",
        "page_id": "page:1",
        "relation_spec": "candidate_matches_section_caption",
        "observation_ids": list(observation_ids),
        "crop_ref": "crop:cross-section:1",
    }


def review_request(decision="accepted", candidates=None):
    return CandidateReviewRequest(
        review_run_id="review-run:1",
        relation_spec="candidate_matches_section_caption",
        group_key="group:1",
        source_element_id="cross-section:1",
        page_id="page:1",
        rule_version="match-v1",
        candidates=tuple(candidates or (semantic_candidate(),)),
        evidence_refs=("crop:cross-section:1", "crop:caption:1"),
        context={
            "reviewer": "reviewer:1",
            "reason": "unique same-key caption",
            "page_context": {"page_id": "page:1"},
            "spatial_evidence": {"distance": 0.0},
            "observation_ids": ("obs:1", "obs:2"),
        },
    )


class SemanticCandidateReviewTest(unittest.TestCase):
    def test_request_requires_complete_candidates_evidence_and_observations(self):
        request = review_request()

        self.assertEqual(1, request.candidate_count)
        self.assertEqual(("crop:cross-section:1", "crop:caption:1"), request.evidence_refs)
        self.assertEqual(("obs:1", "obs:2"), request.candidates[0]["observation_ids"])
        self.assertIn("page_context", request.context)
        self.assertIn("spatial_evidence", request.context)

    def test_semantic_candidate_without_observation_ids_is_rejected(self):
        with self.assertRaises(CandidateReviewError) as error:
            review_request(candidates=(semantic_candidate(observation_ids=()),))

        self.assertEqual("missing_observation_evidence", error.exception.category)

    def test_dry_run_review_never_updates_candidate_status(self):
        repository = SpyRepository()
        facade = DrawingGraphToolFacade(
            FakeDrawingGraphReadPort(),
            candidate_relation_port=repository,
        )

        summary = facade.review_candidate_relation(
            candidate_group_id="group:1",
            decision="accepted",
            reviewer="reviewer:1",
            reason="unique same-key caption",
            relation_spec="candidate_matches_section_caption",
            page_id="page:1",
            source_element_id="cross-section:1",
            rule_version="match-v1",
            candidates=(semantic_candidate(),),
            evidence_refs=("crop:cross-section:1", "crop:caption:1"),
            write_back=False,
        )

        self.assertEqual("accepted", summary.status)
        self.assertFalse(summary.persisted)
        self.assertFalse(summary.promoted)
        self.assertEqual([], repository.calls)

    def test_write_back_accepted_updates_and_promotes_through_service_rules(self):
        repository = SpyRepository()
        facade = DrawingGraphToolFacade(
            FakeDrawingGraphReadPort(),
            candidate_relation_port=repository,
        )

        summary = facade.review_candidate_relation(
            candidate_group_id="group:1",
            decision="accepted",
            reviewer="reviewer:1",
            reason="unique same-key caption",
            relation_spec="candidate_matches_section_caption",
            page_id="page:1",
            source_element_id="cross-section:1",
            rule_version="match-v1",
            candidates=(semantic_candidate(),),
            evidence_refs=("crop:cross-section:1", "crop:caption:1"),
            repository=repository,
            write_back=True,
        )

        self.assertTrue(summary.persisted)
        self.assertTrue(summary.promoted)
        self.assertEqual(("update_candidate_review", "promote_candidate_relation"), tuple(call[0] for call in repository.calls))
        update_kwargs = repository.calls[0][1]
        self.assertEqual("candidate_matches_section_caption", update_kwargs["relation_spec"])
        self.assertEqual("cross-section:1", update_kwargs["start_id"])
        self.assertEqual("caption:1", update_kwargs["end_id"])
        promote_kwargs = repository.calls[1][1]
        self.assertEqual("candidate_matches_section_caption", promote_kwargs["relation_spec"])
        self.assertEqual("cross-section:1", promote_kwargs["candidate_start_id"])

    def test_accepted_with_multiple_candidates_fails_hard_rule(self):
        facade = DrawingGraphToolFacade(
            FakeDrawingGraphReadPort(),
            candidate_relation_port=SpyRepository(),
        )
        candidates = (
            semantic_candidate(),
            semantic_candidate("candidate:2", ("obs:3", "obs:4")),
        )

        with self.assertRaises(ToolModelError) as error:
            facade.review_candidate_relation(
                candidate_group_id="group:1",
                decision="accepted",
                reviewer="reviewer:1",
                reason="accepted but not unique",
                relation_spec="candidate_matches_section_caption",
                page_id="page:1",
                source_element_id="cross-section:1",
                rule_version="match-v1",
                candidates=candidates,
                evidence_refs=("crop:cross-section:1", "crop:caption:1"),
                write_back=True,
            )

        self.assertEqual("CANDIDATE_REVIEW_REJECTED", error.exception.category)

    def test_rejected_and_unresolved_review_do_not_promote(self):
        repository = SpyRepository()
        facade = DrawingGraphToolFacade(
            FakeDrawingGraphReadPort(),
            candidate_relation_port=repository,
        )

        rejected = facade.review_candidate_relation(
            candidate_group_id="group:1",
            decision="rejected",
            reviewer="reviewer:1",
            reason="caption belongs to another section",
            relation_spec="candidate_matches_section_caption",
            page_id="page:1",
            source_element_id="cross-section:1",
            rule_version="match-v1",
            candidates=(semantic_candidate(),),
            evidence_refs=("crop:cross-section:1", "crop:caption:1"),
            repository=repository,
            write_back=True,
        )
        unresolved = facade.review_candidate_relation(
            candidate_group_id="group:1",
            decision="unresolved",
            reviewer="reviewer:1",
            reason="cannot decide",
            relation_spec="candidate_matches_section_caption",
            page_id="page:1",
            source_element_id="cross-section:1",
            rule_version="match-v1",
            candidates=(semantic_candidate(),),
            evidence_refs=("crop:cross-section:1", "crop:caption:1"),
            repository=repository,
            write_back=True,
        )

        self.assertEqual("rejected", rejected.status)
        self.assertEqual("unresolved", unresolved.status)
        self.assertEqual(("update_candidate_review", "update_candidate_review"), tuple(call[0] for call in repository.calls))
        self.assertFalse(any(call[0] == "promote_candidate_relation" for call in repository.calls))


if __name__ == "__main__":
    unittest.main()
