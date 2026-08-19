"""Tests for evidence normalization (Task 12-18)."""

import unittest

from drawing_graph.assistant_evidence_normalization import (
    ClaimCapabilityRegistry,
    ComparisonKeyBuilder,
    ContentFingerprintBuilder,
    EvidenceFamilyKeyBuilder,
    EvidenceNormalizer,
    FusionNormalizationContext,
    NormalizationResult,
    NormalizationRule,
    NormalizationRuleLookupError,
    NormalizationRuleRegistry,
    SectionLabelValueNormalizer,
)
from drawing_graph.assistant_evidence_fusion_models import ClaimCapability
from drawing_graph.assistant_models import (
    AssistantScope,
    EvidenceItem,
    FactKind,
    ReasonCode,
)


def rule(
    fact_kind="semantic_observation",
    task_type="element_text_observation",
    value_slot="text",
    rule_version="normalize-v1",
):
    return NormalizationRule(
        fact_kind=fact_kind,
        task_type=task_type,
        value_slot=value_slot,
        rule_version=rule_version,
    )


class NormalizationRegistryTests(unittest.TestCase):
    def test_registry_routes_by_fact_kind_task_type_and_slot(self):
        registry = NormalizationRuleRegistry(
            rules=(
                rule(),
                rule(task_type="block_semantic_identification", value_slot="summary"),
            )
        )
        matched = registry.lookup(
            "semantic_observation",
            "element_text_observation",
            "text",
        )
        self.assertEqual("normalize-v1", matched.rule_version)
        self.assertEqual(FactKind.SEMANTIC_OBSERVATION, matched.fact_kind)

    def test_registry_rejects_duplicate_rules(self):
        with self.assertRaises(ValueError):
            NormalizationRuleRegistry(rules=(rule(), rule()))

    def test_registry_rejects_empty_rule_version(self):
        with self.assertRaises(ValueError):
            NormalizationRule(rule_version="", fact_kind="semantic_observation", task_type="t", value_slot="text")

    def test_registry_rejects_unknown_value_slot(self):
        with self.assertRaises(ValueError):
            NormalizationRuleRegistry(
                rules=(rule(value_slot="not_a_real_slot"),)
            )

    def test_registry_rejects_unknown_fact_kind(self):
        with self.assertRaises(ValueError):
            NormalizationRule(fact_kind="not_a_fact_kind", task_type="t", value_slot="text", rule_version="v1")

    def test_registry_is_immutable(self):
        registry = NormalizationRuleRegistry(rules=(rule(),))
        self.assertEqual(1, len(registry.rules))
        with self.assertRaises(TypeError):
            registry.rules[("semantic_observation", "element_text_observation", "text")] = rule()

    def test_lookup_returns_stable_failure_for_missing_rule(self):
        registry = NormalizationRuleRegistry(rules=(rule(),))
        with self.assertRaises(NormalizationRuleLookupError):
            registry.lookup("semantic_observation", "element_text_observation", "summary")

    def test_registry_has_no_side_effects(self):
        registry = NormalizationRuleRegistry(rules=(rule(),))
        self.assertEqual("normalize-v1", registry.registry_version)
        self.assertIsInstance(registry.registry_version, str)


class ComparisonKeyTests(unittest.TestCase):
    def _builder(self):
        return ComparisonKeyBuilder()

    def test_same_input_produces_same_key(self):
        builder = self._builder()
        first = builder.build(AssistantScope(page_id="page:1"), "text", ("q1", "q2"))
        second = builder.build(AssistantScope(page_id="page:1"), "text", ("q1", "q2"))
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("comparison:"))

    def test_qualifier_order_does_not_change_key(self):
        builder = self._builder()
        first = builder.build(AssistantScope(page_id="page:1"), "text", ("q1", "q2"))
        second = builder.build(AssistantScope(page_id="page:1"), "text", ("q2", "q1"))
        self.assertEqual(first, second)

    def test_different_scope_produces_different_key(self):
        builder = self._builder()
        first = builder.build(AssistantScope(page_id="page:1"), "text")
        second = builder.build(AssistantScope(page_id="page:2"), "text")
        self.assertNotEqual(first, second)

    def test_different_slot_produces_different_key(self):
        builder = self._builder()
        first = builder.build(AssistantScope(page_id="page:1"), "text")
        second = builder.build(AssistantScope(page_id="page:1"), "summary")
        self.assertNotEqual(first, second)

    def test_different_qualifiers_produce_different_key(self):
        builder = self._builder()
        first = builder.build(AssistantScope(page_id="page:1"), "relation", ("outgoing",))
        second = builder.build(AssistantScope(page_id="page:1"), "relation", ("incoming",))
        self.assertNotEqual(first, second)

    def test_key_excludes_confidence_secret_and_payload(self):
        builder = self._builder()
        key = builder.build(AssistantScope(page_id="page:1"), "text")
        lowered = key.lower()
        self.assertNotIn("confidence", lowered)
        self.assertNotIn("secret", lowered)
        self.assertNotIn("payload", lowered)
        self.assertNotIn("c:\\", lowered)


class EvidenceFamilyKeyTests(unittest.TestCase):
    def test_family_key_only_uses_stable_target_task_slot_scope(self):
        builder = EvidenceFamilyKeyBuilder()
        key = builder.build("target:1", "element_text_observation", "text", "default")
        self.assertTrue(key.startswith("family:"))
        self.assertNotIn("image", key)
        self.assertNotIn("model", key)
        self.assertNotIn("prompt", key)
        self.assertNotIn("contract", key)

    def test_family_key_is_stable_for_same_inputs(self):
        builder = EvidenceFamilyKeyBuilder()
        first = builder.build("target:1", "element_text_observation", "text")
        second = builder.build("target:1", "element_text_observation", "text")
        self.assertEqual(first, second)

    def test_family_key_changes_with_target_or_slot(self):
        builder = EvidenceFamilyKeyBuilder()
        base = builder.build("target:1", "element_text_observation", "text")
        self.assertNotEqual(base, builder.build("target:2", "element_text_observation", "text"))
        self.assertNotEqual(base, builder.build("target:1", "element_text_observation", "summary"))


class ContentFingerprintTests(unittest.TestCase):
    def test_same_input_produces_same_fingerprint(self):
        builder = ContentFingerprintBuilder()
        first = builder.build("semantic_observation", "comparison:1", {"text": "A1"})
        second = builder.build("semantic_observation", "comparison:1", {"text": "A1"})
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("fingerprint:"))

    def test_dict_key_order_does_not_change_fingerprint(self):
        builder = ContentFingerprintBuilder()
        first = builder.build("semantic_observation", "comparison:1", {"a": 1, "b": 2})
        second = builder.build("semantic_observation", "comparison:1", {"b": 2, "a": 1})
        self.assertEqual(first, second)

    def test_fact_kind_change_changes_fingerprint(self):
        builder = ContentFingerprintBuilder()
        first = builder.build("semantic_observation", "comparison:1", {"text": "A1"})
        second = builder.build("semantic_interpretation", "comparison:1", {"text": "A1"})
        self.assertNotEqual(first, second)

    def test_normalized_value_change_changes_fingerprint(self):
        builder = ContentFingerprintBuilder()
        first = builder.build("semantic_observation", "comparison:1", {"text": "A1"})
        second = builder.build("semantic_observation", "comparison:1", {"text": "A2"})
        self.assertNotEqual(first, second)

    def test_comparison_key_change_changes_fingerprint(self):
        builder = ContentFingerprintBuilder()
        first = builder.build("semantic_observation", "comparison:1", {"text": "A1"})
        second = builder.build("semantic_observation", "comparison:2", {"text": "A1"})
        self.assertNotEqual(first, second)

    def test_source_fingerprint_participates(self):
        builder = ContentFingerprintBuilder()
        first = builder.build("semantic_observation", "comparison:1", {"text": "A1"}, source_fingerprint="src:1")
        second = builder.build("semantic_observation", "comparison:1", {"text": "A1"}, source_fingerprint="src:2")
        self.assertNotEqual(first, second)


class ClaimCapabilityRegistryTests(unittest.TestCase):
    def test_seven_capability_mapping_matches_design(self):
        registry = ClaimCapabilityRegistry()
        self.assertEqual(
            (ClaimCapability.IDENTITY_AND_LOCATION,),
            registry.capabilities(FactKind.SOURCE_FACT),
        )
        self.assertEqual(
            (ClaimCapability.CONFIRMED_RELATION,),
            registry.capabilities(FactKind.FORMAL_RELATION),
        )
        self.assertEqual(
            (ClaimCapability.RULE_DERIVED_CONTEXT,),
            registry.capabilities(FactKind.DERIVED_RELATION),
        )
        self.assertEqual(
            (ClaimCapability.OBSERVED_TEXT_OR_SYMBOL,),
            registry.capabilities(FactKind.SEMANTIC_OBSERVATION),
        )
        self.assertEqual(
            (ClaimCapability.SEMANTIC_MEANING,),
            registry.capabilities(FactKind.SEMANTIC_INTERPRETATION),
        )
        self.assertEqual(
            (ClaimCapability.POSSIBLE_RELATION,),
            registry.capabilities(FactKind.CANDIDATE_RELATION),
        )
        self.assertEqual(
            (ClaimCapability.RUNTIME_OR_CACHE_STATUS,),
            registry.capabilities(FactKind.DIAGNOSTIC),
        )

    def test_candidate_can_only_support_possible_relation(self):
        registry = ClaimCapabilityRegistry()
        capabilities = registry.capabilities(FactKind.CANDIDATE_RELATION)
        self.assertEqual((ClaimCapability.POSSIBLE_RELATION,), capabilities)
        self.assertNotIn(ClaimCapability.CONFIRMED_RELATION, capabilities)

    def test_diagnostic_can_only_support_runtime_or_cache_status(self):
        registry = ClaimCapabilityRegistry()
        capabilities = registry.capabilities(FactKind.DIAGNOSTIC)
        self.assertEqual((ClaimCapability.RUNTIME_OR_CACHE_STATUS,), capabilities)
        self.assertNotIn(ClaimCapability.IDENTITY_AND_LOCATION, capabilities)

    def test_unregistered_fact_kind_fails_closed_to_empty(self):
        registry = ClaimCapabilityRegistry()
        self.assertEqual((), registry.capabilities(FactKind.UNSUPPORTED))

    def test_free_text_fact_kind_is_rejected(self):
        registry = ClaimCapabilityRegistry()
        with self.assertRaises(ValueError):
            registry.capabilities("formal_relation_is_confirmed")


def normalization_registry():
    return NormalizationRuleRegistry(
        rules=(
            NormalizationRule(
                fact_kind="semantic_observation",
                task_type="element_text_observation",
                value_slot="text",
                rule_version="normalize-v1",
            ),
            NormalizationRule(
                fact_kind="semantic_interpretation",
                task_type="block_semantic_identification",
                value_slot="summary",
                rule_version="normalize-v1",
            ),
            NormalizationRule(
                fact_kind="candidate_relation",
                task_type="relation_evidence_extraction",
                value_slot="relation",
                rule_version="normalize-v1",
            ),
        )
    )


def make_normalizer():
    return EvidenceNormalizer(rule_registry=normalization_registry())


def observation_item(**overrides):
    values = dict(
        evidence_id="evidence:obs:1",
        fact_kind=FactKind.SEMANTIC_OBSERVATION,
        scope=AssistantScope(page_id="page:1", element_id="element:1"),
        value={
            "raw_text": "  A1  ",
            "normalized_text": "A1",
            "bbox": {"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
        },
        evidence_metadata={"task_type": "element_text_observation"},
    )
    values.update(overrides)
    return EvidenceItem(**values)


def candidate_item(**overrides):
    values = dict(
        evidence_id="evidence:candidate:1",
        fact_kind=FactKind.CANDIDATE_RELATION,
        value={
            "relation_type": "connected_to",
            "source_target_id": "target:1",
            "supporting_target_ids": ("target:2",),
        },
    )
    values.update(overrides)
    return EvidenceItem(**values)


class EvidenceNormalizerTests(unittest.TestCase):
    def test_text_normalization_does_not_overwrite_original_value(self):
        item = observation_item()
        result = make_normalizer().normalize((item,))
        self.assertEqual(1, len(result.normalized))
        fusion = result.normalized[0]
        self.assertEqual("  A1  ", fusion.item.value["raw_text"])
        self.assertEqual("A1", fusion.metadata.normalized_value["text"])

    def test_bbox_normalizes_to_four_coordinates(self):
        item = observation_item()
        fusion = make_normalizer().normalize((item,)).normalized[0]
        self.assertEqual(
            {"x_min": 1.0, "y_min": 2.0, "x_max": 3.0, "y_max": 4.0},
            fusion.metadata.normalized_value["bbox"],
        )

    def test_relation_normalizes_to_subject_predicate_object(self):
        item = candidate_item()
        fusion = make_normalizer().normalize((item,)).normalized[0]
        self.assertEqual(
            {"subject": "target:1", "predicate": "connected_to", "objects": ("target:2",)},
            fusion.metadata.normalized_value,
        )

    def test_output_fills_all_keys_and_capabilities(self):
        item = candidate_item()
        fusion = make_normalizer().normalize((item,)).normalized[0]
        metadata = fusion.metadata
        self.assertIsNotNone(metadata.comparison_key)
        self.assertIsNotNone(metadata.evidence_family_key)
        self.assertIsNotNone(metadata.content_fingerprint)
        self.assertEqual((ClaimCapability.POSSIBLE_RELATION,), metadata.claim_capabilities)
        self.assertEqual("normalize-v1", metadata.normalization_rule_version)

    def test_unormalizable_relation_is_isolated_preserving_id(self):
        item = candidate_item(value={"relation_type": "connected_to"})
        result = make_normalizer().normalize((item,))
        self.assertEqual((), result.normalized)
        self.assertEqual(1, len(result.isolated))
        self.assertEqual("evidence:candidate:1", result.isolated[0].evidence_id)
        self.assertEqual((ReasonCode.EVIDENCE_NORMALIZATION_FAILED,), result.reason_codes)

    def test_reversed_relation_gets_different_comparison_key(self):
        first = candidate_item()
        second = candidate_item(
            evidence_id="evidence:candidate:2",
            value={
                "relation_type": "connected_to",
                "source_target_id": "target:2",
                "supporting_target_ids": ("target:1",),
            },
        )
        normalizer = make_normalizer()
        first_key = normalizer.normalize((first,)).normalized[0].metadata.comparison_key
        second_key = normalizer.normalize((second,)).normalized[0].metadata.comparison_key
        self.assertNotEqual(first_key, second_key)


class SectionNormalizationReuseTests(unittest.TestCase):
    def _normalizer(self):
        return SectionLabelValueNormalizer()

    def test_symbol_system_classifications_match_existing_rules(self):
        normalizer = self._normalizer()
        self.assertEqual("alphabetic", normalizer.normalize("A", "A")["symbol_system"])
        self.assertEqual("roman", normalizer.normalize("I", "I")["symbol_system"])
        self.assertEqual("numeric", normalizer.normalize("1", "1")["symbol_system"])
        self.assertEqual("alphanumeric", normalizer.normalize("A1", "A1")["symbol_system"])
        self.assertEqual("unknown", normalizer.normalize("??", "??")["symbol_system"])

    def test_ascii_roman_fullwidth_and_numeric_do_not_merge(self):
        normalizer = self._normalizer()
        ascii_key = normalizer.normalize("I", "I")["normalized_key"]
        fullwidth_key = normalizer.normalize("Ⅰ", "Ⅰ")["normalized_key"]
        numeric_key = normalizer.normalize("1", "1")["normalized_key"]
        self.assertEqual("SECTION_ROMAN_I", ascii_key)
        self.assertEqual("SECTION_ROMAN_Ⅰ", fullwidth_key)
        self.assertEqual("SECTION_NUMERIC_1", numeric_key)
        self.assertEqual(3, len({ascii_key, fullwidth_key, numeric_key}))

    def test_original_labels_and_symbol_system_are_preserved(self):
        normalizer = self._normalizer()
        result = normalizer.normalize("A - A", "A-A")
        self.assertEqual("A - A", result["start_label"])
        self.assertEqual("A-A", result["end_label"])
        self.assertEqual("alphabetic", result["symbol_system"])
        self.assertEqual("SECTION_ALPHA_A", result["normalized_key"])

    def test_mismatched_endpoints_are_not_deterministic(self):
        normalizer = self._normalizer()
        result = normalizer.normalize("A", "B")
        self.assertFalse(result["deterministic"])
        self.assertIsNone(result["normalized_key"])


if __name__ == "__main__":
    unittest.main()
