"""Deterministic Chinese rule routing for question understanding.

路由器只做文本分类，不访问图谱、不调用模型；无法唯一分类时返回
澄清或 unsupported，而不是猜测。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .assistant_models import AssistantScope, QuestionType, ReasonCode
from .assistant_question_text import QuestionTextNormalizer


@dataclass(frozen=True)
class QuestionRouteResult:
    """规则路由结果：问题类型、置信度、命中规则与歧义/不支持部分。"""

    question_type: str
    confidence: float
    matched_rules: tuple[str, ...] = field(default_factory=tuple)
    unsupported_parts: tuple[str, ...] = field(default_factory=tuple)
    ambiguities: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.question_type, str) or not self.question_type.strip():
            raise ValueError("question_type must be a non-empty string")
        if not isinstance(self.confidence, (int, float)) or isinstance(self.confidence, bool):
            raise ValueError("confidence must be numeric")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        for field_name in ("matched_rules", "unsupported_parts", "ambiguities"):
            values = getattr(self, field_name)
            if not isinstance(values, tuple) or not all(
                isinstance(item, str) and item.strip() for item in values
            ):
                raise ValueError(f"{field_name} must be a tuple of non-empty strings")


@dataclass(frozen=True)
class _Rule:
    """一条可测试的确定性路由规则。"""

    rule_id: str
    question_type: str
    patterns: tuple[tuple[str, ...], ...]
    excluded: tuple[str, ...] = ()

    def matches(self, text: str) -> bool:
        """任一模式全部命中即匹配；命中排除词则整条规则不匹配。"""

        if any(token in text for token in self.excluded):
            return False
        return any(
            all(token in text for token in pattern)
            for pattern in self.patterns
        )


_DEFAULT_RULES = (
    _Rule(
        rule_id="rule:page_summary",
        question_type=QuestionType.PAGE_SUMMARY.value,
        patterns=(
            ("主要讲什么",),
            ("页面内容",),
            ("总结了什么",),
            ("概述",),
            ("page", "内容"),
        ),
    ),
    _Rule(
        rule_id="rule:block_relations",
        question_type=QuestionType.BLOCK_RELATIONS.value,
        patterns=(
            ("图块", "关系"),
            ("block", "关系"),
            ("块", "关系"),
        ),
        excluded=("候选关系",),
    ),
    _Rule(
        rule_id="rule:block_semantic_identification",
        question_type=QuestionType.BLOCK_SEMANTIC_IDENTIFICATION.value,
        patterns=(
            ("是什么构件",),
            ("构件", "是什么"),
        ),
    ),
    _Rule(
        rule_id="rule:block_identity_short",
        question_type=QuestionType.BLOCK_SEMANTIC_IDENTIFICATION.value,
        patterns=(
            ("是什么",),
        ),
        excluded=(
            "元素",
            "图",
            "页",
            "候选",
            "关系",
            "标题",
            "断面",
            "表",
            "册",
            "构件",
            "来源",
            "出处",
            "溯源",
        ),
    ),
    _Rule(
        rule_id="rule:element_text_or_meaning",
        question_type=QuestionType.ELEMENT_TEXT_OR_MEANING.value,
        patterns=(
            ("元素", "是什么"),
            ("element", "是什么"),
            ("元素", "文字"),
            ("element", "文字"),
            ("文字", "是什么"),
            ("内容", "是什么"),
            ("元素", "内容"),
            ("element", "内容"),
        ),
    ),
    _Rule(
        rule_id="rule:candidate_relations",
        question_type=QuestionType.CANDIDATE_RELATIONS.value,
        patterns=(
            ("候选关系",),
        ),
    ),
    _Rule(
        rule_id="rule:page_content_search",
        question_type=QuestionType.PAGE_CONTENT_SEARCH.value,
        patterns=(
            ("哪一页",),
            ("哪些图",),
            ("哪几张图",),
            ("哪几页",),
            ("哪块",),
            ("关于", "图"),
            ("涉及",),
            ("在", "哪一页"),
            ("查找", "图"),
            ("搜索", "图"),
        ),
        excluded=("关系",),
    ),
    _Rule(
        rule_id="rule:section_matches",
        question_type=QuestionType.SECTION_MATCHES.value,
        patterns=(
            ("对应", "标题"),
            ("断面", "匹配"),
            ("标题", "匹配"),
            ("对应哪个标题",),
            ("剖面", "图块"),
            ("在哪个图块",),
        ),
    ),
    _Rule(
        rule_id="rule:table_caption_status",
        question_type=QuestionType.TABLE_CAPTION_STATUS.value,
        patterns=(
            ("表题",),
            ("表格", "标题"),
            ("table", "标题"),
            ("caption",),
        ),
    ),
    _Rule(
        rule_id="rule:drawing_diagnostic",
        question_type=QuestionType.DRAWING_DIAGNOSTIC.value,
        patterns=(
            ("诊断",),
            ("图纸问题",),
        ),
    ),
    _Rule(
        rule_id="rule:source_trace",
        question_type=QuestionType.SOURCE_TRACE.value,
        patterns=(
            ("来源",),
            ("溯源",),
            ("出处",),
        ),
    ),
    _Rule(
        rule_id="rule:comparison",
        question_type=QuestionType.COMPARISON.value,
        patterns=(
            ("比较",),
            ("对比",),
            ("区别",),
            ("差异",),
        ),
    ),
)


class RuleQuestionRouter:
    """按规范化中文问题与稳定 ID 路由到首版问题类型。"""

    def __init__(self, normalizer: QuestionTextNormalizer | None = None) -> None:
        self.normalizer = normalizer or QuestionTextNormalizer()

    def route(
        self,
        question: str,
        scope: AssistantScope | None,
    ) -> QuestionRouteResult:
        """返回无命中、单命中或多命中的稳定路由结果。"""

        del scope
        normalized = self.normalizer.normalize(question)
        matched = [
            rule
            for rule in _DEFAULT_RULES
            if rule.matches(normalized)
        ]
        if not matched:
            return QuestionRouteResult(
                question_type=QuestionType.UNKNOWN_OR_UNSUPPORTED.value,
                confidence=0.0,
                unsupported_parts=("question_type",),
            )
        unique_types = list(dict.fromkeys(rule.question_type for rule in matched))
        rule_ids = tuple(rule.rule_id for rule in matched)
        if len(unique_types) == 1:
            return QuestionRouteResult(
                question_type=unique_types[0],
                confidence=1.0,
                matched_rules=rule_ids,
            )
        return QuestionRouteResult(
            question_type=QuestionType.CLARIFICATION_REQUIRED.value,
            confidence=0.5,
            matched_rules=rule_ids,
            ambiguities=(ReasonCode.AMBIGUOUS_QUESTION_TYPE.value,),
        )
