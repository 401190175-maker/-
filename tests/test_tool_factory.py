import importlib
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.config import ToolFacadeConfig
from drawing_graph.relation_repository import (
    RelationRepositoryCandidateRelationPort,
    RelationRepositorySectionMatchPort,
    RelationRepositorySectionMatchQueryPort,
)
from drawing_graph.semantic_neo4j_repository import SemanticNeo4jRepository
from drawing_graph.semantic_client import FakeMultimodalRecognitionClient
from drawing_graph.source_fact_query import Neo4jPageSourceFactReader, SourceFactQuery
from drawing_graph.tool_factory import create_neo4j_tool_facade, create_tool_facade
from drawing_graph.qwen_semantic_client import QwenMultimodalRecognitionClient


class FakeReadPort:
    connected = False

    def list_drawing_sets(self, project_id, limit=100):
        return []


class ToolFactoryTest(unittest.TestCase):
    def test_config_defaults_and_rejects_sensitive_tool_fields(self):
        config = ToolFacadeConfig.from_mapping({})

        self.assertFalse(config.default_write_back)
        self.assertEqual("default", config.model_profile)
        self.assertEqual("in_memory", config.run_log_store)
        self.assertEqual("in_memory", config.payload_store)
        self.assertEqual("in_memory", config.semantic_repository)
        self.assertEqual("section-match-v1", config.section_match_rule_version)
        self.assertEqual("fake", config.recognition_provider)
        self.assertEqual("qwen3-vl-plus", config.qwen_model)
        with self.assertRaises(ValueError):
            ToolFacadeConfig.from_mapping({"neo4j_password": "secret"})

    def test_config_accepts_controlled_store_types_and_rejects_unknown_ones(self):
        config = ToolFacadeConfig.from_mapping(
            {
                "run_log_store": "in_memory",
                "payload_store": "in_memory",
                "semantic_repository": "in_memory",
                "cache_store": "in_memory",
                "section_match_rule_version": "match-v2",
            }
        )

        self.assertEqual("in_memory", config.semantic_repository)
        self.assertEqual("match-v2", config.section_match_rule_version)
        with self.assertRaises(ValueError):
            ToolFacadeConfig.from_mapping({"semantic_repository": "neo4j"})
        with self.assertRaises(ValueError):
            ToolFacadeConfig.from_mapping({"payload_store": "file"})

    def test_config_accepts_qwen_provider_non_secret_settings(self):
        config = ToolFacadeConfig.from_mapping(
            {
                "recognition_provider": "qwen",
                "qwen_model": "qwen3-vl-plus",
                "qwen_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "qwen_timeout_seconds": 45,
            }
        )

        self.assertEqual("qwen", config.recognition_provider)
        self.assertEqual("qwen3-vl-plus", config.qwen_model)
        self.assertEqual(45.0, config.qwen_timeout_seconds)
        with self.assertRaises(ValueError):
            ToolFacadeConfig.from_mapping({"recognition_provider": "unknown"})

    def test_config_from_env_reads_qwen_provider_non_secret_settings(self):
        previous = {
            name: os.environ.get(name)
            for name in (
                "DRAWING_GRAPH_RECOGNITION_PROVIDER",
                "DRAWING_GRAPH_QWEN_MODEL",
                "DRAWING_GRAPH_QWEN_BASE_URL",
                "DRAWING_GRAPH_QWEN_TIMEOUT_SECONDS",
            )
        }
        os.environ["DRAWING_GRAPH_RECOGNITION_PROVIDER"] = "qwen"
        os.environ["DRAWING_GRAPH_QWEN_MODEL"] = "qwen3-vl-plus"
        os.environ["DRAWING_GRAPH_QWEN_BASE_URL"] = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        os.environ["DRAWING_GRAPH_QWEN_TIMEOUT_SECONDS"] = "30"
        try:
            config = ToolFacadeConfig.from_env()
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

        self.assertEqual("qwen", config.recognition_provider)
        self.assertEqual("qwen3-vl-plus", config.qwen_model)
        self.assertEqual(30.0, config.qwen_timeout_seconds)

    def test_factory_creates_facade_without_connecting_at_import_time(self):
        module = importlib.import_module("drawing_graph.tool_factory")
        self.assertFalse(hasattr(module, "driver"))

        facade = create_tool_facade(read_port=FakeReadPort(), config=ToolFacadeConfig.from_mapping({}))

        self.assertEqual([], facade.list_drawing_sets("project:1"))
        self.assertFalse(FakeReadPort.connected)
        self.assertIsNotNone(facade.payload_store)
        self.assertIsNotNone(facade.semantic_service.input_builder)
        self.assertIsNotNone(facade.semantic_service.cache_service)
        self.assertIsInstance(facade.semantic_service.client, FakeMultimodalRecognitionClient)

    def test_neo4j_factory_wires_real_ports_without_connecting_at_creation(self):
        driver = object()

        facade = create_neo4j_tool_facade(driver)

        self.assertIsInstance(facade.semantic_repository, SemanticNeo4jRepository)
        self.assertIs(facade.semantic_repository.driver, driver)
        self.assertIsInstance(facade.read_port.source_fact_reader, SourceFactQuery)
        self.assertIsInstance(facade.read_port.source_fact_reader.page_reader, Neo4jPageSourceFactReader)
        self.assertIs(facade.read_port.source_fact_reader.page_reader.driver, driver)
        self.assertIsInstance(facade.section_match_write_port, RelationRepositorySectionMatchPort)
        self.assertIsInstance(facade.candidate_relation_port, RelationRepositoryCandidateRelationPort)
        self.assertIsInstance(facade.section_match_query_port, RelationRepositorySectionMatchQueryPort)
        self.assertIsNotNone(facade.candidate_review_service)
        self.assertIs(facade.candidate_review_service.repository.driver, driver)
        self.assertIs(facade.candidate_relation_port.repository.driver, driver)
        self.assertIs(facade.section_match_query_port.repository.driver, driver)
        self.assertIsNotNone(facade.payload_store)
        self.assertIsNotNone(facade.semantic_service)
        self.assertIsInstance(facade.semantic_service.client, FakeMultimodalRecognitionClient)

    def test_neo4j_factory_wires_qwen_client_when_configured_with_dashscope_key(self):
        previous = os.environ.get("DASHSCOPE_API_KEY")
        os.environ["DASHSCOPE_API_KEY"] = "test-key"
        try:
            facade = create_neo4j_tool_facade(
                object(),
                config=ToolFacadeConfig.from_mapping({"recognition_provider": "qwen"}),
            )
        finally:
            if previous is None:
                os.environ.pop("DASHSCOPE_API_KEY", None)
            else:
                os.environ["DASHSCOPE_API_KEY"] = previous

        self.assertIsInstance(facade.semantic_service.client, QwenMultimodalRecognitionClient)

    def test_neo4j_factory_reads_recognition_provider_from_env_by_default(self):
        previous = {
            name: os.environ.get(name)
            for name in ("DASHSCOPE_API_KEY", "DRAWING_GRAPH_RECOGNITION_PROVIDER")
        }
        os.environ["DASHSCOPE_API_KEY"] = "test-key"
        os.environ["DRAWING_GRAPH_RECOGNITION_PROVIDER"] = "qwen"
        try:
            facade = create_neo4j_tool_facade(object())
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

        self.assertIsInstance(facade.semantic_service.client, QwenMultimodalRecognitionClient)


if __name__ == "__main__":
    unittest.main()
