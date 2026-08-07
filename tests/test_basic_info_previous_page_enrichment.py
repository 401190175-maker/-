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


def element(element_id, page_id, properties=None):
    from drawing_graph.block_relation_enrichment import PageElementSnapshot

    return PageElementSnapshot(id=element_id, page_id=page_id, bbox=bbox(), properties=properties or {})


def scope():
    from drawing_graph.block_relation_enrichment import EnrichmentScope

    return EnrichmentScope(project_id="project:road", relation_batch_id="relation-batch:001", rule_version="v1")


def page_snapshot(page_number, blocks=(), basic_infos=(), drawing_set_id="set:road:set-a"):
    from drawing_graph.block_relation_enrichment import PageRelationSnapshot

    drawing_set_slug = drawing_set_id.split(":")[-1]
    page_id = f"page:road:{drawing_set_slug}:road_{page_number}"
    return PageRelationSnapshot(
        page_id=page_id,
        drawing_set_id=drawing_set_id,
        page_number=page_number,
        blocks=blocks,
        basic_infos=basic_infos,
    )


class BasicInfoPreviousPageEnrichmentTest(unittest.TestCase):
    def test_previous_page_basic_info_context_returns_partial_without_formal_inheritance(self):
        from drawing_graph.block_relation_enrichment import enrich_previous_page_basic_infos

        current_page_id = "page:road:set-a:road_24"
        previous_page_id = "page:road:set-a:road_23"
        first_block = element("block:1", current_page_id)
        second_block = element("block:2", current_page_id)
        first_basic_info = element("basic-info:1", previous_page_id)
        second_basic_info = element("basic-info:2", previous_page_id)
        current_page = page_snapshot(24, blocks=[first_block, second_block])
        previous_page = page_snapshot(23, basic_infos=[first_basic_info, second_basic_info])

        result = enrich_previous_page_basic_infos(scope(), current_page, previous_page)

        self.assertEqual((), result.relations)
        self.assertEqual(["basic_info_partial"], [issue.category for issue in result.issues])
        self.assertEqual(2, result.stats.block_count)
        self.assertEqual(2, result.stats.basic_info_count)
        self.assertEqual(0, result.stats.relation_count)
        self.assertEqual(1, result.stats.not_evaluated_count)

    def test_conflicting_previous_page_basic_info_anchors_return_ambiguous_context(self):
        from drawing_graph.block_relation_enrichment import enrich_previous_page_basic_infos

        current_page_id = "page:road:set-a:road_24"
        previous_page_id = "page:road:set-a:road_23"
        block = element("block:1", current_page_id)
        first_basic_info = element("basic-info:1", previous_page_id, {"anchor_group_id": "anchor:start"})
        second_basic_info = element("basic-info:2", previous_page_id, {"anchor_group_id": "anchor:end"})
        current_page = page_snapshot(24, blocks=[block])
        previous_page = page_snapshot(23, basic_infos=[first_basic_info, second_basic_info])

        result = enrich_previous_page_basic_infos(scope(), current_page, previous_page)

        self.assertEqual((), result.relations)
        self.assertEqual(["basic_info_ambiguous"], [issue.category for issue in result.issues])
        self.assertEqual(2, result.stats.basic_info_count)
        self.assertEqual(0, result.stats.relation_count)
        self.assertEqual(1, result.stats.ambiguous_count)

    def test_current_page_basic_info_prevents_previous_page_inheritance(self):
        from drawing_graph.block_relation_enrichment import enrich_previous_page_basic_infos

        current_page_id = "page:road:set-a:road_24"
        previous_page_id = "page:road:set-a:road_23"
        block = element("block:1", current_page_id)
        current_basic_info = element("basic-info:current", current_page_id)
        previous_basic_info = element("basic-info:previous", previous_page_id)
        current_page = page_snapshot(24, blocks=[block], basic_infos=[current_basic_info])
        previous_page = page_snapshot(23, basic_infos=[previous_basic_info])

        result = enrich_previous_page_basic_infos(scope(), current_page, previous_page)

        self.assertEqual((), result.relations)
        self.assertEqual((), result.issues)
        self.assertEqual(1, result.stats.block_count)
        self.assertEqual(1, result.stats.basic_info_count)
        self.assertEqual(0, result.stats.relation_count)

    def test_missing_previous_page_records_previous_page_missing(self):
        from drawing_graph.block_relation_enrichment import enrich_previous_page_basic_infos

        current_page_id = "page:road:set-a:road_24"
        block = element("block:1", current_page_id)
        current_page = page_snapshot(24, blocks=[block])

        result = enrich_previous_page_basic_infos(scope(), current_page, None)

        self.assertEqual((), result.relations)
        self.assertEqual(["basic_info_not_evaluated"], [issue.category for issue in result.issues])
        self.assertEqual("warning", result.issues[0].severity)
        self.assertEqual(current_page.page_id, result.issues[0].page_id)

    def test_single_page_run_without_context_records_previous_page_unavailable(self):
        from drawing_graph.block_relation_enrichment import enrich_previous_page_basic_infos

        current_page_id = "page:road:set-a:road_24"
        block = element("block:1", current_page_id)
        current_page = page_snapshot(24, blocks=[block])

        result = enrich_previous_page_basic_infos(scope(), current_page, None, previous_page_context_available=False)

        self.assertEqual((), result.relations)
        self.assertEqual(["basic_info_not_evaluated"], [issue.category for issue in result.issues])
        self.assertEqual(1, result.stats.not_evaluated_count)

    def test_previous_page_without_basic_info_records_not_found(self):
        from drawing_graph.block_relation_enrichment import enrich_previous_page_basic_infos

        current_page_id = "page:road:set-a:road_24"
        block = element("block:1", current_page_id)
        current_page = page_snapshot(24, blocks=[block])
        previous_page = page_snapshot(23)

        result = enrich_previous_page_basic_infos(scope(), current_page, previous_page)

        self.assertEqual((), result.relations)
        self.assertEqual(["basic_info_not_evaluated"], [issue.category for issue in result.issues])

    def test_does_not_fallback_to_earlier_than_previous_page(self):
        from drawing_graph.block_relation_enrichment import enrich_previous_page_basic_infos

        current_page_id = "page:road:set-a:road_24"
        earlier_page_id = "page:road:set-a:road_22"
        block = element("block:1", current_page_id)
        earlier_basic_info = element("basic-info:too-early", earlier_page_id)
        current_page = page_snapshot(24, blocks=[block])
        earlier_page = page_snapshot(22, basic_infos=[earlier_basic_info])

        result = enrich_previous_page_basic_infos(scope(), current_page, earlier_page)

        self.assertEqual((), result.relations)
        self.assertEqual(["basic_info_not_evaluated"], [issue.category for issue in result.issues])

    def test_different_drawing_set_does_not_inherit(self):
        from drawing_graph.block_relation_enrichment import enrich_previous_page_basic_infos

        current_page_id = "page:road:set-a:road_24"
        other_set_page_id = "page:road:set-b:road_23"
        block = element("block:1", current_page_id)
        other_set_basic_info = element("basic-info:other-set", other_set_page_id)
        current_page = page_snapshot(24, blocks=[block], drawing_set_id="set:road:set-a")
        other_set_previous_page = page_snapshot(
            23,
            basic_infos=[other_set_basic_info],
            drawing_set_id="set:road:set-b",
        )

        result = enrich_previous_page_basic_infos(scope(), current_page, other_set_previous_page)

        self.assertEqual((), result.relations)
        self.assertEqual(["basic_info_not_evaluated"], [issue.category for issue in result.issues])


if __name__ == "__main__":
    unittest.main()
