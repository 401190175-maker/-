import asyncio
import os
import subprocess
import sys
import unittest
from pathlib import Path


def _run(coro):
    """Run one async protocol-level check with asyncio."""

    return asyncio.run(coro)


def _client_session(server):
    """Return an in-memory MCP client session connected to the given server."""

    from mcp.shared.memory import create_connected_server_and_client_session

    return create_connected_server_and_client_session(server)


class QAMcpServerFactoryTests(unittest.TestCase):
    """create_mcp_server must build a tools-only, no-side-effect server."""

    def test_factory_creates_server_with_fixed_name_and_instructions(self):
        from drawing_graph.qa_mcp_server import (
            MCP_SERVER_INSTRUCTIONS,
            MCP_SERVER_NAME,
            create_mcp_server,
        )

        server = create_mcp_server(_StubTools())
        self.assertEqual("drawing-graph-qa", MCP_SERVER_NAME)
        self.assertLessEqual(len(MCP_SERVER_INSTRUCTIONS), 512)

        async def check():
            async with _client_session(server) as client:
                init = await client.initialize()
                return init

        init = _run(check())
        self.assertEqual("drawing-graph-qa", init.serverInfo.name)
        self.assertIsNotNone(init.instructions)
        for phrase in ("只读", "候选", "正式", "来源事实", "Cypher", "验证状态"):
            self.assertIn(phrase, MCP_SERVER_INSTRUCTIONS)

    def test_initialized_server_advertises_only_tools_capability(self):
        from drawing_graph.qa_mcp_server import create_mcp_server

        server = create_mcp_server(_StubTools())

        async def check():
            async with _client_session(server) as client:
                init = await client.initialize()
                return init

        init = _run(check())
        self.assertIsNotNone(init.capabilities.tools)
        self.assertIsNone(init.capabilities.resources)
        self.assertIsNone(init.capabilities.prompts)
        self.assertIsNone(init.capabilities.completions)
        self.assertIsNone(init.capabilities.logging)

    def test_create_mcp_server_has_no_env_driver_or_transport_side_effect(self):
        code = (
            "import sys\n"
            "import drawing_graph.qa_mcp_server as module\n"
            "assert 'neo4j' not in sys.modules\n"
            "assert 'drawing_graph.qa_http' not in sys.modules\n"
            "assert 'drawing_graph.qa_http_runtime' not in sys.modules\n"
            "print('import-ok')\n"
        )
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("NEO4J_", "DRAWING_GRAPH_QA_MCP_"))
        }
        result = subprocess.run(
            [sys.executable, "-c", code],
            env=env,
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[1]),
            timeout=30,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("import-ok", result.stdout)

    def test_server_module_does_not_import_http_cli_or_repository(self):
        import ast

        source = Path("src/drawing_graph/qa_mcp_server.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

        for forbidden in (
            "drawing_graph.qa_http",
            "drawing_graph.qa_http_runtime",
            "drawing_graph.qa_service",
            "drawing_graph.query_service",
            "drawing_graph.relation_repository",
            "drawing_graph.tool_facade",
            "neo4j",
        ):
            self.assertNotIn(forbidden, imported)

    def test_factory_creates_server_without_running_transport(self):
        from mcp.server.lowlevel import Server

        from drawing_graph.qa_mcp_server import create_mcp_server

        server = create_mcp_server(_StubTools())
        self.assertIsInstance(server, Server)


class AskDrawingPageContractTests(unittest.TestCase):
    """ask_drawing_page must be discoverable and delegate to its handler."""

    def _server(self, service):
        from drawing_graph.qa_mcp_server import create_mcp_server
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools

        return create_mcp_server(DrawingGraphMCPTools(service))

    def test_tool_is_discoverable_with_stable_schema_and_annotations(self):
        import json

        server = self._server(_FakeQAService())

        async def check():
            async with _client_session(server) as client:
                listed = await client.list_tools()
                return listed

        listed = _run(check())
        tool = next(item for item in listed.tools if item.name == "ask_drawing_page")

        self.assertIn("图纸页", tool.description)
        self.assertIn("摘要", tool.description)
        schema = tool.inputSchema
        self.assertEqual({"page_id", "language", "include_semantics"}, set(schema["properties"]))
        self.assertEqual(["page_id"], schema["required"])
        self.assertEqual("zh", schema["properties"]["language"]["default"])
        self.assertTrue(schema["properties"]["include_semantics"]["default"])
        self.assertEqual("boolean", schema["properties"]["include_semantics"]["type"])

        output = tool.outputSchema
        json.dumps(output)
        self.assertEqual("McpQAToolResult", output.get("title"))
        self.assertIn("oneOf", output)
        self.assertIn("drawing-qa-mcp-v1", json.dumps(output))

        self.assertTrue(tool.annotations.readOnlyHint)
        self.assertFalse(tool.annotations.destructiveHint)
        self.assertFalse(tool.annotations.openWorldHint)

    def test_call_delegates_once_and_returns_structured_and_text_content(self):
        from drawing_graph.qa_models import QuestionType

        service = _FakeQAService()
        server = self._server(service)

        async def check():
            async with _client_session(server) as client:
                result = await client.call_tool(
                    "ask_drawing_page",
                    {"page_id": " page:1 ", "include_semantics": False},
                )
                return result

        result = _run(check())

        self.assertFalse(result.isError)
        self.assertEqual("ok", result.structuredContent["status"])
        self.assertEqual(
            "drawing-qa-mcp-v1",
            result.structuredContent["meta"]["contract_version"],
        )
        self.assertEqual(
            "ask_drawing_page",
            result.structuredContent["meta"]["tool_name"],
        )
        self.assertEqual("answered", result.structuredContent["data"]["status"])
        text = result.content[0].text
        self.assertIn("answered", text)
        self.assertIn("页面摘要可用", text)

        self.assertEqual(1, len(service.requests))
        request = service.requests[0]
        self.assertEqual(QuestionType.PAGE_SUMMARY, request.question_type)
        self.assertEqual("page:1", request.scope.page_id)
        self.assertFalse(request.include_semantics)
        self.assertFalse(request.write_back)
        self.assertFalse(request.include_payload)
        self.assertEqual("zh", request.language)

    def test_invalid_language_is_safe_tool_error_not_protocol_error(self):
        server = self._server(_FakeQAService())

        async def check():
            async with _client_session(server) as client:
                result = await client.call_tool(
                    "ask_drawing_page",
                    {"page_id": "page:1", "language": "fr"},
                )
                return result

        result = _run(check())

        self.assertTrue(result.isError)
        self.assertEqual("error", result.structuredContent["status"])
        self.assertEqual("invalid_argument", result.structuredContent["error"]["category"])
        self.assertFalse(result.structuredContent["error"]["retryable"])

    def test_not_found_answer_is_tool_error(self):
        from drawing_graph.qa_models import QAAnswer, QAAnswerStatus, QAScope, QuestionType

        answer = QAAnswer(
            question_type=QuestionType.PAGE_SUMMARY,
            scope=QAScope(page_id="page:missing"),
            status=QAAnswerStatus.NOT_FOUND,
            summary="页面不存在或来源事实不可用",
        )
        server = self._server(_FakeQAService(result=answer))

        async def check():
            async with _client_session(server) as client:
                result = await client.call_tool("ask_drawing_page", {"page_id": "page:missing"})
                return result

        result = _run(check())

        self.assertTrue(result.isError)
        self.assertEqual("not_found", result.structuredContent["error"]["category"])

    def test_partial_answer_is_not_a_tool_error(self):
        from drawing_graph.qa_models import QAAnswer, QAAnswerStatus, QAScope, QuestionType

        answer = QAAnswer(
            question_type=QuestionType.PAGE_SUMMARY,
            scope=QAScope(page_id="page:1"),
            status=QAAnswerStatus.PARTIAL,
            summary="部分回答",
            unsupported_parts=("语义证据不可用",),
        )
        server = self._server(_FakeQAService(result=answer))

        async def check():
            async with _client_session(server) as client:
                result = await client.call_tool("ask_drawing_page", {"page_id": "page:1"})
                return result

        result = _run(check())

        self.assertFalse(result.isError)
        self.assertEqual("partial", result.structuredContent["data"]["status"])
        self.assertEqual(["语义证据不可用"], result.structuredContent["data"]["unsupported_parts"])
        self.assertIn("部分回答", result.content[0].text)


class AskDrawingBlockContractTests(unittest.TestCase):
    """ask_drawing_block must expose a narrow block-relations contract."""

    def _server(self, service):
        from drawing_graph.qa_mcp_server import create_mcp_server
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools

        return create_mcp_server(DrawingGraphMCPTools(service))

    def test_tool_schema_annotations_and_description(self):
        server = self._server(_FakeQAService())

        async def check():
            async with _client_session(server) as client:
                listed = await client.list_tools()
                return listed

        listed = _run(check())
        tool = next(item for item in listed.tools if item.name == "ask_drawing_block")

        self.assertIn("图块", tool.description)
        self.assertIn("候选", tool.description)
        schema = tool.inputSchema
        self.assertEqual(
            {"block_id", "language", "include_candidates"},
            set(schema["properties"]),
        )
        self.assertEqual(["block_id"], schema["required"])
        self.assertTrue(schema["properties"]["include_candidates"]["default"])
        self.assertTrue(tool.annotations.readOnlyHint)
        self.assertFalse(tool.annotations.destructiveHint)
        self.assertFalse(tool.annotations.openWorldHint)

    def test_call_passes_include_candidates_and_preserves_candidate_kind(self):
        from drawing_graph.qa_models import (
            AnswerFact,
            QAAnswer,
            QAAnswerStatus,
            QAScope,
            QuestionType,
        )

        answer = QAAnswer(
            question_type=QuestionType.BLOCK_RELATIONS,
            scope=QAScope(block_id="block:1"),
            status=QAAnswerStatus.ANSWERED,
            summary="图块关系可用",
            facts=(
                AnswerFact(
                    fact_kind="candidate_relation",
                    label="候选标题关系",
                    status="candidate",
                    ids={"candidate_group_id": "group:1", "block_id": "block:1"},
                    relation_type="CANDIDATE_CAPTION_OF",
                ),
            ),
        )
        service = _FakeQAService(result=answer)
        server = self._server(service)

        async def check():
            async with _client_session(server) as client:
                result = await client.call_tool(
                    "ask_drawing_block",
                    {"block_id": "block:1", "include_candidates": False},
                )
                return result

        result = _run(check())

        self.assertFalse(result.isError)
        self.assertEqual(
            "candidate_relation",
            result.structuredContent["data"]["facts"][0]["fact_kind"],
        )
        self.assertEqual(
            "CANDIDATE_CAPTION_OF",
            result.structuredContent["data"]["facts"][0]["relation_type"],
        )
        self.assertEqual(1, len(service.requests))
        request = service.requests[0]
        self.assertEqual(QuestionType.BLOCK_RELATIONS, request.question_type)
        self.assertEqual("block:1", request.scope.block_id)
        self.assertFalse(request.include_candidates)
        self.assertFalse(request.write_back)
        self.assertFalse(request.include_payload)

    def test_handler_is_the_only_business_entry_point(self):
        service = _FakeQAService()
        server = self._server(service)

        async def check():
            async with _client_session(server) as client:
                result = await client.call_tool("ask_drawing_block", {"block_id": "block:1"})
                return result

        result = _run(check())

        self.assertFalse(result.isError)
        self.assertEqual(1, len(service.requests))
        self.assertEqual("block:1", service.requests[0].scope.block_id)


class _StubTools:
    """Minimal stand-in that server creation must not call during creation."""

    def __getattr__(self, name):
        raise AssertionError(f"server factory must not call tools.{name} during creation")


class _FakeQAService:
    """Minimal QA service double recording ask() calls for server tests."""

    def __init__(self, result=None):
        self.result = result
        self.requests = []

    def ask(self, request):
        self.requests.append(request)
        if self.result is not None:
            return self.result
        from drawing_graph.qa_models import QAAnswer, QAAnswerStatus

        return QAAnswer(
            question_type=request.question_type,
            scope=request.scope,
            status=QAAnswerStatus.ANSWERED,
            summary="页面摘要可用",
        )


if __name__ == "__main__":
    unittest.main()
