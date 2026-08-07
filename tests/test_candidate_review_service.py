import sys
import unittest
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


class StructuredClient:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def review(self, review_request):
        self.requests.append(review_request)
        return self.response


class FailingClient:
    def review(self, review_request):
        raise RuntimeError("model endpoint unavailable")


class RecordingRepository:
    def __init__(self, *, fail_update=False, fail_promote=False):
        self.fail_update = fail_update
        self.fail_promote = fail_promote
        self.review_updates = []
        self.promotions = []

    def update_candidate_review(self, **kwargs):
        self.review_updates.append(kwargs)
        if self.fail_update:
            raise RuntimeError("password=hunter2")

    def promote_candidate_relation(self, **kwargs):
        self.promotions.append(kwargs)
        if self.fail_promote:
            raise RuntimeError("password=hunter2")


class CandidateReviewServiceTest(unittest.TestCase):
    def test_service_calls_injected_client_and_returns_structured_result(self):
        from drawing_graph.candidate_review import CandidateReviewService

        review_request = request()
        service = CandidateReviewService(
            StructuredClient(
                {
                    "status": "accepted",
                    "accepted_candidate_id": "candidate:caption:1:block:1",
                    "model_version": "vision-model-v1",
                    "prompt_version": "candidate-review-v1",
                    "score": 0.89,
                    "reason": "caption and block align visually",
                }
            )
        )

        result = service.review_candidate_group(review_request)

        self.assertEqual("accepted", result.status)
        self.assertEqual("candidate:caption:1:block:1", result.accepted_candidate_id)
        self.assertEqual("vision-model-v1", result.model_version)
        self.assertIsNone(result.issue_category)

    def test_client_unavailable_returns_unresolved_review_result(self):
        from drawing_graph.candidate_review import CandidateReviewService

        result = CandidateReviewService(FailingClient()).review_candidate_group(request())

        self.assertEqual("unresolved", result.status)
        self.assertEqual("candidate_review_unavailable", result.issue_category)
        self.assertIn("unavailable", result.reason)

    def test_invalid_client_output_returns_unresolved_review_result(self):
        from drawing_graph.candidate_review import CandidateReviewService

        result = CandidateReviewService(StructuredClient({"status": "confirmed"})).review_candidate_group(request())

        self.assertEqual("unresolved", result.status)
        self.assertEqual("candidate_review_invalid_output", result.issue_category)
        self.assertIsNone(result.accepted_candidate_id)

    def test_accepted_candidate_must_exist_in_current_complete_candidate_group(self):
        from drawing_graph.candidate_review import CandidateReviewService

        result = CandidateReviewService(
            StructuredClient(
                {
                    "status": "accepted",
                    "accepted_candidate_id": "candidate:caption:1:block:missing",
                    "score": 0.8,
                }
            )
        ).review_candidate_group(request())

        self.assertEqual("unresolved", result.status)
        self.assertEqual("candidate_promotion_rule_failed", result.issue_category)

    def test_accepted_candidate_requires_unique_same_page_candidate_with_matching_spec(self):
        from drawing_graph.candidate_review import CandidateReviewService

        duplicate_candidate = candidate(
            "candidate:caption:1:block:1",
            start_id="caption:1",
            end_id="block:duplicate",
        )
        wrong_page_candidate = candidate(
            "candidate:caption:1:block:2",
            end_id="block:2",
            page_id="page:road:set-a:road_25",
        )
        wrong_spec_candidate = candidate(
            "candidate:caption:1:block:3",
            end_id="block:3",
            relation_spec="candidate_section_mark",
        )

        duplicate_result = CandidateReviewService(
            StructuredClient({"status": "accepted", "accepted_candidate_id": "candidate:caption:1:block:1"})
        ).review_candidate_group(request(candidates=(candidate(), duplicate_candidate)))
        wrong_page_result = CandidateReviewService(
            StructuredClient({"status": "accepted", "accepted_candidate_id": "candidate:caption:1:block:2"})
        ).review_candidate_group(request(candidates=(wrong_page_candidate,)))
        wrong_spec_result = CandidateReviewService(
            StructuredClient({"status": "accepted", "accepted_candidate_id": "candidate:caption:1:block:3"})
        ).review_candidate_group(request(candidates=(wrong_spec_candidate,)))

        self.assertEqual("candidate_promotion_rule_failed", duplicate_result.issue_category)
        self.assertEqual("candidate_promotion_rule_failed", wrong_page_result.issue_category)
        self.assertEqual("candidate_promotion_rule_failed", wrong_spec_result.issue_category)

    def test_rejected_and_unresolved_results_do_not_trigger_promotion_rule_failure(self):
        from drawing_graph.candidate_review import CandidateReviewService

        rejected = CandidateReviewService(
            StructuredClient({"status": "rejected", "reason": "none of the candidates is reliable"})
        ).review_candidate_group(request())
        unresolved = CandidateReviewService(
            StructuredClient({"status": "unresolved", "reason": "evidence is ambiguous"})
        ).review_candidate_group(request())

        self.assertEqual("rejected", rejected.status)
        self.assertIsNone(rejected.issue_category)
        self.assertEqual("unresolved", unresolved.status)
        self.assertIsNone(unresolved.issue_category)

    def test_accepted_result_updates_candidate_review_and_promotes_formal_relation(self):
        from drawing_graph.candidate_review import CandidateReviewService

        repository = RecordingRepository()
        result = CandidateReviewService(
            StructuredClient(
                {
                    "status": "accepted",
                    "accepted_candidate_id": "candidate:caption:1:block:1",
                    "model_version": "vision-model-v1",
                    "prompt_version": "candidate-review-v1",
                    "score": 0.91,
                    "reason": "candidate is visually best",
                }
            ),
            repository=repository,
        ).review_candidate_group(request())

        self.assertEqual("accepted", result.status)
        self.assertEqual(
            {
                "relation_spec": "candidate_caption_of",
                "start_id": "caption:1",
                "end_id": "block:1",
                "rule_version": "relation-rules-v1",
                "review_status": "accepted",
                "review_run_id": "review-run:001",
                "review_model_version": "vision-model-v1",
                "review_prompt_version": "candidate-review-v1",
                "review_score": 0.91,
                "review_reason": "candidate is visually best",
            },
            repository.review_updates[0],
        )
        self.assertEqual(
            {
                "relation_spec": "candidate_caption_of",
                "candidate_start_id": "caption:1",
                "candidate_end_id": "block:1",
                "candidate_rule_version": "relation-rules-v1",
                "review_status": "accepted",
                "review_run_id": "review-run:001",
                "formal_rule_version": "relation-rules-v1",
                "confirmation_method": "multimodal_llm",
            },
            repository.promotions[0],
        )

    def test_rejected_and_unresolved_results_update_candidate_without_promotion(self):
        from drawing_graph.candidate_review import CandidateReviewService

        rejected_repository = RecordingRepository()
        unresolved_repository = RecordingRepository()

        CandidateReviewService(
            StructuredClient({"status": "rejected", "reason": "no candidate is reliable"}),
            repository=rejected_repository,
        ).review_candidate_group(request())
        CandidateReviewService(
            StructuredClient({"status": "unresolved", "reason": "ambiguous candidate group"}),
            repository=unresolved_repository,
        ).review_candidate_group(request())

        self.assertEqual("rejected", rejected_repository.review_updates[0]["review_status"])
        self.assertEqual([], rejected_repository.promotions)
        self.assertEqual("unresolved", unresolved_repository.review_updates[0]["review_status"])
        self.assertEqual([], unresolved_repository.promotions)

    def test_candidate_review_write_failure_returns_unresolved_without_leaking_secret(self):
        from drawing_graph.candidate_review import CandidateReviewService

        result = CandidateReviewService(
            StructuredClient(
                {
                    "status": "accepted",
                    "accepted_candidate_id": "candidate:caption:1:block:1",
                }
            ),
            repository=RecordingRepository(fail_update=True),
        ).review_candidate_group(request())

        self.assertEqual("unresolved", result.status)
        self.assertEqual("candidate_review_write_failed", result.issue_category)
        self.assertNotIn("hunter2", result.reason)


if __name__ == "__main__":
    unittest.main()
