"""Transport-independent handlers and result mapping for the MCP QA adapter.

本模块位于 MCP server 与 ``DrawingGraphQAService`` 之间：只做窄口径参数到
``QARequest`` 的转换、一次 ``ask()`` 调用以及 ``QAAnswer`` 到 MCP 结果对象
的映射。不导入 HTTP/CLI、不直接调用 facade 单项方法、repository 或 Neo4j，
也不重新分类已有事实。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Mapping

from .qa_mcp_models import (
    AskDrawingBlockInput,
    AskDrawingPageInput,
    GetDrawingDiagnosticsInput,
    GetTableCaptionStatusInput,
    GetSectionMatchStatusInput,
    ListDrawingCandidatesInput,
    McpErrorCategory,
    McpInputError,
    McpQAError,
    McpQAFailure,
    McpQASuccess,
    McpResultMeta,
    McpToolName,
    McpToolOutcome,
)
from .qa_models import QAAnswer, QAAnswerStatus, QAError, QAErrorCode
from .qa_serialization import sanitize_error_message, to_jsonable


logger = logging.getLogger("drawing_graph.qa_mcp_tools")

_QA_ERROR_CATEGORY_MAP: dict[QAErrorCode, McpErrorCategory] = {
    QAErrorCode.INVALID_ARGUMENT: "invalid_argument",
    QAErrorCode.UNSUPPORTED_QUESTION: "unsupported_question",
    QAErrorCode.UNSUPPORTED_SCOPE: "unsupported_scope",
    QAErrorCode.NOT_FOUND: "not_found",
    QAErrorCode.WRITE_BACK_FORBIDDEN: "write_back_forbidden",
    QAErrorCode.FACADE_UNAVAILABLE: "facade_unavailable",
    QAErrorCode.NEO4J_UNAVAILABLE: "neo4j_unavailable",
    QAErrorCode.SEMANTIC_EVIDENCE_UNAVAILABLE: "semantic_evidence_unavailable",
    QAErrorCode.PARTIAL_ANSWER: "internal_error",
    QAErrorCode.INTERNAL_ERROR: "internal_error",
}


class DrawingGraphMCPTools:
    """Six narrow read-only MCP tool handlers backed by one QA service.

    只接收已通过白名单校验的输入模型；每个公开 handler 固定映射一个
    ``QuestionType``，并只调用一次注入服务的 ``ask()``。
    """

    def __init__(self, service):
        if service is None:
            raise ValueError("a DrawingGraphQAService must be injected")
        self.service = service

    def ask_drawing_page(self, tool_input: AskDrawingPageInput) -> McpToolOutcome:
        """Answer page-summary questions through one read-only QA request."""

        return self._invoke("ask_drawing_page", tool_input)

    def ask_drawing_block(self, tool_input: AskDrawingBlockInput) -> McpToolOutcome:
        """Answer block-relation questions through one read-only QA request."""

        return self._invoke("ask_drawing_block", tool_input)

    def list_drawing_candidates(self, tool_input: ListDrawingCandidatesInput) -> McpToolOutcome:
        """List candidate relations for one page or block scope (read-only)."""

        return self._invoke("list_drawing_candidates", tool_input)

    def get_section_match_status(
        self,
        tool_input: GetSectionMatchStatusInput,
    ) -> McpToolOutcome:
        """Answer section-match questions through one read-only QA request."""

        return self._invoke("get_section_match_status", tool_input)

    def get_table_caption_status(
        self,
        tool_input: GetTableCaptionStatusInput,
    ) -> McpToolOutcome:
        """Answer table-caption questions through one read-only QA request."""

        return self._invoke("get_table_caption_status", tool_input)

    def get_drawing_diagnostics(
        self,
        tool_input: GetDrawingDiagnosticsInput,
    ) -> McpToolOutcome:
        """Answer diagnostic questions through one read-only QA request."""

        return self._invoke("get_drawing_diagnostics", tool_input)

    def _invoke(self, tool_name: McpToolName, tool_input) -> McpToolOutcome:
        """Run one tool call: convert input, ask once, and map result/error.

        ``tool_input`` 必须是已通过白名单校验的输入模型（或测试注入的等价
        对象）；本方法固定生成非敏感 call ID，且无论成功或失败都不把原始
        payload、driver 或异常对象放进结果。
        """

        call_id = uuid.uuid4().hex
        try:
            qa_request = tool_input.to_qa_request()
        except (McpInputError, ValueError) as error:
            return _build_failure(
                tool_name=tool_name,
                call_id=call_id,
                category="invalid_argument",
                message=sanitize_error_message(str(error)) or "invalid tool input",
                retryable=False,
            )
        try:
            answer = self.service.ask(qa_request)
        except QAError as error:
            return map_qa_error_to_failure(tool_name, call_id, error)
        except Exception as error:
            return _map_unexpected_error(tool_name, call_id, error)
        if answer.status in {
            QAAnswerStatus.NOT_FOUND,
            QAAnswerStatus.UNSUPPORTED,
            QAAnswerStatus.FAILED,
        }:
            return map_qa_answer_to_failure(tool_name, call_id, answer)
        return map_qa_answer_to_success(tool_name, call_id, answer)


def map_qa_answer_to_success(
    tool_name: McpToolName,
    call_id: str,
    answer: QAAnswer,
) -> McpQASuccess:
    """Convert one QAAnswer into MCP success structured content without loss.

    直接复用 ``to_jsonable()``，不复制 CLI/HTTP envelope；事实类型、证据、
    warnings、unsupported parts 和 source calls 全部保留在 ``data`` 中。
    """

    return McpQASuccess(
        data=to_jsonable(answer),
        meta=McpResultMeta(tool_name=tool_name, call_id=call_id),
    )


def map_qa_answer_to_failure(
    tool_name: McpToolName,
    call_id: str,
    answer: QAAnswer,
) -> McpQAFailure:
    """Convert a not-found/unsupported/failed QAAnswer into a stable tool error."""

    category_by_status: dict[QAAnswerStatus, McpErrorCategory] = {
        QAAnswerStatus.NOT_FOUND: "not_found",
        QAAnswerStatus.UNSUPPORTED: "unsupported_question",
        QAAnswerStatus.FAILED: "internal_error",
    }
    category = category_by_status.get(answer.status, "internal_error")
    message = sanitize_error_message(answer.summary) or "QA 请求未完成"
    return _build_failure(
        tool_name=tool_name,
        call_id=call_id,
        category=category,
        message=message,
        retryable=False,
    )


def map_qa_error_to_failure(
    tool_name: McpToolName,
    call_id: str,
    error: QAError,
) -> McpQAFailure:
    """Map one QAError to a stable sanitized MCP error without dynamic categories."""

    category = _QA_ERROR_CATEGORY_MAP.get(error.category, "internal_error")
    message = sanitize_error_message(str(error)) or "QA 请求失败"
    return _build_failure(
        tool_name=tool_name,
        call_id=call_id,
        category=category,
        message=message,
        retryable=error.retryable,
    )


def _build_failure(
    *,
    tool_name: McpToolName,
    call_id: str,
    category: McpErrorCategory,
    message: str,
    retryable: bool,
) -> McpQAFailure:
    return McpQAFailure(
        error=McpQAError(
            category=category,
            message=message,
            retryable=retryable,
        ),
        meta=McpResultMeta(tool_name=tool_name, call_id=call_id),
    )


def _map_unexpected_error(
    tool_name: McpToolName,
    call_id: str,
    error: Exception,
) -> McpQAFailure:
    """Return a fixed safe error and keep detailed diagnostics on stderr only."""

    # 只记录脱敏消息与 call ID；不携带 exc_info，避免把含凭据/URI 的原始
    # traceback 写进 stderr（设计要求 stderr 不输出 stack trace 和 secret）。
    logger.error(
        "MCP tool %s call_id=%s failed: %s",
        tool_name,
        call_id,
        sanitize_error_message(str(error)) or error.__class__.__name__,
    )
    return _build_failure(
        tool_name=tool_name,
        call_id=call_id,
        category="internal_error",
        message="内部错误，请查看服务端日志或稍后重试",
        retryable=False,
    )


def build_mcp_text_summary(outcome: McpToolOutcome) -> str:
    """Build a short human-readable text summary from the same mapped outcome.

    成功时只概述 QA 状态、摘要和数量，不重排事实等级；partial 明确提示
    结果不完整。失败时只输出稳定错误类别和脱敏消息。
    """

    if isinstance(outcome, McpQAFailure):
        return f"工具执行失败（{outcome.error.category}）：{outcome.error.message}"
    data = outcome.data
    status = data.get("status", "unknown")
    summary = str(data.get("summary", "")).strip()
    fact_count = len(data.get("facts") or ())
    warning_count = len(data.get("warnings") or ())
    unsupported_count = len(data.get("unsupported_parts") or ())
    text = (
        f"QA 状态：{status}；摘要：{summary or '无'}；"
        f"facts={fact_count}；warnings={warning_count}；unsupported={unsupported_count}"
    )
    if status == "partial":
        text += "；部分回答：结果不完整"
    return text


__all__ = (
    "DrawingGraphMCPTools",
    "build_mcp_text_summary",
    "map_qa_answer_to_failure",
    "map_qa_answer_to_success",
    "map_qa_error_to_failure",
)
