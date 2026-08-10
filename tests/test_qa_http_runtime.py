"""Tests for the process-local HTTP QA runtime."""

from __future__ import annotations

import unittest

from drawing_graph.config import QAHttpConfig


def _config() -> QAHttpConfig:
    return QAHttpConfig(
        neo4j_uri="bolt://localhost:7687",
        neo4j_user="neo4j",
        neo4j_password="runtime-test-secret",
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


class QAHttpRuntimeTests(unittest.TestCase):
    """QAHttpRuntime must assemble injectable resources and close them safely."""

    def test_runtime_holds_injected_resources_and_starts_ready(self):
        from drawing_graph.qa_http_runtime import create_qa_http_runtime

        driver = FakeDriver()
        facade = FakeFacade()
        service = FakeService(facade)
        runtime = create_qa_http_runtime(
            _config(),
            driver_factory=lambda uri, auth: driver,
            facade_factory=lambda d: facade,
            service_factory=lambda f: service,
        )

        self.assertIs(driver, runtime.driver)
        self.assertIs(facade, runtime.facade)
        self.assertIs(service, runtime.service)
        self.assertTrue(runtime.ready)
        self.assertEqual("bolt://localhost:7687", runtime.config.neo4j_uri)

    def test_driver_factory_receives_uri_and_auth(self):
        from drawing_graph.qa_http_runtime import create_qa_http_runtime

        captured = {}
        facade = FakeFacade()

        def driver_factory(uri, auth):
            captured["uri"] = uri
            captured["auth"] = auth
            return FakeDriver()

        runtime = create_qa_http_runtime(
            _config(),
            driver_factory=driver_factory,
            facade_factory=lambda d: facade,
            service_factory=lambda f: FakeService(f),
        )
        self.assertEqual("bolt://localhost:7687", captured["uri"])
        self.assertEqual(("neo4j", "runtime-test-secret"), captured["auth"])
        runtime.close()

    def test_default_factories_are_the_documented_wiring(self):
        import drawing_graph.qa_http_runtime as runtime_module
        from drawing_graph.qa_service import DrawingGraphQAService
        from drawing_graph.tool_factory import create_neo4j_tool_facade

        self.assertIs(create_neo4j_tool_facade, runtime_module._default_facade_factory)
        self.assertIs(DrawingGraphQAService, runtime_module._default_service_factory)
        self.assertTrue(callable(runtime_module._default_driver_factory))

    def test_default_factories_build_offline_runtime_without_connecting(self):
        from drawing_graph.qa_http_runtime import create_qa_http_runtime

        runtime = create_qa_http_runtime(_config())
        self.assertIsNotNone(runtime.driver)
        self.assertIsNotNone(runtime.facade)
        self.assertIsNotNone(runtime.service)
        self.assertTrue(runtime.ready)
        runtime.close()
        self.assertFalse(runtime.ready)

    def test_facade_failure_closes_created_driver_and_reraises(self):
        from drawing_graph.qa_http_runtime import create_qa_http_runtime

        driver = FakeDriver()
        with self.assertRaises(RuntimeError):
            create_qa_http_runtime(
                _config(),
                driver_factory=lambda uri, auth: driver,
                facade_factory=lambda d: (_ for _ in ()).throw(RuntimeError("facade init failed")),
                service_factory=lambda f: FakeService(f),
            )
        self.assertEqual(1, driver.close_calls)

    def test_service_failure_closes_created_driver_and_reraises(self):
        from drawing_graph.qa_http_runtime import create_qa_http_runtime

        driver = FakeDriver()
        with self.assertRaises(RuntimeError):
            create_qa_http_runtime(
                _config(),
                driver_factory=lambda uri, auth: driver,
                facade_factory=lambda d: FakeFacade(),
                service_factory=lambda f: (_ for _ in ()).throw(RuntimeError("service init failed")),
            )
        self.assertEqual(1, driver.close_calls)

    def test_close_is_idempotent_and_clears_resources(self):
        from drawing_graph.qa_http_runtime import create_qa_http_runtime

        driver = FakeDriver()
        facade = FakeFacade()
        service = FakeService(facade)
        runtime = create_qa_http_runtime(
            _config(),
            driver_factory=lambda uri, auth: driver,
            facade_factory=lambda d: facade,
            service_factory=lambda f: service,
        )

        runtime.close()
        runtime.close()

        self.assertEqual(1, driver.close_calls)
        self.assertFalse(runtime.ready)
        self.assertIsNone(runtime.driver)
        self.assertIsNone(runtime.facade)
        self.assertIsNone(runtime.service)

    def test_close_swallows_low_level_driver_error(self):
        from drawing_graph.qa_http_runtime import create_qa_http_runtime

        class FailingCloseDriver(FakeDriver):
            def close(self):
                raise RuntimeError("bolt://secret driver close failed")

        driver = FailingCloseDriver()
        runtime = create_qa_http_runtime(
            _config(),
            driver_factory=lambda uri, auth: driver,
            facade_factory=lambda d: FakeFacade(),
            service_factory=lambda f: FakeService(f),
        )

        runtime.close()  # must not raise
        self.assertFalse(runtime.ready)

    def test_runtime_module_has_no_forbidden_backend_paths(self):
        from pathlib import Path

        project_root = Path(__file__).resolve().parents[1]
        source = (project_root / "src" / "drawing_graph" / "qa_http_runtime.py").read_text(encoding="utf-8")
        for forbidden in (
            "from .relation_repository",
            "from .block_relation_enrichment",
            "from .import_service",
            "import_json",
            "enrich_block_relations",
            "review_candidate_relations",
            "create_schema",
            ".session(",
            ".transaction(",
            ".run(",
        ):
            self.assertNotIn(forbidden, source.lower())


if __name__ == "__main__":
    unittest.main()
