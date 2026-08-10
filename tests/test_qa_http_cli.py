"""Tests for the single-worker HTTP service startup script."""

from __future__ import annotations

import importlib.util
import io
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from drawing_graph.config import ConfigError, QAHttpConfig


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "serve_drawing_graph_qa.py"


def _config() -> QAHttpConfig:
    return QAHttpConfig(
        neo4j_uri="bolt://localhost:7687",
        neo4j_user="neo4j",
        neo4j_password="serve-test-secret",
        host="127.0.0.1",
        port=8123,
        log_level="DEBUG",
    )


def _load_script():
    module_name = "serve_drawing_graph_qa_under_test"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ServeScriptTests(unittest.TestCase):
    """serve_drawing_graph_qa.py must be a thin env-driven single-worker entry."""

    def test_main_builds_app_and_runs_single_worker(self):
        module = _load_script()
        fake_app = object()
        calls = []

        def fake_runner(app, **kwargs):
            calls.append((app, kwargs))

        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.object(module, "create_app", return_value=fake_app) as create_app_mock:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = module.main(config_loader=lambda: _config(), runner=fake_runner)

        self.assertEqual(0, exit_code)
        self.assertEqual("", stderr.getvalue())
        create_app_mock.assert_called_once()
        self.assertEqual(1, len(calls))
        app, kwargs = calls[0]
        self.assertIs(fake_app, app)
        self.assertEqual("127.0.0.1", kwargs["host"])
        self.assertEqual(8123, kwargs["port"])
        self.assertEqual(1, kwargs["workers"])
        self.assertEqual("debug", kwargs["log_level"])
        summary = stdout.getvalue()
        self.assertIn("127.0.0.1:8123", summary)
        self.assertIn("drawing-qa-http-v1", summary)
        self.assertNotIn("serve-test-secret", summary)

    def test_module_import_has_no_environment_side_effects(self):
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("NEO4J_", "DRAWING_GRAPH_"))
        }
        env["PYTHONPATH"] = str(SRC_ROOT)
        result = subprocess.run(
            [sys.executable, "-c", "import serve_drawing_graph_qa; print('import-ok')"],
            cwd=str(PROJECT_ROOT / "scripts"),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("import-ok", result.stdout)

    def test_config_error_returns_nonzero_with_sanitized_message(self):
        module = _load_script()

        def failing_loader():
            raise ConfigError("NEO4J_PASSWORD=serve-secret is missing")

        calls = []
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = module.main(
                config_loader=failing_loader,
                runner=lambda app, **kwargs: calls.append(kwargs),
            )

        self.assertEqual(2, exit_code)
        self.assertEqual([], calls)
        self.assertNotIn("serve-secret", stderr.getvalue())
        self.assertNotIn("NEO4J_PASSWORD", stderr.getvalue())

    def test_script_has_no_secret_command_line_arguments(self):
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertNotIn("argparse", source)
        self.assertNotIn("--password", source)
        self.assertNotIn("--token", source)
        self.assertNotIn("--api-key", source)


if __name__ == "__main__":
    unittest.main()
