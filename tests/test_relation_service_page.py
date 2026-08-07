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


def scope(**overrides):
    from drawing_graph.block_relation_enrichment import EnrichmentScope

    values = {
        "project_id": "project:road",
        "drawing_set_id": "set:road:set-a",
        "page_id": "page:road:set-a:road_24",
        "relation_batch_id": "relation-batch:001",
        "rule_version": "relation-rules-v1",
    }
    values.update(overrides)
    return EnrichmentScope(**values)


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


class FakeRepository:
    def __init__(self, *, pages=(), previous_page=None, write_error=None, write_errors_by_end_id=None):
        self.pages = tuple(pages)
        self.previous_page = previous_page
        self.write_error = write_error
        self.write_errors_by_end_id = dict(write_errors_by_end_id or {})
        self.read_scopes = []
        self.previous_page_requests = []
        self.written_relations = []

    def read_pages(self, read_scope, limit=100):
        self.read_scopes.append((read_scope, limit))
        return self.pages

    def read_previous_page_basic_infos(self, page):
        self.previous_page_requests.append(page)
        return self.previous_page

    def write_relations(self, relations):
        self.written_relations.append(tuple(relations))
        for relation in relations:
            error = self.write_errors_by_end_id.get(relation.end_id)
            if error is not None:
                raise error
        if self.write_error is not None:
            raise self.write_error


class RelationEnrichmentServicePageTest(unittest.TestCase):
    def test_enrich_page_reads_calculates_writes_and_records_success_summary(self):
        from drawing_graph.audit import RelationAuditStore
        from drawing_graph.relation_service import RelationEnrichmentService

        page_id = "page:road:set-a:road_24"
        page = page_snapshot(
            blocks=[element("block:1", page_id, (50, 100, 90, 140))],
            captions=[element("caption:1", page_id, (50, 70, 90, 80))],
            basic_infos=[element("basic-info:1", page_id)],
            annotations=[element("annotation:1", page_id)],
        )
        repository = FakeRepository(pages=[page])
        audit_store = RelationAuditStore()
        service = RelationEnrichmentService(repository, audit_store)

        result = service.enrich_page(scope())

        self.assertEqual(3, result.stats.relation_count)
        self.assertEqual(3, len(repository.written_relations[0]))
        self.assertEqual([], repository.previous_page_requests)
        self.assertEqual("success", service.get_batch_summary("relation-batch:001")["status"])
        self.assertEqual(3, service.get_batch_summary("relation-batch:001")["relation_count"])

    def test_enrich_page_for_missing_page_returns_failed_summary_without_writing(self):
        from drawing_graph.audit import RelationAuditStore
        from drawing_graph.relation_service import RelationEnrichmentService

        repository = FakeRepository(pages=())
        service = RelationEnrichmentService(repository, RelationAuditStore())

        result = service.enrich_page(scope())

        self.assertEqual(0, result.stats.page_count)
        self.assertEqual([], repository.written_relations)
        summary = service.get_batch_summary("relation-batch:001")
        self.assertEqual("failed", summary["status"])
        self.assertEqual(0, summary["relation_count"])

    def test_enrich_page_without_blocks_records_empty_page_summary_without_writing(self):
        from drawing_graph.audit import RelationAuditStore
        from drawing_graph.relation_service import RelationEnrichmentService

        page_id = "page:road:set-a:road_24"
        page = page_snapshot(
            captions=[element("caption:orphan", page_id)],
            basic_infos=[element("basic-info:1", page_id)],
            annotations=[element("annotation:1", page_id)],
        )
        repository = FakeRepository(pages=[page])
        service = RelationEnrichmentService(repository, RelationAuditStore())

        result = service.enrich_page(scope())

        self.assertEqual(1, result.stats.page_count)
        self.assertEqual(0, result.stats.block_count)
        self.assertEqual(0, result.stats.relation_count)
        self.assertEqual([], repository.written_relations)
        self.assertEqual("success", service.get_batch_summary("relation-batch:001")["status"])

    def test_enrich_page_without_blocks_writes_table_caption_relation(self):
        from drawing_graph.audit import RelationAuditStore
        from drawing_graph.relation_service import RelationEnrichmentService

        page_id = "page:road:set-a:road_24"
        page = page_snapshot(
            tables=[element("table:1", page_id, (10, 10, 100, 100))],
            table_captions=[element("table-caption:1", page_id, (10, 110, 100, 130))],
        )
        repository = FakeRepository(pages=[page])
        service = RelationEnrichmentService(repository, RelationAuditStore())

        result = service.enrich_page(scope())

        self.assertEqual(1, result.stats.table_caption_relation_count)
        self.assertEqual(1, len(repository.written_relations))
        self.assertEqual("table_caption", repository.written_relations[0][0].relation_spec)
        summary = service.get_batch_summary("relation-batch:001")
        self.assertEqual("success", summary["status"])
        self.assertEqual(1, summary["table_caption_relation_count"])

    def test_enrich_page_processes_cross_sections_and_records_section_mark_summary(self):
        from drawing_graph.audit import RelationAuditStore
        from drawing_graph.relation_service import RelationEnrichmentService

        page_id = "page:road:set-a:road_24"
        page = page_snapshot(
            blocks=[element("block:1", page_id, (10, 10, 100, 100))],
            basic_infos=[element("basic-info:1", page_id)],
            annotations=[element("annotation:1", page_id)],
            cross_sections=[element("cross-section:1", page_id, (20, 20, 40, 40))],
        )
        repository = FakeRepository(pages=[page])
        service = RelationEnrichmentService(repository, RelationAuditStore())

        result = service.enrich_page(scope())

        self.assertEqual(1, result.stats.cross_section_count)
        self.assertEqual(3, result.stats.relation_count)
        relation_types = sorted(relation.relation_type for relation in repository.written_relations[0])
        self.assertEqual(["HAS_ANNOTATION", "HAS_SECTION_MARK", "USES_BASIC_INFO"], relation_types)
        summary = service.get_batch_summary("relation-batch:001")
        self.assertEqual("success", summary["status"])
        self.assertEqual(1, summary["cross_section_count"])
        self.assertEqual(3, summary["relation_count"])

    def test_single_page_missing_previous_context_records_classified_warning(self):
        from drawing_graph.audit import RelationAuditStore
        from drawing_graph.relation_service import RelationEnrichmentService

        page_id = "page:road:set-a:road_24"
        page = page_snapshot(
            blocks=[element("block:1", page_id)],
            annotations=[element("annotation:1", page_id)],
        )
        repository = FakeRepository(pages=[page])
        service = RelationEnrichmentService(repository, RelationAuditStore())

        result = service.enrich_page(scope())

        self.assertEqual([], repository.previous_page_requests)
        self.assertEqual(["basic_info_not_evaluated"], [issue.category for issue in result.issues])
        summary = service.get_batch_summary("relation-batch:001")
        self.assertEqual("partial", summary["status"])
        self.assertEqual({"basic_info_not_evaluated": 1}, summary["issue_summary"])

    def test_relation_write_failure_is_classified_in_audit_summary(self):
        from drawing_graph.audit import RelationAuditStore
        from drawing_graph.relation_service import RelationEnrichmentService

        page_id = "page:road:set-a:road_24"
        page = page_snapshot(
            blocks=[element("block:1", page_id)],
            basic_infos=[element("basic-info:1", page_id)],
            annotations=[element("annotation:1", page_id)],
        )
        repository = FakeRepository(pages=[page], write_error=RuntimeError("password=hunter2"))
        service = RelationEnrichmentService(repository, RelationAuditStore())

        result = service.enrich_page(scope())

        self.assertEqual(2, result.stats.relation_count)
        summary = service.get_batch_summary("relation-batch:001")
        self.assertEqual("failed", summary["status"])
        self.assertEqual(1, summary["error_count"])
        self.assertEqual({"relation_write_failed": 1}, summary["issue_summary"])
        self.assertNotIn("hunter2", repr(summary))

    def test_table_caption_legacy_conflict_is_isolated_from_other_candidates(self):
        from drawing_graph.audit import RelationAuditStore
        from drawing_graph.relation_repository import RelationRepositoryError
        from drawing_graph.relation_service import RelationEnrichmentService

        page_id = "page:road:set-a:road_24"
        page = page_snapshot(
            blocks=[element("block:1", page_id, (50, 100, 90, 140))],
            captions=[element("caption:1", page_id, (50, 70, 90, 80))],
            basic_infos=[element("basic-info:1", page_id)],
            tables=[
                element("table:conflict", page_id, (0, 0, 50, 50)),
                element("table:ok", page_id, (100, 0, 150, 50)),
            ],
            table_captions=[
                element("table-caption:conflict", page_id, (0, 60, 50, 80)),
                element("table-caption:ok", page_id, (100, 60, 150, 80)),
            ],
        )
        repository = FakeRepository(
            pages=[page],
            write_errors_by_end_id={
                "table-caption:conflict": RelationRepositoryError(
                    "table_caption_legacy_conflict",
                    "legacy conflict",
                )
            },
        )
        service = RelationEnrichmentService(repository, RelationAuditStore())

        result = service.enrich_page(scope())

        self.assertEqual("partial", service.get_batch_summary("relation-batch:001")["status"])
        self.assertEqual(3, len(repository.written_relations))
        self.assertEqual(
            {"block_caption", "page_uses_basic_info"},
            {relation.relation_spec for relation in repository.written_relations[0]},
        )
        self.assertEqual("table_caption", repository.written_relations[1][0].relation_spec)
        self.assertEqual("table_caption", repository.written_relations[2][0].relation_spec)
        self.assertEqual("table-caption:ok", repository.written_relations[2][0].end_id)
        summary = service.get_batch_summary("relation-batch:001")
        self.assertEqual({"table_caption_legacy_conflict": 1}, summary["issue_summary"])
        self.assertEqual(1, summary["warning_count"])
        self.assertEqual(0, summary["error_count"])
        self.assertEqual(4, result.stats.relation_count)

    def test_section_mark_write_failure_is_classified_in_audit_summary(self):
        from drawing_graph.audit import RelationAuditStore
        from drawing_graph.relation_service import RelationEnrichmentService

        page_id = "page:road:set-a:road_24"
        page = page_snapshot(
            blocks=[element("block:1", page_id, (10, 10, 100, 100))],
            basic_infos=[element("basic-info:1", page_id)],
            cross_sections=[element("cross-section:1", page_id, (20, 20, 40, 40))],
        )
        repository = FakeRepository(pages=[page], write_error=RuntimeError("password=hunter2"))
        service = RelationEnrichmentService(repository, RelationAuditStore())

        result = service.enrich_page(scope())

        self.assertEqual(2, result.stats.relation_count)
        summary = service.get_batch_summary("relation-batch:001")
        self.assertEqual("failed", summary["status"])
        self.assertEqual(1, summary["error_count"])
        self.assertEqual({"section_mark_write_failed": 1}, summary["issue_summary"])
        self.assertNotIn("relation_write_failed", summary["issue_summary"])
        self.assertNotIn("hunter2", repr(summary))

    def test_audit_summary_can_be_read_by_relation_batch_id(self):
        from drawing_graph.audit import RelationAuditStore
        from drawing_graph.relation_service import RelationEnrichmentService

        page = page_snapshot(blocks=[element("block:1")], annotations=[element("annotation:1")])
        service = RelationEnrichmentService(FakeRepository(pages=[page]), RelationAuditStore())

        service.enrich_page(scope())

        self.assertEqual("relation-batch:001", service.get_batch_summary("relation-batch:001")["relation_batch_id"])
        self.assertIsNone(service.get_batch_summary("relation-batch:missing"))


if __name__ == "__main__":
    unittest.main()
