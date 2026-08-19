"""Fake-service end-to-end tests for the three product entrances (CLI/HTTP/MCP).

These tests run the same fake service through the product CLI, HTTP app, and MCP
server and assert that request_id, status, text_answer, warnings, and
unsupported_parts stay consistent. No Neo4j, no DashScope, and no filesystem
business data is used.
"""

import asyncio
import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
CLI_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "drawing_assistant.py"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from drawing_graph.assistant_models import AnswerPackage, AnswerStatus, MachineAnswer


class _FakeConfig:
    neo4j_uri = "bolt://example"
    neo4j_user = "neo4j"
    neo4j_password = "secret"


class _FakeDriver:
    def close(self):
        pass


class _FakeFacade:
    pass


def _make_package(status="answered", request_id="req:1", text="答案文本", warnings=(), unsupported_parts=()):
    machine = MachineAnswer(
        answer_contract_version="drawing-assistant-answer-v1",
        request_id=request_id,
        question_type="page_summary",
        status=AnswerStatus(status),
        warnings=warnings,
        unsupported_parts=unsupported_parts,
    )
    return AnswerPackage(
        request_id=request_id,
        question_type="page_summary",
        status=status,
        machine_answer=machine,
        text_answer=text,
        warnings=warnings,
        unsupported_parts=unsupported_parts,
    )


class _FakeService:
    def __init__(self, package):
        self.package = package
        self.calls = 0

    def answer(self, request, policy=None):
        self.calls += 1
        return self.package


def _run_cli(service, request_id="req:1"):
    spec = importlib.util.spec_from_file_location("product_adapter_e2e_cli", CLI_SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = module.main(
            ["--question", "q", "--request-id", request_id],
            config_loader=lambda: _FakeConfig(),
            driver_factory=lambda uri, auth: _FakeDriver(),
            facade_factory=lambda d: _FakeFacade(),
            service_factory=lambda f: service,
        )
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _run_http(service, request_id="req:1"):
    from drawing_graph.assistant_http import create_app
    from drawing_graph.assistant_http_runtime import AssistantHttpRuntime
    from drawing_graph.config import AssistantHttpConfig

    config = AssistantHttpConfig(
        neo4j_uri="bolt://localhost:7687",
        neo4j_user="neo4j",
        neo4j_password="secret",
    )
    runtime = AssistantHttpRuntime(config=config, driver=_FakeDriver(), facade=_FakeFacade(), service=service)
    app = create_app(config, runtime_factory=lambda c: runtime)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/drawing-assistant/ask",
            json={"question": "q", "request_id": request_id},
        )
    return response.status_code, response.json()


def _run_mcp(service, request_id="req:1"):
    from drawing_graph.assistant_mcp_server import create_mcp_server
    from drawing_graph.assistant_mcp_tools import DrawingAssistantMCPTools
    from mcp.shared.memory import create_connected_server_and_client_session

    server = create_mcp_server(DrawingAssistantMCPTools(service))

    async def check():
        async with create_connected_server_and_client_session(server) as client:
            result = await client.call_tool(
                "ask_drawing_assistant",
                {"question": "q", "request_id": request_id},
            )
            return result

    return asyncio.run(check())


class ProductAdapterE2ETests(unittest.TestCase):
    def test_three_entrances_agree_on_core_fields(self):
        for status in ("answered", "partial", "clarification_required", "unsupported", "recognition_failed"):
            with self.subTest(status=status):
                package = _make_package(
                    status=status,
                    warnings=("warn-a",),
                    unsupported_parts=("part-b",),
                )
                service = _FakeService(package)

                cli_exit, cli_out, cli_err = _run_cli(service)
                http_status, http_payload = _run_http(service)
                mcp_result = _run_mcp(service)

                self.assertEqual(0, cli_exit)
                self.assertEqual("", cli_err)
                cli_payload = json.loads(cli_out)

                self.assertEqual(status, cli_payload["data"]["status"])
                self.assertEqual(status, http_payload["data"]["status"])
                self.assertEqual(status, mcp_result.structuredContent["status"])

                self.assertEqual("req:1", cli_payload["data"]["request_id"])
                self.assertEqual("req:1", http_payload["data"]["request_id"])
                self.assertEqual("req:1", mcp_result.structuredContent["request_id"])

                self.assertEqual("答案文本", cli_payload["data"]["text_answer"])
                self.assertEqual("答案文本", http_payload["data"]["text_answer"])
                self.assertEqual("答案文本", mcp_result.structuredContent["text_answer"])

    def test_three_entrances_preserve_warnings_and_unsupported_parts(self):
        package = _make_package(warnings=("warn-a",), unsupported_parts=("part-b",))
        service = _FakeService(package)

        _, cli_out, _ = _run_cli(service)
        _, http_payload = _run_http(service)
        mcp_result = _run_mcp(service)

        cli_payload = json.loads(cli_out)
        # CLI keeps warnings/unsupported_parts inside machine_answer.
        self.assertEqual(["warn-a"], cli_payload["data"]["machine_answer"]["warnings"])
        self.assertEqual(["part-b"], cli_payload["data"]["machine_answer"]["unsupported_parts"])
        self.assertEqual(["warn-a"], http_payload["data"]["warnings"])
        self.assertEqual(["part-b"], http_payload["data"]["unsupported_parts"])
        self.assertEqual(["warn-a"], mcp_result.structuredContent["warnings"])
        self.assertEqual(["part-b"], mcp_result.structuredContent["unsupported_parts"])

    def test_text_output_does_not_add_facts(self):
        package = _make_package(text="唯一答案", unsupported_parts=("part-b",))
        service = _FakeService(package)

        _, http_payload = _run_http(service)
        mcp_result = _run_mcp(service)

        # Text summary must not introduce a claim that is not in structured content.
        self.assertIn("唯一答案", mcp_result.content[0].text)
        self.assertNotIn("唯一答案以外的结论", mcp_result.content[0].text)
        self.assertNotIn("claim", mcp_result.structuredContent.get("text_answer", "").lower())

    def test_write_back_is_fixed_false_across_entrances(self):
        class RecordingService(_FakeService):
            def __init__(self, package):
                super().__init__(package)
                self.requests = []

            def answer(self, request, policy=None):
                self.requests.append(request)
                return self.package

        service = RecordingService(_make_package())

        _run_cli(service)
        _run_http(service)
        _run_mcp(service)

        self.assertEqual(3, len(service.requests))
        for request in service.requests:
            self.assertFalse(request.allow_write_back)


if __name__ == "__main__":
    unittest.main()
