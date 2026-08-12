"""QA-to-product retrieval mapping adapter.

把现有六类固定 ``QARequest`` 映射为产品层 ``QuestionUnderstandingResult``
与 ``EvidenceRequirement``，供后续复用通用检索闭环；本映射不修改
``DrawingGraphQAService`` 行为，也不让 QAService 反向依赖产品模块。
"""

from __future__ import annotations

from .assistant_models import (
    AssistantScope,
    EvidenceRequirement,
    EvidenceType,
    QuestionUnderstandingResult,
)
from .qa_models import QARequest, QAScope, QuestionType


_QA_TO_PRODUCT_TYPE = {
    "page_summary": "page_summary",
    "block_relations": "block_relations",
    "candidate_relations": "candidate_relations",
    "section_matches": "section_matches",
    "table_caption_status": "table_caption_status",
    "diagnostic_status": "drawing_diagnostic",
    "unknown_or_unsupported": "unknown_or_unsupported",
}


def qa_request_to_question_result(
    request: QARequest,
) -> QuestionUnderstandingResult:
    """把一个固定 QA 请求映射为产品问题理解结果。"""

    scope = _to_assistant_scope(request.scope)
    evidence_types = _evidence_types(request)
    requirements = tuple(
        EvidenceRequirement(
            requirement_id=f"qa:{request.question_type.value}:{evidence_type.value}",
            evidence_type=evidence_type,
            target_scope=scope,
            required=True,
            include_payload=(
                request.include_payload
                and evidence_type is EvidenceType.SEMANTIC_PAYLOAD
            ),
        )
        for evidence_type in evidence_types
    )
    unsupported_parts = (
        ("question_type",)
        if request.question_type is QuestionType.UNKNOWN_OR_UNSUPPORTED
        else ()
    )
    return QuestionUnderstandingResult(
        request_id=f"qa:{request.question_type.value}",
        question_type=_product_question_type(request.question_type),
        scope=scope,
        required_evidence=requirements,
        unsupported_parts=unsupported_parts,
    )


def _product_question_type(qa_type: QuestionType) -> str:
    """把固定 QA 类型映射为产品层稳定问题类型字符串。"""

    return _QA_TO_PRODUCT_TYPE.get(qa_type.value, "unknown_or_unsupported")


def _evidence_types(request: QARequest) -> tuple[EvidenceType, ...]:
    """按问题类型与开关生成产品证据需求类型。"""

    if request.question_type is QuestionType.PAGE_SUMMARY:
        types = [EvidenceType.PAGE_SOURCE_FACTS]
        if request.include_semantics:
            types.extend(
                (
                    EvidenceType.TEXT_OBSERVATIONS,
                    EvidenceType.STRUCTURED_INTERPRETATIONS,
                )
            )
        return tuple(types)
    if request.question_type is QuestionType.BLOCK_RELATIONS:
        return (EvidenceType.BLOCK_TRACE, EvidenceType.BLOCK_RELATIONS)
    if request.question_type is QuestionType.CANDIDATE_RELATIONS:
        return (EvidenceType.CANDIDATE_RELATIONS,) if request.include_candidates else ()
    if request.question_type is QuestionType.SECTION_MATCHES:
        return (EvidenceType.SECTION_MATCHES,)
    if request.question_type is QuestionType.TABLE_CAPTION_STATUS:
        return (EvidenceType.PAGE_SOURCE_FACTS,)
    if request.question_type is QuestionType.DIAGNOSTIC_STATUS:
        types = [EvidenceType.PAGE_SOURCE_FACTS]
        if request.include_candidates:
            types.append(EvidenceType.CANDIDATE_RELATIONS)
        return tuple(types)
    return ()


def _to_assistant_scope(scope: QAScope) -> AssistantScope:
    """把 QA scope 映射为产品 scope（claim_id 在 QA 层不存在，保持 None）。"""

    return AssistantScope(
        project_id=scope.project_id,
        drawing_set_id=scope.drawing_set_id,
        page_id=scope.page_id,
        block_id=scope.block_id,
        element_id=scope.element_id,
        cross_section_id=scope.cross_section_id,
        table_id=scope.table_id,
        table_caption_id=scope.table_caption_id,
    )
