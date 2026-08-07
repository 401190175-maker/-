import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.recognition_run_log import InMemoryRecognitionRunLog
from drawing_graph.tool_models import ToolModelError


class RecognitionRunLogTest(unittest.TestCase):
    def test_creates_completes_fails_and_reads_graph_external_runs(self):
        log = InMemoryRecognitionRunLog()
        run = log.create_run(
            page_id="page:1",
            model_profile="default",
            prompt_version="p1",
            input_refs={"elements": ["block:1"]},
            write_back=True,
        )

        completed = log.complete_run(run.recognition_run_id, model_name="fake", model_version="v1")
        failed = log.create_run("page:2", "default", "p1", {}, False)
        log.fail_run(failed.recognition_run_id, "timeout")

        self.assertEqual("succeeded", completed.status)
        self.assertEqual("fake", log.get_run(run.recognition_run_id).model_name)
        self.assertEqual("failed", log.get_run(failed.recognition_run_id).status)
        self.assertFalse(hasattr(completed, "labels"))

    def test_missing_run_returns_not_found(self):
        with self.assertRaises(ToolModelError) as error:
            InMemoryRecognitionRunLog().get_run("run:missing")

        self.assertEqual("NOT_FOUND", error.exception.category)

    def test_supports_interpretation_and_candidate_review_run_types(self):
        log = InMemoryRecognitionRunLog()

        interpretation_run = log.create_run(
            page_id="page:1",
            model_profile="vision-v1",
            prompt_version="prompt-v1",
            input_refs={"element_ids": ("block:1",)},
            write_back=True,
            run_type="interpretation",
            target_scope="block:1",
            cost_summary={"tokens": 1200},
        )
        review_run = log.create_run(
            page_id="page:1",
            model_profile="review-v1",
            prompt_version="prompt-v2",
            input_refs={"candidate_group_id": "group:1"},
            write_back=True,
            run_type="candidate_review",
            target_scope="group:1",
            model_name="review-model",
            model_version="r1",
        )
        completed = log.complete_run(interpretation_run.recognition_run_id, model_name="vision-model", model_version="v1")

        self.assertEqual("interpretation", interpretation_run.run_type)
        self.assertEqual("block:1", interpretation_run.target_scope)
        self.assertEqual({"tokens": 1200}, dict(interpretation_run.cost_summary))
        self.assertEqual("candidate_review", review_run.run_type)
        self.assertEqual("review-model", log.get_run(review_run.recognition_run_id).model_name)
        self.assertEqual("interpretation", completed.run_type)
        self.assertEqual("block:1", completed.target_scope)

    def test_run_log_never_creates_driver_or_graph_node_and_queries_do_not_create_runs(self):
        log = InMemoryRecognitionRunLog()
        run = log.create_run("page:1", "default", "p1", {}, False)
        before = len(log._runs)

        log.get_run(run.recognition_run_id)
        log.get_run(run.recognition_run_id)

        self.assertEqual(before, len(log._runs))
        self.assertFalse(hasattr(log, "driver"))
        self.assertFalse(hasattr(log, "labels"))
        self.assertFalse(hasattr(run, "labels"))
        self.assertNotIn("RecognitionRun", repr(run).lower())

    def test_rejects_unsupported_run_type(self):
        with self.assertRaises(ToolModelError) as error:
            InMemoryRecognitionRunLog().create_run(
                page_id="page:1",
                model_profile="default",
                prompt_version="p1",
                input_refs={},
                write_back=False,
                run_type="unsupported",
            )

        self.assertEqual("invalid_run_type", error.exception.category)


if __name__ == "__main__":
    unittest.main()
