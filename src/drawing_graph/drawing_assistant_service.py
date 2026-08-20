"""Read-only drawing assistant orchestration (07).

本模块是产品级唯一总编排入口 ``DrawingAssistantService``，固定串联 01—06，
并内部组合 ``SubrequestProjector``、``RecognitionTargetGrouper`` 与
``AnswerPackageAggregator``。服务只依赖注入的 01—06 服务与
``DrawingGraphToolFacade`` 公开识别入口，不直接访问 driver、repository、
Cypher、CLI 或离线增强规则，也不创建 driver 或读取环境。
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .assistant_models import (
    ANSWER_CONTRACT_VERSION,
    AssistantExecutionPolicy,
    AssistantRequest,
    AssistantSubrequest,
    AnswerGenerationPolicy,
    AnswerGenerationRequest,
    AnswerPackage,
    AnswerStatus,
    MachineAnswer,
    QuestionType,
    QuestionUnderstandingResult,
    ReasonCode,
    RecognitionFailure,
    RecognitionTarget,
    Subanswer,
    TextRenderMode,
)
from .assistant_evidence_fusion_models import EvidenceFusionRequest
from .page_search_answer_builder import PageContentSearchAnswerBuilder
from .page_search_service import PageContentSearchService
from .tool_models import BBox, SemanticTargetInput


class ReadOnlyViolationError(ValueError):
    """只读授权违规时抛出的稳定领域错误。"""


class AssistantExecutionError(ValueError):
    """总编排基础设施失败时抛出的稳定错误。"""

    def __init__(self, reason_code: str | ReasonCode, message: str):
        self.reason_code = reason_code
        super().__init__(message)


_TERMINAL_QUESTION_TYPES = frozenset(
    {
        QuestionType.CLARIFICATION_REQUIRED.value,
        QuestionType.UNKNOWN_OR_UNSUPPORTED.value,
    }
)


class SubrequestProjector:
    """把单个 ``AssistantSubrequest`` 投影为带父 request ID 与自身 subrequest ID 的独立结果。"""

    def project(self, subrequest: AssistantSubrequest, request_id: str) -> QuestionUnderstandingResult:
        return QuestionUnderstandingResult(
            request_id=request_id,
            question_type=subrequest.question_type,
            subrequest_id=subrequest.subrequest_id,
            scope=subrequest.scope,
            required_evidence=subrequest.required_evidence,
            answer_requirements=subrequest.answer_requirements,
            confidence=subrequest.confidence,
            ambiguities=subrequest.ambiguities,
            unsupported_parts=subrequest.unsupported_parts,
        )

    def project_all(
        self,
        subrequests: tuple[AssistantSubrequest, ...],
        request_id: str,
    ) -> tuple[QuestionUnderstandingResult, ...]:
        return tuple(self.project(subrequest, request_id) for subrequest in subrequests)


class RecognitionTargetGrouper:
    """按 ``page_id`` 稳定分组识别目标，缺页目标转为结构化失败。"""

    def group(
        self,
        targets: tuple[RecognitionTarget, ...],
    ) -> tuple[tuple[tuple[str, tuple[RecognitionTarget, ...]], ...], tuple[RecognitionFailure, ...]]:
        failures: list[RecognitionFailure] = []
        for target in targets:
            if not target.page_id:
                failures.append(
                    RecognitionFailure(
                        page_id=None,
                        target_ids=(target.target_id,),
                        reason_code=ReasonCode.TARGET_LOCATION_MISSING,
                        message=f"recognition target {target.target_id} has no page_id",
                    )
                )

        grouped: dict[str, list[RecognitionTarget]] = {}
        for target in targets:
            if not target.page_id:
                continue
            grouped.setdefault(target.page_id, []).append(target)

        pages = tuple(
            (page_id, tuple(grouped[page_id]))
            for page_id in sorted(grouped)
        )
        return pages, tuple(failures)


def _to_bbox(bbox: Mapping[str, float] | None) -> BBox | None:
    if bbox is None:
        return None
    return BBox(
        x_min=float(bbox["x_min"]),
        y_min=float(bbox["y_min"]),
        x_max=float(bbox["x_max"]),
        y_max=float(bbox["y_max"]),
    )


def _to_semantic_target(target: RecognitionTarget) -> SemanticTargetInput:
    return SemanticTargetInput(
        target_id=target.target_id,
        page_id=target.page_id,
        target_type=target.target_type,
        task_type=target.task_type,
        target_element_id=target.target_element_id,
        required_outputs=target.required_outputs,
        bbox=_to_bbox(target.bbox),
        normalized_bbox=_to_bbox(target.normalized_bbox),
        context_element_ids=target.context_element_ids,
    )


class AnswerPackageAggregator:
    """按原始子请求顺序聚合 Subanswer、claim、citation、warning 与整体状态。"""

    def __init__(self, template_renderer=None) -> None:
        from .assistant_answer_templates import ChineseAnswerTemplateRenderer

        self.template_renderer = template_renderer or ChineseAnswerTemplateRenderer()

    def aggregate(
        self,
        results: tuple[tuple[str, AnswerPackage], ...],
        request_id: str,
        question_type: str,
        scope,
    ) -> AnswerPackage:
        subanswers = tuple(
            self._to_subanswer(subrequest_id, package)
            for subrequest_id, package in results
        )
        claims = _dedup_claims(
            claim for _, package in results for claim in package.claims
        )
        citations = _dedup_citations(
            citation for _, package in results for citation in package.citations
        )
        warnings = _dedup_strings(
            warning for _, package in results for warning in package.warnings
        )
        unsupported_parts = _dedup_strings(
            part for _, package in results for part in package.unsupported_parts
        )
        run_ids = _dedup_strings(
            run_id for _, package in results for run_id in package.recognition_run_ids
        )
        follow_ups = _dedup_strings(
            action for _, package in results for action in package.follow_up_actions
        )
        reason_codes = _dedup_reason_codes(
            code for _, package in results for code in package.reason_codes
        )

        status = self._overall_status(subanswers)
        machine = MachineAnswer(
            answer_contract_version=ANSWER_CONTRACT_VERSION,
            request_id=request_id,
            question_type=question_type,
            scope=scope,
            status=status,
            subanswers=subanswers,
            claims=claims,
            citations=citations,
            warnings=warnings,
            unsupported_parts=unsupported_parts,
            recognition_run_ids=run_ids,
            follow_up_actions=follow_ups,
            reason_codes=reason_codes,
        )
        text = self.template_renderer.render(machine)
        return AnswerPackage(
            request_id=request_id,
            question_type=question_type,
            scope=scope,
            status=status.value,
            machine_answer=machine,
            text_answer=text,
            claims=claims,
            citations=citations,
            warnings=warnings,
            unsupported_parts=unsupported_parts,
            recognition_run_ids=run_ids,
            follow_up_actions=follow_ups,
            subanswers=subanswers,
            reason_codes=reason_codes,
            render_mode=TextRenderMode.TEMPLATE,
        )

    @staticmethod
    def _to_subanswer(subrequest_id: str, package: AnswerPackage) -> Subanswer:
        machine = package.machine_answer
        status = machine.status if isinstance(machine, MachineAnswer) else AnswerStatus(package.status)
        return Subanswer(
            subrequest_id=subrequest_id,
            question_type=package.question_type,
            scope=package.scope,
            status=status,
            claim_ids=tuple(claim.claim_id for claim in package.claims),
            citation_ids=tuple(citation.citation_id for citation in package.citations),
            warnings=package.warnings,
            unsupported_parts=package.unsupported_parts,
        )

    @staticmethod
    def _overall_status(subanswers: Sequence[Subanswer]) -> AnswerStatus:
        statuses = [subanswer.status for subanswer in subanswers]
        if not statuses:
            return AnswerStatus.UNSUPPORTED
        if all(status is AnswerStatus.CLARIFICATION_REQUIRED for status in statuses):
            return AnswerStatus.CLARIFICATION_REQUIRED
        if all(status is AnswerStatus.UNSUPPORTED for status in statuses):
            return AnswerStatus.UNSUPPORTED
        if all(status is AnswerStatus.RECOGNITION_FAILED for status in statuses):
            return AnswerStatus.RECOGNITION_FAILED
        if all(status is AnswerStatus.ANSWERED for status in statuses):
            return AnswerStatus.ANSWERED
        return AnswerStatus.PARTIAL


def _dedup_claims(claims):
    seen: set[str] = set()
    result = []
    for claim in claims:
        if claim.claim_id not in seen:
            seen.add(claim.claim_id)
            result.append(claim)
    return tuple(result)


def _dedup_citations(citations):
    seen: set[str] = set()
    result = []
    for citation in citations:
        if citation.citation_id not in seen:
            seen.add(citation.citation_id)
            result.append(citation)
    return tuple(result)


def _dedup_strings(values):
    return tuple(dict.fromkeys(values))


def _dedup_reason_codes(codes):
    seen: set[str] = set()
    result = []
    for code in codes:
        key = code.value if isinstance(code, ReasonCode) else str(code)
        if key not in seen:
            seen.add(key)
            result.append(code)
    return tuple(result)


class DrawingAssistantService:
    """产品级只读总编排入口。"""

    def __init__(
        self,
        question_service: object,
        retrieval_service: object,
        gap_decision_service: object,
        fusion_service: object,
        answer_service: object,
        facade: object | None = None,
        projector: SubrequestProjector | None = None,
        target_grouper: RecognitionTargetGrouper | None = None,
        aggregator: AnswerPackageAggregator | None = None,
        traceability_service: object | None = None,
        page_search_service: PageContentSearchService | None = None,
        page_search_answer_builder: PageContentSearchAnswerBuilder | None = None,
        page_search_recognize_limit: int = 10,
    ) -> None:
        self.question_service = question_service
        self.retrieval_service = retrieval_service
        self.gap_decision_service = gap_decision_service
        self.fusion_service = fusion_service
        self.answer_service = answer_service
        self.facade = facade
        self.projector = projector or SubrequestProjector()
        self.target_grouper = target_grouper or RecognitionTargetGrouper()
        self.aggregator = aggregator or AnswerPackageAggregator()
        self.traceability_service = traceability_service
        self.page_search_service = page_search_service or (
            PageContentSearchService(self.facade) if self.facade is not None else None
        )
        self.page_search_answer_builder = page_search_answer_builder or PageContentSearchAnswerBuilder()
        self.page_search_recognize_limit = page_search_recognize_limit

    def answer(
        self,
        request: AssistantRequest,
        policy: AssistantExecutionPolicy | None = None,
    ) -> AnswerPackage:
        policy = policy or AssistantExecutionPolicy()
        self._validate_read_only(request)

        question_result = self.question_service.understand(request)
        if self._is_terminal(question_result):
            package = self._terminal_answer(request, question_result, policy)
        elif question_result.subrequests:
            self._enforce_limit(
                len(question_result.subrequests),
                policy.max_subrequests,
                ReasonCode.MAX_SUBREQUESTS_EXCEEDED,
                "subrequests",
            )
            package = self._answer_multi_intent(request, question_result, policy)
        else:
            package = self._answer_single_intent(request, question_result, policy)

        self._record_trace(request, question_result, package)
        return package

    def _record_trace(
        self,
        request: AssistantRequest,
        question_result: QuestionUnderstandingResult,
        package: AnswerPackage,
    ) -> None:
        if self.traceability_service is None:
            return
        try:
            self.traceability_service.record_answer_trace(
                request=request,
                question_result=question_result,
                answer_package=package,
            )
        except Exception:  # noqa: BLE001 - trace failure must not affect the answer.
            return

    def _answer_single_intent(
        self,
        request: AssistantRequest,
        question_result: QuestionUnderstandingResult,
        policy: AssistantExecutionPolicy,
    ) -> AnswerPackage:
        if question_result.question_type == QuestionType.PAGE_CONTENT_SEARCH.value:
            return self._answer_page_content_search(request, question_result)
        try:
            retrieval_bundle = self.retrieval_service.retrieve(
                question_result,
                policy.retrieval_policy,
            )
        except Exception as exc:  # noqa: BLE001
            raise AssistantExecutionError("retrieval_failed", "required retrieval failed") from exc

        decision = self.gap_decision_service.decide(
            question_result,
            retrieval_bundle,
            policy.recognition_policy,
        )
        recognition_results, recognition_failures = self._execute_recognition(
            request,
            decision,
            policy,
        )
        bundle = self._fuse(
            request,
            question_result,
            retrieval_bundle,
            decision,
            recognition_results,
        )
        generation_request = AnswerGenerationRequest(
            assistant_request=request,
            question_result=question_result,
            evidence_bundle=bundle,
            subrequest_id=question_result.subrequest_id,
            stage_warnings=decision.warnings,
            recognition_failures=recognition_failures,
        )
        return self.answer_service.generate(
            generation_request,
            self._answer_policy(policy),
        )

    def _answer_page_content_search(
        self,
        request: AssistantRequest,
        question_result: QuestionUnderstandingResult,
    ) -> AnswerPackage:
        scope = question_result.scope
        if scope is None or scope.drawing_set_id is None:
            raise AssistantExecutionError(
                "missing_scope",
                "drawing_set_id is required for page content search",
            )
        if self.page_search_service is None:
            raise AssistantExecutionError(
                "search_unavailable",
                "page content search service is not configured",
            )
        result = self.page_search_service.search(
            scope.drawing_set_id,
            request.question,
            allow_recognition=request.allow_recognition,
            recognize_page_limit=self.page_search_recognize_limit,
        )
        return self.page_search_answer_builder.build(
            request.request_id,
            scope,
            result,
        )

    def _execute_recognition(
        self,
        request: AssistantRequest,
        decision,
        policy: AssistantExecutionPolicy,
    ) -> tuple[tuple[object, ...], tuple[RecognitionFailure, ...]]:
        if not request.allow_recognition or not decision.selected_targets:
            return (), ()
        pages, missing_failures = self.target_grouper.group(decision.selected_targets)
        self._enforce_limit(
            len(pages),
            policy.max_page_groups,
            ReasonCode.MAX_PAGE_GROUPS_EXCEEDED,
            "page groups",
        )
        results: list[object] = []
        failures: list[RecognitionFailure] = list(missing_failures)
        for page_id, targets in pages:
            semantic_targets = tuple(_to_semantic_target(target) for target in targets)
            try:
                results.append(
                    self.facade.recognize_semantic_targets(
                        semantic_targets,
                        write_back=False,
                    )
                )
            except Exception:  # noqa: BLE001
                failures.append(
                    RecognitionFailure(
                        page_id=page_id,
                        target_ids=tuple(target.target_id for target in targets),
                        reason_code=ReasonCode.RECOGNITION_FAILED,
                        message=f"recognition failed for page {page_id}",
                    )
                )
        return tuple(results), tuple(failures)

    def _fuse(
        self,
        request: AssistantRequest,
        question_result: QuestionUnderstandingResult,
        retrieval_bundle,
        decision,
        recognition_results: tuple[object, ...],
    ):
        fusion_request = EvidenceFusionRequest(
            assistant_request=request,
            question_result=question_result,
            retrieval_bundle=retrieval_bundle,
            semantic_gap_decision=decision,
            recognition_results=tuple(recognition_results),
            write_back_policy=None,
        )
        return self.fusion_service.fuse(fusion_request)

    def _answer_multi_intent(
        self,
        request: AssistantRequest,
        question_result: QuestionUnderstandingResult,
        policy: AssistantExecutionPolicy,
    ) -> AnswerPackage:
        results: list[tuple[str, AnswerPackage]] = []
        for subrequest in question_result.subrequests:
            projected = self.projector.project(subrequest, request.request_id)
            subpackage = self._answer_single_intent(request, projected, policy)
            results.append((subrequest.subrequest_id, subpackage))
        return self.aggregator.aggregate(
            tuple(results),
            request.request_id,
            question_result.question_type,
            question_result.scope,
        )

    @staticmethod
    def _validate_read_only(request: AssistantRequest) -> None:
        if request.allow_write_back:
            raise ReadOnlyViolationError(
                "write-back is not allowed in the read-only product assistant"
            )

    @staticmethod
    def _is_terminal(question_result: QuestionUnderstandingResult) -> bool:
        return (
            not question_result.subrequests
            and question_result.question_type in _TERMINAL_QUESTION_TYPES
        )

    def _terminal_answer(
        self,
        request: AssistantRequest,
        question_result: QuestionUnderstandingResult,
        policy: AssistantExecutionPolicy,
    ) -> AnswerPackage:
        generation_request = AnswerGenerationRequest(
            assistant_request=request,
            question_result=question_result,
            evidence_bundle=None,
            subrequest_id=question_result.subrequest_id,
        )
        return self.answer_service.generate(
            generation_request,
            self._answer_policy(policy),
        )

    @staticmethod
    def _answer_policy(policy: AssistantExecutionPolicy) -> AnswerGenerationPolicy:
        return AnswerGenerationPolicy(
            enable_constrained_text=policy.enable_constrained_text,
            max_claims=policy.max_claims,
            max_citations=policy.max_citations,
        )

    @staticmethod
    def _enforce_limit(count: int, limit: int | None, reason_code: ReasonCode, name: str) -> None:
        if limit is not None and count > limit:
            raise AssistantExecutionError(
                reason_code,
                f"{name} exceed the resource limit ({count} > {limit})",
            )
