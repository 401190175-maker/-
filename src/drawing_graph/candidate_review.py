"""Candidate relation review contracts and service orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal, Mapping


ReviewStatus = Literal["accepted", "rejected", "unresolved"]
CandidateRelationSpec = Literal["candidate_caption_of", "candidate_section_mark"]
SUPPORTED_REVIEW_STATUSES = frozenset(("accepted", "rejected", "unresolved"))
SUPPORTED_CANDIDATE_SPECS = frozenset(
    ("candidate_caption_of", "candidate_section_mark", "candidate_matches_section_caption")
)


class CandidateReviewError(ValueError):
    """Raised when candidate review input or output violates fixed contracts."""

    def __init__(self, category: str, message: str):
        self.category = category
        super().__init__(message)


@dataclass(frozen=True)
class CandidateReviewRequest:
    """Immutable complete candidate group sent to an injected review client."""

    review_run_id: str
    relation_spec: CandidateRelationSpec
    group_key: str
    source_element_id: str
    page_id: str
    rule_version: str
    candidates: tuple[Mapping[str, Any], ...]
    evidence_refs: tuple[str, ...]
    context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.review_run_id, "review_run_id")
        _require_candidate_spec(self.relation_spec)
        _require_text(self.group_key, "group_key")
        _require_text(self.source_element_id, "source_element_id")
        _require_text(self.page_id, "page_id")
        _require_text(self.rule_version, "rule_version")
        candidates = _read_candidate_tuple(self.candidates)
        if not candidates:
            raise CandidateReviewError("missing_candidates", "candidates must contain the complete candidate group")
        evidence_refs = _read_text_tuple(self.evidence_refs, "evidence_refs")
        if not evidence_refs:
            raise CandidateReviewError("missing_evidence_refs", "evidence_refs must not be empty")
        if not isinstance(self.context, Mapping):
            raise CandidateReviewError("invalid_context", "context must be a mapping")
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "evidence_refs", evidence_refs)
        object.__setattr__(self, "context", MappingProxyType(dict(self.context)))

    @property
    def candidate_count(self) -> int:
        """Return the number of candidates provided to the review client."""

        return len(self.candidates)


@dataclass(frozen=True)
class CandidateReviewResult:
    """Immutable structured result returned by candidate relation review."""

    review_run_id: str
    relation_spec: CandidateRelationSpec
    status: ReviewStatus
    accepted_candidate_id: str | None = None
    model_version: str | None = None
    prompt_version: str | None = None
    score: float | None = None
    reason: str | None = None
    issue_category: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.review_run_id, "review_run_id")
        _require_candidate_spec(self.relation_spec)
        if self.status not in SUPPORTED_REVIEW_STATUSES:
            raise CandidateReviewError("invalid_review_status", "status must be accepted, rejected, or unresolved")
        if self.status == "accepted":
            if not isinstance(self.accepted_candidate_id, str) or not self.accepted_candidate_id:
                raise CandidateReviewError(
                    "missing_accepted_candidate",
                    "accepted results must include accepted_candidate_id",
                )
        elif self.accepted_candidate_id is not None:
            raise CandidateReviewError(
                "unexpected_accepted_candidate",
                "only accepted results may include accepted_candidate_id",
            )
        _require_optional_text(self.model_version, "model_version")
        _require_optional_text(self.prompt_version, "prompt_version")
        _require_optional_text(self.reason, "reason")
        _require_optional_text(self.issue_category, "issue_category")
        if self.score is not None and (
            not isinstance(self.score, (int, float)) or isinstance(self.score, bool)
        ):
            raise CandidateReviewError("invalid_review_score", "score must be numeric when provided")


class CandidateReviewService:
    """Run structured candidate review through an injected client."""

    def __init__(self, review_client: Any, repository: Any | None = None):
        self.review_client = review_client
        self.repository = repository

    def review_candidate_group(self, request: CandidateReviewRequest) -> CandidateReviewResult:
        """Review one complete candidate group and return a validated result."""

        if not isinstance(request, CandidateReviewRequest):
            raise CandidateReviewError("invalid_review_request", "request must be a CandidateReviewRequest")
        try:
            raw_result = self.review_client.review(request)
        except Exception:  # noqa: BLE001 - service boundary converts external client failures to unresolved.
            return _unresolved_result(
                request,
                "candidate_review_unavailable",
                "candidate review client unavailable",
            )
        try:
            result = _coerce_review_result(request, raw_result)
        except CandidateReviewError:
            return _unresolved_result(
                request,
                "candidate_review_invalid_output",
                "candidate review client returned invalid output",
            )
        if not _passes_promotion_rules(request, result):
            return _unresolved_result(
                request,
                "candidate_promotion_rule_failed",
                "accepted candidate failed hard promotion rules",
            )
        if self.repository is not None:
            try:
                _persist_review_result(self.repository, request, result)
            except Exception:  # noqa: BLE001 - repository boundary returns classified unresolved result.
                return _unresolved_result(
                    request,
                    "candidate_review_write_failed",
                    "candidate review result could not be written",
                )
        return result


def _require_candidate_spec(value: str) -> None:
    _require_text(value, "relation_spec")
    if value not in SUPPORTED_CANDIDATE_SPECS:
        raise CandidateReviewError("invalid_candidate_relation_spec", "relation_spec must be a fixed candidate spec")


def _require_text(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise CandidateReviewError("missing_required_field", f"{field_name} must be a non-empty string")


def _require_optional_text(value: Any, field_name: str) -> None:
    if value is not None:
        _require_text(value, field_name)


def _read_text_tuple(values: Any, field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
        raise CandidateReviewError("invalid_sequence", f"{field_name} must be a sequence")
    for value in values:
        _require_text(value, field_name)
    return tuple(values)


def _read_candidate_tuple(values: Any) -> tuple[Mapping[str, Any], ...]:
    if isinstance(values, Mapping) or not isinstance(values, (list, tuple)):
        raise CandidateReviewError("invalid_candidates", "candidates must be a sequence of mappings")
    candidates: list[Mapping[str, Any]] = []
    for candidate in values:
        if not isinstance(candidate, Mapping):
            raise CandidateReviewError("invalid_candidate", "each candidate must be a mapping")
        _require_text(candidate.get("candidate_id"), "candidate_id")
        _require_text(candidate.get("start_id"), "start_id")
        _require_text(candidate.get("end_id"), "end_id")
        _require_text(candidate.get("page_id"), "page_id")
        _require_candidate_spec(candidate.get("relation_spec"))
        normalized_candidate = dict(candidate)
        if candidate.get("relation_spec") == "candidate_matches_section_caption":
            observation_ids = candidate.get("observation_ids")
            if isinstance(observation_ids, (str, bytes)) or not isinstance(observation_ids, (list, tuple)):
                raise CandidateReviewError(
                    "missing_observation_evidence",
                    "semantic candidates must include observation_ids",
                )
            if not observation_ids:
                raise CandidateReviewError(
                    "missing_observation_evidence",
                    "semantic candidates must include at least one observation_id",
                )
            for observation_id in observation_ids:
                _require_text(observation_id, "observation_id")
            normalized_candidate["observation_ids"] = tuple(observation_ids)
        candidates.append(MappingProxyType(normalized_candidate))
    return tuple(candidates)


def _coerce_review_result(request: CandidateReviewRequest, raw_result: Any) -> CandidateReviewResult:
    if isinstance(raw_result, CandidateReviewResult):
        if raw_result.review_run_id != request.review_run_id:
            raise CandidateReviewError("review_run_mismatch", "result review_run_id must match request")
        if raw_result.relation_spec != request.relation_spec:
            raise CandidateReviewError("relation_spec_mismatch", "result relation_spec must match request")
        return raw_result
    if not isinstance(raw_result, Mapping):
        raise CandidateReviewError("invalid_review_output", "review output must be a mapping or result")
    return CandidateReviewResult(
        review_run_id=request.review_run_id,
        relation_spec=request.relation_spec,
        status=raw_result.get("status"),
        accepted_candidate_id=raw_result.get("accepted_candidate_id"),
        model_version=raw_result.get("model_version"),
        prompt_version=raw_result.get("prompt_version"),
        score=raw_result.get("score"),
        reason=raw_result.get("reason"),
        issue_category=raw_result.get("issue_category"),
    )


def _unresolved_result(
    request: CandidateReviewRequest,
    issue_category: str,
    reason: str,
) -> CandidateReviewResult:
    return CandidateReviewResult(
        review_run_id=request.review_run_id,
        relation_spec=request.relation_spec,
        status="unresolved",
        reason=reason,
        issue_category=issue_category,
    )


def _passes_promotion_rules(request: CandidateReviewRequest, result: CandidateReviewResult) -> bool:
    if result.status != "accepted":
        return True
    matches = [
        candidate
        for candidate in request.candidates
        if candidate.get("candidate_id") == result.accepted_candidate_id
    ]
    if len(matches) != 1:
        return False
    accepted_candidate = matches[0]
    if accepted_candidate.get("relation_spec") != request.relation_spec:
        return False
    if accepted_candidate.get("page_id") != request.page_id:
        return False
    if request.relation_spec == "candidate_caption_of":
        return str(accepted_candidate.get("start_id", "")).startswith("caption:") and str(
            accepted_candidate.get("end_id", "")
        ).startswith("block:")
    if request.relation_spec == "candidate_section_mark":
        return str(accepted_candidate.get("start_id", "")).startswith("block:") and str(
            accepted_candidate.get("end_id", "")
        ).startswith("cross-section:")
    if request.relation_spec == "candidate_matches_section_caption":
        return (
            len(request.candidates) == 1
            and str(accepted_candidate.get("start_id", "")).startswith("cross-section:")
            and str(accepted_candidate.get("end_id", "")).startswith("caption:")
            and bool(accepted_candidate.get("observation_ids"))
        )
    return False


def _persist_review_result(repository: Any, request: CandidateReviewRequest, result: CandidateReviewResult) -> None:
    target_candidates = _candidates_for_review_update(request, result)
    for candidate in target_candidates:
        repository.update_candidate_review(
            relation_spec=request.relation_spec,
            start_id=candidate["start_id"],
            end_id=candidate["end_id"],
            rule_version=request.rule_version,
            review_status=result.status,
            review_run_id=request.review_run_id,
            review_model_version=result.model_version,
            review_prompt_version=result.prompt_version,
            review_score=result.score,
            review_reason=result.reason,
        )
    if result.status != "accepted":
        return
    accepted_candidate = target_candidates[0]
    repository.promote_candidate_relation(
        relation_spec=request.relation_spec,
        candidate_start_id=accepted_candidate["start_id"],
        candidate_end_id=accepted_candidate["end_id"],
        candidate_rule_version=request.rule_version,
        review_status="accepted",
        review_run_id=request.review_run_id,
        formal_rule_version=request.rule_version,
        confirmation_method="multimodal_llm",
    )


def _candidates_for_review_update(
    request: CandidateReviewRequest,
    result: CandidateReviewResult,
) -> tuple[Mapping[str, Any], ...]:
    if result.status == "accepted":
        return tuple(
            candidate
            for candidate in request.candidates
            if candidate.get("candidate_id") == result.accepted_candidate_id
        )
    return request.candidates


__all__ = (
    "CandidateReviewError",
    "CandidateReviewRequest",
    "CandidateReviewResult",
    "CandidateReviewService",
)
