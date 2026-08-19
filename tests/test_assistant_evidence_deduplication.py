"""Tests for deterministic evidence deduplication (Task 19)."""

import unittest

from drawing_graph.assistant_evidence_deduplication import (
    DeduplicationResult,
    EvidenceDeduplicator,
)
from drawing_graph.assistant_evidence_fusion_models import (
    EvidenceProvenance,
    FusionEvidence,
    FusionMetadata,
)
from drawing_graph.assistant_models import EvidenceItem, FactKind


def make_fusion(
    evidence_id,
    fact_kind="semantic_observation",
    fingerprint="fp:1",
    comparison_key="comparison:1",
    provenance=(),
    created_at=None,
    confidence=None,
):
    return FusionEvidence(
        item=EvidenceItem(
            evidence_id=evidence_id,
            fact_kind=fact_kind,
            value={},
            confidence=confidence,
            created_at_or_version=created_at,
        ),
        metadata=FusionMetadata(
            normalized_value={"text": "A1"},
            comparison_key=comparison_key,
            content_fingerprint=fingerprint,
        ),
        provenance=provenance,
    )


class EvidenceDeduplicationTests(unittest.TestCase):
    def test_identical_evidence_merges(self):
        first = make_fusion("evidence:a")
        second = make_fusion("evidence:b")
        result = EvidenceDeduplicator().deduplicate((first, second))
        self.assertEqual(1, len(result.deduplicated))
        self.assertEqual(("evidence:a", "evidence:b"), result.deduplicated[0].original_evidence_ids)

    def test_different_fact_kind_not_merged(self):
        first = make_fusion("evidence:a", fact_kind="semantic_observation", fingerprint="fp:1")
        second = make_fusion("evidence:b", fact_kind="semantic_interpretation", fingerprint="fp:2")
        result = EvidenceDeduplicator().deduplicate((first, second))
        self.assertEqual(2, len(result.deduplicated))

    def test_different_fingerprint_not_merged(self):
        first = make_fusion("evidence:a", fingerprint="fp:1")
        second = make_fusion("evidence:b", fingerprint="fp:2")
        result = EvidenceDeduplicator().deduplicate((first, second))
        self.assertEqual(2, len(result.deduplicated))

    def test_different_comparison_key_not_merged(self):
        first = make_fusion("evidence:a", fingerprint="fp:1", comparison_key="comparison:1")
        second = make_fusion("evidence:b", fingerprint="fp:1", comparison_key="comparison:2")
        result = EvidenceDeduplicator().deduplicate((first, second))
        self.assertEqual(2, len(result.deduplicated))

    def test_merge_preserves_all_provenance(self):
        provenance_a = (EvidenceProvenance(recognition_run_id="run:1"),)
        provenance_b = (EvidenceProvenance(recognition_run_id="run:2", payload_ref="payload:1"),)
        first = make_fusion("evidence:a", provenance=provenance_a)
        second = make_fusion("evidence:b", provenance=provenance_b)
        result = EvidenceDeduplicator().deduplicate((first, second))
        self.assertEqual(2, len(result.deduplicated[0].provenance))
        self.assertEqual("payload:1", result.deduplicated[0].provenance[1].payload_ref)

    def test_canonical_prefers_non_transient_stable_id(self):
        transient = make_fusion("candidate:run:temp:1:0", fingerprint="fp:1")
        stable = make_fusion("evidence:stable:1", fingerprint="fp:1")
        result = EvidenceDeduplicator().deduplicate((transient, stable))
        self.assertEqual("evidence:stable:1", result.deduplicated[0].item.evidence_id)

    def test_canonical_falls_back_to_created_at_then_id(self):
        older = make_fusion("evidence:z", fingerprint="fp:1", created_at="2026-01-01T00:00:00Z")
        newer = make_fusion("evidence:a", fingerprint="fp:1", created_at="2026-08-01T00:00:00Z")
        result = EvidenceDeduplicator().deduplicate((older, newer))
        self.assertEqual("evidence:a", result.deduplicated[0].item.evidence_id)

    def test_dedup_does_not_change_fact_kind_or_confidence(self):
        first = make_fusion("evidence:a", fingerprint="fp:1", confidence=0.8)
        second = make_fusion("evidence:b", fingerprint="fp:1", confidence=0.9)
        result = EvidenceDeduplicator().deduplicate((first, second))
        canonical = result.deduplicated[0]
        self.assertEqual(FactKind.SEMANTIC_OBSERVATION, canonical.item.fact_kind)
        self.assertEqual(0.8, canonical.item.confidence)

    def test_single_evidence_returns_unchanged(self):
        single = make_fusion("evidence:a")
        result = EvidenceDeduplicator().deduplicate((single,))
        self.assertEqual(1, len(result.deduplicated))
        self.assertEqual("evidence:a", result.deduplicated[0].item.evidence_id)

    def test_output_is_deterministic(self):
        items = (
            make_fusion("evidence:b", fingerprint="fp:1"),
            make_fusion("evidence:a", fingerprint="fp:2"),
            make_fusion("evidence:c", fingerprint="fp:1"),
        )
        first = EvidenceDeduplicator().deduplicate(items)
        second = EvidenceDeduplicator().deduplicate(items)
        self.assertEqual(
            tuple(item.item.evidence_id for item in first.deduplicated),
            tuple(item.item.evidence_id for item in second.deduplicated),
        )


if __name__ == "__main__":
    unittest.main()
