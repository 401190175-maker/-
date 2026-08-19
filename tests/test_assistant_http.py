"""Tests for the product HTTP application factory, routes, and status mapping."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from drawing_graph.assistant_models import (
    AnswerPackage,
    AnswerStatus,
    MachineAnswer,
)
from drawing_graph.assistant_http_runtime import AssistantHttpRuntime
from drawing_graph.config import AssistantHttpConfig


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"


def _config(**overrides) -> AssistantHttpConfig:
    values = {
        "neo4j_uri": "bolt://localhost:7687",
        "neo4j_user": "neo4j",
        "neo4j_password": "app-factory-secret",
    }
    values.update(overrides)
    return AssistantHttpConfig(**values)


class FakeDriver:
    def __init__(self):
        self.close_calls = 0

    def close(self):
        self.close_calls += 1


class FakeFacade:
    pass


def _make_package(status="answered", request_id="req:1", text="答案文本"):
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
    )


class RecordingService:
    """Fake service that records AssistantRequest objects and returns configurable answers."""

    def __init__(self, package=None):
        self.requests = []
        self.answer_calls = 0
        self.package = package

    def answer(self, request, policy=None):
        self.answer_calls += 1
        self.requests.append(request)
        if self.package is not None:
            return self.package
        return _make_package()


def _app_with_service(service, config=None):
    from drawing_graph.assistant_http import create_app

    config = config or _config()
    runtime = AssistantHttpRuntime(
        config=config,
        driver=FakeDriver(),
        facade=FakeFacade(),
        service=service,
    )
    return create_app(config, runtime_factory=lambda c: runtime)


class AssistantHttpApplicationFactoryTests(unittest.TestCase):
    def test_module_import_has_no_side_effects(self):
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("NEO4J_", "DRAWING_GRAPH_"))
        }
        env["PYTHONPATH"] = str(SRC_ROOT)
        result = subprocess.run(
            [sys.executable, "-c", "import drawing_graph.assistant_http; print('import-ok')"],
            cwd=str(PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("import-ok", result.stdout)

    def test_docs_are_disabled_by_default(self):
        from drawing_graph.assistant_http import create_app

        app = create_app(_config())
        self.assertIsNone(app.docs_url)
        self.assertIsNone(app.redoc_url)
        self.assertIsNone(app.openapi_url)


class AssistantHttpHealthTests(unittest.TestCase):
    def test_live_reports_liveness_without_runtime(self):
        app = _app_with_service(RecordingService())

        with TestClient(app) as client:
            response = client.get("/health/live")

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("live", payload["status"])
        self.assertEqual("drawing-assistant-http", payload["service"])
        self.assertEqual("drawing-assistant-http-v1", payload["contract_version"])

    def test_ready_reports_assembly_not_live_neo4j(self):
        app = _app_with_service(RecordingService())

        with TestClient(app) as client:
            response = client.get("/health/ready")

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("ready", payload["status"])
        self.assertEqual("not_checked", payload["neo4j_status"])


class AssistantHttpAskRouteTests(unittest.TestCase):
    def test_ask_calls_service_once_with_read_only_request(self):
        service = RecordingService()
        app = _app_with_service(service)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/drawing-assistant/ask",
                json={"question": "这张图主要讲什么", "scope_hint": {"page_id": "page:1"}},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, service.answer_calls)
        request = service.requests[0]
        self.assertEqual("这张图主要讲什么", request.question)
        self.assertFalse(request.allow_write_back)
        self.assertEqual("page:1", request.scope_hint.page_id)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual("answered", payload["data"]["status"])
        self.assertEqual("drawing-assistant-http-v1", payload["meta"]["contract_version"])
        self.assertEqual(payload["meta"]["request_id"], response.headers["X-Request-ID"])

    def test_client_request_id_is_used_when_provided(self):
        class EchoService(RecordingService):
            def answer(self, request, policy=None):
                RecordingService.answer(self, request, policy)
                return _make_package(request_id=request.request_id)

        service = EchoService()
        app = _app_with_service(service)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/drawing-assistant/ask",
                json={"question": "q", "request_id": "req:client-1"},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual("req:client-1", service.requests[0].request_id)
        self.assertEqual("req:client-1", response.json()["data"]["request_id"])

    def test_all_business_statuses_return_200(self):
        for status in ("answered", "partial", "clarification_required", "unsupported", "recognition_failed"):
            with self.subTest(status=status):
                service = RecordingService(package=_make_package(status=status))
                app = _app_with_service(service)
                with TestClient(app) as client:
                    response = client.post(
                        "/api/v1/drawing-assistant/ask",
                        json={"question": "q"},
                    )
                self.assertEqual(200, response.status_code)
                self.assertEqual(status, response.json()["data"]["status"])

    def test_write_back_true_is_rejected_without_calling_service(self):
        service = RecordingService()
        app = _app_with_service(service)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/drawing-assistant/ask",
                json={"question": "q", "write_back": True},
            )

        self.assertEqual(403, response.status_code)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual("read_only_violation", payload["error"]["code"])
        self.assertEqual(0, service.answer_calls)

    def test_allow_write_back_true_is_rejected(self):
        app = _app_with_service(RecordingService())

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/drawing-assistant/ask",
                json={"question": "q", "allow_write_back": True},
            )

        self.assertEqual(403, response.status_code)
        self.assertEqual("read_only_violation", response.json()["error"]["code"])

    def test_missing_question_returns_400(self):
        app = _app_with_service(RecordingService())

        with TestClient(app) as client:
            response = client.post("/api/v1/drawing-assistant/ask", json={})

        self.assertEqual(400, response.status_code)
        self.assertEqual("invalid_argument", response.json()["error"]["code"])


class AssistantAnswerHttpMappingTests(unittest.TestCase):
    def test_answer_package_maps_to_success_envelope(self):
        from drawing_graph.assistant_http import map_answer_to_http

        status_code, envelope = map_answer_to_http(_make_package(), "req-1")

        self.assertEqual(200, status_code)
        self.assertTrue(envelope["ok"])
        self.assertEqual("answered", envelope["data"]["status"])
        self.assertEqual("req-1", envelope["meta"]["request_id"])
        self.assertEqual("drawing-assistant-http-v1", envelope["meta"]["contract_version"])
        self.assertEqual("drawing-assistant-http", envelope["meta"]["adapter"])


class AssistantHttpErrorMappingTests(unittest.TestCase):
    def _error_service(self, error):
        class FailingService(RecordingService):
            def answer(self, request, policy=None):
                raise error

        return FailingService()

    def test_read_only_violation_maps_to_403(self):
        from drawing_graph.drawing_assistant_service import ReadOnlyViolationError

        app = _app_with_service(self._error_service(ReadOnlyViolationError("write-back forbidden")))

        with TestClient(app) as client:
            response = client.post("/api/v1/drawing-assistant/ask", json={"question": "q"})

        self.assertEqual(403, response.status_code)
        self.assertEqual("read_only_violation", response.json()["error"]["code"])

    def test_assistant_execution_error_maps_to_500(self):
        from drawing_graph.drawing_assistant_service import AssistantExecutionError

        app = _app_with_service(
            self._error_service(AssistantExecutionError("retrieval_failed", "retrieval failed"))
        )

        with TestClient(app) as client:
            response = client.post("/api/v1/drawing-assistant/ask", json={"question": "q"})

        self.assertEqual(500, response.status_code)
        self.assertEqual("assistant_call_failed", response.json()["error"]["code"])

    def test_unexpected_error_maps_to_internal_error_and_sanitizes(self):
        app = _app_with_service(
            self._error_service(RuntimeError("bolt://user:password@host:7687 traceback"))
        )

        with TestClient(app) as client:
            response = client.post("/api/v1/drawing-assistant/ask", json={"question": "q"})

        self.assertEqual(500, response.status_code)
        payload = response.json()
        self.assertEqual("internal_error", payload["error"]["code"])
        self.assertNotIn("password", payload["error"]["message"])
        self.assertNotIn("bolt://", payload["error"]["message"])

    def test_map_error_to_http_is_sanitized_and_stable(self):
        from drawing_graph.assistant_http import map_error_to_http

        status_code, envelope = map_error_to_http(
            RuntimeError("token=secret neo4j://host traceback"),
            "req-1",
        )
        self.assertEqual(500, status_code)
        self.assertFalse(envelope["ok"])
        self.assertEqual("internal_error", envelope["error"]["code"])
        self.assertNotIn("secret", envelope["error"]["message"])
        self.assertEqual("drawing-assistant-http", envelope["meta"]["adapter"])


class AssistantHttpAuthenticationTests(unittest.TestCase):
    def _token_config(self):
        return _config(api_token="test-token-123")

    def test_missing_credentials_returns_401(self):
        app = _app_with_service(RecordingService(), config=self._token_config())

        with TestClient(app) as client:
            response = client.post("/api/v1/drawing-assistant/ask", json={"question": "q"})

        self.assertEqual(401, response.status_code)
        self.assertEqual("unauthorized", response.json()["error"]["code"])

    def test_wrong_credentials_returns_401(self):
        app = _app_with_service(RecordingService(), config=self._token_config())

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/drawing-assistant/ask",
                json={"question": "q"},
                headers={"Authorization": "Bearer wrong-token"},
            )

        self.assertEqual(401, response.status_code)
        self.assertEqual("unauthorized", response.json()["error"]["code"])

    def test_correct_credentials_allow_request(self):
        app = _app_with_service(RecordingService(), config=self._token_config())

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/drawing-assistant/ask",
                json={"question": "q"},
                headers={"Authorization": "Bearer test-token-123"},
            )

        self.assertEqual(200, response.status_code)

    def test_live_health_stays_anonymous(self):
        app = _app_with_service(RecordingService(), config=self._token_config())

        with TestClient(app) as client:
            response = client.get("/health/live")

        self.assertEqual(200, response.status_code)

    def test_token_value_is_never_exposed(self):
        app = _app_with_service(RecordingService(), config=self._token_config())

        with TestClient(app) as client:
            response = client.post("/api/v1/drawing-assistant/ask", json={"question": "q"})

        self.assertNotIn("test-token-123", response.text)


class AssistantHttpRequestSizeTests(unittest.TestCase):
    def test_oversized_request_returns_413_without_calling_service(self):
        service = RecordingService()
        app = _app_with_service(service, config=_config(max_request_bytes=200))

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/drawing-assistant/ask",
                json={"question": "q", "conversation_context": "x" * 500},
            )

        self.assertEqual(413, response.status_code)
        self.assertEqual("request_too_large", response.json()["error"]["code"])
        self.assertEqual(0, service.answer_calls)
        self.assertNotIn("x" * 500, response.text)


class AssistantHttpConcurrencyTests(unittest.TestCase):
    def test_capacity_held_until_answer_finishes_then_released(self):
        started = threading.Event()
        release = threading.Event()

        class BlockingService(RecordingService):
            def answer(self, request, policy=None):
                started.set()
                release.wait(5)
                return _make_package()

        service = BlockingService()
        app = _app_with_service(service, config=_config(max_concurrent_requests=1))
        results = []

        with TestClient(app) as client:
            def first_request():
                results.append(client.post("/api/v1/drawing-assistant/ask", json={"question": "q"}))

            thread = threading.Thread(target=first_request)
            thread.start()
            self.assertTrue(started.wait(2), "first request did not reach the service")

            rejected = client.post("/api/v1/drawing-assistant/ask", json={"question": "q2"})

            self.assertEqual(429, rejected.status_code)
            self.assertEqual("concurrency_limit_reached", rejected.json()["error"]["code"])

            release.set()
            thread.join(5)

        self.assertEqual(200, results[0].status_code)


class AssistantHttpTimeoutTests(unittest.TestCase):
    def test_service_timeout_returns_504_without_widening_scope(self):
        class SlowService(RecordingService):
            def answer(self, request, policy=None):
                self.answer_calls += 1
                time.sleep(2)
                return _make_package()

        service = SlowService()
        app = _app_with_service(service, config=_config(request_timeout_seconds=0.2))

        with TestClient(app) as client:
            response = client.post("/api/v1/drawing-assistant/ask", json={"question": "q"})

        self.assertEqual(504, response.status_code)
        self.assertEqual("timeout", response.json()["error"]["code"])
        self.assertEqual(1, service.answer_calls)


if __name__ == "__main__":
    unittest.main()
