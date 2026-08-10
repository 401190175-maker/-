"""Tests for the FastAPI application factory and lifespan runtime."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

from fastapi import Request
from fastapi.testclient import TestClient

from drawing_graph.config import QAHttpConfig
from drawing_graph.qa_http_runtime import QAHttpRuntime


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"


def _config() -> QAHttpConfig:
    return QAHttpConfig(
        neo4j_uri="bolt://localhost:7687",
        neo4j_user="neo4j",
        neo4j_password="app-factory-secret",
    )


class FakeDriver:
    def __init__(self):
        self.close_calls = 0

    def close(self):
        self.close_calls += 1


class FakeFacade:
    pass


class FakeService:
    def __init__(self, facade):
        self.facade = facade


class RecordingRuntimeFactory:
    """Runtime factory that counts calls and records the config it received."""

    def __init__(self):
        self.calls = 0
        self.last_config = None
        self.driver = FakeDriver()
        self.service = FakeService(FakeFacade())

    def __call__(self, config):
        self.calls += 1
        self.last_config = config
        return QAHttpRuntime(
            config=config,
            driver=self.driver,
            facade=FakeFacade(),
            service=self.service,
        )


def _probe_route(request: Request) -> dict:
    runtime = request.app.state.qa_runtime
    return {"service_id": id(runtime.service), "ready": runtime.ready}


class QAHttpApplicationFactoryTests(unittest.TestCase):
    """create_app() must build a side-effect-free app with a managed lifespan."""

    def test_module_import_has_no_environment_or_driver_side_effects(self):
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("NEO4J_", "DRAWING_GRAPH_"))
        }
        env["PYTHONPATH"] = str(SRC_ROOT)
        result = subprocess.run(
            [sys.executable, "-c", "import drawing_graph.qa_http; print('import-ok')"],
            cwd=str(PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("import-ok", result.stdout)

    def test_create_app_stores_config_without_creating_runtime(self):
        from drawing_graph.qa_http import create_app

        config = _config()
        factory = RecordingRuntimeFactory()
        app = create_app(config, runtime_factory=factory)

        self.assertIs(config, app.state.qa_http_config)
        self.assertFalse(hasattr(app.state, "qa_runtime"))
        self.assertEqual(0, factory.calls)

    def test_lifespan_creates_runtime_once_and_reuses_service(self):
        from drawing_graph.qa_http import create_app

        config = _config()
        factory = RecordingRuntimeFactory()
        app = create_app(config, runtime_factory=factory)
        app.add_api_route("/__probe__", _probe_route, methods=["GET"])

        with TestClient(app) as client:
            first = client.get("/__probe__")
            second = client.get("/__probe__")

            self.assertEqual(200, first.status_code)
            self.assertEqual(200, second.status_code)
            self.assertEqual(first.json()["service_id"], second.json()["service_id"])
            self.assertTrue(first.json()["ready"])
            self.assertEqual(1, factory.calls)
            self.assertIs(config, factory.last_config)

        self.assertEqual(1, factory.driver.close_calls)

    def test_startup_failure_fails_application(self):
        from drawing_graph.qa_http import create_app

        def failing_factory(config):
            raise RuntimeError("runtime init failed")

        app = create_app(_config(), runtime_factory=failing_factory)

        with self.assertRaises(RuntimeError):
            with TestClient(app) as client:
                client.get("/__probe__")

    def test_docs_are_disabled_by_default(self):
        from drawing_graph.qa_http import create_app

        app = create_app(_config())
        self.assertIsNone(app.docs_url)
        self.assertIsNone(app.redoc_url)
        self.assertIsNone(app.openapi_url)


if __name__ == "__main__":
    unittest.main()
