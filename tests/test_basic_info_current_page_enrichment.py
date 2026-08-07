import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def bbox():
    from drawing_graph.models import BBox

    return BBox(x_min=10, y_min=20, x_max=110, y_max=120)


def element(element_id, page_id="page:road:set-a:road_24"):
    from drawing_graph.block_relation_enrichment import PageElementSnapshot

    return PageElementSnapshot(id=element_id, page_id=page_id, bbox=bbox())


def scope():
    from drawing_graph.block_relation_enrichment import EnrichmentScope

    return EnrichmentScope(project_id="project:road", relation_batch_id="relation-batch:001", rule_version="v1")


def page_snapshot(blocks, basic_infos, page_id="page:road:set-a:road_24"):
    from drawing_graph.block_relation_enrichment import PageRelationSnapshot

    return PageRelationSnapshot(
        page_id=page_id,
        drawing_set_id="set:road:set-a",
        page_number=24,
        blocks=blocks,
        basic_infos=basic_infos,
    )


class BasicInfoCurrentPageEnrichmentTest(unittest.TestCase):
    def test_current_page_with_blocks_uses_multiple_current_page_basic_infos(self):
        from drawing_graph.block_relation_enrichment import enrich_current_page_basic_infos

        block = element("block:1")
        first_basic_info = element("basic-info:1")
        second_basic_info = element("basic-info:2")

        result = enrich_current_page_basic_infos(scope(), page_snapshot([block], [first_basic_info, second_basic_info]))

        self.assertEqual(
            {("page:road:set-a:road_24", "basic-info:1"), ("page:road:set-a:road_24", "basic-info:2")},
            {(relation.start_id, relation.end_id) for relation in result.relations},
        )
        self.assertEqual({"USES_BASIC_INFO"}, {relation.relation_type for relation in result.relations})
        self.assertEqual({"page_uses_basic_info"}, {relation.relation_spec for relation in result.relations})
        self.assertEqual(
            {"current_page"},
            {relation.properties["source"] for relation in result.relations},
        )
        self.assertEqual({"confirmed"}, {relation.properties["status"] for relation in result.relations})
        self.assertNotIn("distance", result.relations[0].properties)

    def test_multiple_blocks_do_not_fan_out_current_page_basic_info(self):
        from drawing_graph.block_relation_enrichment import enrich_current_page_basic_infos

        first_block = element("block:1")
        second_block = element("block:2")
        basic_info = element("basic-info:1")

        result = enrich_current_page_basic_infos(scope(), page_snapshot([first_block, second_block], [basic_info]))

        self.assertEqual(
            {("page:road:set-a:road_24", "basic-info:1")},
            {(relation.start_id, relation.end_id) for relation in result.relations},
        )
        self.assertEqual(2, result.stats.block_count)
        self.assertEqual(1, result.stats.basic_info_count)
        self.assertEqual(1, result.stats.uses_basic_info_count)
        self.assertEqual(1, result.stats.relation_count)

    def test_page_without_blocks_returns_empty_result_status(self):
        from drawing_graph.block_relation_enrichment import enrich_current_page_basic_infos

        basic_info = element("basic-info:1")

        result = enrich_current_page_basic_infos(scope(), page_snapshot([], [basic_info]))

        self.assertEqual((), result.relations)
        self.assertEqual((), result.issues)
        self.assertEqual(0, result.stats.block_count)
        self.assertEqual(1, result.stats.basic_info_count)
        self.assertEqual(0, result.stats.uses_basic_info_count)
        self.assertEqual(0, result.stats.relation_count)

    def test_page_without_basic_info_does_not_read_previous_page(self):
        from drawing_graph.block_relation_enrichment import enrich_current_page_basic_infos

        block = element("block:1")

        result = enrich_current_page_basic_infos(scope(), page_snapshot([block], []))

        self.assertEqual((), result.relations)
        self.assertEqual((), result.issues)
        self.assertEqual(1, result.stats.block_count)
        self.assertEqual(0, result.stats.basic_info_count)
        self.assertEqual(0, result.stats.uses_basic_info_count)
        self.assertEqual(0, result.stats.relation_count)

    def test_elements_from_other_pages_do_not_participate(self):
        from drawing_graph.block_relation_enrichment import enrich_current_page_basic_infos

        same_page_block = element("block:same-page")
        other_page_block = element("block:other-page", page_id="page:road:set-a:road_25")
        same_page_basic_info = element("basic-info:same-page")
        other_page_basic_info = element("basic-info:other-page", page_id="page:road:set-a:road_25")

        result = enrich_current_page_basic_infos(
            scope(),
            page_snapshot([same_page_block, other_page_block], [same_page_basic_info, other_page_basic_info]),
        )

        self.assertEqual(1, len(result.relations))
        self.assertEqual("page:road:set-a:road_24", result.relations[0].start_id)
        self.assertEqual("basic-info:same-page", result.relations[0].end_id)
        self.assertEqual("USES_BASIC_INFO", result.relations[0].relation_type)


if __name__ == "__main__":
    unittest.main()
