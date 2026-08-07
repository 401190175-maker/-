import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def bbox(x_min=10, y_min=20, x_max=110, y_max=120):
    from drawing_graph.models import BBox

    return BBox(x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max)


def element(element_id, page_id="page:road:set-a:road_24", values=None):
    from drawing_graph.block_relation_enrichment import PageElementSnapshot

    return PageElementSnapshot(id=element_id, page_id=page_id, bbox=bbox(*(values or (10, 20, 110, 120))))


def scope():
    from drawing_graph.block_relation_enrichment import EnrichmentScope

    return EnrichmentScope(project_id="project:road", relation_batch_id="relation-batch:001", rule_version="v1")


def page_snapshot(
    page_number=24,
    *,
    blocks=(),
    captions=(),
    tables=(),
    table_captions=(),
    basic_infos=(),
    annotations=(),
    cross_sections=(),
    drawing_set_id="set:road:set-a",
):
    from drawing_graph.block_relation_enrichment import PageRelationSnapshot

    drawing_set_slug = drawing_set_id.split(":")[-1]
    page_id = f"page:road:{drawing_set_slug}:road_{page_number}"
    return PageRelationSnapshot(
        page_id=page_id,
        drawing_set_id=drawing_set_id,
        page_number=page_number,
        blocks=blocks,
        captions=captions,
        tables=tables,
        table_captions=table_captions,
        basic_infos=basic_infos,
        annotations=annotations,
        cross_sections=cross_sections,
    )


class EnrichPageRelationsTest(unittest.TestCase):
    def test_generates_caption_basic_info_and_annotation_relations_for_one_page(self):
        from drawing_graph.block_relation_enrichment import enrich_page_relations

        page_id = "page:road:set-a:road_24"
        block = element("block:1", page_id, (50, 100, 90, 140))
        caption = element("caption:1", page_id, (50, 70, 90, 80))
        basic_info = element("basic-info:1", page_id)
        annotation = element("annotation:1", page_id)
        page = page_snapshot(
            blocks=[block],
            captions=[caption],
            basic_infos=[basic_info],
            annotations=[annotation],
        )

        result = enrich_page_relations(scope(), page)

        self.assertEqual(
            {
                ("block:1", "caption:1", "HAS_CAPTION"),
                ("page:road:set-a:road_24", "basic-info:1", "USES_BASIC_INFO"),
                ("block:1", "annotation:1", "HAS_ANNOTATION"),
            },
            {(relation.start_id, relation.end_id, relation.relation_type) for relation in result.relations},
        )
        self.assertEqual(1, result.stats.page_count)
        self.assertEqual(1, result.stats.block_count)
        self.assertEqual(1, result.stats.caption_count)
        self.assertEqual(1, result.stats.basic_info_count)
        self.assertEqual(1, result.stats.annotation_count)
        self.assertEqual(1, result.stats.uses_basic_info_count)
        self.assertEqual(3, result.stats.relation_count)

    def test_page_without_blocks_still_generates_table_caption_relations(self):
        from drawing_graph.block_relation_enrichment import enrich_page_relations

        page_id = "page:road:set-a:road_24"
        table = element("table:1", page_id, (10, 10, 100, 100))
        table_caption = element("table-caption:1", page_id, (10, 110, 100, 130))
        page = page_snapshot(tables=[table], table_captions=[table_caption])

        result = enrich_page_relations(scope(), page)

        self.assertEqual(
            {("table:1", "table-caption:1", "table_caption", "HAS_CAPTION")},
            {
                (relation.start_id, relation.end_id, relation.relation_spec, relation.relation_type)
                for relation in result.relations
            },
        )
        self.assertEqual(0, result.stats.block_count)
        self.assertEqual(1, result.stats.table_count)
        self.assertEqual(1, result.stats.table_caption_count)
        self.assertEqual(1, result.stats.table_caption_relation_count)
        self.assertEqual(1, result.stats.relation_count)

    def test_combines_block_and_table_caption_relations(self):
        from drawing_graph.block_relation_enrichment import enrich_page_relations

        page_id = "page:road:set-a:road_24"
        block = element("block:1", page_id, (50, 100, 90, 140))
        caption = element("caption:1", page_id, (50, 70, 90, 80))
        table = element("table:1", page_id, (10, 10, 100, 100))
        table_caption = element("table-caption:1", page_id, (10, 110, 100, 130))
        page = page_snapshot(blocks=[block], captions=[caption], tables=[table], table_captions=[table_caption])

        result = enrich_page_relations(scope(), page, previous_page_context_available=False)

        self.assertEqual(
            {("block:1", "caption:1", "block_caption"), ("table:1", "table-caption:1", "table_caption")},
            {(relation.start_id, relation.end_id, relation.relation_spec) for relation in result.relations},
        )
        self.assertEqual(1, result.stats.table_caption_relation_count)
        self.assertEqual(2, result.stats.relation_count)

    def test_generates_partial_relations_when_only_some_page_elements_exist(self):
        from drawing_graph.block_relation_enrichment import enrich_page_relations

        page_id = "page:road:set-a:road_24"
        block = element("block:1", page_id)
        annotation = element("annotation:1", page_id)
        page = page_snapshot(blocks=[block], annotations=[annotation])

        result = enrich_page_relations(scope(), page, previous_page_context_available=False)

        self.assertEqual(
            {("block:1", "annotation:1", "HAS_ANNOTATION")},
            {(relation.start_id, relation.end_id, relation.relation_type) for relation in result.relations},
        )
        self.assertEqual(["basic_info_not_evaluated"], [issue.category for issue in result.issues])
        self.assertEqual(1, result.stats.block_count)
        self.assertEqual(0, result.stats.caption_count)
        self.assertEqual(0, result.stats.basic_info_count)
        self.assertEqual(1, result.stats.annotation_count)
        self.assertEqual(1, result.stats.relation_count)
        self.assertEqual(1, result.stats.not_evaluated_count)
        self.assertEqual(1, result.stats.warning_count)

    def test_page_without_blocks_returns_empty_summary_without_caption_warnings(self):
        from drawing_graph.block_relation_enrichment import enrich_page_relations

        page_id = "page:road:set-a:road_24"
        caption = element("caption:orphan", page_id)
        basic_info = element("basic-info:1", page_id)
        annotation = element("annotation:1", page_id)
        page = page_snapshot(captions=[caption], basic_infos=[basic_info], annotations=[annotation])

        result = enrich_page_relations(scope(), page)

        self.assertEqual((), result.relations)
        self.assertEqual((), result.issues)
        self.assertEqual(0, result.stats.block_count)
        self.assertEqual(1, result.stats.caption_count)
        self.assertEqual(1, result.stats.basic_info_count)
        self.assertEqual(1, result.stats.annotation_count)
        self.assertEqual(0, result.stats.relation_count)

    def test_combines_warnings_from_component_rules(self):
        from drawing_graph.block_relation_enrichment import enrich_page_relations

        page_id = "page:road:set-a:road_24"
        block = element("block:1", page_id, (50, 100, 90, 140))
        near_caption = element("caption:near", page_id, (50, 70, 90, 80))
        far_caption = element("caption:far", page_id, (50, 10, 90, 20))
        page = page_snapshot(blocks=[block], captions=[far_caption, near_caption])

        result = enrich_page_relations(scope(), page, previous_page_context_available=False)

        self.assertEqual(
            ["caption_candidate_ambiguous", "basic_info_not_evaluated"],
            [issue.category for issue in result.issues],
        )
        self.assertEqual(2, result.stats.warning_count)
        self.assertEqual(0, result.stats.error_count)

    def test_deduplicates_same_rule_version_candidate_relations(self):
        from drawing_graph.block_relation_enrichment import enrich_page_relations

        page_id = "page:road:set-a:road_24"
        duplicate_block = element("block:1", page_id)
        duplicate_caption = element("caption:1", page_id, (50, 70, 90, 80))
        page = page_snapshot(
            blocks=[duplicate_block, duplicate_block],
            captions=[duplicate_caption, duplicate_caption],
        )

        result = enrich_page_relations(scope(), page, previous_page_context_available=False)

        self.assertEqual(1, len(result.relations))
        self.assertEqual("block:1", result.relations[0].start_id)
        self.assertEqual("caption:1", result.relations[0].end_id)
        self.assertEqual("HAS_CAPTION", result.relations[0].relation_type)

    def test_includes_cross_section_relations_and_stats_in_page_summary(self):
        from drawing_graph.block_relation_enrichment import enrich_page_relations

        page_id = "page:road:set-a:road_24"
        block = element("block:1", page_id, (0, 0, 100, 100))
        cross_section = element("cross-section:1", page_id, (10, 20, 30, 40))
        page = page_snapshot(blocks=[block], cross_sections=[cross_section])

        result = enrich_page_relations(scope(), page, previous_page_context_available=False)

        self.assertIn(
            ("block:1", "cross-section:1", "HAS_SECTION_MARK"),
            {(relation.start_id, relation.end_id, relation.relation_type) for relation in result.relations},
        )
        self.assertEqual(1, result.stats.cross_section_count)
        self.assertEqual(1, result.stats.relation_count)

    def test_includes_cross_section_warnings_in_page_summary(self):
        from drawing_graph.block_relation_enrichment import enrich_page_relations

        page_id = "page:road:set-a:road_24"
        first_block = element("block:a-first", page_id, (0, 0, 100, 100))
        second_block = element("block:z-second", page_id, (0, 0, 100, 100))
        basic_info = element("basic-info:1", page_id)
        cross_section = element("cross-section:1", page_id, (10, 20, 30, 40))
        page = page_snapshot(blocks=[first_block, second_block], basic_infos=[basic_info], cross_sections=[cross_section])

        result = enrich_page_relations(scope(), page, previous_page_context_available=False)

        self.assertIn("section_candidate_ambiguous", [issue.category for issue in result.issues])
        self.assertEqual(1, result.stats.cross_section_count)
        self.assertEqual(1, result.stats.warning_count)
        self.assertIn(
            ("page:road:set-a:road_24", "basic-info:1", "USES_BASIC_INFO"),
            {(relation.start_id, relation.end_id, relation.relation_type) for relation in result.relations},
        )
        self.assertEqual(2, result.stats.candidate_count)


if __name__ == "__main__":
    unittest.main()
