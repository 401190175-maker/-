import ast
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src" / "drawing_graph"

FORBIDDEN_IMPORTS = (
    "drawing_graph.qa_http",
    "drawing_graph.qa_http_models",
    "drawing_graph.qa_http_runtime",
    "drawing_graph.qa_service",
    "drawing_graph.query_service",
    "drawing_graph.query_ports",
    "drawing_graph.relation_repository",
    "drawing_graph.tool_facade",
    "drawing_graph.tool_factory",
    "drawing_graph.semantic_service",
    "drawing_graph.semantic_repository",
    "drawing_graph.semantic_neo4j_repository",
    "drawing_graph.semantic_client",
    "drawing_graph.block_relation_enrichment",
    "drawing_graph.candidate_review",
    "neo4j",
    "drawing_graph_qa",
    "serve_drawing_graph_qa",
    "serve_drawing_graph_mcp",
)

FORBIDDEN_SCHEMA_FIELDS = (
    "write_back",
    "include_payload",
    "cypher",
    "credential",
    "password",
    "token",
    "driver",
    "session",
    "transaction",
    "repository",
    "path",
)

MCP_MODULE_NAMES = ("qa_mcp_models", "qa_mcp_tools", "qa_mcp_server")


def _module_imports(name):
    source = (SRC_DIR / f"{name}.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def _source(name):
    return (SRC_DIR / f"{name}.py").read_text(encoding="utf-8")


def _schema_keys(schema):
    """Collect every JSON object key in a schema for exact forbidden checks."""

    keys = set()
    stack = [schema]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            keys.update(value)
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    return keys


class QAMcpImportBoundaryTests(unittest.TestCase):
    """MCP modules must not import HTTP/CLI/facade/repository/Neo4j internals."""

    def test_mcp_modules_do_not_import_forbidden_modules(self):
        for module_name in MCP_MODULE_NAMES:
            with self.subTest(module=module_name):
                imported = _module_imports(module_name)
                for forbidden in FORBIDDEN_IMPORTS:
                    self.assertNotIn(forbidden, imported)

    def test_mcp_modules_never_reference_neo4j_or_cypher(self):
        for module_name in MCP_MODULE_NAMES:
            with self.subTest(module=module_name):
                source = _source(module_name).lower()
                self.assertNotIn("graphdatabase", source)
                self.assertNotIn("driver(", source)
                self.assertNotIn("session(", source)
                self.assertNotIn(".run(", source)


class QAMcpSchemaBoundaryTests(unittest.TestCase):
    """All external schemas must stay narrow and never expose backend fields."""

    def _all_input_schemas(self):
        from drawing_graph.qa_mcp_models import (
            AskDrawingBlockInput,
            AskDrawingPageInput,
            GetDrawingDiagnosticsInput,
            GetSectionMatchStatusInput,
            GetTableCaptionStatusInput,
            ListDrawingCandidatesInput,
        )

        return [
            model.model_json_schema()
            for model in (
                AskDrawingPageInput,
                AskDrawingBlockInput,
                ListDrawingCandidatesInput,
                GetSectionMatchStatusInput,
                GetTableCaptionStatusInput,
                GetDrawingDiagnosticsInput,
            )
        ]

    def test_input_model_schemas_never_expose_forbidden_fields(self):
        for schema in self._all_input_schemas():
            keys = _schema_keys(schema)
            for forbidden in FORBIDDEN_SCHEMA_FIELDS:
                self.assertNotIn(forbidden, keys)

    def test_server_tool_schemas_never_expose_forbidden_fields(self):
        schemas = self._protocol_tool_schemas()
        self.assertEqual(6, len(schemas))
        for name, input_schema, output_schema in schemas:
            with self.subTest(tool=name):
                for schema in (input_schema, output_schema):
                    keys = _schema_keys(schema)
                    for forbidden in FORBIDDEN_SCHEMA_FIELDS:
                        self.assertNotIn(forbidden, keys)

    def _protocol_tool_schemas(self):
        import asyncio

        from mcp.shared.memory import create_connected_server_and_client_session

        from drawing_graph.qa_mcp_server import create_mcp_server
        from drawing_graph.qa_mcp_tools import DrawingGraphMCPTools

        class FakeService:
            def ask(self, request):
                from drawing_graph.qa_models import QAAnswer, QAAnswerStatus

                return QAAnswer(
                    question_type=request.question_type,
                    scope=request.scope,
                    status=QAAnswerStatus.ANSWERED,
                    summary="ok",
                )

        server = create_mcp_server(DrawingGraphMCPTools(FakeService()))

        async def list_schemas():
            async with create_connected_server_and_client_session(server) as client:
                listed = await client.list_tools()
                return [
                    (tool.name, tool.inputSchema, tool.outputSchema)
                    for tool in listed.tools
                ]

        return asyncio.run(list_schemas())


class QAMcpHandlerBoundaryTests(unittest.TestCase):
    """Handlers must only reach business logic through QAService.ask()."""

    def test_six_handlers_only_call_the_private_dispatcher(self):
        source = _source("qa_mcp_tools")
        tree = ast.parse(source)
        handler_methods = {
            "ask_drawing_page",
            "ask_drawing_block",
            "list_drawing_candidates",
            "get_section_match_status",
            "get_table_caption_status",
            "get_drawing_diagnostics",
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name in handler_methods
            ):
                body_calls = [
                    call
                    for call in ast.walk(node)
                    if isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "_invoke"
                ]
                self.assertEqual(1, len(body_calls), node.name)

    def test_service_ask_is_the_only_service_attribute_call(self):
        source = _source("qa_mcp_tools")
        tree = ast.parse(source)
        service_calls = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Attribute)
                and isinstance(node.func.value.value, ast.Name)
                and node.func.value.value.id == "self"
                and node.func.value.attr == "service"
            ):
                service_calls.add(node.func.attr)
        self.assertEqual({"ask"}, service_calls)

    def test_no_facade_repository_or_rule_function_references(self):
        source = _source("qa_mcp_tools").lower()
        for forbidden in (
            "facade.",
            "repository.",
            "graphdatabase",
            "match_section_caption",
            "review_candidate",
            "enrich_",
            "import_",
        ):
            self.assertNotIn(forbidden, source)


class QAMcpDomainStabilityTests(unittest.TestCase):
    """Domain, facade, HTTP, and schema files must not absorb MCP concerns."""

    DOMAIN_FILES = (
        "qa_models.py",
        "qa_service.py",
        "qa_rendering.py",
        "qa_http.py",
        "qa_http_models.py",
        "qa_http_runtime.py",
        "tool_facade.py",
        "tool_factory.py",
        "query_service.py",
        "query_ports.py",
        "relation_repository.py",
        "candidate_review.py",
        "semantic_models.py",
        "semantic_service.py",
        "semantic_repository.py",
        "block_relation_enrichment.py",
        "import_service.py",
    )

    def test_domain_files_do_not_import_or_reference_mcp_modules(self):
        for file_name in self.DOMAIN_FILES:
            with self.subTest(file=file_name):
                source = (SRC_DIR / file_name).read_text(encoding="utf-8")
                self.assertNotIn("qa_mcp", source)

    def test_schema_script_is_not_modified_by_mcp(self):
        schema_path = PROJECT_ROOT / "scripts" / "create_schema.cypher"
        source = schema_path.read_text(encoding="utf-8")
        self.assertNotIn("mcp", source.lower())


if __name__ == "__main__":
    unittest.main()
