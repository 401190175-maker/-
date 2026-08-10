import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "serve_drawing_graph_mcp.py"


def _load_script():
    module_name = "serve_drawing_graph_mcp_under_test"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class QAMcpCliImportTests(unittest.TestCase):
    """serve_drawing_graph_mcp must import cleanly and assemble via main()."""

    def test_import_has_no_env_driver_server_or_output_side_effect(self):
        code = (
            "import sys\n"
            "sys.path.insert(0, 'scripts')\n"
            "import serve_drawing_graph_mcp\n"
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
        self.assertEqual("import-ok\n", result.stdout)
        self.assertEqual("", result.stderr)

    def test_main_assembles_config_runtime_tools_and_server_in_order(self):
        module = _load_script()

        events = []
        config = object()

        class FakeRuntime:
            def __init__(self, loaded_config):
                self.service = object()
                self.close_calls = 0

            def close(self):
                self.close_calls += 1

        runtime = FakeRuntime(config)

        def config_loader():
            events.append("config")
            return config

        def runtime_factory(loaded_config):
            events.append("runtime")
            self.assertIs(config, loaded_config)
            return runtime

        def tools_factory(service):
            events.append("tools")
            return object()

        def server_factory(tools):
            events.append("server")
            return object()

        code = module.main(
            config_loader=config_loader,
            runtime_factory=runtime_factory,
            tools_factory=tools_factory,
            server_factory=server_factory,
        )

        self.assertEqual(0, code)
        self.assertEqual(["config", "runtime", "tools", "server"], events)
        self.assertEqual(1, runtime.close_calls)

    def test_config_failure_returns_nonzero_and_sanitizes_stderr(self):
        module = _load_script()

        def config_loader():
            raise RuntimeError("bolt://user:secret@host:7687 traceback detail")

        stderr = io.StringIO()
        stdout = io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
            code = module.main(config_loader=config_loader)

        self.assertEqual(2, code)
        self.assertEqual("", stdout.getvalue())
        self.assertNotIn("secret", stderr.getvalue())
        self.assertNotIn("bolt://", stderr.getvalue())
        self.assertNotIn("traceback", stderr.getvalue())

    def test_assembly_failure_closes_runtime_and_returns_nonzero(self):
        module = _load_script()

        class FakeRuntime:
            def __init__(self):
                self.service = object()
                self.close_calls = 0

            def close(self):
                self.close_calls += 1

        runtime = FakeRuntime()

        def tools_factory(service):
            raise RuntimeError("tools assembly failed")

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = module.main(
                config_loader=lambda: object(),
                runtime_factory=lambda config: runtime,
                tools_factory=tools_factory,
            )

        self.assertEqual(2, code)
        self.assertEqual(1, runtime.close_calls)
        self.assertIn("tools assembly failed", stderr.getvalue())

    def test_script_has_no_cli_argument_parsing_or_network_parameters(self):
        import ast

        source = Path("scripts/serve_drawing_graph_mcp.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)

        self.assertNotIn("argparse", imports)
        self.assertNotIn("uvicorn", imports)
        self.assertNotIn("sys.argv", source)


if __name__ == "__main__":
    unittest.main()
