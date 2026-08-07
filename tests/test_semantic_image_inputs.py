import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.semantic_image_inputs import SemanticImageInputBuilder
from drawing_graph.tool_models import BBox, ElementEvidence, PageSourceFacts, ToolModelError


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def element(element_id="block:1", element_type="DrawingBlock"):
    return ElementEvidence(
        element_id=element_id,
        element_type=element_type,
        source_label="block",
        bbox=BBox(1, 2, 3, 4),
        normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
    )


def page_facts(**overrides):
    values = {
        "page_id": "page:1",
        "image_path": "road_24.png",
        "elements": (element(), element("caption:1", "BlockCaption")),
    }
    values.update(overrides)
    return PageSourceFacts(**values)


class SemanticImageInputsTest(unittest.TestCase):
    def test_builds_input_with_bbox_image_hash_and_context_refs(self):
        builder = SemanticImageInputBuilder(image_hash_provider=lambda image_path: "hash:provided")

        image_input = builder.build_input(page_facts(), "block:1")

        self.assertEqual("page:1", image_input.page_id)
        self.assertEqual("block:1", image_input.element_id)
        self.assertEqual("DrawingBlock", image_input.element_type)
        self.assertEqual("road_24.png", image_input.image_path)
        self.assertEqual("hash:provided", image_input.image_hash)
        self.assertEqual(BBox(1, 2, 3, 4), image_input.bbox)
        self.assertEqual(2, len(image_input.context_refs))
        self.assertEqual(("block:1", "caption:1"), tuple(item.element_id for item in image_input.context_refs))

    def test_missing_element_returns_not_found(self):
        builder = SemanticImageInputBuilder(image_hash_provider=lambda image_path: "hash:provided")

        with self.assertRaises(ToolModelError) as error:
            builder.build_input(page_facts(), "missing:1")

        self.assertEqual("NOT_FOUND", error.exception.category)

    def test_missing_image_reference_returns_stable_error(self):
        builder = SemanticImageInputBuilder(image_hash_provider=lambda image_path: "hash:provided")

        with self.assertRaises(ToolModelError) as error:
            builder.build_input(page_facts(image_path=None), "block:1")

        self.assertEqual("INVALID_ARGUMENT", error.exception.category)

    def test_invalid_bbox_is_rejected_before_input_build(self):
        builder = SemanticImageInputBuilder(image_hash_provider=lambda image_path: "hash:provided")

        with self.assertRaises(ToolModelError):
            page_facts(
                elements=(
                    ElementEvidence(
                        element_id="block:1",
                        element_type="DrawingBlock",
                        source_label="block",
                        bbox=BBox(0.5, 0.2, 0.1, 0.4),
                        normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
                    ),
                )
            )

    def test_computes_image_hash_from_file_when_facts_have_no_hash(self):
        test_dir = PROJECT_ROOT / ".test_tmp" / "semantic_image_inputs"
        test_dir.mkdir(parents=True, exist_ok=True)
        image_file = test_dir / "page.png"
        image_file.write_bytes(b"fake-image-bytes")
        expected_hash = hashlib.sha256(b"fake-image-bytes").hexdigest()
        try:
            builder = SemanticImageInputBuilder()
            image_input = builder.build_input(
                page_facts(image_path=str(image_file)),
                "block:1",
            )
            self.assertEqual(expected_hash, image_input.image_hash)
        finally:
            image_file.unlink(missing_ok=True)

    def test_page_facts_hash_is_preferred_over_file_provider(self):
        builder = SemanticImageInputBuilder(image_hash_provider=lambda image_path: "hash:computed")

        image_input = builder.build_input(page_facts(image_hash="hash:from-graph"), "block:1")

        self.assertEqual("hash:from-graph", image_input.image_hash)


if __name__ == "__main__":
    unittest.main()
