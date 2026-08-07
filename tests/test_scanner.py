import sys
import shutil
import uuid
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class ScannerTest(unittest.TestCase):
    def setUp(self):
        self.temp_root = PROJECT_ROOT / ".test_tmp" / f"scanner-{uuid.uuid4().hex}"
        self.temp_root.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def test_scan_drawing_sets_returns_sorted_sets_and_json_files(self):
        from drawing_graph.scanner import scan_drawing_sets

        data_root = self.temp_root
        beta = data_root / "beta"
        alpha = data_root / "alpha"
        beta.mkdir()
        alpha.mkdir()
        (beta / "road_2.json").write_text("{}", encoding="utf-8")
        (beta / "road_1.json").write_text("{}", encoding="utf-8")
        (beta / "road_1.png").write_text("png", encoding="utf-8")
        (beta / "notes.txt").write_text("ignore", encoding="utf-8")
        (alpha / "road_3.json").write_text("{}", encoding="utf-8")

        drawing_sets = scan_drawing_sets(data_root)

        self.assertEqual(["alpha", "beta"], [item.name for item in drawing_sets])
        self.assertEqual(
            ["road_3.json"],
            [record.path.name for record in drawing_sets[0].json_files],
        )
        self.assertEqual(
            ["road_1.json", "road_2.json"],
            [record.path.name for record in drawing_sets[1].json_files],
        )
        self.assertEqual(beta / "road_1.png", drawing_sets[1].json_files[0].image_path)
        self.assertIsNone(drawing_sets[1].json_files[1].image_path)

    def test_scan_drawing_sets_includes_empty_directories(self):
        from drawing_graph.scanner import scan_drawing_sets

        data_root = self.temp_root
        (data_root / "empty").mkdir()

        drawing_sets = scan_drawing_sets(data_root)

        self.assertEqual(1, len(drawing_sets))
        self.assertEqual("empty", drawing_sets[0].name)
        self.assertEqual((), drawing_sets[0].json_files)

    def test_scan_drawing_sets_rejects_missing_root(self):
        from drawing_graph.scanner import ScannerError, scan_drawing_sets

        missing_root = self.temp_root / "missing"

        with self.assertRaises(ScannerError) as context:
            scan_drawing_sets(missing_root)

        self.assertIn("data_root", str(context.exception))

    def test_scan_drawing_sets_rejects_file_root(self):
        from drawing_graph.scanner import ScannerError, scan_drawing_sets

        file_root = self.temp_root / "data.txt"
        file_root.write_text("not a directory", encoding="utf-8")

        with self.assertRaises(ScannerError) as context:
            scan_drawing_sets(file_root)

        self.assertIn("directory", str(context.exception))


if __name__ == "__main__":
    unittest.main()
