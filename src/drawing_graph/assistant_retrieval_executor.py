"""Read-only graph retrieval executor for the product assistant layer.

执行器只按 ``RetrievalPlan`` 调用 ``DrawingGraphToolFacade`` 白名单内的
只读方法，记录 ``SourceCallRecord``，把底层异常转为稳定原因码并脱敏；
不调用识别、审核、断面写回或任何持久化能力。
"""

from __future__ import annotations

from .assistant_models import (
    RawRetrievalResult,
    ReasonCode,
    RetrievalPlan,
    RetrievalStatus,
    RetrievalStep,
    SourceCallRecord,
)

_SENSITIVE_TOKENS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "traceback",
)
_QUERY_MARKER = "MATCH" + " ("


class RetrievalExecutor:
    """按检索计划执行 facade 只读调用并生成审计记录。"""

    ALLOWED_FACADE_METHODS = frozenset(
        {
            "list_drawing_sets",
            "list_pages",
            "get_page_source_facts",
            "get_block_trace",
            "get_block_relations",
            "list_text_observations",
            "list_interpretations",
            "get_semantic_payload",
            "list_candidate_relations",
            "list_section_matches",
        }
    )

    def execute(
        self,
        plan: RetrievalPlan,
        facade: object,
    ) -> tuple[RawRetrievalResult, tuple[SourceCallRecord, ...]]:
        """执行计划并返回 (原始结果, source call 记录)。"""

        results: dict[str, object] = {}
        calls: list[SourceCallRecord] = []
        executed_keys: dict[str, object] = {}
        executed_counts: dict[str, int] = {}
        truncated: list[str] = []
        for step in plan.steps:
            if step.facade_method not in self.ALLOWED_FACADE_METHODS:
                calls.append(
                    SourceCallRecord(
                        source_call_id=f"call:{step.step_id}",
                        step_id=step.step_id,
                        facade_method=step.facade_method,
                        status=RetrievalStatus.ERROR,
                        reason_code=ReasonCode.UNSUPPORTED_EVIDENCE_TYPE,
                        warning=f"unsupported facade method: {step.facade_method}",
                    )
                )
                continue
            if step.dedupe_key is not None and step.dedupe_key in executed_keys:
                results[step.step_id] = executed_keys[step.dedupe_key]
                calls.append(
                    SourceCallRecord(
                        source_call_id=f"call:{step.step_id}",
                        step_id=step.step_id,
                        facade_method=step.facade_method,
                        status=RetrievalStatus.OK,
                        result_count=executed_counts[step.dedupe_key],
                    )
                )
                continue
            try:
                method = getattr(facade, step.facade_method)
                result = method(**dict(step.parameters))
            except Exception as exc:
                calls.append(
                    SourceCallRecord(
                        source_call_id=f"call:{step.step_id}",
                        step_id=step.step_id,
                        facade_method=step.facade_method,
                        status=RetrievalStatus.ERROR,
                        reason_code=_classify_error(step.facade_method, exc),
                        warning=_sanitize_error_message(str(exc)),
                    )
                )
                continue
            result_count = _result_count(result)
            results[step.step_id] = result
            if step.dedupe_key is not None:
                executed_keys[step.dedupe_key] = result
                executed_counts[step.dedupe_key] = result_count
            if step.limit is not None and result_count > step.limit:
                truncated.append(step.step_id)
            calls.append(
                SourceCallRecord(
                    source_call_id=f"call:{step.step_id}",
                    step_id=step.step_id,
                    facade_method=step.facade_method,
                    status=RetrievalStatus.OK,
                    result_count=result_count,
                )
            )
        return (
            RawRetrievalResult(results=results, truncated_step_ids=tuple(truncated)),
            tuple(calls),
        )


def _result_count(result: object) -> int:
    """计算一次 facade 返回的结果数量；None 计 0，序列计长度，其余计 1。"""

    if result is None:
        return 0
    if isinstance(result, (list, tuple)):
        return len(result)
    return 1


def _classify_error(facade_method: str, exc: Exception) -> ReasonCode:
    """把 facade 异常映射为稳定原因码，不透出底层细节。"""

    if facade_method == "get_semantic_payload" and getattr(exc, "category", None) == "PAYLOAD_UNAVAILABLE":
        return ReasonCode.PAYLOAD_UNAVAILABLE
    return ReasonCode.FACADE_CALL_FAILED


def _sanitize_error_message(message: str) -> str:
    """脱敏错误消息：含敏感/底层关键字时返回通用文案。"""

    lowered = message.lower()
    if _QUERY_MARKER.lower() in lowered or any(token in lowered for token in _SENSITIVE_TOKENS):
        return "sensitive or low-level backend detail is unavailable"
    return message
