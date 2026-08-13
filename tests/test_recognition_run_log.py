import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.recognition_run_log import InMemoryRecognitionRunLog
from drawing_graph.recognition_models import RecognitionLatencySummary, RecognitionProviderUsage
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

    def test_run_summary_carries_execution_audit_defaults(self):
        log = InMemoryRecognitionRunLog()
        run = log.create_run("page:1", "default", "p1", {}, True)

        self.assertEqual((), run.attempt_ids)
        self.assertIsNone(run.usage_summary)
        self.assertIsNone(run.latency_summary)
        self.assertIsNone(run.payload_ref)
        self.assertEqual("1", run.input_contract_version)
        self.assertEqual("1", run.output_contract_version)
        self.assertEqual("preprocess-v1", run.preprocessing_version)

    def test_complete_run_carries_attempt_usage_latency_and_payload(self):
        log = InMemoryRecognitionRunLog()
        run = log.create_run("page:1", "default", "p1", {}, True)
        usage = RecognitionProviderUsage(input_tokens=10, output_tokens=5, status="available")
        latency = RecognitionLatencySummary(provider_ms=10.0, total_ms=10.0)

        completed = log.complete_run(
            run.recognition_run_id,
            model_name="fake",
            model_version="v1",
            attempt_ids=("attempt:1",),
            usage_summary=usage,
            latency_summary=latency,
            payload_ref="payload:1",
            input_contract_version="2",
            output_contract_version="3",
            preprocessing_version="preprocess-v2",
        )

        self.assertEqual(("attempt:1",), completed.attempt_ids)
        self.assertEqual(10, completed.usage_summary.input_tokens)
        self.assertEqual(10.0, completed.latency_summary.provider_ms)
        self.assertEqual("payload:1", completed.payload_ref)
        self.assertEqual("2", completed.input_contract_version)
        self.assertEqual("3", completed.output_contract_version)
        self.assertEqual("preprocess-v2", completed.preprocessing_version)


if __name__ == "__main__":
    unittest.main()
