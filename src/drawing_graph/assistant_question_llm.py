"""Constrained model client protocol for question understanding.

本模块只定义受约束的候选结果与可注入协议；默认不启用真实模型，
不读取密钥、不导入外部模型客户端、不发起网络请求。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol, runtime_checkable

from .assistant_models import AssistantScope, QuestionType, ReasonCode


_ALLOWED_OUTPUT_KEYS = frozenset(
    {"question_type", "confidence", "ambiguities", "unsupported_parts"}
)


@dataclass(frozen=True)
class QuestionUnderstandingCandidate:
    """受约束的问题理解候选：只承载问题类型、置信度与歧义信息。"""

    question_type: str
    confidence: float
    ambiguities: tuple[str, ...] = field(default_factory=tuple)
    unsupported_parts: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.question_type, str) or not self.question_type.strip():
            raise ValueError("question_type must be a non-empty string")
        if not isinstance(self.confidence, (int, float)) or isinstance(self.confidence, bool):
            raise ValueError("confidence must be numeric")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        for field_name in ("ambiguities", "unsupported_parts"):
            values = getattr(self, field_name)
            if not isinstance(values, tuple) or not all(
                isinstance(item, str) and item.strip() for item in values
            ):
                raise ValueError(f"{field_name} must be a tuple of non-empty strings")


@runtime_checkable
class QuestionUnderstandingModelClient(Protocol):
    """可注入文本模型协议；实现必须返回受约束候选结果。"""

    def understand(
        self,
        question: str,
        scope: AssistantScope | None = None,
    ) -> QuestionUnderstandingCandidate:
        """把问题文本转为受约束候选；不得生成事实、写回或查询语言。"""

        ...


@dataclass(frozen=True)
class ModelOutputValidation:
    """模型输出校验结果：合法候选或稳定原因码。"""

    candidate: QuestionUnderstandingCandidate | None
    reason_codes: tuple[str, ...] = field(default_factory=tuple)


class FakeQuestionUnderstandingModelClient:
    """可测试 fake 客户端：返回配置候选，绝不发起网络请求。"""

    def __init__(self, candidate: QuestionUnderstandingCandidate | None = None) -> None:
        self.candidate = candidate

    def understand(
        self,
        question: str,
        scope: AssistantScope | None = None,
    ) -> QuestionUnderstandingCandidate:
        del question, scope
        if self.candidate is not None:
            return self.candidate
        return QuestionUnderstandingCandidate(
            question_type=QuestionType.UNKNOWN_OR_UNSUPPORTED.value,
            confidence=0.0,
        )


def validate_model_output(raw: Mapping[str, object]) -> ModelOutputValidation:
    """校验模型输出；非法输出返回 ``model_output_invalid``。"""

    try:
        if not isinstance(raw, Mapping):
            raise ValueError("raw must be a mapping")
        if set(raw) - _ALLOWED_OUTPUT_KEYS:
            raise ValueError("output contains unexpected keys")
        question_type = raw.get("question_type")
        confidence = raw.get("confidence")
        if not isinstance(question_type, str):
            raise ValueError("question_type must be a string")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            raise ValueError("confidence must be numeric")
        QuestionType(question_type)
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        ambiguities = _read_text_tuple(raw.get("ambiguities", ()), "ambiguities")
        unsupported_parts = _read_text_tuple(
            raw.get("unsupported_parts", ()),
            "unsupported_parts",
        )
    except (TypeError, ValueError):
        return ModelOutputValidation(
            None,
            (ReasonCode.MODEL_OUTPUT_INVALID.value,),
        )
    return ModelOutputValidation(
        candidate=QuestionUnderstandingCandidate(
            question_type=question_type,
            confidence=float(confidence),
            ambiguities=ambiguities,
            unsupported_parts=unsupported_parts,
        ),
    )


def _read_text_tuple(value: object, field_name: str) -> tuple[str, ...]:
    """把模型输出中的序列字段规整为字符串元组。"""

    if isinstance(value, (str, bytes)) or not isinstance(value, (tuple, list)):
        raise ValueError(f"{field_name} must be a sequence of strings")
    items = tuple(value)
    if not all(isinstance(item, str) and item.strip() for item in items):
        raise ValueError(f"{field_name} must contain only non-empty strings")
    return items
