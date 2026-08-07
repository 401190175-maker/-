import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class IdentifiersTest(unittest.TestCase):
    def test_project_set_page_and_element_ids_follow_design_format(self):
        from drawing_graph.identifiers import (
            make_element_id,
            make_page_id,
            make_project_id,
            make_set_id,
        )

        shape_hash = "abc123"

        self.assertEqual("project:road-project", make_project_id("road-project"))
        self.assertEqual("set:road-project:set-a", make_set_id("road-project", "set-a"))
        self.assertEqual("page:road-project:set-a:road_24", make_page_id("road-project", "set-a", "road_24"))
        self.assertEqual(
            "block:road-project:set-a:road_24:abc123",
            make_element_id("block", "road-project", "set-a", "road_24", shape_hash),
        )
        self.assertEqual(
            "element:road-project:set-a:road_24:abc123",
            make_element_id("element", "road-project", "set-a", "road_24", shape_hash),
        )

    def test_shape_hash_is_stable_when_dictionary_keys_are_reordered(self):
        from drawing_graph.identifiers import make_shape_hash

        first_shape = {
            "label": "block",
            "shape_type": "rectangle",
            "points": [[10, 20], [30, 40]],
        }
        reordered_shape = {
            "points": [[10, 20], [30, 40]],
            "shape_type": "rectangle",
            "label": "block",
        }

        self.assertEqual(make_shape_hash(first_shape), make_shape_hash(reordered_shape))

    def test_shape_hash_changes_when_geometry_changes(self):
        from drawing_graph.identifiers import make_shape_hash

        original_shape = {
            "label": "block",
            "shape_type": "rectangle",
            "points": [[10, 20], [30, 40]],
        }
        moved_shape = {
            "label": "block",
            "shape_type": "rectangle",
            "points": [[10, 20], [31, 40]],
        }

        self.assertNotEqual(make_shape_hash(original_shape), make_shape_hash(moved_shape))

    def test_exact_duplicate_shapes_generate_same_hash(self):
        from drawing_graph.identifiers import make_shape_hash

        shape = {
            "label": "table",
            "shape_type": "polygon",
            "points": [[0, 0], [10, 0], [10, 10], [0, 10]],
        }

        self.assertEqual(make_shape_hash(shape), make_shape_hash(shape.copy()))

    def test_same_page_name_in_different_drawing_sets_does_not_conflict(self):
        from drawing_graph.identifiers import make_page_id

        first_page_id = make_page_id("road-project", "set-a", "road_24")
        second_page_id = make_page_id("road-project", "set-b", "road_24")

        self.assertNotEqual(first_page_id, second_page_id)

    def test_shape_hash_does_not_depend_on_shapes_array_position(self):
        from drawing_graph.identifiers import make_shape_hash

        first_shape = {
            "label": "block",
            "shape_type": "rectangle",
            "points": [[10, 20], [30, 40]],
        }
        second_shape = {
            "label": "table",
            "shape_type": "rectangle",
            "points": [[50, 60], [70, 80]],
        }
        original_order_hashes = [make_shape_hash(shape) for shape in [first_shape, second_shape]]
        reversed_order_hashes = [make_shape_hash(shape) for shape in [second_shape, first_shape]]

        self.assertEqual(set(original_order_hashes), set(reversed_order_hashes))

    def test_rejects_unknown_element_kind(self):
        from drawing_graph.identifiers import IdentifierError, make_element_id

        with self.assertRaises(IdentifierError) as context:
            make_element_id("caption", "road-project", "set-a", "road_24", "abc123")

        self.assertEqual("invalid_element_kind", context.exception.category)


if __name__ == "__main__":
    unittest.main()
