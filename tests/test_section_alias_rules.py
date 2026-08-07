import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.section_alias_rules import (
    SectionAliasRuleStatus,
    SectionAliasRuleStore,
    SectionLabelAliasRule,
)
from drawing_graph.section_label_normalization import SectionSymbolSystem


def rule(
    alias_rule_id="alias:1",
    scope="page:1",
    status="confirmed",
    from_system="numeric",
    to_system="alphabetic",
):
    return SectionLabelAliasRule(
        alias_rule_id=alias_rule_id,
        alias_rule_version="v1",
        scope=scope,
        from_symbol_system=from_system,
        to_symbol_system=to_system,
        mapping={"SECTION_NUMERIC_1": "SECTION_ALPHA_A"},
        status=status,
        evidence_ref="evidence:1",
        source_system="design-manual-2024",
        confirmed_by="reviewer:1",
        created_at="2026-08-06T00:00:00Z",
    )


class SectionAliasRulesTest(unittest.TestCase):
    def test_rule_contains_scope_version_status_and_evidence(self):
        alias_rule = rule()

        self.assertEqual("alias:1", alias_rule.alias_rule_id)
        self.assertEqual("v1", alias_rule.alias_rule_version)
        self.assertEqual("page:1", alias_rule.scope)
        self.assertEqual(SectionSymbolSystem.NUMERIC, alias_rule.from_symbol_system)
        self.assertEqual(SectionSymbolSystem.ALPHABETIC, alias_rule.to_symbol_system)
        self.assertEqual("SECTION_ALPHA_A", alias_rule.mapping["SECTION_NUMERIC_1"])
        self.assertEqual("evidence:1", alias_rule.evidence_ref)
        self.assertEqual(SectionAliasRuleStatus.CONFIRMED, alias_rule.status)

    def test_only_confirmed_rules_with_matching_scope_participate(self):
        store = SectionAliasRuleStore(
            (
                rule(),
                rule("alias:revoked", status="revoked"),
                rule("alias:ambiguous", status="ambiguous"),
                rule("alias:other-page", scope="page:2"),
            )
        )

        applicable = store.find_applicable(
            scope="page:1",
            from_symbol_system="numeric",
            to_symbol_system="alphabetic",
        )

        self.assertEqual(("alias:1",), tuple(item.alias_rule_id for item in applicable))
        self.assertTrue(store.can_match(scope="page:1", from_symbol_system="numeric", to_symbol_system="alphabetic"))
        self.assertFalse(store.can_match(scope="page:3", from_symbol_system="numeric", to_symbol_system="alphabetic"))

    def test_global_scope_rule_applies_to_any_scope(self):
        store = SectionAliasRuleStore((rule(scope="*"),))

        self.assertTrue(store.can_match(scope="page:9", from_symbol_system="numeric", to_symbol_system="alphabetic"))

    def test_rejects_invalid_status_system_and_empty_mapping(self):
        with self.assertRaises(ValueError):
            rule(status="unknown_status")
        with self.assertRaises(ValueError):
            rule(from_system="unknown")
        with self.assertRaises(ValueError):
            SectionLabelAliasRule(
                alias_rule_id="alias:2",
                alias_rule_version="v1",
                scope="page:1",
                from_symbol_system="numeric",
                to_symbol_system="alphabetic",
                mapping={},
            )
        with self.assertRaises(ValueError):
            rule(from_system="numeric", to_system="numeric")

    def test_store_never_creates_graph_nodes(self):
        store = SectionAliasRuleStore((rule(),))

        self.assertFalse(hasattr(store, "driver"))
        self.assertFalse(hasattr(store, "labels"))
        self.assertFalse(hasattr(store._rules["alias:1"], "labels"))
        self.assertNotIn("RecognitionRun", repr(store).lower())


if __name__ == "__main__":
    unittest.main()
