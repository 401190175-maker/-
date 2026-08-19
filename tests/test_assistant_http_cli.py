"""Tests for the product HTTP serve script (serve_drawing_assistant.py)."""

import importlib.util
import io
import json
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "serve_drawing_assistant.py"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def _load_script():
    spec = importlib.util.spec_from_file_location("serve_drawing_assistant_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ServeScriptImportTests(unittest.TestCase):
    def test_script_import_has_no_side_effects(self):
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("NEO4J_", "DRAWING_GRAPH_"))
        }
        env["PYTHONPATH"] = str(SRC_ROOT)
        result = subprocess.run(
            [sys.executable, "-c", "import serve_drawing_assistant; print('import-ok')"],
            cwd=str(PROJECT_ROOT / "scripts"),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("import-ok", result.stdout)

    def test_script_has_no_secret_cli_arguments(self):
        import ast

        source = SCRIPT_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for forbidden in ("add_argument", "password", "api_key", "token"):
            # Only enforce that no argparse add_argument exists; secrets stay env-only.
            pass
        self.assertNotIn("add_argument", source)


class ServeScriptStartupTests(unittest.TestCase):
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

    def test_config_error_returns_two_in_subprocess(self):
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

    def test_main_loads_config_from_env_and_runs_runner(self):
        module = _load_script()
        from drawing_graph.config import AssistantHttpConfig

        config = AssistantHttpConfig(
            neo4j_uri="bolt://localhost:7687",
            neo4j_user="neo4j",
            neo4j_password="secret",
        )

        calls = []

        def config_loader():
            return config

        def runner(app, host, port, workers, log_level):
            calls.append((app, host, port, workers, log_level))

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = module.main(config_loader=config_loader, runner=runner)
        self.assertEqual(0, exit_code)
        self.assertEqual(1, len(calls))
        app, host, port, workers, log_level = calls[0]
        self.assertEqual("127.0.0.1", host)
        self.assertEqual(8001, port)
        self.assertEqual(1, workers)


if __name__ == "__main__":
    unittest.main()
