"""Tests for shared 03/05 evidence gating rules (Task 20)."""

import unittest

from drawing_graph.assistant_evidence_rules import (
    allowed_fact_kinds,
    fact_kind_allowed,
    formal_review_required,
    scope_matches,
    status_acceptability,
)
from drawing_graph.assistant_models import (
    AssistantScope,
    EvidenceItem,
    EvidenceType,
    FactKind,
    ReasonCode,
)


class ScopeMatchTests(unittest.TestCase):
    def test_element_scope_matches(self):
        target = AssistantScope(page_id="page:1", element_id="element:1")
        self.assertTrue(scope_matches(target, AssistantScope(page_id="page:1", element_id="element:1")))

    def test_cross_page_does_not_match(self):
        target = AssistantScope(page_id="page:1", element_id="element:1")
        self.assertFalse(scope_matches(target, AssistantScope(page_id="page:2", element_id="element:1")))

    def test_cross_element_does_not_match(self):
        target = AssistantScope(page_id="page:1", element_id="element:1")
        self.assertFalse(scope_matches(target, AssistantScope(page_id="page:1", element_id="element:2")))

    def test_block_scope_matches_without_element(self):
        target = AssistantScope(page_id="page:1", block_id="block:1")
        self.assertTrue(scope_matches(target, AssistantScope(page_id="page:1", block_id="block:1")))


class FactKindGateTests(unittest.TestCase):
    def test_allowed_fact_kinds_by_evidence_type(self):
        self.assertEqual({FactKind.SOURCE_FACT}, allowed_fact_kinds(EvidenceType.PAGE_SOURCE_FACTS))
        self.assertEqual({FactKind.CANDIDATE_RELATION, FactKind.FORMAL_RELATION}, allowed_fact_kinds(EvidenceType.SECTION_MATCHES))

    def test_candidate_cannot_satisfy_source_fact(self):
        self.assertFalse(fact_kind_allowed(EvidenceType.PAGE_SOURCE_FACTS, FactKind.CANDIDATE_RELATION))

    def test_semantic_cannot_satisfy_formal(self):
        self.assertFalse(fact_kind_allowed(EvidenceType.SECTION_MATCHES, FactKind.SEMANTIC_OBSERVATION))


class StatusAcceptabilityTests(unittest.TestCase):
    def test_confirmed_observation_is_acceptable(self):
        self.assertIsNone(status_acceptability(FactKind.SEMANTIC_OBSERVATION, "confirmed"))

    def test_stale_returns_stale_reason(self):
        self.assertEqual(ReasonCode.EVIDENCE_STALE, status_acceptability(FactKind.SEMANTIC_OBSERVATION, "stale"))

    def test_insufficient_status_returns_reason(self):
        self.assertEqual(ReasonCode.STATUS_INSUFFICIENT, status_acceptability(FactKind.SEMANTIC_OBSERVATION, "partial"))

    def test_minimum_status_mismatch_returns_reason(self):
        self.assertEqual(
            ReasonCode.STATUS_INSUFFICIENT,
            status_acceptability(FactKind.CANDIDATE_RELATION, "candidate", minimum_status="confirmed"),
        )


class FormalGateTests(unittest.TestCase):
    def _item(self, evidence_id, fact_kind):
        return EvidenceItem(evidence_id=evidence_id, fact_kind=fact_kind, value={})

    def test_formal_present_does_not_require_review(self):
        self.assertFalse(
            formal_review_required(
                EvidenceType.SECTION_MATCHES,
                (self._item("e1", FactKind.FORMAL_RELATION),),
            )
        )

    def test_candidate_only_requires_review(self):
        self.assertTrue(
            formal_review_required(
                EvidenceType.SECTION_MATCHES,
                (self._item("e1", FactKind.CANDIDATE_RELATION),),
            )
        )

    def test_non_section_matches_never_requires_review(self):
        self.assertFalse(
            formal_review_required(
                EvidenceType.TEXT_OBSERVATIONS,
                (self._item("e1", FactKind.CANDIDATE_RELATION),),
            )
        )


if __name__ == "__main__":
    unittest.main()
