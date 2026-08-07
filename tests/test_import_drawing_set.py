import json
import sys
import unittest
from pathlib import Path
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class FakeRepository:
    def __init__(self):
        self.nodes = []
        self.relations = []
        self.linked_pages = []

    def merge_nodes(self, nodes):
        self.nodes.extend(nodes)

    def merge_relations(self, relations):
        self.relations.extend(relations)

    def link_page_to_batch(self, page_id, batch_id):
        self.linked_pages.append((page_id, batch_id))


class ImportDrawingSetTest(unittest.TestCase):
    def test_import_drawing_set_imports_all_pages_in_name_order(self):
        from drawing_graph.config import ImportConfig
        from drawing_graph.import_service import ImportService

        with _workspace_temp_dir() as data_root:
            drawing_set = data_root / "set-a"
            drawing_set.mkdir()
            _write_page(drawing_set, "road_2.json", [_shape("block", [[1, 1], [20, 20]])])
            _write_page(drawing_set, "road_1.json", [_shape("title", [[1, 1], [20, 20]])])
            (drawing_set / "note.txt").write_text("ignored", encoding="utf-8")
            repository = FakeRepository()
            service = ImportService(_config(data_root), repository)

            result = service.import_drawing_set("batch:1", drawing_set)

            self.assertEqual("success", result.status)
            self.assertEqual("set:road-project:set-a", result.drawing_set_id)
            self.assertEqual(2, result.total_count)
            self.assertEqual(2, result.success_count)
            self.assertEqual(0, result.skipped_count)
            self.assertEqual(0, result.failed_count)
            self.assertEqual(0, result.warning_count)
            self.assertEqual(
                [
                    ("page:road-project:set-a:road_1", "batch:1"),
                    ("page:road-project:set-a:road_2", "batch:1"),
                ],
                repository.linked_pages,
            )

    def test_page_failure_does_not_stop_remaining_pages(self):
        from drawing_graph.config import ImportConfig
        from drawing_graph.import_service import ImportService

        with _workspace_temp_dir() as data_root:
            drawing_set = data_root / "set-a"
            drawing_set.mkdir()
            _write_page(drawing_set, "road_1.json", [_shape("block", [[1, 1], [20, 20]])])
            _write_page(drawing_set, "road_x.json", [_shape("block", [[1, 1], [20, 20]])])
            _write_page(drawing_set, "road_2.json", [_shape("plain text", [[1, 1], [20, 20]])])
            repository = FakeRepository()
            service = ImportService(_config(data_root), repository)

            result = service.import_drawing_set("batch:1", drawing_set)

            self.assertEqual("failed", result.status)
            self.assertEqual(3, result.total_count)
            self.assertEqual(2, result.success_count)
            self.assertEqual(0, result.skipped_count)
            self.assertEqual(1, result.failed_count)
            self.assertEqual(("invalid_page_filename",), result.errors)
            self.assertEqual(2, len(repository.linked_pages))

    def test_skipped_page_is_counted_without_stopping_drawing_set(self):
        from drawing_graph.config import ImportConfig
        from drawing_graph.import_service import ImportService

        with _workspace_temp_dir() as data_root:
            drawing_set = data_root / "set-a"
            drawing_set.mkdir()
            _write_page(drawing_set, "road_1.json", [_shape("block", [[1, 1], [20, 20]])])
            _write_json_without_png(drawing_set, "road_2.json", [_shape("block", [[1, 1], [20, 20]])])
            repository = FakeRepository()
            service = ImportService(_config(data_root), repository)

            result = service.import_drawing_set("batch:1", drawing_set)

            self.assertEqual("success", result.status)
            self.assertEqual(2, result.total_count)
            self.assertEqual(1, result.success_count)
            self.assertEqual(1, result.skipped_count)
            self.assertEqual(0, result.failed_count)
            self.assertEqual(("same_name_png_missing",), result.errors)
            self.assertEqual(1, len(repository.linked_pages))

    def test_empty_drawing_set_returns_skipped_summary(self):
        from drawing_graph.import_service import ImportService

        with _workspace_temp_dir() as data_root:
            drawing_set = data_root / "empty-set"
            drawing_set.mkdir()
            repository = FakeRepository()
            service = ImportService(_config(data_root), repository)

            result = service.import_drawing_set("batch:1", drawing_set)

            self.assertEqual("skipped", result.status)
            self.assertEqual("set:road-project:empty-set", result.drawing_set_id)
            self.assertEqual(0, result.total_count)
            self.assertEqual(0, result.success_count)
            self.assertEqual(0, result.skipped_count)
            self.assertEqual(0, result.failed_count)
            self.assertEqual(("empty_drawing_set",), result.errors)
            self.assertEqual([], repository.linked_pages)

    def test_repeated_import_keeps_stable_page_links(self):
        from drawing_graph.import_service import ImportService

        with _workspace_temp_dir() as data_root:
            drawing_set = data_root / "set-a"
            drawing_set.mkdir()
            _write_page(drawing_set, "road_1.json", [_shape("block", [[1, 1], [20, 20]])])
            repository = FakeRepository()
            service = ImportService(_config(data_root), repository)

            first_result = service.import_drawing_set("batch:1", drawing_set)
            second_result = service.import_drawing_set("batch:1", drawing_set)

            self.assertEqual("success", first_result.status)
            self.assertEqual("success", second_result.status)
            self.assertEqual(
                [
                    ("page:road-project:set-a:road_1", "batch:1"),
                    ("page:road-project:set-a:road_1", "batch:1"),
                ],
                repository.linked_pages,
            )


def _config(data_root):
    from drawing_graph.config import ImportConfig

    return ImportConfig(
        data_root=data_root,
        project_slug="road-project",
        neo4j_uri="bolt://x",
        neo4j_user="u",
        neo4j_password="p",
    )


def _write_page(drawing_set, file_name, shapes):
    json_path = drawing_set / file_name
    json_path.with_suffix(".png").write_bytes(b"png")
    json_path.write_text(json.dumps(_document(json_path.with_suffix(".png").name, shapes)), encoding="utf-8")
    return json_path


def _write_json_without_png(drawing_set, file_name, shapes):
    json_path = drawing_set / file_name
    json_path.write_text(json.dumps(_document(json_path.with_suffix(".png").name, shapes)), encoding="utf-8")
    return json_path


def _document(image_path, shapes):
    return {
        "imagePath": image_path,
        "imageWidth": 200,
        "imageHeight": 100,
        "shapes": shapes,
    }


def _shape(label, points):
    return {
        "label": label,
        "points": points,
        "shape_type": "rectangle",
        "score": 0.9,
    }


class _workspace_temp_dir:
    def __enter__(self):
        self.path = PROJECT_ROOT / ".test_tmp" / f"import-drawing-set-{uuid4().hex}"
        self.path.mkdir(parents=True)
        return self.path

    def __exit__(self, exc_type, exc_value, traceback):
        _remove_tree(self.path)
        return False


def _remove_tree(path):
    if not path.exists():
        return
    for child in sorted(path.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if child.is_file():
            child.unlink()
        else:
            child.rmdir()
    path.rmdir()


if __name__ == "__main__":
    unittest.main()
