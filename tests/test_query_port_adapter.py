import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.query_port_adapter import QueryServiceReadPortAdapter
from drawing_graph.query_service import QueryError
from drawing_graph.tool_models import ToolModelError


class FakeQueryService:
    def get_project_sets(self, project_id, limit=100):
        return [{"id": "set:1", "name": "set", "page_count": 2, "neo4j_label": "DrawingSet"}]

    def get_set_pages(self, drawing_set_id, limit=100):
        return [{"id": "page:1", "file_name": "road_24.json", "page_number": 24, "image_path": "road_24.png"}]

    def get_block_trace(self, block_id):
        return {
            "project_id": "project:1",
            "drawing_set_id": "set:1",
            "page_id": "page:1",
            "page_number": 24,
            "image_path": "road_24.png",
            "bbox": {"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
            "normalized_bbox": {"x_min": 0.1, "y_min": 0.2, "x_max": 0.3, "y_max": 0.4},
            "citation_ref": "road_24#0",
            "driver": object(),
        }

    def get_block_relations(self, block_id):
        return {
            "block_id": block_id,
            "caption_ids": ["caption:1"],
            "basic_info_ids": [],
            "annotation_ids": [],
            "section_mark_ids": [],
            "candidate_caption_ids": ["caption:2"],
            "candidate_section_mark_ids": [],
            "relation_status": "candidate",
            "basic_info_status": "not_evaluated",
            "basic_info_source": None,
        }


class FailingQueryService(FakeQueryService):
    def get_project_sets(self, project_id, limit=100):
        raise QueryError("invalid_limit", "MATCH secret RETURN n")


class QueryPortAdapterTest(unittest.TestCase):
    def test_projects_pages_trace_and_relations_are_projected_to_tool_dtos(self):
        adapter = QueryServiceReadPortAdapter(FakeQueryService())

        drawing_set = adapter.list_drawing_sets("project:1")[0]
        page = adapter.list_pages("set:1")[0]
        trace = adapter.get_block_trace("block:1")
        relations = adapter.get_block_relations("block:1")

        self.assertEqual("set:1", drawing_set.drawing_set_id)
        self.assertEqual("road_24", page.file_stem)
        self.assertEqual("page:1", trace.page_id)
        self.assertEqual(("caption:2",), relations.candidate_caption_ids)
        self.assertNotIn("neo4j_label", repr(drawing_set))
        self.assertNotIn("driver", repr(trace))

    def test_query_errors_become_tool_model_errors_without_query_text(self):
        adapter = QueryServiceReadPortAdapter(FailingQueryService())

        with self.assertRaises(ToolModelError) as error:
            adapter.list_drawing_sets("project:1")

        self.assertEqual("invalid_limit", error.exception.category)
        self.assertNotIn("MATCH", str(error.exception))


if __name__ == "__main__":
    unittest.main()
