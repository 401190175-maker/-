"""Tests for the product HTTP runtime and its configuration."""

import os
import unittest
from unittest import mock

from drawing_graph.config import AssistantHttpConfig, ConfigError


def _config(**overrides):
    values = {
        "neo4j_uri": "bolt://example",
        "neo4j_user": "neo4j",
        "neo4j_password": "secret",
    }
    values.update(overrides)
    return AssistantHttpConfig(**values)


class AssistantHttpConfigTests(unittest.TestCase):
    def test_from_env_reads_product_prefix(self):
        env = {
            "NEO4J_URI": "bolt://example",
            "NEO4J_USER": "neo4j",
            "NEO4J_PASSWORD": "secret",
            "DRAWING_GRAPH_ASSISTANT_HTTP_HOST": "127.0.0.1",
            "DRAWING_GRAPH_ASSISTANT_HTTP_PORT": "8123",
            "DRAWING_GRAPH_ASSISTANT_HTTP_API_TOKEN": "tok",
            "DRAWING_GRAPH_ASSISTANT_HTTP_MAX_REQUEST_BYTES": "1024",
            "DRAWING_GRAPH_ASSISTANT_HTTP_REQUEST_TIMEOUT_SECONDS": "15",
            "DRAWING_GRAPH_ASSISTANT_HTTP_MAX_CONCURRENT_REQUESTS": "4",
            "DRAWING_GRAPH_ASSISTANT_HTTP_DOCS_ENABLED": "true",
            "DRAWING_GRAPH_ASSISTANT_HTTP_LOG_LEVEL": "debug",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            config = AssistantHttpConfig.from_env()
        self.assertEqual("127.0.0.1", config.host)
        self.assertEqual(8123, config.port)
        self.assertEqual("tok", config.api_token)
        self.assertEqual(1024, config.max_request_bytes)
        self.assertEqual(15.0, config.request_timeout_seconds)
        self.assertEqual(4, config.max_concurrent_requests)
        self.assertTrue(config.docs_enabled)
        self.assertEqual("DEBUG", config.log_level)

    def test_defaults_are_loopback_read_only(self):
        env = {
            "NEO4J_URI": "bolt://example",
            "NEO4J_USER": "neo4j",
            "NEO4J_PASSWORD": "secret",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            config = AssistantHttpConfig.from_env()
        self.assertEqual("127.0.0.1", config.host)
        self.assertEqual(8001, config.port)
        self.assertFalse(config.allow_remote)
        self.assertFalse(config.docs_enabled)
        self.assertEqual("", config.api_token)

    def test_repr_masks_secrets(self):
        config = _config(api_token="tokvalue123")
        text = repr(config)
        self.assertNotIn("secret", text)
        self.assertNotIn("tokvalue123", text)

    def test_non_loopback_requires_remote_and_token(self):
        with self.assertRaises(ConfigError):
            _config(host="0.0.0.0", allow_remote=False)

    def test_docs_disallowed_on_remote(self):
        with self.assertRaises(ConfigError):
            _config(host="0.0.0.0", allow_remote=True, api_token="tok", docs_enabled=True)


class AssistantHttpRuntimeTests(unittest.TestCase):
    def test_runtime_assembles_with_fake_factories(self):
        from drawing_graph.assistant_http_runtime import create_assistant_http_runtime

        class FakeDriver:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        class FakeFacade:
            pass

        class FakeService:
            pass

        driver = FakeDriver()
        facade = FakeFacade()
        service = FakeService()
        runtime = create_assistant_http_runtime(
            _config(),
            driver_factory=lambda uri, auth: driver,
            facade_factory=lambda d: facade,
            service_factory=lambda f: service,
        )
        self.assertTrue(runtime.ready)
        self.assertIs(service, runtime.service)
        runtime.close()
        self.assertTrue(driver.closed)
        self.assertFalse(runtime.ready)

    def test_close_is_idempotent(self):
        from drawing_graph.assistant_http_runtime import create_assistant_http_runtime

        class FakeDriver:
            def __init__(self):
                self.closed = 0

            def close(self):
                self.closed += 1

        driver = FakeDriver()
        runtime = create_assistant_http_runtime(
            _config(),
            driver_factory=lambda uri, auth: driver,
            facade_factory=lambda d: object(),
            service_factory=lambda f: object(),
        )
        runtime.close()
        runtime.close()
        self.assertEqual(1, driver.closed)

    def test_init_failure_closes_driver(self):
        from drawing_graph.assistant_http_runtime import create_assistant_http_runtime

        class FakeDriver:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        driver = FakeDriver()

        def boom_facade(d):
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            create_assistant_http_runtime(
                _config(),
                driver_factory=lambda uri, auth: driver,
                facade_factory=boom_facade,
                service_factory=lambda f: object(),
            )
        self.assertTrue(driver.closed)


if __name__ == "__main__":
    unittest.main()
