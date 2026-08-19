"""Candidate review feedback adapter (08 feedback loop).

把合法 ``request_review`` 反馈转换为 ``CandidateReviewRequest`` 并调用注入的
候选审核服务的 ``review_candidate_group()``。只支持候选关系 claim；候选集合
不完整、跨页、方向不明或缺少 evidence refs 时返回稳定错误，不直接调用
repository、不拼查询语言、不创建图数据库 driver。
"""

from __future__ import annotations

from typing import Any, Protocol

from .assistant_models import FactKind, FeedbackEvent
from .assistant_trace_models import ClaimTrace
from .candidate_review import (
    CandidateReviewRequest,
    CandidateReviewResult,
)

_SUPPORTED_RELATION_SPECS = frozenset(
    {
        "candidate_caption_of",
        "candidate_section_mark",
        "candidate_matches_section_caption",
    }
)

_DIRECTION_RULES = {
    "candidate_caption_of": ("caption:", "block:"),
    "candidate_section_mark": ("block:", "cross-section:"),
    "candidate_matches_section_caption": ("cross-section:", "caption:"),
}


class _ReviewService(Protocol):
    """候选审核服务的最小协议，实例由调用方注入。"""

    def review_candidate_group(self, request: CandidateReviewRequest) -> CandidateReviewResult: ...


class CandidateReviewAdapterError(ValueError):
    """候选审核适配的稳定领域错误，携带 category 而非底层异常。"""

    def __init__(self, category: str, message: str):
        self.category = category
        super().__init__(message)


class CandidateReviewAdapter:
    """仅处理 request_review，受控调用注入的候选审核服务。"""

    def __init__(self, review_service: _ReviewService) -> None:
        self.review_service = review_service

    def build_review_request(
        self,
        feedback_event: FeedbackEvent,
        claim_trace: ClaimTrace,
    ) -> CandidateReviewRequest:
        _require_candidate_claim(claim_trace)
        relation_spec = claim_trace.relation_spec
        if not relation_spec or relation_spec not in _SUPPORTED_RELATION_SPECS:
            raise CandidateReviewAdapterError(
                "direction_unknown",
                "claim trace lacks a supported candidate relation spec",
            )
        candidates = list(claim_trace.candidates)
        if not candidates:
            raise CandidateReviewAdapterError(
                "incomplete_candidates",
                "claim trace has no complete candidate group",
            )

        page_id = _resolve_page_id(candidates, claim_trace)
        _require_same_page(candidates, page_id)
        _require_direction(relation_spec, candidates)

        evidence_refs = tuple(claim_trace.evidence_refs)
        if not evidence_refs:
            raise CandidateReviewAdapterError(
                "missing_evidence_refs",
                "claim trace has no evidence refs for review",
            )

        rule_version = claim_trace.rule_version or str(candidates[0].get("rule_version", ""))
        if not rule_version:
            raise CandidateReviewAdapterError(
                "missing_rule_version",
                "claim trace lacks a rule version",
            )

        group_key = claim_trace.candidate_group_ids[0] if claim_trace.candidate_group_ids else str(candidates[0].get("start_id", ""))
        source_element_id = str(candidates[0].get("start_id", ""))

        return CandidateReviewRequest(
            review_run_id=f"review-run:{feedback_event.feedback_id}",
            relation_spec=relation_spec,
            group_key=group_key,
            source_element_id=source_element_id,
            page_id=page_id,
            rule_version=rule_version,
            candidates=tuple(candidates),
            evidence_refs=evidence_refs,
        )

    def request_review(
        self,
        feedback_event: FeedbackEvent,
        claim_trace: ClaimTrace,
    ) -> CandidateReviewResult:
        request = self.build_review_request(feedback_event, claim_trace)
        return self.review_service.review_candidate_group(request)


def _require_candidate_claim(claim_trace: ClaimTrace) -> None:
    if FactKind.CANDIDATE_RELATION not in claim_trace.fact_kinds:
        raise CandidateReviewAdapterError(
            "not_candidate_claim",
            "feedback review only supports candidate relation claims",
        )


def _resolve_page_id(candidates: list[Any], claim_trace: ClaimTrace) -> str:
    page_id = str(candidates[0].get("page_id", ""))
    if not page_id and claim_trace.page_ids:
        page_id = claim_trace.page_ids[0]
    if not page_id:
        raise CandidateReviewAdapterError(
            "cross_page",
            "candidate group has no page id",
        )
    return page_id


def _require_same_page(candidates: list[Any], page_id: str) -> None:
    for candidate in candidates:
        if str(candidate.get("page_id", "")) != page_id:
            raise CandidateReviewAdapterError(
                "cross_page",
                "candidate group spans multiple pages",
            )


def _require_direction(relation_spec: str, candidates: list[Any]) -> None:
    start_prefix, end_prefix = _DIRECTION_RULES[relation_spec]
    for candidate in candidates:
        start_id = str(candidate.get("start_id", ""))
        end_id = str(candidate.get("end_id", ""))
        if not start_id.startswith(start_prefix) or not end_id.startswith(end_prefix):
            raise CandidateReviewAdapterError(
                "direction_unknown",
                "candidate relation direction is not consistent with the spec",
            )


__all__ = (
    "CandidateReviewAdapter",
    "CandidateReviewAdapterError",
)
