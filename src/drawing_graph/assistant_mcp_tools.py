"""Transport-independent handler and result mapping for the MCP product adapter.

本模块位于产品 MCP server 与 ``DrawingAssistantService`` 之间：只做白名单参数到
``AssistantRequest`` 的转换、一次 ``answer()`` 调用以及 ``AnswerPackage`` 到 MCP
结果对象的映射。不导入 HTTP/CLI、不直接调用 facade 单项方法、repository 或
Neo4j，也不重新分类已有事实。candidate/formal 语义保持原样。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from .assistant_adapter_serialization import (
    answer_package_to_data,
    map_exception_to_error,
    sanitize_error_message,
)
from .assistant_mcp_models import (
    McpAssistantErrorBody,
    McpAssistantErrorCategory,
    McpAssistantFailure,
    McpAssistantResultMeta,
    McpAssistantSuccess,
    McpAssistantToolOutcome,
    McpAssistantInputError,
)

logger = logging.getLogger("drawing_graph.assistant_mcp_tools")

_ALLOWED_MCP_CATEGORIES: frozenset[str] = frozenset(
    {
        "invalid_argument",
        "read_only_violation",
        "configuration_failed",
        "initialization_failed",
        "assistant_call_failed",
        "timeout",
        "concurrency_limit_reached",
        "internal_error",
    }
)


class DrawingAssistantMCPTools:
    """One narrow read-only product MCP tool handler backed by one service.

    只接收已通过白名单校验的输入模型；公开 handler 固定转换一次输入并只调用
    一次注入服务的 ``answer()``。所有业务状态（answered/partial/
    clarification_required/unsupported/recognition_failed）都映射为 success。
    """

    def __init__(self, service):
        if service is None:
            raise ValueError("a DrawingAssistantService must be injected")
        self.service = service

    def ask_drawing_assistant(self, tool_input) -> McpAssistantToolOutcome:
        """Answer a natural-language product question through one read-only call."""

        call_id = uuid.uuid4().hex
        try:
            request = tool_input.to_assistant_request()
        except (McpAssistantInputError, ValueError) as error:
            return _build_failure(
                tool_name="ask_drawing_assistant",
                call_id=call_id,
                category="invalid_argument",
                message=sanitize_error_message(str(error)) or "invalid tool input",
                retryable=False,
            )
        try:
            package = self.service.answer(request)
        except Exception as error:  # noqa: BLE001
            return map_exception_to_failure("ask_drawing_assistant", call_id, error)
        return map_package_to_success("ask_drawing_assistant", call_id, package)


def map_package_to_success(
    tool_name: str,
    call_id: str,
    package: Any,
) -> McpAssistantSuccess:
    """Convert one AnswerPackage into MCP success structured content without loss."""

    return McpAssistantSuccess(
        data=answer_package_to_data(package),
        meta=McpAssistantResultMeta(tool_name=tool_name, call_id=call_id),
    )


def map_exception_to_failure(
    tool_name: str,
    call_id: str,
    error: Exception,
) -> McpAssistantFailure:
    """Map one raised exception to a stable sanitized MCP tool error."""

    code, retryable = map_exception_to_error(error)
    category = code if code in _ALLOWED_MCP_CATEGORIES else "internal_error"
    message = sanitize_error_message(str(error)) or "assistant request failed"
    return _build_failure(
        tool_name=tool_name,
        call_id=call_id,
        category=category,
        message=message,
        retryable=retryable,
    )


def _build_failure(
    *,
    tool_name: str,
    call_id: str,
    category: McpAssistantErrorCategory,
    message: str,
    retryable: bool,
) -> McpAssistantFailure:
    return McpAssistantFailure(
        error=McpAssistantErrorBody(
            category=category,
            message=message,
            retryable=retryable,
        ),
        meta=McpAssistantResultMeta(tool_name=tool_name, call_id=call_id),
    )


def build_assistant_text_summary(outcome: McpAssistantToolOutcome) -> str:
    """Build a short human-readable text summary from the same mapped outcome.

    成功时只概述状态、text_answer 和 claim/warning/unsupported 数量，不重排
    事实等级、不新增 claim；partial 明确提示结果不完整。失败时只输出稳定错误
    类别和脱敏消息。
    """

    if isinstance(outcome, McpAssistantFailure):
        return f"工具执行失败（{outcome.error.category}）：{outcome.error.message}"
    data = outcome.data
    status = str(data.get("status", "unknown"))
    text_answer = str(data.get("text_answer") or "").strip()
    claim_count = len(data.get("claims") or ())
    warning_count = len(data.get("warnings") or ())
    unsupported_count = len(data.get("unsupported_parts") or ())
    text = (
        f"状态：{status}；回答：{text_answer or '无'}；"
        f"claims={claim_count}；warnings={warning_count}；unsupported={unsupported_count}"
    )
    if status == "partial":
        text += "；部分回答：结果不完整"
    return text


__all__ = (
    "DrawingAssistantMCPTools",
    "build_assistant_text_summary",
    "map_exception_to_failure",
    "map_package_to_success",
)
