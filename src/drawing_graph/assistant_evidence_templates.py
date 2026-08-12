"""Evidence requirement templates for question understanding.

按 ``question_type + scope`` 生成只读 ``EvidenceRequirement``；本模块不访问
图谱、不调用模型、不修改请求权限，模型生成只表达“后续可补充语义证据”。
"""

from __future__ import annotations

from enum import Enum

from .assistant_models import (
    AssistantRequest,
    AssistantScope,
    EvidenceRequirement,
    EvidenceType,
    FreshnessRequirement,
    QuestionType,
)


_MODEL_GENERATION_TYPES = frozenset(
    {
        EvidenceType.TEXT_OBSERVATIONS,
        EvidenceType.STRUCTURED_INTERPRETATIONS,
    }
)


_MINIMUM_STATUS_BY_TYPE = {
    EvidenceType.TEXT_OBSERVATIONS: "confirmed",
    EvidenceType.STRUCTURED_INTERPRETATIONS: "interpreted",
}


_FRESHNESS_BY_TYPE = {
    EvidenceType.TEXT_OBSERVATIONS: FreshnessRequirement(
        require_current_image=True,
        require_current_bbox=True,
        require_current_prompt=True,
    ),
    EvidenceType.STRUCTURED_INTERPRETATIONS: FreshnessRequirement(
        require_current_prompt=True,
        require_current_contract=True,
    ),
}


class EvidenceRequirementFactory:
    """集中维护问题类型到证据需求的稳定映射。"""

    def build(
        self,
        question_type: str,
        scope: AssistantScope | None,
        request: AssistantRequest,
    ) -> tuple[EvidenceRequirement, ...]:
        """生成证据需求；没有模板时返回空元组，不做猜测。"""

        del request
        question_type_value = (
            question_type.value if isinstance(question_type, Enum) else question_type
        )
        target = scope or AssistantScope()
        evidence_types = _evidence_types_for(question_type_value, target)
        return tuple(
            EvidenceRequirement(
                requirement_id=(
                    f"understanding:{question_type_value}:{evidence_type.value}"
                ),
                evidence_type=evidence_type,
                target_scope=target,
                required=True,
                minimum_status=_MINIMUM_STATUS_BY_TYPE.get(evidence_type),
                freshness_requirement=_FRESHNESS_BY_TYPE.get(evidence_type),
                allow_model_generation=evidence_type in _MODEL_GENERATION_TYPES,
            )
            for evidence_type in evidence_types
        )


def _evidence_types_for(
    question_type: str,
    scope: AssistantScope,
) -> tuple[EvidenceType, ...]:
    """返回问题类型对应的稳定证据类型序列。"""

    if question_type == QuestionType.PAGE_SUMMARY.value:
        return (EvidenceType.PAGE_SOURCE_FACTS,)
    if question_type == QuestionType.BLOCK_RELATIONS.value:
        return (EvidenceType.BLOCK_TRACE, EvidenceType.BLOCK_RELATIONS)
    if question_type == QuestionType.BLOCK_SEMANTIC_IDENTIFICATION.value:
        return (
            EvidenceType.BLOCK_TRACE,
            EvidenceType.STRUCTURED_INTERPRETATIONS,
        )
    if question_type == QuestionType.ELEMENT_TEXT_OR_MEANING.value:
        return (EvidenceType.PAGE_SOURCE_FACTS, EvidenceType.TEXT_OBSERVATIONS)
    if question_type == QuestionType.CANDIDATE_RELATIONS.value:
        return (EvidenceType.CANDIDATE_RELATIONS,)
    if question_type == QuestionType.SECTION_MATCHES.value:
        if scope.page_id is not None:
            return (EvidenceType.TEXT_OBSERVATIONS, EvidenceType.SECTION_MATCHES)
        return (EvidenceType.SECTION_MATCHES,)
    if question_type == QuestionType.TABLE_CAPTION_STATUS.value:
        return (EvidenceType.PAGE_SOURCE_FACTS,)
    if question_type == QuestionType.DRAWING_DIAGNOSTIC.value:
        return (EvidenceType.PAGE_SOURCE_FACTS,)
    if question_type == QuestionType.SOURCE_TRACE.value:
        if scope.page_id is not None:
            return (EvidenceType.PAGE_SOURCE_FACTS,)
        if scope.block_id is not None:
            return (EvidenceType.BLOCK_TRACE,)
        return ()
    return ()
