"""Factory for assembling the read-only drawing assistant service without side effects.

装配默认 01—07 服务并支持注入已构造的 facade 与可选文本生成 port。factory
调用本身不打开连接、不读取 secret、不执行查询、不调用模型，也不接收裸
repository/session；它不扩张 ``tool_factory``。
"""

from __future__ import annotations

from .assistant_answer_generation import AnswerGenerationService
from .assistant_evidence_fusion_factory import create_evidence_fusion_service
from .assistant_question_understanding import QuestionUnderstandingService
from .assistant_retrieval_service import GraphRetrievalService
from .assistant_semantic_gap_decision import SemanticGapDecisionService
from .assistant_traceability_service import TraceabilityService
from .drawing_assistant_service import DrawingAssistantService


def create_drawing_assistant_service(
    facade: object,
    text_generator: object | None = None,
    question_service: object | None = None,
    retrieval_service: object | None = None,
    gap_decision_service: object | None = None,
    fusion_service: object | None = None,
    answer_service: object | None = None,
    traceability_service: object | None = None,
    trace_store: object | None = None,
) -> DrawingAssistantService:
    """装配默认 01—07 服务，无外部副作用。"""

    question_service = question_service or QuestionUnderstandingService()
    retrieval_service = retrieval_service or GraphRetrievalService(facade)
    gap_decision_service = gap_decision_service or SemanticGapDecisionService()
    fusion_service = fusion_service or create_evidence_fusion_service()
    answer_service = answer_service or AnswerGenerationService(text_generator=text_generator)

    if traceability_service is None and trace_store is not None:
        traceability_service = TraceabilityService(trace_store)

    return DrawingAssistantService(
        question_service=question_service,
        retrieval_service=retrieval_service,
        gap_decision_service=gap_decision_service,
        fusion_service=fusion_service,
        answer_service=answer_service,
        facade=facade,
        traceability_service=traceability_service,
    )


__all__ = ("create_drawing_assistant_service",)
