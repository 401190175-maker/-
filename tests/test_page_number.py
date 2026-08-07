import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class PageNumberTest(unittest.TestCase):
    def test_road_number_json_returns_page_number(self):
        from drawing_graph.page_number import parse_page_number

        page_number = parse_page_number(Path("drawing_set") / "road_24.json")

        self.assertEqual(24, page_number)

    def test_road_number_with_leading_zeroes_returns_integer(self):
        from drawing_graph.page_number import parse_page_number

        page_number = parse_page_number("road_007.json")

        self.assertEqual(7, page_number)

    def test_rejects_revision_file_name(self):
        from drawing_graph.page_number import PageNumberError, parse_page_number

        with self.assertRaises(PageNumberError) as context:
            parse_page_number("road_2_rev_1.json")

        self.assertEqual("invalid_page_filename", context.exception.category)
        self.assertIn("road_<number>.json", str(context.exception))

    def test_rejects_non_numeric_page_name(self):
        from drawing_graph.page_number import PageNumberError, parse_page_number

        with self.assertRaises(PageNumberError) as context:
            parse_page_number("road_x.json")

        self.assertEqual("invalid_page_filename", context.exception.category)

    def test_rejects_file_name_without_number(self):
        from drawing_graph.page_number import PageNumberError, parse_page_number

        with self.assertRaises(PageNumberError) as context:
            parse_page_number("overview.json")

        self.assertEqual("invalid_page_filename", context.exception.category)

    def test_rejects_non_json_suffix(self):
        from drawing_graph.page_number import PageNumberError, parse_page_number

        with self.assertRaises(PageNumberError) as context:
            parse_page_number("road_24.txt")

        self.assertEqual("invalid_page_filename", context.exception.category)


if __name__ == "__main__":
    unittest.main()
