"""Tests for the read-only graph retrieval planner scope validation."""

import inspect
from pathlib import Path
import unittest

from drawing_graph.assistant_models import (
    AssistantScope,
    EvidenceRequirement,
    EvidenceType,
    QuestionUnderstandingResult,
    ReasonCode,
    RetrievalPlan,
    RetrievalPolicy,
)
from drawing_graph.assistant_retrieval_planner import RetrievalPlanner


def make_result(*requirements: EvidenceRequirement) -> QuestionUnderstandingResult:
    return QuestionUnderstandingResult(
        request_id="req:1",
        question_type="page_summary",
        required_evidence=requirements,
    )


class RetrievalPlannerScopeValidationTests(unittest.TestCase):
    def test_missing_page_id_for_page_source_facts_returns_scope_missing(self):
        requirement = EvidenceRequirement(
            requirement_id="req-ev:1",
            evidence_type=EvidenceType.PAGE_SOURCE_FACTS,
            target_scope=AssistantScope(),
        )
        plan = RetrievalPlanner().plan(make_result(requirement), RetrievalPolicy())
        self.assertIsInstance(plan, RetrievalPlan)
        self.assertEqual("req:1", plan.request_id)
        self.assertEqual((), plan.steps)
        self.assertEqual(1, len(plan.warnings))
        warning = plan.warnings[0]
        self.assertEqual(ReasonCode.SCOPE_MISSING, warning.reason_code)
        self.assertEqual("req-ev:1", warning.requirement_id)

    def test_missing_block_id_for_block_trace_returns_scope_missing(self):
        requirement = EvidenceRequirement(
            requirement_id="req-ev:2",
            evidence_type=EvidenceType.BLOCK_TRACE,
            target_scope=AssistantScope(),
        )
        plan = RetrievalPlanner().plan(make_result(requirement), RetrievalPolicy())
        self.assertEqual((), plan.steps)
        self.assertEqual(ReasonCode.SCOPE_MISSING, plan.warnings[0].reason_code)

    def test_conflicting_page_and_block_scope_returns_scope_conflict(self):
        requirement = EvidenceRequirement(
            requirement_id="req-ev:3",
            evidence_type=EvidenceType.PAGE_SOURCE_FACTS,
            target_scope=AssistantScope(page_id="page:1", block_id="block:1"),
        )
        plan = RetrievalPlanner().plan(make_result(requirement), RetrievalPolicy())
        self.assertEqual((), plan.steps)
        self.assertEqual(ReasonCode.SCOPE_CONFLICT, plan.warnings[0].reason_code)

    def test_scope_validation_does_not_import_tool_facade(self):
        module_path = Path(inspect.getfile(RetrievalPlanner))
        source = module_path.read_text(encoding="utf-8")
        self.assertNotIn("tool_facade", source)


class RetrievalPlannerSourceFactMappingTests(unittest.TestCase):
    SOURCE_FACT_METHODS = {
        "list_drawing_sets",
        "list_pages",
        "get_page_source_facts",
        "get_block_trace",
    }

    def test_project_drawing_sets_maps_to_list_drawing_sets(self):
        requirement = EvidenceRequirement(
            requirement_id="req-ev:10",
            evidence_type=EvidenceType.PROJECT_DRAWING_SETS,
            target_scope=AssistantScope(project_id="project:1"),
        )
        plan = RetrievalPlanner().plan(make_result(requirement), RetrievalPolicy())
        self.assertEqual((), plan.warnings)
        self.assertEqual(1, len(plan.steps))
        step = plan.steps[0]
        self.assertEqual("list_drawing_sets", step.facade_method)
        self.assertEqual("project:1", step.parameters["project_id"])
        self.assertEqual(100, step.limit)
        self.assertTrue(step.required)
        self.assertEqual(("req-ev:10",), step.requirement_ids)

    def test_drawing_set_pages_maps_to_list_pages(self):
        requirement = EvidenceRequirement(
            requirement_id="req-ev:11",
            evidence_type=EvidenceType.DRAWING_SET_PAGES,
            target_scope=AssistantScope(drawing_set_id="set:1"),
        )
        plan = RetrievalPlanner().plan(make_result(requirement), RetrievalPolicy())
        self.assertEqual(1, len(plan.steps))
        step = plan.steps[0]
        self.assertEqual("list_pages", step.facade_method)
        self.assertEqual("set:1", step.parameters["drawing_set_id"])
        self.assertEqual(("req-ev:11",), step.requirement_ids)

    def test_page_source_facts_maps_to_get_page_source_facts(self):
        requirement = EvidenceRequirement(
            requirement_id="req-ev:12",
            evidence_type=EvidenceType.PAGE_SOURCE_FACTS,
            target_scope=AssistantScope(page_id="page:1"),
        )
        plan = RetrievalPlanner().plan(make_result(requirement), RetrievalPolicy())
        self.assertEqual(1, len(plan.steps))
        step = plan.steps[0]
        self.assertEqual("get_page_source_facts", step.facade_method)
        self.assertEqual("page:1", step.parameters["page_id"])
        self.assertIsNone(step.parameters["element_types"])
        self.assertTrue(step.parameters["include_image_meta"])
        self.assertEqual(("req-ev:12",), step.requirement_ids)

    def test_block_trace_maps_to_get_block_trace(self):
        requirement = EvidenceRequirement(
            requirement_id="req-ev:13",
            evidence_type=EvidenceType.BLOCK_TRACE,
            target_scope=AssistantScope(block_id="block:1"),
        )
        plan = RetrievalPlanner().plan(make_result(requirement), RetrievalPolicy())
        self.assertEqual(1, len(plan.steps))
        step = plan.steps[0]
        self.assertEqual("get_block_trace", step.facade_method)
        self.assertEqual("block:1", step.parameters["block_id"])
        self.assertEqual(("req-ev:13",), step.requirement_ids)

    def test_source_fact_steps_use_only_whitelisted_methods(self):
        requirements = (
            EvidenceRequirement(
                requirement_id="req-ev:14",
                evidence_type=EvidenceType.PROJECT_DRAWING_SETS,
                target_scope=AssistantScope(project_id="project:1"),
            ),
            EvidenceRequirement(
                requirement_id="req-ev:15",
                evidence_type=EvidenceType.DRAWING_SET_PAGES,
                target_scope=AssistantScope(drawing_set_id="set:1"),
            ),
            EvidenceRequirement(
                requirement_id="req-ev:16",
                evidence_type=EvidenceType.PAGE_SOURCE_FACTS,
                target_scope=AssistantScope(page_id="page:1"),
            ),
            EvidenceRequirement(
                requirement_id="req-ev:17",
                evidence_type=EvidenceType.BLOCK_TRACE,
                target_scope=AssistantScope(block_id="block:1"),
            ),
        )
        plan = RetrievalPlanner().plan(make_result(*requirements), RetrievalPolicy())
        self.assertEqual(
            self.SOURCE_FACT_METHODS,
            {step.facade_method for step in plan.steps},
        )
        self.assertTrue(all(step.facade_method in self.SOURCE_FACT_METHODS for step in plan.steps))


class RetrievalPlannerRelationSemanticMappingTests(unittest.TestCase):
    FORBIDDEN_METHODS = {
        "recognize_page_semantics",
        "review_candidate_relation",
        "match_section_caption",
    }

    def test_block_relations_maps_to_get_block_relations(self):
        requirement = EvidenceRequirement(
            requirement_id="req-ev:20",
            evidence_type=EvidenceType.BLOCK_RELATIONS,
            target_scope=AssistantScope(block_id="block:1"),
        )
        plan = RetrievalPlanner().plan(make_result(requirement), RetrievalPolicy())
        self.assertEqual((), plan.warnings)
        self.assertEqual(1, len(plan.steps))
        step = plan.steps[0]
        self.assertEqual("get_block_relations", step.facade_method)
        self.assertEqual("block:1", step.parameters["block_id"])
        self.assertEqual(("req-ev:20",), step.requirement_ids)

    def test_text_observations_maps_to_list_text_observations_by_page(self):
        requirement = EvidenceRequirement(
            requirement_id="req-ev:21",
            evidence_type=EvidenceType.TEXT_OBSERVATIONS,
            target_scope=AssistantScope(page_id="page:1"),
        )
        plan = RetrievalPlanner().plan(make_result(requirement), RetrievalPolicy())
        self.assertEqual(2, len(plan.steps))
        step = plan.steps[0]
        self.assertEqual("list_text_observations", step.facade_method)
        self.assertEqual("page:1", step.parameters["page_id"])
        self.assertIsNone(step.parameters["element_id"])
        locate = plan.steps[1]
        self.assertEqual("get_page_source_facts", locate.facade_method)
        self.assertEqual("page:1", locate.parameters["page_id"])
        self.assertTrue(locate.parameters["include_image_meta"])
        self.assertEqual(("req-ev:21",), locate.requirement_ids)

    def test_text_observations_maps_to_list_text_observations_by_element(self):
        requirement = EvidenceRequirement(
            requirement_id="req-ev:22",
            evidence_type=EvidenceType.TEXT_OBSERVATIONS,
            target_scope=AssistantScope(element_id="element:1"),
        )
        plan = RetrievalPlanner().plan(make_result(requirement), RetrievalPolicy())
        self.assertEqual(1, len(plan.steps))
        step = plan.steps[0]
        self.assertEqual("list_text_observations", step.facade_method)
        self.assertIsNone(step.parameters["page_id"])
        self.assertEqual("element:1", step.parameters["element_id"])

    def test_structured_interpretations_maps_to_list_interpretations(self):
        requirement = EvidenceRequirement(
            requirement_id="req-ev:23",
            evidence_type=EvidenceType.STRUCTURED_INTERPRETATIONS,
            target_scope=AssistantScope(page_id="page:1"),
        )
        plan = RetrievalPlanner().plan(make_result(requirement), RetrievalPolicy())
        self.assertEqual(2, len(plan.steps))
        step = plan.steps[0]
        self.assertEqual("list_interpretations", step.facade_method)
        self.assertEqual("page:1", step.parameters["page_id"])
        locate = plan.steps[1]
        self.assertEqual("get_page_source_facts", locate.facade_method)
        self.assertEqual(("req-ev:23",), locate.requirement_ids)

    def test_semantic_locate_step_is_read_only_and_never_writes_back(self):
        requirement = EvidenceRequirement(
            requirement_id="req-ev:35",
            evidence_type=EvidenceType.STRUCTURED_INTERPRETATIONS,
            target_scope=AssistantScope(page_id="page:1"),
        )
        plan = RetrievalPlanner().plan(make_result(requirement), RetrievalPolicy())
        methods = {step.facade_method for step in plan.steps}
        self.assertNotIn("recognize_page_semantics", methods)
        self.assertNotIn("review_candidate_relation", methods)
        self.assertNotIn("match_section_caption", methods)
        self.assertTrue(all(not step.include_payload or step.facade_method == "get_semantic_payload" for step in plan.steps))

    def test_semantic_locate_step_merges_with_page_source_facts_requirement(self):
        page_facts = EvidenceRequirement(
            requirement_id="req-ev:36",
            evidence_type=EvidenceType.PAGE_SOURCE_FACTS,
            target_scope=AssistantScope(page_id="page:1"),
        )
        observations = EvidenceRequirement(
            requirement_id="req-ev:37",
            evidence_type=EvidenceType.TEXT_OBSERVATIONS,
            target_scope=AssistantScope(page_id="page:1"),
        )
        plan = RetrievalPlanner().plan(
            make_result(page_facts, observations),
            RetrievalPolicy(),
        )
        source_fact_steps = [
            step for step in plan.steps if step.facade_method == "get_page_source_facts"
        ]
        self.assertEqual(1, len(source_fact_steps))
        self.assertEqual(
            ("req-ev:36", "req-ev:37"),
            source_fact_steps[0].requirement_ids,
        )

    def test_payload_maps_only_when_include_payload_is_true(self):
        with_payload = EvidenceRequirement(
            requirement_id="req-ev:24",
            evidence_type=EvidenceType.SEMANTIC_PAYLOAD,
            target_scope=AssistantScope(page_id="page:1"),
            include_payload=True,
            payload_ref="payload:1",
        )
        without_payload = EvidenceRequirement(
            requirement_id="req-ev:25",
            evidence_type=EvidenceType.SEMANTIC_PAYLOAD,
            target_scope=AssistantScope(page_id="page:1"),
            include_payload=False,
        )
        plan = RetrievalPlanner().plan(make_result(with_payload, without_payload), RetrievalPolicy())
        self.assertEqual(1, len(plan.steps))
        step = plan.steps[0]
        self.assertEqual("get_semantic_payload", step.facade_method)
        self.assertEqual("payload:1", step.parameters["payload_ref"])
        self.assertEqual(("req-ev:24",), step.requirement_ids)

    def test_payload_without_ref_reports_scope_missing(self):
        requirement = EvidenceRequirement(
            requirement_id="req-ev:26",
            evidence_type=EvidenceType.SEMANTIC_PAYLOAD,
            target_scope=AssistantScope(page_id="page:1"),
            include_payload=True,
        )
        plan = RetrievalPlanner().plan(make_result(requirement), RetrievalPolicy())
        self.assertEqual((), plan.steps)
        self.assertEqual(ReasonCode.SCOPE_MISSING, plan.warnings[0].reason_code)

    def test_candidate_relations_maps_to_list_candidate_relations(self):
        requirement = EvidenceRequirement(
            requirement_id="req-ev:27",
            evidence_type=EvidenceType.CANDIDATE_RELATIONS,
            target_scope=AssistantScope(page_id="page:1"),
        )
        plan = RetrievalPlanner().plan(make_result(requirement), RetrievalPolicy())
        self.assertEqual(1, len(plan.steps))
        step = plan.steps[0]
        self.assertEqual("list_candidate_relations", step.facade_method)
        self.assertEqual("page:1", step.parameters["page_id"])
        self.assertIsNone(step.parameters["block_id"])
        self.assertIsNone(step.parameters["relation_type"])
        self.assertIsNone(step.parameters["status"])

    def test_section_matches_maps_to_list_section_matches(self):
        requirement = EvidenceRequirement(
            requirement_id="req-ev:28",
            evidence_type=EvidenceType.SECTION_MATCHES,
            target_scope=AssistantScope(cross_section_id="section:1"),
        )
        plan = RetrievalPlanner().plan(make_result(requirement), RetrievalPolicy())
        self.assertEqual(1, len(plan.steps))
        step = plan.steps[0]
        self.assertEqual("list_section_matches", step.facade_method)
        self.assertEqual("section:1", step.parameters["cross_section_id"])
        self.assertIsNone(step.parameters["statuses"])

    def test_forbidden_methods_never_appear_in_any_plan(self):
        requirements = (
            EvidenceRequirement(
                requirement_id="req-ev:29",
                evidence_type=EvidenceType.BLOCK_RELATIONS,
                target_scope=AssistantScope(block_id="block:1"),
            ),
            EvidenceRequirement(
                requirement_id="req-ev:30",
                evidence_type=EvidenceType.TEXT_OBSERVATIONS,
                target_scope=AssistantScope(page_id="page:1"),
            ),
            EvidenceRequirement(
                requirement_id="req-ev:31",
                evidence_type=EvidenceType.STRUCTURED_INTERPRETATIONS,
                target_scope=AssistantScope(page_id="page:1"),
            ),
            EvidenceRequirement(
                requirement_id="req-ev:32",
                evidence_type=EvidenceType.SEMANTIC_PAYLOAD,
                target_scope=AssistantScope(page_id="page:1"),
                include_payload=True,
                payload_ref="payload:1",
            ),
            EvidenceRequirement(
                requirement_id="req-ev:33",
                evidence_type=EvidenceType.CANDIDATE_RELATIONS,
                target_scope=AssistantScope(page_id="page:1"),
            ),
            EvidenceRequirement(
                requirement_id="req-ev:34",
                evidence_type=EvidenceType.SECTION_MATCHES,
                target_scope=AssistantScope(cross_section_id="section:1"),
            ),
        )
        plan = RetrievalPlanner().plan(make_result(*requirements), RetrievalPolicy())
        methods = {step.facade_method for step in plan.steps}
        self.assertTrue(methods.isdisjoint(self.FORBIDDEN_METHODS))


class RetrievalPlannerDedupePayloadLimitTests(unittest.TestCase):
    def test_identical_page_source_fact_requirements_merge_into_one_step(self):
        first = EvidenceRequirement(
            requirement_id="req-ev:40",
            evidence_type=EvidenceType.PAGE_SOURCE_FACTS,
            target_scope=AssistantScope(page_id="page:1"),
        )
        second = EvidenceRequirement(
            requirement_id="req-ev:41",
            evidence_type=EvidenceType.PAGE_SOURCE_FACTS,
            target_scope=AssistantScope(page_id="page:1"),
        )
        plan = RetrievalPlanner().plan(make_result(first, second), RetrievalPolicy())
        self.assertEqual(1, len(plan.steps))
        self.assertEqual(("req-ev:40", "req-ev:41"), plan.steps[0].requirement_ids)
        self.assertEqual(1, len(plan.dedupe_keys))

    def test_payload_defaults_off_even_when_policy_enables_payload(self):
        requirement = EvidenceRequirement(
            requirement_id="req-ev:42",
            evidence_type=EvidenceType.PAGE_SOURCE_FACTS,
            target_scope=AssistantScope(page_id="page:1"),
        )
        policy = RetrievalPolicy(include_payload_by_default=True)
        plan = RetrievalPlanner().plan(make_result(requirement), policy)
        self.assertEqual(1, len(plan.steps))
        self.assertFalse(plan.steps[0].include_payload)

    def test_explicit_payload_request_keeps_include_payload_true(self):
        requirement = EvidenceRequirement(
            requirement_id="req-ev:43",
            evidence_type=EvidenceType.SEMANTIC_PAYLOAD,
            target_scope=AssistantScope(page_id="page:1"),
            include_payload=True,
            payload_ref="payload:1",
        )
        policy = RetrievalPolicy(include_payload_by_default=False)
        plan = RetrievalPlanner().plan(make_result(requirement), policy)
        self.assertEqual(1, len(plan.steps))
        self.assertTrue(plan.steps[0].include_payload)

    def test_step_limit_is_capped_at_policy_max_limit(self):
        requirement = EvidenceRequirement(
            requirement_id="req-ev:44",
            evidence_type=EvidenceType.PROJECT_DRAWING_SETS,
            target_scope=AssistantScope(project_id="project:1"),
            limit=1000,
        )
        policy = RetrievalPolicy(default_limit=50, max_limit=100)
        plan = RetrievalPlanner().plan(make_result(requirement), policy)
        self.assertEqual(1, len(plan.steps))
        self.assertEqual(100, plan.steps[0].limit)


if __name__ == "__main__":
    unittest.main()
