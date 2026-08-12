"""Clarification policy for question understanding.

根据 scope 缺失/冲突、指代不唯一和问题类型歧义生成结构化澄清项；
澄清场景不生成可触发只读检索的必需证据需求。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .assistant_models import (
    AssistantRequest,
    AssistantScope,
    ClarificationItem,
    EvidenceRequirement,
    ReasonCode,
)
from .assistant_question_rules import QuestionRouteResult
from .assistant_scope_resolution import ScopeResolutionResult


_REQUIRED_SCOPE_FIELDS = {
    "page_summary": ("page_id",),
    "block_relations": ("block_id",),
    "block_semantic_identification": ("block_id",),
    "element_text_or_meaning": ("element_id", "page_id"),
    "candidate_relations": ("page_id", "block_id"),
    "section_matches": ("cross_section_id", "page_id"),
    "table_caption_status": ("page_id",),
    "drawing_diagnostic": ("page_id",),
    "source_trace": ("claim_id", "page_id", "block_id"),
}


@dataclass(frozen=True)
class ClarificationDecision:
    """澄清策略输出：是否需要澄清、澄清项与原因码。"""

    required: bool
    items: tuple[ClarificationItem, ...] = field(default_factory=tuple)
    reason_codes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.required, bool):
            raise ValueError("required must be a boolean")
        if not isinstance(self.items, tuple) or not all(
            isinstance(item, ClarificationItem) for item in self.items
        ):
            raise ValueError("items must be a tuple of ClarificationItem")
        if not isinstance(self.reason_codes, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.reason_codes
        ):
            raise ValueError("reason_codes must be a tuple of non-empty strings")


class ClarificationPolicy:
    """判断当前问题理解是否必须向用户澄清。"""

    def evaluate(
        self,
        request: AssistantRequest,
        route_result: QuestionRouteResult,
        scope_result: ScopeResolutionResult,
        requirements: tuple[EvidenceRequirement, ...],
    ) -> ClarificationDecision:
        """返回结构化澄清决策；unsupported 不进入澄清流程。"""

        del requirements
        if route_result.question_type == "unknown_or_unsupported":
            return ClarificationDecision(required=False)

        items: list[ClarificationItem] = []
        if route_result.question_type == "clarification_required" or (
            "ambiguous_question_type" in route_result.ambiguities
        ):
            items.append(
                self._item(
                    request,
                    ReasonCode.AMBIGUOUS_QUESTION_TYPE,
                    "question_type",
                    "问题类型存在多个同等命中，请确认具体想问哪一类",
                    ("question_type",),
                    scope_result,
                )
            )

        if "scope_conflict" in scope_result.conflicts:
            items.append(
                self._item(
                    request,
                    ReasonCode.SCOPE_CONFLICT,
                    "scope",
                    "问题文本与已提供 scope 冲突，请确认目标对象",
                    ("page_id", "block_id", "element_id"),
                    scope_result,
                )
            )

        if "ambiguous_reference" in scope_result.ambiguities:
            items.append(
                self._item(
                    request,
                    ReasonCode.AMBIGUOUS_REFERENCE,
                    "scope",
                    "指代对象在上下文中不唯一，请补充稳定业务 ID",
                    ("page_id", "block_id", "element_id"),
                    scope_result,
                )
            )

        required_fields = _REQUIRED_SCOPE_FIELDS.get(route_result.question_type)
        if required_fields and _scope_satisfies(
            scope_result.scope,
            required_fields,
        ) is False:
            items.append(
                self._item(
                    request,
                    ReasonCode.SCOPE_MISSING,
                    required_fields[0],
                    f"缺少 {required_fields[0]}，请补充稳定业务 ID",
                    required_fields,
                    scope_result,
                )
            )

        if not items:
            return ClarificationDecision(required=False)
        reason_codes = tuple(dict.fromkeys(item.reason_code.value for item in items))
        return ClarificationDecision(
            required=True,
            items=tuple(items),
            reason_codes=reason_codes,
        )

    @staticmethod
    def _item(
        request: AssistantRequest,
        reason_code: ReasonCode,
        target_field: str,
        message: str,
        allowed_scope_types: tuple[str, ...],
        scope_result: ScopeResolutionResult,
    ) -> ClarificationItem:
        return ClarificationItem(
            clarification_id=f"clarify:{reason_code.value}",
            reason_code=reason_code,
            target_field=target_field,
            message=message,
            allowed_scope_types=allowed_scope_types,
            candidate_refs=tuple(scope_result.extracted_ids.values()),
            required=True,
        )


def _scope_satisfies(
    scope: AssistantScope | None,
    required_fields: tuple[str, ...],
) -> bool | None:
    """返回 None 表示无条件满足；False 表示任一必需字段都缺失。"""

    if scope is None:
        return False
    return any(getattr(scope, field_name) is not None for field_name in required_fields)
