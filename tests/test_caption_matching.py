import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def make_element(element_id, label, bbox_values):
    from drawing_graph.models import BBox, ElementRecord, NormalizedBBox

    return ElementRecord(
        id=element_id,
        page_id="page:road-project:set-a:road_24",
        label=label,
        confidence=0.95,
        shape_type="rectangle",
        bbox=BBox(**bbox_values),
        normalized_bbox=NormalizedBBox(x_min=0.1, y_min=0.1, x_max=0.2, y_max=0.2),
        source_label=label,
        original_points=((bbox_values["x_min"], bbox_values["y_min"]), (bbox_values["x_max"], bbox_values["y_max"])),
        citation_ref=f"set-a/road_24#{element_id}",
    )


class CaptionMatchingTest(unittest.TestCase):
    def test_pure_matcher_matches_compatible_entry_point_results(self):
        from drawing_graph.caption_matching import TableCaptionMatchInput, match_table_caption_inputs, match_table_captions

        table = make_element("table:a", "table", {"x_min": 10, "y_min": 10, "x_max": 100, "y_max": 100})
        caption = make_element(
            "caption:a",
            "table caption",
            {"x_min": 10, "y_min": 110, "x_max": 100, "y_max": 130},
        )

        pure_matches = match_table_caption_inputs(
            tables=[TableCaptionMatchInput(id=table.id, bbox=table.bbox)],
            captions=[TableCaptionMatchInput(id=caption.id, bbox=caption.bbox)],
        )
        compatible_relations = match_table_captions([table], [caption])

        self.assertEqual(1, len(pure_matches))
        self.assertEqual(compatible_relations[0].start_id, pure_matches[0].table_id)
        self.assertEqual(compatible_relations[0].end_id, pure_matches[0].table_caption_id)
        self.assertEqual(10.0, pure_matches[0].distance)

    def test_pure_matcher_uses_same_stable_tie_breaker(self):
        from drawing_graph.caption_matching import TableCaptionMatchInput, match_table_caption_inputs

        later_table = make_element("table:b", "table", {"x_min": 90, "y_min": 0, "x_max": 110, "y_max": 20})
        earlier_table = make_element("table:a", "table", {"x_min": 0, "y_min": 0, "x_max": 20, "y_max": 20})
        caption = make_element(
            "caption:center",
            "table caption",
            {"x_min": 50, "y_min": 0, "x_max": 60, "y_max": 20},
        )

        matches = match_table_caption_inputs(
            tables=[
                TableCaptionMatchInput(id=later_table.id, bbox=later_table.bbox),
                TableCaptionMatchInput(id=earlier_table.id, bbox=earlier_table.bbox),
            ],
            captions=[TableCaptionMatchInput(id=caption.id, bbox=caption.bbox)],
        )

        self.assertEqual("table:a", matches[0].table_id)

    def test_single_table_matches_single_caption(self):
        from drawing_graph.caption_matching import match_table_captions

        table = make_element("table:a", "table", {"x_min": 10, "y_min": 10, "x_max": 100, "y_max": 100})
        caption = make_element(
            "caption:a",
            "table caption",
            {"x_min": 10, "y_min": 110, "x_max": 100, "y_max": 130},
        )

        relations = match_table_captions([table], [caption])

        self.assertEqual(1, len(relations))
        self.assertEqual("table:a", relations[0].start_id)
        self.assertEqual("caption:a", relations[0].end_id)
        self.assertEqual("HAS_CAPTION", relations[0].relation_type)

    def test_multiple_tables_choose_minimum_bbox_distance(self):
        from drawing_graph.caption_matching import match_table_captions

        far_table = make_element("table:far", "table", {"x_min": 300, "y_min": 10, "x_max": 400, "y_max": 100})
        near_table = make_element("table:near", "table", {"x_min": 10, "y_min": 10, "x_max": 100, "y_max": 100})
        caption = make_element(
            "caption:a",
            "table caption",
            {"x_min": 10, "y_min": 112, "x_max": 100, "y_max": 132},
        )

        relations = match_table_captions([far_table, near_table], [caption])

        self.assertEqual("table:near", relations[0].start_id)

    def test_multiple_captions_each_get_at_most_one_relation(self):
        from drawing_graph.caption_matching import match_table_captions

        first_table = make_element("table:first", "table", {"x_min": 0, "y_min": 0, "x_max": 100, "y_max": 100})
        second_table = make_element("table:second", "table", {"x_min": 300, "y_min": 0, "x_max": 400, "y_max": 100})
        first_caption = make_element(
            "caption:first",
            "table caption",
            {"x_min": 0, "y_min": 110, "x_max": 100, "y_max": 130},
        )
        second_caption = make_element(
            "caption:second",
            "table caption",
            {"x_min": 300, "y_min": 110, "x_max": 400, "y_max": 130},
        )

        relations = match_table_captions([first_table, second_table], [first_caption, second_caption])

        self.assertEqual(2, len(relations))
        self.assertEqual({("table:first", "caption:first"), ("table:second", "caption:second")}, {
            (relation.start_id, relation.end_id) for relation in relations
        })

    def test_equal_distance_uses_table_id_lexical_order(self):
        from drawing_graph.caption_matching import match_table_captions

        later_table = make_element("table:b", "table", {"x_min": 90, "y_min": 0, "x_max": 110, "y_max": 20})
        earlier_table = make_element("table:a", "table", {"x_min": 0, "y_min": 0, "x_max": 20, "y_max": 20})
        caption = make_element(
            "caption:center",
            "table caption",
            {"x_min": 50, "y_min": 0, "x_max": 60, "y_max": 20},
        )

        relations = match_table_captions([later_table, earlier_table], [caption])

        self.assertEqual("table:a", relations[0].start_id)

    def test_missing_tables_returns_classified_exception(self):
        from drawing_graph.caption_matching import CaptionMatchingError, match_table_captions

        caption = make_element(
            "caption:a",
            "table caption",
            {"x_min": 10, "y_min": 110, "x_max": 100, "y_max": 130},
        )

        with self.assertRaises(CaptionMatchingError) as context:
            match_table_captions([], [caption])

        self.assertEqual("missing_table", context.exception.category)

    def test_one_table_can_receive_multiple_caption_relations(self):
        from drawing_graph.caption_matching import match_table_captions

        table = make_element("table:a", "table", {"x_min": 10, "y_min": 10, "x_max": 100, "y_max": 100})
        first_caption = make_element(
            "caption:first",
            "table caption",
            {"x_min": 10, "y_min": 110, "x_max": 100, "y_max": 130},
        )
        second_caption = make_element(
            "caption:second",
            "table caption",
            {"x_min": 110, "y_min": 10, "x_max": 130, "y_max": 100},
        )

        relations = match_table_captions([table], [first_caption, second_caption])

        self.assertEqual(2, len(relations))
        self.assertEqual(["table:a", "table:a"], [relation.start_id for relation in relations])

    def test_rejects_non_table_inputs(self):
        from drawing_graph.caption_matching import CaptionMatchingError, match_table_captions

        block = make_element("block:a", "block", {"x_min": 10, "y_min": 10, "x_max": 100, "y_max": 100})
        caption = make_element(
            "caption:a",
            "table caption",
            {"x_min": 10, "y_min": 110, "x_max": 100, "y_max": 130},
        )

        with self.assertRaises(CaptionMatchingError) as context:
            match_table_captions([block], [caption])

        self.assertEqual("invalid_table_label", context.exception.category)

    def test_rejects_non_table_caption_inputs(self):
        from drawing_graph.caption_matching import CaptionMatchingError, match_table_captions

        table = make_element("table:a", "table", {"x_min": 10, "y_min": 10, "x_max": 100, "y_max": 100})
        block_caption = make_element(
            "caption:a",
            "block caption",
            {"x_min": 10, "y_min": 110, "x_max": 100, "y_max": 130},
        )

        with self.assertRaises(CaptionMatchingError) as context:
            match_table_captions([table], [block_caption])

        self.assertEqual("invalid_caption_label", context.exception.category)


if __name__ == "__main__":
    unittest.main()
