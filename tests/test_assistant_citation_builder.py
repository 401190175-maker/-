"""Tests for the deterministic citation builder."""

import unittest

from drawing_graph.assistant_citation_builder import (
    CitationBuilder,
    CitationIntegrityError,
    bind_claim_citations,
    build_citation_id,
)
from drawing_graph.assistant_evidence_fusion_models import (
    EvidenceBundle,
    FusionEvidence,
    FusionMetadata,
)
from drawing_graph.assistant_models import (
    AssistantScope,
    Citation,
    Claim,
    ClaimStatus,
    EvidenceItem,
    EvidenceRef,
    FactKind,
)


def make_claim(claim_id="claim:1", evidence_ids=("evidence:1",), status="supported"):
    return Claim(
        claim_id=claim_id,
        statement="图中识别到的文字与符号已确认",
        claim_type="observed_text_or_symbol",
        status=status,
        evidence_ids=evidence_ids,
        fact_kinds=(FactKind.SEMANTIC_OBSERVATION,),
    )


def make_observation_fusion():
    return FusionEvidence(
        item=EvidenceItem(
            evidence_id="evidence:1",
            fact_kind=FactKind.SEMANTIC_OBSERVATION,
            scope=AssistantScope(
                page_id="page:1",
                block_id="block:1",
                element_id="element:1",
            ),
            value={"observation_id": "obs:1"},
            recognition_run_id="run:1",
            payload_ref="payload:1",
            rule_version="v1",
            evidence_refs=(
                EvidenceRef(
                    page_id="page:1",
                    element_id="element:1",
                    bbox={"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
                ),
            ),
        ),
        metadata=FusionMetadata(),
    )


def make_bundle(evidence=()):
    return EvidenceBundle(request_id="req:1", accepted_evidence=evidence)


def make_plain_fusion(evidence_id, fact_kind, page_id="page:1"):
    return FusionEvidence(
        item=EvidenceItem(
            evidence_id=evidence_id,
            fact_kind=fact_kind,
            scope=AssistantScope(page_id=page_id),
            value={},
        ),
        metadata=FusionMetadata(),
    )


class MinimalCitationProjectionTests(unittest.TestCase):
    def test_projects_minimal_location_and_source_fields(self):
        builder = CitationBuilder()
        citation = builder.build((make_claim(),), make_bundle((make_observation_fusion(),)))[0]
        self.assertEqual("evidence:1", citation.evidence_id)
        self.assertEqual("page:1", citation.page_id)
        self.assertEqual("block:1", citation.block_id)
        self.assertEqual("element:1", citation.element_id)
        self.assertEqual(
            {"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
            dict(citation.bbox),
        )
        self.assertEqual("obs:1", citation.observation_id)
        self.assertEqual("run:1", citation.recognition_run_id)
        self.assertEqual("payload:1", citation.payload_ref)
        self.assertEqual("v1", citation.rule_version)
        self.assertEqual(("claim:1",), citation.claim_ids)

    def test_does_not_output_image_path_uri_or_internal_ids(self):
        builder = CitationBuilder()
        citation = builder.build((make_claim(),), make_bundle((make_observation_fusion(),)))[0]
        self.assertFalse(hasattr(citation, "image_path"))
        self.assertFalse(hasattr(citation, "database_uri"))
        self.assertFalse(hasattr(citation, "cypher"))

    def test_payload_ref_is_reference_not_body(self):
        builder = CitationBuilder()
        citation = builder.build((make_claim(),), make_bundle((make_observation_fusion(),)))[0]
        self.assertEqual("payload:1", citation.payload_ref)
        self.assertFalse(hasattr(citation, "payload"))

    def test_candidate_group_projected_when_present(self):
        fusion = FusionEvidence(
            item=EvidenceItem(
                evidence_id="candidate:1",
                fact_kind=FactKind.CANDIDATE_RELATION,
                scope=AssistantScope(page_id="page:1", block_id="block:1"),
                value={},
                evidence_metadata={"candidate_group_id": "group:1"},
            ),
            metadata=FusionMetadata(),
        )
        claim = Claim(
            claim_id="claim:2",
            statement="候选关系",
            status="supported",
            evidence_ids=("candidate:1",),
            fact_kinds=(FactKind.CANDIDATE_RELATION,),
        )
        citation = CitationBuilder().build((claim,), make_bundle((fusion,)))[0]
        self.assertEqual("group:1", citation.candidate_group_id)
        self.assertEqual("block:1", citation.block_id)


class StableCitationOrderingTests(unittest.TestCase):
    def test_same_public_location_same_id(self):
        first = build_citation_id("evidence:1", page_id="page:1", element_id="element:1")
        second = build_citation_id("evidence:1", page_id="page:1", element_id="element:1")
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("citation:"))

    def test_different_location_or_evidence_changes_id(self):
        base = build_citation_id("evidence:1", page_id="page:1")
        self.assertNotEqual(base, build_citation_id("evidence:1", page_id="page:2"))
        self.assertNotEqual(base, build_citation_id("evidence:2", page_id="page:1"))
        self.assertNotEqual(base, build_citation_id("evidence:1", page_id="page:1", element_id="element:1"))

    def test_citations_follow_first_cited_claim_order(self):
        builder = CitationBuilder()
        claim_a = Claim(
            claim_id="claim:a",
            statement="s",
            status="supported",
            evidence_ids=("evidence:z",),
            fact_kinds=(FactKind.SEMANTIC_OBSERVATION,),
        )
        claim_b = Claim(
            claim_id="claim:b",
            statement="s",
            status="supported",
            evidence_ids=("evidence:a",),
            fact_kinds=(FactKind.SOURCE_FACT,),
        )
        evidence = (
            make_plain_fusion("evidence:z", FactKind.SEMANTIC_OBSERVATION),
            make_plain_fusion("evidence:a", FactKind.SOURCE_FACT),
        )
        citations = builder.build((claim_a, claim_b), make_bundle(evidence))
        self.assertEqual(
            ("evidence:z", "evidence:a"),
            tuple(item.evidence_id for item in citations),
        )

    def test_input_disorder_does_not_change_output(self):
        builder = CitationBuilder()
        claim1 = Claim(
            claim_id="claim:1",
            statement="s",
            status="supported",
            evidence_ids=("evidence:a", "evidence:b"),
            fact_kinds=(FactKind.SOURCE_FACT, FactKind.SOURCE_FACT),
        )
        claim2 = Claim(
            claim_id="claim:1",
            statement="s",
            status="supported",
            evidence_ids=("evidence:b", "evidence:a"),
            fact_kinds=(FactKind.SOURCE_FACT, FactKind.SOURCE_FACT),
        )
        evidence = (
            make_plain_fusion("evidence:a", FactKind.SOURCE_FACT),
            make_plain_fusion("evidence:b", FactKind.SOURCE_FACT),
        )
        first = builder.build((claim1,), make_bundle(evidence))
        second = builder.build((claim2,), make_bundle(evidence))
        self.assertEqual(tuple(item.citation_id for item in first), tuple(item.citation_id for item in second))
        self.assertEqual(tuple(item.evidence_id for item in first), tuple(item.evidence_id for item in second))


class ClaimCitationIntegrityTests(unittest.TestCase):
    def test_non_diagnostic_claim_gets_at_least_one_citation(self):
        builder = CitationBuilder()
        claim = make_claim()
        citations = builder.build((claim,), make_bundle((make_observation_fusion(),)))
        bound = bind_claim_citations((claim,), citations)
        self.assertEqual(1, len(bound[0].citation_ids))
        self.assertEqual(citations[0].citation_id, bound[0].citation_ids[0])

    def test_bidirectional_consistency(self):
        builder = CitationBuilder()
        claim = make_claim()
        citations = builder.build((claim,), make_bundle((make_observation_fusion(),)))
        bound = bind_claim_citations((claim,), citations)
        self.assertEqual(("claim:1",), citations[0].claim_ids)
        self.assertEqual((citations[0].citation_id,), bound[0].citation_ids)

    def test_deduplicated_evidence_yields_one_citation(self):
        builder = CitationBuilder()
        claim_a = make_claim("claim:a", evidence_ids=("evidence:1",))
        claim_b = make_claim("claim:b", evidence_ids=("evidence:1",))
        citations = builder.build(
            (claim_a, claim_b),
            make_bundle((make_observation_fusion(),)),
        )
        self.assertEqual(1, len(citations))
        self.assertEqual(("claim:a", "claim:b"), citations[0].claim_ids)

    def test_unknown_evidence_fails_closed(self):
        builder = CitationBuilder()
        claim = make_claim(evidence_ids=("evidence:missing",))
        with self.assertRaises(CitationIntegrityError):
            builder.build((claim,), make_bundle((make_observation_fusion(),)))

    def test_diagnostic_claim_needs_no_citation(self):
        builder = CitationBuilder()
        diagnostic = Claim(
            claim_id="claim:diag",
            statement="运行状态说明",
            status="diagnostic",
            evidence_ids=(),
            fact_kinds=(FactKind.DIAGNOSTIC,),
        )
        citations = builder.build((diagnostic,), make_bundle(()))
        self.assertEqual((), citations)


if __name__ == "__main__":
    unittest.main()
