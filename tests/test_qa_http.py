"""Tests for the FastAPI application factory and lifespan runtime."""

from __future__ import annotations

import os
import subprocess
import sys
import asyncio
import threading
import time
import unittest
from pathlib import Path
from uuid import UUID

from fastapi import Request
from fastapi.testclient import TestClient

from drawing_graph.config import QAHttpConfig
from drawing_graph.qa_models import (
    AnswerFact,
    QAAnswer,
    QAAnswerStatus,
    QAError,
    QAErrorCode,
    QAScope,
    QuestionType,
)
from drawing_graph.qa_service import DrawingGraphQAService
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


class RecordingQAService:
    """Fake service that records domain requests and returns configurable answers."""

    def __init__(self, answer=None):
        self.facade = FakeFacade()
        self.requests = []
        self.ask_calls = 0
        self.answer = answer

    def ask(self, request):
        self.ask_calls += 1
        self.requests.append(request)
        if self.answer is not None:
            return self.answer
        return QAAnswer(
            question_type=request.question_type,
            scope=request.scope,
            status=QAAnswerStatus.ANSWERED,
            summary="已回答",
        )


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


def _app_with_service(service, config=None):
    from drawing_graph.qa_http import create_app

    config = config or _config()
    runtime = QAHttpRuntime(
        config=config,
        driver=FakeDriver(),
        facade=FakeFacade(),
        service=service,
    )
    return create_app(config, runtime_factory=lambda c: runtime)


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


class QAHttpResponseMetadataTests(unittest.TestCase):
    """Every response must carry a server-generated request ID and security headers."""

    def _app_with_probe(self):
        from drawing_graph.qa_http import create_app

        factory = RecordingRuntimeFactory()
        app = create_app(_config(), runtime_factory=factory)
        app.add_api_route("/__probe__", _probe_route, methods=["GET"])
        return app, factory

    def test_every_response_gets_server_generated_request_id(self):
        app, _ = self._app_with_probe()

        with TestClient(app) as client:
            first = client.get("/__probe__")
            second = client.get("/__probe__")

        for response in (first, second):
            self.assertIn("X-Request-ID", response.headers)
            UUID(response.headers["X-Request-ID"])
        self.assertNotEqual(first.headers["X-Request-ID"], second.headers["X-Request-ID"])

    def test_client_request_id_header_is_not_trusted(self):
        app, _ = self._app_with_probe()

        with TestClient(app) as client:
            response = client.get(
                "/__probe__",
                headers={"X-Request-ID": "client-supplied-1"},
            )

        self.assertNotEqual("client-supplied-1", response.headers["X-Request-ID"])
        UUID(response.headers["X-Request-ID"])

    def test_business_responses_have_security_headers(self):
        app, _ = self._app_with_probe()

        with TestClient(app) as client:
            response = client.get("/__probe__")

        self.assertEqual("no-store", response.headers["Cache-Control"])
        self.assertEqual("nosniff", response.headers["X-Content-Type-Options"])

    def test_request_id_is_not_a_domain_dto_field(self):
        import dataclasses

        from drawing_graph.qa_models import QAAnswer, QARequest

        for dto in (QARequest, QAAnswer):
            field_names = {item.name for item in dataclasses.fields(dto)}
            self.assertNotIn("request_id", field_names)


class QAAnswerHttpMappingTests(unittest.TestCase):
    """map_answer_to_http() must map answer statuses without reclassifying facts."""

    def _mapping(self):
        from drawing_graph.qa_http import map_answer_to_http

        return map_answer_to_http

    def test_answered_maps_to_200_success_envelope(self):
        answer = QAAnswer(
            question_type=QuestionType.PAGE_SUMMARY,
            scope=QAScope(page_id="page:1"),
            status=QAAnswerStatus.ANSWERED,
            summary="页面存在，共 3 个元素",
            facts=(
                AnswerFact(
                    fact_kind="source_fact",
                    label="页面",
                    status="confirmed",
                    ids={"page_id": "page:1"},
                ),
            ),
            source_calls=("read_page_source_facts",),
        )

        status_code, envelope = self._mapping()(answer, "req-1")

        self.assertEqual(200, status_code)
        self.assertEqual("ok", envelope["status"])
        self.assertEqual("answered", envelope["data"]["status"])
        self.assertEqual("source_fact", envelope["data"]["facts"][0]["fact_kind"])
        self.assertEqual("req-1", envelope["meta"]["request_id"])
        self.assertEqual("drawing-qa-http-v1", envelope["meta"]["contract_version"])

    def test_partial_maps_to_200_and_preserves_gaps(self):
        answer = QAAnswer(
            question_type=QuestionType.TABLE_CAPTION_STATUS,
            scope=QAScope(page_id="page:1"),
            status=QAAnswerStatus.PARTIAL,
            summary="表格标题状态部分可用",
            warnings=("语义证据不可用",),
            unsupported_parts=("live Neo4j 验证未执行",),
        )

        status_code, envelope = self._mapping()(answer, "req-2")

        self.assertEqual(200, status_code)
        self.assertEqual("ok", envelope["status"])
        self.assertEqual(["语义证据不可用"], envelope["data"]["warnings"])
        self.assertEqual(["live Neo4j 验证未执行"], envelope["data"]["unsupported_parts"])

    def test_not_found_maps_to_404_with_safe_details(self):
        answer = QAAnswer(
            question_type=QuestionType.PAGE_SUMMARY,
            scope=QAScope(page_id="page:secret-value"),
            status=QAAnswerStatus.NOT_FOUND,
            summary="页面不存在",
            source_calls=("read_page_source_facts",),
        )

        status_code, envelope = self._mapping()(answer, "req-3")

        self.assertEqual(404, status_code)
        self.assertEqual("failed", envelope["status"])
        self.assertEqual("NOT_FOUND", envelope["error"]["category"])
        self.assertIs(False, envelope["error"]["retryable"])
        details = envelope["error"]["details"]
        self.assertEqual("page_summary", details["question_type"])
        self.assertEqual(["page_id"], details["scope_fields"])
        self.assertEqual(["read_page_source_facts"], details["source_calls"])
        self.assertNotIn("page:secret-value", str(details))

    def test_unsupported_maps_to_422(self):
        answer = QAAnswer(
            question_type=QuestionType.BLOCK_RELATIONS,
            scope=QAScope(block_id="block:1"),
            status=QAAnswerStatus.UNSUPPORTED,
            summary="该问题类型不受支持",
        )

        status_code, envelope = self._mapping()(answer, "req-4")

        self.assertEqual(422, status_code)
        self.assertEqual("UNSUPPORTED_QUESTION", envelope["error"]["category"])

    def test_failed_maps_to_500_and_sanitizes_message(self):
        answer = QAAnswer(
            question_type=QuestionType.DIAGNOSTIC_STATUS,
            scope=QAScope(page_id="page:1"),
            status=QAAnswerStatus.FAILED,
            summary="neo4j password=top-secret unavailable",
        )

        status_code, envelope = self._mapping()(answer, "req-5")

        self.assertEqual(500, status_code)
        self.assertEqual("INTERNAL_ERROR", envelope["error"]["category"])
        self.assertNotIn("top-secret", envelope["error"]["message"])
        self.assertNotIn("password", envelope["error"]["message"])

    def test_candidate_and_formal_facts_keep_their_kinds(self):
        answer = QAAnswer(
            question_type=QuestionType.CANDIDATE_RELATIONS,
            scope=QAScope(page_id="page:1"),
            status=QAAnswerStatus.ANSWERED,
            summary="候选关系",
            facts=(
                AnswerFact(
                    fact_kind="candidate_relation",
                    label="候选",
                    status="matched_candidate",
                    relation_type="CANDIDATE_MATCHES_SECTION_CAPTION",
                ),
                AnswerFact(
                    fact_kind="formal_relation",
                    label="正式",
                    status="confirmed",
                    relation_type="MATCHES_SECTION_CAPTION",
                ),
            ),
        )

        _, envelope = self._mapping()(answer, "req-6")

        self.assertEqual(
            ["candidate_relation", "formal_relation"],
            [fact["fact_kind"] for fact in envelope["data"]["facts"]],
        )


class QAErrorHttpMappingTests(unittest.TestCase):
    """map_error_to_http() must map every QAErrorCode with stable status/retryable."""

    def _mapping(self):
        from drawing_graph.qa_http import map_error_to_http

        return map_error_to_http

    def test_all_error_codes_map_to_design_status_and_retryable(self):
        expected = {
            QAErrorCode.INVALID_ARGUMENT: (422, False),
            QAErrorCode.UNSUPPORTED_QUESTION: (422, False),
            QAErrorCode.UNSUPPORTED_SCOPE: (422, False),
            QAErrorCode.NOT_FOUND: (404, False),
            QAErrorCode.PARTIAL_ANSWER: (422, False),
            QAErrorCode.WRITE_BACK_FORBIDDEN: (403, False),
            QAErrorCode.FACADE_UNAVAILABLE: (503, True),
            QAErrorCode.NEO4J_UNAVAILABLE: (503, True),
            QAErrorCode.SEMANTIC_EVIDENCE_UNAVAILABLE: (503, True),
            QAErrorCode.INTERNAL_ERROR: (500, False),
        }

        for code, (status, retryable) in expected.items():
            status_code, envelope = self._mapping()(QAError(code, "message"), "req-1")
            self.assertEqual(status, status_code, code)
            self.assertEqual(code.value, envelope["error"]["category"])
            self.assertEqual(retryable, envelope["error"]["retryable"])

    def test_sensitive_error_message_is_sanitized(self):
        error = QAError(QAErrorCode.NEO4J_UNAVAILABLE, "bolt://neo4j:top-secret@localhost:7687 unavailable")

        _, envelope = self._mapping()(error, "req-2")

        self.assertNotIn("top-secret", envelope["error"]["message"])
        self.assertNotIn("bolt://", envelope["error"]["message"])
        self.assertNotIn("neo4j:", envelope["error"]["message"])

    def test_envelope_meta_has_request_id_and_contract_version(self):
        error = QAError(QAErrorCode.NOT_FOUND, "not found")

        _, envelope = self._mapping()(error, "req-3")

        self.assertEqual("failed", envelope["status"])
        self.assertEqual("req-3", envelope["meta"]["request_id"])
        self.assertEqual("drawing-qa-http-v1", envelope["meta"]["contract_version"])


class QAHttpPostAskTests(unittest.TestCase):
    """POST /api/v1/drawing-qa/ask must be the single authoritative QA entry."""

    def test_post_ask_calls_service_once_with_domain_request(self):
        service = RecordingQAService()
        app = _app_with_service(service)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/drawing-qa/ask",
                json={
                    "question_type": "page_summary",
                    "scope": {"page_id": "page:1"},
                    "language": "zh",
                },
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, service.ask_calls)
        request = service.requests[0]
        self.assertIs(QuestionType.PAGE_SUMMARY, request.question_type)
        self.assertEqual("page:1", request.scope.page_id)
        self.assertEqual("json", request.format_hint)
        payload = response.json()
        self.assertEqual("ok", payload["status"])
        self.assertEqual("page_summary", payload["data"]["question_type"])
        self.assertEqual(payload["meta"]["request_id"], response.headers["X-Request-ID"])
        self.assertEqual("drawing-qa-http-v1", payload["meta"]["contract_version"])

    def test_all_six_question_types_route_through_ask(self):
        scopes = {
            "page_summary": {"page_id": "page:1"},
            "block_relations": {"block_id": "block:1"},
            "candidate_relations": {"page_id": "page:1"},
            "section_matches": {"cross_section_id": "cross:1"},
            "table_caption_status": {"table_id": "table:1"},
            "diagnostic_status": {"page_id": "page:1"},
        }

        for question_type, scope in scopes.items():
            service = RecordingQAService()
            app = _app_with_service(service)
            with TestClient(app) as client:
                response = client.post(
                    "/api/v1/drawing-qa/ask",
                    json={"question_type": question_type, "scope": scope},
                )
            self.assertEqual(200, response.status_code, question_type)
            self.assertEqual(question_type, response.json()["data"]["question_type"])
            self.assertEqual(1, service.ask_calls)

    def test_write_back_true_is_rejected_by_service_as_403(self):
        service = DrawingGraphQAService(FakeFacade())
        app = _app_with_service(service)

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
        payload = response.json()
        self.assertEqual("WRITE_BACK_FORBIDDEN", payload["error"]["category"])
        self.assertIs(False, payload["error"]["retryable"])

    def test_partial_answer_returns_200_with_gaps(self):
        answer = QAAnswer(
            question_type=QuestionType.TABLE_CAPTION_STATUS,
            scope=QAScope(page_id="page:1"),
            status=QAAnswerStatus.PARTIAL,
            summary="部分可用",
            warnings=("语义证据不可用",),
            unsupported_parts=("live Neo4j 验证未执行",),
        )
        service = RecordingQAService(answer=answer)
        app = _app_with_service(service)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/drawing-qa/ask",
                json={
                    "question_type": "table_caption_status",
                    "scope": {"page_id": "page:1"},
                },
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(["语义证据不可用"], response.json()["data"]["warnings"])
        self.assertEqual(["live Neo4j 验证未执行"], response.json()["data"]["unsupported_parts"])

    def test_qa_error_from_service_maps_to_error_envelope(self):
        class FailingService(RecordingQAService):
            def ask(self, request):
                raise QAError(QAErrorCode.NOT_FOUND, "page not found")

        service = FailingService()
        app = _app_with_service(service)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/drawing-qa/ask",
                json={
                    "question_type": "page_summary",
                    "scope": {"page_id": "page:1"},
                },
            )

        self.assertEqual(404, response.status_code)
        self.assertEqual("NOT_FOUND", response.json()["error"]["category"])

    def test_route_module_does_not_touch_facade_directly(self):
        source = (PROJECT_ROOT / "src" / "drawing_graph" / "qa_http.py").read_text(encoding="utf-8")
        for forbidden in (
            "from .tool_facade",
            "import tool_facade",
            ".facade.",
        ):
            self.assertNotIn(forbidden, source)


class QAHttpPageSummaryRouteTests(unittest.TestCase):
    """GET page summary route must construct the page_summary QARequest only."""

    def test_get_page_summary_builds_page_summary_request(self):
        service = RecordingQAService()
        app = _app_with_service(service)

        with TestClient(app) as client:
            response = client.get("/api/v1/drawing-qa/pages/page:1/summary")

        self.assertEqual(200, response.status_code)
        request = service.requests[0]
        self.assertIs(QuestionType.PAGE_SUMMARY, request.question_type)
        self.assertEqual("page:1", request.scope.page_id)
        self.assertIsNone(request.scope.block_id)
        self.assertTrue(request.include_semantics)
        self.assertFalse(request.include_payload)
        self.assertFalse(request.write_back)
        self.assertEqual("json", request.format_hint)

    def test_include_semantics_query_flag_is_forwarded(self):
        service = RecordingQAService()
        app = _app_with_service(service)

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/drawing-qa/pages/page:1/summary",
                params={"include_semantics": "false"},
            )

        self.assertEqual(200, response.status_code)
        self.assertFalse(service.requests[0].include_semantics)

    def test_route_has_no_write_back_or_payload_controls(self):
        service = RecordingQAService()
        app = _app_with_service(service)

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/drawing-qa/pages/page:1/summary",
                params={"write_back": "true", "include_payload": "true"},
            )

        self.assertEqual(200, response.status_code)
        request = service.requests[0]
        self.assertFalse(request.write_back)
        self.assertFalse(request.include_payload)

    def test_not_found_answer_maps_to_404(self):
        answer = QAAnswer(
            question_type=QuestionType.PAGE_SUMMARY,
            scope=QAScope(page_id="page:missing"),
            status=QAAnswerStatus.NOT_FOUND,
            summary="页面不存在",
        )
        app = _app_with_service(RecordingQAService(answer=answer))

        with TestClient(app) as client:
            response = client.get("/api/v1/drawing-qa/pages/page:missing/summary")

        self.assertEqual(404, response.status_code)
        self.assertEqual("NOT_FOUND", response.json()["error"]["category"])


class QAHttpBlockRelationsRouteTests(unittest.TestCase):
    """GET block relations route must build the block_relations QARequest only."""

    def test_get_block_relations_builds_block_relations_request(self):
        service = RecordingQAService()
        app = _app_with_service(service)

        with TestClient(app) as client:
            response = client.get("/api/v1/drawing-qa/blocks/block:1/relations")

        self.assertEqual(200, response.status_code)
        request = service.requests[0]
        self.assertIs(QuestionType.BLOCK_RELATIONS, request.question_type)
        self.assertEqual("block:1", request.scope.block_id)
        self.assertIsNone(request.scope.page_id)
        self.assertTrue(request.include_candidates)
        self.assertFalse(request.include_payload)
        self.assertFalse(request.write_back)
        self.assertEqual("json", request.format_hint)

    def test_include_candidates_query_flag_is_forwarded(self):
        service = RecordingQAService()
        app = _app_with_service(service)

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/drawing-qa/blocks/block:1/relations",
                params={"include_candidates": "false"},
            )

        self.assertEqual(200, response.status_code)
        self.assertFalse(service.requests[0].include_candidates)

    def test_candidate_output_stays_candidate_relation(self):
        answer = QAAnswer(
            question_type=QuestionType.BLOCK_RELATIONS,
            scope=QAScope(block_id="block:1"),
            status=QAAnswerStatus.ANSWERED,
            summary="候选关系保持候选",
            facts=(
                AnswerFact(
                    fact_kind="candidate_relation",
                    label="候选",
                    status="candidate",
                    relation_type="CANDIDATE_CAPTION_OF",
                ),
            ),
        )
        app = _app_with_service(RecordingQAService(answer=answer))

        with TestClient(app) as client:
            response = client.get("/api/v1/drawing-qa/blocks/block:1/relations")

        self.assertEqual(200, response.status_code)
        self.assertEqual("candidate_relation", response.json()["data"]["facts"][0]["fact_kind"])


class QAHttpCandidateRelationsRouteTests(unittest.TestCase):
    """GET candidates route must pass page/block scope without upgrading facts."""

    def test_get_candidates_passes_both_scope_ids(self):
        service = RecordingQAService()
        app = _app_with_service(service)

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/drawing-qa/candidates",
                params={"page_id": "page:1", "block_id": "block:1"},
            )

        self.assertEqual(200, response.status_code)
        request = service.requests[0]
        self.assertIs(QuestionType.CANDIDATE_RELATIONS, request.question_type)
        self.assertEqual("page:1", request.scope.page_id)
        self.assertEqual("block:1", request.scope.block_id)
        self.assertFalse(request.write_back)
        self.assertEqual("json", request.format_hint)

    def test_get_candidates_accepts_block_only_scope(self):
        service = RecordingQAService()
        app = _app_with_service(service)

        with TestClient(app) as client:
            response = client.get("/api/v1/drawing-qa/candidates", params={"block_id": "block:1"})

        self.assertEqual(200, response.status_code)
        request = service.requests[0]
        self.assertIsNone(request.scope.page_id)
        self.assertEqual("block:1", request.scope.block_id)

    def test_get_candidates_without_scope_is_rejected(self):
        app = _app_with_service(DrawingGraphQAService(FakeFacade()))

        with TestClient(app) as client:
            response = client.get("/api/v1/drawing-qa/candidates")

        self.assertEqual(422, response.status_code)
        self.assertEqual("INVALID_ARGUMENT", response.json()["error"]["category"])

    def test_matched_candidate_is_not_upgraded_to_formal(self):
        answer = QAAnswer(
            question_type=QuestionType.CANDIDATE_RELATIONS,
            scope=QAScope(page_id="page:1"),
            status=QAAnswerStatus.ANSWERED,
            summary="候选匹配",
            facts=(
                AnswerFact(
                    fact_kind="candidate_relation",
                    label="候选匹配",
                    status="matched_candidate",
                    relation_type="CANDIDATE_MATCHES_SECTION_CAPTION",
                ),
            ),
        )
        app = _app_with_service(RecordingQAService(answer=answer))

        with TestClient(app) as client:
            response = client.get("/api/v1/drawing-qa/candidates", params={"page_id": "page:1"})

        self.assertEqual(200, response.status_code)
        fact = response.json()["data"]["facts"][0]
        self.assertEqual("candidate_relation", fact["fact_kind"])
        self.assertEqual("matched_candidate", fact["status"])


class QAHttpSectionMatchesRouteTests(unittest.TestCase):
    """GET section-matches route must pass scope without calling match logic directly."""

    def test_get_section_matches_passes_both_scope_ids(self):
        service = RecordingQAService()
        app = _app_with_service(service)

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/drawing-qa/section-matches",
                params={"cross_section_id": "cross:1", "page_id": "page:1"},
            )

        self.assertEqual(200, response.status_code)
        request = service.requests[0]
        self.assertIs(QuestionType.SECTION_MATCHES, request.question_type)
        self.assertEqual("cross:1", request.scope.cross_section_id)
        self.assertEqual("page:1", request.scope.page_id)
        self.assertFalse(request.write_back)
        self.assertEqual("json", request.format_hint)

    def test_get_section_matches_accepts_cross_section_only(self):
        service = RecordingQAService()
        app = _app_with_service(service)

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/drawing-qa/section-matches",
                params={"cross_section_id": "cross:1"},
            )

        self.assertEqual(200, response.status_code)
        self.assertIsNone(service.requests[0].scope.page_id)
        self.assertEqual("cross:1", service.requests[0].scope.cross_section_id)

    def test_get_section_matches_without_scope_is_rejected(self):
        app = _app_with_service(DrawingGraphQAService(FakeFacade()))

        with TestClient(app) as client:
            response = client.get("/api/v1/drawing-qa/section-matches")

        self.assertEqual(422, response.status_code)
        self.assertEqual("INVALID_ARGUMENT", response.json()["error"]["category"])

    def test_formal_and_candidate_semantics_are_preserved(self):
        answer = QAAnswer(
            question_type=QuestionType.SECTION_MATCHES,
            scope=QAScope(cross_section_id="cross:1"),
            status=QAAnswerStatus.ANSWERED,
            summary="断面匹配",
            facts=(
                AnswerFact(
                    fact_kind="candidate_relation",
                    label="候选匹配",
                    status="candidate",
                    relation_type="CANDIDATE_MATCHES_SECTION_CAPTION",
                ),
                AnswerFact(
                    fact_kind="formal_relation",
                    label="正式匹配",
                    status="confirmed",
                    relation_type="MATCHES_SECTION_CAPTION",
                ),
            ),
        )
        app = _app_with_service(RecordingQAService(answer=answer))

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/drawing-qa/section-matches",
                params={"cross_section_id": "cross:1"},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            ["candidate_relation", "formal_relation"],
            [fact["fact_kind"] for fact in response.json()["data"]["facts"]],
        )


class QAHttpTableCaptionRouteTests(unittest.TestCase):
    """GET table caption status route must pass scope and preserve partial gaps."""

    def test_get_table_caption_status_passes_all_scope_ids(self):
        service = RecordingQAService()
        app = _app_with_service(service)

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/drawing-qa/table-captions/status",
                params={
                    "page_id": "page:1",
                    "table_id": "table:1",
                    "table_caption_id": "tc:1",
                },
            )

        self.assertEqual(200, response.status_code)
        request = service.requests[0]
        self.assertIs(QuestionType.TABLE_CAPTION_STATUS, request.question_type)
        self.assertEqual("page:1", request.scope.page_id)
        self.assertEqual("table:1", request.scope.table_id)
        self.assertEqual("tc:1", request.scope.table_caption_id)
        self.assertFalse(request.write_back)
        self.assertEqual("json", request.format_hint)

    def test_get_table_caption_status_accepts_table_only(self):
        service = RecordingQAService()
        app = _app_with_service(service)

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/drawing-qa/table-captions/status",
                params={"table_id": "table:1"},
            )

        self.assertEqual(200, response.status_code)
        request = service.requests[0]
        self.assertIsNone(request.scope.page_id)
        self.assertEqual("table:1", request.scope.table_id)

    def test_get_table_caption_status_without_scope_is_rejected(self):
        app = _app_with_service(DrawingGraphQAService(FakeFacade()))

        with TestClient(app) as client:
            response = client.get("/api/v1/drawing-qa/table-captions/status")

        self.assertEqual(422, response.status_code)
        self.assertEqual("INVALID_ARGUMENT", response.json()["error"]["category"])

    def test_partial_status_returns_200_with_unsupported_parts(self):
        answer = QAAnswer(
            question_type=QuestionType.TABLE_CAPTION_STATUS,
            scope=QAScope(table_id="table:1"),
            status=QAAnswerStatus.PARTIAL,
            summary="表格标题状态部分可用",
            warnings=("能力不足",),
            unsupported_parts=("表格标题语义未增强",),
        )
        app = _app_with_service(RecordingQAService(answer=answer))

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/drawing-qa/table-captions/status",
                params={"table_id": "table:1"},
            )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(["能力不足"], payload["data"]["warnings"])
        self.assertEqual(["表格标题语义未增强"], payload["data"]["unsupported_parts"])


class QAHttpDiagnosticRouteTests(unittest.TestCase):
    """GET diagnostics route must pass flags and never fabricate verification status."""

    def test_get_diagnostics_passes_scope_and_flags(self):
        service = RecordingQAService()
        app = _app_with_service(service)

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/drawing-qa/diagnostics",
                params={
                    "page_id": "page:1",
                    "block_id": "block:1",
                    "include_semantics": "false",
                    "include_candidates": "false",
                },
            )

        self.assertEqual(200, response.status_code)
        request = service.requests[0]
        self.assertIs(QuestionType.DIAGNOSTIC_STATUS, request.question_type)
        self.assertEqual("page:1", request.scope.page_id)
        self.assertEqual("block:1", request.scope.block_id)
        self.assertFalse(request.include_semantics)
        self.assertFalse(request.include_candidates)
        self.assertFalse(request.write_back)
        self.assertEqual("json", request.format_hint)

    def test_get_diagnostics_accepts_page_only_with_default_flags(self):
        service = RecordingQAService()
        app = _app_with_service(service)

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/drawing-qa/diagnostics",
                params={"page_id": "page:1"},
            )

        self.assertEqual(200, response.status_code)
        request = service.requests[0]
        self.assertIsNone(request.scope.block_id)
        self.assertTrue(request.include_semantics)
        self.assertTrue(request.include_candidates)

    def test_get_diagnostics_without_scope_is_rejected(self):
        app = _app_with_service(DrawingGraphQAService(FakeFacade()))

        with TestClient(app) as client:
            response = client.get("/api/v1/drawing-qa/diagnostics")

        self.assertEqual(422, response.status_code)
        self.assertEqual("INVALID_ARGUMENT", response.json()["error"]["category"])

    def test_response_does_not_fabricate_neo4j_verification_status(self):
        service = RecordingQAService()
        app = _app_with_service(service)

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/drawing-qa/diagnostics",
                params={"page_id": "page:1"},
            )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertNotIn("neo4j_status", payload)
        self.assertNotIn("live", payload["data"]["summary"].lower())


class QAHttpLiveHealthTests(unittest.TestCase):
    """GET /health/live must report ASGI liveness without touching the runtime."""

    def test_live_returns_status_and_contract(self):
        service = RecordingQAService()
        app = _app_with_service(service)

        with TestClient(app) as client:
            response = client.get("/health/live")

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("live", payload["status"])
        self.assertEqual("drawing-graph-qa-http", payload["service"])
        self.assertEqual("drawing-qa-http-v1", payload["contract_version"])
        self.assertEqual(0, service.ask_calls)

    def test_live_does_not_expose_sensitive_or_environment_fields(self):
        app = _app_with_service(RecordingQAService())

        with TestClient(app) as client:
            response = client.get("/health/live")

        payload = response.json()
        for field in (
            "host",
            "port",
            "neo4j_uri",
            "neo4j_user",
            "password",
            "api_token",
            "neo4j_status",
            "data_path",
            "count",
        ):
            self.assertNotIn(field, payload)


class QAHttpReadyHealthTests(unittest.TestCase):
    """GET /health/ready must check runtime assembly without claiming Neo4j checks."""

    def test_ready_returns_not_checked_neo4j_status(self):
        app = _app_with_service(RecordingQAService())

        with TestClient(app) as client:
            response = client.get("/health/ready")

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("ready", payload["status"])
        self.assertEqual("drawing-graph-qa-http", payload["service"])
        self.assertEqual("drawing-qa-http-v1", payload["contract_version"])
        self.assertEqual("not_checked", payload["neo4j_status"])

    def test_ready_returns_503_when_runtime_not_ready(self):
        from drawing_graph.qa_http import create_app

        class NotReadyRuntime:
            ready = False

            def close(self):
                pass

        app = create_app(_config(), runtime_factory=lambda config: NotReadyRuntime())

        with TestClient(app) as client:
            response = client.get("/health/ready")

        self.assertEqual(503, response.status_code)
        payload = response.json()
        self.assertEqual("FACADE_UNAVAILABLE", payload["error"]["category"])
        self.assertIs(True, payload["error"]["retryable"])

    def test_ready_handler_never_runs_database_checks(self):
        source = (PROJECT_ROOT / "src" / "drawing_graph" / "qa_http.py").read_text(encoding="utf-8")
        for forbidden in ("verify_connectivity", "session(", ".run(", "cypher"):
            self.assertNotIn(forbidden, source.lower())


class QAHttpAuthenticationTests(unittest.TestCase):
    """Optional Bearer token auth must protect business routes and readiness."""

    def _token_config(self):
        return QAHttpConfig(
            neo4j_uri="bolt://localhost:7687",
            neo4j_user="neo4j",
            neo4j_password="auth-test-secret",
            api_token="test-token-123",
        )

    def test_no_token_configured_allows_business_requests(self):
        app = _app_with_service(RecordingQAService())

        with TestClient(app) as client:
            response = client.get("/api/v1/drawing-qa/pages/page:1/summary")

        self.assertEqual(200, response.status_code)

    def test_missing_credentials_returns_authentication_required(self):
        app = _app_with_service(RecordingQAService(), config=self._token_config())

        with TestClient(app) as client:
            response = client.get("/api/v1/drawing-qa/pages/page:1/summary")

        self.assertEqual(401, response.status_code)
        payload = response.json()
        self.assertEqual("AUTHENTICATION_REQUIRED", payload["error"]["category"])
        self.assertIn("X-Request-ID", response.headers)

    def test_wrong_credentials_returns_authentication_failed(self):
        app = _app_with_service(RecordingQAService(), config=self._token_config())

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/drawing-qa/pages/page:1/summary",
                headers={"Authorization": "Bearer wrong-token"},
            )

        self.assertEqual(401, response.status_code)
        self.assertEqual("AUTHENTICATION_FAILED", response.json()["error"]["category"])

    def test_correct_credentials_allow_request(self):
        app = _app_with_service(RecordingQAService(), config=self._token_config())

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/drawing-qa/pages/page:1/summary",
                headers={"Authorization": "Bearer test-token-123"},
            )

        self.assertEqual(200, response.status_code)

    def test_live_health_stays_anonymous_when_token_configured(self):
        app = _app_with_service(RecordingQAService(), config=self._token_config())

        with TestClient(app) as client:
            response = client.get("/health/live")

        self.assertEqual(200, response.status_code)
        self.assertEqual("live", response.json()["status"])

    def test_ready_health_requires_auth_when_token_configured(self):
        app = _app_with_service(RecordingQAService(), config=self._token_config())

        with TestClient(app) as client:
            anonymous = client.get("/health/ready")
            authenticated = client.get(
                "/health/ready",
                headers={"Authorization": "Bearer test-token-123"},
            )

        self.assertEqual(401, anonymous.status_code)
        self.assertEqual(200, authenticated.status_code)

    def test_token_value_is_never_exposed_in_responses(self):
        app = _app_with_service(RecordingQAService(), config=self._token_config())

        with TestClient(app) as client:
            response = client.get("/api/v1/drawing-qa/pages/page:1/summary")

        self.assertNotIn("test-token-123", response.text)
        self.assertNotIn("test-token-123", str(response.headers))


class QAHttpCorsTests(unittest.TestCase):
    """CORS must be opt-in, explicit, and never wildcarded."""

    def _cors_config(self, origins=("https://app.example.com",)):
        return QAHttpConfig(
            neo4j_uri="bolt://localhost:7687",
            neo4j_user="neo4j",
            neo4j_password="cors-test-secret",
            allowed_origins=origins,
        )

    def test_no_origins_means_no_cors_headers(self):
        app = _app_with_service(RecordingQAService())

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/drawing-qa/pages/page:1/summary",
                headers={"Origin": "https://other.example.com"},
            )

        self.assertEqual(200, response.status_code)
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_preflight_allows_only_configured_origin_without_credentials(self):
        app = _app_with_service(RecordingQAService(), config=self._cors_config())

        with TestClient(app) as client:
            response = client.options(
                "/api/v1/drawing-qa/pages/page:1/summary",
                headers={
                    "Origin": "https://app.example.com",
                    "Access-Control-Request-Method": "GET",
                },
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            "https://app.example.com",
            response.headers["access-control-allow-origin"],
        )
        self.assertNotIn("access-control-allow-credentials", response.headers)
        allowed_methods = response.headers["access-control-allow-methods"]
        for method in ("GET", "POST", "OPTIONS"):
            self.assertIn(method, allowed_methods)

    def test_allowed_origin_gets_cors_header_on_normal_request(self):
        app = _app_with_service(RecordingQAService(), config=self._cors_config())

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/drawing-qa/pages/page:1/summary",
                headers={"Origin": "https://app.example.com"},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            "https://app.example.com",
            response.headers["access-control-allow-origin"],
        )

    def test_disallowed_origin_gets_no_cors_header(self):
        app = _app_with_service(RecordingQAService(), config=self._cors_config())

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/drawing-qa/pages/page:1/summary",
                headers={"Origin": "https://evil.example.com"},
            )

        self.assertEqual(200, response.status_code)
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_preflight_bypasses_auth_but_normal_requests_still_require_token(self):
        config = QAHttpConfig(
            neo4j_uri="bolt://localhost:7687",
            neo4j_user="neo4j",
            neo4j_password="cors-auth-test-secret",
            allowed_origins=("https://app.example.com",),
            api_token="cors-token-1",
        )
        app = _app_with_service(RecordingQAService(), config=config)

        with TestClient(app) as client:
            preflight = client.options(
                "/api/v1/drawing-qa/pages/page:1/summary",
                headers={
                    "Origin": "https://app.example.com",
                    "Access-Control-Request-Method": "GET",
                },
            )
            anonymous = client.get(
                "/api/v1/drawing-qa/pages/page:1/summary",
                headers={"Origin": "https://app.example.com"},
            )
            authenticated = client.get(
                "/api/v1/drawing-qa/pages/page:1/summary",
                headers={
                    "Origin": "https://app.example.com",
                    "Authorization": "Bearer cors-token-1",
                },
            )

        self.assertEqual(200, preflight.status_code)
        self.assertEqual(401, anonymous.status_code)
        self.assertEqual(200, authenticated.status_code)


class QAHttpRequestSizeTests(unittest.TestCase):
    """Request bodies must be limited by actual received bytes, not declared length."""

    def _small_limit_config(self):
        return QAHttpConfig(
            neo4j_uri="bolt://localhost:7687",
            neo4j_user="neo4j",
            neo4j_password="size-test-secret",
            max_request_bytes=200,
        )

    def test_oversized_request_returns_413_without_calling_service(self):
        service = RecordingQAService()
        app = _app_with_service(service, config=self._small_limit_config())
        oversized_payload = {
            "question_type": "page_summary",
            "scope": {"page_id": "page:" + "x" * 500},
        }

        with TestClient(app) as client:
            response = client.post("/api/v1/drawing-qa/ask", json=oversized_payload)

        self.assertEqual(413, response.status_code)
        payload = response.json()
        self.assertEqual("REQUEST_TOO_LARGE", payload["error"]["category"])
        self.assertIs(False, payload["error"]["retryable"])
        self.assertIn("X-Request-ID", response.headers)
        self.assertEqual(0, service.ask_calls)
        self.assertNotIn("x" * 500, response.text)

    def test_small_request_still_works_with_same_limit(self):
        service = RecordingQAService()
        app = _app_with_service(service, config=self._small_limit_config())

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/drawing-qa/ask",
                json={"question_type": "page_summary", "scope": {"page_id": "page:1"}},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, service.ask_calls)

    def test_actual_bytes_are_counted_not_content_length(self):
        from drawing_graph.qa_http import _RequestBodySizeLimitMiddleware

        async def consume_app(scope, receive, send):
            while True:
                message = await receive()
                if message["type"] == "http.request" and not message.get("more_body", False):
                    break
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        async def scenario():
            chunks = [b"x" * 100, b"y" * 100]  # 200 actual bytes; declared length is 10
            sent = []

            async def receive():
                if chunks:
                    return {
                        "type": "http.request",
                        "body": chunks.pop(0),
                        "more_body": bool(chunks),
                    }
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send(message):
                sent.append(message)

            scope = {
                "type": "http",
                "method": "POST",
                "path": "/api/v1/drawing-qa/ask",
                "headers": [(b"content-length", b"10")],
                "state": {"request_id": "req-size-1"},
            }
            middleware = _RequestBodySizeLimitMiddleware(consume_app, max_request_bytes=150)
            await middleware(scope, receive, send)
            return sent

        sent = asyncio.run(scenario())
        self.assertEqual("http.response.start", sent[0]["type"])
        self.assertEqual(413, sent[0]["status"])


class QAHttpConcurrencyLimitTests(unittest.TestCase):
    """Concurrency capacity must reject extra requests without touching the service."""

    def test_capacity_held_until_ask_finishes_then_released(self):
        started = threading.Event()
        release = threading.Event()

        class BlockingService(RecordingQAService):
            def ask(self, request):
                started.set()
                release.wait(5)
                return super().ask(request)

        service = BlockingService()
        config = QAHttpConfig(
            neo4j_uri="bolt://localhost:7687",
            neo4j_user="neo4j",
            neo4j_password="concurrency-test-secret",
            max_concurrent_requests=1,
        )
        app = _app_with_service(service, config=config)
        results = []

        with TestClient(app) as client:
            def first_request():
                results.append(client.get("/api/v1/drawing-qa/pages/page:1/summary"))

            thread = threading.Thread(target=first_request)
            thread.start()
            self.assertTrue(started.wait(2), "first request did not reach the service")

            rejected = client.get("/api/v1/drawing-qa/pages/page:2/summary")

            self.assertEqual(429, rejected.status_code)
            self.assertEqual("TOO_MANY_REQUESTS", rejected.json()["error"]["category"])
            self.assertIs(False, rejected.json()["error"]["retryable"])

            release.set()
            thread.join(3)
            self.assertEqual(200, results[0].status_code)
            self.assertEqual(1, service.ask_calls)

            after_release = client.get("/api/v1/drawing-qa/pages/page:3/summary")

        self.assertEqual(200, after_release.status_code)
        self.assertEqual(2, service.ask_calls)


class QAHttpTimeoutTests(unittest.TestCase):
    """Client wait timeout must return 504 without pretending to cancel the backend."""

    def test_timeout_returns_504_and_capacity_stays_held_until_ask_ends(self):
        started = threading.Event()
        release = threading.Event()
        first_done = threading.Event()

        class SlowService(RecordingQAService):
            def ask(self, request):
                started.set()
                release.wait(5)
                return super().ask(request)

        service = SlowService()
        config = QAHttpConfig(
            neo4j_uri="bolt://localhost:7687",
            neo4j_user="neo4j",
            neo4j_password="timeout-test-secret",
            max_concurrent_requests=1,
            request_timeout_seconds=0.1,
        )
        app = _app_with_service(service, config=config)
        results = []

        with TestClient(app) as client:
            def first_request():
                results.append(client.get("/api/v1/drawing-qa/pages/page:1/summary"))
                first_done.set()

            thread = threading.Thread(target=first_request)
            thread.start()
            self.assertTrue(started.wait(2), "first request did not reach the service")
            self.assertTrue(first_done.wait(2), "first request did not time out")

            timed_out = results[0]
            self.assertEqual(504, timed_out.status_code)
            self.assertEqual("REQUEST_TIMEOUT", timed_out.json()["error"]["category"])
            self.assertIs(False, timed_out.json()["error"]["retryable"])

            still_held = client.get("/api/v1/drawing-qa/pages/page:2/summary")
            self.assertEqual(429, still_held.status_code)

            release.set()
            deadline = time.time() + 2
            while service.ask_calls < 1 and time.time() < deadline:
                time.sleep(0.02)
            thread.join(3)
            self.assertEqual(1, service.ask_calls)

            after_completion = client.get("/api/v1/drawing-qa/pages/page:3/summary")

        self.assertEqual(200, after_completion.status_code)
        self.assertEqual(2, service.ask_calls)

    def test_timeout_message_has_no_request_or_secret_details(self):
        started = threading.Event()
        release = threading.Event()

        class SlowService(RecordingQAService):
            def ask(self, request):
                started.set()
                release.wait(5)
                return super().ask(request)

        config = QAHttpConfig(
            neo4j_uri="bolt://localhost:7687",
            neo4j_user="neo4j",
            neo4j_password="timeout-test-secret",
            request_timeout_seconds=0.05,
        )
        app = _app_with_service(SlowService(), config=config)

        with TestClient(app) as client:
            response = client.get("/api/v1/drawing-qa/pages/page:1/summary")

        self.assertEqual(504, response.status_code)
        self.assertNotIn("page:1", response.text)
        self.assertNotIn("timeout-test-secret", response.text)
        release.set()


class QAHttpProtocolErrorTests(unittest.TestCase):
    """Protocol errors must return the unified sanitized envelope."""

    def test_validation_error_returns_422_with_safe_details(self):
        app = _app_with_service(RecordingQAService())

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/drawing-qa/ask",
                json={"question_type": "not_a_question", "scope": {"page_id": "page:1"}},
            )

        self.assertEqual(422, response.status_code)
        payload = response.json()
        self.assertEqual("INVALID_ARGUMENT", payload["error"]["category"])
        details = payload["error"]["details"]
        self.assertIsInstance(details, list)
        self.assertGreater(len(details), 0)
        for item in details:
            self.assertIn("loc", item)
            self.assertIn("type", item)
            self.assertNotIn("input", item)
        self.assertNotIn("not_a_question", response.text)
        self.assertIn("X-Request-ID", response.headers)

    def test_unknown_route_returns_404_route_not_found(self):
        app = _app_with_service(RecordingQAService())

        with TestClient(app) as client:
            response = client.get("/api/v1/does-not-exist")

        self.assertEqual(404, response.status_code)
        payload = response.json()
        self.assertEqual("failed", payload["status"])
        self.assertEqual("ROUTE_NOT_FOUND", payload["error"]["category"])
        self.assertEqual("drawing-qa-http-v1", payload["meta"]["contract_version"])

    def test_wrong_method_returns_405_method_not_allowed(self):
        app = _app_with_service(RecordingQAService())

        with TestClient(app) as client:
            response = client.put(
                "/api/v1/drawing-qa/ask",
                json={"question_type": "page_summary", "scope": {"page_id": "page:1"}},
            )

        self.assertEqual(405, response.status_code)
        self.assertEqual("METHOD_NOT_ALLOWED", response.json()["error"]["category"])

    def test_unclassified_exception_returns_500_without_details(self):
        class ExplodingService(RecordingQAService):
            def ask(self, request):
                raise RuntimeError("boom neo4j password=protocol-secret")

        app = _app_with_service(ExplodingService())

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/api/v1/drawing-qa/pages/page:1/summary")

        self.assertEqual(500, response.status_code)
        payload = response.json()
        self.assertEqual("HTTP_INTERNAL_ERROR", payload["error"]["category"])
        self.assertNotIn("protocol-secret", response.text)
        self.assertNotIn("Traceback", response.text)
        self.assertNotIn("RuntimeError", response.text)

    def test_adapter_error_categories_are_not_qa_error_codes(self):
        from drawing_graph.qa_models import QAErrorCode

        qa_codes = {item.value for item in QAErrorCode}
        for category in (
            "AUTHENTICATION_REQUIRED",
            "AUTHENTICATION_FAILED",
            "REQUEST_TOO_LARGE",
            "TOO_MANY_REQUESTS",
            "REQUEST_TIMEOUT",
            "ROUTE_NOT_FOUND",
            "METHOD_NOT_ALLOWED",
            "HTTP_INTERNAL_ERROR",
        ):
            self.assertNotIn(category, qa_codes)


class QAHttpStaticBoundaryTests(unittest.TestCase):
    """Static guards: HTTP routes may only reach the QA service, never backends."""

    def _source(self, name):
        return (PROJECT_ROOT / "src" / "drawing_graph" / name).read_text(encoding="utf-8")

    def test_qa_http_imports_no_backend_modules(self):
        source = self._source("qa_http.py")
        for forbidden in (
            "query_service",
            "relation_repository",
            "block_relation_enrichment",
            "import_service",
            "candidate_review",
            "semantic_",
            "tool_facade",
            "tool_factory",
            "create_schema",
            "import_json",
            "enrich_block_relations",
            "review_candidate_relations",
            "from neo4j",
            "import neo4j",
            "GraphDatabase",
        ):
            self.assertNotIn(forbidden, source)

    def test_qa_http_has_no_cypher_session_or_transaction_access(self):
        source = self._source("qa_http.py").lower()
        for forbidden in ("cypher", ".session(", ".transaction(", ".run(", "verify_connectivity"):
            self.assertNotIn(forbidden, source)

    def test_business_routes_never_call_facade_methods_directly(self):
        source = self._source("qa_http.py")
        for forbidden in (
            ".get_page_source_facts",
            ".get_block_trace",
            ".get_block_relations",
            ".list_candidate_relations",
            ".list_section_matches",
            ".match_section_caption",
            ".recognize_page_semantics",
            ".review_candidate_relation",
            ".list_text_observations",
            ".list_interpretations",
            ".get_semantic_payload",
            ".get_recognition_run",
            ".list_pages",
            ".list_drawing_sets",
        ):
            self.assertNotIn(forbidden, source)

    def test_http_code_does_not_drive_import_enrichment_or_promotion(self):
        source = self._source("qa_http.py")
        for forbidden in (
            "import_all",
            "enrich_project",
            "enrich_drawing_set",
            "enrich_page",
            "promote_candidate",
            "update_candidate_review",
            "write_relations",
            "persist_observation",
            "persist_interpretation",
        ):
            self.assertNotIn(forbidden, source)

    def test_protected_domain_modules_do_not_depend_on_http_modules(self):
        protected = (
            "qa_models.py",
            "qa_service.py",
            "qa_rendering.py",
            "tool_facade.py",
            "tool_factory.py",
            "query_service.py",
            "relation_repository.py",
            "block_relation_enrichment.py",
            "import_service.py",
            "candidate_review.py",
            "semantic_models.py",
            "semantic_service.py",
            "semantic_repository.py",
            "semantic_neo4j_repository.py",
            "semantic_query_projection.py",
            "section_match_service.py",
        )
        for name in protected:
            with self.subTest(module=name):
                self.assertNotIn("qa_http", self._source(name))


if __name__ == "__main__":
    unittest.main()
