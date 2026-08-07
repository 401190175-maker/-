import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class ImagePathTest(unittest.TestCase):
    def setUp(self):
        self.temp_root = PROJECT_ROOT / ".test_tmp" / f"image-paths-{uuid.uuid4().hex}"
        self.temp_root.mkdir(parents=True)
        self.data_root = self.temp_root / "data"
        self.drawing_set = self.data_root / "set-a"
        self.drawing_set.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def write_page(self, image_path):
        json_path = self.drawing_set / "road_24.json"
        document = {
            "imagePath": image_path,
            "imageWidth": 100,
            "imageHeight": 80,
            "shapes": [],
            "untouched": {"value": 1},
        }
        json_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        return json_path, document

    def read_page(self, json_path):
        return json.loads(json_path.read_text(encoding="utf-8"))

    def test_correct_same_directory_png_path_is_unchanged(self):
        from drawing_graph.image_paths import ImagePathStatus, normalize_image_path

        json_path, document = self.write_page("road_24.png")
        png_path = self.drawing_set / "road_24.png"
        png_path.write_text("png", encoding="utf-8")

        result = normalize_image_path(json_path, document, self.data_root)

        self.assertEqual(ImagePathStatus.UNCHANGED, result.status)
        self.assertEqual("road_24.png", result.original_image_path)
        self.assertEqual(png_path, result.image_path)
        self.assertEqual("road_24.png", document["imagePath"])
        self.assertEqual(self.read_page(json_path), document)

    def test_external_image_path_is_repaired_to_same_directory_png(self):
        from drawing_graph.image_paths import ImagePathStatus, normalize_image_path

        json_path, document = self.write_page("../old/road_24.png")
        (self.drawing_set / "road_24.png").write_text("png", encoding="utf-8")

        result = normalize_image_path(json_path, document, self.data_root)

        stored_document = self.read_page(json_path)
        self.assertEqual(ImagePathStatus.UPDATED, result.status)
        self.assertEqual("../old/road_24.png", result.original_image_path)
        self.assertEqual("road_24.png", document["imagePath"])
        self.assertEqual("road_24.png", stored_document["imagePath"])
        self.assertEqual({"value": 1}, stored_document["untouched"])

    def test_missing_same_name_png_skips_without_modifying_json(self):
        from drawing_graph.image_paths import ImagePathStatus, normalize_image_path

        json_path, document = self.write_page("../old/road_24.png")
        original_file_text = json_path.read_text(encoding="utf-8")

        result = normalize_image_path(json_path, document, self.data_root)

        self.assertEqual(ImagePathStatus.MISSING_IMAGE, result.status)
        self.assertEqual("same_name_png_missing", result.issue.category)
        self.assertEqual("../old/road_24.png", document["imagePath"])
        self.assertEqual(original_file_text, json_path.read_text(encoding="utf-8"))

    def test_json_path_outside_data_root_is_rejected(self):
        from drawing_graph.image_paths import ImagePathError, normalize_image_path

        outside_json = self.temp_root / "road_24.json"
        outside_json.write_text("{}", encoding="utf-8")

        with self.assertRaises(ImagePathError) as context:
            normalize_image_path(outside_json, {"imagePath": "road_24.png"}, self.data_root)

        self.assertEqual("path_escapes_data_root", context.exception.category)

    def test_atomic_replace_failure_keeps_original_json(self):
        from drawing_graph.image_paths import ImagePathError, normalize_image_path

        json_path, document = self.write_page("../old/road_24.png")
        (self.drawing_set / "road_24.png").write_text("png", encoding="utf-8")
        original_file_text = json_path.read_text(encoding="utf-8")

        with patch("drawing_graph.image_paths.os.replace", side_effect=OSError("locked")):
            with self.assertRaises(ImagePathError) as context:
                normalize_image_path(json_path, document, self.data_root)

        self.assertEqual("atomic_replace_failed", context.exception.category)
        self.assertEqual(original_file_text, json_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
