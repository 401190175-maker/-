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
        self.nodes = []
        self.relations = []
        self.linked_pages = []

    def merge_nodes(self, nodes):
        if self.fail_on == "merge_nodes":
            raise RuntimeError("database unavailable")
        self.nodes.extend(nodes)

    def merge_relations(self, relations):
        if self.fail_on == "merge_relations":
            raise RuntimeError("relationship write failed")
        self.relations.extend(relations)

    def link_page_to_batch(self, page_id, batch_id):
        if self.fail_on == "link_page_to_batch":
            raise RuntimeError("batch link failed")
        self.linked_pages.append((page_id, batch_id))


class ImportPageTest(unittest.TestCase):
    def test_successful_page_import_persists_traceable_graph_and_batch_link(self):
        from drawing_graph.config import ImportConfig
        from drawing_graph.import_service import ImportService

        with _workspace_temp_dir() as data_root:
            json_path = _write_page(
                data_root,
                "set-a",
                "road_24.json",
                image_path="../old/road_24.png",
                shapes=[
                    _shape("block", [[10, 10], [50, 60]]),
                    _shape("table", [[70, 50], [120, 80]]),
                    _shape("table caption", [[80, 82], [110, 90]]),
                    _shape("title", [[1, 1], [20, 5]]),
                ],
            )
            repository = FakeRepository()
            service = ImportService(
                config=ImportConfig(data_root=data_root, project_slug="road-project", neo4j_uri="bolt://x", neo4j_user="u", neo4j_password="p"),
                repository=repository,
            )

            result = service.import_page("batch:1", json_path)

            self.assertEqual("success", result.status)
            self.assertEqual("page:road-project:set-a:road_24", result.page_id)
            self.assertEqual((), result.errors)
            self.assertIn(("page:road-project:set-a:road_24", "batch:1"), repository.linked_pages)

            labels_by_id = {node.id: node.labels for node in repository.nodes}
            self.assertEqual(("Project",), labels_by_id["project:road-project"])
            self.assertEqual(("DrawingSet",), labels_by_id["set:road-project:set-a"])
            self.assertEqual(("DrawingPage",), labels_by_id["page:road-project:set-a:road_24"])
            self.assertIn(("DrawingBlock",), labels_by_id.values())
            self.assertIn(("Table",), labels_by_id.values())
            self.assertIn(("TableCaption",), labels_by_id.values())
            self.assertIn(("Title",), labels_by_id.values())

            page_node = next(node for node in repository.nodes if node.id == "page:road-project:set-a:road_24")
            self.assertEqual(24, page_node.properties["page_number"])
            self.assertEqual("road_24.json", page_node.properties["file_name"])
            self.assertTrue(page_node.properties["image_path"].endswith("road_24.png"))
            self.assertEqual("../old/road_24.png", page_node.properties["original_image_path"])
            self.assertNotIn("import_batch_id", page_node.properties)

            relation_types = [relation.relation_type for relation in repository.relations]
            self.assertIn("HAS_SET", relation_types)
            self.assertIn("HAS_PAGE", relation_types)
            self.assertIn("HAS_BLOCK", relation_types)
            self.assertIn("HAS_TABLE", relation_types)
            self.assertIn("HAS_TEXT", relation_types)
            self.assertIn("HAS_ELEMENT", relation_types)
            self.assertEqual(0, sum(1 for relation in repository.relations if relation.relation_type == "HAS_CAPTION"))

    def test_missing_same_name_png_skips_page_without_persistence(self):
        from drawing_graph.config import ImportConfig
        from drawing_graph.import_service import ImportService

        with _workspace_temp_dir() as data_root:
            drawing_set = data_root / "set-a"
            drawing_set.mkdir()
            json_path = drawing_set / "road_24.json"
            json_path.write_text(
                json.dumps(_document("road_24.png", [_shape("block", [[1, 1], [2, 2]])])),
                encoding="utf-8",
            )
            repository = FakeRepository()
            service = ImportService(
                config=ImportConfig(data_root=data_root, project_slug="road-project", neo4j_uri="bolt://x", neo4j_user="u", neo4j_password="p"),
                repository=repository,
            )

            result = service.import_page("batch:1", json_path)

            self.assertEqual("skipped", result.status)
            self.assertIsNone(result.page_id)
            self.assertIn("same_name_png_missing", result.errors)
            self.assertEqual([], repository.nodes)
            self.assertEqual([], repository.relations)
            self.assertEqual([], repository.linked_pages)

    def test_invalid_page_number_fails_before_persistence(self):
        from drawing_graph.config import ImportConfig
        from drawing_graph.import_service import ImportService

        with _workspace_temp_dir() as data_root:
            json_path = _write_page(data_root, "set-a", "road_x.json", shapes=[_shape("block", [[1, 1], [2, 2]])])
            repository = FakeRepository()
            service = ImportService(
                config=ImportConfig(data_root=data_root, project_slug="road-project", neo4j_uri="bolt://x", neo4j_user="u", neo4j_password="p"),
                repository=repository,
            )

            result = service.import_page("batch:1", json_path)

            self.assertEqual("failed", result.status)
            self.assertIsNone(result.page_id)
            self.assertIn("invalid_page_filename", result.errors)
            self.assertEqual([], repository.nodes)
            self.assertEqual([], repository.relations)

    def test_invalid_shape_is_skipped_without_blocking_valid_elements(self):
        from drawing_graph.config import ImportConfig
        from drawing_graph.import_service import ImportService

        with _workspace_temp_dir() as data_root:
            json_path = _write_page(
                data_root,
                "set-a",
                "road_24.json",
                shapes=[
                    _shape("block", [[1, 1], [20, 20]]),
                    _shape("plain text", [[5, 5]]),
                ],
            )
            repository = FakeRepository()
            service = ImportService(
                config=ImportConfig(data_root=data_root, project_slug="road-project", neo4j_uri="bolt://x", neo4j_user="u", neo4j_password="p"),
                repository=repository,
            )

            result = service.import_page("batch:1", json_path)

            self.assertEqual("success", result.status)
            self.assertIn("invalid_points", result.warnings)
            element_nodes = [node for node in repository.nodes if node.id.startswith(("block:", "element:"))]
            self.assertEqual(1, len(element_nodes))
            self.assertEqual(("DrawingBlock",), element_nodes[0].labels)

    def test_duplicate_shape_is_deduplicated_and_reported_as_warning(self):
        from drawing_graph.config import ImportConfig
        from drawing_graph.import_service import ImportService

        duplicate = _shape("block", [[1, 1], [20, 20]])
        with _workspace_temp_dir() as data_root:
            json_path = _write_page(data_root, "set-a", "road_24.json", shapes=[duplicate, dict(duplicate)])
            repository = FakeRepository()
            service = ImportService(
                config=ImportConfig(data_root=data_root, project_slug="road-project", neo4j_uri="bolt://x", neo4j_user="u", neo4j_password="p"),
                repository=repository,
            )

            result = service.import_page("batch:1", json_path)

            self.assertEqual("success", result.status)
            self.assertIn("duplicate_shape", result.warnings)
            block_nodes = [node for node in repository.nodes if node.labels == ("DrawingBlock",)]
            self.assertEqual(1, len(block_nodes))

    def test_persistence_failure_returns_failed_without_page_batch_link(self):
        from drawing_graph.config import ImportConfig
        from drawing_graph.import_service import ImportService

        with _workspace_temp_dir() as data_root:
            json_path = _write_page(data_root, "set-a", "road_24.json", shapes=[_shape("block", [[1, 1], [20, 20]])])
            repository = FakeRepository(fail_on="merge_nodes")
            service = ImportService(
                config=ImportConfig(data_root=data_root, project_slug="road-project", neo4j_uri="bolt://x", neo4j_user="u", neo4j_password="p"),
                repository=repository,
            )

            result = service.import_page("batch:1", json_path)

            self.assertEqual("failed", result.status)
            self.assertEqual("page:road-project:set-a:road_24", result.page_id)
            self.assertIn("persistence_failed", result.errors)
            self.assertEqual([], repository.relations)
            self.assertEqual([], repository.linked_pages)


def _write_page(data_root, drawing_set_name, file_name, image_path=None, shapes=None):
    drawing_set = data_root / drawing_set_name
    drawing_set.mkdir()
    json_path = drawing_set / file_name
    png_path = json_path.with_suffix(".png")
    png_path.write_bytes(b"png")
    json_path.write_text(
        json.dumps(_document(image_path or png_path.name, shapes or [])),
        encoding="utf-8",
    )
    return json_path


class _workspace_temp_dir:
    def __enter__(self):
        self.path = PROJECT_ROOT / ".test_tmp" / f"import-page-{uuid4().hex}"
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


if __name__ == "__main__":
    unittest.main()
