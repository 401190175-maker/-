"""Tests for freshness and cache disposition evaluation."""

import unittest

from drawing_graph.assistant_evidence_freshness import EvidenceFreshnessEvaluator
from drawing_graph.assistant_models import (
    AssistantScope,
    CacheCandidate,
    CacheDisposition,
    EvidenceItem,
    EvidenceRequirement,
    EvidenceType,
    FactKind,
    FreshnessRequirement,
    ReasonCode,
    RecognitionPolicy,
    RequirementAssessment,
    RequirementAssessmentStatus,
    RetrievalBundle,
)
from drawing_graph.semantic_cache import SemanticCacheKeyInput, build_semantic_cache_key


PAGE_ID = "page:1"
ELEMENT_ID = "element:1"
DEFAULT_BBOX = {"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4}


def observation_requirement(
    requirement_id: str = "req:obs",
    *,
    freshness: FreshnessRequirement | None = None,
) -> EvidenceRequirement:
    return EvidenceRequirement(
        requirement_id=requirement_id,
        evidence_type=EvidenceType.TEXT_OBSERVATIONS,
        target_scope=AssistantScope(page_id=PAGE_ID, element_id=ELEMENT_ID),
        minimum_status="confirmed",
        allow_model_generation=True,
        freshness_requirement=freshness or FreshnessRequirement(
            require_current_image=True,
            require_current_bbox=True,
            require_current_prompt=True,
            require_current_contract=True,
        ),
    )


def observation_evidence(
    evidence_id: str,
    *,
    image_hash: str = "hash:current",
    bbox: dict | None = DEFAULT_BBOX,
    model_profile: str = "qwen-vl",
    model_version: str = "1.0",
    prompt_version: str = "prompt:v1",
    contract_version: str = "contract:v1",
    task_type: str | None = "element_text_or_meaning",
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        fact_kind=FactKind.SEMANTIC_OBSERVATION,
        scope=AssistantScope(page_id=PAGE_ID, element_id=ELEMENT_ID),
        status="confirmed",
        value={},
        evidence_metadata={
            "image_hash": image_hash,
            "bbox": bbox,
            "task_type": task_type,
            "model_profile": model_profile,
            "model_version": model_version,
            "prompt_version": prompt_version,
            "contract_version": contract_version,
            "preprocessing_version": "pre:v1",
            "normalization_rule_version": "norm:v1",
        },
    )


def page_source_facts(
    image_hash: str = "hash:current",
    bbox: dict | None = DEFAULT_BBOX,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id="evidence:source:1",
        fact_kind=FactKind.SOURCE_FACT,
        scope=AssistantScope(page_id=PAGE_ID, element_id=ELEMENT_ID),
        value={},
        evidence_metadata={
            "page_id": PAGE_ID,
            "element_id": ELEMENT_ID,
            "image_hash": image_hash,
            "bbox": bbox,
        },
    )


def make_assessment(
    requirement_id: str,
    matched: tuple[str, ...],
    *,
    status: RequirementAssessmentStatus = RequirementAssessmentStatus.SATISFIED,
    rejected: tuple[str, ...] = (),
) -> RequirementAssessment:
    return RequirementAssessment(
        requirement_id=requirement_id,
        status=status,
        matched_evidence_ids=matched,
        rejected_evidence_ids=rejected,
        reason_codes=(ReasonCode.EVIDENCE_COMPLETE,),
        allow_model_generation=True,
    )


def make_policy(**overrides) -> RecognitionPolicy:
    values = {
        "model_profile": "qwen-vl",
        "model_version": "1.0",
        "prompt_version": "prompt:v1",
        "preprocessing_version": "pre:v1",
        "normalization_rule_version": "norm:v1",
        "contract_version": "contract:v1",
    }
    values.update(overrides)
    return RecognitionPolicy(**values)


class EvidenceFreshnessDimensionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluator = EvidenceFreshnessEvaluator()
        self.requirement = observation_requirement()
        self.policy = make_policy()

    def evaluate(self, bundle: RetrievalBundle, requirement: EvidenceRequirement | None = None):
        req = requirement or self.requirement
        assessments = (
            RequirementAssessment(
                requirement_id=req.requirement_id,
                status=RequirementAssessmentStatus.SATISFIED,
                matched_evidence_ids=("evidence:obs:1",),
                reason_codes=(ReasonCode.EVIDENCE_COMPLETE,),
                allow_model_generation=True,
            ),
        )
        return self.evaluator.evaluate(
            assessments,
            bundle,
            self.policy,
            requirements={req.requirement_id: req},
        )[0]

    def test_current_evidence_is_fresh(self):
        bundle = RetrievalBundle(
            request_id="req:1",
            semantic_observations=(observation_evidence("evidence:obs:1"),),
            source_facts=(page_source_facts(),),
        )
        assessment = self.evaluate(bundle)
        self.assertTrue(assessment.freshness_result.is_current)
        self.assertEqual((), assessment.freshness_result.missing_metadata)
        self.assertTrue(assessment.freshness_result.dimensions["image_hash"])
        self.assertTrue(assessment.freshness_result.dimensions["bbox"])

    def test_image_hash_change_is_detected(self):
        bundle = RetrievalBundle(
            request_id="req:1",
            semantic_observations=(
                observation_evidence("evidence:obs:1", image_hash="hash:old"),
            ),
            source_facts=(page_source_facts(image_hash="hash:new"),),
        )
        assessment = self.evaluate(bundle)
        self.assertFalse(assessment.freshness_result.is_current)
        self.assertFalse(assessment.freshness_result.dimensions["image_hash"])
        self.assertIn(ReasonCode.IMAGE_CHANGED, assessment.freshness_result.reason_codes)

    def test_bbox_change_is_detected(self):
        bundle = RetrievalBundle(
            request_id="req:1",
            semantic_observations=(
                observation_evidence(
                    "evidence:obs:1",
                    bbox={"x_min": 5, "y_min": 6, "x_max": 7, "y_max": 8},
                ),
            ),
            source_facts=(page_source_facts(),),
        )
        assessment = self.evaluate(bundle)
        self.assertFalse(assessment.freshness_result.is_current)
        self.assertFalse(assessment.freshness_result.dimensions["bbox"])
        self.assertIn(ReasonCode.BBOX_CHANGED, assessment.freshness_result.reason_codes)

    def test_prompt_version_change_is_detected(self):
        bundle = RetrievalBundle(
            request_id="req:1",
            semantic_observations=(
                observation_evidence(
                    "evidence:obs:1",
                    prompt_version="prompt:v0",
                ),
            ),
            source_facts=(page_source_facts(),),
        )
        assessment = self.evaluate(bundle)
        self.assertFalse(assessment.freshness_result.dimensions["prompt"])
        self.assertIn(ReasonCode.PROMPT_VERSION_CHANGED, assessment.freshness_result.reason_codes)

    def test_contract_version_change_is_detected(self):
        bundle = RetrievalBundle(
            request_id="req:1",
            semantic_observations=(
                observation_evidence(
                    "evidence:obs:1",
                    contract_version="contract:v0",
                ),
            ),
            source_facts=(page_source_facts(),),
        )
        assessment = self.evaluate(bundle)
        self.assertFalse(assessment.freshness_result.dimensions["contract"])
        self.assertIn(ReasonCode.CONTRACT_VERSION_CHANGED, assessment.freshness_result.reason_codes)

    def test_combined_freshness_requirement_checks_multiple_dimensions(self):
        requirement = observation_requirement(
            freshness=FreshnessRequirement(
                require_current_image=True,
                require_current_bbox=True,
                require_current_prompt=True,
            )
        )
        bundle = RetrievalBundle(
            request_id="req:1",
            semantic_observations=(
                observation_evidence(
                    "evidence:obs:1",
                    image_hash="hash:old",
                    prompt_version="prompt:v0",
                ),
            ),
            source_facts=(page_source_facts(image_hash="hash:new"),),
        )
        assessment = self.evaluate(bundle, requirement)
        self.assertFalse(assessment.freshness_result.dimensions["image_hash"])
        self.assertFalse(assessment.freshness_result.dimensions["prompt"])
        self.assertIn(ReasonCode.IMAGE_CHANGED, assessment.freshness_result.reason_codes)
        self.assertIn(ReasonCode.PROMPT_VERSION_CHANGED, assessment.freshness_result.reason_codes)

    def test_missing_metadata_is_unknown_not_valid(self):
        evidence = observation_evidence("evidence:obs:1")
        metadata = dict(evidence.evidence_metadata)
        del metadata["image_hash"]
        evidence = EvidenceItem(
            evidence_id=evidence.evidence_id,
            fact_kind=evidence.fact_kind,
            scope=evidence.scope,
            status=evidence.status,
            value={},
            evidence_metadata=metadata,
        )
        bundle = RetrievalBundle(
            request_id="req:1",
            semantic_observations=(evidence,),
            source_facts=(page_source_facts(),),
        )
        assessment = self.evaluate(bundle)
        self.assertFalse(assessment.freshness_result.is_current)
        self.assertIn("image_hash", assessment.freshness_result.missing_metadata)


class EvidenceFreshnessCacheKeyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluator = EvidenceFreshnessEvaluator()
        self.requirement = observation_requirement()
        self.policy = make_policy()

    def candidates(self, bundle: RetrievalBundle, policy: RecognitionPolicy | None = None):
        assessments = (
            RequirementAssessment(
                requirement_id=self.requirement.requirement_id,
                status=RequirementAssessmentStatus.SATISFIED,
                matched_evidence_ids=("evidence:obs:1",),
                reason_codes=(ReasonCode.EVIDENCE_COMPLETE,),
                allow_model_generation=True,
            ),
        )
        return self.evaluator.cache_candidates(
            assessments,
            bundle,
            policy or self.policy,
            requirements={self.requirement.requirement_id: self.requirement},
        )

    def test_cache_key_matches_build_semantic_cache_key(self):
        bundle = RetrievalBundle(
            request_id="req:1",
            semantic_observations=(observation_evidence("evidence:obs:1"),),
            source_facts=(page_source_facts(),),
        )
        candidates = self.candidates(bundle)
        expected_key = build_semantic_cache_key(
            SemanticCacheKeyInput(
                image_hash="hash:current",
                bbox=(1, 2, 3, 4),
                target_element_id=ELEMENT_ID,
                task_type="element_text_or_meaning",
                model_profile="qwen-vl",
                model_version="1.0",
                prompt_version="prompt:v1",
                preprocessing_version="pre:v1",
                normalization_rule_version="norm:v1",
                contract_version="contract:v1",
            )
        )
        self.assertEqual(expected_key, candidates[0].cache_key)
        self.assertIsInstance(candidates[0], CacheCandidate)
        self.assertEqual(self.requirement.requirement_id, candidates[0].requirement_id)

    def test_missing_current_image_hash_makes_key_unavailable(self):
        bundle = RetrievalBundle(
            request_id="req:1",
            semantic_observations=(observation_evidence("evidence:obs:1"),),
            source_facts=(page_source_facts(image_hash=None),),
        )
        candidates = self.candidates(bundle)
        self.assertIsNone(candidates[0].cache_key)
        self.assertEqual(CacheDisposition.UNKNOWN, candidates[0].disposition)
        self.assertIn(ReasonCode.CACHE_KEY_UNAVAILABLE, candidates[0].reason_codes)

    def test_missing_current_bbox_makes_key_unavailable(self):
        bundle = RetrievalBundle(
            request_id="req:1",
            semantic_observations=(observation_evidence("evidence:obs:1"),),
            source_facts=(page_source_facts(bbox=None),),
        )
        candidates = self.candidates(bundle)
        self.assertIsNone(candidates[0].cache_key)
        self.assertEqual(CacheDisposition.UNKNOWN, candidates[0].disposition)

    def test_missing_task_type_makes_key_unavailable(self):
        evidence = observation_evidence("evidence:obs:1", task_type=None)
        bundle = RetrievalBundle(
            request_id="req:1",
            semantic_observations=(evidence,),
            source_facts=(page_source_facts(),),
        )
        candidates = self.candidates(bundle)
        self.assertIsNone(candidates[0].cache_key)
        self.assertEqual(CacheDisposition.UNKNOWN, candidates[0].disposition)

    def test_missing_prompt_version_makes_key_unavailable(self):
        bundle = RetrievalBundle(
            request_id="req:1",
            semantic_observations=(observation_evidence("evidence:obs:1"),),
            source_facts=(page_source_facts(),),
        )
        policy = make_policy(prompt_version=None)
        candidates = self.candidates(bundle, policy)
        self.assertIsNone(candidates[0].cache_key)
        self.assertEqual(CacheDisposition.UNKNOWN, candidates[0].disposition)

    def test_bypass_mode_is_respected(self):
        bundle = RetrievalBundle(
            request_id="req:1",
            semantic_observations=(observation_evidence("evidence:obs:1"),),
            source_facts=(page_source_facts(),),
        )
        policy = make_policy(cache_mode="bypass")
        candidates = self.candidates(bundle, policy)
        self.assertEqual(CacheDisposition.BYPASSED, candidates[0].disposition)


class EvidenceCacheDispositionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluator = EvidenceFreshnessEvaluator()
        self.requirement = observation_requirement()
        self.policy = make_policy()

    def candidates(
        self,
        observations: tuple[EvidenceItem, ...],
        source_facts: tuple[EvidenceItem, ...] = (page_source_facts(),),
        matched: tuple[str, ...] | None = None,
    ):
        matched_ids = matched or tuple(item.evidence_id for item in observations)
        bundle = RetrievalBundle(
            request_id="req:1",
            semantic_observations=observations,
            source_facts=source_facts,
        )
        assessments = (
            RequirementAssessment(
                requirement_id=self.requirement.requirement_id,
                status=RequirementAssessmentStatus.SATISFIED,
                matched_evidence_ids=matched_ids,
                reason_codes=(ReasonCode.EVIDENCE_COMPLETE,),
                allow_model_generation=True,
            ),
        )
        return self.evaluator.cache_candidates(
            assessments,
            bundle,
            self.policy,
            requirements={self.requirement.requirement_id: self.requirement},
        )

    def test_full_hit_when_all_required_evidence_is_fresh(self):
        candidates = self.candidates(
            (observation_evidence("evidence:obs:1"),),
            (page_source_facts(),),
        )
        self.assertEqual(CacheDisposition.FULL_HIT, candidates[0].disposition)
        self.assertEqual(("evidence:obs:1",), candidates[0].reusable_evidence_ids)

    def test_partial_hit_keeps_remaining_gap(self):
        fresh = observation_evidence("evidence:obs:1", image_hash="hash:new")
        stale = observation_evidence("evidence:obs:2", image_hash="hash:old")
        candidates = self.candidates(
            (fresh, stale),
            (page_source_facts(image_hash="hash:new"),),
        )
        self.assertEqual(CacheDisposition.PARTIAL_HIT, candidates[0].disposition)
        self.assertEqual(("evidence:obs:1",), candidates[0].reusable_evidence_ids)
        self.assertIn(ReasonCode.IMAGE_CHANGED, candidates[0].reason_codes)

    def test_miss_when_no_compatible_evidence(self):
        candidates = self.candidates((), matched=())
        self.assertEqual(CacheDisposition.MISS, candidates[0].disposition)
        self.assertEqual((), candidates[0].reusable_evidence_ids)

    def test_cache_candidate_is_traceable_to_requirement_and_evidence(self):
        candidates = self.candidates(
            (observation_evidence("evidence:obs:1"),),
            (page_source_facts(),),
        )
        self.assertEqual(self.requirement.requirement_id, candidates[0].requirement_id)
        self.assertEqual(("evidence:obs:1",), candidates[0].reusable_evidence_ids)
        self.assertIsNotNone(candidates[0].cache_key)


class EvidenceCacheProtectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluator = EvidenceFreshnessEvaluator()
        self.requirement = observation_requirement()
        self.policy = make_policy()

    def outcome(self, bundle: RetrievalBundle, assessment: RequirementAssessment):
        updated = self.evaluator.evaluate(
            (assessment,),
            bundle,
            self.policy,
            requirements={self.requirement.requirement_id: self.requirement},
        )[0]
        candidate = self.evaluator.cache_candidates(
            (assessment,),
            bundle,
            self.policy,
            requirements={self.requirement.requirement_id: self.requirement},
        )[0]
        return updated, candidate

    def test_stale_evidence_produces_stale_disposition_and_reason(self):
        bundle = RetrievalBundle(
            request_id="req:1",
            semantic_observations=(
                observation_evidence("evidence:obs:1", image_hash="hash:old"),
            ),
            source_facts=(page_source_facts(image_hash="hash:new"),),
        )
        assessment = make_assessment(
            self.requirement.requirement_id,
            matched=("evidence:obs:1",),
        )
        updated, candidate = self.outcome(bundle, assessment)
        self.assertEqual(CacheDisposition.STALE, candidate.disposition)
        self.assertEqual(RequirementAssessmentStatus.STALE, updated.status)
        self.assertIn(ReasonCode.EVIDENCE_STALE, updated.reason_codes)
        self.assertIn(ReasonCode.IMAGE_CHANGED, updated.freshness_result.reason_codes)

    def test_rejected_evidence_never_produces_full_hit(self):
        bundle = RetrievalBundle(request_id="req:1")
        assessment = RequirementAssessment(
            requirement_id=self.requirement.requirement_id,
            status=RequirementAssessmentStatus.MISSING,
            matched_evidence_ids=(),
            rejected_evidence_ids=("evidence:rejected:1",),
            reason_codes=(ReasonCode.STATUS_INSUFFICIENT,),
            allow_model_generation=True,
        )
        updated, candidate = self.outcome(bundle, assessment)
        self.assertEqual(CacheDisposition.MISS, candidate.disposition)
        self.assertNotEqual(CacheDisposition.FULL_HIT, candidate.disposition)
        self.assertEqual((), candidate.reusable_evidence_ids)
        self.assertEqual(RequirementAssessmentStatus.MISSING, updated.status)

    def test_recognition_failed_evidence_never_produces_full_hit(self):
        bundle = RetrievalBundle(request_id="req:1")
        assessment = RequirementAssessment(
            requirement_id=self.requirement.requirement_id,
            status=RequirementAssessmentStatus.MISSING,
            matched_evidence_ids=(),
            rejected_evidence_ids=("evidence:failed:1",),
            reason_codes=(ReasonCode.STATUS_INSUFFICIENT,),
            allow_model_generation=True,
        )
        _, candidate = self.outcome(bundle, assessment)
        self.assertNotEqual(CacheDisposition.FULL_HIT, candidate.disposition)
        self.assertEqual((), candidate.reusable_evidence_ids)

    def test_conflicting_evidence_never_produces_full_hit(self):
        bundle = RetrievalBundle(request_id="req:1")
        assessment = RequirementAssessment(
            requirement_id=self.requirement.requirement_id,
            status=RequirementAssessmentStatus.CONFLICTING,
            matched_evidence_ids=(),
            rejected_evidence_ids=("evidence:a:1", "evidence:b:1"),
            reason_codes=(ReasonCode.EVIDENCE_CONFLICT,),
            allow_model_generation=True,
        )
        _, candidate = self.outcome(bundle, assessment)
        self.assertNotEqual(CacheDisposition.FULL_HIT, candidate.disposition)
        self.assertEqual((), candidate.reusable_evidence_ids)

    def test_unknown_metadata_is_not_downgraded_to_hit(self):
        evidence = observation_evidence("evidence:obs:1")
        metadata = dict(evidence.evidence_metadata)
        del metadata["contract_version"]
        evidence = EvidenceItem(
            evidence_id=evidence.evidence_id,
            fact_kind=evidence.fact_kind,
            scope=evidence.scope,
            status=evidence.status,
            value={},
            evidence_metadata=metadata,
        )
        bundle = RetrievalBundle(
            request_id="req:1",
            semantic_observations=(evidence,),
            source_facts=(page_source_facts(),),
        )
        assessment = make_assessment(
            self.requirement.requirement_id,
            matched=("evidence:obs:1",),
        )
        updated, candidate = self.outcome(bundle, assessment)
        self.assertEqual(CacheDisposition.UNKNOWN, candidate.disposition)
        self.assertNotEqual(CacheDisposition.FULL_HIT, candidate.disposition)
        self.assertEqual((), candidate.reusable_evidence_ids)
        self.assertEqual(RequirementAssessmentStatus.SATISFIED, updated.status)
        self.assertIn("contract_version", updated.missing_metadata)

    def test_full_hit_keeps_assessment_status_consistent(self):
        bundle = RetrievalBundle(
            request_id="req:1",
            semantic_observations=(observation_evidence("evidence:obs:1"),),
            source_facts=(page_source_facts(),),
        )
        assessment = make_assessment(
            self.requirement.requirement_id,
            matched=("evidence:obs:1",),
        )
        updated, candidate = self.outcome(bundle, assessment)
        self.assertEqual(CacheDisposition.FULL_HIT, candidate.disposition)
        self.assertEqual(RequirementAssessmentStatus.SATISFIED, updated.status)
        self.assertEqual(CacheDisposition.FULL_HIT, updated.cache_disposition)


class EvidenceFreshnessNarrowHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluator = EvidenceFreshnessEvaluator()
        self.requirement = observation_requirement()
        self.policy = make_policy()

    def bundle(self, observations, source_facts=(page_source_facts(),)):
        return RetrievalBundle(
            request_id="req:1",
            semantic_observations=observations,
            source_facts=source_facts,
        )

    def test_helper_reuses_existing_freshness_rules(self):
        bundle = self.bundle((observation_evidence("evidence:obs:1"),))
        results = self.evaluator.evaluate_evidence(
            (observation_evidence("evidence:obs:1"),),
            self.policy,
            bundle,
            self.requirement,
        )
        self.assertEqual(1, len(results))
        self.assertTrue(results[0].is_current)
        self.assertTrue(results[0].dimensions["image_hash"])
        self.assertTrue(results[0].dimensions["bbox"])

    def test_helper_detects_image_change(self):
        bundle = self.bundle((observation_evidence("evidence:obs:1", image_hash="hash:old"),))
        results = self.evaluator.evaluate_evidence(
            (observation_evidence("evidence:obs:1", image_hash="hash:old"),),
            self.policy,
            bundle,
            self.requirement,
        )
        self.assertFalse(results[0].is_current)
        self.assertIn(ReasonCode.IMAGE_CHANGED, results[0].reason_codes)

    def test_missing_metadata_is_not_current(self):
        evidence = observation_evidence("evidence:obs:1")
        metadata = dict(evidence.evidence_metadata)
        del metadata["image_hash"]
        evidence = EvidenceItem(
            evidence_id=evidence.evidence_id,
            fact_kind=evidence.fact_kind,
            scope=evidence.scope,
            status=evidence.status,
            value={},
            evidence_metadata=metadata,
        )
        bundle = self.bundle((evidence,))
        results = self.evaluator.evaluate_evidence(
            (evidence,),
            self.policy,
            bundle,
            self.requirement,
        )
        self.assertFalse(results[0].is_current)
        self.assertIn("image_hash", results[0].missing_metadata)

    def test_helper_is_read_only_and_returns_tuple(self):
        bundle = self.bundle(())
        results = self.evaluator.evaluate_evidence((), self.policy, bundle, self.requirement)
        self.assertEqual((), results)


if __name__ == "__main__":
    unittest.main()
