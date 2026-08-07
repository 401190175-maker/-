import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.source_fact_query import SourceFactQuery
from drawing_graph.tool_models import ToolModelError


class FakePageReader:
    def read_page_source_facts(self, page_id):
        if page_id != "page:1":
            return None
        return {
            "page_id": "page:1",
            "image_path": "road_24.png",
            "image_width": 1000,
            "image_height": 2000,
            "elements": [
                {
                    "id": "block:1",
                    "element_type": "DrawingBlock",
                    "source_label": "block",
                    "bbox": {"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
                    "normalized_bbox": {"x_min": 0.1, "y_min": 0.2, "x_max": 0.3, "y_max": 0.4},
                },
                {
                    "id": "caption:1",
                    "element_type": "BlockCaption",
                    "source_label": "block caption",
                    "bbox": {"x_min": 5, "y_min": 6, "x_max": 7, "y_max": 8},
                    "normalized_bbox": {"x_min": 0.5, "y_min": 0.6, "x_max": 0.7, "y_max": 0.8},
                },
            ],
        }


class FakeRecord(dict):
    def __getitem__(self, key):
        return dict.__getitem__(self, key)


class FakeTransaction:
    def __init__(self, records):
        self.records = list(records)
        self.calls = []

    def run(self, cypher, **parameters):
        self.calls.append((cypher, parameters))
        return list(self.records)


class FakeSession:
    def __init__(self, records):
        self.transaction = FakeTransaction(records)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute_read(self, callback):
        return callback(self.transaction)


class FakeDriver:
    def __init__(self, records):
        self.records = list(records)
        self.sessions = []

    def session(self):
        session = FakeSession(self.records)
        self.sessions.append(session)
        return session


class SourceFactQueryTest(unittest.TestCase):
    def test_projects_single_page_source_facts(self):
        facts = SourceFactQuery(FakePageReader()).get_page_source_facts("page:1")

        self.assertEqual("road_24.png", facts.image_path)
        self.assertEqual((1000, 2000), facts.image_size)
        self.assertEqual(["DrawingBlock", "BlockCaption"], [item.element_type for item in facts.elements])

    def test_filters_element_types_and_can_hide_image_meta(self):
        facts = SourceFactQuery(FakePageReader()).get_page_source_facts(
            "page:1",
            element_types=("BlockCaption",),
            include_image_meta=False,
        )

        self.assertIsNone(facts.image_size)
        self.assertEqual(("caption:1",), tuple(item.element_id for item in facts.elements))

    def test_missing_page_returns_not_found_error(self):
        with self.assertRaises(ToolModelError) as error:
            SourceFactQuery(FakePageReader()).get_page_source_facts("page:missing")

        self.assertEqual("NOT_FOUND", error.exception.category)

    def test_neo4j_page_reader_projects_page_and_element_records(self):
        from drawing_graph.source_fact_query import Neo4jPageSourceFactReader

        driver = FakeDriver(
            (
                FakeRecord(
                    page_id="page:1",
                    image_path="road_24.png",
                    image_width=100,
                    image_height=200,
                    image_hash="hash:1",
                    elements=[
                        {
                            "id": "block:1",
                            "labels": ["DrawingBlock"],
                            "source_label": "block",
                            "bbox": [1, 2, 3, 4],
                            "normalized_bbox": [0.1, 0.2, 0.3, 0.4],
                        },
                        {
                            "id": "caption:1",
                            "labels": ["BlockCaption"],
                            "source_label": "block caption",
                            "bbox": {"x_min": 5, "y_min": 6, "x_max": 7, "y_max": 8},
                            "normalized_bbox": {"x_min": 0.5, "y_min": 0.6, "x_max": 0.7, "y_max": 0.8},
                        },
                    ],
                ),
            )
        )

        raw_page = Neo4jPageSourceFactReader(driver).read_page_source_facts("page:1")

        self.assertEqual("page:1", raw_page["page_id"])
        self.assertEqual("DrawingBlock", raw_page["elements"][0]["element_type"])
        self.assertEqual("BlockCaption", raw_page["elements"][1]["element_type"])
        self.assertEqual({"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4}, raw_page["elements"][0]["bbox"])
        cypher, parameters = driver.sessions[0].transaction.calls[0]
        self.assertIn("HAS_BLOCK|HAS_TABLE|HAS_ELEMENT|HAS_BASIC_INFO|HAS_ANNOTATION|HAS_TEXT", cypher)
        self.assertNotIn("page:1", cypher)
        self.assertEqual({"page_id": "page:1"}, parameters)


if __name__ == "__main__":
    unittest.main()
