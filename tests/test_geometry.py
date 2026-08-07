import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class GeometryTest(unittest.TestCase):
    def test_rectangle_points_return_bbox_center_size_and_normalized_bbox(self):
        from drawing_graph.geometry import normalize_geometry

        result = normalize_geometry([[10, 20], [110, 120]], 1000, 800)

        self.assertEqual(
            {"x_min": 10.0, "y_min": 20.0, "x_max": 110.0, "y_max": 120.0},
            result.bbox,
        )
        self.assertEqual(60.0, result.center_x)
        self.assertEqual(70.0, result.center_y)
        self.assertEqual(100.0, result.width)
        self.assertEqual(100.0, result.height)
        self.assertEqual(
            {"x_min": 0.01, "y_min": 0.025, "x_max": 0.11, "y_max": 0.15},
            result.normalized_bbox,
        )
        self.assertEqual((), result.warnings)

    def test_polygon_points_use_outer_bbox(self):
        from drawing_graph.geometry import normalize_geometry

        result = normalize_geometry([[30, 80], [10, 20], [70, 40], [50, 120]], 100, 200)

        self.assertEqual(
            {"x_min": 10.0, "y_min": 20.0, "x_max": 70.0, "y_max": 120.0},
            result.bbox,
        )
        self.assertEqual(40.0, result.center_x)
        self.assertEqual(70.0, result.center_y)

    def test_rotation_points_use_all_points_outer_bbox(self):
        from drawing_graph.geometry import normalize_geometry

        result = normalize_geometry([[50, 10], [90, 50], [50, 90], [10, 50]], 100, 100)

        self.assertEqual(
            {"x_min": 10.0, "y_min": 10.0, "x_max": 90.0, "y_max": 90.0},
            result.bbox,
        )
        self.assertEqual(
            {"x_min": 0.1, "y_min": 0.1, "x_max": 0.9, "y_max": 0.9},
            result.normalized_bbox,
        )

    def test_invalid_points_are_rejected_with_category(self):
        from drawing_graph.geometry import GeometryError, normalize_geometry

        with self.assertRaises(GeometryError) as context:
            normalize_geometry([[10, 20]], 100, 100)

        self.assertEqual("invalid_points", context.exception.category)

    def test_zero_size_image_is_rejected_with_category(self):
        from drawing_graph.geometry import GeometryError, normalize_geometry

        with self.assertRaises(GeometryError) as context:
            normalize_geometry([[10, 20], [30, 40]], 0, 100)

        self.assertEqual("invalid_image_size", context.exception.category)

    def test_out_of_bounds_coordinates_return_warning_and_clamped_normalized_bbox(self):
        from drawing_graph.geometry import normalize_geometry

        result = normalize_geometry([[-10, 20], [120, 140]], 100, 100)

        self.assertEqual(
            {"x_min": -10.0, "y_min": 20.0, "x_max": 120.0, "y_max": 140.0},
            result.bbox,
        )
        self.assertEqual(
            {"x_min": 0.0, "y_min": 0.2, "x_max": 1.0, "y_max": 1.0},
            result.normalized_bbox,
        )
        self.assertEqual(1, len(result.warnings))
        self.assertEqual("coordinate_out_of_bounds", result.warnings[0].category)


if __name__ == "__main__":
    unittest.main()
