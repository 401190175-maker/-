"""Question understanding trace event builder.

生成轻量 ``QuestionUnderstandingEvent`` 并放入 ``TraceRecord.module_events``；
details 自动脱敏，不保存密钥、授权头、底层堆栈或查询语言片段。
"""

from __future__ import annotations

from typing import Any, Mapping

from .assistant_models import QuestionUnderstandingEvent


_SENSITIVE_KEYS = (
    "authorization",
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "traceback",
    "cypher",
)

_SENSITIVE_VALUE_MARKERS = (
    "authorization",
    "bearer",
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "traceback",
    "cypher",
)


class QuestionUnderstandingTraceBuilder:
    """构造问题理解阶段的轻量追溯事件。"""

    def __init__(self) -> None:
        self._counter = 0

    def build_event(
        self,
        request_id: str,
        stage: str,
        question_type: str,
        confidence: float | None = None,
        reason_codes: tuple[object, ...] = (),
        details: Mapping[str, Any] | None = None,
    ) -> QuestionUnderstandingEvent:
        """生成一个可放入 ``TraceRecord.module_events`` 的事件。"""

        self._counter += 1
        return QuestionUnderstandingEvent(
            event_id=f"event:{request_id}:{self._counter}",
            request_id=request_id,
            stage=stage,
            question_type=question_type,
            confidence=confidence,
            reason_codes=reason_codes,
            details=_sanitize_details(details),
        )


def _sanitize_details(details: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """移除敏感键，并把含敏感标记的字符串值替换为占位符。"""

    if details is None:
        return None
    cleaned: dict[str, Any] = {}
    for key, value in details.items():
        lowered_key = str(key).lower()
        if any(token in lowered_key for token in _SENSITIVE_KEYS):
            continue
        if isinstance(value, str) and any(
            token in value.lower() for token in _SENSITIVE_VALUE_MARKERS
        ):
            cleaned[key] = "[redacted]"
        else:
            cleaned[key] = value
    return cleaned
