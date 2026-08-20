"""Build AnswerPackage from page search results (narrow read-only path)."""

from __future__ import annotations

from typing import Any

from .assistant_answer_templates import ChineseAnswerTemplateRenderer
from .assistant_models import (
    ANSWER_CONTRACT_VERSION,
    AnswerPackage,
    AnswerStatus,
    AssistantScope,
    Citation,
    Claim,
    ClaimStatus,
    MachineAnswer,
    QuestionType,
    TextRenderMode,
)
from .page_search_service import PageSearchResult


class PageContentSearchAnswerBuilder:
    """Convert PageSearchResult into a stable AnswerPackage."""

    def __init__(self, template_renderer: Any | None = None) -> None:
        self.template_renderer = template_renderer or ChineseAnswerTemplateRenderer()

    def build(
        self,
        request_id: str,
        scope: AssistantScope | None,
        result: PageSearchResult,
    ) -> AnswerPackage:
        claims: list[Claim] = []
        citations: list[Citation] = []
        for match in result.matches:
            claim_id = f"claim:page-search:{match.page_id}"
            citation_id = f"citation:page-search:{match.page_id}"
            claims.append(
                Claim(
                    claim_id=claim_id,
                    statement=f"页面 {match.page_title} 命中检索",
                    status=ClaimStatus.SUPPORTED.value,
                    fact_kinds=("source_fact",),
                    scope=AssistantScope(page_id=match.page_id),
                    citation_ids=(citation_id,),
                )
            )
            citations.append(
                Citation(
                    citation_id=citation_id,
                    evidence_id=f"evidence:page-search:{match.page_id}",
                    claim_ids=(claim_id,),
                    page_id=match.page_id,
                )
            )
        status = AnswerStatus.ANSWERED if claims else AnswerStatus.PARTIAL
        machine = MachineAnswer(
            answer_contract_version=ANSWER_CONTRACT_VERSION,
            request_id=request_id,
            question_type=QuestionType.PAGE_CONTENT_SEARCH.value,
            scope=scope,
            status=status,
            claims=tuple(claims),
            citations=tuple(citations),
        )
        text = self.template_renderer.render(machine)
        return AnswerPackage(
            request_id=request_id,
            question_type=QuestionType.PAGE_CONTENT_SEARCH.value,
            scope=scope,
            status=status.value,
            machine_answer=machine,
            text_answer=text,
            claims=tuple(claims),
            citations=tuple(citations),
            render_mode=TextRenderMode.TEMPLATE,
        )
