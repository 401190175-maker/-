"""Tests for recognition cost/latency estimation and budget gating."""

import inspect
from pathlib import Path
import unittest

from drawing_graph.assistant_models import (
    EstimateStatus,
    ReasonCode,
    RecognitionPolicy,
    RecognitionTarget,
    RecognitionTargetStatus,
)
from drawing_graph.assistant_recognition_budget import (
    RecognitionBudgetEvaluator,
    RecognitionCostProfile,
    RecognitionEstimator,
)


def make_target(
    target_id: str,
    *,
    task_type: str = "text_observation",
    bbox: dict | None = {"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
    normalized_bbox: dict | None = {
        "x_min": 0.1,
        "y_min": 0.2,
        "x_max": 0.2,
        "y_max": 0.3,
    },
) -> RecognitionTarget:
    return RecognitionTarget(
        target_id=target_id,
        target_type="DrawingElement",
        task_type=task_type,
        target_element_id=f"element:{target_id}",
        page_id="page:1",
        required_outputs=("observation",),
        bbox=bbox,
        normalized_bbox=normalized_bbox,
        covered_requirement_ids=(f"req:{target_id}",),
        status=RecognitionTargetStatus.SELECTED,
    )


def make_profile(**overrides) -> RecognitionCostProfile:
    values = {
        "task_cost": {
            "text_observation": 0.01,
            "structured_interpretation": 0.02,
        },
        "task_latency_ms": {
            "text_observation": 100.0,
            "structured_interpretation": 250.0,
        },
        "model_cost_multiplier": {"qwen-vl": 2.0},
        "model_latency_multiplier": {"qwen-vl": 1.5},
        "area_cost_factor": 0.005,
        "area_latency_factor": 10.0,
    }
    values.update(overrides)
    return RecognitionCostProfile(**values)


class RecognitionEstimatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.estimator = RecognitionEstimator()

    def test_estimates_base_cost_and_latency_by_task_type(self):
        estimate = self.estimator.estimate(
            make_target("t1"),
            make_profile(area_cost_factor=0.0, area_latency_factor=0.0),
        )
        self.assertIsNotNone(estimate)
        cost, latency_ms = estimate
        self.assertAlmostEqual(0.01, cost)
        self.assertAlmostEqual(100.0, latency_ms)

    def test_model_profile_multiplier_applies(self):
        cost, latency_ms = self.estimator.estimate(
            make_target("t2"),
            make_profile(area_cost_factor=0.0, area_latency_factor=0.0),
            model_profile="qwen-vl",
        )
        self.assertAlmostEqual(0.02, cost)
        self.assertAlmostEqual(150.0, latency_ms)

    def test_image_area_factor_applies(self):
        target = make_target("t3")
        normalized_area = (
            (0.2 - 0.1) * (0.3 - 0.2)
        )
        cost, latency_ms = self.estimator.estimate(
            target,
            make_profile(),
        )
        self.assertAlmostEqual(0.01 + 0.005 * normalized_area, cost)
        self.assertAlmostEqual(100.0 + 10.0 * normalized_area, latency_ms)

    def test_no_profile_returns_unavailable_not_zero_cost(self):
        self.assertIsNone(self.estimator.estimate(make_target("t4")))

    def test_unknown_task_type_returns_unavailable(self):
        self.assertIsNone(
            self.estimator.estimate(
                make_target("t5", task_type="unknown_task"),
                make_profile(),
            )
        )

    def test_profile_carries_estimator_version_and_currency(self):
        profile = make_profile()
        self.assertTrue(profile.estimator_version)
        self.assertTrue(profile.currency)

    def test_module_never_reads_credentials_or_network(self):
        module_path = Path(inspect.getfile(RecognitionEstimator))
        source = module_path.read_text(encoding="utf-8")
        self.assertNotIn("api_key", source)
        self.assertNotIn("import requests", source)
        self.assertNotIn("import urllib", source)
        self.assertNotIn("import http", source)


class RecognitionBudgetGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluator = RecognitionBudgetEvaluator(
            estimator=RecognitionEstimator(),
            profile=make_profile(area_cost_factor=0.0, area_latency_factor=0.0),
        )
        self.targets = (
            make_target("t1"),
            make_target("t2"),
            make_target("t3"),
        )

    def test_default_policy_selects_all_targets(self):
        selected, deferred, estimate = self.evaluator.evaluate(
            self.targets,
            RecognitionPolicy(),
        )
        self.assertEqual(("t1", "t2", "t3"), tuple(t.target_id for t in selected))
        self.assertEqual((), deferred)
        self.assertEqual(3, estimate.selected_target_count)
        self.assertEqual(0, estimate.deferred_target_count)

    def test_allow_recognition_false_defers_all_targets(self):
        selected, deferred, estimate = self.evaluator.evaluate(
            self.targets,
            RecognitionPolicy(allow_recognition=False),
        )
        self.assertEqual((), selected)
        self.assertEqual(
            ("t1", "t2", "t3"),
            tuple(t.target_id for t in deferred),
        )
        self.assertTrue(
            all(
                ReasonCode.RECOGNITION_FORBIDDEN in target.reason_codes
                for target in deferred
            )
        )
        self.assertEqual(0, estimate.selected_target_count)
        self.assertEqual(3, estimate.deferred_target_count)
        self.assertEqual(EstimateStatus.NOT_REQUIRED, estimate.status)

    def test_max_targets_selects_stable_prefix_and_defers_rest(self):
        selected, deferred, estimate = self.evaluator.evaluate(
            self.targets,
            RecognitionPolicy(max_targets=2),
        )
        self.assertEqual(("t1", "t2"), tuple(t.target_id for t in selected))
        self.assertEqual(("t3",), tuple(t.target_id for t in deferred))
        self.assertIn(ReasonCode.BUDGET_EXCEEDED, deferred[0].reason_codes)
        self.assertEqual(2, estimate.selected_target_count)
        self.assertEqual(1, estimate.deferred_target_count)

    def test_gating_preserves_covered_requirement_ids(self):
        selected, deferred, _ = self.evaluator.evaluate(
            self.targets,
            RecognitionPolicy(max_targets=1),
        )
        self.assertEqual(("req:t1",), selected[0].covered_requirement_ids)
        self.assertEqual(("req:t2",), deferred[0].covered_requirement_ids)
        self.assertEqual(("req:t3",), deferred[1].covered_requirement_ids)


class RecognitionBudgetHardLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = make_profile(area_cost_factor=0.0, area_latency_factor=0.0)
        self.evaluator = RecognitionBudgetEvaluator(
            estimator=RecognitionEstimator(),
            profile=self.profile,
        )

    def test_cost_cap_defers_targets_with_budget_exceeded(self):
        selected, deferred, estimate = self.evaluator.evaluate(
            (make_target("t1"), make_target("t2")),
            RecognitionPolicy(max_estimated_cost=0.015),
        )
        self.assertEqual(("t1",), tuple(t.target_id for t in selected))
        self.assertEqual(("t2",), tuple(t.target_id for t in deferred))
        self.assertIn(ReasonCode.BUDGET_EXCEEDED, deferred[0].reason_codes)
        self.assertEqual(EstimateStatus.ESTIMATED, estimate.status)
        self.assertAlmostEqual(0.01, estimate.estimated_cost)
        self.assertIn(ReasonCode.BUDGET_EXCEEDED, estimate.reason_codes)

    def test_latency_cap_defers_targets_with_latency_exceeded(self):
        text_target = make_target("t1")
        interpretation_target = make_target(
            "t2",
            task_type="structured_interpretation",
        )
        selected, deferred, estimate = self.evaluator.evaluate(
            (text_target, interpretation_target),
            RecognitionPolicy(max_latency_seconds=0.2),
        )
        self.assertEqual(("t1",), tuple(t.target_id for t in selected))
        self.assertEqual(("t2",), tuple(t.target_id for t in deferred))
        self.assertIn(ReasonCode.LATENCY_EXCEEDED, deferred[0].reason_codes)
        self.assertIn(ReasonCode.LATENCY_EXCEEDED, estimate.reason_codes)

    def test_hard_budget_without_profile_fails_closed(self):
        evaluator = RecognitionBudgetEvaluator(
            estimator=RecognitionEstimator(),
            profile=None,
        )
        selected, deferred, estimate = evaluator.evaluate(
            (make_target("t1"), make_target("t2")),
            RecognitionPolicy(max_estimated_cost=1.0),
        )
        self.assertEqual((), selected)
        self.assertEqual(("t1", "t2"), tuple(t.target_id for t in deferred))
        self.assertTrue(
            all(
                ReasonCode.ESTIMATE_UNAVAILABLE in target.reason_codes
                for target in deferred
            )
        )
        self.assertEqual(EstimateStatus.ESTIMATE_UNAVAILABLE, estimate.status)
        self.assertIsNone(estimate.estimated_cost)
        self.assertIsNone(estimate.estimated_latency_ms)

    def test_retry_count_is_included_in_latency_estimate(self):
        cost, latency_ms = RecognitionEstimator().estimate(
            make_target("t1"),
            self.profile,
            retry_count=1,
        )
        self.assertAlmostEqual(0.01, cost)
        self.assertAlmostEqual(200.0, latency_ms)

    def test_estimate_aggregates_selected_totals(self):
        selected, deferred, estimate = self.evaluator.evaluate(
            (make_target("t1"), make_target("t2")),
            RecognitionPolicy(),
        )
        self.assertEqual(2, len(selected))
        self.assertEqual((), deferred)
        self.assertEqual(EstimateStatus.ESTIMATED, estimate.status)
        self.assertAlmostEqual(0.02, estimate.estimated_cost)
        self.assertAlmostEqual(200.0, estimate.estimated_latency_ms)
        self.assertEqual(2, estimate.selected_target_count)
        self.assertEqual(0, estimate.deferred_target_count)


if __name__ == "__main__":
    unittest.main()
