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
    def __init__(self, fail_on=None):
        self.fail_on = fail_on
        self.created_batches = []
        self.finished_batches = []
        self.nodes = []
        self.relations = []
        self.linked_pages = []

    def create_batch(self, batch_id, project_id, source_root, started_at):
        if self.fail_on == "create_batch":
            raise RuntimeError("database unavailable")
        self.created_batches.append(
            {
                "batch_id": batch_id,
                "project_id": project_id,
                "source_root": source_root,
                "started_at": started_at,
            }
        )
        return batch_id

    def finish_batch(
        self,
        batch_id,
        status,
        finished_at,
        total_files,
        success_count,
        skipped_count,
        failed_count,
        warning_count,
        error_summary,
    ):
        if self.fail_on == "finish_batch":
            raise RuntimeError("finish failed")
        self.finished_batches.append(
            {
                "batch_id": batch_id,
                "status": status,
                "finished_at": finished_at,
                "total_files": total_files,
                "success_count": success_count,
                "skipped_count": skipped_count,
                "failed_count": failed_count,
                "warning_count": warning_count,
                "error_summary": tuple(error_summary),
            }
        )

    def merge_nodes(self, nodes):
        self.nodes.extend(nodes)

    def merge_relations(self, relations):
        self.relations.extend(relations)

    def link_page_to_batch(self, page_id, batch_id):
        if self.fail_on == "link_page_to_batch":
            raise RuntimeError("database disconnected")
        self.linked_pages.append((page_id, batch_id))


class ImportAllTest(unittest.TestCase):
    def test_import_all_creates_successful_batch_for_all_drawing_sets(self):
        from drawing_graph.import_service import ImportService

        with _workspace_temp_dir() as data_root:
            set_b = data_root / "set-b"
            set_a = data_root / "set-a"
            set_b.mkdir()
            set_a.mkdir()
            _write_page(set_b, "road_2.json", [_shape("block", [[1, 1], [20, 20]])])
            _write_page(set_a, "road_1.json", [_shape("title", [[1, 1], [20, 20]])])
            repository = FakeRepository()
            service = ImportService(_config(data_root), repository)

            result = service.import_all()

            self.assertEqual("success", result.status)
            self.assertEqual(2, result.total_count)
            self.assertEqual(2, result.success_count)
            self.assertEqual(0, result.skipped_count)
            self.assertEqual(0, result.failed_count)
            self.assertTrue(result.batch_id.startswith("batch:"))
            self.assertEqual(result.batch_id, repository.created_batches[0]["batch_id"])
            self.assertEqual("project:road-project", repository.created_batches[0]["project_id"])
            self.assertEqual(str(data_root), repository.created_batches[0]["source_root"])
            self.assertEqual("success", repository.finished_batches[0]["status"])
            self.assertEqual(
                [
                    ("page:road-project:set-a:road_1", result.batch_id),
                    ("page:road-project:set-b:road_2", result.batch_id),
                ],
                repository.linked_pages,
            )

    def test_import_all_finishes_failed_when_any_drawing_set_has_failed_page(self):
        from drawing_graph.import_service import ImportService

        with _workspace_temp_dir() as data_root:
            set_a = data_root / "set-a"
            set_a.mkdir()
            _write_page(set_a, "road_1.json", [_shape("block", [[1, 1], [20, 20]])])
            _write_page(set_a, "road_x.json", [_shape("block", [[1, 1], [20, 20]])])
            repository = FakeRepository()
            service = ImportService(_config(data_root), repository)

            result = service.import_all()

            self.assertEqual("failed", result.status)
            self.assertEqual(2, result.total_count)
            self.assertEqual(1, result.success_count)
            self.assertEqual(0, result.skipped_count)
            self.assertEqual(1, result.failed_count)
            self.assertEqual(("invalid_page_filename",), result.errors)
            self.assertEqual("failed", repository.finished_batches[0]["status"])
            self.assertEqual(("invalid_page_filename",), repository.finished_batches[0]["error_summary"])

    def test_import_all_stops_after_database_disconnection_and_finishes_failed_batch(self):
        from drawing_graph.import_service import ImportService

        with _workspace_temp_dir() as data_root:
            set_a = data_root / "set-a"
            set_b = data_root / "set-b"
            set_a.mkdir()
            set_b.mkdir()
            _write_page(set_a, "road_1.json", [_shape("block", [[1, 1], [20, 20]])])
            _write_page(set_b, "road_2.json", [_shape("block", [[1, 1], [20, 20]])])
            repository = FakeRepository(fail_on="link_page_to_batch")
            service = ImportService(_config(data_root), repository)

            result = service.import_all()

            self.assertEqual("failed", result.status)
            self.assertEqual(1, result.total_count)
            self.assertEqual(0, result.success_count)
            self.assertEqual(0, result.skipped_count)
            self.assertEqual(1, result.failed_count)
            self.assertEqual(("persistence_failed",), result.errors)
            self.assertEqual("failed", repository.finished_batches[0]["status"])
            self.assertEqual(("persistence_failed",), repository.finished_batches[0]["error_summary"])

    def test_import_all_returns_failed_without_batch_when_create_batch_fails(self):
        from drawing_graph.import_service import ImportService

        with _workspace_temp_dir() as data_root:
            drawing_set = data_root / "set-a"
            drawing_set.mkdir()
            _write_page(drawing_set, "road_1.json", [_shape("block", [[1, 1], [20, 20]])])
            repository = FakeRepository(fail_on="create_batch")
            service = ImportService(_config(data_root), repository)

            result = service.import_all()

            self.assertEqual("failed", result.status)
            self.assertIsNone(result.batch_id)
            self.assertEqual(0, result.total_count)
            self.assertEqual(("batch_create_failed",), result.errors)
            self.assertEqual([], repository.finished_batches)
            self.assertEqual([], repository.linked_pages)


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
        self.path = PROJECT_ROOT / ".test_tmp" / f"import-all-{uuid4().hex}"
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
