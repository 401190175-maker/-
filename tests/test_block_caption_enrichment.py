import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def bbox(x_min, y_min, x_max, y_max):
    from drawing_graph.models import BBox

    return BBox(x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max)


def element(element_id, page_id, values):
    from drawing_graph.block_relation_enrichment import PageElementSnapshot

    return PageElementSnapshot(id=element_id, page_id=page_id, bbox=bbox(*values))


def scope():
    from drawing_graph.block_relation_enrichment import EnrichmentScope

    return EnrichmentScope(project_id="project:road", relation_batch_id="relation-batch:001", rule_version="v1")


def page_snapshot(blocks, captions, page_id="page:road:set-a:road_24"):
    from drawing_graph.block_relation_enrichment import PageRelationSnapshot

    return PageRelationSnapshot(
        page_id=page_id,
        drawing_set_id="set:road:set-a",
        page_number=24,
        blocks=blocks,
        captions=captions,
    )


class BlockCaptionEnrichmentTest(unittest.TestCase):
    def test_caption_matches_nearest_block_below_by_center_distance(self):
        from drawing_graph.block_relation_enrichment import enrich_block_captions

        caption = element("caption:1", "page:road:set-a:road_24", (40, 20, 60, 30))
        far_below = element("block:far", "page:road:set-a:road_24", (180, 80, 220, 120))
        near_below = element("block:near", "page:road:set-a:road_24", (45, 60, 65, 80))

        result = enrich_block_captions(scope(), page_snapshot([far_below, near_below], [caption]))

        self.assertEqual(1, len(result.relations))
        self.assertEqual("block:near", result.relations[0].start_id)
        self.assertEqual("caption:1", result.relations[0].end_id)
        self.assertEqual("HAS_CAPTION", result.relations[0].relation_type)
        self.assertEqual("below", result.relations[0].properties["match_direction"])
        self.assertAlmostEqual(45.276926, result.relations[0].properties["distance"], places=6)

    def test_caption_prefers_below_block_over_closer_above_block(self):
        from drawing_graph.block_relation_enrichment import enrich_block_captions

        caption = element("caption:1", "page:road:set-a:road_24", (50, 50, 70, 70))
        closer_above = element("block:above", "page:road:set-a:road_24", (55, 35, 65, 45))
        farther_below = element("block:below", "page:road:set-a:road_24", (50, 120, 70, 140))

        result = enrich_block_captions(scope(), page_snapshot([closer_above, farther_below], [caption]))

        self.assertEqual("block:below", result.relations[0].start_id)
        self.assertEqual("below", result.relations[0].properties["match_direction"])

    def test_caption_matches_above_when_no_block_below_exists(self):
        from drawing_graph.block_relation_enrichment import enrich_block_captions

        caption = element("caption:1", "page:road:set-a:road_24", (50, 100, 70, 120))
        above = element("block:above", "page:road:set-a:road_24", (50, 40, 70, 60))

        result = enrich_block_captions(scope(), page_snapshot([above], [caption]))

        self.assertEqual("block:above", result.relations[0].start_id)
        self.assertEqual("above", result.relations[0].properties["match_direction"])

    def test_each_caption_produces_at_most_one_relation(self):
        from drawing_graph.block_relation_enrichment import enrich_block_captions

        caption = element("caption:1", "page:road:set-a:road_24", (50, 20, 70, 40))
        first_block = element("block:first", "page:road:set-a:road_24", (50, 80, 70, 100))
        second_block = element("block:second", "page:road:set-a:road_24", (90, 80, 110, 100))

        result = enrich_block_captions(scope(), page_snapshot([first_block, second_block], [caption]))

        self.assertEqual(1, len(result.relations))
        self.assertEqual("caption:1", result.relations[0].end_id)

    def test_near_equal_block_candidates_are_persisted_without_formal_caption_fact(self):
        from drawing_graph.block_relation_enrichment import enrich_block_captions

        caption = element("caption:1", "page:road:set-a:road_24", (50, 20, 70, 40))
        first_block = element("block:first", "page:road:set-a:road_24", (40, 80, 60, 100))
        second_block = element("block:second", "page:road:set-a:road_24", (60, 80, 80, 100))

        result = enrich_block_captions(scope(), page_snapshot([first_block, second_block], [caption]))

        self.assertEqual(
            {
                ("caption:1", "block:first", "candidate_caption_of", "CANDIDATE_CAPTION_OF"),
                ("caption:1", "block:second", "candidate_caption_of", "CANDIDATE_CAPTION_OF"),
            },
            {
                (relation.start_id, relation.end_id, relation.relation_spec, relation.relation_type)
                for relation in result.relations
            },
        )
        self.assertEqual(["caption_candidate_ambiguous"], [issue.category for issue in result.issues])
        self.assertEqual(2, result.stats.candidate_count)
        self.assertEqual(1, result.stats.ambiguous_count)

    def test_conflicting_captions_create_candidates_and_record_issue(self):
        from drawing_graph.block_relation_enrichment import enrich_block_captions

        block = element("block:shared", "page:road:set-a:road_24", (50, 100, 90, 140))
        near_caption = element("caption:near", "page:road:set-a:road_24", (50, 70, 90, 80))
        far_caption = element("caption:far", "page:road:set-a:road_24", (50, 10, 90, 20))

        result = enrich_block_captions(scope(), page_snapshot([block], [far_caption, near_caption]))

        self.assertEqual(
            {
                ("caption:far", "block:shared", "CANDIDATE_CAPTION_OF"),
                ("caption:near", "block:shared", "CANDIDATE_CAPTION_OF"),
            },
            {(relation.start_id, relation.end_id, relation.relation_type) for relation in result.relations},
        )
        self.assertEqual(["caption_candidate_ambiguous"], [issue.category for issue in result.issues])
        self.assertEqual("block:shared", result.issues[0].element_id)
        self.assertEqual(2, result.stats.candidate_count)

    def test_unmatched_caption_records_classified_warning(self):
        from drawing_graph.block_relation_enrichment import enrich_block_captions

        caption = element("caption:orphan", "page:road:set-a:road_24", (50, 20, 70, 40))

        result = enrich_block_captions(scope(), page_snapshot([], [caption]))

        self.assertEqual((), result.relations)
        self.assertEqual(1, len(result.issues))
        self.assertEqual("caption_candidate_not_found", result.issues[0].category)
        self.assertEqual("warning", result.issues[0].severity)
        self.assertEqual("caption:orphan", result.issues[0].element_id)

    def test_elements_from_other_pages_do_not_participate(self):
        from drawing_graph.block_relation_enrichment import enrich_block_captions

        caption = element("caption:1", "page:road:set-a:road_24", (50, 20, 70, 40))
        other_page_block = element("block:other-page", "page:road:set-a:road_25", (50, 80, 70, 100))
        same_page_block = element("block:same-page", "page:road:set-a:road_24", (50, 120, 70, 140))

        result = enrich_block_captions(scope(), page_snapshot([other_page_block, same_page_block], [caption]))

        self.assertEqual(1, len(result.relations))
        self.assertEqual("block:same-page", result.relations[0].start_id)


if __name__ == "__main__":
    unittest.main()
