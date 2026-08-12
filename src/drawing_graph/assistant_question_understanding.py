"""Question understanding service orchestration.

把 ``AssistantRequest`` 编排为 ``QuestionUnderstandingResult``：
规范化 -> scope 解析 -> 规则路由 -> 多意图拆分 -> 证据需求 -> 澄清策略。
本模块不访问数据库、不调用 ``DrawingGraphToolFacade``、不调用真实模型客户端，
且不会把问题文本推断为写回授权。
"""

from __future__ import annotations

from .assistant_clarification import ClarificationPolicy
from .assistant_evidence_templates import EvidenceRequirementFactory
from .assistant_intent_splitter import IntentSplitter
from .assistant_models import (
    AssistantRequest,
    AssistantScope,
    AssistantSubrequest,
    QuestionType,
    QuestionUnderstandingResult,
)
from .assistant_question_llm import QuestionUnderstandingModelClient
from .assistant_question_rules import RuleQuestionRouter
from .assistant_question_text import QuestionTextNormalizer
from .assistant_question_trace import QuestionUnderstandingTraceBuilder
from .assistant_scope_resolution import ScopeResolver


class QuestionUnderstandingService:
    """问题理解闭环入口：把请求稳定转换为下游可消费的结果。"""

    def __init__(
        self,
        normalizer: QuestionTextNormalizer | None = None,
        scope_resolver: ScopeResolver | None = None,
        router: RuleQuestionRouter | None = None,
        splitter: IntentSplitter | None = None,
        evidence_factory: EvidenceRequirementFactory | None = None,
        clarification_policy: ClarificationPolicy | None = None,
        trace_builder: QuestionUnderstandingTraceBuilder | None = None,
        model_client: QuestionUnderstandingModelClient | None = None,
    ) -> None:
        self.normalizer = normalizer or QuestionTextNormalizer()
        self.scope_resolver = scope_resolver or ScopeResolver()
        self.router = router or RuleQuestionRouter()
        self.splitter = splitter or IntentSplitter(router=self.router)
        self.evidence_factory = evidence_factory or EvidenceRequirementFactory()
        self.clarification_policy = clarification_policy or ClarificationPolicy()
        self.trace_builder = trace_builder or QuestionUnderstandingTraceBuilder()
        # 规则优先阶段不调用模型；模型客户端仅作为后续受约束适配口预留。
        self.model_client = model_client

    def understand(
        self,
        request: AssistantRequest,
    ) -> QuestionUnderstandingResult:
        """执行问题理解编排并返回稳定结果。"""

        normalized = self.normalizer.normalize(request.question)
        scope_result = self.scope_resolver.resolve(
            request.question,
            request.scope_hint,
            request.conversation_context,
        )
        route_result = self.router.route(normalized, scope_result.scope)
        scope = scope_result.scope

        if route_result.question_type == QuestionType.UNKNOWN_OR_UNSUPPORTED.value:
            return QuestionUnderstandingResult(
                request_id=request.request_id,
                question_type=QuestionType.UNKNOWN_OR_UNSUPPORTED.value,
                scope=scope,
                confidence=route_result.confidence,
                ambiguities=route_result.ambiguities,
                unsupported_parts=route_result.unsupported_parts
                or ("question_type",),
            )

        subrequests = self.splitter.split(normalized, route_result, scope)
        if len(subrequests) > 1:
            return self._multi_intent_result(request, subrequests, scope)

        subrequest = subrequests[0]
        requirements = self.evidence_factory.build(
            subrequest.question_type,
            scope,
            request,
        )
        decision = self.clarification_policy.evaluate(
            request,
            route_result,
            scope_result,
            requirements,
        )
        needs_clarification = decision.required or (
            subrequest.question_type == QuestionType.CLARIFICATION_REQUIRED.value
        )
        if needs_clarification:
            return QuestionUnderstandingResult(
                request_id=request.request_id,
                question_type=QuestionType.CLARIFICATION_REQUIRED.value,
                scope=scope,
                required_evidence=(),
                answer_requirements=decision.items,
                confidence=route_result.confidence,
                ambiguities=_merge_texts(
                    route_result.ambiguities,
                    subrequest.ambiguities,
                    decision.reason_codes,
                ),
                unsupported_parts=_merge_texts(
                    route_result.unsupported_parts,
                    subrequest.unsupported_parts,
                ),
            )
        if not requirements:
            return QuestionUnderstandingResult(
                request_id=request.request_id,
                question_type=QuestionType.UNKNOWN_OR_UNSUPPORTED.value,
                scope=scope,
                confidence=route_result.confidence,
                ambiguities=_merge_texts(
                    route_result.ambiguities,
                    subrequest.ambiguities,
                ),
                unsupported_parts=("evidence_template",),
            )
        return QuestionUnderstandingResult(
            request_id=request.request_id,
            question_type=subrequest.question_type,
            scope=scope,
            required_evidence=requirements,
            confidence=route_result.confidence,
            ambiguities=_merge_texts(
                route_result.ambiguities,
                subrequest.ambiguities,
            ),
            unsupported_parts=_merge_texts(
                route_result.unsupported_parts,
                subrequest.unsupported_parts,
            ),
        )

    def _multi_intent_result(
        self,
        request: AssistantRequest,
        subrequests: tuple[AssistantSubrequest, ...],
        scope: AssistantScope | None,
    ) -> QuestionUnderstandingResult:
        """多意图结果：每个子请求携带独立证据需求，不丢弃任何子问题。"""

        built = []
        for subrequest in subrequests:
            requirements = self.evidence_factory.build(
                subrequest.question_type,
                scope,
                request,
            )
            built.append(
                AssistantSubrequest(
                    subrequest_id=subrequest.subrequest_id,
                    question_type=subrequest.question_type,
                    scope=scope,
                    required_evidence=requirements,
                    confidence=subrequest.confidence,
                    ambiguities=subrequest.ambiguities,
                    unsupported_parts=subrequest.unsupported_parts,
                )
            )
        any_ambiguous = any(
            item.question_type == QuestionType.CLARIFICATION_REQUIRED.value
            or item.ambiguities
            for item in built
        )
        question_type = (
            QuestionType.CLARIFICATION_REQUIRED.value
            if any_ambiguous
            else "multi_intent"
        )
        return QuestionUnderstandingResult(
            request_id=request.request_id,
            question_type=question_type,
            scope=scope,
            subrequests=tuple(built),
            confidence=subrequests[0].confidence,
            ambiguities=_merge_texts(
                *(item.ambiguities for item in built),
            ),
            unsupported_parts=_merge_texts(
                *(item.unsupported_parts for item in built),
            ),
        )


def _merge_texts(*groups: tuple[str, ...]) -> tuple[str, ...]:
    """按出现顺序合并字符串元组并去重。"""

    merged: list[str] = []
    for group in groups:
        for item in group:
            if item not in merged:
                merged.append(item)
    return tuple(merged)
