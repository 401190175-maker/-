import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def candidate(candidate_id="candidate:caption:1:block:1", **overrides):
    values = {
        "candidate_id": candidate_id,
        "start_id": "caption:1",
        "end_id": "block:1",
        "page_id": "page:road:set-a:road_24",
        "relation_spec": "candidate_caption_of",
        "score": 0.91,
    }
    values.update(overrides)
    return values


def request(**overrides):
    from drawing_graph.candidate_review import CandidateReviewRequest

    values = {
        "review_run_id": "review-run:001",
        "relation_spec": "candidate_caption_of",
        "group_key": "caption:1",
        "source_element_id": "caption:1",
        "page_id": "page:road:set-a:road_24",
        "rule_version": "relation-rules-v1",
        "candidates": (candidate(),),
        "evidence_refs": ("crop:caption:1", "page-context:road_24"),
    }
    values.update(overrides)
    return CandidateReviewRequest(**values)


class CandidateReviewModelsTest(unittest.TestCase):
    def test_request_requires_complete_candidate_set_evidence_and_review_run(self):
        from drawing_graph.candidate_review import CandidateReviewError

        review_request = request()

        self.assertEqual("review-run:001", review_request.review_run_id)
        self.assertEqual("candidate_caption_of", review_request.relation_spec)
        self.assertEqual(1, review_request.candidate_count)
        self.assertEqual(("crop:caption:1", "page-context:road_24"), review_request.evidence_refs)

        with self.assertRaises(CandidateReviewError) as context:
            request(candidates=())
        self.assertEqual("missing_candidates", context.exception.category)

        with self.assertRaises(CandidateReviewError) as context:
            request(evidence_refs=())
        self.assertEqual("missing_evidence_refs", context.exception.category)

        with self.assertRaises(CandidateReviewError) as context:
            request(review_run_id="")
        self.assertEqual("missing_required_field", context.exception.category)

    def test_request_and_nested_candidates_are_immutable(self):
        review_request = request()

        with self.assertRaises(FrozenInstanceError):
            review_request.review_run_id = "review-run:changed"
        with self.assertRaises(TypeError):
            review_request.candidates[0]["score"] = 0.1

    def test_result_accepts_only_supported_statuses_and_requires_unique_accepted_candidate(self):
        from drawing_graph.candidate_review import CandidateReviewError, CandidateReviewResult

        accepted = CandidateReviewResult(
            review_run_id="review-run:001",
            relation_spec="candidate_caption_of",
            status="accepted",
            accepted_candidate_id="candidate:caption:1:block:1",
            model_version="vision-model-v1",
            prompt_version="prompt-v1",
            score=0.88,
            reason="the caption visually belongs to the selected block",
        )

        self.assertEqual("accepted", accepted.status)
        self.assertEqual("candidate:caption:1:block:1", accepted.accepted_candidate_id)

        with self.assertRaises(CandidateReviewError) as context:
            CandidateReviewResult(
                review_run_id="review-run:001",
                relation_spec="candidate_caption_of",
                status="accepted",
            )
        self.assertEqual("missing_accepted_candidate", context.exception.category)

        with self.assertRaises(CandidateReviewError) as context:
            CandidateReviewResult(
                review_run_id="review-run:001",
                relation_spec="candidate_caption_of",
                status="confirmed",
            )
        self.assertEqual("invalid_review_status", context.exception.category)

    def test_non_accepted_result_cannot_carry_accepted_candidate_id(self):
        from drawing_graph.candidate_review import CandidateReviewError, CandidateReviewResult

        unresolved = CandidateReviewResult(
            review_run_id="review-run:001",
            relation_spec="candidate_caption_of",
            status="unresolved",
            reason="visual evidence is unclear",
        )

        self.assertEqual("unresolved", unresolved.status)
        self.assertIsNone(unresolved.accepted_candidate_id)

        with self.assertRaises(CandidateReviewError) as context:
            CandidateReviewResult(
                review_run_id="review-run:001",
                relation_spec="candidate_caption_of",
                status="rejected",
                accepted_candidate_id="candidate:caption:1:block:1",
            )
        self.assertEqual("unexpected_accepted_candidate", context.exception.category)


if __name__ == "__main__":
    unittest.main()
