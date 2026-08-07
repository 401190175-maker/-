import importlib
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
from drawing_graph.source_fact_query import Neo4jPageSourceFactReader, SourceFactQuery
from drawing_graph.tool_factory import create_neo4j_tool_facade, create_tool_facade


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

    def test_factory_creates_facade_without_connecting_at_import_time(self):
        module = importlib.import_module("drawing_graph.tool_factory")
        self.assertFalse(hasattr(module, "driver"))

        facade = create_tool_facade(read_port=FakeReadPort(), config=ToolFacadeConfig.from_mapping({}))

        self.assertEqual([], facade.list_drawing_sets("project:1"))
        self.assertFalse(FakeReadPort.connected)
        self.assertIsNotNone(facade.payload_store)
        self.assertIsNotNone(facade.semantic_service.input_builder)
        self.assertIsNotNone(facade.semantic_service.cache_service)

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


if __name__ == "__main__":
    unittest.main()
