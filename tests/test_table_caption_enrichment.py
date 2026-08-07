import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def make_bbox(x_min, y_min, x_max, y_max):
    from drawing_graph.models import BBox

    return BBox(x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max)


def element(element_id, page_id="page:1", bbox=None):
    from drawing_graph.block_relation_enrichment import PageElementSnapshot

    return PageElementSnapshot(
        id=element_id,
        page_id=page_id,
        bbox=bbox or make_bbox(0, 0, 10, 10),
    )


def scope():
    from drawing_graph.block_relation_enrichment import EnrichmentScope

    return EnrichmentScope(project_id="project:road", relation_batch_id="batch:1", rule_version="v1")


def page(**overrides):
    from drawing_graph.block_relation_enrichment import PageRelationSnapshot

    values = {"page_id": "page:1", "drawing_set_id": "set:1", "page_number": 1}
    values.update(overrides)
    return PageRelationSnapshot(**values)


class TableCaptionEnrichmentTest(unittest.TestCase):
    def test_single_table_matches_single_table_caption(self):
        from drawing_graph.block_relation_enrichment import (
            TABLE_CAPTION_BBOX_DISTANCE_LINK_RULE,
            enrich_table_captions,
        )

        result = enrich_table_captions(
            scope(),
            page(
                tables=[element("table:1", bbox=make_bbox(10, 10, 100, 100))],
                table_captions=[element("table-caption:1", bbox=make_bbox(10, 110, 100, 130))],
            ),
        )

        self.assertEqual(1, len(result.relations))
        relation = result.relations[0]
        self.assertEqual("table_caption", relation.relation_spec)
        self.assertEqual("HAS_CAPTION", relation.relation_type)
        self.assertEqual("table:1", relation.start_id)
        self.assertEqual("table-caption:1", relation.end_id)
        self.assertEqual(TABLE_CAPTION_BBOX_DISTANCE_LINK_RULE, relation.link_rule)
        self.assertEqual(10.0, relation.properties["distance"])
        self.assertEqual(1, result.stats.table_count)
        self.assertEqual(1, result.stats.table_caption_count)
        self.assertEqual(1, result.stats.table_caption_relation_count)

    def test_multiple_tables_choose_nearest_with_stable_tie_breaker(self):
        from drawing_graph.block_relation_enrichment import enrich_table_captions

        result = enrich_table_captions(
            scope(),
            page(
                tables=[
                    element("table:b", bbox=make_bbox(90, 0, 110, 20)),
                    element("table:a", bbox=make_bbox(0, 0, 20, 20)),
                ],
                table_captions=[element("table-caption:center", bbox=make_bbox(50, 0, 60, 20))],
            ),
        )

        self.assertEqual("table:a", result.relations[0].start_id)

    def test_missing_table_records_warning_without_exception(self):
        from drawing_graph.block_relation_enrichment import enrich_table_captions

        result = enrich_table_captions(
            scope(),
            page(table_captions=[element("table-caption:1", bbox=make_bbox(10, 110, 100, 130))]),
        )

        self.assertEqual((), result.relations)
        self.assertEqual(1, len(result.issues))
        self.assertEqual("table_caption_missing_table", result.issues[0].category)
        self.assertEqual("warning", result.issues[0].severity)
        self.assertEqual(0, result.stats.table_count)
        self.assertEqual(1, result.stats.table_caption_count)

    def test_elements_from_other_pages_do_not_participate(self):
        from drawing_graph.block_relation_enrichment import enrich_table_captions

        result = enrich_table_captions(
            scope(),
            page(
                tables=[
                    element("table:other", page_id="page:2", bbox=make_bbox(0, 0, 20, 20)),
                    element("table:current", bbox=make_bbox(100, 0, 120, 20)),
                ],
                table_captions=[
                    element("table-caption:other", page_id="page:2", bbox=make_bbox(0, 30, 20, 50)),
                    element("table-caption:current", bbox=make_bbox(100, 30, 120, 50)),
                ],
            ),
        )

        self.assertEqual(1, len(result.relations))
        self.assertEqual("table:current", result.relations[0].start_id)
        self.assertEqual("table-caption:current", result.relations[0].end_id)
        self.assertEqual(1, result.stats.table_count)
        self.assertEqual(1, result.stats.table_caption_count)


if __name__ == "__main__":
    unittest.main()
