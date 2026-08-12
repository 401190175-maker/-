"""Multi-intent splitting for question understanding.

只在连接词或明确列举式多意图时拆分；拆分不确定时返回
``multi_intent_ambiguous``，不丢弃任何子问题。
"""

from __future__ import annotations

from .assistant_models import AssistantScope, AssistantSubrequest, ReasonCode
from .assistant_question_rules import QuestionRouteResult, RuleQuestionRouter
from .assistant_question_text import QuestionTextNormalizer


_CONNECTORS = (",并", ",同时", ",以及", "并", "同时", "以及")


class IntentSplitter:
    """把明确列举式或连接式多意图问题拆分为稳定子请求。"""

    def __init__(
        self,
        router: RuleQuestionRouter | None = None,
        normalizer: QuestionTextNormalizer | None = None,
    ) -> None:
        self.router = router or RuleQuestionRouter()
        self.normalizer = normalizer or QuestionTextNormalizer()

    def split(
        self,
        question: str,
        route_result: QuestionRouteResult,
        scope: AssistantScope | None,
    ) -> tuple[AssistantSubrequest, ...]:
        """拆分问题；无连接词时返回单个子请求并保留歧义信息。"""

        normalized = self.normalizer.normalize(question)
        parts = self._split_parts(normalized)
        if len(parts) == 1:
            return self._single_subrequest(normalized, route_result, scope)
        subrequests = []
        for index, part in enumerate(parts, start=1):
            part_route = self.router.route(part, scope)
            ambiguities = list(part_route.ambiguities)
            unsupported = list(part_route.unsupported_parts)
            if part_route.question_type == "unknown_or_unsupported":
                unsupported.append(part)
            if part_route.question_type == "clarification_required":
                ambiguities.append(ReasonCode.MULTI_INTENT_AMBIGUOUS.value)
            subrequests.append(
                AssistantSubrequest(
                    subrequest_id=f"sub:{index}:{part_route.question_type}",
                    question_type=part_route.question_type,
                    scope=scope,
                    confidence=part_route.confidence,
                    ambiguities=tuple(dict.fromkeys(ambiguities)),
                    unsupported_parts=tuple(dict.fromkeys(unsupported)),
                )
            )
        return tuple(subrequests)

    def _split_parts(self, normalized: str) -> list[str]:
        """按稳定连接词切分；避免把“并且”当作连接词。"""

        for connector in _CONNECTORS:
            if connector == "并" and "并且" in normalized:
                continue
            if connector in normalized:
                head, _, tail = normalized.partition(connector)
                parts = [part.strip() for part in (head, tail) if part.strip()]
                if len(parts) >= 2:
                    return parts
        return [normalized]

    def _single_subrequest(
        self,
        normalized: str,
        route_result: QuestionRouteResult,
        scope: AssistantScope | None,
    ) -> tuple[AssistantSubrequest, ...]:
        """单个子请求：保留整句问题、路由歧义与 unsupported 部分。"""

        ambiguities = list(route_result.ambiguities)
        unsupported = list(route_result.unsupported_parts)
        if route_result.question_type == "clarification_required":
            ambiguities.append(ReasonCode.MULTI_INTENT_AMBIGUOUS.value)
        if route_result.question_type == "unknown_or_unsupported":
            unsupported.append(normalized)
        return (
            AssistantSubrequest(
                subrequest_id=f"sub:1:{route_result.question_type}",
                question_type=route_result.question_type,
                scope=scope,
                confidence=route_result.confidence,
                ambiguities=tuple(dict.fromkeys(ambiguities)),
                unsupported_parts=tuple(dict.fromkeys(unsupported)),
            ),
        )
