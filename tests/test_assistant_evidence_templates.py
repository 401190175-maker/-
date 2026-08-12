"""Tests for evidence requirement template factory."""

import unittest

from drawing_graph.assistant_evidence_templates import EvidenceRequirementFactory
from drawing_graph.assistant_models import (
    AssistantRequest,
    AssistantScope,
    EvidenceType,
    FreshnessRequirement,
)


class EvidenceRequirementFactoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.factory = EvidenceRequirementFactory()
        self.request = AssistantRequest(request_id="req:1", question="q")

    def evidence_types(self, question_type: str, scope: AssistantScope):
        return tuple(
            requirement.evidence_type
            for requirement in self.factory.build(question_type, scope, self.request)
        )

    def test_page_summary_generates_page_source_facts(self):
        scope = AssistantScope(page_id="page:1")
        self.assertEqual(
            (EvidenceType.PAGE_SOURCE_FACTS,),
            self.evidence_types("page_summary", scope),
        )

    def test_block_relations_generates_trace_and_relations(self):
        scope = AssistantScope(block_id="block:1")
        self.assertEqual(
            (EvidenceType.BLOCK_TRACE, EvidenceType.BLOCK_RELATIONS),
            self.evidence_types("block_relations", scope),
        )

    def test_candidate_relations_generates_candidate_requirement(self):
        scope = AssistantScope(page_id="page:1")
        self.assertEqual(
            (EvidenceType.CANDIDATE_RELATIONS,),
            self.evidence_types("candidate_relations", scope),
        )

    def test_section_matches_generates_section_requirement(self):
        scope = AssistantScope(cross_section_id="cross_section:1")
        self.assertEqual(
            (EvidenceType.SECTION_MATCHES,),
            self.evidence_types("section_matches", scope),
        )

    def test_block_semantic_identification_allows_model_generation_only_for_interpretations(self):
        scope = AssistantScope(block_id="block:1")
        requirements = self.factory.build(
            "block_semantic_identification",
            scope,
            self.request,
        )
        by_type = {requirement.evidence_type: requirement for requirement in requirements}
        self.assertIn(EvidenceType.BLOCK_TRACE, by_type)
        self.assertIn(EvidenceType.STRUCTURED_INTERPRETATIONS, by_type)
        self.assertFalse(by_type[EvidenceType.BLOCK_TRACE].allow_model_generation)
        self.assertTrue(
            by_type[EvidenceType.STRUCTURED_INTERPRETATIONS].allow_model_generation
        )

    def test_element_text_or_meaning_generates_source_and_observations(self):
        scope = AssistantScope(element_id="element:1")
        self.assertEqual(
            (EvidenceType.PAGE_SOURCE_FACTS, EvidenceType.TEXT_OBSERVATIONS),
            self.evidence_types("element_text_or_meaning", scope),
        )

    def test_observation_requirement_declares_minimum_status_and_generation(self):
        scope = AssistantScope(element_id="element:1")
        requirements = self.factory.build(
            "element_text_or_meaning",
            scope,
            self.request,
        )
        observation = next(
            requirement
            for requirement in requirements
            if requirement.evidence_type is EvidenceType.TEXT_OBSERVATIONS
        )
        source_fact = next(
            requirement
            for requirement in requirements
            if requirement.evidence_type is EvidenceType.PAGE_SOURCE_FACTS
        )
        self.assertTrue(observation.allow_model_generation)
        self.assertEqual("confirmed", observation.minimum_status)
        self.assertFalse(source_fact.allow_model_generation)

    def test_observation_requirement_carries_combined_freshness_constraints(self):
        scope = AssistantScope(element_id="element:1")
        requirements = self.factory.build(
            "element_text_or_meaning",
            scope,
            self.request,
        )
        observation = next(
            requirement
            for requirement in requirements
            if requirement.evidence_type is EvidenceType.TEXT_OBSERVATIONS
        )
        freshness = observation.freshness_requirement
        self.assertIsInstance(freshness, FreshnessRequirement)
        self.assertTrue(freshness.require_current_image)
        self.assertTrue(freshness.require_current_bbox)

    def test_table_caption_status_generates_page_source_facts(self):
        scope = AssistantScope(table_id="table:1")
        self.assertEqual(
            (EvidenceType.PAGE_SOURCE_FACTS,),
            self.evidence_types("table_caption_status", scope),
        )

    def test_interpretation_requirement_declares_contract_freshness(self):
        scope = AssistantScope(block_id="block:1")
        requirements = self.factory.build(
            "block_semantic_identification",
            scope,
            self.request,
        )
        interpretation = next(
            requirement
            for requirement in requirements
            if requirement.evidence_type is EvidenceType.STRUCTURED_INTERPRETATIONS
        )
        self.assertEqual("interpreted", interpretation.minimum_status)
        self.assertTrue(interpretation.allow_model_generation)
        self.assertTrue(interpretation.freshness_requirement.require_current_contract)

    def test_section_matches_express_both_observation_and_relation_requirements(self):
        scope = AssistantScope(cross_section_id="section:1", page_id="page:1")
        requirements = self.factory.build(
            "section_matches",
            scope,
            self.request,
        )
        self.assertEqual(
            (EvidenceType.TEXT_OBSERVATIONS, EvidenceType.SECTION_MATCHES),
            self.evidence_types("section_matches", scope),
        )
        observation = next(
            requirement
            for requirement in requirements
            if requirement.evidence_type is EvidenceType.TEXT_OBSERVATIONS
        )
        relation = next(
            requirement
            for requirement in requirements
            if requirement.evidence_type is EvidenceType.SECTION_MATCHES
        )
        self.assertTrue(observation.allow_model_generation)
        self.assertFalse(relation.allow_model_generation)

    def test_section_matches_without_page_keeps_relation_requirement(self):
        scope = AssistantScope(cross_section_id="section:1")
        requirements = self.factory.build(
            "section_matches",
            scope,
            self.request,
        )
        self.assertEqual(
            (EvidenceType.SECTION_MATCHES,),
            self.evidence_types("section_matches", scope),
        )
        self.assertFalse(requirements[0].allow_model_generation)

    def test_requirement_ids_are_stable_and_defaults_are_safe(self):
        scope = AssistantScope(page_id="page:1")
        requirements = self.factory.build("page_summary", scope, self.request)
        self.assertEqual(
            "understanding:page_summary:page_source_facts",
            requirements[0].requirement_id,
        )
        self.assertTrue(requirements[0].required)
        self.assertFalse(requirements[0].include_payload)

    def test_types_without_template_return_empty(self):
        scope = AssistantScope()
        self.assertEqual((), self.factory.build("comparison", scope, self.request))
        self.assertEqual(
            (),
            self.factory.build("clarification_required", scope, self.request),
        )
        self.assertEqual(
            (),
            self.factory.build("unknown_or_unsupported", scope, self.request),
        )


if __name__ == "__main__":
    unittest.main()
