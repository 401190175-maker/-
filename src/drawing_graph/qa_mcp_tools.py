"""Transport-independent handlers and result mapping for the MCP QA adapter.

本模块位于 MCP server 与 ``DrawingGraphQAService`` 之间：只做窄口径参数到
``QARequest`` 的转换、一次 ``ask()`` 调用以及 ``QAAnswer`` 到 MCP 结果对象
的映射。不导入 HTTP/CLI、不直接调用 facade 单项方法、repository 或 Neo4j，
也不重新分类已有事实。
"""

from __future__ import annotations

from typing import Any, Mapping

from .qa_mcp_models import (
    McpQAFailure,
    McpQASuccess,
    McpResultMeta,
    McpToolName,
    McpToolOutcome,
)
from .qa_models import QAAnswer
from .qa_serialization import to_jsonable


class DrawingGraphMCPTools:
    """Six narrow read-only MCP tool handlers backed by one QA service.

    只接收已通过白名单校验的输入模型；每个公开 handler 固定映射一个
    ``QuestionType``，并只调用一次注入服务的 ``ask()``。
    """

    def __init__(self, service):
        if service is None:
            raise ValueError("a DrawingGraphQAService must be injected")
        self.service = service


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
    "map_qa_answer_to_success",
)
