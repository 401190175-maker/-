import dataclasses
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class ModelsTest(unittest.TestCase):
    def test_bbox_serializes_to_design_field_names(self):
        from drawing_graph.models import BBox

        bbox = BBox(x_min=10, y_min=20, x_max=110, y_max=120)

        self.assertEqual(
            {"x_min": 10.0, "y_min": 20.0, "x_max": 110.0, "y_max": 120.0},
            bbox.to_dict(),
        )

    def test_normalized_bbox_rejects_values_outside_zero_to_one(self):
        from drawing_graph.models import ModelError, NormalizedBBox

        with self.assertRaises(ModelError) as context:
            NormalizedBBox(x_min=0, y_min=0, x_max=1.2, y_max=1)

        self.assertEqual("invalid_normalized_bbox", context.exception.category)

    def test_bbox_rejects_non_positive_area(self):
        from drawing_graph.models import BBox, ModelError

        with self.assertRaises(ModelError) as context:
            BBox(x_min=10, y_min=20, x_max=10, y_max=30)

        self.assertEqual("invalid_bbox", context.exception.category)

    def test_page_record_requires_design_fields_without_import_batch_id(self):
        from drawing_graph.models import PageRecord

        page = PageRecord(
            id="page:road-project:set-a:road_24",
            page_number=24,
            file_name="road_24.json",
            json_path="data/set-a/road_24.json",
            image_path="data/set-a/road_24.png",
            original_image_path="../images/road_24.png",
            image_width=1000,
            image_height=800,
        )

        self.assertFalse(hasattr(page, "import_batch_id"))
        self.assertEqual(24, page.page_number)
        self.assertEqual("data/set-a/road_24.png", page.image_path)

    def test_page_record_rejects_invalid_image_size(self):
        from drawing_graph.models import ModelError, PageRecord

        with self.assertRaises(ModelError) as context:
            PageRecord(
                id="page:road-project:set-a:road_24",
                page_number=24,
                file_name="road_24.json",
                json_path="data/set-a/road_24.json",
                image_path="data/set-a/road_24.png",
                original_image_path="../images/road_24.png",
                image_width=0,
                image_height=800,
            )

        self.assertEqual("invalid_image_size", context.exception.category)

    def test_element_record_contains_source_geometry_without_block_type(self):
        from drawing_graph.models import BBox, ElementRecord, NormalizedBBox

        element = ElementRecord(
            id="block:road-project:set-a:road_24:abc123",
            page_id="page:road-project:set-a:road_24",
            label="block",
            confidence=0.95,
            shape_type="rectangle",
            bbox=BBox(x_min=10, y_min=20, x_max=110, y_max=120),
            normalized_bbox=NormalizedBBox(x_min=0.01, y_min=0.025, x_max=0.11, y_max=0.15),
            source_label="block",
            original_points=((10.0, 20.0), (110.0, 120.0)),
            citation_ref="set-a/road_24#block:abc123",
        )

        self.assertFalse(hasattr(element, "block_type"))
        self.assertEqual("block", element.label)
        self.assertEqual(
            {"x_min": 10.0, "y_min": 20.0, "x_max": 110.0, "y_max": 120.0},
            element.bbox.to_dict(),
        )

    def test_element_record_rejects_confidence_outside_zero_to_one(self):
        from drawing_graph.models import BBox, ElementRecord, ModelError, NormalizedBBox

        with self.assertRaises(ModelError) as context:
            ElementRecord(
                id="block:road-project:set-a:road_24:abc123",
                page_id="page:road-project:set-a:road_24",
                label="block",
                confidence=1.5,
                shape_type="rectangle",
                bbox=BBox(x_min=10, y_min=20, x_max=110, y_max=120),
                normalized_bbox=NormalizedBBox(x_min=0.01, y_min=0.025, x_max=0.11, y_max=0.15),
                source_label="block",
                original_points=((10.0, 20.0), (110.0, 120.0)),
                citation_ref="set-a/road_24#block:abc123",
            )

        self.assertEqual("invalid_confidence", context.exception.category)

    def test_graph_node_and_relation_are_immutable_fixed_structures(self):
        from drawing_graph.models import GraphNode, GraphRelation

        node = GraphNode(id="page:road-project:set-a:road_24", labels=("DrawingPage",), properties={"page_number": 24})
        relation = GraphRelation(
            start_id="set:road-project:set-a",
            end_id=node.id,
            relation_type="HAS_PAGE",
            properties={},
        )

        with self.assertRaises(dataclasses.FrozenInstanceError):
            node.id = "changed"

        self.assertEqual(("DrawingPage",), node.labels)
        self.assertEqual("HAS_PAGE", relation.relation_type)

    def test_import_result_accepts_only_terminal_or_running_statuses(self):
        from drawing_graph.models import ImportResult, ModelError

        result = ImportResult(
            status="success",
            page_id="page:road-project:set-a:road_24",
            warnings=("coordinate_out_of_bounds",),
            errors=(),
        )

        self.assertEqual("success", result.status)
        with self.assertRaises(ModelError) as context:
            ImportResult(status="done", page_id=None, warnings=(), errors=())

        self.assertEqual("invalid_import_status", context.exception.category)


if __name__ == "__main__":
    unittest.main()
