import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.query_ports import FakeDrawingGraphReadPort
from drawing_graph.tool_facade import DrawingGraphToolFacade
from drawing_graph.tool_models import BBox, BlockRelations, BlockTrace, DrawingSetSummary, PageSummary, ToolModelError


class ExplodingPort(FakeDrawingGraphReadPort):
    def list_drawing_sets(self, project_id, limit=100):
        raise RuntimeError("driver stack with MATCH secret")


class ToolFacadeReadOnlyTest(unittest.TestCase):
    def test_read_only_facade_delegates_to_port_without_internal_dicts(self):
        port = FakeDrawingGraphReadPort(
            drawing_sets=(DrawingSetSummary("project:1", "set:1", "set", 1),),
            pages=(PageSummary("set:1", "page:1", "road_24", 24),),
            block_traces={
                "block:1": BlockTrace(
                    block_id="block:1",
                    project_id="project:1",
                    drawing_set_id="set:1",
                    page_id="page:1",
                    bbox=BBox(1, 2, 3, 4),
                    normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
                )
            },
            block_relations={"block:1": BlockRelations(block_id="block:1", caption_ids=("caption:1",))},
        )
        facade = DrawingGraphToolFacade(read_port=port)

        self.assertEqual("set:1", facade.list_drawing_sets("project:1")[0].drawing_set_id)
        self.assertEqual("page:1", facade.list_pages("set:1")[0].page_id)
        self.assertEqual("block:1", facade.get_block_trace("block:1").block_id)
        self.assertEqual(("caption:1",), facade.get_block_relations("block:1").caption_ids)
        self.assertNotIn("dict", repr(facade.list_drawing_sets("project:1")[0]).lower())

    def test_read_only_methods_reject_write_back_intent(self):
        facade = DrawingGraphToolFacade(read_port=FakeDrawingGraphReadPort())

        with self.assertRaises(ToolModelError) as error:
            facade.list_drawing_sets("project:1", write_back=True)

        self.assertEqual("WRITE_BACK_FORBIDDEN", error.exception.category)

    def test_low_level_errors_are_sanitized(self):
        facade = DrawingGraphToolFacade(read_port=ExplodingPort())

        with self.assertRaises(ToolModelError) as error:
            facade.list_drawing_sets("project:1")

        self.assertEqual("NEO4J_UNAVAILABLE", error.exception.category)
        self.assertNotIn("MATCH", str(error.exception))


if __name__ == "__main__":
    unittest.main()
