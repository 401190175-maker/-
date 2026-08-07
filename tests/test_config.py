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


if __name__ == "__main__":
    unittest.main()
