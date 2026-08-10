"""No-side-effect MCP server factory for the drawing graph QA adapter.

本模块只创建尚未运行 transport 的 ``drawing-graph-qa`` server：配置 server
instructions、Tools capability、工具 Schema 与 annotations，不读取环境变量、
不创建 driver、不连接 Neo4j、不启动 STDIO。六个只读工具由后续 Task 22-27
逐项加入 ``_TOOL_SPECS``；所有业务能力仍通过注入的 ``DrawingGraphMCPTools``
调用 QAService，不直接访问 facade、repository 或 Neo4j。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from mcp.server.lowlevel import Server
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations
from pydantic import ValidationError

from .qa_mcp_models import (
    AskDrawingBlockInput,
    AskDrawingPageInput,
    GetDrawingDiagnosticsInput,
    GetTableCaptionStatusInput,
    GetSectionMatchStatusInput,
    ListDrawingCandidatesInput,
    McpInputModel,
    McpQAError,
    McpQAFailure,
    McpQASuccess,
    McpResultMeta,
    McpToolOutcome,
)
from .qa_mcp_tools import DrawingGraphMCPTools, build_mcp_text_summary
from .qa_serialization import sanitize_error_message


MCP_SERVER_NAME = "drawing-graph-qa"
MCP_SERVER_INSTRUCTIONS = (
    "本 MCP server 默认且强制只读：不提供写回、导入、增强、候选复核或任意 "
    "Cypher 工具。候选关系（CANDIDATE_*、matched_candidate）不是正式图谱事实；"
    "模型 observation/interpretation 不覆盖来源事实。所有结果必须如实区分来源事实、"
    "派生关系、语义证据、候选关系与正式关系，并按验证状态如实报告；"
    "未验证的 live Neo4j 不得声称通过。"
)

_READ_ONLY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    openWorldHint=False,
)


@dataclass(frozen=True)
class _ToolSpec:
    """Stable registration data for one narrow read-only MCP tool."""

    name: str
    description: str
    input_model: type[McpInputModel]
    handler_method: str


_TOOL_SPECS: tuple[_ToolSpec, ...] = (
    _ToolSpec(
        name="ask_drawing_page",
        description=(
            "查询指定图纸页的摘要与可用语义证据（只读）。scope 仅接受 page_id；"
            "include_semantics 只读取已有证据，不触发识别或持久化。"
        ),
        input_model=AskDrawingPageInput,
        handler_method="ask_drawing_page",
    ),
    _ToolSpec(
        name="ask_drawing_block",
        description=(
            "查询指定图块的派生关系与候选关系（只读）。scope 仅接受 block_id；"
            "候选关系保持 candidate 分类，不等于正式事实。"
        ),
        input_model=AskDrawingBlockInput,
        handler_method="ask_drawing_block",
    ),
    _ToolSpec(
        name="list_drawing_candidates",
        description=(
            "列出页面或图块范围内的候选关系（只读）。候选关系不是正式关系；"
            "不提供审核、提升或写回。page_id 与 block_id 必须且只能提供一个。"
        ),
        input_model=ListDrawingCandidatesInput,
        handler_method="list_drawing_candidates",
    ),
    _ToolSpec(
        name="get_section_match_status",
        description=(
            "查询断面匹配状态与证据（只读）。matched_candidate 仍是候选结果，"
            "不是正式关系；不接受 write_back 或 rule_version。"
            "cross_section_id 与 page_id 必须且只能提供一个。"
        ),
        input_model=GetSectionMatchStatusInput,
        handler_method="get_section_match_status",
    ),
    _ToolSpec(
        name="get_table_caption_status",
        description=(
            "查询表格与表题状态（只读）。底层能力不足时允许返回 partial 与 "
            "unsupported parts，不补造结论。table_id、table_caption_id 与 "
            "page_id 必须且只能提供一个。"
        ),
        input_model=GetTableCaptionStatusInput,
        handler_method="get_table_caption_status",
    ),
    _ToolSpec(
        name="get_drawing_diagnostics",
        description=(
            "查询页面或图块诊断状态（只读）。诊断不自动修复，也不触发导入、"
            "增强、识别或写回。page_id 与 block_id 必须且只能提供一个。"
        ),
        input_model=GetDrawingDiagnosticsInput,
        handler_method="get_drawing_diagnostics",
    ),
)

_SPEC_BY_NAME = {spec.name: spec for spec in _TOOL_SPECS}


def create_mcp_server(tools: DrawingGraphMCPTools) -> Server:
    """Create an unstarted tools-only MCP server without runtime side effects.

    ``tools`` 只用于后续工具调用委托；创建 server 时不会调用其任何方法。
    STDIO transport 由启动脚本单独运行，本工厂不读取环境变量、不创建 driver。
    """

    if tools is None:
        raise ValueError("a DrawingGraphMCPTools instance must be injected")
    server = Server(name=MCP_SERVER_NAME, instructions=MCP_SERVER_INSTRUCTIONS)

    tools_by_name = {
        spec.name: _build_tool_definition(spec, _READ_ONLY_ANNOTATIONS)
        for spec in _TOOL_SPECS
    }

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """Return the six narrow read-only tool definitions (SDK contract)."""

        return list(tools_by_name.values())

    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
        """Validate one narrow input, delegate once, and map result or error."""

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
    """Build the stable root object schema accepting success/error roots."""

    success_schema = McpQASuccess.model_json_schema()
    failure_schema = McpQAFailure.model_json_schema()
    definitions = {
        **success_schema.get("$defs", {}),
        **failure_schema.get("$defs", {}),
    }
    return {
        "title": "McpQAToolResult",
        "oneOf": [
            {key: value for key, value in schema.items() if key != "$defs"}
            for schema in (success_schema, failure_schema)
        ],
        "$defs": definitions,
    }


def _invoke_tool(
    tools: DrawingGraphMCPTools,
    spec: _ToolSpec,
    arguments: dict[str, Any] | None,
) -> McpToolOutcome:
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
) -> McpQAFailure:
    """Map an input-model validation failure to a stable sanitized tool error."""

    errors = error.errors()
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.get("loc", ())) or "input"
        message = str(first.get("msg", "invalid input"))
        detail = f"{location}: {message}"
    else:
        detail = "invalid tool input"
    return McpQAFailure(
        error=McpQAError(
            category="invalid_argument",
            message=sanitize_error_message(detail) or "invalid tool input",
            retryable=False,
        ),
        meta=McpResultMeta(
            tool_name=tool_name,
            call_id=call_id,
        ),
    )


def _to_call_result(outcome: McpToolOutcome) -> CallToolResult:
    """Convert one MCP outcome into structured content plus same-source text."""

    return CallToolResult(
        content=[
            TextContent(
                type="text",
                text=build_mcp_text_summary(outcome),
            )
        ],
        structuredContent=outcome.model_dump(mode="json", by_alias=True),
        isError=isinstance(outcome, McpQAFailure),
    )


__all__ = ("MCP_SERVER_INSTRUCTIONS", "MCP_SERVER_NAME", "create_mcp_server")
