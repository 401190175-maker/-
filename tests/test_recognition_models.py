"""Offline contract tests for the 04 recognition execution-layer models."""

from __future__ import annotations

import unittest

from drawing_graph.recognition_models import (
    CacheOutcome,
    CostStatus,
    ProviderErrorCategory,
    RecognitionAttemptStatus,
    RecognitionAttempt,
    RecognitionCandidateEvidence,
    RecognitionCostSummary,
    RecognitionExecutionPolicy,
    RecognitionExecutionRequest,
    RecognitionExecutionResult,
    RecognitionExecutionStatus,
    RecognitionImageRole,
    RecognitionLatencySummary,
    RecognitionProviderUsage,
    RecognitionTaskType,
    UsageStatus,
    ValidatedRecognitionOutput,
    ValidatedRecognitionRequest,
)
from drawing_graph.tool_models import SemanticTargetInput, ToolModelError


class RecognitionTaskTypeTests(unittest.TestCase):
    """RecognitionTaskType must expose exactly the seven stable task types."""

    def test_contains_exactly_seven_design_tasks(self) -> None:
        expected = {
            "page_summary",
            "element_text_observation",
            "block_semantic_identification",
            "basic_info_interpretation",
            "table_interpretation",
            "section_label_observation",
            "relation_evidence_extraction",
        }
        actual = {item.value for item in RecognitionTaskType}
        self.assertEqual(expected, actual)
        self.assertEqual(7, len(RecognitionTaskType))

    def test_values_are_stable_lowercase_strings(self) -> None:
        for item in RecognitionTaskType:
            self.assertIsInstance(item.value, str)
            self.assertEqual(item.value, item.value.lower())

    def test_members_can_be_constructed_from_string(self) -> None:
        self.assertIs(RecognitionTaskType("page_summary"), RecognitionTaskType.PAGE_SUMMARY)

    def test_unknown_value_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RecognitionTaskType("unknown_task")


class RecognitionExecutionStatusTests(unittest.TestCase):
    """RecognitionExecutionStatus must match the design status set."""

    def test_contains_design_statuses(self) -> None:
        expected = {
            "succeeded",
            "partial",
            "ambiguous",
            "not_found",
            "contract_failed",
            "provider_failed",
            "deadline_exceeded",
            "recognition_failed",
        }
        self.assertEqual(expected, {item.value for item in RecognitionExecutionStatus})

    def test_unknown_status_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RecognitionExecutionStatus("unknown")


class RecognitionAttemptStatusTests(unittest.TestCase):
    """RecognitionAttemptStatus must keep attempt-level states distinct."""

    def test_contains_design_attempt_statuses(self) -> None:
        expected = {"succeeded", "retryable_failed", "terminal_failed", "contract_failed"}
        self.assertEqual(expected, {item.value for item in RecognitionAttemptStatus})

    def test_unknown_attempt_status_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RecognitionAttemptStatus("unknown")


class ProviderErrorCategoryTests(unittest.TestCase):
    """Provider error categories used by retry decisions."""

    def test_contains_design_categories(self) -> None:
        expected = {
            "authentication",
            "permission",
            "rate_limited",
            "temporary",
            "timeout",
            "permanent",
            "invalid_response",
        }
        self.assertEqual(expected, {item.value for item in ProviderErrorCategory})

    def test_unknown_category_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ProviderErrorCategory("unknown")


class UsageStatusTests(unittest.TestCase):
    """Usage status must distinguish unavailable from zero."""

    def test_contains_design_usage_statuses(self) -> None:
        self.assertEqual(
            {"available", "partial", "unavailable"},
            {item.value for item in UsageStatus},
        )

    def test_unknown_usage_status_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            UsageStatus("unknown")


class CostStatusTests(unittest.TestCase):
    """Cost status must separate calculated, estimated and unavailable."""

    def test_contains_design_cost_statuses(self) -> None:
        self.assertEqual(
            {"calculated", "estimated", "unavailable"},
            {item.value for item in CostStatus},
        )

    def test_unknown_cost_status_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CostStatus("unknown")


class RecognitionImageRoleTests(unittest.TestCase):
    """Image roles used by the preprocessor and prompt renderer."""

    def test_contains_design_roles(self) -> None:
        self.assertEqual(
            {"target", "context", "page"},
            {item.value for item in RecognitionImageRole},
        )

    def test_unknown_role_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RecognitionImageRole("unknown")


class RecognitionModelPurityTests(unittest.TestCase):
    """The models module must stay free of external-layer imports."""

    def test_module_does_not_import_forbidden_layers(self) -> None:
        from pathlib import Path

        import drawing_graph.recognition_models as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        import_lines = "\n".join(
            line.strip().lower()
            for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))
        )
        for forbidden in ("neo4j", "repository", "cypher", "httpx", "qwen", "facade", "os.environ"):
            self.assertNotIn(forbidden, import_lines)


class RecognitionExecutionPolicyTests(unittest.TestCase):
    """RecognitionExecutionPolicy must reject illegal execution parameters."""

    def test_default_policy_is_valid(self) -> None:
        policy = RecognitionExecutionPolicy()
        self.assertEqual(3, policy.max_attempts)
        self.assertEqual(1, policy.structure_repair_attempts)
        self.assertEqual(60.0, policy.deadline_seconds)
        self.assertEqual(250, policy.base_backoff_ms)
        self.assertEqual(2000, policy.max_backoff_ms)
        self.assertEqual(0.1, policy.jitter_ratio)
        self.assertIsNone(policy.estimated_cost_budget)

    def test_valid_custom_policy(self) -> None:
        policy = RecognitionExecutionPolicy(
            max_attempts=2,
            structure_repair_attempts=1,
            deadline_seconds=30.0,
            base_backoff_ms=100,
            max_backoff_ms=500,
            jitter_ratio=0.2,
            estimated_cost_budget=0.5,
        )
        self.assertEqual(2, policy.max_attempts)
        self.assertEqual(0.5, policy.estimated_cost_budget)

    def test_max_attempts_must_be_positive(self) -> None:
        for value in (0, -1):
            with self.assertRaises(ValueError):
                RecognitionExecutionPolicy(max_attempts=value)

    def test_structure_repair_must_not_exceed_total_attempts(self) -> None:
        with self.assertRaises(ValueError):
            RecognitionExecutionPolicy(max_attempts=2, structure_repair_attempts=2)

    def test_negative_deadline_or_budget_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RecognitionExecutionPolicy(deadline_seconds=-1)
        with self.assertRaises(ValueError):
            RecognitionExecutionPolicy(estimated_cost_budget=-0.1)

    def test_backoff_bounds_must_be_ordered(self) -> None:
        with self.assertRaises(ValueError):
            RecognitionExecutionPolicy(base_backoff_ms=2000, max_backoff_ms=250)

    def test_jitter_ratio_must_be_between_zero_and_one(self) -> None:
        for value in (-0.1, 1.5):
            with self.assertRaises(ValueError):
                RecognitionExecutionPolicy(jitter_ratio=value)


class RecognitionExecutionRequestTests(unittest.TestCase):
    """RecognitionExecutionRequest is the pre-validation input contract."""

    @staticmethod
    def _target() -> SemanticTargetInput:
        return SemanticTargetInput(
            target_id="target-1",
            page_id="page-1",
            target_type="DrawingBlock",
            task_type="block_semantic_identification",
        )

    def test_valid_minimal_request(self) -> None:
        request = RecognitionExecutionRequest(
            request_id="req-1",
            recognition_run_id="run-1",
            page_id="page-1",
            task_type="block_semantic_identification",
            targets=(self._target(),),
            model_profile="default",
            prompt_version="prompt-v1",
        )
        self.assertFalse(request.write_back)
        self.assertEqual(60.0, request.deadline_seconds)
        self.assertEqual("1", request.input_contract_version)
        self.assertEqual("1", request.output_contract_version)
        self.assertEqual("preprocess-v1", request.preprocessing_version)

    def test_write_back_must_be_explicit_boolean(self) -> None:
        request = RecognitionExecutionRequest(
            request_id="req-1",
            recognition_run_id="run-1",
            page_id="page-1",
            task_type="page_summary",
            targets=(self._target(),),
            model_profile="default",
            prompt_version="prompt-v1",
            write_back=True,
        )
        self.assertTrue(request.write_back)

    def test_write_back_defaults_to_false(self) -> None:
        request = RecognitionExecutionRequest(
            request_id="req-1",
            recognition_run_id="run-1",
            page_id="page-1",
            task_type="page_summary",
            targets=(self._target(),),
            model_profile="default",
            prompt_version="prompt-v1",
        )
        self.assertIs(False, request.write_back)

    def test_empty_required_text_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RecognitionExecutionRequest(
                request_id="",
                recognition_run_id="run-1",
                page_id="page-1",
                task_type="page_summary",
                targets=(self._target(),),
                model_profile="default",
                prompt_version="prompt-v1",
            )

    def test_targets_must_be_non_empty_tuple_of_semantic_target_input(self) -> None:
        with self.assertRaises(ValueError):
            RecognitionExecutionRequest(
                request_id="req-1",
                recognition_run_id="run-1",
                page_id="page-1",
                task_type="page_summary",
                targets=(),
                model_profile="default",
                prompt_version="prompt-v1",
            )
        with self.assertRaises(ValueError):
            RecognitionExecutionRequest(
                request_id="req-1",
                recognition_run_id="run-1",
                page_id="page-1",
                task_type="page_summary",
                targets=("not-a-target",),
                model_profile="default",
                prompt_version="prompt-v1",
            )

    def test_negative_deadline_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RecognitionExecutionRequest(
                request_id="req-1",
                recognition_run_id="run-1",
                page_id="page-1",
                task_type="page_summary",
                targets=(self._target(),),
                model_profile="default",
                prompt_version="prompt-v1",
                deadline_seconds=-1,
            )

    def test_dto_rejects_unknown_secret_fields(self) -> None:
        with self.assertRaises(TypeError):
            RecognitionExecutionRequest(
                request_id="req-1",
                recognition_run_id="run-1",
                page_id="page-1",
                task_type="page_summary",
                targets=(self._target(),),
                model_profile="default",
                prompt_version="prompt-v1",
                api_key="secret",
            )


class ValidatedRecognitionRequestTests(unittest.TestCase):
    """ValidatedRecognitionRequest is the post-validation internal projection."""

    @staticmethod
    def _target() -> SemanticTargetInput:
        return SemanticTargetInput(
            target_id="target-1",
            page_id="page-1",
            target_type="DrawingBlock",
            task_type="block_semantic_identification",
        )

    def test_valid_projection(self) -> None:
        request = ValidatedRecognitionRequest(
            request_id="req-1",
            recognition_run_id="run-1",
            page_id="page-1",
            task_type=RecognitionTaskType.BLOCK_SEMANTIC_IDENTIFICATION,
            targets=(self._target(),),
            model_profile="default",
            prompt_version="prompt-v1",
            input_contract_version="1",
            output_contract_version="1",
            preprocessing_version="preprocess-v1",
            write_back=False,
            deadline_seconds=60.0,
            image_path=r"C:\drawings\page-1.png",
            image_size=(1000, 800),
        )
        self.assertEqual((1000, 800), request.image_size)

    def test_repr_must_not_expose_internal_image_path(self) -> None:
        request = ValidatedRecognitionRequest(
            request_id="req-1",
            recognition_run_id="run-1",
            page_id="page-1",
            task_type=RecognitionTaskType.PAGE_SUMMARY,
            targets=(self._target(),),
            model_profile="default",
            prompt_version="prompt-v1",
            input_contract_version="1",
            output_contract_version="1",
            preprocessing_version="preprocess-v1",
            write_back=False,
            deadline_seconds=60.0,
            image_path=r"C:\secrets\drawings\page-1.png",
        )
        self.assertNotIn("secrets", repr(request))
        self.assertNotIn("drawings", repr(request))

    def test_write_back_defaults_to_false(self) -> None:
        request = ValidatedRecognitionRequest(
            request_id="req-1",
            recognition_run_id="run-1",
            page_id="page-1",
            task_type=RecognitionTaskType.PAGE_SUMMARY,
            targets=(self._target(),),
            model_profile="default",
            prompt_version="prompt-v1",
            image_path=None,
        )
        self.assertIs(False, request.write_back)


class RecognitionProviderUsageTests(unittest.TestCase):
    """Provider usage must distinguish unavailable from zero values."""

    def test_valid_usage(self) -> None:
        usage = RecognitionProviderUsage(
            input_tokens=100,
            output_tokens=50,
            image_units=1,
            status="available",
        )
        self.assertEqual(100, usage.input_tokens)
        self.assertEqual(1, usage.image_units)

    def test_unavailable_usage_allows_none_values(self) -> None:
        usage = RecognitionProviderUsage(status="unavailable")
        self.assertIsNone(usage.input_tokens)
        self.assertIsNone(usage.output_tokens)

    def test_negative_token_units_are_rejected(self) -> None:
        for field_name in ("input_tokens", "output_tokens", "image_units"):
            with self.subTest(field=field_name):
                with self.assertRaises(ValueError):
                    RecognitionProviderUsage(**{field_name: -1})

    def test_unknown_usage_status_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RecognitionProviderUsage(status="unknown")


class RecognitionAttemptTests(unittest.TestCase):
    """RecognitionAttempt records one auditable provider call."""

    def test_valid_attempt(self) -> None:
        attempt = RecognitionAttempt(
            attempt_id="attempt-1",
            recognition_run_id="run-1",
            attempt_number=1,
            task_type="page_summary",
            provider="qwen",
            model_name="qwen3-vl-plus",
            request_fingerprint="fp-1",
            prompt_version="prompt-v1",
            output_contract_version="1",
            status="succeeded",
            latency_ms=120.5,
            usage=RecognitionProviderUsage(input_tokens=10, output_tokens=5, status="available"),
            provider_request_id="req-id-1",
        )
        self.assertEqual(1, attempt.attempt_number)
        self.assertEqual(120.5, attempt.latency_ms)

    def test_attempt_number_must_start_at_one(self) -> None:
        with self.assertRaises(ValueError):
            RecognitionAttempt(
                attempt_id="attempt-1",
                recognition_run_id="run-1",
                attempt_number=0,
                task_type="page_summary",
                provider="qwen",
                model_name="m",
                request_fingerprint="fp",
                prompt_version="v",
                output_contract_version="1",
                status="succeeded",
            )

    def test_negative_latency_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RecognitionAttempt(
                attempt_id="attempt-1",
                recognition_run_id="run-1",
                attempt_number=1,
                task_type="page_summary",
                provider="qwen",
                model_name="m",
                request_fingerprint="fp",
                prompt_version="v",
                output_contract_version="1",
                status="succeeded",
                latency_ms=-1,
            )

    def test_attempt_rejects_secret_or_prompt_fields(self) -> None:
        with self.assertRaises(TypeError):
            RecognitionAttempt(
                attempt_id="attempt-1",
                recognition_run_id="run-1",
                attempt_number=1,
                task_type="page_summary",
                provider="qwen",
                model_name="m",
                request_fingerprint="fp",
                prompt_version="v",
                output_contract_version="1",
                status="succeeded",
                prompt="full prompt text",
            )
        with self.assertRaises(TypeError):
            RecognitionAttempt(
                attempt_id="attempt-1",
                recognition_run_id="run-1",
                attempt_number=1,
                task_type="page_summary",
                provider="qwen",
                model_name="m",
                request_fingerprint="fp",
                prompt_version="v",
                output_contract_version="1",
                status="succeeded",
                authorization="Bearer secret",
            )


class RecognitionCostSummaryTests(unittest.TestCase):
    """Cost summary must keep unavailable distinct from zero cost."""

    def test_calculated_cost_requires_numeric_actual_cost(self) -> None:
        summary = RecognitionCostSummary(
            status="calculated",
            actual_cost=0.001,
            currency="USD",
            rate_card_version="rate-v1",
        )
        self.assertEqual(0.001, summary.actual_cost)

    def test_unavailable_cost_must_not_use_zero(self) -> None:
        summary = RecognitionCostSummary(
            status="unavailable",
            estimated_cost=None,
            actual_cost=None,
            reason="no rate card",
        )
        self.assertIsNone(summary.actual_cost)
        with self.assertRaises(ValueError):
            RecognitionCostSummary(status="unavailable", actual_cost=0)

    def test_estimated_status_keeps_actual_cost_null(self) -> None:
        summary = RecognitionCostSummary(status="estimated", estimated_cost=0.05)
        self.assertIsNone(summary.actual_cost)
        with self.assertRaises(ValueError):
            RecognitionCostSummary(status="estimated", estimated_cost=0.05, actual_cost=0.05)

    def test_unknown_cost_status_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RecognitionCostSummary(status="unknown")


class RecognitionLatencySummaryTests(unittest.TestCase):
    """Latency segments must be non-negative and separately traceable."""

    def test_valid_latency_summary(self) -> None:
        summary = RecognitionLatencySummary(
            validation_ms=1.0,
            preprocessing_ms=2.0,
            provider_ms=10.0,
            backoff_ms=3.0,
            output_validation_ms=1.0,
            total_ms=17.0,
        )
        self.assertEqual(17.0, summary.total_ms)

    def test_negative_latency_segment_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RecognitionLatencySummary(total_ms=-1)


class ValidatedRecognitionOutputTests(unittest.TestCase):
    """Validated output carries only task-schema fields."""

    def test_valid_output(self) -> None:
        output = ValidatedRecognitionOutput(
            task_type="page_summary",
            target_id="page-1",
            target_type="DrawingPage",
            status="succeeded",
            output={"summary": "page text"},
            confidence=0.9,
            uncertainties=("low confidence on title",),
        )
        self.assertEqual({"summary": "page text"}, output.output)

    def test_unknown_fact_level_field_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            ValidatedRecognitionOutput(
                task_type="page_summary",
                target_id="page-1",
                target_type="DrawingPage",
                status="succeeded",
                output={"summary": "x"},
                source_fact="not allowed",
            )

    def test_confidence_must_be_between_zero_and_one(self) -> None:
        with self.assertRaises(ValueError):
            ValidatedRecognitionOutput(
                task_type="page_summary",
                target_id="page-1",
                target_type="DrawingPage",
                status="succeeded",
                output={"summary": "x"},
                confidence=1.5,
            )

    def test_unknown_output_status_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ValidatedRecognitionOutput(
                task_type="page_summary",
                target_id="page-1",
                target_type="DrawingPage",
                status="unknown",
                output={"summary": "x"},
            )


class RecognitionCandidateEvidenceTests(unittest.TestCase):
    """Candidate evidence can only be projected as candidate_relation."""

    def test_valid_candidate_evidence(self) -> None:
        evidence = RecognitionCandidateEvidence(
            relation_type="CANDIDATE_CAPTION_OF",
            source_target_id="block-1",
            supporting_target_ids=("caption-1",),
            confidence=0.8,
        )
        self.assertEqual("candidate_relation", evidence.status)

    def test_non_candidate_status_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RecognitionCandidateEvidence(
                relation_type="HAS_CAPTION",
                source_target_id="block-1",
                supporting_target_ids=(),
                status="formal",
            )

    def test_confidence_out_of_range_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RecognitionCandidateEvidence(
                relation_type="CANDIDATE_CAPTION_OF",
                source_target_id="block-1",
                supporting_target_ids=(),
                confidence=2.0,
            )


class RecognitionExecutionResultTests(unittest.TestCase):
    """Execution result is the safe product-level summary contract."""

    def test_default_result_is_valid_and_dry_run(self) -> None:
        result = RecognitionExecutionResult(
            recognition_run_id="run-1",
            status="recognition_failed",
        )
        self.assertFalse(result.persisted)
        self.assertEqual((), result.validated_outputs)
        self.assertEqual((), result.attempts)
        self.assertIsNone(result.payload_ref)
        self.assertIsNone(result.safe_error)

    def test_result_accepts_full_summary(self) -> None:
        result = RecognitionExecutionResult(
            recognition_run_id="run-1",
            status="succeeded",
            validated_outputs=(
                ValidatedRecognitionOutput(
                    task_type="page_summary",
                    target_id="page-1",
                    target_type="DrawingPage",
                    status="succeeded",
                    output={"summary": "x"},
                ),
            ),
            attempts=(),
            warnings=("optional warning",),
            persisted=False,
        )
        self.assertEqual(1, len(result.validated_outputs))
        self.assertEqual(("optional warning",), result.warnings)

    def test_unknown_status_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RecognitionExecutionResult(recognition_run_id="run-1", status="unknown")

    def test_result_rejects_prompt_or_traceback_fields(self) -> None:
        with self.assertRaises(TypeError):
            RecognitionExecutionResult(
                recognition_run_id="run-1",
                status="succeeded",
                prompt="full prompt",
            )
        with self.assertRaises(TypeError):
            RecognitionExecutionResult(
                recognition_run_id="run-1",
                status="succeeded",
                traceback="tb",
            )

    def test_persisted_must_be_boolean(self) -> None:
        with self.assertRaises(ValueError):
            RecognitionExecutionResult(
                recognition_run_id="run-1",
                status="succeeded",
                persisted="yes",
            )


class CacheOutcomeTests(unittest.TestCase):
    def test_cache_outcome_carries_target_disposition_and_reused_ids(self):
        outcome = CacheOutcome(
            target_id="target:1",
            disposition="hit",
            cache_key="semantic:abc",
            reused_evidence_ids=("obs:1",),
            provider_called=False,
        )
        self.assertEqual("target:1", outcome.target_id)
        self.assertEqual("hit", outcome.disposition)
        self.assertEqual("semantic:abc", outcome.cache_key)
        self.assertEqual(("obs:1",), outcome.reused_evidence_ids)
        self.assertFalse(outcome.provider_called)

    def test_miss_outcome_has_provider_called_true(self):
        outcome = CacheOutcome(target_id="target:1", disposition="miss", cache_key="semantic:abc", provider_called=True)
        self.assertEqual("miss", outcome.disposition)
        self.assertTrue(outcome.provider_called)

    def test_rejects_invalid_disposition(self):
        with self.assertRaises(ToolModelError):
            CacheOutcome(target_id="target:1", disposition="not_a_disposition")

    def test_rejects_empty_target_id(self):
        with self.assertRaises(ToolModelError):
            CacheOutcome(target_id="", disposition="hit")


if __name__ == "__main__":
    unittest.main()
