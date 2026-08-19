"""No-side-effect MCP server factory for the product drawing assistant adapter.

本模块只创建尚未运行 transport 的 ``drawing-assistant`` server：配置 server
instructions、Tools capability、工具 Schema 与 annotations，不读取环境变量、
不创建 driver、不连接 Neo4j、不启动 STDIO。唯一只读工具 ``ask_drawing_assistant``
通过注入的 ``DrawingAssistantMCPTools`` 调用 ``DrawingAssistantService.answer()``，
不直接访问 facade、repository 或 Neo4j。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from mcp.server.lowlevel import Server
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations
from pydantic import ValidationError

from .assistant_mcp_models import (
    AskDrawingAssistantInput,
    McpAssistantErrorBody,
    McpAssistantFailure,
    McpAssistantResultMeta,
    McpAssistantToolOutcome,
    McpAssistantInputModel,
)
from .assistant_mcp_tools import DrawingAssistantMCPTools, build_assistant_text_summary
from .qa_serialization import sanitize_error_message


MCP_SERVER_NAME = "drawing-assistant"
MCP_SERVER_INSTRUCTIONS = (
    "本 MCP server 默认且强制只读：不提供写回、导入、增强、候选复核或任意 "
    "Cypher 工具。默认 write_back=false；候选关系（CANDIDATE_*、matched_candidate）"
    "不是正式图谱事实；模型 observation/interpretation 不覆盖来源事实。所有结果"
    "必须如实区分来源事实、派生关系、语义证据、候选关系与正式关系，并按验证状态"
    "如实报告；未验证的 live Neo4j 不得声称通过。"
)

_READ_ONLY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    openWorldHint=False,
)


@dataclass(frozen=True)
class _ToolSpec:
    """Stable registration data for the single read-only product MCP tool."""

    name: str
    description: str
    input_model: type[McpAssistantInputModel]
    handler_method: str


_TOOL_SPECS: tuple[_ToolSpec, ...] = (
    _ToolSpec(
        name="ask_drawing_assistant",
        description=(
            "对图纸图谱发起只读自然语言问答。scope_hint 仅接受稳定业务 ID "
            "(project_id/drawing_set_id/page_id/block_id/element_id/cross_section_id/"
            "table_id/table_caption_id/claim_id)；allow_recognition 只表示允许按需识别，"
            "不表示允许写回数据库。候选关系保持 candidate 分类，不等于正式事实。"
        ),
        input_model=AskDrawingAssistantInput,
        handler_method="ask_drawing_assistant",
    ),
)

_SPEC_BY_NAME = {spec.name: spec for spec in _TOOL_SPECS}


def create_mcp_server(tools: DrawingAssistantMCPTools) -> Server:
    """Create an unstarted tools-only MCP server without runtime side effects."""

    if tools is None:
        raise ValueError("a DrawingAssistantMCPTools instance must be injected")
    server = Server(name=MCP_SERVER_NAME, instructions=MCP_SERVER_INSTRUCTIONS)

    tools_by_name = {
        spec.name: _build_tool_definition(spec, _READ_ONLY_ANNOTATIONS)
        for spec in _TOOL_SPECS
    }

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """Return the single read-only product tool definition (SDK contract)."""

        return list(tools_by_name.values())

    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
        """Validate the narrow input, delegate once, and map result or error."""

        spec = _SPEC_BY_NAME.get(name)
        if spec is None:
            raise ValueError(f"unknown tool: {name}")
        outcome = _invoke_tool(tools, spec, arguments)
        return _to_call_result(outcome)

    return server


def _build_tool_definition(spec: _ToolSpec, annotations: ToolAnnotations) -> Tool:
    """Build one stable protocol Tool with schema and read-only annotations."""

    return Tool(
        name=spec.name,
        description=spec.description,
        inputSchema=spec.input_model.model_json_schema(),
        outputSchema=_build_output_schema(),
        annotations=annotations,
    )


def _build_output_schema() -> dict[str, Any]:
    """Build the stable root object schema accepting the projection or error body."""

    from .assistant_mcp_models import McpAssistantAnswer, McpAssistantErrorBody

    answer_schema = McpAssistantAnswer.model_json_schema()
    error_schema = McpAssistantErrorBody.model_json_schema()
    definitions = {
        **answer_schema.get("$defs", {}),
        **error_schema.get("$defs", {}),
    }
    return {
        "title": "McpAssistantToolResult",
        "oneOf": [
            {key: value for key, value in answer_schema.items() if key != "$defs"},
            {key: value for key, value in error_schema.items() if key != "$defs"},
        ],
        "$defs": definitions,
    }


def _invoke_tool(
    tools: DrawingAssistantMCPTools,
    spec: _ToolSpec,
    arguments: dict[str, Any] | None,
) -> McpAssistantToolOutcome:
    """Convert protocol arguments, delegate to the matching handler, and map."""

    call_id = uuid.uuid4().hex
    try:
        tool_input = spec.input_model.model_validate(arguments or {})
    except ValidationError as error:
        return _build_input_failure(spec.name, call_id, error)
    handler = getattr(tools, spec.handler_method)
    return handler(tool_input)


def _build_input_failure(
    tool_name: str,
    call_id: str,
    error: ValidationError,
) -> McpAssistantFailure:
    """Map an input-model validation failure to a stable sanitized tool error."""

    errors = error.errors()
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.get("loc", ())) or "input"
        message = str(first.get("msg", "invalid input"))
        detail = f"{location}: {message}"
    else:
        detail = "invalid tool input"
    return McpAssistantFailure(
        error=McpAssistantErrorBody(
            category="invalid_argument",
            message=sanitize_error_message(detail) or "invalid tool input",
            retryable=False,
        ),
        meta=McpAssistantResultMeta(
            tool_name=tool_name,
            call_id=call_id,
        ),
    )


def _to_call_result(outcome: McpAssistantToolOutcome) -> CallToolResult:
    """Convert one MCP outcome into structured content plus same-source text.

    成功时 structuredContent 直接是 ``AnswerPackage`` 的 JSON-safe 投影；
    失败时 structuredContent 是脱敏错误体。TextContent 只概述状态与数量，
    不新增事实。
    """

    text = build_assistant_text_summary(outcome)
    if isinstance(outcome, McpAssistantFailure):
        structured_content = outcome.error.model_dump(mode="json")
        is_error = True
    else:
        structured_content = outcome.data
        is_error = False
    return CallToolResult(
        content=[
            TextContent(
                type="text",
                text=text,
            )
        ],
        structuredContent=structured_content,
        isError=is_error,
    )


__all__ = ("MCP_SERVER_INSTRUCTIONS", "MCP_SERVER_NAME", "create_mcp_server")
