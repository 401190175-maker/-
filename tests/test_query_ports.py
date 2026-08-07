import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.query_ports import FakeDrawingGraphReadPort
from drawing_graph.tool_models import BBox, DrawingSetSummary, ElementEvidence, PageSourceFacts, PageSummary


class QueryPortsTest(unittest.TestCase):
    def test_fake_read_port_supports_minimal_read_contract(self):
        facts = PageSourceFacts(
            page_id="page:1",
            image_path="road_24.png",
            elements=(
                ElementEvidence(
                    element_id="block:1",
                    element_type="DrawingBlock",
                    bbox=BBox(1, 2, 3, 4),
                    normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
                    source_label="block",
                ),
            ),
        )
        port = FakeDrawingGraphReadPort(
            drawing_sets=(DrawingSetSummary("project:1", "set:1", "set", 1),),
            pages=(PageSummary("set:1", "page:1", "road_24", 24, "road_24.png"),),
            source_facts={"page:1": facts},
        )

        self.assertEqual("set:1", port.list_drawing_sets("project:1")[0].drawing_set_id)
        self.assertEqual("page:1", port.list_pages("set:1")[0].page_id)
        self.assertEqual("block:1", port.get_page_source_facts("page:1").elements[0].element_id)
        self.assertEqual(None, port.get_block_trace("missing"))
        self.assertEqual(None, port.get_block_relations("missing"))
        self.assertEqual([], port.calls_with_internal_dependencies)

    def test_fake_port_applies_business_filters_without_neo4j(self):
        port = FakeDrawingGraphReadPort(
            drawing_sets=(
                DrawingSetSummary("project:1", "set:1", "set 1", 1),
                DrawingSetSummary("project:2", "set:2", "set 2", 1),
            ),
            pages=(
                PageSummary("set:1", "page:1", "road_24", 24),
                PageSummary("set:2", "page:2", "road_25", 25),
            ),
        )

        self.assertEqual(["set:1"], [item.drawing_set_id for item in port.list_drawing_sets("project:1")])
        self.assertEqual(["page:2"], [item.page_id for item in port.list_pages("set:2")])


if __name__ == "__main__":
    unittest.main()
