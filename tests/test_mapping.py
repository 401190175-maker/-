import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def make_element(label):
    from drawing_graph.models import BBox, ElementRecord, NormalizedBBox

    normalized_label = label.replace(" ", "_")
    return ElementRecord(
        id=f"element:road-project:set-a:road_24:{normalized_label}",
        page_id="page:road-project:set-a:road_24",
        label=label,
        confidence=0.95,
        shape_type="rectangle",
        bbox=BBox(x_min=10, y_min=20, x_max=110, y_max=120),
        normalized_bbox=NormalizedBBox(x_min=0.01, y_min=0.025, x_max=0.11, y_max=0.15),
        source_label=label,
        original_points=((10.0, 20.0), (110.0, 120.0)),
        citation_ref=f"set-a/road_24#{normalized_label}",
    )


class MappingTest(unittest.TestCase):
    def test_block_maps_to_drawing_block_with_has_block_relation(self):
        from drawing_graph.mapping import map_element

        node, relation = map_element(make_element("block"))

        self.assertEqual(("DrawingBlock",), node.labels)
        self.assertEqual("HAS_BLOCK", relation.relation_type)
        self.assertEqual("page:road-project:set-a:road_24", relation.start_id)
        self.assertEqual(node.id, relation.end_id)

    def test_table_maps_to_table_with_has_table_relation(self):
        from drawing_graph.mapping import map_element

        node, relation = map_element(make_element("table"))

        self.assertEqual(("Table",), node.labels)
        self.assertEqual("HAS_TABLE", relation.relation_type)

    def test_table_caption_maps_to_page_element_relation(self):
        from drawing_graph.mapping import map_element

        node, relation = map_element(make_element("table caption"))

        self.assertEqual(("TableCaption",), node.labels)
        self.assertEqual("HAS_ELEMENT", relation.relation_type)

    def test_block_caption_maps_to_page_element_relation(self):
        from drawing_graph.mapping import map_element

        node, relation = map_element(make_element("block caption"))

        self.assertEqual(("BlockCaption",), node.labels)
        self.assertEqual("HAS_ELEMENT", relation.relation_type)

    def test_cross_section_maps_to_page_element_relation(self):
        from drawing_graph.mapping import map_element

        node, relation = map_element(make_element("cross section"))

        self.assertEqual(("CrossSection",), node.labels)
        self.assertEqual("HAS_ELEMENT", relation.relation_type)

    def test_drawing_basic_info_maps_to_has_basic_info_relation(self):
        from drawing_graph.mapping import map_element

        node, relation = map_element(make_element("drawing basic info"))

        self.assertEqual(("DrawingBasicInfo",), node.labels)
        self.assertEqual("HAS_BASIC_INFO", relation.relation_type)

    def test_drawing_annotation_maps_to_has_annotation_relation(self):
        from drawing_graph.mapping import map_element

        node, relation = map_element(make_element("drawing annotation"))

        self.assertEqual(("DrawingAnnotation",), node.labels)
        self.assertEqual("HAS_ANNOTATION", relation.relation_type)

    def test_plain_text_and_title_use_has_text_relation(self):
        from drawing_graph.mapping import map_element

        plain_text_node, plain_text_relation = map_element(make_element("plain text"))
        title_node, title_relation = map_element(make_element("title"))

        self.assertEqual(("PlainText",), plain_text_node.labels)
        self.assertEqual("HAS_TEXT", plain_text_relation.relation_type)
        self.assertEqual(("Title",), title_node.labels)
        self.assertEqual("HAS_TEXT", title_relation.relation_type)

    def test_abandon_maps_to_ignored_element_not_queryable(self):
        from drawing_graph.mapping import map_element

        node, relation = map_element(make_element("abandon"))

        self.assertEqual(("IgnoredElement",), node.labels)
        self.assertEqual("HAS_ELEMENT", relation.relation_type)
        self.assertFalse(node.properties["queryable"])
        self.assertEqual("abandon", node.properties["ignore_reason"])

    def test_node_properties_keep_geometry_and_source_evidence(self):
        from drawing_graph.mapping import map_element

        node, _ = map_element(make_element("block"))

        self.assertEqual("block", node.properties["label"])
        self.assertEqual(0.95, node.properties["confidence"])
        self.assertEqual("rectangle", node.properties["shape_type"])
        self.assertEqual([10.0, 20.0, 110.0, 120.0], node.properties["bbox"])
        self.assertEqual([0.01, 0.025, 0.11, 0.15], node.properties["normalized_bbox"])
        self.assertEqual("block", node.properties["source_label"])
        self.assertEqual([10.0, 20.0, 110.0, 120.0], node.properties["original_points"])
        self.assertEqual("set-a/road_24#block", node.properties["citation_ref"])
        self.assertNotIn("block_type", node.properties)

    def test_node_properties_are_neo4j_property_compatible(self):
        from drawing_graph.mapping import map_element

        node, _ = map_element(make_element("block"))

        for value in node.properties.values():
            self.assertFalse(isinstance(value, dict))
            if isinstance(value, (list, tuple)):
                self.assertTrue(all(not isinstance(item, (list, tuple, dict)) for item in value))

    def test_unknown_label_is_rejected_without_dynamic_label(self):
        from drawing_graph.mapping import MappingError, map_element

        with self.assertRaises(MappingError) as context:
            map_element(make_element("custom symbol"))

        self.assertEqual("unknown_element_label", context.exception.category)


if __name__ == "__main__":
    unittest.main()
