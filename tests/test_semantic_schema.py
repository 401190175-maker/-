import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.semantic_schema import (
    INTERPRETATION_SOURCE_LABELS,
    OBSERVATION_SOURCE_LABELS,
    SEMANTIC_INDEXES,
    SEMANTIC_NODE_LABELS,
    SEMANTIC_RELATION_TYPES,
    SEMANTIC_UNIQUE_CONSTRAINTS,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SemanticSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema_text = (PROJECT_ROOT / "scripts" / "create_schema.cypher").read_text(encoding="utf-8")

    def test_static_spec_defines_semantic_nodes_and_relations(self):
        self.assertEqual(
            {"TextObservation", "BlockInterpretation", "BasicInfoInterpretation", "TableInterpretation"},
            set(SEMANTIC_NODE_LABELS),
        )
        self.assertEqual(
            {
                "HAS_OBSERVATION",
                "HAS_INTERPRETATION",
                "SUPPORTED_BY",
                "CANDIDATE_MATCHES_SECTION_CAPTION",
                "MATCHES_SECTION_CAPTION",
            },
            set(SEMANTIC_RELATION_TYPES),
        )
        self.assertIn("DrawingBlock", OBSERVATION_SOURCE_LABELS)
        self.assertIn("BlockCaption", OBSERVATION_SOURCE_LABELS)
        self.assertIn("CrossSection", OBSERVATION_SOURCE_LABELS)
        self.assertEqual({"DrawingBlock", "DrawingBasicInfo", "Table"}, set(INTERPRETATION_SOURCE_LABELS))

    def test_schema_script_creates_semantic_unique_constraints_idempotently(self):
        for constraint_name, label in SEMANTIC_UNIQUE_CONSTRAINTS:
            with self.subTest(label=label):
                self.assertIn(f"CREATE CONSTRAINT {constraint_name}", self.schema_text)
                self.assertRegex(
                    self.schema_text,
                    rf"CREATE\s+CONSTRAINT\s+{constraint_name}[\s\S]*?IF\s+NOT\s+EXISTS[\s\S]*?"
                    rf"FOR\s+\(\w+:{label}\)[\s\S]*?REQUIRE\s+\w+\.id\s+IS\s+UNIQUE",
                )

    def test_schema_script_creates_semantic_indexes_idempotently(self):
        for index_name, label, property_name in SEMANTIC_INDEXES:
            with self.subTest(label=label, property_name=property_name):
                self.assertRegex(
                    self.schema_text,
                    rf"CREATE\s+INDEX\s+{index_name}[\s\S]*?IF\s+NOT\s+EXISTS[\s\S]*?"
                    rf"FOR\s+\(\w+:{label}\)[\s\S]*?ON\s+\(\w+\.{property_name}\)",
                )

    def test_schema_never_creates_recognition_run_graph_node(self):
        self.assertNotIn("RecognitionRun", self.schema_text)

    def test_every_semantic_create_statement_is_idempotent(self):
        semantic_section = self.schema_text.split("Semantic Evidence Layer")[-1]
        statements = [
            statement.strip()
            for statement in semantic_section.split(";")
            if statement.strip().upper().startswith("CREATE ")
        ]
        self.assertGreater(len(statements), 0)
        for statement in statements:
            with self.subTest(statement=statement.splitlines()[0]):
                self.assertRegex(statement, re.compile(r"\bIF\s+NOT\s+EXISTS\b", re.I))


if __name__ == "__main__":
    unittest.main()
