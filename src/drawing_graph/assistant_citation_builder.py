"""Deterministic citation builder for the 06 answer-generation layer.

本模块从 claim 的 evidence IDs、``FusionEvidence`` 与 provenance 构造最小
citation，建立 claim 到 citation 的稳定关联，并执行稳定排序与去重。citation
不复制完整 payload，不输出本地图片路径、数据库 URI、Cypher 或内部 ID。
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from typing import Mapping, Sequence

from .assistant_evidence_fusion_models import FusionEvidence
from .assistant_models import (
    ANSWER_CONTRACT_VERSION,
    Citation,
    Claim,
    ClaimStatus,
    FactKind,
)


class CitationIntegrityError(ValueError):
    """claim/citation 双向完整性失败时抛出的稳定错误。"""


_FACT_KIND_ORDER = (
    FactKind.SOURCE_FACT,
    FactKind.DERIVED_RELATION,
    FactKind.SEMANTIC_OBSERVATION,
    FactKind.SEMANTIC_INTERPRETATION,
    FactKind.CANDIDATE_RELATION,
    FactKind.FORMAL_RELATION,
    FactKind.DIAGNOSTIC,
    FactKind.UNSUPPORTED,
)
_FACT_KIND_RANK = {kind: index for index, kind in enumerate(_FACT_KIND_ORDER)}


def build_citation_id(
    evidence_id: str,
    project_id: str | None = None,
    drawing_set_id: str | None = None,
    page_id: str | None = None,
    block_id: str | None = None,
    element_id: str | None = None,
    contract_version: str = ANSWER_CONTRACT_VERSION,
) -> str:
    """由合同版本、evidence ID 与公开定位字段生成稳定 citation ID。"""

    payload = {
        "answer_contract_version": contract_version,
        "evidence_id": evidence_id,
        "project_id": project_id or "",
        "drawing_set_id": drawing_set_id or "",
        "page_id": page_id or "",
        "block_id": block_id or "",
        "element_id": element_id or "",
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"citation:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _evidence_by_id(bundle) -> dict[str, FusionEvidence]:
    result: dict[str, FusionEvidence] = {}
    for fusion in tuple(bundle.accepted_evidence) + tuple(bundle.conflicting_evidence):
        result[fusion.item.evidence_id] = fusion
    return result


def _value_text(value, key: str) -> str | None:
    if isinstance(value, Mapping) and isinstance(value.get(key), str) and value[key].strip():
        return value[key]
    return None


def _metadata_text(metadata, key: str) -> str | None:
    if not isinstance(metadata, Mapping):
        return None
    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _project_citation(evidence_id: str, claim_ids: tuple[str, ...], fusion: FusionEvidence) -> Citation:
    item = fusion.item
    scope = item.scope
    metadata = item.evidence_metadata if isinstance(item.evidence_metadata, Mapping) else {}
    ref = item.evidence_refs[0] if item.evidence_refs else None

    bbox = None
    if ref is not None and ref.bbox is not None:
        bbox = dict(ref.bbox)
    elif isinstance(metadata.get("bbox"), Mapping):
        bbox = dict(metadata["bbox"])

    observation_id = None
    interpretation_id = None
    if item.fact_kind is FactKind.SEMANTIC_OBSERVATION:
        observation_id = _value_text(item.value, "observation_id")
    elif item.fact_kind is FactKind.SEMANTIC_INTERPRETATION:
        interpretation_id = _value_text(item.value, "interpretation_id")

    project_id = scope.project_id if scope else None
    drawing_set_id = scope.drawing_set_id if scope else None
    page_id = scope.page_id if scope else None
    block_id = scope.block_id if scope else None
    element_id = scope.element_id if scope else None

    return Citation(
        citation_id=build_citation_id(
            evidence_id,
            project_id,
            drawing_set_id,
            page_id,
            block_id,
            element_id,
        ),
        evidence_id=evidence_id,
        claim_ids=claim_ids,
        project_id=project_id,
        drawing_set_id=drawing_set_id,
        page_id=page_id,
        block_id=block_id,
        element_id=element_id,
        bbox=bbox,
        observation_id=observation_id,
        interpretation_id=interpretation_id,
        candidate_group_id=_metadata_text(metadata, "candidate_group_id"),
        recognition_run_id=item.recognition_run_id,
        payload_ref=item.payload_ref,
        rule_version=item.rule_version,
    )


def _is_diagnostic(claim: Claim) -> bool:
    status = claim.status
    return status == ClaimStatus.DIAGNOSTIC.value or status is ClaimStatus.DIAGNOSTIC


def _citation_sort_key(record) -> tuple:
    first_index, fact_kind, citation = record
    return (
        first_index,
        _FACT_KIND_RANK.get(fact_kind, 999),
        citation.page_id or "",
        citation.block_id or "",
        citation.element_id or "",
        citation.evidence_id or "",
        citation.citation_id or "",
    )


class CitationBuilder:
    """从 claim 的 evidence IDs 构造最小 citation 并稳定排序、去重。"""

    def build(self, claims: Sequence[Claim], evidence_bundle) -> tuple[Citation, ...]:
        evidence_by_id = _evidence_by_id(evidence_bundle)
        grouped: dict[str, dict] = {}
        for claim_index, claim in enumerate(claims):
            if _is_diagnostic(claim):
                continue
            for evidence_id in claim.evidence_ids:
                fusion = evidence_by_id.get(evidence_id)
                if fusion is None:
                    raise CitationIntegrityError(
                        f"claim {claim.claim_id} references unknown evidence {evidence_id}"
                    )
                entry = grouped.setdefault(
                    evidence_id,
                    {"claim_ids": [], "first": claim_index, "fusion": fusion},
                )
                if claim.claim_id not in entry["claim_ids"]:
                    entry["claim_ids"].append(claim.claim_id)

        records: list[tuple] = []
        for evidence_id, entry in grouped.items():
            fusion = entry["fusion"]
            citation = _project_citation(
                evidence_id,
                tuple(entry["claim_ids"]),
                fusion,
            )
            records.append((entry["first"], fusion.item.fact_kind, citation))
        records.sort(key=_citation_sort_key)
        return tuple(record[2] for record in records)


def bind_claim_citations(
    claims: Sequence[Claim],
    citations: Sequence[Citation],
) -> tuple[Claim, ...]:
    """把 citation 的 claim_ids 反向绑定到各 claim 的 citation_ids，建立双向一致。"""

    citations_by_claim: dict[str, list[str]] = {}
    for citation in citations:
        for claim_id in citation.claim_ids:
            citations_by_claim.setdefault(claim_id, []).append(citation.citation_id)
    updated: list[Claim] = []
    for claim in claims:
        ids = tuple(sorted(citations_by_claim.get(claim.claim_id, [])))
        updated.append(dataclasses.replace(claim, citation_ids=ids))
    return tuple(updated)
