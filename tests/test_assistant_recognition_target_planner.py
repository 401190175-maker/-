"""Tests for recognition target planning."""

import inspect
from pathlib import Path
import unittest

from drawing_graph.assistant_models import (
    AssistantScope,
    CacheDisposition,
    EvidenceItem,
    EvidenceRequirement,
    EvidenceType,
    FactKind,
    ReasonCode,
    RecognitionPolicy,
    RecognitionTarget,
    RecognitionTargetStatus,
    RequirementAssessment,
    RequirementAssessmentStatus,
    RetrievalBundle,
)
from drawing_graph.assistant_recognition_target_planner import RecognitionTargetPlanner


PAGE_ID = "page:1"
ELEMENT_ID = "element:1"
BLOCK_ID = "block:1"
ELEMENT_BBOX = {"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4}
NORMALIZED_BBOX = {"x_min": 0.1, "y_min": 0.2, "x_max": 0.3, "y_max": 0.4}
BLOCK_BBOX = {"x_min": 10, "y_min": 20, "x_max": 30, "y_max": 40}


def element_source_fact(
    element_id: str = ELEMENT_ID,
    *,
    image_path: str = "data/road_24.png",
    image_hash: str = "hash:1",
    bbox: dict | None = ELEMENT_BBOX,
    normalized_bbox: dict | None = NORMALIZED_BBOX,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=f"evidence:source:{element_id}",
        fact_kind=FactKind.SOURCE_FACT,
        scope=AssistantScope(page_id=PAGE_ID, element_id=element_id),
        value={},
        evidence_metadata={
            "page_id": PAGE_ID,
            "element_id": element_id,
            "element_type": "DrawingBlock",
            "image_path": image_path,
            "image_hash": image_hash,
            "bbox": bbox,
            "normalized_bbox": normalized_bbox,
        },
    )


def block_trace_fact(
    block_id: str = BLOCK_ID,
    *,
    image_path: str = "data/road_24.png",
    bbox: dict | None = BLOCK_BBOX,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=f"evidence:trace:{block_id}",
        fact_kind=FactKind.SOURCE_FACT,
        scope=AssistantScope(page_id=PAGE_ID, block_id=block_id),
        value={},
        evidence_metadata={
            "page_id": PAGE_ID,
            "block_id": block_id,
            "image_path": image_path,
            "bbox": bbox,
        },
    )


def page_source_fact(
    *,
    image_path: str = "data/road_24.png",
    image_hash: str = "hash:1",
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id="evidence:source:page",
        fact_kind=FactKind.SOURCE_FACT,
        scope=AssistantScope(page_id=PAGE_ID),
        value={},
        evidence_metadata={
            "page_id": PAGE_ID,
            "image_path": image_path,
            "image_hash": image_hash,
        },
    )


def make_requirement(
    requirement_id: str,
    *,
    evidence_type: EvidenceType = EvidenceType.TEXT_OBSERVATIONS,
    scope: AssistantScope | None = None,
    allow_model_generation: bool = True,
    required: bool = True,
) -> EvidenceRequirement:
    return EvidenceRequirement(
        requirement_id=requirement_id,
        evidence_type=evidence_type,
        target_scope=scope or AssistantScope(page_id=PAGE_ID, element_id=ELEMENT_ID),
        allow_model_generation=allow_model_generation,
        required=required,
    )


def make_assessment(
    requirement_id: str,
    *,
    status: RequirementAssessmentStatus = RequirementAssessmentStatus.MISSING,
    allow_model_generation: bool = True,
) -> RequirementAssessment:
    return RequirementAssessment(
        requirement_id=requirement_id,
        status=status,
        reason_codes=(ReasonCode.EVIDENCE_MISSING,),
        allow_model_generation=allow_model_generation,
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


class RecognitionTargetLocationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.planner = RecognitionTargetPlanner()
        self.policy = make_policy()

    def plan(
        self,
        assessments: tuple[RequirementAssessment, ...],
        bundle: RetrievalBundle,
        requirements: dict,
    ):
        return self.planner.plan(
            assessments,
            bundle,
            self.policy,
            requirements=requirements,
        )

    def test_element_location_is_found_from_page_source_facts(self):
        requirement = make_requirement("req:element")
        assessment = make_assessment("req:element")
        bundle = RetrievalBundle(
            request_id="req:1",
            source_facts=(element_source_fact(),),
        )
        targets = self.plan(
            (assessment,),
            bundle,
            {requirement.requirement_id: requirement},
        )
        self.assertEqual(1, len(targets))
        target = targets[0]
        self.assertEqual(RecognitionTargetStatus.SELECTED, target.status)
        self.assertEqual(PAGE_ID, target.page_id)
        self.assertEqual(ELEMENT_ID, target.target_element_id)
        self.assertEqual(ELEMENT_BBOX, dict(target.bbox))
        self.assertIsNotNone(target.cache_key)

    def test_block_location_is_found_from_block_trace_and_page_facts(self):
        requirement = make_requirement(
            "req:block",
            scope=AssistantScope(page_id=PAGE_ID, block_id=BLOCK_ID),
            evidence_type=EvidenceType.STRUCTURED_INTERPRETATIONS,
        )
        assessment = make_assessment("req:block")
        bundle = RetrievalBundle(
            request_id="req:1",
            source_facts=(block_trace_fact(), page_source_fact()),
        )
        targets = self.plan(
            (assessment,),
            bundle,
            {requirement.requirement_id: requirement},
        )
        self.assertEqual(1, len(targets))
        target = targets[0]
        self.assertEqual(RecognitionTargetStatus.SELECTED, target.status)
        self.assertEqual(BLOCK_ID, target.target_element_id)
        self.assertEqual(BLOCK_BBOX, dict(target.bbox))
        self.assertEqual("block_semantic_identification", target.task_type)

    def test_block_dry_run_target_allows_page_hash_to_be_computed_later(self):
        requirement = make_requirement(
            "req:block:nohash",
            scope=AssistantScope(page_id=PAGE_ID, block_id=BLOCK_ID),
            evidence_type=EvidenceType.STRUCTURED_INTERPRETATIONS,
        )
        assessment = make_assessment("req:block:nohash")
        bundle = RetrievalBundle(
            request_id="req:1",
            source_facts=(block_trace_fact(), page_source_fact(image_hash=None)),
        )
        targets = self.plan(
            (assessment,),
            bundle,
            {requirement.requirement_id: requirement},
        )
        self.assertEqual(1, len(targets))
        target = targets[0]
        self.assertEqual(RecognitionTargetStatus.SELECTED, target.status)
        self.assertEqual(BLOCK_ID, target.target_element_id)
        self.assertIsNone(target.cache_key)

    def test_missing_location_never_produces_selected_target(self):
        requirement = make_requirement("req:nolocation")
        assessment = make_assessment("req:nolocation")
        bundle = RetrievalBundle(request_id="req:1")
        targets = self.plan(
            (assessment,),
            bundle,
            {requirement.requirement_id: requirement},
        )
        self.assertEqual(1, len(targets))
        self.assertEqual(RecognitionTargetStatus.BLOCKED, targets[0].status)
        self.assertIn(ReasonCode.TARGET_LOCATION_MISSING, targets[0].reason_codes)

    def test_planner_does_not_import_facade_or_read_files(self):
        module_path = Path(inspect.getfile(RecognitionTargetPlanner))
        source = module_path.read_text(encoding="utf-8")
        self.assertNotIn("tool_facade", source)
        self.assertNotIn("open(", source)
        self.assertNotIn("Path(", source)


class RecognitionTargetGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.planner = RecognitionTargetPlanner()
        self.policy = make_policy()

    def plan(
        self,
        assessments: tuple[RequirementAssessment, ...],
        bundle: RetrievalBundle,
        requirements: dict,
    ):
        return self.planner.plan(
            assessments,
            bundle,
            self.policy,
            requirements=requirements,
        )

    def test_element_gap_generates_element_level_target(self):
        requirement = make_requirement("req:element")
        assessment = make_assessment("req:element")
        bundle = RetrievalBundle(
            request_id="req:1",
            source_facts=(element_source_fact(),),
        )
        targets = self.plan(
            (assessment,),
            bundle,
            {requirement.requirement_id: requirement},
        )
        self.assertEqual(1, len(targets))
        target = targets[0]
        self.assertEqual("DrawingBlock", target.target_type)
        self.assertEqual(ELEMENT_ID, target.target_element_id)
        self.assertEqual(ELEMENT_BBOX, dict(target.bbox))
        self.assertEqual(NORMALIZED_BBOX, dict(target.normalized_bbox))

    def test_page_scoped_requirement_generates_page_level_target(self):
        requirement = make_requirement(
            "req:page",
            scope=AssistantScope(page_id=PAGE_ID),
        )
        assessment = make_assessment("req:page")
        bundle = RetrievalBundle(
            request_id="req:1",
            source_facts=(page_source_fact(),),
        )
        targets = self.plan(
            (assessment,),
            bundle,
            {requirement.requirement_id: requirement},
        )
        self.assertEqual(1, len(targets))
        target = targets[0]
        self.assertEqual("page", target.target_type)
        self.assertEqual(PAGE_ID, target.page_id)
        self.assertIsNone(target.target_element_id)
        self.assertIsNone(target.bbox)

    def test_satisfied_full_hit_requirement_generates_no_target(self):
        requirement = make_requirement("req:done")
        assessment = RequirementAssessment(
            requirement_id="req:done",
            status=RequirementAssessmentStatus.SATISFIED,
            reason_codes=(ReasonCode.EVIDENCE_COMPLETE,),
            cache_disposition=CacheDisposition.FULL_HIT,
            allow_model_generation=True,
        )
        bundle = RetrievalBundle(
            request_id="req:1",
            source_facts=(element_source_fact(),),
        )
        targets = self.plan(
            (assessment,),
            bundle,
            {requirement.requirement_id: requirement},
        )
        self.assertEqual((), targets)

    def test_formal_review_and_forbidden_requirements_generate_no_target(self):
        requirement = make_requirement("req:formal")
        bundle = RetrievalBundle(
            request_id="req:1",
            source_facts=(element_source_fact(),),
        )
        formal = RequirementAssessment(
            requirement_id="req:formal",
            status=RequirementAssessmentStatus.FORMAL_REVIEW_REQUIRED,
            reason_codes=(ReasonCode.FORMAL_REVIEW_REQUIRED,),
            allow_model_generation=False,
        )
        forbidden = RequirementAssessment(
            requirement_id="req:forbidden",
            status=RequirementAssessmentStatus.FORBIDDEN,
            reason_codes=(ReasonCode.RECOGNITION_FORBIDDEN,),
            allow_model_generation=False,
        )
        targets = self.plan(
            (formal, forbidden),
            bundle,
            {requirement.requirement_id: requirement},
        )
        self.assertEqual((), targets)

    def test_stale_gap_generates_target_with_stale_reason(self):
        requirement = make_requirement("req:stale")
        assessment = make_assessment(
            "req:stale",
            status=RequirementAssessmentStatus.STALE,
        )
        bundle = RetrievalBundle(
            request_id="req:1",
            source_facts=(element_source_fact(),),
        )
        targets = self.plan(
            (assessment,),
            bundle,
            {requirement.requirement_id: requirement},
        )
        self.assertEqual(1, len(targets))
        self.assertEqual((ReasonCode.EVIDENCE_STALE,), targets[0].reason_codes)

    def test_target_carries_task_type_outputs_and_coverage(self):
        requirement = make_requirement(
            "req:carry",
            evidence_type=EvidenceType.TEXT_OBSERVATIONS,
        )
        assessment = make_assessment("req:carry")
        bundle = RetrievalBundle(
            request_id="req:1",
            source_facts=(element_source_fact(),),
        )
        target = self.plan(
            (assessment,),
            bundle,
            {requirement.requirement_id: requirement},
        )[0]
        self.assertEqual("element_text_observation", target.task_type)
        self.assertEqual(("observation",), target.required_outputs)
        self.assertEqual(("req:carry",), target.covered_requirement_ids)
        self.assertEqual((ReasonCode.EVIDENCE_MISSING,), target.reason_codes)
        self.assertIsNotNone(target.cache_key)

    def test_target_contains_no_secret_or_raw_payload(self):
        requirement = make_requirement("req:clean")
        assessment = make_assessment("req:clean")
        bundle = RetrievalBundle(
            request_id="req:1",
            source_facts=(element_source_fact(),),
        )
        target = self.plan(
            (assessment,),
            bundle,
            {requirement.requirement_id: requirement},
        )[0]
        serialized = repr(target).lower()
        self.assertNotIn("api_key", serialized)
        self.assertNotIn("password", serialized)
        self.assertNotIn("raw_text", serialized)


class RecognitionTargetMergeOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.planner = RecognitionTargetPlanner()
        self.policy = make_policy()

    def bundle(self) -> RetrievalBundle:
        return RetrievalBundle(
            request_id="req:1",
            source_facts=(element_source_fact(),),
        )

    def test_same_element_and_task_requirements_merge_into_one_target(self):
        first = make_requirement("req:a")
        second = make_requirement("req:b")
        assessments = (
            make_assessment("req:a"),
            make_assessment("req:b"),
        )
        targets = self.planner.plan(
            assessments,
            self.bundle(),
            self.policy,
            requirements={
                first.requirement_id: first,
                second.requirement_id: second,
            },
        )
        self.assertEqual(1, len(targets))
        self.assertEqual(("req:a", "req:b"), targets[0].covered_requirement_ids)

    def test_different_task_types_do_not_merge(self):
        observation = make_requirement(
            "req:obs",
            evidence_type=EvidenceType.TEXT_OBSERVATIONS,
        )
        interpretation = make_requirement(
            "req:interp",
            evidence_type=EvidenceType.STRUCTURED_INTERPRETATIONS,
        )
        assessments = (
            make_assessment("req:obs"),
            make_assessment("req:interp"),
        )
        targets = self.planner.plan(
            assessments,
            self.bundle(),
            self.policy,
            requirements={
                observation.requirement_id: observation,
                interpretation.requirement_id: interpretation,
            },
        )
        self.assertEqual(2, len(targets))
        self.assertEqual(
            {"element_text_observation", "block_semantic_identification"},
            {target.task_type for target in targets},
        )

    def test_optional_requirement_merges_into_required_target(self):
        required = make_requirement("req:required", required=True)
        optional = make_requirement("req:optional", required=False)
        assessments = (
            make_assessment("req:required"),
            make_assessment("req:optional"),
        )
        targets = self.planner.plan(
            assessments,
            self.bundle(),
            self.policy,
            requirements={
                required.requirement_id: required,
                optional.requirement_id: optional,
            },
        )
        self.assertEqual(1, len(targets))
        self.assertEqual(("req:required", "req:optional"), targets[0].covered_requirement_ids)
        self.assertEqual(100, targets[0].priority)

    def test_output_order_is_deterministic(self):
        requirements = {
            f"req:{index}": make_requirement(f"req:{index}")
            for index in range(3)
        }
        assessments = tuple(
            make_assessment(f"req:{index}") for index in range(3)
        )
        first_run = self.planner.plan(
            assessments,
            self.bundle(),
            self.policy,
            requirements=requirements,
        )
        second_run = self.planner.plan(
            assessments,
            self.bundle(),
            self.policy,
            requirements=requirements,
        )
        self.assertEqual(
            tuple(target.target_id for target in first_run),
            tuple(target.target_id for target in second_run),
        )


class RecognitionTargetBlockedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.planner = RecognitionTargetPlanner()
        self.policy = make_policy()

    def plan_with(self, source_facts: tuple[EvidenceItem, ...]):
        requirement = make_requirement("req:blocked")
        assessment = make_assessment("req:blocked")
        bundle = RetrievalBundle(
            request_id="req:1",
            source_facts=source_facts,
        )
        return self.planner.plan(
            (assessment,),
            bundle,
            self.policy,
            requirements={requirement.requirement_id: requirement},
        )

    def assert_blocked_with(self, targets, reason_code: ReasonCode):
        self.assertEqual(1, len(targets))
        target = targets[0]
        self.assertEqual(RecognitionTargetStatus.BLOCKED, target.status)
        self.assertIn(reason_code, target.reason_codes)
        self.assertIn("req:blocked", target.covered_requirement_ids)

    def test_missing_image_path_blocks_target(self):
        targets = self.plan_with(
            (element_source_fact(image_path=None),),
        )
        self.assert_blocked_with(targets, ReasonCode.TARGET_LOCATION_MISSING)
        self.assertEqual((), tuple(t for t in targets if t.status is RecognitionTargetStatus.SELECTED))

    def test_missing_image_hash_selects_target_without_cache_key(self):
        targets = self.plan_with(
            (element_source_fact(image_hash=None),),
        )
        self.assertEqual(1, len(targets))
        self.assertEqual(RecognitionTargetStatus.SELECTED, targets[0].status)
        self.assertIsNone(targets[0].cache_key)

    def test_missing_bbox_blocks_target(self):
        targets = self.plan_with(
            (element_source_fact(bbox=None),),
        )
        self.assert_blocked_with(targets, ReasonCode.TARGET_LOCATION_MISSING)

    def test_missing_page_id_blocks_target(self):
        unscoped = EvidenceItem(
            evidence_id="evidence:source:unscoped",
            fact_kind=FactKind.SOURCE_FACT,
            scope=AssistantScope(element_id=ELEMENT_ID),
            value={},
            evidence_metadata={
                "element_id": ELEMENT_ID,
                "element_type": "DrawingBlock",
                "image_path": "data/road_24.png",
                "image_hash": "hash:1",
                "bbox": ELEMENT_BBOX,
            },
        )
        targets = self.plan_with((unscoped,))
        self.assert_blocked_with(targets, ReasonCode.TARGET_LOCATION_MISSING)

    def test_missing_scope_returns_scope_missing_for_clarification(self):
        requirement = make_requirement(
            "req:noscope",
            scope=AssistantScope(),
        )
        assessment = make_assessment("req:noscope")
        bundle = RetrievalBundle(
            request_id="req:1",
            source_facts=(element_source_fact(),),
        )
        targets = self.planner.plan(
            (assessment,),
            bundle,
            self.policy,
            requirements={requirement.requirement_id: requirement},
        )
        self.assertEqual(1, len(targets))
        self.assertEqual(RecognitionTargetStatus.BLOCKED, targets[0].status)
        self.assertIn(ReasonCode.SCOPE_MISSING, targets[0].reason_codes)

    def test_blocked_requirement_is_not_silently_dropped(self):
        requirement = make_requirement("req:visible")
        assessment = make_assessment("req:visible")
        bundle = RetrievalBundle(request_id="req:1")
        targets = self.planner.plan(
            (assessment,),
            bundle,
            self.policy,
            requirements={requirement.requirement_id: requirement},
        )
        self.assertEqual(1, len(targets))
        self.assertEqual("req:visible", targets[0].covered_requirement_ids[0])
        self.assertIn(ReasonCode.TARGET_LOCATION_MISSING, targets[0].reason_codes)


if __name__ == "__main__":
    unittest.main()
