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


def page_snapshot(blocks, annotations, page_id="page:road:set-a:road_24"):
    from drawing_graph.block_relation_enrichment import PageRelationSnapshot

    return PageRelationSnapshot(
        page_id=page_id,
        drawing_set_id="set:road:set-a",
        page_number=24,
        blocks=blocks,
        annotations=annotations,
    )


class AnnotationEnrichmentTest(unittest.TestCase):
    def test_multiple_blocks_and_annotations_are_fully_shared(self):
        from drawing_graph.block_relation_enrichment import enrich_page_annotations

        first_block = element("block:1")
        second_block = element("block:2")
        first_annotation = element("annotation:1")
        second_annotation = element("annotation:2")

        result = enrich_page_annotations(
            scope(),
            page_snapshot([first_block, second_block], [first_annotation, second_annotation]),
        )

        self.assertEqual(
            {
                ("block:1", "annotation:1"),
                ("block:1", "annotation:2"),
                ("block:2", "annotation:1"),
                ("block:2", "annotation:2"),
            },
            {(relation.start_id, relation.end_id) for relation in result.relations},
        )
        self.assertEqual({"HAS_ANNOTATION"}, {relation.relation_type for relation in result.relations})
        self.assertEqual({"same_page_shared"}, {relation.properties["match_direction"] for relation in result.relations})
        self.assertNotIn("distance", result.relations[0].properties)
        self.assertEqual(2, result.stats.block_count)
        self.assertEqual(2, result.stats.annotation_count)
        self.assertEqual(4, result.stats.relation_count)

    def test_page_without_annotations_returns_empty_status(self):
        from drawing_graph.block_relation_enrichment import enrich_page_annotations

        block = element("block:1")

        result = enrich_page_annotations(scope(), page_snapshot([block], []))

        self.assertEqual((), result.relations)
        self.assertEqual((), result.issues)
        self.assertEqual(1, result.stats.block_count)
        self.assertEqual(0, result.stats.annotation_count)
        self.assertEqual(0, result.stats.relation_count)

    def test_page_without_blocks_returns_empty_status(self):
        from drawing_graph.block_relation_enrichment import enrich_page_annotations

        annotation = element("annotation:1")

        result = enrich_page_annotations(scope(), page_snapshot([], [annotation]))

        self.assertEqual((), result.relations)
        self.assertEqual((), result.issues)
        self.assertEqual(0, result.stats.block_count)
        self.assertEqual(1, result.stats.annotation_count)
        self.assertEqual(0, result.stats.relation_count)

    def test_elements_from_other_pages_do_not_participate(self):
        from drawing_graph.block_relation_enrichment import enrich_page_annotations

        same_page_block = element("block:same-page")
        other_page_block = element("block:other-page", page_id="page:road:set-a:road_25")
        same_page_annotation = element("annotation:same-page")
        other_page_annotation = element("annotation:other-page", page_id="page:road:set-a:road_25")

        result = enrich_page_annotations(
            scope(),
            page_snapshot([same_page_block, other_page_block], [same_page_annotation, other_page_annotation]),
        )

        self.assertEqual(1, len(result.relations))
        self.assertEqual("block:same-page", result.relations[0].start_id)
        self.assertEqual("annotation:same-page", result.relations[0].end_id)


if __name__ == "__main__":
    unittest.main()
