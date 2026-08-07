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
        "relation_batch_id": "relation-batch:001",
        "rule_version": "relation-rules-v1",
    }
    values.update(overrides)
    return EnrichmentScope(**values)


def page_snapshot(
    drawing_set_slug,
    page_number,
    *,
    blocks=(),
    tables=(),
    table_captions=(),
    basic_infos=(),
    annotations=(),
    cross_sections=(),
):
    from drawing_graph.block_relation_enrichment import PageRelationSnapshot

    page_id = f"page:road:{drawing_set_slug}:road_{page_number}"
    return PageRelationSnapshot(
        page_id=page_id,
        drawing_set_id=f"set:road:{drawing_set_slug}",
        page_number=page_number,
        blocks=blocks,
        tables=tables,
        table_captions=table_captions,
        basic_infos=basic_infos,
        annotations=annotations,
        cross_sections=cross_sections,
    )


class FakeRepository:
    def __init__(self, *, pages=(), failing_start_ids=(), failing_relation_types=(), read_error=None, write_errors_by_end_id=None):
        self.pages = tuple(pages)
        self.failing_start_ids = set(failing_start_ids)
        self.failing_relation_types = set(failing_relation_types)
        self.read_error = read_error
        self.write_errors_by_end_id = dict(write_errors_by_end_id or {})
        self.read_scopes = []
        self.written_relations = []

    def read_pages(self, read_scope, limit=100):
        self.read_scopes.append((read_scope, limit))
        if self.read_error is not None:
            raise self.read_error
        return self.pages

    def write_relations(self, relations):
        relation_batch = tuple(relations)
        self.written_relations.append(relation_batch)
        for relation in relation_batch:
            error = self.write_errors_by_end_id.get(relation.end_id)
            if error is not None:
                raise error
        if any(
            relation.start_id in self.failing_start_ids or relation.relation_type in self.failing_relation_types
            for relation in relation_batch
        ):
            raise RuntimeError("password=hunter2")


class RelationEnrichmentServiceProjectTest(unittest.TestCase):
    def test_enrich_project_processes_multiple_drawing_sets_and_records_success_summary(self):
        from drawing_graph.audit import RelationAuditStore
        from drawing_graph.relation_service import RelationEnrichmentService

        set_a_page_id = "page:road:set-a:road_1"
        set_b_page_id = "page:road:set-b:road_1"
        set_a_page = page_snapshot(
            "set-a",
            1,
            blocks=[element("block:a", set_a_page_id)],
            basic_infos=[element("basic-info:a", set_a_page_id)],
            annotations=[element("annotation:a", set_a_page_id)],
        )
        set_b_page = page_snapshot(
            "set-b",
            1,
            blocks=[element("block:b", set_b_page_id)],
            basic_infos=[element("basic-info:b", set_b_page_id)],
            annotations=[element("annotation:b", set_b_page_id)],
        )
        repository = FakeRepository(pages=[set_b_page, set_a_page])
        service = RelationEnrichmentService(repository, RelationAuditStore())

        result = service.enrich_project(scope())

        self.assertEqual(2, result.stats.page_count)
        self.assertEqual(4, result.stats.relation_count)
        self.assertEqual(10000, repository.read_scopes[0][1])
        self.assertEqual(["block:a", "block:b"], [batch[0].start_id for batch in repository.written_relations])
        summary = service.get_batch_summary("relation-batch:001")
        self.assertEqual("success", summary["status"])
        self.assertEqual(2, summary["page_count"])
        self.assertEqual(4, summary["relation_count"])

    def test_one_drawing_set_write_failure_does_not_stop_other_sets(self):
        from drawing_graph.audit import RelationAuditStore
        from drawing_graph.relation_service import RelationEnrichmentService

        set_a_page_id = "page:road:set-a:road_1"
        set_b_page_id = "page:road:set-b:road_1"
        set_a_page = page_snapshot(
            "set-a",
            1,
            blocks=[element("block:fail", set_a_page_id)],
            basic_infos=[element("basic-info:a", set_a_page_id)],
        )
        set_b_page = page_snapshot(
            "set-b",
            1,
            blocks=[element("block:ok", set_b_page_id)],
            basic_infos=[element("basic-info:b", set_b_page_id)],
        )
        repository = FakeRepository(pages=[set_a_page, set_b_page], failing_start_ids={set_a_page_id})
        service = RelationEnrichmentService(repository, RelationAuditStore())

        result = service.enrich_project(scope())

        self.assertEqual(2, result.stats.page_count)
        self.assertEqual(2, result.stats.relation_count)
        self.assertEqual(2, len(repository.written_relations))
        summary = service.get_batch_summary("relation-batch:001")
        self.assertEqual("partial", summary["status"])
        self.assertEqual({"relation_write_failed": 1}, summary["issue_summary"])

    def test_project_without_pages_returns_failed_batch_summary(self):
        from drawing_graph.audit import RelationAuditStore
        from drawing_graph.relation_service import RelationEnrichmentService

        service = RelationEnrichmentService(FakeRepository(pages=()), RelationAuditStore())

        result = service.enrich_project(scope())

        self.assertEqual(0, result.stats.page_count)
        self.assertEqual(0, result.stats.relation_count)
        summary = service.get_batch_summary("relation-batch:001")
        self.assertEqual("failed", summary["status"])
        self.assertEqual(0, summary["page_count"])

    def test_project_summary_accumulates_pages_blocks_relations_and_warnings(self):
        from drawing_graph.audit import RelationAuditStore
        from drawing_graph.relation_service import RelationEnrichmentService

        set_a_page_id = "page:road:set-a:road_1"
        set_b_page_id = "page:road:set-b:road_2"
        set_a_page = page_snapshot(
            "set-a",
            1,
            blocks=[element("block:a", set_a_page_id)],
            basic_infos=[element("basic-info:a", set_a_page_id)],
        )
        set_b_page = page_snapshot(
            "set-b",
            2,
            blocks=[element("block:b", set_b_page_id)],
        )
        service = RelationEnrichmentService(FakeRepository(pages=[set_a_page, set_b_page]), RelationAuditStore())

        result = service.enrich_project(scope())

        self.assertEqual(2, result.stats.page_count)
        self.assertEqual(2, result.stats.block_count)
        self.assertEqual(1, result.stats.relation_count)
        self.assertEqual(["basic_info_not_evaluated"], [issue.category for issue in result.issues])
        summary = service.get_batch_summary("relation-batch:001")
        self.assertEqual("partial", summary["status"])
        self.assertEqual({"basic_info_not_evaluated": 1}, summary["issue_summary"])

    def test_project_summarizes_table_counts_and_isolates_table_conflict_across_sets(self):
        from drawing_graph.audit import RelationAuditStore
        from drawing_graph.relation_repository import RelationRepositoryError
        from drawing_graph.relation_service import RelationEnrichmentService

        set_a_page_id = "page:road:set-a:road_1"
        set_b_page_id = "page:road:set-b:road_1"
        set_a_page = page_snapshot(
            "set-a",
            1,
            tables=[element("table:conflict", set_a_page_id, (0, 0, 50, 50))],
            table_captions=[element("table-caption:conflict", set_a_page_id, (0, 60, 50, 80))],
        )
        set_b_page = page_snapshot(
            "set-b",
            1,
            tables=[element("table:ok", set_b_page_id, (100, 0, 150, 50))],
            table_captions=[element("table-caption:ok", set_b_page_id, (100, 60, 150, 80))],
        )
        repository = FakeRepository(
            pages=[set_a_page, set_b_page],
            write_errors_by_end_id={
                "table-caption:conflict": RelationRepositoryError(
                    "table_caption_legacy_conflict",
                    "legacy conflict",
                )
            },
        )
        service = RelationEnrichmentService(repository, RelationAuditStore())

        result = service.enrich_project(scope())

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

    def test_project_summary_accumulates_section_mark_relations_and_cross_section_issues(self):
        from drawing_graph.audit import RelationAuditStore
        from drawing_graph.relation_service import RelationEnrichmentService

        set_a_page_id = "page:road:set-a:road_1"
        set_b_page_id = "page:road:set-b:road_1"
        set_a_page = page_snapshot(
            "set-a",
            1,
            blocks=[element("block:a", set_a_page_id, (10, 10, 100, 100))],
            basic_infos=[element("basic-info:a", set_a_page_id)],
            cross_sections=[element("cross-section:a", set_a_page_id, (20, 20, 40, 40))],
        )
        set_b_page = page_snapshot(
            "set-b",
            1,
            blocks=[
                element("block:b1", set_b_page_id, (10, 10, 60, 60)),
                element("block:b2", set_b_page_id, (10, 10, 60, 60)),
            ],
            basic_infos=[element("basic-info:b", set_b_page_id)],
            cross_sections=[element("cross-section:b-conflict", set_b_page_id, (20, 20, 40, 40))],
        )
        service = RelationEnrichmentService(FakeRepository(pages=[set_b_page, set_a_page]), RelationAuditStore())

        result = service.enrich_project(scope())

        self.assertEqual(2, result.stats.cross_section_count)
        self.assertEqual(5, result.stats.relation_count)
        self.assertEqual(1, result.stats.warning_count)
        self.assertEqual(2, result.stats.candidate_count)
        self.assertIn(
            ("block:a", "cross-section:a", "HAS_SECTION_MARK"),
            {(relation.start_id, relation.end_id, relation.relation_type) for relation in result.relations},
        )
        summary = service.get_batch_summary("relation-batch:001")
        self.assertEqual("partial", summary["status"])
        self.assertEqual(2, summary["cross_section_count"])
        self.assertEqual({"section_candidate_ambiguous": 1}, summary["issue_summary"])

    def test_section_mark_write_failure_does_not_stop_other_drawing_sets_in_project(self):
        from drawing_graph.audit import RelationAuditStore
        from drawing_graph.relation_service import RelationEnrichmentService

        set_a_page_id = "page:road:set-a:road_1"
        set_b_page_id = "page:road:set-b:road_1"
        set_a_page = page_snapshot(
            "set-a",
            1,
            blocks=[element("block:section-fail", set_a_page_id, (10, 10, 100, 100))],
            basic_infos=[element("basic-info:a", set_a_page_id)],
            cross_sections=[element("cross-section:a", set_a_page_id, (20, 20, 40, 40))],
        )
        set_b_page = page_snapshot(
            "set-b",
            1,
            blocks=[element("block:ok", set_b_page_id)],
            basic_infos=[element("basic-info:b", set_b_page_id)],
        )
        repository = FakeRepository(
            pages=[set_a_page, set_b_page],
            failing_relation_types={"HAS_SECTION_MARK"},
        )
        service = RelationEnrichmentService(repository, RelationAuditStore())

        result = service.enrich_project(scope())

        self.assertEqual(2, result.stats.page_count)
        self.assertEqual(1, result.stats.cross_section_count)
        self.assertEqual(3, result.stats.relation_count)
        self.assertEqual(2, len(repository.written_relations))
        summary = service.get_batch_summary("relation-batch:001")
        self.assertEqual("partial", summary["status"])
        self.assertEqual({"section_mark_write_failed": 1}, summary["issue_summary"])

    def test_previous_page_basic_info_is_not_shared_between_drawing_sets(self):
        from drawing_graph.audit import RelationAuditStore
        from drawing_graph.relation_service import RelationEnrichmentService

        set_a_page_id = "page:road:set-a:road_1"
        set_b_page_id = "page:road:set-b:road_2"
        set_a_page = page_snapshot(
            "set-a",
            1,
            blocks=[element("block:a", set_a_page_id)],
            basic_infos=[element("basic-info:set-a", set_a_page_id)],
        )
        set_b_page = page_snapshot(
            "set-b",
            2,
            blocks=[element("block:b", set_b_page_id)],
        )
        service = RelationEnrichmentService(FakeRepository(pages=[set_a_page, set_b_page]), RelationAuditStore())

        result = service.enrich_project(scope())

        self.assertNotIn(
            ("block:b", "basic-info:set-a", "HAS_BASIC_INFO"),
            {(relation.start_id, relation.end_id, relation.relation_type) for relation in result.relations},
        )
        self.assertEqual(["basic_info_not_evaluated"], [issue.category for issue in result.issues])

    def test_enrich_project_requires_project_scope(self):
        from drawing_graph.audit import RelationAuditStore
        from drawing_graph.relation_service import RelationEnrichmentService, RelationServiceError

        service = RelationEnrichmentService(FakeRepository(), RelationAuditStore())

        with self.assertRaises(RelationServiceError) as context:
            service.enrich_project(scope(drawing_set_id="set:road:set-a"))

        self.assertEqual("invalid_project_scope", context.exception.category)


if __name__ == "__main__":
    unittest.main()
