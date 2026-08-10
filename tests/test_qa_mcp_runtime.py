import unittest


class QAMcpRuntimeConstructionTests(unittest.TestCase):
    """QAMcpRuntime must assemble driver -> facade -> service with injectable factories."""

    def test_production_assembly_order_with_injected_factories(self):
        from drawing_graph.config import QAMcpConfig
        from drawing_graph.qa_mcp_runtime import QAMcpRuntime, create_qa_mcp_runtime

        config = QAMcpConfig(
            neo4j_uri="bolt://localhost:7687",
            neo4j_user="neo4j",
            neo4j_password="pw",
            log_level="INFO",
        )
        events = []
        fake_driver = object()
        fake_facade = object()
        fake_service = object()

        def driver_factory(uri, auth):
            events.append("driver")
            self.assertEqual("bolt://localhost:7687", uri)
            self.assertEqual(("neo4j", "pw"), auth)
            return fake_driver

        def facade_factory(driver):
            events.append("facade")
            self.assertIs(fake_driver, driver)
            return fake_facade

        def service_factory(facade):
            events.append("service")
            self.assertIs(fake_facade, facade)
            return fake_service

        runtime = create_qa_mcp_runtime(
            config,
            driver_factory=driver_factory,
            facade_factory=facade_factory,
            service_factory=service_factory,
        )

        self.assertEqual(["driver", "facade", "service"], events)
        self.assertIsInstance(runtime, QAMcpRuntime)
        self.assertIs(fake_driver, runtime.driver)
        self.assertIs(fake_facade, runtime.facade)
        self.assertIs(fake_service, runtime.service)
        self.assertTrue(runtime.ready)

    def test_factories_are_called_once_and_service_is_reused(self):
        from drawing_graph.config import QAMcpConfig
        from drawing_graph.qa_mcp_runtime import create_qa_mcp_runtime

        config = QAMcpConfig(
            neo4j_uri="bolt://localhost:7687",
            neo4j_user="neo4j",
            neo4j_password="pw",
            log_level="INFO",
        )
        counts = {"driver": 0, "facade": 0, "service": 0}
        fake_driver = object()
        fake_facade = object()
        fake_service = object()

        def driver_factory(uri, auth):
            counts["driver"] += 1
            return fake_driver

        def facade_factory(driver):
            counts["facade"] += 1
            return fake_facade

        def service_factory(facade):
            counts["service"] += 1
            return fake_service

        runtime = create_qa_mcp_runtime(
            config,
            driver_factory=driver_factory,
            facade_factory=facade_factory,
            service_factory=service_factory,
        )

        self.assertEqual({"driver": 1, "facade": 1, "service": 1}, counts)
        self.assertIs(fake_service, runtime.service)

    def test_default_factories_are_production_wiring(self):
        from drawing_graph.qa_mcp_runtime import (
            _default_driver_factory,
            _default_facade_factory,
            _default_service_factory,
        )
        from drawing_graph.qa_service import DrawingGraphQAService
        from drawing_graph.tool_factory import create_neo4j_tool_facade

        self.assertIs(create_neo4j_tool_facade, _default_facade_factory)
        self.assertIs(DrawingGraphQAService, _default_service_factory)
        self.assertTrue(callable(_default_driver_factory))

    def test_module_import_has_no_env_read_or_connection_side_effect(self):
        import os
        import subprocess
        import sys
        from pathlib import Path

        code = (
            "import sys\n"
            "import drawing_graph.qa_mcp_runtime as module\n"
            "assert 'neo4j' not in sys.modules\n"
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
        self.assertIn("import-ok", result.stdout)

    def test_runtime_does_not_inherit_or_import_http_runtime(self):
        import ast
        from pathlib import Path

        source = Path("src/drawing_graph/qa_mcp_runtime.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

        self.assertNotIn("drawing_graph.qa_http_runtime", imported)
        self.assertNotIn("drawing_graph.qa_http", imported)


class QAMcpRuntimeCleanupTests(unittest.TestCase):
    """Runtime must clean up partial initialization and close idempotently."""

    def _config(self):
        from drawing_graph.config import QAMcpConfig

        return QAMcpConfig(
            neo4j_uri="bolt://localhost:7687",
            neo4j_user="neo4j",
            neo4j_password="pw",
            log_level="INFO",
        )

    def test_facade_failure_closes_driver_exactly_once(self):
        from drawing_graph.qa_mcp_runtime import create_qa_mcp_runtime

        driver = _CountingDriver()

        def driver_factory(uri, auth):
            return driver

        def facade_factory(facade_driver):
            raise RuntimeError("facade construction failed")

        with self.assertRaises(RuntimeError):
            create_qa_mcp_runtime(
                self._config(),
                driver_factory=driver_factory,
                facade_factory=facade_factory,
            )

        self.assertEqual(1, driver.close_calls)

    def test_service_failure_closes_driver_exactly_once(self):
        from drawing_graph.qa_mcp_runtime import create_qa_mcp_runtime

        driver = _CountingDriver()
        fake_facade = object()

        def driver_factory(uri, auth):
            return driver

        def facade_factory(facade_driver):
            return fake_facade

        def service_factory(facade):
            raise RuntimeError("service construction failed")

        with self.assertRaises(RuntimeError):
            create_qa_mcp_runtime(
                self._config(),
                driver_factory=driver_factory,
                facade_factory=facade_factory,
                service_factory=service_factory,
            )

        self.assertEqual(1, driver.close_calls)

    def test_normal_close_is_idempotent(self):
        from drawing_graph.qa_mcp_runtime import create_qa_mcp_runtime

        driver = _CountingDriver()
        runtime = create_qa_mcp_runtime(
            self._config(),
            driver_factory=lambda uri, auth: driver,
            facade_factory=lambda d: object(),
            service_factory=lambda f: object(),
        )

        runtime.close()
        runtime.close()
        runtime.close()

        self.assertEqual(1, driver.close_calls)
        self.assertFalse(runtime.ready)
        self.assertIsNone(runtime.driver)
        self.assertIsNone(runtime.facade)
        self.assertIsNone(runtime.service)

    def test_close_failure_does_not_leak_uri_user_or_password(self):
        from drawing_graph.qa_mcp_runtime import create_qa_mcp_runtime

        driver = _CountingDriver(
            close_error=RuntimeError(
                "close failed bolt://neo4j:secret@localhost:7687 neo4j://"
            )
        )
        runtime = create_qa_mcp_runtime(
            self._config(),
            driver_factory=lambda uri, auth: driver,
            facade_factory=lambda d: object(),
            service_factory=lambda f: object(),
        )

        with self.assertLogs("drawing_graph.qa_mcp_runtime", level="ERROR") as logs:
            runtime.close()

        self.assertEqual(1, driver.close_calls)
        log_text = "".join(logs.output)
        self.assertNotIn("secret", log_text)
        self.assertNotIn("bolt://", log_text)
        self.assertNotIn("neo4j://", log_text)

    def test_no_threading_singleton_or_runtime_base_class(self):
        import ast
        from pathlib import Path

        from drawing_graph.qa_mcp_runtime import QAMcpRuntime

        self.assertEqual((object,), QAMcpRuntime.__bases__)
        source = Path("src/drawing_graph/qa_mcp_runtime.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        self.assertFalse(any(name.startswith("threading") for name in imported))
        self.assertNotIn("singleton", source.lower())


class _CountingDriver:
    """Fake driver that counts close() calls and can fail on close."""

    def __init__(self, close_error=None):
        self.close_calls = 0
        self.close_error = close_error

    def close(self):
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error


if __name__ == "__main__":
    unittest.main()
