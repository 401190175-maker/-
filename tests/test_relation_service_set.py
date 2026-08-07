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


def element(element_id, page_id, values=None):
    from drawing_graph.block_relation_enrichment import PageElementSnapshot

    return PageElementSnapshot(id=element_id, page_id=page_id, bbox=bbox(*(values or (10, 20, 110, 120))))


def scope(**overrides):
    from drawing_graph.block_relation_enrichment import EnrichmentScope

    values = {
        "project_id": "project:road",
        "drawing_set_id": "set:road:set-a",
        "relation_batch_id": "relation-batch:001",
        "rule_version": "relation-rules-v1",
    }
    values.update(overrides)
    return EnrichmentScope(**values)


def page_snapshot(
    page_number,
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


class FakeRepository:
    def __init__(self, *, pages=(), failing_page_ids=(), failing_relation_types=(), write_errors_by_end_id=None):
        self.pages = tuple(pages)
        self.failing_page_ids = set(failing_page_ids)
        self.failing_relation_types = set(failing_relation_types)
        self.write_errors_by_end_id = dict(write_errors_by_end_id or {})
        self.read_scopes = []
        self.written_relations = []

    def read_pages(self, read_scope, limit=100):
        self.read_scopes.append((read_scope, limit))
        return self.pages

    def write_relations(self, relations):
        relation_batch = tuple(relations)
        self.written_relations.append(relation_batch)
        for relation in relation_batch:
            error = self.write_errors_by_end_id.get(relation.end_id)
            if error is not None:
                raise error
        if any(
            relation.start_id in self.failing_page_ids or relation.relation_type in self.failing_relation_types
            for relation in relation_batch
        ):
            raise RuntimeError("password=hunter2")


class RelationEnrichmentServiceSetTest(unittest.TestCase):
    def test_enrich_drawing_set_processes_all_pages_in_order_and_records_success_summary(self):
        from drawing_graph.audit import RelationAuditStore
        from drawing_graph.relation_service import RelationEnrichmentService

        page_1_id = "page:road:set-a:road_1"
        page_2_id = "page:road:set-a:road_2"
        page_1 = page_snapshot(
            1,
            blocks=[element("block:1", page_1_id)],
            basic_infos=[element("basic-info:1", page_1_id)],
            annotations=[element("annotation:1", page_1_id)],
        )
        page_2 = page_snapshot(
            2,
            blocks=[element("block:2", page_2_id)],
            basic_infos=[element("basic-info:2", page_2_id)],
            annotations=[element("annotation:2", page_2_id)],
        )
        repository = FakeRepository(pages=[page_2, page_1])
        service = RelationEnrichmentService(repository, RelationAuditStore())

        result = service.enrich_drawing_set(scope())

        self.assertEqual(2, result.stats.page_count)
        self.assertEqual(4, result.stats.relation_count)
        self.assertEqual(10000, repository.read_scopes[0][1])
        self.assertEqual(["block:1", "block:2"], [batch[0].start_id for batch in repository.written_relations])
        summary = service.get_batch_summary("relation-batch:001")
        self.assertEqual("success", summary["status"])
        self.assertEqual(2, summary["page_count"])
        self.assertEqual(4, summary["relation_count"])

    def test_single_page_write_failure_does_not_stop_later_pages(self):
        from drawing_graph.audit import RelationAuditStore
        from drawing_graph.relation_service import RelationEnrichmentService

        page_1_id = "page:road:set-a:road_1"
        page_2_id = "page:road:set-a:road_2"
        page_1 = page_snapshot(
            1,
            blocks=[element("block:fail", page_1_id)],
            basic_infos=[element("basic-info:1", page_1_id)],
        )
        page_2 = page_snapshot(
            2,
            blocks=[element("block:ok", page_2_id)],
            basic_infos=[element("basic-info:2", page_2_id)],
        )
        service = RelationEnrichmentService(
            FakeRepository(pages=[page_1, page_2], failing_page_ids={page_1_id}),
            RelationAuditStore(),
        )

        result = service.enrich_drawing_set(scope())

        self.assertEqual(2, result.stats.page_count)
        self.assertEqual(2, result.stats.relation_count)
        summary = service.get_batch_summary("relation-batch:001")
        self.assertEqual("partial", summary["status"])
        self.assertEqual({"relation_write_failed": 1}, summary["issue_summary"])
        self.assertEqual(2, len(service.repository.written_relations))

    def test_drawing_set_summarizes_table_counts_and_isolates_table_conflict(self):
        from drawing_graph.audit import RelationAuditStore
        from drawing_graph.relation_repository import RelationRepositoryError
        from drawing_graph.relation_service import RelationEnrichmentService

        page_1_id = "page:road:set-a:road_1"
        page_2_id = "page:road:set-a:road_2"
        page_1 = page_snapshot(
            1,
            tables=[element("table:conflict", page_1_id, (0, 0, 50, 50))],
            table_captions=[element("table-caption:conflict", page_1_id, (0, 60, 50, 80))],
        )
        page_2 = page_snapshot(
            2,
            tables=[element("table:ok", page_2_id, (100, 0, 150, 50))],
            table_captions=[element("table-caption:ok", page_2_id, (100, 60, 150, 80))],
        )
        repository = FakeRepository(
            pages=[page_1, page_2],
            write_errors_by_end_id={
                "table-caption:conflict": RelationRepositoryError(
                    "table_caption_legacy_conflict",
                    "legacy conflict",
                )
            },
        )
        service = RelationEnrichmentService(repository, RelationAuditStore())

        result = service.enrich_drawing_set(scope())

        self.assertEqual(2, result.stats.table_count)
        self.assertEqual(2, result.stats.table_caption_count)
        self.assertEqual(2, result.stats.table_caption_relation_count)
        self.assertEqual(2, result.stats.relation_count)
        self.assertEqual(2, len(repository.written_relations))
        self.assertEqual("table-caption:ok", repository.written_relations[1][0].end_id)
        summary = service.get_batch_summary("relation-batch:001")
        self.assertEqual("partial", summary["status"])
        self.assertEqual(2, summary["table_caption_relation_count"])
        self.assertEqual({"table_caption_legacy_conflict": 1}, summary["issue_summary"])

    def test_drawing_set_summarizes_section_mark_relations_and_cross_section_issues(self):
        from drawing_graph.audit import RelationAuditStore
        from drawing_graph.relation_service import RelationEnrichmentService

        page_1_id = "page:road:set-a:road_1"
        page_2_id = "page:road:set-a:road_2"
        page_1 = page_snapshot(
            1,
            blocks=[element("block:1", page_1_id, (10, 10, 100, 100))],
            basic_infos=[element("basic-info:1", page_1_id)],
            cross_sections=[element("cross-section:matched", page_1_id, (20, 20, 40, 40))],
        )
        page_2 = page_snapshot(
            2,
            blocks=[
                element("block:2a", page_2_id, (10, 10, 60, 60)),
                element("block:2b", page_2_id, (10, 10, 60, 60)),
            ],
            basic_infos=[element("basic-info:2", page_2_id)],
            cross_sections=[
                element("cross-section:conflict", page_2_id, (20, 20, 40, 40)),
                element("cross-section:low-overlap", page_2_id, (0, 0, 100, 100)),
            ],
        )
        service = RelationEnrichmentService(FakeRepository(pages=[page_1, page_2]), RelationAuditStore())

        result = service.enrich_drawing_set(scope())

        self.assertEqual(3, result.stats.cross_section_count)
        self.assertEqual(5, result.stats.relation_count)
        self.assertEqual(2, result.stats.warning_count)
        self.assertEqual(2, result.stats.candidate_count)
        self.assertIn(
            ("block:1", "cross-section:matched", "HAS_SECTION_MARK"),
            {(relation.start_id, relation.end_id, relation.relation_type) for relation in result.relations},
        )
        summary = service.get_batch_summary("relation-batch:001")
        self.assertEqual("partial", summary["status"])
        self.assertEqual(3, summary["cross_section_count"])
        self.assertEqual({"section_candidate_ambiguous": 1, "section_candidate_low_evidence": 1}, summary["issue_summary"])

    def test_section_mark_write_failure_does_not_stop_later_pages_in_drawing_set(self):
        from drawing_graph.audit import RelationAuditStore
        from drawing_graph.relation_service import RelationEnrichmentService

        page_1_id = "page:road:set-a:road_1"
        page_2_id = "page:road:set-a:road_2"
        page_1 = page_snapshot(
            1,
            blocks=[element("block:fail-section", page_1_id, (10, 10, 100, 100))],
            basic_infos=[element("basic-info:1", page_1_id)],
            cross_sections=[element("cross-section:1", page_1_id, (20, 20, 40, 40))],
        )
        page_2 = page_snapshot(
            2,
            blocks=[element("block:ok", page_2_id)],
            basic_infos=[element("basic-info:2", page_2_id)],
        )
        service = RelationEnrichmentService(
            FakeRepository(pages=[page_1, page_2], failing_relation_types={"HAS_SECTION_MARK"}),
            RelationAuditStore(),
        )

        result = service.enrich_drawing_set(scope())

        self.assertEqual(2, result.stats.page_count)
        self.assertEqual(1, result.stats.cross_section_count)
        self.assertEqual(3, result.stats.relation_count)
        summary = service.get_batch_summary("relation-batch:001")
        self.assertEqual("partial", summary["status"])
        self.assertEqual({"section_mark_write_failed": 1}, summary["issue_summary"])
        self.assertEqual(2, len(service.repository.written_relations))

    def test_empty_drawing_set_returns_successful_empty_summary(self):
        from drawing_graph.audit import RelationAuditStore
        from drawing_graph.relation_service import RelationEnrichmentService

        service = RelationEnrichmentService(FakeRepository(pages=()), RelationAuditStore())

        result = service.enrich_drawing_set(scope())

        self.assertEqual(0, result.stats.page_count)
        self.assertEqual(0, result.stats.relation_count)
        summary = service.get_batch_summary("relation-batch:001")
        self.assertEqual("success", summary["status"])
        self.assertEqual(0, summary["page_count"])

    def test_later_page_records_partial_basic_info_context_without_formal_inheritance(self):
        from drawing_graph.audit import RelationAuditStore
        from drawing_graph.relation_service import RelationEnrichmentService

        page_1_id = "page:road:set-a:road_1"
        page_2_id = "page:road:set-a:road_2"
        page_1 = page_snapshot(
            1,
            blocks=[element("block:1", page_1_id)],
            basic_infos=[element("basic-info:previous", page_1_id)],
        )
        page_2 = page_snapshot(
            2,
            blocks=[element("block:2", page_2_id)],
        )
        service = RelationEnrichmentService(FakeRepository(pages=[page_1, page_2]), RelationAuditStore())

        result = service.enrich_drawing_set(scope())

        self.assertNotIn(
            ("block:2", "basic-info:previous", "HAS_BASIC_INFO"),
            {(relation.start_id, relation.end_id, relation.relation_type) for relation in result.relations},
        )
        self.assertIn(
            ("page:road:set-a:road_1", "basic-info:previous", "USES_BASIC_INFO"),
            {(relation.start_id, relation.end_id, relation.relation_type) for relation in result.relations},
        )
        self.assertEqual(["basic_info_partial"], [issue.category for issue in result.issues])
        self.assertEqual(1, result.stats.not_evaluated_count)

    def test_previous_page_context_is_not_shared_across_drawing_sets(self):
        from drawing_graph.audit import RelationAuditStore
        from drawing_graph.relation_service import RelationEnrichmentService

        set_a_page = page_snapshot(
            1,
            blocks=[element("block:a", "page:road:set-a:road_1")],
            basic_infos=[element("basic-info:set-a", "page:road:set-a:road_1")],
            drawing_set_id="set:road:set-a",
        )
        set_b_page = page_snapshot(
            2,
            blocks=[element("block:b", "page:road:set-b:road_2")],
            drawing_set_id="set:road:set-b",
        )
        service = RelationEnrichmentService(FakeRepository(pages=[set_a_page, set_b_page]), RelationAuditStore())

        result = service.enrich_drawing_set(scope())

        self.assertNotIn(
            ("block:b", "basic-info:set-a", "HAS_BASIC_INFO"),
            {(relation.start_id, relation.end_id, relation.relation_type) for relation in result.relations},
        )
        self.assertEqual(["basic_info_not_evaluated"], [issue.category for issue in result.issues])

    def test_enrich_drawing_set_requires_drawing_set_scope(self):
        from drawing_graph.audit import RelationAuditStore
        from drawing_graph.relation_service import RelationEnrichmentService, RelationServiceError

        service = RelationEnrichmentService(FakeRepository(), RelationAuditStore())

        with self.assertRaises(RelationServiceError) as context:
            service.enrich_drawing_set(scope(drawing_set_id=None))

        self.assertEqual("missing_drawing_set_id", context.exception.category)


if __name__ == "__main__":
    unittest.main()
