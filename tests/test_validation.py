import copy
import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class ValidationTest(unittest.TestCase):
    def valid_document(self):
        return {
            "imagePath": "road_24.png",
            "imageWidth": 1000,
            "imageHeight": 800,
            "shapes": [
                {
                    "label": "block",
                    "points": [[10, 20], [110, 120]],
                    "shape_type": "rectangle",
                }
            ],
        }

    def test_valid_document_is_importable(self):
        from drawing_graph.validation import ValidationStatus, validate_document

        result = validate_document(self.valid_document())

        self.assertEqual(ValidationStatus.IMPORTABLE, result.status)
        self.assertEqual((), result.issues)

    def test_invalid_json_text_is_not_importable(self):
        from drawing_graph.validation import ValidationStatus, validate_document

        result = validate_document("{not json")

        self.assertEqual(ValidationStatus.INVALID, result.status)
        self.assertEqual("json_parse_error", result.issues[0].category)

    def test_missing_page_level_field_is_not_importable(self):
        from drawing_graph.validation import ValidationStatus, validate_document

        document = self.valid_document()
        del document["imageWidth"]

        result = validate_document(document)

        self.assertEqual(ValidationStatus.INVALID, result.status)
        self.assertEqual("missing_page_field", result.issues[0].category)
        self.assertIn("imageWidth", result.issues[0].message)

    def test_missing_shape_field_is_repairable(self):
        from drawing_graph.validation import ValidationStatus, validate_document

        document = self.valid_document()
        del document["shapes"][0]["shape_type"]

        result = validate_document(document)

        self.assertEqual(ValidationStatus.REPAIRABLE, result.status)
        self.assertEqual("missing_shape_field", result.issues[0].category)
        self.assertEqual("shapes[0]", result.issues[0].location)

    def test_empty_points_are_repairable(self):
        from drawing_graph.validation import ValidationStatus, validate_document

        document = self.valid_document()
        document["shapes"][0]["points"] = []

        result = validate_document(document)

        self.assertEqual(ValidationStatus.REPAIRABLE, result.status)
        self.assertEqual("empty_points", result.issues[0].category)

    def test_validation_does_not_modify_input_object(self):
        from drawing_graph.validation import validate_document

        document = self.valid_document()
        original = copy.deepcopy(document)

        validate_document(document)

        self.assertEqual(original, document)

    def test_json_text_document_is_validated_after_parsing(self):
        from drawing_graph.validation import ValidationStatus, validate_document

        result = validate_document(json.dumps(self.valid_document()))

        self.assertEqual(ValidationStatus.IMPORTABLE, result.status)


if __name__ == "__main__":
    unittest.main()
