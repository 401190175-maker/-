"""Tests for deterministic evidence conflict detection (Task 24-27)."""

import unittest

from drawing_graph.assistant_evidence_conflicts import (
    EvidenceConflictDetector,
    build_conflict_id,
)
from drawing_graph.assistant_evidence_fusion_models import (
    ConflictSeverity,
    ConflictType,
    FusionEvidence,
    FusionMetadata,
)
from drawing_graph.assistant_models import EvidenceItem, FactKind


def make_fusion(evidence_id, fact_kind="semantic_observation", comparison_key="comparison:1", value=None):
    return FusionEvidence(
        item=EvidenceItem(evidence_id=evidence_id, fact_kind=fact_kind, value={}),
        metadata=FusionMetadata(
            comparison_key=comparison_key,
            normalized_value=value if value is not None else {"text": evidence_id},
            content_fingerprint=f"fp:{evidence_id}",
        ),
    )


class ConflictGroupingTests(unittest.TestCase):
    def test_conflict_id_is_deterministic(self):
        first = build_conflict_id("comparison:1", ConflictType.HARD_CONFLICT, ("e:a", "e:b"))
        second = build_conflict_id("comparison:1", ConflictType.HARD_CONFLICT, ("e:a", "e:b"))
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("conflict:"))

    def test_conflict_id_sorts_evidence_ids(self):
        first = build_conflict_id("comparison:1", ConflictType.HARD_CONFLICT, ("e:a", "e:b"))
        second = build_conflict_id("comparison:1", ConflictType.HARD_CONFLICT, ("e:b", "e:a"))
        self.assertEqual(first, second)

    def test_conflict_id_changes_with_type_and_key(self):
        base = build_conflict_id("comparison:1", ConflictType.HARD_CONFLICT, ("e:a", "e:b"))
        self.assertNotEqual(base, build_conflict_id("comparison:1", ConflictType.PEER_CONFLICT, ("e:a", "e:b")))
        self.assertNotEqual(base, build_conflict_id("comparison:2", ConflictType.HARD_CONFLICT, ("e:a", "e:b")))

    def test_conflict_id_excludes_confidence(self):
        conflict_id = build_conflict_id("comparison:1", ConflictType.HARD_CONFLICT, ("e:a", "e:b"))
        self.assertNotIn("confidence", conflict_id.lower())

    def test_different_comparison_key_are_not_grouped(self):
        detector = EvidenceConflictDetector()
        groups = detector.comparison_groups(
            (
                make_fusion("e:a", comparison_key="comparison:1"),
                make_fusion("e:b", comparison_key="comparison:2"),
            )
        )
        self.assertEqual(2, len(groups))

    def test_same_comparison_key_are_grouped(self):
        detector = EvidenceConflictDetector()
        groups = detector.comparison_groups(
            (
                make_fusion("e:a", comparison_key="comparison:1"),
                make_fusion("e:b", comparison_key="comparison:1"),
            )
        )
        self.assertEqual(1, len(groups))
        self.assertEqual(("e:a", "e:b"), groups[0][1])

    def test_detector_rejects_invalid_limits(self):
        with self.assertRaises(ValueError):
            EvidenceConflictDetector(max_group_size=0)
        with self.assertRaises(ValueError):
            EvidenceConflictDetector(max_total_conflicts=-1)


class SourceDerivedConflictMatrixTests(unittest.TestCase):
    def test_source_source_same_value_no_conflict(self):
        detector = EvidenceConflictDetector()
        records = detector.detect(
            (
                make_fusion("e:a", fact_kind="source_fact", value={"page_id": "page:1"}),
                make_fusion("e:b", fact_kind="source_fact", value={"page_id": "page:1"}),
            )
        )
        self.assertEqual((), records)

    def test_source_source_different_value_is_blocking_hard_conflict(self):
        detector = EvidenceConflictDetector()
        records = detector.detect(
            (
                make_fusion("e:a", fact_kind="source_fact", value={"page_id": "page:1"}),
                make_fusion("e:b", fact_kind="source_fact", value={"page_id": "page:2"}),
            )
        )
        self.assertEqual(1, len(records))
        self.assertEqual(ConflictType.HARD_CONFLICT, records[0].conflict_type)
        self.assertEqual(ConflictSeverity.BLOCKING, records[0].severity)
        self.assertTrue(records[0].blocks_answer)

    def test_source_derived_is_complementary_by_default(self):
        detector = EvidenceConflictDetector()
        records = detector.detect(
            (
                make_fusion("e:a", fact_kind="source_fact", value={"page_id": "page:1"}),
                make_fusion("e:b", fact_kind="derived_relation", value={"subject": "a", "predicate": "p", "objects": ("b",)}),
            )
        )
        self.assertEqual((), records)

    def test_source_derived_negation_is_rule_conflict(self):
        detector = EvidenceConflictDetector()
        records = detector.detect(
            (
                make_fusion("e:a", fact_kind="source_fact", value={"page_id": "page:1"}),
                make_fusion("e:b", fact_kind="derived_relation", value={"subject": "a", "predicate": "p", "objects": (), "negates": True}),
            )
        )
        self.assertEqual(1, len(records))
        self.assertEqual(ConflictType.RULE_CONFLICT, records[0].conflict_type)

    def test_derived_derived_different_value_is_rule_conflict(self):
        detector = EvidenceConflictDetector()
        records = detector.detect(
            (
                make_fusion("e:a", fact_kind="derived_relation", value={"subject": "a", "predicate": "p", "objects": ("b",)}),
                make_fusion("e:b", fact_kind="derived_relation", value={"subject": "a", "predicate": "p", "objects": ("c",)}),
            )
        )
        self.assertEqual(1, len(records))
        self.assertEqual(ConflictType.RULE_CONFLICT, records[0].conflict_type)

    def test_source_facts_are_never_overwritten(self):
        detector = EvidenceConflictDetector()
        source = make_fusion("e:a", fact_kind="source_fact", value={"page_id": "page:1"})
        derived = make_fusion("e:b", fact_kind="derived_relation", value={"subject": "a", "predicate": "p", "objects": (), "negates": True})
        records = detector.detect((source, derived))
        self.assertEqual(1, len(records))
        self.assertIn("e:a", records[0].evidence_ids)


class SemanticConflictMatrixTests(unittest.TestCase):
    def test_model_vs_source_conflict(self):
        detector = EvidenceConflictDetector()
        records = detector.detect(
            (
                make_fusion("e:a", fact_kind="source_fact", value={"page_id": "page:1"}),
                make_fusion("e:b", fact_kind="semantic_observation", value={"text": "A1"}),
            )
        )
        self.assertEqual(1, len(records))
        self.assertEqual(ConflictType.MODEL_VS_SOURCE, records[0].conflict_type)

    def test_semantic_vs_rule_conflict(self):
        detector = EvidenceConflictDetector()
        records = detector.detect(
            (
                make_fusion("e:a", fact_kind="derived_relation", value={"subject": "a", "predicate": "p", "objects": ("b",)}),
                make_fusion("e:b", fact_kind="semantic_interpretation", value={"summary": "x"}),
            )
        )
        types = [record.conflict_type for record in records]
        self.assertIn(ConflictType.SEMANTIC_VS_RULE, types)

    def test_observation_peer_conflict_on_different_text(self):
        detector = EvidenceConflictDetector()
        records = detector.detect(
            (
                make_fusion("e:a", fact_kind="semantic_observation", value={"text": "A1"}),
                make_fusion("e:b", fact_kind="semantic_observation", value={"text": "A2"}),
            )
        )
        peer_records = [record for record in records if record.conflict_type is ConflictType.PEER_CONFLICT]
        self.assertEqual(1, len(peer_records))
        self.assertFalse(peer_records[0].blocks_answer)

    def test_interpretation_peer_conflict_on_different_value(self):
        detector = EvidenceConflictDetector()
        records = detector.detect(
            (
                make_fusion("e:a", fact_kind="semantic_interpretation", value={"summary": "x"}),
                make_fusion("e:b", fact_kind="semantic_interpretation", value={"summary": "y"}),
            )
        )
        peer_records = [record for record in records if record.conflict_type is ConflictType.PEER_CONFLICT]
        self.assertEqual(1, len(peer_records))

    def test_interpretation_without_observation_support_is_support_conflict(self):
        detector = EvidenceConflictDetector()
        interp = FusionEvidence(
            item=EvidenceItem(
                evidence_id="interp:1",
                fact_kind="semantic_interpretation",
                value={},
                evidence_metadata={"supported_by_observation_ids": ()},
            ),
            metadata=FusionMetadata(
                comparison_key="comparison:1",
                normalized_value={"summary": "x"},
                content_fingerprint="fp:1",
            ),
        )
        records = detector.detect((interp,))
        self.assertEqual(1, len(records))
        self.assertEqual(ConflictType.SUPPORT_CONFLICT, records[0].conflict_type)
        self.assertEqual(("interp:1",), records[0].evidence_ids)

    def test_interpretation_with_observation_support_has_no_support_conflict(self):
        detector = EvidenceConflictDetector()
        observation = make_fusion("obs:1", fact_kind="semantic_observation", value={"text": "A1"})
        interp = FusionEvidence(
            item=EvidenceItem(
                evidence_id="interp:1",
                fact_kind="semantic_interpretation",
                value={},
                evidence_metadata={"supported_by_observation_ids": ("obs:1",)},
            ),
            metadata=FusionMetadata(
                comparison_key="comparison:1",
                normalized_value={"summary": "x"},
                content_fingerprint="fp:1",
            ),
        )
        records = detector.detect((observation, interp))
        support_records = [r for r in records if r.conflict_type is ConflictType.SUPPORT_CONFLICT]
        self.assertEqual([], support_records)

    def test_high_confidence_semantic_does_not_override_source(self):
        detector = EvidenceConflictDetector()
        source = make_fusion("e:a", fact_kind="source_fact", value={"page_id": "page:1"})
        observation = make_fusion("e:b", fact_kind="semantic_observation", value={"text": "A1"})
        records = detector.detect((source, observation))
        self.assertEqual(1, len(records))
        self.assertEqual(ConflictType.MODEL_VS_SOURCE, records[0].conflict_type)
        self.assertIn("e:a", records[0].evidence_ids)


class RelationDiagnosticConflictMatrixTests(unittest.TestCase):
    def test_candidate_ambiguity_on_multiple_targets(self):
        detector = EvidenceConflictDetector()
        records = detector.detect(
            (
                make_fusion("e:a", fact_kind="candidate_relation", value={"subject": "a", "predicate": "p", "objects": ("b",)}),
                make_fusion("e:b", fact_kind="candidate_relation", value={"subject": "a", "predicate": "p", "objects": ("c",)}),
            )
        )
        ambiguity = [r for r in records if r.conflict_type is ConflictType.CANDIDATE_AMBIGUITY]
        self.assertEqual(1, len(ambiguity))
        self.assertFalse(ambiguity[0].blocks_answer)

    def test_candidate_and_formal_coexist_without_conflict(self):
        detector = EvidenceConflictDetector()
        records = detector.detect(
            (
                make_fusion("e:a", fact_kind="candidate_relation", value={"subject": "a", "predicate": "p", "objects": ("b",)}),
                make_fusion("e:b", fact_kind="formal_relation", value={"subject": "a", "predicate": "p", "objects": ("b",)}),
            )
        )
        self.assertEqual((), records)

    def test_formal_formal_exclusive_is_critical_integrity_conflict(self):
        detector = EvidenceConflictDetector()
        records = detector.detect(
            (
                make_fusion("e:a", fact_kind="formal_relation", value={"subject": "a", "predicate": "p", "objects": ("b",)}),
                make_fusion("e:b", fact_kind="formal_relation", value={"subject": "a", "predicate": "p", "objects": ("c",)}),
            )
        )
        self.assertEqual(1, len(records))
        self.assertEqual(ConflictType.CRITICAL_INTEGRITY_CONFLICT, records[0].conflict_type)
        self.assertEqual(ConflictSeverity.CRITICAL, records[0].severity)
        self.assertTrue(records[0].blocks_answer)

    def test_formal_semantic_does_not_revoke_formal(self):
        detector = EvidenceConflictDetector()
        records = detector.detect(
            (
                make_fusion("e:a", fact_kind="formal_relation", value={"subject": "a", "predicate": "p", "objects": ("b",)}),
                make_fusion("e:b", fact_kind="semantic_interpretation", value={"summary": "x"}),
            )
        )
        types = [r.conflict_type for r in records]
        self.assertIn(ConflictType.FORMAL_VS_SEMANTIC, types)

    def test_diagnostic_same_run_contradiction_is_diagnostic_conflict(self):
        detector = EvidenceConflictDetector()
        left = FusionEvidence(
            item=EvidenceItem(evidence_id="diag:1", fact_kind="diagnostic", value={}, recognition_run_id="run:1"),
            metadata=FusionMetadata(comparison_key="comparison:1", normalized_value={"run_status": "succeeded"}, content_fingerprint="fp:1"),
        )
        right = FusionEvidence(
            item=EvidenceItem(evidence_id="diag:2", fact_kind="diagnostic", value={}, recognition_run_id="run:1"),
            metadata=FusionMetadata(comparison_key="comparison:1", normalized_value={"run_status": "failed"}, content_fingerprint="fp:2"),
        )
        records = detector.detect((left, right))
        diagnostic_conflicts = [r for r in records if r.conflict_type is ConflictType.DIAGNOSTIC_CONFLICT]
        self.assertEqual(1, len(diagnostic_conflicts))

    def test_diagnostic_different_run_does_not_conflict(self):
        detector = EvidenceConflictDetector()
        left = FusionEvidence(
            item=EvidenceItem(evidence_id="diag:1", fact_kind="diagnostic", value={}, recognition_run_id="run:1"),
            metadata=FusionMetadata(comparison_key="comparison:1", normalized_value={"run_status": "succeeded"}, content_fingerprint="fp:1"),
        )
        right = FusionEvidence(
            item=EvidenceItem(evidence_id="diag:2", fact_kind="diagnostic", value={}, recognition_run_id="run:2"),
            metadata=FusionMetadata(comparison_key="comparison:1", normalized_value={"run_status": "failed"}, content_fingerprint="fp:2"),
        )
        records = detector.detect((left, right))
        diagnostic_conflicts = [r for r in records if r.conflict_type is ConflictType.DIAGNOSTIC_CONFLICT]
        self.assertEqual([], diagnostic_conflicts)


if __name__ == "__main__":
    unittest.main()
