"""Tests for the product MCP STDIO serve script (serve_drawing_assistant_mcp.py)."""

import importlib.util
import io
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "serve_drawing_assistant_mcp.py"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "serve_drawing_assistant_mcp_under_test", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ServeMcpScriptImportTests(unittest.TestCase):
    def test_script_import_has_no_side_effects(self):
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("NEO4J_", "DRAWING_GRAPH_"))
        }
        env["PYTHONPATH"] = str(SRC_ROOT)
        result = subprocess.run(
            [sys.executable, "-c", "import serve_drawing_assistant_mcp; print('import-ok')"],
            cwd=str(PROJECT_ROOT / "scripts"),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("import-ok", result.stdout)

    def test_script_has_no_cli_arguments(self):
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertNotIn("add_argument", source)


class ServeMcpScriptStartupTests(unittest.TestCase):
    def test_config_error_returns_two_with_sanitized_stderr(self):
        module = _load_script()

        def boom():
            raise RuntimeError("password=secret bolt://host")

        stderr = io.StringIO()
        with redirect_stderr(stderr):
            exit_code = module.main(config_loader=boom)
        self.assertEqual(2, exit_code)
        self.assertNotIn("secret", stderr.getvalue())
        self.assertNotIn("bolt://", stderr.getvalue())

    def test_runtime_error_returns_two_and_closes(self):
        module = _load_script()
        from drawing_graph.config import AssistantMcpConfig

        config = AssistantMcpConfig(
            neo4j_uri="bolt://localhost:7687",
            neo4j_user="neo4j",
            neo4j_password="secret",
        )

        def boom_runtime(cfg):
            raise RuntimeError("initialization_failed secret")

        stderr = io.StringIO()
        with redirect_stderr(stderr):
            exit_code = module.main(
                config_loader=lambda: config,
                runtime_factory=boom_runtime,
            )
        self.assertEqual(2, exit_code)
        self.assertNotIn("secret", stderr.getvalue())

    def test_missing_config_returns_two_in_subprocess(self):
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("NEO4J_", "DRAWING_GRAPH_"))
        }
        env["PYTHONPATH"] = str(SRC_ROOT)
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            cwd=str(PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(2, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertNotIn("password", result.stderr.lower())
        self.assertNotIn("secret", result.stderr.lower())

    def test_main_runs_transport_and_closes_once(self):
        module = _load_script()
        from drawing_graph.config import AssistantMcpConfig

        config = AssistantMcpConfig(
            neo4j_uri="bolt://localhost:7687",
            neo4j_user="neo4j",
            neo4j_password="secret",
        )

        class FakeDriver:
            def __init__(self):
                self.closed = 0

            def close(self):
                self.closed += 1

        class FakeFacade:
            pass

        class FakeService:
            def answer(self, request, policy=None):
                return None

        driver = FakeDriver()
        calls = []

        def runtime_factory(cfg):
            from drawing_graph.assistant_mcp_runtime import AssistantMcpRuntime

            return AssistantMcpRuntime(cfg, driver, FakeFacade(), FakeService())

        def transport_runner(server):
            calls.append(server)

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = module.main(
                config_loader=lambda: config,
                runtime_factory=runtime_factory,
                transport_runner=transport_runner,
            )
        self.assertEqual(0, exit_code)
        self.assertEqual(1, len(calls))
        self.assertEqual(1, driver.closed)
        self.assertEqual("", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
