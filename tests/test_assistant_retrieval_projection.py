"""Tests for the read-only graph retrieval bundle builder."""

import unittest

from drawing_graph.assistant_models import (
    AssistantScope,
    EvidenceItem,
    EvidenceRequirement,
    EvidenceType,
    FactKind,
    MissingEvidence,
    PlanWarning,
    QuestionUnderstandingResult,
    RawRetrievalResult,
    ReasonCode,
    RetrievalBundle,
    RetrievalPlan,
    RetrievalStatus,
    RetrievalStep,
    SourceCallRecord,
)
from drawing_graph.assistant_retrieval_projection import RetrievalBundleBuilder
from drawing_graph.tool_models import (
    BBox,
    BlockRelations,
    BlockTrace,
    CandidateRelationSummary,
    DrawingSetSummary,
    ElementEvidence,
    PageSourceFacts,
    PageSummary,
    SectionMatchSummary,
    SemanticInterpretationSummary,
    SemanticObservationSummary,
)


def make_result(*requirements: EvidenceRequirement) -> QuestionUnderstandingResult:
    return QuestionUnderstandingResult(
        request_id="req:1",
        question_type="page_summary",
        required_evidence=requirements,
    )


def make_step(
    step_id: str,
    method: str,
    requirement_id: str,
    parameters: dict,
    scope: AssistantScope | None = None,
) -> RetrievalStep:
    return RetrievalStep(
        step_id=step_id,
        facade_method=method,
        scope=scope,
        parameters=parameters,
        requirement_ids=(requirement_id,),
        dedupe_key=f"{method}:{step_id}",
    )


def make_call(step_id: str, method: str, result_count: int = 1) -> SourceCallRecord:
    return SourceCallRecord(
        source_call_id=f"call:{step_id}",
        step_id=step_id,
        facade_method=method,
        status=RetrievalStatus.OK,
        result_count=result_count,
    )


def make_requirement(evidence_type: EvidenceType, scope: AssistantScope) -> EvidenceRequirement:
    return EvidenceRequirement(
        requirement_id=f"req:{evidence_type.value}",
        evidence_type=evidence_type,
        target_scope=scope,
    )


class RetrievalBundleBuilderSourceFactTests(unittest.TestCase):
    def test_page_source_facts_map_to_source_fact_per_element(self):
        requirement = make_requirement(
            EvidenceType.PAGE_SOURCE_FACTS,
            AssistantScope(page_id="page:1"),
        )
        plan = RetrievalPlan(
            request_id="req:1",
            steps=(
                make_step(
                    "step:1",
                    "get_page_source_facts",
                    requirement.requirement_id,
                    {"page_id": "page:1", "element_types": None, "include_image_meta": True},
                    AssistantScope(page_id="page:1"),
                ),
            ),
        )
        facts = PageSourceFacts(
            page_id="page:1",
            image_path="data/road_24.png",
            image_size=(100, 200),
            image_hash="hash:1",
            elements=(
                ElementEvidence(
                    element_id="element:1",
                    element_type="Block",
                    bbox=BBox(1, 2, 3, 4),
                    normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
                    source_label="l1",
                ),
                ElementEvidence(
                    element_id="element:2",
                    element_type="Text",
                    bbox=BBox(5, 6, 7, 8),
                    normalized_bbox=BBox(0.5, 0.6, 0.7, 0.8),
                    source_label="l2",
                ),
            ),
        )
        raw = RawRetrievalResult(results={"step:1": facts})
        calls = (make_call("step:1", "get_page_source_facts", 1),)

        bundle = RetrievalBundleBuilder().build(
            make_result(requirement),
            plan,
            raw,
            calls,
        )
        self.assertEqual(2, len(bundle.source_facts))
        first = bundle.source_facts[0]
        self.assertEqual(FactKind.SOURCE_FACT, first.fact_kind)
        self.assertTrue(first.evidence_id)
        self.assertEqual("page:1", first.scope.page_id)
        self.assertEqual("element:1", first.scope.element_id)
        self.assertEqual("call:step:1", first.source_call_id)
        self.assertEqual({"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4}, dict(first.evidence_refs[0].bbox))

    def test_page_source_facts_carry_stable_decision_metadata(self):
        requirement = make_requirement(
            EvidenceType.PAGE_SOURCE_FACTS,
            AssistantScope(page_id="page:1"),
        )
        plan = RetrievalPlan(
            request_id="req:1",
            steps=(
                make_step(
                    "step:1",
                    "get_page_source_facts",
                    requirement.requirement_id,
                    {"page_id": "page:1", "element_types": None, "include_image_meta": True},
                    AssistantScope(page_id="page:1"),
                ),
            ),
        )
        facts = PageSourceFacts(
            page_id="page:1",
            image_path="data/road_24.png",
            image_size=(100, 200),
            image_hash="hash:1",
            elements=(
                ElementEvidence(
                    element_id="element:1",
                    element_type="Block",
                    bbox=BBox(1, 2, 3, 4),
                    normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
                    source_label="l1",
                ),
            ),
        )
        raw = RawRetrievalResult(results={"step:1": facts})
        calls = (make_call("step:1", "get_page_source_facts", 1),)

        bundle = RetrievalBundleBuilder().build(
            make_result(requirement),
            plan,
            raw,
            calls,
        )
        item = bundle.source_facts[0]
        metadata = dict(item.evidence_metadata)
        self.assertEqual("data/road_24.png", metadata["image_path"])
        self.assertEqual("hash:1", metadata["image_hash"])
        self.assertEqual([100, 200], metadata["image_size"])
        self.assertEqual("element:1", metadata["element_id"])
        self.assertEqual("page:1", metadata["page_id"])
        self.assertEqual("Block", metadata["element_type"])
        self.assertEqual(
            {"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
            metadata["bbox"],
        )
        self.assertEqual(
            {"x_min": 0.1, "y_min": 0.2, "x_max": 0.3, "y_max": 0.4},
            metadata["normalized_bbox"],
        )
        self.assertEqual("hash:1", item.value["image_hash"])
        self.assertNotIn("decision", metadata)
        self.assertNotIn("selected_targets", metadata)
        self.assertEqual(FactKind.SOURCE_FACT, item.fact_kind)

    def test_block_trace_carries_location_metadata(self):
        requirement = make_requirement(
            EvidenceType.BLOCK_TRACE,
            AssistantScope(block_id="block:1"),
        )
        plan = RetrievalPlan(
            request_id="req:1",
            steps=(
                make_step(
                    "step:1",
                    "get_block_trace",
                    requirement.requirement_id,
                    {"block_id": "block:1"},
                    AssistantScope(block_id="block:1"),
                ),
            ),
        )
        trace = BlockTrace(
            block_id="block:1",
            project_id="project:1",
            drawing_set_id="set:1",
            page_id="page:1",
            bbox=BBox(1, 2, 3, 4),
            normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
            image_path="data/road_24.png",
        )
        raw = RawRetrievalResult(results={"step:1": trace})
        calls = (make_call("step:1", "get_block_trace", 1),)

        bundle = RetrievalBundleBuilder().build(
            make_result(requirement),
            plan,
            raw,
            calls,
        )
        item = bundle.source_facts[0]
        metadata = dict(item.evidence_metadata)
        self.assertEqual("page:1", metadata["page_id"])
        self.assertEqual("block:1", metadata["block_id"])
        self.assertEqual("data/road_24.png", metadata["image_path"])
        self.assertEqual(
            {"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
            metadata["bbox"],
        )
        self.assertEqual(
            {"x_min": 0.1, "y_min": 0.2, "x_max": 0.3, "y_max": 0.4},
            metadata["normalized_bbox"],
        )
        self.assertEqual(FactKind.SOURCE_FACT, item.fact_kind)

    def test_block_trace_maps_to_source_fact_with_scope_and_bbox(self):
        requirement = make_requirement(
            EvidenceType.BLOCK_TRACE,
            AssistantScope(block_id="block:1"),
        )
        plan = RetrievalPlan(
            request_id="req:1",
            steps=(
                make_step(
                    "step:1",
                    "get_block_trace",
                    requirement.requirement_id,
                    {"block_id": "block:1"},
                    AssistantScope(block_id="block:1"),
                ),
            ),
        )
        trace = BlockTrace(
            block_id="block:1",
            project_id="project:1",
            drawing_set_id="set:1",
            page_id="page:1",
            bbox=BBox(1, 2, 3, 4),
            normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
            image_path="data/road_24.png",
        )
        raw = RawRetrievalResult(results={"step:1": trace})
        calls = (make_call("step:1", "get_block_trace", 1),)

        bundle = RetrievalBundleBuilder().build(
            make_result(requirement),
            plan,
            raw,
            calls,
        )
        self.assertEqual(1, len(bundle.source_facts))
        item = bundle.source_facts[0]
        self.assertEqual(FactKind.SOURCE_FACT, item.fact_kind)
        self.assertEqual("block:1", item.scope.block_id)
        self.assertEqual("page:1", item.scope.page_id)
        self.assertEqual("call:step:1", item.source_call_id)
        self.assertEqual("block:1", item.evidence_refs[0].block_id)
        self.assertEqual({"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4}, dict(item.evidence_refs[0].bbox))

    def test_drawing_set_and_page_lists_map_to_source_facts(self):
        requirements = (
            make_requirement(
                EvidenceType.PROJECT_DRAWING_SETS,
                AssistantScope(project_id="project:1"),
            ),
            make_requirement(
                EvidenceType.DRAWING_SET_PAGES,
                AssistantScope(drawing_set_id="set:1"),
            ),
        )
        plan = RetrievalPlan(
            request_id="req:1",
            steps=(
                make_step(
                    "step:1",
                    "list_drawing_sets",
                    requirements[0].requirement_id,
                    {"project_id": "project:1", "limit": 100},
                    AssistantScope(project_id="project:1"),
                ),
                make_step(
                    "step:2",
                    "list_pages",
                    requirements[1].requirement_id,
                    {"drawing_set_id": "set:1", "limit": 100},
                    AssistantScope(drawing_set_id="set:1"),
                ),
            ),
        )
        raw = RawRetrievalResult(
            results={
                "step:1": (
                    DrawingSetSummary("project:1", "set:1", "图纸册A", 2),
                ),
                "step:2": (
                    PageSummary("set:1", "page:1", "road_24", 24),
                    PageSummary("set:1", "page:2", "road_25", 25),
                ),
            }
        )
        calls = (
            make_call("step:1", "list_drawing_sets", 1),
            make_call("step:2", "list_pages", 2),
        )

        bundle = RetrievalBundleBuilder().build(
            make_result(*requirements),
            plan,
            raw,
            calls,
        )
        self.assertEqual(3, len(bundle.source_facts))
        self.assertEqual("set:1", bundle.source_facts[0].scope.drawing_set_id)
        self.assertEqual("page:2", bundle.source_facts[2].scope.page_id)
        self.assertTrue(all(item.fact_kind == FactKind.SOURCE_FACT for item in bundle.source_facts))


class RetrievalBundleBuilderRelationSemanticTests(unittest.TestCase):
    def test_block_relations_split_derived_and_candidate_buckets(self):
        requirement = make_requirement(
            EvidenceType.BLOCK_RELATIONS,
            AssistantScope(block_id="block:1"),
        )
        plan = RetrievalPlan(
            request_id="req:1",
            steps=(
                make_step(
                    "step:1",
                    "get_block_relations",
                    requirement.requirement_id,
                    {"block_id": "block:1"},
                    AssistantScope(block_id="block:1"),
                ),
            ),
        )
        relations = BlockRelations(
            block_id="block:1",
            caption_ids=("caption:1",),
            basic_info_ids=("bi:1",),
            annotation_ids=("ann:1",),
            section_mark_ids=("sm:1",),
            candidate_caption_ids=("cand:1",),
            candidate_section_mark_ids=("candsm:1",),
        )
        raw = RawRetrievalResult(results={"step:1": relations})
        calls = (make_call("step:1", "get_block_relations", 1),)

        bundle = RetrievalBundleBuilder().build(
            make_result(requirement),
            plan,
            raw,
            calls,
        )
        self.assertEqual(4, len(bundle.derived_relations))
        self.assertEqual(2, len(bundle.candidate_relations))
        self.assertTrue(
            all(item.fact_kind == FactKind.DERIVED_RELATION for item in bundle.derived_relations)
        )
        self.assertTrue(
            all(item.fact_kind == FactKind.CANDIDATE_RELATION for item in bundle.candidate_relations)
        )

    def test_text_observations_map_to_semantic_observations(self):
        requirement = make_requirement(
            EvidenceType.TEXT_OBSERVATIONS,
            AssistantScope(page_id="page:1"),
        )
        plan = RetrievalPlan(
            request_id="req:1",
            steps=(
                make_step(
                    "step:1",
                    "list_text_observations",
                    requirement.requirement_id,
                    {"page_id": "page:1", "element_id": None, "recognition_run_id": None, "statuses": None},
                    AssistantScope(page_id="page:1"),
                ),
            ),
        )
        observation = SemanticObservationSummary(
            observation_id="obs:1",
            recognition_run_id="run:1",
            target_element_id="element:1",
            target_element_type="BlockCaption",
            page_id="page:1",
            raw_text="标题",
            normalized_text="标题",
            bbox=BBox(1, 2, 3, 4),
            normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
            confidence=0.9,
            status="completed",
            image_hash="hash:1",
            cache_key="semantic:obs",
            model_version="1.0",
            contract_version="contract:v1",
            preprocessing_version="pre:v1",
            normalization_rule_version="norm:v1",
            created_at="2026-08-12T00:00:00Z",
        )
        raw = RawRetrievalResult(results={"step:1": (observation,)})
        calls = (make_call("step:1", "list_text_observations", 1),)

        bundle = RetrievalBundleBuilder().build(
            make_result(requirement),
            plan,
            raw,
            calls,
        )
        self.assertEqual(1, len(bundle.semantic_observations))
        item = bundle.semantic_observations[0]
        self.assertEqual(FactKind.SEMANTIC_OBSERVATION, item.fact_kind)
        self.assertEqual("element:1", item.scope.element_id)
        self.assertEqual("run:1", item.evidence_refs[0].recognition_run_id)
        self.assertEqual("completed", item.status)
        self.assertEqual("2026-08-12T00:00:00Z", item.created_at_or_version)
        metadata = dict(item.evidence_metadata)
        self.assertEqual("hash:1", metadata["image_hash"])
        self.assertEqual("semantic:obs", metadata["cache_key"])
        self.assertEqual("default", metadata["model_profile"])
        self.assertEqual("1.0", metadata["model_version"])
        self.assertEqual("default", metadata["prompt_version"])
        self.assertEqual("contract:v1", metadata["contract_version"])
        self.assertEqual("pre:v1", metadata["preprocessing_version"])
        self.assertEqual("norm:v1", metadata["normalization_rule_version"])
        self.assertEqual("completed", metadata["status"])

    def test_observation_missing_metadata_is_expressed_as_none(self):
        requirement = make_requirement(
            EvidenceType.TEXT_OBSERVATIONS,
            AssistantScope(page_id="page:1"),
        )
        plan = RetrievalPlan(
            request_id="req:1",
            steps=(
                make_step(
                    "step:1",
                    "list_text_observations",
                    requirement.requirement_id,
                    {"page_id": "page:1", "element_id": None, "recognition_run_id": None, "statuses": None},
                    AssistantScope(page_id="page:1"),
                ),
            ),
        )
        observation = SemanticObservationSummary(
            observation_id="obs:2",
            recognition_run_id="run:2",
            target_element_id="element:2",
            target_element_type="Text",
            page_id="page:1",
            raw_text="A",
            normalized_text="A",
            bbox=BBox(1, 2, 3, 4),
            normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
            confidence=0.8,
            status="confirmed",
        )
        raw = RawRetrievalResult(results={"step:1": (observation,)})
        calls = (make_call("step:1", "list_text_observations", 1),)

        bundle = RetrievalBundleBuilder().build(
            make_result(requirement),
            plan,
            raw,
            calls,
        )
        metadata = dict(bundle.semantic_observations[0].evidence_metadata)
        self.assertIsNone(metadata["image_hash"])
        self.assertIsNone(metadata["cache_key"])
        self.assertIsNone(metadata["model_version"])
        self.assertIsNone(metadata["contract_version"])
        self.assertIsNone(metadata["preprocessing_version"])
        self.assertIsNone(metadata["normalization_rule_version"])
        self.assertEqual("confirmed", metadata["status"])
        self.assertIsNone(bundle.semantic_observations[0].created_at_or_version)

    def test_interpretations_map_to_semantic_interpretations_not_source_facts(self):
        requirement = make_requirement(
            EvidenceType.STRUCTURED_INTERPRETATIONS,
            AssistantScope(page_id="page:1"),
        )
        plan = RetrievalPlan(
            request_id="req:1",
            steps=(
                make_step(
                    "step:1",
                    "list_interpretations",
                    requirement.requirement_id,
                    {"page_id": "page:1", "element_id": None, "recognition_run_id": None, "statuses": None},
                    AssistantScope(page_id="page:1"),
                ),
            ),
        )
        interpretation = SemanticInterpretationSummary(
            interpretation_id="interp:1",
            recognition_run_id="run:1",
            element_id="element:1",
            element_type="Block",
            page_id="page:1",
            summary="该图块是一个标题",
            analysis_status="completed",
            payload_ref="payload:1",
            cache_key="semantic:interp",
            image_hash="hash:1",
            model_profile="qwen-vl",
            model_version="1.0",
            prompt_version="prompt:v1",
            contract_version="contract:v1",
            created_at="2026-08-12T00:00:00Z",
        )
        raw = RawRetrievalResult(results={"step:1": (interpretation,)})
        calls = (make_call("step:1", "list_interpretations", 1),)

        bundle = RetrievalBundleBuilder().build(
            make_result(requirement),
            plan,
            raw,
            calls,
        )
        self.assertEqual(1, len(bundle.semantic_interpretations))
        self.assertEqual((), bundle.source_facts)
        self.assertEqual(FactKind.SEMANTIC_INTERPRETATION, bundle.semantic_interpretations[0].fact_kind)
        self.assertEqual("payload:1", bundle.semantic_interpretations[0].evidence_refs[0].payload_ref)
        item = bundle.semantic_interpretations[0]
        self.assertEqual("completed", item.status)
        self.assertEqual("2026-08-12T00:00:00Z", item.created_at_or_version)
        metadata = dict(item.evidence_metadata)
        self.assertEqual("semantic:interp", metadata["cache_key"])
        self.assertEqual("hash:1", metadata["image_hash"])
        self.assertEqual("qwen-vl", metadata["model_profile"])
        self.assertEqual("1.0", metadata["model_version"])
        self.assertEqual("prompt:v1", metadata["prompt_version"])
        self.assertEqual("contract:v1", metadata["contract_version"])
        self.assertEqual("completed", metadata["status"])
        self.assertEqual((), bundle.source_facts)

    def test_section_matches_split_candidate_and_formal_buckets(self):
        requirement = make_requirement(
            EvidenceType.SECTION_MATCHES,
            AssistantScope(cross_section_id="section:1"),
        )
        plan = RetrievalPlan(
            request_id="req:1",
            steps=(
                make_step(
                    "step:1",
                    "list_section_matches",
                    requirement.requirement_id,
                    {"cross_section_id": "section:1", "page_id": None, "statuses": None},
                    AssistantScope(cross_section_id="section:1"),
                ),
            ),
        )
        candidate = SectionMatchSummary(
            cross_section_id="section:1",
            match_status="candidate",
            status="candidate",
            fact_kind="candidate_relation",
            candidate_count=2,
            matched_caption_ids=("caption:1", "caption:2"),
        )
        formal = SectionMatchSummary(
            cross_section_id="section:1",
            match_status="formal",
            status="formal",
            fact_kind="formal_relation",
            matched_caption_ids=("caption:1",),
            persisted=True,
        )
        raw = RawRetrievalResult(results={"step:1": (candidate, formal)})
        calls = (make_call("step:1", "list_section_matches", 2),)

        bundle = RetrievalBundleBuilder().build(
            make_result(requirement),
            plan,
            raw,
            calls,
        )
        self.assertEqual(1, len(bundle.candidate_relations))
        self.assertEqual(1, len(bundle.formal_relations))
        self.assertEqual(FactKind.CANDIDATE_RELATION, bundle.candidate_relations[0].fact_kind)
        self.assertEqual(FactKind.FORMAL_RELATION, bundle.formal_relations[0].fact_kind)
        candidate_metadata = dict(bundle.candidate_relations[0].evidence_metadata)
        self.assertEqual("candidate", candidate_metadata["status"])
        self.assertIsNone(candidate_metadata["cache_key"])
        formal_metadata = dict(bundle.formal_relations[0].evidence_metadata)
        self.assertEqual("formal", formal_metadata["status"])
        self.assertIsNone(formal_metadata["cache_key"])

    def test_candidate_relations_never_enter_formal_bucket(self):
        requirement = make_requirement(
            EvidenceType.CANDIDATE_RELATIONS,
            AssistantScope(page_id="page:1"),
        )
        plan = RetrievalPlan(
            request_id="req:1",
            steps=(
                make_step(
                    "step:1",
                    "list_candidate_relations",
                    requirement.requirement_id,
                    {"page_id": "page:1", "block_id": None, "relation_type": None, "status": None},
                    AssistantScope(page_id="page:1"),
                ),
            ),
        )
        candidate = make_candidate_summary("group:1")
        raw = RawRetrievalResult(results={"step:1": (candidate,)})
        calls = (make_call("step:1", "list_candidate_relations", 1),)

        bundle = RetrievalBundleBuilder().build(
            make_result(requirement),
            plan,
            raw,
            calls,
        )
        self.assertEqual(1, len(bundle.candidate_relations))
        self.assertEqual((), bundle.formal_relations)

    def test_candidate_relations_carry_status_metadata(self):
        requirement = make_requirement(
            EvidenceType.CANDIDATE_RELATIONS,
            AssistantScope(page_id="page:1"),
        )
        plan = RetrievalPlan(
            request_id="req:1",
            steps=(
                make_step(
                    "step:1",
                    "list_candidate_relations",
                    requirement.requirement_id,
                    {"page_id": "page:1", "block_id": None, "relation_type": None, "status": None},
                    AssistantScope(page_id="page:1"),
                ),
            ),
        )
        candidate = make_candidate_summary("group:2")
        raw = RawRetrievalResult(results={"step:1": (candidate,)})
        calls = (make_call("step:1", "list_candidate_relations", 1),)

        bundle = RetrievalBundleBuilder().build(
            make_result(requirement),
            plan,
            raw,
            calls,
        )
        item = bundle.candidate_relations[0]
        self.assertEqual("matched_candidate", item.status)
        metadata = dict(item.evidence_metadata)
        self.assertEqual("matched_candidate", metadata["status"])
        self.assertEqual("run:1", metadata["recognition_run_id"])
        self.assertIsNone(metadata["cache_key"])
        self.assertIsNone(metadata["contract_version"])
        self.assertEqual((), bundle.formal_relations)

    def test_candidate_relations_carry_group_relation_type_and_direction(self):
        requirement = make_requirement(
            EvidenceType.CANDIDATE_RELATIONS,
            AssistantScope(page_id="page:1"),
        )
        plan = RetrievalPlan(
            request_id="req:1",
            steps=(
                make_step(
                    "step:1",
                    "list_candidate_relations",
                    requirement.requirement_id,
                    {"page_id": "page:1", "block_id": None, "relation_type": None, "status": None},
                    AssistantScope(page_id="page:1"),
                ),
            ),
        )
        candidate = make_candidate_summary("group:3")
        raw = RawRetrievalResult(results={"step:1": (candidate,)})
        calls = (make_call("step:1", "list_candidate_relations", 1),)

        bundle = RetrievalBundleBuilder().build(
            make_result(requirement),
            plan,
            raw,
            calls,
        )
        metadata = dict(bundle.candidate_relations[0].evidence_metadata)
        self.assertEqual("group:3", metadata["candidate_group_id"])
        self.assertEqual("candidate_caption_of", metadata["relation_type"])
        self.assertEqual("block:1->candidate_caption_of", metadata["direction"])

    def test_candidate_relations_carry_subject_predicate_objects(self):
        requirement = make_requirement(
            EvidenceType.CANDIDATE_RELATIONS,
            AssistantScope(page_id="page:1"),
        )
        plan = RetrievalPlan(
            request_id="req:1",
            steps=(
                make_step(
                    "step:1",
                    "list_candidate_relations",
                    requirement.requirement_id,
                    {"page_id": "page:1", "block_id": None, "relation_type": None, "status": None},
                    AssistantScope(page_id="page:1"),
                ),
            ),
        )
        candidate = make_candidate_summary("group:4")
        candidate = CandidateRelationSummary(
            candidate_group_id=candidate.candidate_group_id,
            page_id=candidate.page_id,
            block_id=candidate.block_id,
            relation_type=candidate.relation_type,
            status=candidate.status,
            score=candidate.score,
            recognition_run_id=candidate.recognition_run_id,
            source_element_id="caption:1",
            target_element_id="block:1",
        )
        raw = RawRetrievalResult(results={"step:1": (candidate,)})
        calls = (make_call("step:1", "list_candidate_relations", 1),)

        bundle = RetrievalBundleBuilder().build(
            make_result(requirement),
            plan,
            raw,
            calls,
        )
        value = bundle.candidate_relations[0].value
        self.assertEqual("caption:1", value["subject"])
        self.assertEqual("candidate_caption_of", value["predicate"])
        self.assertEqual(("block:1",), value["objects"])

    def test_candidate_relations_fallback_subject_to_block_id(self):
        requirement = make_requirement(
            EvidenceType.CANDIDATE_RELATIONS,
            AssistantScope(page_id="page:1"),
        )
        plan = RetrievalPlan(
            request_id="req:1",
            steps=(
                make_step(
                    "step:1",
                    "list_candidate_relations",
                    requirement.requirement_id,
                    {"page_id": "page:1", "block_id": None, "relation_type": None, "status": None},
                    AssistantScope(page_id="page:1"),
                ),
            ),
        )
        candidate = make_candidate_summary("group:5")
        raw = RawRetrievalResult(results={"step:1": (candidate,)})
        calls = (make_call("step:1", "list_candidate_relations", 1),)

        bundle = RetrievalBundleBuilder().build(
            make_result(requirement),
            plan,
            raw,
            calls,
        )
        value = bundle.candidate_relations[0].value
        self.assertEqual("block:1", value["subject"])
        self.assertEqual("candidate_caption_of", value["predicate"])
        self.assertEqual((), value["objects"])

    def test_derived_relations_carry_relation_type_and_direction(self):
        requirement = make_requirement(
            EvidenceType.BLOCK_RELATIONS,
            AssistantScope(block_id="block:1"),
        )
        plan = RetrievalPlan(
            request_id="req:1",
            steps=(
                make_step(
                    "step:1",
                    "get_block_relations",
                    requirement.requirement_id,
                    {"block_id": "block:1"},
                    AssistantScope(block_id="block:1"),
                ),
            ),
        )
        relations = BlockRelations(block_id="block:1", caption_ids=("caption:1",))
        raw = RawRetrievalResult(results={"step:1": relations})
        calls = (make_call("step:1", "get_block_relations", 1),)

        bundle = RetrievalBundleBuilder().build(
            make_result(requirement),
            plan,
            raw,
            calls,
        )
        metadata = dict(bundle.derived_relations[0].evidence_metadata)
        self.assertEqual("has_caption", metadata["relation_type"])
        self.assertEqual("block:1->caption:1", metadata["direction"])
        self.assertIsNone(metadata["candidate_group_id"])

    def test_block_relations_project_normalizable_relation_values(self):
        from drawing_graph.assistant_evidence_normalization import EvidenceNormalizer
        from drawing_graph.assistant_evidence_fusion_factory import _default_normalization_registry

        requirement = make_requirement(
            EvidenceType.BLOCK_RELATIONS,
            AssistantScope(block_id="block:1"),
        )
        plan = RetrievalPlan(
            request_id="req:1",
            steps=(
                make_step(
                    "step:1",
                    "get_block_relations",
                    requirement.requirement_id,
                    {"block_id": "block:1"},
                    AssistantScope(block_id="block:1"),
                ),
            ),
        )
        relations = BlockRelations(block_id="block:1", caption_ids=("caption:1",))
        raw = RawRetrievalResult(results={"step:1": relations})
        calls = (make_call("step:1", "get_block_relations", 1),)

        bundle = RetrievalBundleBuilder().build(make_result(requirement), plan, raw, calls)
        normalizer = EvidenceNormalizer(rule_registry=_default_normalization_registry())
        result = normalizer.normalize(bundle.derived_relations)

        self.assertEqual(1, len(result.normalized))
        self.assertEqual((), result.isolated)


def make_candidate_summary(candidate_group_id: str):
    from drawing_graph.tool_models import CandidateRelationSummary

    return CandidateRelationSummary(
        candidate_group_id=candidate_group_id,
        page_id="page:1",
        block_id="block:1",
        relation_type="candidate_caption_of",
        status="matched_candidate",
        score=0.8,
        recognition_run_id="run:1",
    )


class RetrievalBundleBuilderSummaryTests(unittest.TestCase):
    def test_empty_result_creates_missing_evidence(self):
        requirement = make_requirement(
            EvidenceType.CANDIDATE_RELATIONS,
            AssistantScope(page_id="page:1"),
        )
        plan = RetrievalPlan(
            request_id="req:1",
            steps=(
                make_step(
                    "step:1",
                    "list_candidate_relations",
                    requirement.requirement_id,
                    {"page_id": "page:1", "block_id": None, "relation_type": None, "status": None},
                    AssistantScope(page_id="page:1"),
                ),
            ),
        )
        raw = RawRetrievalResult(results={"step:1": ()})
        calls = (make_call("step:1", "list_candidate_relations", 0),)

        bundle = RetrievalBundleBuilder().build(
            make_result(requirement),
            plan,
            raw,
            calls,
        )
        self.assertEqual(1, len(bundle.missing_evidence))
        missing = bundle.missing_evidence[0]
        self.assertEqual(ReasonCode.EMPTY_RESULT, missing.reason_code)
        self.assertEqual(requirement.requirement_id, missing.requirement_id)
        self.assertEqual(EvidenceType.CANDIDATE_RELATIONS, missing.evidence_type)

    def test_unsupported_step_creates_missing_evidence(self):
        requirement = make_requirement(
            EvidenceType.CANDIDATE_RELATIONS,
            AssistantScope(page_id="page:1"),
        )
        step = RetrievalStep(
            step_id="step:1",
            facade_method="recognize_page_semantics",
            parameters={},
            requirement_ids=(requirement.requirement_id,),
        )
        plan = RetrievalPlan(request_id="req:1", steps=(step,))
        raw = RawRetrievalResult(results={})
        calls = (
            SourceCallRecord(
                source_call_id="call:step:1",
                step_id="step:1",
                facade_method="recognize_page_semantics",
                status=RetrievalStatus.ERROR,
                reason_code=ReasonCode.UNSUPPORTED_EVIDENCE_TYPE,
                warning="unsupported facade method",
            ),
        )

        bundle = RetrievalBundleBuilder().build(
            make_result(requirement),
            plan,
            raw,
            calls,
        )
        self.assertEqual(1, len(bundle.missing_evidence))
        self.assertEqual(ReasonCode.UNSUPPORTED_EVIDENCE_TYPE, bundle.missing_evidence[0].reason_code)

    def test_required_failure_sets_error_status(self):
        requirement = make_requirement(
            EvidenceType.BLOCK_TRACE,
            AssistantScope(block_id="block:1"),
        )
        plan = RetrievalPlan(
            request_id="req:1",
            steps=(
                make_step(
                    "step:1",
                    "get_block_trace",
                    requirement.requirement_id,
                    {"block_id": "block:1"},
                    AssistantScope(block_id="block:1"),
                ),
            ),
        )
        raw = RawRetrievalResult(results={})
        calls = (
            SourceCallRecord(
                source_call_id="call:step:1",
                step_id="step:1",
                facade_method="get_block_trace",
                status=RetrievalStatus.ERROR,
                reason_code=ReasonCode.FACADE_CALL_FAILED,
                warning="backend unavailable",
            ),
        )

        bundle = RetrievalBundleBuilder().build(
            make_result(requirement),
            plan,
            raw,
            calls,
        )
        self.assertEqual(RetrievalStatus.ERROR, bundle.status)

    def test_optional_failure_with_evidence_sets_partial_status(self):
        trace_requirement = make_requirement(
            EvidenceType.BLOCK_TRACE,
            AssistantScope(block_id="block:1"),
        )
        facts_requirement = make_requirement(
            EvidenceType.PAGE_SOURCE_FACTS,
            AssistantScope(page_id="page:1"),
        )
        plan = RetrievalPlan(
            request_id="req:1",
            steps=(
                RetrievalStep(
                    step_id="step:1",
                    facade_method="get_block_trace",
                    parameters={"block_id": "block:1"},
                    required=False,
                    requirement_ids=(trace_requirement.requirement_id,),
                ),
                make_step(
                    "step:2",
                    "get_page_source_facts",
                    facts_requirement.requirement_id,
                    {"page_id": "page:1", "element_types": None, "include_image_meta": True},
                    AssistantScope(page_id="page:1"),
                ),
            ),
        )
        facts = PageSourceFacts(page_id="page:1", image_path=None, elements=())
        raw = RawRetrievalResult(results={"step:2": facts})
        calls = (
            SourceCallRecord(
                source_call_id="call:step:1",
                step_id="step:1",
                facade_method="get_block_trace",
                status=RetrievalStatus.ERROR,
                reason_code=ReasonCode.FACADE_CALL_FAILED,
                warning="boom",
            ),
            make_call("step:2", "get_page_source_facts", 1),
        )

        bundle = RetrievalBundleBuilder().build(
            make_result(trace_requirement, facts_requirement),
            plan,
            raw,
            calls,
        )
        self.assertEqual(RetrievalStatus.PARTIAL, bundle.status)
        self.assertEqual(1, len(bundle.source_facts))

    def test_truncated_result_adds_truncation_warning(self):
        requirement = make_requirement(
            EvidenceType.DRAWING_SET_PAGES,
            AssistantScope(drawing_set_id="set:1"),
        )
        plan = RetrievalPlan(
            request_id="req:1",
            steps=(
                RetrievalStep(
                    step_id="step:1",
                    facade_method="list_pages",
                    parameters={"drawing_set_id": "set:1", "limit": 1},
                    limit=1,
                    requirement_ids=(requirement.requirement_id,),
                ),
            ),
        )
        raw = RawRetrievalResult(
            results={
                "step:1": (
                    PageSummary("set:1", "page:1", "road_24", 24),
                    PageSummary("set:1", "page:2", "road_25", 25),
                )
            },
            truncated_step_ids=("step:1",),
        )
        calls = (make_call("step:1", "list_pages", 2),)

        bundle = RetrievalBundleBuilder().build(
            make_result(requirement),
            plan,
            raw,
            calls,
        )
        self.assertEqual(1, len(bundle.warnings))
        self.assertEqual(ReasonCode.RESULT_TRUNCATED, bundle.warnings[0].reason_code)
        self.assertEqual(2, len(bundle.source_facts))


class RetrievalSubrequestProjectionTests(unittest.TestCase):
    def test_bundle_carries_plan_subrequest_id(self):
        requirement = make_requirement(
            EvidenceType.PAGE_SOURCE_FACTS,
            AssistantScope(page_id="page:1"),
        )
        plan = RetrievalPlan(
            request_id="req:1",
            subrequest_id="sub:1",
            steps=(
                make_step(
                    "step:1",
                    "get_page_source_facts",
                    requirement.requirement_id,
                    {"page_id": "page:1", "element_types": None, "include_image_meta": True},
                    AssistantScope(page_id="page:1"),
                ),
            ),
        )
        facts = PageSourceFacts(page_id="page:1", image_path=None, elements=())
        raw = RawRetrievalResult(results={"step:1": facts})
        calls = (make_call("step:1", "get_page_source_facts", 1),)

        bundle = RetrievalBundleBuilder().build(
            make_result(requirement),
            plan,
            raw,
            calls,
        )
        self.assertEqual("sub:1", bundle.subrequest_id)

    def test_top_level_bundle_keeps_subrequest_id_none(self):
        requirement = make_requirement(
            EvidenceType.BLOCK_TRACE,
            AssistantScope(block_id="block:1"),
        )
        plan = RetrievalPlan(
            request_id="req:1",
            steps=(
                make_step(
                    "step:1",
                    "get_block_trace",
                    requirement.requirement_id,
                    {"block_id": "block:1"},
                    AssistantScope(block_id="block:1"),
                ),
            ),
        )
        trace = BlockTrace(
            block_id="block:1",
            project_id="project:1",
            drawing_set_id="set:1",
            page_id="page:1",
            bbox=BBox(1, 2, 3, 4),
            normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
            image_path=None,
        )
        raw = RawRetrievalResult(results={"step:1": trace})
        calls = (make_call("step:1", "get_block_trace", 1),)

        bundle = RetrievalBundleBuilder().build(
            make_result(requirement),
            plan,
            raw,
            calls,
        )
        self.assertIsNone(bundle.subrequest_id)

    def test_subrequest_passthrough_does_not_change_buckets_or_status(self):
        requirement = make_requirement(
            EvidenceType.BLOCK_TRACE,
            AssistantScope(block_id="block:1"),
        )
        plan = RetrievalPlan(
            request_id="req:1",
            subrequest_id="sub:2",
            steps=(
                make_step(
                    "step:1",
                    "get_block_trace",
                    requirement.requirement_id,
                    {"block_id": "block:1"},
                    AssistantScope(block_id="block:1"),
                ),
            ),
        )
        trace = BlockTrace(
            block_id="block:1",
            project_id="project:1",
            drawing_set_id="set:1",
            page_id="page:1",
            bbox=BBox(1, 2, 3, 4),
            normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
            image_path=None,
        )
        raw = RawRetrievalResult(results={"step:1": trace})
        calls = (make_call("step:1", "get_block_trace", 1),)

        bundle = RetrievalBundleBuilder().build(
            make_result(requirement),
            plan,
            raw,
            calls,
        )
        self.assertEqual("sub:2", bundle.subrequest_id)
        self.assertEqual(1, len(bundle.source_facts))
        self.assertEqual((), bundle.missing_evidence)
        self.assertEqual(RetrievalStatus.OK, bundle.status)


class RetrievalBundleDecisionMetadataCompatibilityTests(unittest.TestCase):
    def test_evidence_metadata_does_not_break_bucket_validation(self):
        observation = EvidenceItem(
            evidence_id="evidence:obs:1",
            fact_kind=FactKind.SEMANTIC_OBSERVATION,
            scope=AssistantScope(page_id="page:1"),
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
        bundle = RetrievalBundle(
            request_id="req:1",
            semantic_observations=(observation,),
        )
        self.assertEqual(
            "semantic:abc",
            bundle.semantic_observations[0].evidence_metadata["cache_key"],
        )

    def test_candidate_metadata_cannot_enter_formal_bucket(self):
        candidate = EvidenceItem(
            evidence_id="evidence:cand:1",
            fact_kind=FactKind.CANDIDATE_RELATION,
            value={},
            evidence_metadata={"cache_key": "semantic:match"},
        )
        with self.assertRaises(ValueError):
            RetrievalBundle(request_id="req:2", formal_relations=(candidate,))


if __name__ == "__main__":
    unittest.main()
