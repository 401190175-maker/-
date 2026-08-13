"""Application facade for stable drawing graph tool calls."""

from __future__ import annotations

from typing import Callable, TypeVar

from .query_ports import DrawingGraphReadPort
from .candidate_review import CandidateReviewRequest, CandidateReviewResult, CandidateReviewService
from .recognition_models import RecognitionExecutionPolicy
from .semantic_query_projection import SemanticQueryProjection
from .section_match_service import SectionMatchDecision, SectionMatchService
from .semantic_service import SemanticRecognitionResult
from .tool_models import (
    BlockRelations,
    BlockTrace,
    CandidateReviewSummary,
    DrawingSetSummary,
    PageSourceFacts,
    PageSummary,
    SectionMatchSummary,
    SemanticPayloadSummary,
    SemanticTargetInput,
    ToolModelError,
)


T = TypeVar("T")


class DrawingGraphToolFacade:
    """Stable application boundary intended for future Tool adapters."""

    def __init__(
        self,
        read_port: DrawingGraphReadPort,
        semantic_service: object | None = None,
        run_log: object | None = None,
        semantic_repository: object | None = None,
        candidate_relation_port: object | None = None,
        candidate_review_service: object | None = None,
        semantic_query_projection: object | None = None,
        payload_store: object | None = None,
        section_match_service: object | None = None,
        section_match_write_port: object | None = None,
        section_match_query_port: object | None = None,
    ):
        self.read_port = read_port
        self.semantic_service = semantic_service
        self.run_log = run_log
        self.semantic_repository = semantic_repository
        self.candidate_relation_port = candidate_relation_port
        self.candidate_review_service = candidate_review_service
        self.semantic_query_projection = semantic_query_projection or SemanticQueryProjection()
        self.payload_store = payload_store
        self.section_match_service = section_match_service or SectionMatchService()
        self.section_match_write_port = section_match_write_port
        self.section_match_query_port = section_match_query_port

    def list_drawing_sets(
        self,
        project_id: str,
        limit: int = 100,
        write_back: bool = False,
    ) -> list[DrawingSetSummary]:
        _reject_write_back(write_back)
        return self._read_call(lambda: self.read_port.list_drawing_sets(project_id, limit))

    def list_pages(
        self,
        drawing_set_id: str,
        limit: int = 100,
        write_back: bool = False,
    ) -> list[PageSummary]:
        _reject_write_back(write_back)
        return self._read_call(lambda: self.read_port.list_pages(drawing_set_id, limit))

    def get_page_source_facts(
        self,
        page_id: str,
        element_types: tuple[str, ...] | None = None,
        include_image_meta: bool = True,
        write_back: bool = False,
    ) -> PageSourceFacts | None:
        _reject_write_back(write_back)
        return self._read_call(
            lambda: self.read_port.get_page_source_facts(page_id, element_types, include_image_meta)
        )

    def get_block_trace(self, block_id: str, write_back: bool = False) -> BlockTrace | None:
        _reject_write_back(write_back)
        return self._read_call(lambda: self.read_port.get_block_trace(block_id))

    def get_block_relations(self, block_id: str, write_back: bool = False) -> BlockRelations | None:
        _reject_write_back(write_back)
        return self._read_call(lambda: self.read_port.get_block_relations(block_id))

    def recognize_page_semantics(
        self,
        page_id: str,
        target_types: tuple[str, ...],
        model_profile: str = "default",
        prompt_version: str = "default",
        write_back: bool = False,
    ) -> SemanticRecognitionResult:
        if self.semantic_service is None:
            raise ToolModelError("RECOGNITION_FAILED", "semantic recognition service is not configured")
        page_facts = self.get_page_source_facts(page_id)
        if page_facts is None:
            raise ToolModelError("NOT_FOUND", "page source facts were not found")
        try:
            return self.semantic_service.recognize_page(
                page_facts=page_facts,
                target_types=target_types,
                model_profile=model_profile,
                prompt_version=prompt_version,
                write_back=write_back,
            )
        except ToolModelError:
            raise
        except Exception as exc:
            raise ToolModelError("RECOGNITION_FAILED", "semantic recognition failed") from exc

    def recognize_semantic_targets(
        self,
        targets: tuple[SemanticTargetInput, ...],
        model_profile: str = "default",
        prompt_version: str = "default",
        contract_version: str = "1",
        write_back: bool = False,
        execution_policy: RecognitionExecutionPolicy | None = None,
    ) -> SemanticRecognitionResult:
        """执行精确识别目标（预留入口），默认 ``write_back=false``。"""

        if self.semantic_service is None:
            raise ToolModelError(
                "RECOGNITION_FAILED",
                "semantic recognition service is not configured",
            )
        if (
            not isinstance(targets, tuple)
            or not targets
            or not all(isinstance(target, SemanticTargetInput) for target in targets)
        ):
            raise ToolModelError(
                "INVALID_ARGUMENT",
                "targets must be a non-empty tuple of SemanticTargetInput",
            )
        page_ids = {target.page_id for target in targets}
        if len(page_ids) != 1:
            raise ToolModelError(
                "INVALID_ARGUMENT",
                "all targets must belong to one page",
            )
        page_id = next(iter(page_ids))
        page_facts = self.get_page_source_facts(page_id)
        if page_facts is None:
            raise ToolModelError("NOT_FOUND", "page source facts were not found")
        try:
            return self.semantic_service.recognize_targets(
                page_facts=page_facts,
                targets=targets,
                model_profile=model_profile,
                prompt_version=prompt_version,
                contract_version=contract_version,
                write_back=write_back,
                execution_policy=execution_policy,
            )
        except ToolModelError:
            raise
        except Exception as exc:
            raise ToolModelError("RECOGNITION_FAILED", "semantic recognition failed") from exc

    def get_recognition_run(self, recognition_run_id: str, write_back: bool = False):
        _reject_write_back(write_back)
        if self.run_log is None:
            raise ToolModelError("RUN_LOG_UNAVAILABLE", "recognition run log is not configured")
        return self._read_call(lambda: self.run_log.get_run(recognition_run_id))

    def list_text_observations(
        self,
        page_id: str | None = None,
        element_id: str | None = None,
        recognition_run_id: str | None = None,
        statuses: tuple[str, ...] | None = None,
        write_back: bool = False,
    ):
        _reject_write_back(write_back)
        if self.semantic_repository is None:
            raise ToolModelError("SEMANTIC_EVIDENCE_UNAVAILABLE", "semantic evidence repository is not configured")
        supplied_filters = sum(value is not None for value in (page_id, element_id, recognition_run_id))
        if supplied_filters != 1:
            raise ToolModelError("INVALID_ARGUMENT", "provide exactly one observation query filter")
        if page_id is not None:
            observations = self._read_call(lambda: self.semantic_repository.find_by_page(page_id))
        elif element_id is not None:
            observations = self._read_call(lambda: self.semantic_repository.find_by_element(element_id))
        else:
            observations = self._read_call(lambda: self.semantic_repository.find_by_run(recognition_run_id))
        if statuses is not None:
            allowed_statuses = set(statuses)
            observations = tuple(item for item in observations if item.status.value in allowed_statuses)
        if not observations:
            raise ToolModelError("NOT_FOUND", "text observations were not found")
        return self.semantic_query_projection.project_observations(observations)

    def list_interpretations(
        self,
        page_id: str | None = None,
        element_id: str | None = None,
        recognition_run_id: str | None = None,
        statuses: tuple[str, ...] | None = None,
        write_back: bool = False,
    ):
        """Return stable interpretation summaries through the semantic projection."""

        _reject_write_back(write_back)
        if self.semantic_repository is None:
            raise ToolModelError("SEMANTIC_EVIDENCE_UNAVAILABLE", "semantic evidence repository is not configured")
        supplied_filters = sum(value is not None for value in (page_id, element_id, recognition_run_id))
        if supplied_filters != 1:
            raise ToolModelError("INVALID_ARGUMENT", "provide exactly one interpretation query filter")
        interpretations = self._read_call(
            lambda: self.semantic_repository.find_interpretations(
                page_id=page_id,
                element_id=element_id,
                recognition_run_id=recognition_run_id,
                statuses=statuses,
            )
        )
        if not interpretations:
            raise ToolModelError("NOT_FOUND", "semantic interpretations were not found")
        return self.semantic_query_projection.project_interpretations(interpretations)

    def get_semantic_payload(
        self,
        payload_ref: str,
        write_back: bool = False,
    ) -> SemanticPayloadSummary:
        """Return one immutable semantic payload by reference (read-only)."""

        _reject_write_back(write_back)
        _require_text(payload_ref, "payload_ref")
        if self.payload_store is None:
            raise ToolModelError("PAYLOAD_UNAVAILABLE", "semantic payload store is not configured")
        payload = self._read_call(lambda: self.payload_store.get_payload(payload_ref))
        content_hash, contract_version = _payload_meta(self.payload_store, payload_ref)
        return SemanticPayloadSummary(
            payload_ref=payload_ref,
            content_hash=content_hash,
            contract_version=contract_version,
            payload=payload,
        )

    def match_section_caption(
        self,
        cross_section_id: str,
        page_id: str | None = None,
        write_back: bool = False,
        rule_version: str = "section-match-v1",
    ) -> SectionMatchSummary:
        """Match one CrossSection label against same-page BlockCaption observations."""

        _require_text(cross_section_id, "cross_section_id")
        _require_text(rule_version, "rule_version")
        if self.semantic_repository is None:
            raise ToolModelError("SEMANTIC_EVIDENCE_UNAVAILABLE", "semantic evidence repository is not configured")
        cross_section_observation = self._find_cross_section_observation(cross_section_id)
        resolved_page_id = page_id or (cross_section_observation.page_id if cross_section_observation is not None else None)
        if resolved_page_id is None:
            raise ToolModelError("NOT_FOUND", "cross-section observation was not found")
        page_observations = self._read_call(lambda: self.semantic_repository.find_by_page(resolved_page_id))
        caption_observations = tuple(
            item for item in page_observations if item.target_element_type == "BlockCaption"
        )
        decision = self.section_match_service.evaluate_formal_match(
            cross_section_observation=cross_section_observation,
            caption_observations=caption_observations,
            page_id=resolved_page_id,
            rule_version=rule_version,
        )
        persisted = False
        if write_back:
            persisted = self._write_section_decision(
                decision=decision,
                cross_section_observation=cross_section_observation,
                caption_observations=caption_observations,
                page_id=resolved_page_id,
                rule_version=rule_version,
            )
        return _section_match_summary(decision, persisted)

    def list_section_matches(
        self,
        cross_section_id: str | None = None,
        page_id: str | None = None,
        statuses: tuple[str, ...] | None = None,
        write_back: bool = False,
    ) -> tuple[SectionMatchSummary, ...]:
        """Query persisted section candidate/formal match projections (read-only)."""

        _reject_write_back(write_back)
        if self.section_match_query_port is None:
            raise ToolModelError("NOT_FOUND", "section match query port is not configured")
        matches = self._read_call(
            lambda: self.section_match_query_port.list_section_matches(
                cross_section_id=cross_section_id,
                page_id=page_id,
                statuses=statuses,
            )
        )
        if not matches:
            raise ToolModelError("NOT_FOUND", "section matches were not found")
        return tuple(matches)

    def _find_cross_section_observation(self, cross_section_id: str):
        observations = self._read_call(lambda: self.semantic_repository.find_by_element(cross_section_id))
        return next(
            (item for item in observations if item.target_element_type == "CrossSection"),
            None,
        )

    def _write_section_decision(
        self,
        *,
        decision: SectionMatchDecision,
        cross_section_observation,
        caption_observations: tuple,
        page_id: str,
        rule_version: str,
    ) -> bool:
        if self.section_match_write_port is None:
            raise ToolModelError("SEMANTIC_EVIDENCE_UNAVAILABLE", "section match write port is not configured")
        if decision.status == "formal":
            self.section_match_write_port.write_section_relation(
                relation_type="MATCHES_SECTION_CAPTION",
                start_id=decision.cross_section_id,
                end_id=decision.matched_caption_id,
                properties={
                    "confirmation_method": "deterministic_rule",
                    "rule_version": rule_version,
                    "observation_ids": list(decision.observation_ids),
                },
            )
            return True
        if decision.status in {"candidate", "ambiguous"} and decision.candidate_count > 0:
            candidates = self.section_match_service.generate_candidates(
                cross_section_observation=cross_section_observation,
                caption_observations=caption_observations,
                page_id=page_id,
                rule_version=rule_version,
            )
            for candidate in candidates:
                self.section_match_write_port.write_section_relation(
                    relation_type="CANDIDATE_MATCHES_SECTION_CAPTION",
                    start_id=candidate.cross_section_id,
                    end_id=candidate.block_caption_id,
                    properties={
                        "status": "candidate",
                        "candidate_group_id": candidate.candidate_group_id,
                        "candidate_count": candidate.candidate_count,
                        "score": candidate.score,
                        "conflict_reason": candidate.conflict_reason,
                        "observation_ids": list(candidate.observation_ids),
                        "rule_version": rule_version,
                    },
                )
            return True
        return False

    def list_candidate_relations(
        self,
        page_id: str | None = None,
        block_id: str | None = None,
        relation_type: str | None = None,
        status: str | None = None,
        write_back: bool = False,
    ):
        _reject_write_back(write_back)
        if self.candidate_relation_port is None:
            raise ToolModelError("NOT_FOUND", "candidate relation port is not configured")
        candidates = self._read_call(
            lambda: self.candidate_relation_port.list_candidate_relations(
                page_id=page_id,
                block_id=block_id,
                relation_type=relation_type,
                status=status,
            )
        )
        if not candidates:
            raise ToolModelError("NOT_FOUND", "candidate relations were not found")
        return candidates

    def review_candidate_relation(
        self,
        candidate_group_id: str,
        decision: str,
        reviewer: str,
        reason: str,
        relation_spec: str,
        page_id: str,
        source_element_id: str,
        rule_version: str,
        candidates: tuple[dict[str, object], ...],
        evidence_refs: tuple[str, ...],
        repository: object | None = None,
        write_back: bool = False,
    ) -> CandidateReviewSummary:
        _require_text(candidate_group_id, "candidate_group_id")
        _require_text(reviewer, "reviewer")
        _require_text(reason, "reason")
        if decision not in {"accepted", "rejected", "unresolved"}:
            raise ToolModelError("INVALID_ARGUMENT", "decision must be accepted, rejected, or unresolved")
        request = CandidateReviewRequest(
            review_run_id=f"review:{candidate_group_id}",
            relation_spec=relation_spec,
            group_key=candidate_group_id,
            source_element_id=source_element_id,
            page_id=page_id,
            rule_version=rule_version,
            candidates=candidates,
            evidence_refs=evidence_refs,
            context={"reviewer": reviewer, "reason": reason, "decision": decision},
        )
        if not write_back:
            return CandidateReviewSummary(
                candidate_group_id=candidate_group_id,
                status=decision,
                persisted=False,
                promoted=False,
                reason=reason,
            )
        service = self.candidate_review_service or CandidateReviewService(
            _FixedReviewClient(decision=decision, reason=reason),
            repository=repository,
        )
        result = service.review_candidate_group(request)
        if result.status == "unresolved" and result.issue_category == "candidate_promotion_rule_failed":
            raise ToolModelError("CANDIDATE_REVIEW_REJECTED", result.reason or "candidate review rejected")
        return _candidate_review_summary(candidate_group_id, result, persisted=True)

    def _read_call(self, callback: Callable[[], T]) -> T:
        try:
            return callback()
        except ToolModelError:
            raise
        except Exception as exc:
            raise ToolModelError("NEO4J_UNAVAILABLE", "read port is unavailable") from exc


def _reject_write_back(write_back: bool) -> None:
    if write_back:
        raise ToolModelError("WRITE_BACK_FORBIDDEN", "read-only facade method cannot write back")


def _require_text(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ToolModelError("INVALID_ARGUMENT", f"{field_name} must be a non-empty string")


class _FixedReviewClient:
    def __init__(self, decision: str, reason: str):
        self.decision = decision
        self.reason = reason

    def review(self, request: CandidateReviewRequest) -> CandidateReviewResult:
        accepted_candidate_id = None
        if self.decision == "accepted":
            accepted_candidate_id = request.candidates[0]["candidate_id"]
        return CandidateReviewResult(
            review_run_id=request.review_run_id,
            relation_spec=request.relation_spec,
            status=self.decision,
            accepted_candidate_id=accepted_candidate_id,
            reason=self.reason,
        )


def _candidate_review_summary(
    candidate_group_id: str,
    result: CandidateReviewResult,
    persisted: bool,
) -> CandidateReviewSummary:
    return CandidateReviewSummary(
        candidate_group_id=candidate_group_id,
        status=result.status,
        persisted=persisted,
        promoted=persisted and result.status == "accepted",
        reason=result.reason,
        issue_category=result.issue_category,
    )


def _payload_meta(payload_store: object, payload_ref: str) -> tuple[str, str]:
    meta_getter = getattr(payload_store, "get_payload_meta", None)
    if meta_getter is not None:
        meta = meta_getter(payload_ref)
        return str(meta.get("content_hash") or payload_ref), str(meta.get("contract_version") or "1")
    if payload_ref.startswith("payload:"):
        return payload_ref.split(":", 1)[1], "1"
    return payload_ref, "1"


def _section_match_summary(
    decision: SectionMatchDecision,
    persisted: bool,
) -> SectionMatchSummary:
    return SectionMatchSummary(
        cross_section_id=decision.cross_section_id,
        match_status=decision.status,
        logical_key=decision.logical_key,
        symbol_system=decision.symbol_system.value if decision.symbol_system is not None else None,
        matched_caption_ids=(decision.matched_caption_id,) if decision.matched_caption_id else (),
        candidate_count=decision.candidate_count,
        conflict_reason=decision.conflict_reason,
        observation_ids=decision.observation_ids,
        rule_version=decision.rule_version,
        alias_rule_id=decision.alias_rule_id,
        fact_kind=decision.fact_kind,
        status="confirmed" if decision.status == "formal" else decision.status,
        evidence={"page_id": decision.page_id},
        persisted=persisted,
    )


__all__ = ("DrawingGraphToolFacade",)
