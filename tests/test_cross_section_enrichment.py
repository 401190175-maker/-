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


def page_snapshot(page_id, *, blocks=(), cross_sections=()):
    from drawing_graph.block_relation_enrichment import PageRelationSnapshot

    return PageRelationSnapshot(
        page_id=page_id,
        drawing_set_id="set:road:set-a",
        page_number=24,
        blocks=blocks,
        cross_sections=cross_sections,
    )


class CrossSectionEnrichmentTest(unittest.TestCase):
    def test_contained_cross_section_creates_section_mark_relation(self):
        from drawing_graph.block_relation_enrichment import (
            CROSS_SECTION_GEOMETRY_OWNERSHIP_LINK_RULE,
            enrich_cross_sections,
        )

        page_id = "page:road:set-a:road_24"
        block = element("block:1", page_id, (0, 0, 100, 100))
        cross_section = element("cross-section:1", page_id, (10, 20, 30, 40))
        page = page_snapshot(page_id, blocks=[block], cross_sections=[cross_section])

        result = enrich_cross_sections(scope(), page)

        self.assertEqual(1, len(result.relations))
        relation = result.relations[0]
        self.assertEqual("block:1", relation.start_id)
        self.assertEqual("cross-section:1", relation.end_id)
        self.assertEqual("HAS_SECTION_MARK", relation.relation_type)
        self.assertEqual("relation-batch:001", relation.properties["relation_batch_id"])
        self.assertEqual("v1", relation.properties["rule_version"])
        self.assertEqual(CROSS_SECTION_GEOMETRY_OWNERSHIP_LINK_RULE, relation.properties["link_rule"])
        self.assertEqual(400.0, relation.properties["overlap_area"])
        self.assertEqual(1.0, relation.properties["overlap_ratio"])
        self.assertEqual("contained", relation.properties["containment_status"])
        self.assertEqual(1, result.stats.page_count)
        self.assertEqual(1, result.stats.block_count)
        self.assertEqual(1, result.stats.cross_section_count)
        self.assertEqual(1, result.stats.relation_count)

    def test_cross_page_blocks_and_cross_sections_do_not_match(self):
        from drawing_graph.block_relation_enrichment import enrich_cross_sections

        page_id = "page:road:set-a:road_24"
        other_page_id = "page:road:set-a:road_25"
        same_page_block = element("block:1", page_id, (0, 0, 100, 100))
        other_page_block = element("block:other", other_page_id, (0, 0, 100, 100))
        same_page_cross_section = element("cross-section:1", page_id, (10, 20, 30, 40))
        other_page_cross_section = element("cross-section:other", other_page_id, (10, 20, 30, 40))
        page = page_snapshot(
            page_id,
            blocks=[same_page_block, other_page_block],
            cross_sections=[same_page_cross_section, other_page_cross_section],
        )

        result = enrich_cross_sections(scope(), page)

        self.assertEqual(
            [("block:1", "cross-section:1", "HAS_SECTION_MARK")],
            [(relation.start_id, relation.end_id, relation.relation_type) for relation in result.relations],
        )

    def test_multiple_containing_blocks_selects_smallest_area_block(self):
        from drawing_graph.block_relation_enrichment import enrich_cross_sections

        page_id = "page:road:set-a:road_24"
        large_block = element("block:a-large", page_id, (0, 0, 200, 200))
        small_block = element("block:z-small", page_id, (0, 0, 100, 100))
        cross_section = element("cross-section:1", page_id, (10, 20, 30, 40))

        for blocks in ([large_block, small_block], [small_block, large_block]):
            with self.subTest(block_order=[block.id for block in blocks]):
                page = page_snapshot(page_id, blocks=blocks, cross_sections=[cross_section])

                result = enrich_cross_sections(scope(), page)

                self.assertEqual(1, len(result.relations))
                self.assertEqual("block:z-small", result.relations[0].start_id)
                self.assertEqual("cross-section:1", result.relations[0].end_id)

    def test_tied_smallest_containing_blocks_create_candidate_relations(self):
        from drawing_graph.block_relation_enrichment import enrich_cross_sections

        page_id = "page:road:set-a:road_24"
        first_block = element("block:a-first", page_id, (0, 0, 100, 100))
        second_block = element("block:z-second", page_id, (0, 0, 100, 100))
        cross_section = element("cross-section:1", page_id, (10, 20, 30, 40))
        page = page_snapshot(page_id, blocks=[first_block, second_block], cross_sections=[cross_section])

        result = enrich_cross_sections(scope(), page)

        self.assertEqual(
            {
                ("block:a-first", "cross-section:1", "candidate_section_mark", "CANDIDATE_HAS_SECTION_MARK"),
                ("block:z-second", "cross-section:1", "candidate_section_mark", "CANDIDATE_HAS_SECTION_MARK"),
            },
            {
                (relation.start_id, relation.end_id, relation.relation_spec, relation.relation_type)
                for relation in result.relations
            },
        )
        self.assertEqual(1, len(result.issues))
        issue = result.issues[0]
        self.assertEqual("section_candidate_ambiguous", issue.category)
        self.assertEqual("warning", issue.severity)
        self.assertEqual(page_id, issue.page_id)
        self.assertEqual("cross-section:1", issue.element_id)
        self.assertEqual(1, result.stats.warning_count)
        self.assertEqual(2, result.stats.candidate_count)
        self.assertEqual(1, result.stats.ambiguous_count)
        self.assertEqual(2, result.stats.relation_count)

    def test_non_contained_cross_section_selects_largest_overlap_area_block(self):
        from drawing_graph.block_relation_enrichment import enrich_cross_sections

        page_id = "page:road:set-a:road_24"
        small_overlap_block = element("block:a-small-overlap", page_id, (0, 0, 75, 75))
        large_overlap_block = element("block:z-large-overlap", page_id, (25, 25, 125, 125))
        cross_section = element("cross-section:1", page_id, (50, 50, 150, 150))
        page = page_snapshot(
            page_id,
            blocks=[small_overlap_block, large_overlap_block],
            cross_sections=[cross_section],
        )

        result = enrich_cross_sections(scope(), page)

        self.assertEqual(1, len(result.relations))
        relation = result.relations[0]
        self.assertEqual("block:z-large-overlap", relation.start_id)
        self.assertEqual("cross-section:1", relation.end_id)
        self.assertEqual("HAS_SECTION_MARK", relation.relation_type)
        self.assertEqual(5625.0, relation.properties["overlap_area"])
        self.assertEqual(0.5625, relation.properties["overlap_ratio"])
        self.assertEqual("overlapped", relation.properties["containment_status"])

    def test_tied_largest_overlap_blocks_create_candidate_relations(self):
        from drawing_graph.block_relation_enrichment import enrich_cross_sections

        page_id = "page:road:set-a:road_24"
        first_block = element("block:a-first", page_id, (0, 0, 80, 80))
        second_block = element("block:z-second", page_id, (20, 20, 100, 100))
        cross_section = element("cross-section:1", page_id, (0, 0, 100, 100))
        page = page_snapshot(page_id, blocks=[first_block, second_block], cross_sections=[cross_section])

        result = enrich_cross_sections(scope(), page)

        self.assertEqual(
            {
                ("block:a-first", "cross-section:1", "CANDIDATE_HAS_SECTION_MARK"),
                ("block:z-second", "cross-section:1", "CANDIDATE_HAS_SECTION_MARK"),
            },
            {(relation.start_id, relation.end_id, relation.relation_type) for relation in result.relations},
        )
        self.assertEqual(["section_candidate_ambiguous"], [issue.category for issue in result.issues])
        self.assertEqual(page_id, result.issues[0].page_id)
        self.assertEqual("cross-section:1", result.issues[0].element_id)
        self.assertEqual(1, result.stats.warning_count)
        self.assertEqual(2, result.stats.candidate_count)

    def test_near_tied_overlap_ratio_creates_candidate_relations(self):
        from drawing_graph.block_relation_enrichment import enrich_cross_sections

        page_id = "page:road:set-a:road_24"
        best_block = element("block:best", page_id, (0, 0, 80, 80))
        near_block = element("block:near", page_id, (0, 0, 75, 80))
        cross_section = element("cross-section:1", page_id, (0, 0, 100, 100))
        page = page_snapshot(page_id, blocks=[best_block, near_block], cross_sections=[cross_section])

        result = enrich_cross_sections(scope(), page)

        self.assertEqual(
            {
                ("block:best", "cross-section:1", "CANDIDATE_HAS_SECTION_MARK"),
                ("block:near", "cross-section:1", "CANDIDATE_HAS_SECTION_MARK"),
            },
            {(relation.start_id, relation.end_id, relation.relation_type) for relation in result.relations},
        )
        self.assertEqual(["section_candidate_ambiguous"], [issue.category for issue in result.issues])
        self.assertEqual(page_id, result.issues[0].page_id)
        self.assertEqual("cross-section:1", result.issues[0].element_id)
        self.assertEqual(1, result.stats.warning_count)
        self.assertEqual(2, result.stats.candidate_count)

    def test_non_overlapping_cross_section_does_not_create_relation(self):
        from drawing_graph.block_relation_enrichment import enrich_cross_sections

        page_id = "page:road:set-a:road_24"
        block = element("block:1", page_id, (0, 0, 10, 10))
        cross_section = element("cross-section:1", page_id, (20, 20, 30, 30))
        page = page_snapshot(page_id, blocks=[block], cross_sections=[cross_section])

        result = enrich_cross_sections(scope(), page)

        self.assertEqual((), result.relations)
        self.assertEqual(1, result.stats.block_count)
        self.assertEqual(1, result.stats.cross_section_count)
        self.assertEqual(0, result.stats.relation_count)

    def test_low_overlap_cross_section_records_warning_without_relation(self):
        from drawing_graph.block_relation_enrichment import enrich_cross_sections

        page_id = "page:road:set-a:road_24"
        block = element("block:1", page_id, (0, 0, 25, 25))
        cross_section = element("cross-section:1", page_id, (0, 0, 100, 100))
        page = page_snapshot(page_id, blocks=[block], cross_sections=[cross_section])

        result = enrich_cross_sections(scope(), page)

        self.assertEqual((), result.relations)
        self.assertEqual(1, len(result.issues))
        issue = result.issues[0]
        self.assertEqual("section_candidate_low_evidence", issue.category)
        self.assertEqual("warning", issue.severity)
        self.assertEqual(page_id, issue.page_id)
        self.assertEqual("cross-section:1", issue.element_id)
        self.assertEqual(1, result.stats.warning_count)
        self.assertEqual(0, result.stats.relation_count)

    def test_low_overlap_rejection_does_not_affect_other_cross_section_matches(self):
        from drawing_graph.block_relation_enrichment import enrich_cross_sections

        page_id = "page:road:set-a:road_24"
        low_overlap_block = element("block:low-overlap", page_id, (0, 0, 25, 25))
        matched_block = element("block:matched", page_id, (100, 100, 200, 200))
        low_overlap_cross_section = element("cross-section:low", page_id, (0, 0, 100, 100))
        matched_cross_section = element("cross-section:matched", page_id, (110, 110, 150, 150))
        page = page_snapshot(
            page_id,
            blocks=[low_overlap_block, matched_block],
            cross_sections=[low_overlap_cross_section, matched_cross_section],
        )

        result = enrich_cross_sections(scope(), page)

        self.assertEqual(
            [("block:matched", "cross-section:matched")],
            [(relation.start_id, relation.end_id) for relation in result.relations],
        )
        self.assertEqual(["section_candidate_low_evidence"], [issue.category for issue in result.issues])
        self.assertEqual("cross-section:low", result.issues[0].element_id)
        self.assertEqual(2, result.stats.cross_section_count)
        self.assertEqual(1, result.stats.warning_count)
        self.assertEqual(1, result.stats.relation_count)


if __name__ == "__main__":
    unittest.main()
