"""Claim trace projection (07 traceability loop).

从 ``TraceRecord`` 与 ``AnswerPackage`` 构造 ``ClaimTrace``，提供
``claim_id -> evidence/citation/run/payload/candidate`` 的只读追溯投影。
只使用稳定业务 ID，不使用数据库内部 ID；candidate 关系保持 candidate。
"""

from __future__ import annotations

from .assistant_models import AnswerPackage
from .assistant_trace_models import ClaimTrace, TraceRecord


class ClaimTraceProjector:
    """把 claim 与关联 citation 投影为可回查的 ``ClaimTrace``。"""

    def project(
        self,
        record: TraceRecord,
        package: AnswerPackage,
        claim_id: str,
    ) -> ClaimTrace | None:
        claim = _find_claim(package, claim_id)
        if claim is None:
            return None

        citations = _related_citations(package, claim)

        page_ids: list[str] = []
        block_ids: list[str] = []
        element_ids: list[str] = []
        bboxes: list[dict] = []
        candidate_group_ids: list[str] = []
        recognition_run_ids: list[str] = []
        payload_refs: list[str] = []
        for citation in citations:
            if citation.page_id:
                page_ids.append(citation.page_id)
            if citation.block_id:
                block_ids.append(citation.block_id)
            if citation.element_id:
                element_ids.append(citation.element_id)
            if citation.bbox is not None:
                bboxes.append(dict(citation.bbox))
            if citation.candidate_group_id:
                candidate_group_ids.append(citation.candidate_group_id)
            if citation.recognition_run_id:
                recognition_run_ids.append(citation.recognition_run_id)
            if citation.payload_ref:
                payload_refs.append(citation.payload_ref)

        evidence_ids = tuple(claim.evidence_ids) or tuple(record.evidence_ids)

        return ClaimTrace(
            claim_id=claim.claim_id,
            request_id=record.request_id,
            claim_status=claim.status,
            statement=claim.statement,
            fact_kinds=claim.fact_kinds,
            evidence_ids=tuple(dict.fromkeys(evidence_ids)),
            citation_ids=tuple(dict.fromkeys(claim.citation_ids)),
            page_ids=tuple(dict.fromkeys(page_ids)),
            block_ids=tuple(dict.fromkeys(block_ids)),
            element_ids=tuple(dict.fromkeys(element_ids)),
            bboxes=tuple(bboxes),
            recognition_run_ids=tuple(dict.fromkeys(recognition_run_ids)),
            candidate_group_ids=tuple(dict.fromkeys(candidate_group_ids)),
            payload_refs=tuple(dict.fromkeys(payload_refs)),
        )

    def project_all(
        self,
        record: TraceRecord,
        package: AnswerPackage,
    ) -> tuple[ClaimTrace, ...]:
        traces = []
        for claim in package.claims:
            trace = self.project(record, package, claim.claim_id)
            if trace is not None:
                traces.append(trace)
        return tuple(traces)


def _find_claim(package: AnswerPackage, claim_id: str):
    for claim in package.claims:
        if claim.claim_id == claim_id:
            return claim
    return None


def _related_citations(package: AnswerPackage, claim):
    related = []
    citation_ids = set(claim.citation_ids)
    for citation in package.citations:
        if claim.claim_id in citation.claim_ids or citation.citation_id in citation_ids:
            related.append(citation)
    return related


__all__ = ("ClaimTraceProjector",)
