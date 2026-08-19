"""Regression tests confirming the product adapter does not break the legacy QA adapter.

These tests verify that the six legacy QA question types, HTTP routes, MCP tool
names, write-back rejection, and fact layering are unchanged after adding the
product HTTP/MCP adapters. No product adapter imports are reverse-depended on.
"""

import asyncio
import unittest

from fastapi.testclient import TestClient


def _client_session(server):
    from mcp.shared.memory import create_connected_server_and_client_session

    return create_connected_server_and_client_session(server)


class _NotReadyRuntime:
    ready = False

    def close(self):
        pass


class QACompatQuestionTypeTests(unittest.TestCase):
    def test_six_question_types_are_unchanged(self):
        from drawing_graph.qa_models import QuestionType

        values = {item.value for item in QuestionType}
        self.assertTrue(
            {
                "page_summary",
                "block_relations",
                "candidate_relations",
                "section_matches",
                "table_caption_status",
                "diagnostic_status",
            }.issubset(values)
        )

    def test_qa_service_still_maps_request_to_ask(self):
        from drawing_graph.qa_service import DrawingGraphQAService

        self.assertTrue(hasattr(DrawingGraphQAService, "ask"))


class QACompatHttpRouteTests(unittest.TestCase):
    def test_old_http_routes_are_still_registered(self):
        from drawing_graph.qa_http import create_app
        from drawing_graph.config import QAHttpConfig

        config = QAHttpConfig(
            neo4j_uri="bolt://localhost:7687",
            neo4j_user="neo4j",
            neo4j_password="secret",
        )
        app = create_app(config, runtime_factory=lambda c: _NotReadyRuntime())

        paths = {route.path for route in app.routes}
        for expected in (
            "/api/v1/drawing-qa/ask",
            "/api/v1/drawing-qa/pages/{page_id}/summary",
            "/api/v1/drawing-qa/blocks/{block_id}/relations",
            "/api/v1/drawing-qa/candidates",
            "/api/v1/drawing-qa/section-matches",
            "/api/v1/drawing-qa/table-captions/status",
            "/api/v1/drawing-qa/diagnostics",
        ):
            self.assertIn(expected, paths)

    def test_qa_write_back_true_is_still_rejected(self):
        from drawing_graph.qa_http import create_app
        from drawing_graph.config import QAHttpConfig
        from drawing_graph.qa_http_runtime import QAHttpRuntime
        from drawing_graph.qa_service import DrawingGraphQAService

        class FakeDriver:
            def close(self):
                pass

        class FakeFacade:
            pass

        config = QAHttpConfig(
            neo4j_uri="bolt://localhost:7687",
            neo4j_user="neo4j",
            neo4j_password="secret",
        )
        runtime = QAHttpRuntime(
            config=config,
            driver=FakeDriver(),
            facade=FakeFacade(),
            service=DrawingGraphQAService(FakeFacade()),
        )
        app = create_app(config, runtime_factory=lambda c: runtime)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/drawing-qa/ask",
                json={
                    "question_type": "page_summary",
                    "scope": {"page_id": "page:1"},
                    "write_back": True,
                },
            )

        self.assertEqual(403, response.status_code)
        self.assertEqual("WRITE_BACK_FORBIDDEN", response.json()["error"]["category"])


class QACompatMcpTests(unittest.TestCase):
    def test_mcp_tool_names_are_unchanged(self):
        from drawing_graph.qa_mcp_models import MCP_TOOL_NAMES

        self.assertEqual(
            (
                "ask_drawing_page",
                "ask_drawing_block",
                "list_drawing_candidates",
                "get_section_match_status",
                "get_table_caption_status",
                "get_drawing_diagnostics",
            ),
            tuple(MCP_TOOL_NAMES),
        )

    def test_qa_mcp_still_exposes_six_tools(self):
        from drawing_graph.qa_mcp_server import create_mcp_server
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools

        class FakeQAService:
            def ask(self, request):
                from drawing_graph.qa_models import QAAnswer, QAAnswerStatus

                return QAAnswer(
                    question_type=request.question_type,
                    scope=request.scope,
                    status=QAAnswerStatus.ANSWERED,
                    summary="ok",
                )

        server = create_mcp_server(DrawingGraphMCPTools(FakeQAService()))

        async def check():
            async with _client_session(server) as client:
                listed = await client.list_tools()
                return listed

        listed = asyncio.run(check())
        self.assertEqual(6, len(listed.tools))

    def test_qa_fact_layering_is_preserved(self):
        from drawing_graph.qa_mcp_tools import map_qa_answer_to_success
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
            summary="ok",
            facts=(
                AnswerFact(
                    fact_kind="candidate_relation",
                    label="候选",
                    status="candidate",
                    ids={"block_id": "block:1"},
                    relation_type="CANDIDATE_CAPTION_OF",
                ),
                AnswerFact(
                    fact_kind="formal_relation",
                    label="正式",
                    status="confirmed",
                    ids={"block_id": "block:1"},
                    relation_type="MATCHES_SECTION_CAPTION",
                ),
            ),
        )

        outcome = map_qa_answer_to_success("ask_drawing_block", "call-1", answer)
        kinds = [fact["fact_kind"] for fact in outcome.data["facts"]]
        self.assertEqual(["candidate_relation", "formal_relation"], kinds)


class QACompatNoReverseDependencyTests(unittest.TestCase):
    def test_qa_modules_do_not_import_product_adapter(self):
        import ast
        from pathlib import Path

        src_dir = Path("src/drawing_graph")
        for module_name in ("qa_http", "qa_mcp_tools", "qa_mcp_server", "qa_service"):
            source = (src_dir / f"{module_name}.py").read_text(encoding="utf-8")
            tree = ast.parse(source)
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)
            for forbidden in (
                "drawing_graph.assistant_http",
                "drawing_graph.assistant_mcp",
                "drawing_graph.assistant_adapter_serialization",
            ):
                self.assertNotIn(forbidden, imported, module_name)


if __name__ == "__main__":
    unittest.main()
