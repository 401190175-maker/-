"""Contract tests for semantic gap decision product DTOs and enums."""

import dataclasses
import unittest

from drawing_graph.assistant_models import (
    CacheCandidate,
    CacheDisposition,
    CONTRACT_VERSION,
    EstimateStatus,
    EvidenceItem,
    FactKind,
    FreshnessPolicy,
    FreshnessRequirement,
    FreshnessResult,
    ReasonCode,
    RecognitionEstimate,
    RecognitionPolicy,
    RecognitionTarget,
    RecognitionTargetStatus,
    RequirementAssessment,
    RequirementAssessmentStatus,
    SemanticGapDecision,
    SemanticGapDecisionType,
)


class SemanticGapDecisionTypeTests(unittest.TestCase):
    def test_contains_all_required_values(self):
        self.assertEqual(
            {
                "reuse_existing",
                "recognize_required",
                "clarification_required",
                "unsupported",
            },
            {item.value for item in SemanticGapDecisionType},
        )

    def test_values_are_stable_lowercase_strings(self):
        self.assertEqual("reuse_existing", SemanticGapDecisionType.REUSE_EXISTING.value)
        self.assertEqual("recognize_required", SemanticGapDecisionType.RECOGNIZE_REQUIRED.value)
        self.assertEqual("clarification_required", SemanticGapDecisionType.CLARIFICATION_REQUIRED.value)
        self.assertEqual("unsupported", SemanticGapDecisionType.UNSUPPORTED.value)
        self.assertTrue(all(item.value.islower() for item in SemanticGapDecisionType))


class RequirementAssessmentStatusTests(unittest.TestCase):
    def test_contains_all_required_values(self):
        self.assertEqual(
            {
                "satisfied",
                "missing",
                "stale",
                "conflicting",
                "forbidden",
                "unsupported",
                "formal_review_required",
            },
            {item.value for item in RequirementAssessmentStatus},
        )

    def test_values_are_stable_lowercase_strings(self):
        self.assertEqual("satisfied", RequirementAssessmentStatus.SATISFIED.value)
        self.assertEqual("formal_review_required", RequirementAssessmentStatus.FORMAL_REVIEW_REQUIRED.value)
        self.assertTrue(all(item.value.islower() for item in RequirementAssessmentStatus))


class CacheDispositionTests(unittest.TestCase):
    def test_contains_all_required_values(self):
        self.assertEqual(
            {"full_hit", "partial_hit", "miss", "stale", "bypassed", "unknown"},
            {item.value for item in CacheDisposition},
        )

    def test_values_are_stable_lowercase_strings(self):
        self.assertEqual("full_hit", CacheDisposition.FULL_HIT.value)
        self.assertEqual("unknown", CacheDisposition.UNKNOWN.value)
        self.assertTrue(all(item.value.islower() for item in CacheDisposition))


class RecognitionTargetStatusTests(unittest.TestCase):
    def test_contains_all_required_values(self):
        self.assertEqual(
            {"selected", "deferred", "blocked"},
            {item.value for item in RecognitionTargetStatus},
        )

    def test_values_are_stable_lowercase_strings(self):
        self.assertEqual("selected", RecognitionTargetStatus.SELECTED.value)
        self.assertEqual("deferred", RecognitionTargetStatus.DEFERRED.value)
        self.assertEqual("blocked", RecognitionTargetStatus.BLOCKED.value)


class EstimateStatusTests(unittest.TestCase):
    def test_contains_all_required_values(self):
        self.assertEqual(
            {
                "estimated",
                "not_required",
                "estimate_unavailable",
                "budget_exceeded",
                "latency_exceeded",
            },
            {item.value for item in EstimateStatus},
        )

    def test_values_are_stable_lowercase_strings(self):
        self.assertEqual("estimate_unavailable", EstimateStatus.ESTIMATE_UNAVAILABLE.value)
        self.assertTrue(all(item.value.islower() for item in EstimateStatus))


class SemanticGapReasonCodeTests(unittest.TestCase):
    REQUIRED_REASON_CODES = {
        "evidence_complete",
        "evidence_missing",
        "observation_missing",
        "interpretation_missing",
        "evidence_stale",
        "image_changed",
        "bbox_changed",
        "model_profile_changed",
        "prompt_version_changed",
        "contract_version_changed",
        "preprocessing_version_changed",
        "normalization_rule_changed",
        "evidence_conflict",
        "status_insufficient",
        "evidence_kind_mismatch",
        "recognition_forbidden",
        "budget_exceeded",
        "latency_exceeded",
        "estimate_unavailable",
        "formal_review_required",
        "unsupported_generation",
        "cache_key_unavailable",
        "target_location_missing",
    }

    def test_reason_code_contains_all_semantic_gap_codes(self):
        self.assertTrue(self.REQUIRED_REASON_CODES.issubset({item.value for item in ReasonCode}))

    def test_reason_code_values_are_stable_strings(self):
        self.assertEqual("evidence_missing", ReasonCode.EVIDENCE_MISSING.value)
        self.assertEqual("recognition_forbidden", ReasonCode.RECOGNITION_FORBIDDEN.value)
        self.assertEqual("formal_review_required", ReasonCode.FORMAL_REVIEW_REQUIRED.value)


class FreshnessRequirementTests(unittest.TestCase):
    def test_defaults_require_nothing_and_reject_stale(self):
        requirement = FreshnessRequirement()
        self.assertFalse(requirement.require_current_image)
        self.assertFalse(requirement.require_current_bbox)
        self.assertFalse(requirement.require_current_model)
        self.assertFalse(requirement.require_current_prompt)
        self.assertFalse(requirement.require_current_preprocessing)
        self.assertFalse(requirement.require_current_normalization)
        self.assertFalse(requirement.require_current_contract)
        self.assertFalse(requirement.allow_stale)
        self.assertIsNone(requirement.max_age_seconds)

    def test_combined_freshness_dimensions_are_supported(self):
        requirement = FreshnessRequirement(
            require_current_image=True,
            require_current_bbox=True,
            require_current_model=True,
            require_current_prompt=True,
            require_current_preprocessing=True,
            require_current_normalization=True,
            require_current_contract=True,
            max_age_seconds=3600,
        )
        self.assertTrue(requirement.require_current_image)
        self.assertTrue(requirement.require_current_contract)
        self.assertEqual(3600, requirement.max_age_seconds)

    def test_from_policy_maps_legacy_policies(self):
        self.assertEqual(
            FreshnessRequirement(),
            FreshnessRequirement.from_policy(FreshnessPolicy.ANY),
        )
        self.assertTrue(
            FreshnessRequirement.from_policy(FreshnessPolicy.CURRENT_IMAGE).require_current_image
        )
        self.assertTrue(
            FreshnessRequirement.from_policy(FreshnessPolicy.CURRENT_IMAGE).require_current_bbox
        )
        self.assertTrue(
            FreshnessRequirement.from_policy(FreshnessPolicy.CURRENT_PROMPT).require_current_prompt
        )
        self.assertTrue(
            FreshnessRequirement.from_policy(FreshnessPolicy.CURRENT_CONTRACT).require_current_contract
        )

    def test_from_policy_accepts_stable_string(self):
        self.assertTrue(
            FreshnessRequirement.from_policy("current_image").require_current_image
        )

    def test_serializes_to_stable_mapping(self):
        requirement = FreshnessRequirement(require_current_image=True)
        serialized = dataclasses.asdict(requirement)
        self.assertTrue(serialized["require_current_image"])
        self.assertFalse(serialized["require_current_contract"])

    def test_negative_age_and_non_boolean_flags_are_rejected(self):
        with self.assertRaises(ValueError):
            FreshnessRequirement(max_age_seconds=-1)
        with self.assertRaises(ValueError):
            FreshnessRequirement(require_current_image="yes")


class FreshnessResultTests(unittest.TestCase):
    def test_result_carries_dimensions_missing_metadata_and_reason_codes(self):
        result = FreshnessResult(
            dimensions={"image_hash": True, "bbox": False},
            missing_metadata=("prompt_version",),
            reason_codes=(ReasonCode.PROMPT_VERSION_CHANGED,),
            is_current=False,
        )
        self.assertTrue(result.dimensions["image_hash"])
        self.assertFalse(result.dimensions["bbox"])
        self.assertEqual(("prompt_version",), result.missing_metadata)
        self.assertEqual((ReasonCode.PROMPT_VERSION_CHANGED,), result.reason_codes)
        self.assertFalse(result.is_current)

    def test_missing_metadata_is_never_defaulted_to_valid(self):
        result = FreshnessResult(
            dimensions={},
            missing_metadata=("image_hash", "bbox", "model_version"),
            reason_codes=(),
            is_current=False,
        )
        self.assertEqual(3, len(result.missing_metadata))
        self.assertFalse(result.is_current)

    def test_dimensions_are_immutable_and_reason_codes_are_coerced(self):
        result = FreshnessResult(
            dimensions={"bbox": True},
            reason_codes=("bbox_changed",),
            is_current=True,
        )
        with self.assertRaises(TypeError):
            result.dimensions["bbox"] = False
        self.assertEqual(ReasonCode.BBOX_CHANGED, result.reason_codes[0])

    def test_invalid_dimension_values_are_rejected(self):
        with self.assertRaises(ValueError):
            FreshnessResult(dimensions={"image_hash": "unknown"}, is_current=False)


class CacheCandidateTests(unittest.TestCase):
    def test_candidate_carries_requirement_target_key_and_disposition(self):
        candidate = CacheCandidate(
            requirement_id="req:1",
            target_id="target:1",
            cache_key="semantic:abc",
            disposition=CacheDisposition.PARTIAL_HIT,
            reusable_evidence_ids=("evidence:1",),
            reason_codes=(ReasonCode.EVIDENCE_MISSING,),
        )
        self.assertEqual("req:1", candidate.requirement_id)
        self.assertEqual("target:1", candidate.target_id)
        self.assertEqual("semantic:abc", candidate.cache_key)
        self.assertEqual(CacheDisposition.PARTIAL_HIT, candidate.disposition)
        self.assertEqual(("evidence:1",), candidate.reusable_evidence_ids)
        self.assertEqual((ReasonCode.EVIDENCE_MISSING,), candidate.reason_codes)

    def test_unknown_disposition_is_default(self):
        candidate = CacheCandidate(requirement_id="req:1")
        self.assertEqual(CacheDisposition.UNKNOWN, candidate.disposition)
        self.assertIsNone(candidate.cache_key)
        self.assertEqual((), candidate.reusable_evidence_ids)

    def test_requirement_id_cannot_be_empty(self):
        with self.assertRaises(ValueError):
            CacheCandidate(requirement_id="")

    def test_disposition_accepts_stable_string(self):
        candidate = CacheCandidate(requirement_id="req:1", disposition="miss")
        self.assertEqual(CacheDisposition.MISS, candidate.disposition)


class RecognitionPolicyTests(unittest.TestCase):
    def test_defaults_allow_recognition_with_bounded_read_only_values(self):
        policy = RecognitionPolicy()
        self.assertTrue(policy.allow_recognition)
        self.assertIsNone(policy.max_targets)
        self.assertIsNone(policy.max_estimated_cost)
        self.assertIsNone(policy.max_latency_seconds)
        self.assertEqual("default", policy.cache_mode)
        self.assertEqual(CONTRACT_VERSION, policy.contract_version)
        self.assertIsNone(policy.model_profile)
        self.assertEqual(0, policy.retry_count)

    def test_policy_carries_model_prompt_contract_strategy(self):
        policy = RecognitionPolicy(
            allow_recognition=True,
            max_targets=10,
            max_estimated_cost=5.0,
            max_latency_seconds=30.0,
            model_profile="qwen-vl",
            model_version="1.0",
            prompt_version="prompt:v1",
            preprocessing_version="pre:v1",
            normalization_rule_version="norm:v1",
            contract_version="contract:v1",
            cache_mode="bypass",
            retry_count=2,
        )
        self.assertEqual(10, policy.max_targets)
        self.assertEqual(5.0, policy.max_estimated_cost)
        self.assertEqual("bypass", policy.cache_mode)
        self.assertEqual("contract:v1", policy.contract_version)
        self.assertEqual(2, policy.retry_count)

    def test_non_boolean_authorization_is_rejected(self):
        with self.assertRaises(ValueError):
            RecognitionPolicy(allow_recognition="yes")

    def test_negative_budget_and_latency_are_rejected(self):
        with self.assertRaises(ValueError):
            RecognitionPolicy(max_estimated_cost=-0.1)
        with self.assertRaises(ValueError):
            RecognitionPolicy(max_latency_seconds=-1)

    def test_invalid_max_targets_is_rejected(self):
        with self.assertRaises(ValueError):
            RecognitionPolicy(max_targets=0)
        with self.assertRaises(ValueError):
            RecognitionPolicy(max_targets=-3)

    def test_empty_contract_version_and_unknown_cache_mode_are_rejected(self):
        with self.assertRaises(ValueError):
            RecognitionPolicy(contract_version="")
        with self.assertRaises(ValueError):
            RecognitionPolicy(cache_mode="auto")


class RequirementAssessmentTests(unittest.TestCase):
    def test_assessment_carries_status_evidence_ids_and_reason_codes(self):
        assessment = RequirementAssessment(
            requirement_id="req:1",
            status=RequirementAssessmentStatus.MISSING,
            matched_evidence_ids=("evidence:1",),
            rejected_evidence_ids=("evidence:2",),
            reason_codes=(ReasonCode.EVIDENCE_MISSING,),
            allow_model_generation=True,
        )
        self.assertEqual("req:1", assessment.requirement_id)
        self.assertEqual(RequirementAssessmentStatus.MISSING, assessment.status)
        self.assertEqual(("evidence:1",), assessment.matched_evidence_ids)
        self.assertEqual(("evidence:2",), assessment.rejected_evidence_ids)
        self.assertEqual((ReasonCode.EVIDENCE_MISSING,), assessment.reason_codes)
        self.assertTrue(assessment.allow_model_generation)

    def test_status_accepts_stable_string_and_defaults_are_safe(self):
        assessment = RequirementAssessment(requirement_id="req:2", status="satisfied")
        self.assertEqual(RequirementAssessmentStatus.SATISFIED, assessment.status)
        self.assertEqual((), assessment.matched_evidence_ids)
        self.assertEqual((), assessment.rejected_evidence_ids)
        self.assertFalse(assessment.allow_model_generation)

    def test_empty_requirement_id_is_rejected(self):
        with self.assertRaises(ValueError):
            RequirementAssessment(requirement_id="")

    def test_invalid_status_and_reason_code_are_rejected(self):
        with self.assertRaises(ValueError):
            RequirementAssessment(requirement_id="req:3", status="unknown_status")
        with self.assertRaises(ValueError):
            RequirementAssessment(requirement_id="req:4", reason_codes=("not_a_code",))


class RecognitionTargetTests(unittest.TestCase):
    def test_target_carries_page_element_bbox_task_and_coverage(self):
        target = RecognitionTarget(
            target_id="target:1",
            page_id="page:1",
            target_element_id="element:1",
            target_type="DrawingBlock",
            task_type="block_semantic_identification",
            required_outputs=("interpretation",),
            bbox={"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
            normalized_bbox={"x_min": 0.1, "y_min": 0.2, "x_max": 0.3, "y_max": 0.4},
            context_element_ids=("element:2",),
            covered_requirement_ids=("req:1", "req:2"),
            cache_key="semantic:abc",
            priority=5,
            status=RecognitionTargetStatus.SELECTED,
            reason_codes=(ReasonCode.EVIDENCE_MISSING,),
        )
        self.assertEqual("target:1", target.target_id)
        self.assertEqual("page:1", target.page_id)
        self.assertEqual("element:1", target.target_element_id)
        self.assertEqual("block_semantic_identification", target.task_type)
        self.assertEqual(("req:1", "req:2"), target.covered_requirement_ids)
        self.assertEqual({"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4}, dict(target.bbox))
        self.assertEqual(5, target.priority)
        self.assertEqual(RecognitionTargetStatus.SELECTED, target.status)

    def test_empty_target_id_or_task_type_is_rejected(self):
        with self.assertRaises(ValueError):
            RecognitionTarget(target_id="", target_type="block", task_type="t")
        with self.assertRaises(ValueError):
            RecognitionTarget(target_id="target:2", target_type="", task_type="t")

    def test_empty_covered_requirement_ids_is_rejected(self):
        with self.assertRaises(ValueError):
            RecognitionTarget(
                target_id="target:3",
                target_type="block",
                task_type="t",
                covered_requirement_ids=(),
            )

    def test_negative_priority_is_rejected(self):
        with self.assertRaises(ValueError):
            RecognitionTarget(
                target_id="target:4",
                target_type="block",
                task_type="t",
                covered_requirement_ids=("req:1",),
                priority=-1,
            )

    def test_status_accepts_stable_string(self):
        target = RecognitionTarget(
            target_id="target:5",
            target_type="page",
            task_type="page_summary",
            covered_requirement_ids=("req:1",),
            status="deferred",
        )
        self.assertEqual(RecognitionTargetStatus.DEFERRED, target.status)


class RecognitionEstimateTests(unittest.TestCase):
    def test_estimate_carries_counts_cost_latency_and_version(self):
        estimate = RecognitionEstimate(
            status=EstimateStatus.ESTIMATED,
            selected_target_count=2,
            deferred_target_count=1,
            estimated_cost=0.4,
            estimated_latency_ms=1500.0,
            currency="CNY",
            estimator_version="semantic-gap-estimator-v1",
            reason_codes=(ReasonCode.BUDGET_EXCEEDED,),
        )
        self.assertEqual(EstimateStatus.ESTIMATED, estimate.status)
        self.assertEqual(2, estimate.selected_target_count)
        self.assertEqual(1, estimate.deferred_target_count)
        self.assertEqual(0.4, estimate.estimated_cost)
        self.assertEqual(1500.0, estimate.estimated_latency_ms)
        self.assertEqual("CNY", estimate.currency)

    def test_negative_counts_are_rejected(self):
        with self.assertRaises(ValueError):
            RecognitionEstimate(selected_target_count=-1)
        with self.assertRaises(ValueError):
            RecognitionEstimate(deferred_target_count=-1)

    def test_estimate_unavailable_is_default_without_zero_cost(self):
        estimate = RecognitionEstimate()
        self.assertEqual(EstimateStatus.ESTIMATE_UNAVAILABLE, estimate.status)
        self.assertIsNone(estimate.estimated_cost)
        self.assertIsNone(estimate.estimated_latency_ms)


class SemanticGapDecisionTests(unittest.TestCase):
    def test_decision_carries_assessments_candidates_and_targets(self):
        assessment = RequirementAssessment(
            requirement_id="req:1",
            status="missing",
            reason_codes=(ReasonCode.EVIDENCE_MISSING,),
        )
        candidate = CacheCandidate(
            requirement_id="req:1",
            cache_key="semantic:abc",
            disposition="miss",
        )
        target = RecognitionTarget(
            target_id="target:1",
            target_type="page",
            task_type="page_summary",
            covered_requirement_ids=("req:1",),
        )
        estimate = RecognitionEstimate(status="estimated", selected_target_count=1)
        decision = SemanticGapDecision(
            request_id="req:1",
            subrequest_id="sub:1",
            decision=SemanticGapDecisionType.RECOGNIZE_REQUIRED,
            requirement_assessments=(assessment,),
            missing_requirements=("req:1",),
            cache_candidates=(candidate,),
            selected_targets=(target,),
            deferred_targets=(),
            estimate=estimate,
            reason_codes=(ReasonCode.EVIDENCE_MISSING,),
            write_back_recommendation=False,
            warnings=("scope 提示缺失",),
        )
        self.assertEqual("req:1", decision.request_id)
        self.assertEqual(SemanticGapDecisionType.RECOGNIZE_REQUIRED, decision.decision)
        self.assertEqual(("req:1",), tuple(item.requirement_id for item in decision.requirement_assessments))
        self.assertEqual(("target:1",), tuple(item.target_id for item in decision.selected_targets))
        self.assertFalse(decision.write_back_recommendation)
        self.assertEqual(CONTRACT_VERSION, decision.contract_version)

    def test_write_back_recommendation_defaults_to_false(self):
        decision = SemanticGapDecision(request_id="req:1")
        self.assertFalse(decision.write_back_recommendation)
        self.assertEqual(SemanticGapDecisionType.UNSUPPORTED, decision.decision)

    def test_empty_request_id_is_rejected(self):
        with self.assertRaises(ValueError):
            SemanticGapDecision(request_id="")

    def test_invalid_decision_and_targets_are_rejected(self):
        with self.assertRaises(ValueError):
            SemanticGapDecision(request_id="req:1", decision="maybe")
        bad_target = RecognitionTarget(
            target_id="target:bad",
            target_type="page",
            task_type="t",
            covered_requirement_ids=("req:1",),
        )
        with self.assertRaises(ValueError):
            SemanticGapDecision(request_id="req:1", selected_targets=("not-a-target",))


class EvidenceItemDecisionMetadataTests(unittest.TestCase):
    DECISION_METADATA_KEYS = {
        "image_hash",
        "cache_key",
        "task_type",
        "model_profile",
        "model_version",
        "prompt_version",
        "contract_version",
        "preprocessing_version",
        "normalization_rule_version",
    }

    def test_evidence_item_carries_decision_metadata_mapping(self):
        item = EvidenceItem(
            evidence_id="evidence:1",
            fact_kind=FactKind.SEMANTIC_OBSERVATION,
            value={"raw_text": "标题"},
            evidence_metadata={
                "image_hash": "hash:1",
                "cache_key": "semantic:abc",
                "task_type": "element_text_or_meaning",
                "model_profile": "qwen-vl",
                "model_version": "1.0",
                "prompt_version": "prompt:v1",
                "contract_version": "contract:v1",
                "preprocessing_version": "pre:v1",
                "normalization_rule_version": "norm:v1",
            },
        )
        self.assertEqual("hash:1", item.evidence_metadata["image_hash"])
        self.assertEqual("semantic:abc", item.evidence_metadata["cache_key"])
        self.assertTrue(self.DECISION_METADATA_KEYS.issubset(item.evidence_metadata))

    def test_metadata_defaults_to_empty_frozen_mapping(self):
        first = EvidenceItem(evidence_id="evidence:2", fact_kind=FactKind.SOURCE_FACT)
        second = EvidenceItem(evidence_id="evidence:3", fact_kind=FactKind.SOURCE_FACT)
        self.assertEqual({}, dict(first.evidence_metadata))
        with self.assertRaises(TypeError):
            first.evidence_metadata["image_hash"] = "hash:1"
        self.assertEqual({}, dict(second.evidence_metadata))

    def test_metadata_serializes_without_payload_contamination(self):
        item = EvidenceItem(
            evidence_id="evidence:4",
            fact_kind=FactKind.SEMANTIC_INTERPRETATION,
            value={"summary": "s"},
            evidence_metadata={"contract_version": "contract:v1"},
        )
        serialized = dict(item.evidence_metadata)
        self.assertEqual({"contract_version": "contract:v1"}, serialized)
        self.assertNotIn("raw_payload", serialized)

    def test_non_mapping_metadata_is_rejected(self):
        with self.assertRaises(ValueError):
            EvidenceItem(
                evidence_id="evidence:5",
                fact_kind=FactKind.SOURCE_FACT,
                evidence_metadata=("image_hash", "hash:1"),
            )

    def test_empty_metadata_key_is_rejected(self):
        with self.assertRaises(ValueError):
            EvidenceItem(
                evidence_id="evidence:6",
                fact_kind=FactKind.SOURCE_FACT,
                evidence_metadata={"": "hash:1"},
            )


if __name__ == "__main__":
    unittest.main()
