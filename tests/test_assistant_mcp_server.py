"""Tests for the product MCP server factory."""

import asyncio
import os
import subprocess
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"


def _run(coro):
    return asyncio.run(coro)


def _client_session(server):
    from mcp.shared.memory import create_connected_server_and_client_session

    return create_connected_server_and_client_session(server)


def _make_package(status="answered", request_id="req:1", text="答案文本", **kwargs):
    from drawing_graph.assistant_models import AnswerPackage, AnswerStatus, MachineAnswer

    machine = MachineAnswer(
        answer_contract_version="drawing-assistant-answer-v1",
        request_id=request_id,
        question_type="page_summary",
        status=AnswerStatus(status),
    )
    return AnswerPackage(
        request_id=request_id,
        question_type="page_summary",
        status=status,
        machine_answer=machine,
        text_answer=text,
        warnings=kwargs.get("warnings", ()),
        unsupported_parts=kwargs.get("unsupported_parts", ()),
    )


class _FakeService:
    def __init__(self, package=None, error=None):
        self.package = package or _make_package()
        self.error = error
        self.answer_calls = 0

    def answer(self, request, policy=None):
        self.answer_calls += 1
        if self.error is not None:
            raise self.error
        return self.package


def _server(service=None):
    from drawing_graph.assistant_mcp_server import create_mcp_server
    from drawing_graph.assistant_mcp_tools import DrawingAssistantMCPTools

    return create_mcp_server(DrawingAssistantMCPTools(service or _FakeService()))


class AssistantMcpServerFactoryTests(unittest.TestCase):
    def test_factory_creates_server_with_fixed_name_and_instructions(self):
        from drawing_graph.assistant_mcp_server import (
            MCP_SERVER_INSTRUCTIONS,
            MCP_SERVER_NAME,
            create_mcp_server,
        )

        server = create_mcp_server(_StubTools())
        self.assertEqual("drawing-assistant", MCP_SERVER_NAME)
        self.assertLessEqual(len(MCP_SERVER_INSTRUCTIONS), 512)

        async def check():
            async with _client_session(server) as client:
                init = await client.initialize()
                return init

        init = _run(check())
        self.assertEqual("drawing-assistant", init.serverInfo.name)
        self.assertIsNotNone(init.instructions)
        for phrase in ("只读", "候选", "正式", "来源事实", "Cypher", "write_back=false"):
            self.assertIn(phrase, MCP_SERVER_INSTRUCTIONS)

    def test_initialized_server_advertises_only_tools_capability(self):
        server = _server()

        async def check():
            async with _client_session(server) as client:
                init = await client.initialize()
                return init

        init = _run(check())
        self.assertIsNotNone(init.capabilities.tools)
        self.assertIsNone(init.capabilities.resources)
        self.assertIsNone(init.capabilities.prompts)

    def test_create_mcp_server_requires_tools(self):
        from drawing_graph.assistant_mcp_server import create_mcp_server

        with self.assertRaises(ValueError):
            create_mcp_server(None)

    def test_server_import_has_no_side_effects(self):
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("NEO4J_", "DRAWING_GRAPH_"))
        }
        env["PYTHONPATH"] = str(SRC_ROOT)
        result = subprocess.run(
            [sys.executable, "-c", "import drawing_graph.assistant_mcp_server; print('import-ok')"],
            cwd=str(PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("import-ok", result.stdout)


class AskDrawingAssistantContractTests(unittest.TestCase):
    def test_tool_is_discoverable_with_stable_schema_and_annotations(self):
        server = _server()

        async def check():
            async with _client_session(server) as client:
                listed = await client.list_tools()
                return listed

        listed = _run(check())
        self.assertEqual(1, len(listed.tools))
        tool = listed.tools[0]
        self.assertEqual("ask_drawing_assistant", tool.name)
        schema = tool.inputSchema
        self.assertEqual(
            {"question", "request_id", "language", "scope_hint", "allow_recognition", "answer_format"},
            set(schema["properties"]),
        )
        self.assertEqual(["question"], schema["required"])
        self.assertTrue(tool.annotations.readOnlyHint)
        self.assertFalse(tool.annotations.destructiveHint)
        self.assertFalse(tool.annotations.openWorldHint)

    def test_call_returns_same_source_structured_and_text_content(self):
        service = _FakeService()
        server = _server(service)

        async def check():
            async with _client_session(server) as client:
                result = await client.call_tool(
                    "ask_drawing_assistant",
                    {"question": "这张图主要讲什么", "scope_hint": {"page_id": "page:1"}},
                )
                return result

        result = _run(check())

        self.assertFalse(result.isError)
        self.assertEqual("answered", result.structuredContent["status"])
        self.assertEqual("答案文本", result.structuredContent["text_answer"])
        self.assertIn("answered", result.content[0].text)
        self.assertEqual(1, service.answer_calls)

    def test_call_validates_input_and_returns_invalid_argument(self):
        server = _server()

        async def check(arguments):
            async with _client_session(server) as client:
                result = await client.call_tool("ask_drawing_assistant", arguments)
                return result

        result = _run(check({}))
        self.assertTrue(result.isError)
        self.assertEqual("invalid_argument", result.structuredContent["category"])

    def test_write_back_is_rejected_as_invalid_argument(self):
        server = _server()

        async def check():
            async with _client_session(server) as client:
                result = await client.call_tool(
                    "ask_drawing_assistant",
                    {"question": "q", "write_back": True},
                )
                return result

        result = _run(check())
        self.assertTrue(result.isError)
        self.assertEqual("invalid_argument", result.structuredContent["category"])

    def test_partial_is_success_not_error(self):
        server = _server(_FakeService(package=_make_package(status="partial", unsupported_parts=("x",))))

        async def check():
            async with _client_session(server) as client:
                result = await client.call_tool("ask_drawing_assistant", {"question": "q"})
                return result

        result = _run(check())
        self.assertFalse(result.isError)
        self.assertEqual("partial", result.structuredContent["status"])
        self.assertEqual(["x"], result.structuredContent["unsupported_parts"])
        self.assertIn("部分回答", result.content[0].text)

    def test_unexpected_error_is_sanitized_internal_error(self):
        server = _server(_FakeService(error=RuntimeError("bolt://user:secret@host traceback")))

        async def check():
            async with _client_session(server) as client:
                result = await client.call_tool("ask_drawing_assistant", {"question": "q"})
                return result

        result = _run(check())
        self.assertTrue(result.isError)
        self.assertEqual("internal_error", result.structuredContent["category"])
        self.assertNotIn("secret", result.structuredContent["message"])
        self.assertNotIn("bolt://", result.structuredContent["message"])

    def test_no_generic_write_or_cypher_tool_is_exposed(self):
        server = _server()

        async def check():
            async with _client_session(server) as client:
                listed = await client.list_tools()
                return listed

        listed = _run(check())
        names = {tool.name for tool in listed.tools}
        self.assertEqual({"ask_drawing_assistant"}, names)


class _StubTools:
    def __getattr__(self, name):
        raise AssertionError(f"server factory must not call tools.{name} during creation")


if __name__ == "__main__":
    unittest.main()
