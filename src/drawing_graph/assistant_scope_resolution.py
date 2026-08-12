"""Scope resolution and reference resolution for question understanding.

本模块只做文本与 DTO 层解析：不访问数据库、不调用
``DrawingGraphToolFacade``、不验证对象是否存在；拒绝把数据库内部 ID、
查询语言片段、连接 URI 或文件路径当作 scope。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from .assistant_models import AssistantScope, ReasonCode
from .assistant_question_text import QuestionTextNormalizer


_SCOPE_FIELD_BY_PREFIX = {
    "cross_section": "cross_section_id",
    "table_caption": "table_caption_id",
    "element": "element_id",
    "block": "block_id",
    "page": "page_id",
    "table": "table_id",
    "claim": "claim_id",
}

_ID_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?P<prefix>cross_section|table_caption|element|block|page|table|claim):"
    r"(?P<id>[A-Za-z0-9_][A-Za-z0-9_.\-]*)"
)

_QUERY_SNIPPET_WORDS = re.compile(
    r"\b(?:MATCH|OPTIONAL\s+MATCH|RETURN|WHERE|MERGE|CREATE|DELETE|SET|UNWIND|WITH)\b",
    re.IGNORECASE,
)

_SCOPE_FIELDS = (
    "project_id",
    "drawing_set_id",
    "page_id",
    "block_id",
    "element_id",
    "cross_section_id",
    "table_id",
    "table_caption_id",
    "claim_id",
)

_PRONOUN_SCOPE_FIELDS = (
    ("这张图", "page_id"),
    ("这个图块", "block_id"),
)


@dataclass(frozen=True)
class ScopeResolutionResult:
    """scope 解析结果：合并后的 scope、来源、冲突与歧义。"""

    scope: AssistantScope | None = None
    scope_sources: tuple[str, ...] = field(default_factory=tuple)
    conflicts: tuple[str, ...] = field(default_factory=tuple)
    ambiguities: tuple[str, ...] = field(default_factory=tuple)
    extracted_ids: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.scope is not None and not isinstance(self.scope, AssistantScope):
            raise ValueError("scope must be an AssistantScope or None")
        for field_name in ("scope_sources", "conflicts", "ambiguities"):
            values = getattr(self, field_name)
            if not isinstance(values, tuple) or not all(
                isinstance(item, str) and item.strip() for item in values
            ):
                raise ValueError(f"{field_name} must be a tuple of non-empty strings")
        if not isinstance(self.extracted_ids, Mapping):
            raise ValueError("extracted_ids must be a mapping")
        object.__setattr__(self, "extracted_ids", MappingProxyType(dict(self.extracted_ids)))


class ScopeResolver:
    """从问题文本、scope_hint 与有限对话上下文中解析稳定业务 ID。"""

    def __init__(self, normalizer: QuestionTextNormalizer | None = None) -> None:
        self.normalizer = normalizer or QuestionTextNormalizer()

    def resolve(
        self,
        question: str,
        scope_hint: AssistantScope | None = None,
        conversation_context: str | None = None,
    ) -> ScopeResolutionResult:
        """解析问题文本、合并 scope_hint，并在有限上下文中消解指代。"""

        question_text = self.normalizer.normalize(question)
        if _contains_query_snippet(question_text):
            result = _merge_scope_hint(ScopeResolutionResult(), scope_hint)
            return self._resolve_context_references(result, question_text, conversation_context)
        extracted = _extract_ids(question_text)
        result = _merge_scope_hint(_scope_result_from_extracted(extracted), scope_hint)
        return self._resolve_context_references(result, question_text, conversation_context)

    def _resolve_context_references(
        self,
        result: ScopeResolutionResult,
        question_text: str,
        conversation_context: str | None,
    ) -> ScopeResolutionResult:
        """仅在字段仍为空且上下文候选唯一时解析“这张图/这个图块”。"""

        if conversation_context is None or not conversation_context.strip():
            return result
        context_text = self.normalizer.normalize(conversation_context)
        context_ids = _extract_ids(context_text)
        values = {
            field_name: getattr(result.scope, field_name)
            for field_name in _SCOPE_FIELDS
            if result.scope is not None and getattr(result.scope, field_name) is not None
        }
        sources = list(result.scope_sources)
        ambiguities = list(result.ambiguities)
        for pronoun, field_name in _PRONOUN_SCOPE_FIELDS:
            if field_name in values or pronoun not in question_text:
                continue
            candidates = list(dict.fromkeys(context_ids.get(field_name, [])))
            if len(candidates) == 1:
                values[field_name] = candidates[0]
                if "conversation_context" not in sources:
                    sources.append("conversation_context")
            elif len(candidates) > 1 and "ambiguous_reference" not in ambiguities:
                ambiguities.append(ReasonCode.AMBIGUOUS_REFERENCE.value)
        scope = AssistantScope(**values) if values else None
        return ScopeResolutionResult(
            scope=scope,
            scope_sources=tuple(sources),
            conflicts=result.conflicts,
            ambiguities=tuple(ambiguities),
            extracted_ids=result.extracted_ids,
        )


def _contains_query_snippet(text: str) -> bool:
    """检测文本是否包含查询语言关键操作，命中时不做任何 scope 提取。"""

    return _QUERY_SNIPPET_WORDS.search(text) is not None


def _extract_ids(text: str) -> dict[str, list[str]]:
    """按前缀提取稳定业务 ID，返回 scope 字段名到 ID 列表的映射。"""

    extracted: dict[str, list[str]] = {}
    for item in _ID_PATTERN.finditer(text):
        prefix = item.group("prefix")
        field_name = _SCOPE_FIELD_BY_PREFIX[prefix]
        value = f"{prefix}:{item.group('id')}"
        extracted.setdefault(field_name, []).append(value)
    return extracted


def _scope_result_from_extracted(extracted: dict[str, list[str]]) -> ScopeResolutionResult:
    """把提取结果转为 scope；同一字段出现多个不同 ID 时记歧义不猜测。"""

    scope_values: dict[str, str] = {}
    extracted_ids: dict[str, str] = {}
    ambiguities: list[str] = []
    for field_name, values in extracted.items():
        unique = list(dict.fromkeys(values))
        if len(unique) > 1:
            ambiguities.append(ReasonCode.AMBIGUOUS_REFERENCE.value)
            continue
        scope_values[field_name] = unique[0]
        extracted_ids[field_name] = unique[0]
    if not scope_values:
        return ScopeResolutionResult(ambiguities=tuple(ambiguities))
    return ScopeResolutionResult(
        scope=AssistantScope(**scope_values),
        scope_sources=("question_text",),
        ambiguities=tuple(ambiguities),
        extracted_ids=extracted_ids,
    )


def _merge_scope_hint(
    result: ScopeResolutionResult,
    scope_hint: AssistantScope | None,
) -> ScopeResolutionResult:
    """合并 scope_hint 与文本 ID；同一字段冲突时记录冲突且不擅自选择。"""

    if scope_hint is None:
        return result
    if not isinstance(scope_hint, AssistantScope):
        raise ValueError("scope_hint must be an AssistantScope or None")

    values: dict[str, str] = {}
    sources = list(result.scope_sources)
    conflicts = list(result.conflicts)
    text_scope = result.scope
    for field_name in _SCOPE_FIELDS:
        hint_value = getattr(scope_hint, field_name)
        text_value = getattr(text_scope, field_name) if text_scope is not None else None
        if hint_value is None:
            if text_value is not None:
                values[field_name] = text_value
            continue
        if text_value is None:
            values[field_name] = hint_value
            if "scope_hint" not in sources:
                sources.append("scope_hint")
            continue
        if hint_value == text_value:
            values[field_name] = hint_value
            if "scope_hint" not in sources:
                sources.append("scope_hint")
            continue
        if "scope_conflict" not in conflicts:
            conflicts.append(ReasonCode.SCOPE_CONFLICT.value)

    scope = AssistantScope(**values) if values else None
    return ScopeResolutionResult(
        scope=scope,
        scope_sources=tuple(sources),
        conflicts=tuple(conflicts),
        ambiguities=result.ambiguities,
        extracted_ids=result.extracted_ids,
    )
