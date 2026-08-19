"""Tests for evidence lineage and stale policy (Task 22-23)."""

import unittest

from drawing_graph.assistant_evidence_lineage import (
    EvidenceLineageResolver,
    LineageResult,
    StalePolicy,
    StalePolicyLookupError,
    StalePolicyRegistry,
)
from drawing_graph.assistant_evidence_fusion_models import FusionEvidence, FusionMetadata
from drawing_graph.assistant_models import EvidenceItem, FactKind


def default_registry():
    return StalePolicyRegistry(
        policies=(
            StalePolicy(fact_kind="semantic_observation", policy_id="obs-stale", version="v1"),
            StalePolicy(fact_kind="semantic_interpretation", policy_id="interp-stale", version="v1"),
        )
    )


class StalePolicyRegistryTests(unittest.TestCase):
    def test_observation_and_interpretation_have_policies(self):
        registry = default_registry()
        self.assertTrue(registry.is_stale_eligible(FactKind.SEMANTIC_OBSERVATION))
        self.assertTrue(registry.is_stale_eligible(FactKind.SEMANTIC_INTERPRETATION))
        self.assertEqual("obs-stale", registry.policy_for(FactKind.SEMANTIC_OBSERVATION).policy_id)

    def test_source_derived_candidate_formal_diagnostic_are_excluded(self):
        registry = default_registry()
        for kind in (
            FactKind.SOURCE_FACT,
            FactKind.DERIVED_RELATION,
            FactKind.CANDIDATE_RELATION,
            FactKind.FORMAL_RELATION,
            FactKind.DIAGNOSTIC,
        ):
            with self.subTest(kind=kind):
                self.assertFalse(registry.is_stale_eligible(kind))

    def test_registry_rejects_non_eligible_policy(self):
        with self.assertRaises(ValueError):
            StalePolicyRegistry(
                policies=(StalePolicy(fact_kind="source_fact", policy_id="p", version="v1"),)
            )

    def test_registry_rejects_duplicate_policies(self):
        with self.assertRaises(ValueError):
            StalePolicyRegistry(
                policies=(
                    StalePolicy(fact_kind="semantic_observation", policy_id="a", version="v1"),
                    StalePolicy(fact_kind="semantic_observation", policy_id="b", version="v1"),
                )
            )

    def test_missing_policy_fails_closed(self):
        registry = StalePolicyRegistry()
        with self.assertRaises(StalePolicyLookupError):
            registry.policy_for(FactKind.SEMANTIC_OBSERVATION)

    def test_policy_is_pure_judgment(self):
        registry = default_registry()
        policy = registry.policy_for(FactKind.SEMANTIC_OBSERVATION)
        self.assertEqual("v1", policy.version)
        self.assertEqual("stale-policy-v1", registry.registry_version)


def make_fusion(
    evidence_id,
    family_key="family:1",
    cache_key="cache:1",
    fingerprint="fp:1",
    is_current=False,
    created_at=None,
    fact_kind="semantic_observation",
):
    return FusionEvidence(
        item=EvidenceItem(
            evidence_id=evidence_id,
            fact_kind=fact_kind,
            value={},
            created_at_or_version=created_at,
        ),
        metadata=FusionMetadata(
            evidence_family_key=family_key,
            cache_key=cache_key,
            content_fingerprint=fingerprint,
            is_current_for_request=is_current,
        ),
    )


class EvidenceLineageResolverTests(unittest.TestCase):
    def _resolver(self):
        return EvidenceLineageResolver(stale_policy_registry=default_registry())

    def test_same_cache_key_and_content_is_reuse_not_supersede(self):
        current = make_fusion("evidence:new", cache_key="cache:1", fingerprint="fp:1", is_current=True)
        old = make_fusion("evidence:old", cache_key="cache:1", fingerprint="fp:1", is_current=False)
        result = self._resolver().resolve((current, old))
        self.assertEqual(1, len(result.lineages))
        self.assertEqual((), result.lineages[0].superseded_evidence_ids)
        self.assertEqual((), result.plans)

    def test_different_cache_key_current_forms_supersede_plan(self):
        current = make_fusion("evidence:new", cache_key="cache:2", fingerprint="fp:2", is_current=True)
        old = make_fusion("evidence:old", cache_key="cache:1", fingerprint="fp:1", is_current=False)
        result = self._resolver().resolve((current, old))
        self.assertEqual(1, len(result.lineages))
        self.assertEqual(("evidence:old",), result.lineages[0].superseded_evidence_ids)
        self.assertEqual(1, len(result.plans))
        self.assertEqual(("evidence:old",), result.plans[0].evidence_ids)
        self.assertEqual("evidence:new", result.plans[0].superseded_by_evidence_id)

    def test_resolver_excludes_non_stale_eligible_kinds(self):
        source = make_fusion("evidence:source", fact_kind="source_fact", is_current=True)
        result = self._resolver().resolve((source,))
        self.assertEqual((), result.lineages)
        self.assertEqual((), result.plans)

    def test_resolver_does_not_modify_persistent_state(self):
        current = make_fusion("evidence:new", cache_key="cache:2", fingerprint="fp:2", is_current=True)
        old = make_fusion("evidence:old", cache_key="cache:1", fingerprint="fp:1", is_current=False)
        result = self._resolver().resolve((current, old))
        self.assertIsInstance(result, LineageResult)
        self.assertFalse(old.metadata.is_current_for_request)
        self.assertEqual("cache:1", old.metadata.cache_key)

    def test_output_is_deterministic(self):
        current = make_fusion("evidence:new", cache_key="cache:2", fingerprint="fp:2", is_current=True)
        old = make_fusion("evidence:old", cache_key="cache:1", fingerprint="fp:1", is_current=False)
        first = self._resolver().resolve((old, current))
        second = self._resolver().resolve((current, old))
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
