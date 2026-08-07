import re
import unittest
from pathlib import Path


class SchemaStaticTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema_text = (
            Path(__file__).resolve().parents[1] / "scripts" / "create_schema.cypher"
        ).read_text(encoding="utf-8")

    def test_required_unique_constraints_exist(self):
        required_labels = [
            "Project",
            "DrawingSet",
            "DrawingPage",
            "DrawingBlock",
            "Table",
            "BlockCaption",
            "TableCaption",
            "CrossSection",
            "DrawingBasicInfo",
            "DrawingAnnotation",
            "PlainText",
            "Title",
            "IgnoredElement",
            "ImportBatch",
        ]

        for label in required_labels:
            with self.subTest(label=label):
                self.assertRegex(
                    self.schema_text,
                    rf"CREATE\s+CONSTRAINT\s+\w+[\s\S]*?IF\s+NOT\s+EXISTS[\s\S]*?"
                    rf"FOR\s+\(\w+:{label}\)[\s\S]*?REQUIRE\s+\w+\.id\s+IS\s+UNIQUE",
                )

    def test_required_indexes_exist(self):
        required_indexes = [
            ("DrawingPage", "page_number"),
            ("DrawingPage", "file_name"),
            ("DrawingSet", "name"),
            ("ImportBatch", "status"),
            ("ImportBatch", "started_at"),
        ]

        for label, property_name in required_indexes:
            with self.subTest(label=label, property_name=property_name):
                self.assertRegex(
                    self.schema_text,
                    rf"CREATE\s+INDEX\s+\w+[\s\S]*?IF\s+NOT\s+EXISTS[\s\S]*?"
                    rf"FOR\s+\(\w+:{label}\)[\s\S]*?ON\s+\(\w+\.{property_name}\)",
                )

    def test_schema_does_not_use_legacy_block_label_or_block_type_index(self):
        self.assertNotRegex(self.schema_text, r":Block\b")
        self.assertNotIn("block_type", self.schema_text)

    def test_every_create_statement_is_idempotent(self):
        statements = [
            statement.strip()
            for statement in self.schema_text.split(";")
            if statement.strip().upper().startswith("CREATE ")
        ]

        self.assertGreater(len(statements), 0)
        for statement in statements:
            with self.subTest(statement=statement.splitlines()[0]):
                self.assertRegex(statement, re.compile(r"\bIF\s+NOT\s+EXISTS\b", re.I))


if __name__ == "__main__":
    unittest.main()
