import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class ImportConfigTest(unittest.TestCase):
    def setUp(self):
        self.required_env = {
            "DRAWING_GRAPH_DATA_ROOT": str(PROJECT_ROOT / "data"),
            "DRAWING_GRAPH_PROJECT_SLUG": "road-demo",
            "NEO4J_URI": "bolt://localhost:7687",
            "NEO4J_USER": "neo4j",
            "NEO4J_PASSWORD": "super-secret",
        }

    def test_from_env_returns_immutable_complete_config(self):
        from drawing_graph.config import ImportConfig

        env = {
            **self.required_env,
            "DRAWING_GRAPH_BATCH_SIZE": "250",
            "DRAWING_GRAPH_LOG_LEVEL": "debug",
        }

        with patch.dict(os.environ, env, clear=True):
            config = ImportConfig.from_env()

        self.assertEqual(PROJECT_ROOT / "data", config.data_root)
        self.assertEqual("road-demo", config.project_slug)
        self.assertEqual("bolt://localhost:7687", config.neo4j_uri)
        self.assertEqual("neo4j", config.neo4j_user)
        self.assertEqual("super-secret", config.neo4j_password)
        self.assertEqual(250, config.batch_size)
        self.assertEqual("DEBUG", config.log_level)

        with self.assertRaises(AttributeError):
            config.batch_size = 1

    def test_missing_required_credential_reports_variable_name(self):
        from drawing_graph.config import ConfigError, ImportConfig

        env = dict(self.required_env)
        del env["NEO4J_PASSWORD"]

        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ConfigError) as context:
                ImportConfig.from_env()

        self.assertIn("NEO4J_PASSWORD", str(context.exception))

    def test_invalid_batch_size_is_rejected(self):
        from drawing_graph.config import ConfigError, ImportConfig

        env = {**self.required_env, "DRAWING_GRAPH_BATCH_SIZE": "0"}

        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ConfigError) as context:
                ImportConfig.from_env()

        self.assertIn("DRAWING_GRAPH_BATCH_SIZE", str(context.exception))

    def test_password_is_not_exposed_in_string_representations(self):
        from drawing_graph.config import ImportConfig

        with patch.dict(os.environ, self.required_env, clear=True):
            config = ImportConfig.from_env()

        self.assertNotIn("super-secret", str(config))
        self.assertNotIn("super-secret", repr(config))
        self.assertIn("********", repr(config))


class QAHttpConfigTests(unittest.TestCase):
    """QAHttpConfig must enforce safe HTTP defaults and remote-binding rules."""

    def setUp(self):
        self.required_env = {
            "NEO4J_URI": "bolt://localhost:7687",
            "NEO4J_USER": "neo4j",
            "NEO4J_PASSWORD": "http-super-secret",
        }

    def test_defaults_from_env(self):
        from drawing_graph.config import QAHttpConfig

        with patch.dict(os.environ, self.required_env, clear=True):
            config = QAHttpConfig.from_env()

        self.assertEqual("127.0.0.1", config.host)
        self.assertEqual(8000, config.port)
        self.assertFalse(config.allow_remote)
        self.assertEqual((), config.allowed_origins)
        self.assertEqual("", config.api_token)
        self.assertEqual(65536, config.max_request_bytes)
        self.assertEqual(30.0, config.request_timeout_seconds)
        self.assertEqual(8, config.max_concurrent_requests)
        self.assertFalse(config.docs_enabled)
        self.assertEqual("INFO", config.log_level)

    def test_full_custom_environment_is_parsed(self):
        from drawing_graph.config import QAHttpConfig

        env = {
            **self.required_env,
            "DRAWING_GRAPH_QA_HTTP_HOST": "localhost",
            "DRAWING_GRAPH_QA_HTTP_PORT": "9000",
            "DRAWING_GRAPH_QA_HTTP_ALLOWED_ORIGINS": "https://app.example.com, http://localhost:5173",
            "DRAWING_GRAPH_QA_HTTP_MAX_REQUEST_BYTES": "1024",
            "DRAWING_GRAPH_QA_HTTP_REQUEST_TIMEOUT_SECONDS": "12.5",
            "DRAWING_GRAPH_QA_HTTP_MAX_CONCURRENT_REQUESTS": "2",
            "DRAWING_GRAPH_QA_HTTP_LOG_LEVEL": "debug",
        }

        with patch.dict(os.environ, env, clear=True):
            config = QAHttpConfig.from_env()

        self.assertEqual("localhost", config.host)
        self.assertEqual(9000, config.port)
        self.assertEqual(
            ("https://app.example.com", "http://localhost:5173"),
            config.allowed_origins,
        )
        self.assertEqual(1024, config.max_request_bytes)
        self.assertEqual(12.5, config.request_timeout_seconds)
        self.assertEqual(2, config.max_concurrent_requests)
        self.assertEqual("DEBUG", config.log_level)

    def test_remote_host_without_allow_remote_is_rejected(self):
        from drawing_graph.config import ConfigError, QAHttpConfig

        env = {**self.required_env, "DRAWING_GRAPH_QA_HTTP_HOST": "0.0.0.0"}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ConfigError):
                QAHttpConfig.from_env()

    def test_remote_host_requires_api_token(self):
        from drawing_graph.config import ConfigError, QAHttpConfig

        env = {
            **self.required_env,
            "DRAWING_GRAPH_QA_HTTP_HOST": "0.0.0.0",
            "DRAWING_GRAPH_QA_HTTP_ALLOW_REMOTE": "true",
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ConfigError):
                QAHttpConfig.from_env()

    def test_remote_host_with_token_is_allowed(self):
        from drawing_graph.config import QAHttpConfig

        env = {
            **self.required_env,
            "DRAWING_GRAPH_QA_HTTP_HOST": "0.0.0.0",
            "DRAWING_GRAPH_QA_HTTP_ALLOW_REMOTE": "true",
            "DRAWING_GRAPH_QA_HTTP_API_TOKEN": "remote-token-123",
        }
        with patch.dict(os.environ, env, clear=True):
            config = QAHttpConfig.from_env()

        self.assertTrue(config.allow_remote)
        self.assertEqual("remote-token-123", config.api_token)

    def test_docs_enabled_is_rejected_for_remote_host(self):
        from drawing_graph.config import ConfigError, QAHttpConfig

        env = {
            **self.required_env,
            "DRAWING_GRAPH_QA_HTTP_HOST": "0.0.0.0",
            "DRAWING_GRAPH_QA_HTTP_ALLOW_REMOTE": "true",
            "DRAWING_GRAPH_QA_HTTP_API_TOKEN": "remote-token-123",
            "DRAWING_GRAPH_QA_HTTP_DOCS_ENABLED": "true",
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ConfigError):
                QAHttpConfig.from_env()

    def test_wildcard_or_invalid_origin_is_rejected(self):
        from drawing_graph.config import ConfigError, QAHttpConfig

        for origins in ("*", "https://ok.example.com,*", "ftp://bad.example.com"):
            env = {
                **self.required_env,
                "DRAWING_GRAPH_QA_HTTP_ALLOWED_ORIGINS": origins,
            }
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaises(ConfigError):
                    QAHttpConfig.from_env()

    def test_port_bounds_are_enforced(self):
        from drawing_graph.config import ConfigError, QAHttpConfig

        for port in ("0", "70000", "-1"):
            env = {**self.required_env, "DRAWING_GRAPH_QA_HTTP_PORT": port}
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaises(ConfigError):
                    QAHttpConfig.from_env()

        env = {**self.required_env, "DRAWING_GRAPH_QA_HTTP_PORT": "65535"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(65535, QAHttpConfig.from_env().port)

    def test_positive_limits_are_enforced(self):
        from drawing_graph.config import ConfigError, QAHttpConfig

        cases = {
            "DRAWING_GRAPH_QA_HTTP_MAX_REQUEST_BYTES": "0",
            "DRAWING_GRAPH_QA_HTTP_REQUEST_TIMEOUT_SECONDS": "0",
            "DRAWING_GRAPH_QA_HTTP_MAX_CONCURRENT_REQUESTS": "0",
        }
        for name, value in cases.items():
            env = {**self.required_env, name: value}
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaises(ConfigError):
                    QAHttpConfig.from_env()

    def test_boolean_environment_values_are_parsed_explicitly(self):
        from drawing_graph.config import ConfigError, QAHttpConfig

        env = {
            **self.required_env,
            "DRAWING_GRAPH_QA_HTTP_ALLOW_REMOTE": "1",
            "DRAWING_GRAPH_QA_HTTP_DOCS_ENABLED": "yes",
        }
        with patch.dict(os.environ, env, clear=True):
            config = QAHttpConfig.from_env()
        self.assertTrue(config.allow_remote)
        self.assertTrue(config.docs_enabled)

        bad_env = {**self.required_env, "DRAWING_GRAPH_QA_HTTP_ALLOW_REMOTE": "maybe"}
        with patch.dict(os.environ, bad_env, clear=True):
            with self.assertRaises(ConfigError):
                QAHttpConfig.from_env()

    def test_password_and_token_are_hidden_in_repr(self):
        from drawing_graph.config import QAHttpConfig

        env = {
            **self.required_env,
            "DRAWING_GRAPH_QA_HTTP_API_TOKEN": "hidden-token-456",
        }
        with patch.dict(os.environ, env, clear=True):
            config = QAHttpConfig.from_env()

        representation = repr(config)
        self.assertNotIn("http-super-secret", representation)
        self.assertNotIn("hidden-token-456", representation)
        self.assertIn("********", representation)

    def test_config_is_frozen(self):
        from drawing_graph.config import QAHttpConfig

        with patch.dict(os.environ, self.required_env, clear=True):
            config = QAHttpConfig.from_env()
        with self.assertRaises(Exception):
            config.port = 9999


if __name__ == "__main__":
    unittest.main()
