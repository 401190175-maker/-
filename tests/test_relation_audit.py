import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def scope():
    from drawing_graph.block_relation_enrichment import EnrichmentScope

    return EnrichmentScope(
        project_id="project:road",
        drawing_set_id="set:road:set-a",
        page_id="page:road:set-a:road_24",
        relation_batch_id="relation-batch:001",
        rule_version="relation-rules-v1",
    )


def stats(**overrides):
    from drawing_graph.block_relation_enrichment import EnrichmentStats

    values = {
        "page_count": 1,
        "block_count": 2,
        "caption_count": 1,
        "basic_info_count": 1,
        "annotation_count": 1,
        "cross_section_count": 0,
        "table_count": 0,
        "table_caption_count": 0,
        "table_caption_relation_count": 0,
        "uses_basic_info_count": 0,
        "candidate_count": 0,
        "ambiguous_count": 0,
        "not_evaluated_count": 0,
        "reviewing_count": 0,
        "accepted_count": 0,
        "rejected_count": 0,
        "unresolved_count": 0,
        "relation_count": 3,
        "warning_count": 0,
        "error_count": 0,
    }
    values.update(overrides)
    return EnrichmentStats(**values)


def issue(category, severity="warning", message="classified relation issue", element_id="caption:1"):
    from drawing_graph.block_relation_enrichment import EnrichmentIssue

    return EnrichmentIssue(
        category=category,
        severity=severity,
        message=message,
        page_id="page:road:set-a:road_24",
        element_id=element_id,
    )


def result(*, issues=(), result_stats=None):
    from drawing_graph.block_relation_enrichment import EnrichmentResult

    return EnrichmentResult(
        scope=scope(),
        issues=issues,
        stats=result_stats or stats(),
    )


class RelationAuditTest(unittest.TestCase):
    def test_relation_batch_creation_records_rule_version_and_input_scope(self):
        from drawing_graph.audit import RelationBatchAudit

        audit = RelationBatchAudit.from_scope(scope())

        summary = audit.summary()

        self.assertEqual("relation-batch:001", summary["relation_batch_id"])
        self.assertEqual("running", summary["status"])
        self.assertEqual("project:road", summary["project_id"])
        self.assertEqual("set:road:set-a", summary["drawing_set_id"])
        self.assertEqual("page:road:set-a:road_24", summary["page_id"])
        self.assertEqual("relation-rules-v1", summary["rule_version"])

    def test_enrichment_result_counts_accumulate_without_mutating_import_audit(self):
        from drawing_graph.audit import ImportAudit, RelationBatchAudit

        import_audit = ImportAudit(batch_id="import-batch:001")
        audit = RelationBatchAudit.from_scope(scope())

        audit.record_enrichment_result(result())
        audit.record_enrichment_result(
            result(result_stats=stats(page_count=1, block_count=1, relation_count=2, annotation_count=0))
        )
        summary = audit.summary(status="success")

        self.assertEqual(2, summary["page_count"])
        self.assertEqual(3, summary["block_count"])
        self.assertEqual(2, summary["caption_count"])
        self.assertEqual(2, summary["basic_info_count"])
        self.assertEqual(1, summary["annotation_count"])
        self.assertEqual(5, summary["relation_count"])
        self.assertEqual(0, summary["uses_basic_info_count"])
        self.assertEqual(0, summary["candidate_count"])
        self.assertEqual(0, import_audit.summary()["total_count"])

    def test_new_relation_layer_counts_accumulate_and_appear_in_summary(self):
        from drawing_graph.audit import RelationBatchAudit

        audit = RelationBatchAudit.from_scope(scope())

        audit.record_enrichment_result(
            result(
                result_stats=stats(
                    uses_basic_info_count=1,
                    candidate_count=2,
                    ambiguous_count=1,
                    not_evaluated_count=1,
                    reviewing_count=2,
                    accepted_count=1,
                    rejected_count=1,
                    unresolved_count=1,
                    relation_count=4,
                )
            )
        )
        audit.record_enrichment_result(
            result(
                result_stats=stats(
                    uses_basic_info_count=2,
                    candidate_count=3,
                    ambiguous_count=2,
                    not_evaluated_count=1,
                    reviewing_count=1,
                    accepted_count=0,
                    rejected_count=1,
                    unresolved_count=2,
                    relation_count=5,
                )
            )
        )

        summary = audit.summary(status="success")

        self.assertEqual(3, summary["uses_basic_info_count"])
        self.assertEqual(5, summary["candidate_count"])
        self.assertEqual(3, summary["ambiguous_count"])
        self.assertEqual(2, summary["not_evaluated_count"])
        self.assertEqual(3, summary["reviewing_count"])
        self.assertEqual(1, summary["accepted_count"])
        self.assertEqual(2, summary["rejected_count"])
        self.assertEqual(3, summary["unresolved_count"])
        self.assertEqual(9, summary["relation_count"])

    def test_table_caption_counts_accumulate_and_appear_in_summary(self):
        from drawing_graph.audit import RelationBatchAudit

        audit = RelationBatchAudit.from_scope(scope())

        audit.record_enrichment_result(
            result(
                result_stats=stats(
                    table_count=2,
                    table_caption_count=3,
                    table_caption_relation_count=2,
                    relation_count=5,
                )
            )
        )
        audit.record_enrichment_result(
            result(
                result_stats=stats(
                    table_count=1,
                    table_caption_count=2,
                    table_caption_relation_count=1,
                    relation_count=4,
                )
            )
        )

        summary = audit.summary(status="success")

        self.assertEqual(3, summary["table_count"])
        self.assertEqual(5, summary["table_caption_count"])
        self.assertEqual(3, summary["table_caption_relation_count"])
        self.assertEqual(9, summary["relation_count"])

    def test_warning_and_error_categories_are_summarized(self):
        from drawing_graph.audit import RelationBatchAudit

        audit = RelationBatchAudit.from_scope(scope())
        audit.record_enrichment_result(
            result(
                issues=(
                    issue("caption_candidate_not_found"),
                    issue("caption_candidate_ambiguous"),
                    issue("basic_info_not_evaluated"),
                    issue("basic_info_partial"),
                    issue("basic_info_ambiguous"),
                    issue("annotation_not_found"),
                    issue("relation_write_failed", severity="error"),
                ),
                result_stats=stats(warning_count=6, error_count=1),
            )
        )

        summary = audit.summary(status="partial")

        self.assertEqual(6, summary["warning_count"])
        self.assertEqual(1, summary["error_count"])
        self.assertEqual(
            {
                "caption_candidate_not_found": 1,
                "caption_candidate_ambiguous": 1,
                "basic_info_not_evaluated": 1,
                "basic_info_partial": 1,
                "basic_info_ambiguous": 1,
                "annotation_not_found": 1,
                "relation_write_failed": 1,
            },
            summary["issue_summary"],
        )

    def test_table_caption_issue_categories_are_summarized_and_sanitized(self):
        from drawing_graph.audit import RelationBatchAudit

        audit = RelationBatchAudit.from_scope(scope())
        audit.record_enrichment_result(
            result(
                issues=(
                    issue("table_caption_missing_table", element_id="table-caption:missing"),
                    issue("table_caption_legacy_conflict", element_id="table-caption:conflict"),
                    issue(
                        "table_caption_write_failed",
                        severity="error",
                        message="password=hunter2 token=abc123 bolt://neo4j:hunter2@localhost:7687",
                        element_id="table-caption:failed",
                    ),
                ),
                result_stats=stats(
                    table_count=2,
                    table_caption_count=3,
                    table_caption_relation_count=1,
                    relation_count=4,
                    warning_count=2,
                    error_count=1,
                ),
            )
        )

        summary = audit.summary(status="partial")
        records = audit.log_records()
        serialized_records = repr(records)

        self.assertEqual(
            {
                "table_caption_missing_table": 1,
                "table_caption_legacy_conflict": 1,
                "table_caption_write_failed": 1,
            },
            summary["issue_summary"],
        )
        self.assertEqual(2, summary["warning_count"])
        self.assertEqual(1, summary["error_count"])
        self.assertNotIn("hunter2", serialized_records)
        self.assertNotIn("abc123", serialized_records)

    def test_cross_section_categories_counts_scope_and_sanitized_write_failure(self):
        from drawing_graph.audit import RelationBatchAudit

        audit = RelationBatchAudit.from_scope(scope())
        audit.record_enrichment_result(
            result(
                issues=(
                    issue("cross_section_unmatched", element_id="cross-section:unmatched"),
                    issue("section_candidate_ambiguous", element_id="cross-section:ambiguous"),
                    issue("section_candidate_low_evidence", element_id="cross-section:low-overlap"),
                    issue(
                        "section_mark_write_failed",
                        severity="error",
                        message="token=abc123 password=hunter2 bolt://neo4j:hunter2@localhost:7687",
                        element_id="cross-section:write-failed",
                    ),
                ),
                result_stats=stats(cross_section_count=5, candidate_count=2, ambiguous_count=1, relation_count=2, warning_count=3, error_count=1),
            )
        )

        summary = audit.summary(status="partial")
        records = audit.log_records()
        serialized_records = repr(records)

        self.assertEqual("relation-batch:001", summary["relation_batch_id"])
        self.assertEqual("relation-rules-v1", summary["rule_version"])
        self.assertEqual("project:road", summary["project_id"])
        self.assertEqual("set:road:set-a", summary["drawing_set_id"])
        self.assertEqual("page:road:set-a:road_24", summary["page_id"])
        self.assertEqual(5, summary["cross_section_count"])
        self.assertEqual(2, summary["relation_count"])
        self.assertEqual(3, summary["warning_count"])
        self.assertEqual(1, summary["error_count"])
        self.assertEqual(2, summary["candidate_count"])
        self.assertEqual(1, summary["ambiguous_count"])
        self.assertEqual(
            {
                "cross_section_unmatched": 1,
                "section_candidate_ambiguous": 1,
                "section_candidate_low_evidence": 1,
                "section_mark_write_failed": 1,
            },
            summary["issue_summary"],
        )
        self.assertTrue(
            any(
                record["relation_batch_id"] == "relation-batch:001"
                and record["rule_version"] == "relation-rules-v1"
                and record["page_id"] == "page:road:set-a:road_24"
                and record["category"] == "section_mark_write_failed"
                for record in records
            )
        )
        self.assertNotIn("abc123", serialized_records)
        self.assertNotIn("hunter2", serialized_records)
        self.assertNotIn("bolt://neo4j:hunter2@localhost:7687", serialized_records)

    def test_rejects_unknown_relation_issue_category(self):
        from drawing_graph.audit import AuditError, RelationBatchAudit

        audit = RelationBatchAudit.from_scope(scope())

        with self.assertRaises(AuditError) as context:
            audit.record_enrichment_result(result(issues=(issue("unexpected_category"),)))

        self.assertEqual("invalid_relation_issue_category", context.exception.category)

    def test_store_gets_batch_summary_by_relation_batch_id(self):
        from drawing_graph.audit import RelationAuditStore

        store = RelationAuditStore()
        audit = store.create_batch(scope())
        audit.record_enrichment_result(result())

        summary = store.get_summary("relation-batch:001", status="success")

        self.assertEqual("relation-batch:001", summary["relation_batch_id"])
        self.assertEqual(3, summary["relation_count"])
        self.assertIsNone(store.get_summary("relation-batch:missing"))

    def test_log_records_sanitize_credentials(self):
        from drawing_graph.audit import RelationBatchAudit

        audit = RelationBatchAudit.from_scope(scope())
        audit.record_enrichment_result(
            result(
                issues=(
                    issue(
                        "relation_write_failed",
                        severity="error",
                        message="token=abc123 password=hunter2 bolt://neo4j:hunter2@localhost:7687",
                    ),
                ),
                result_stats=stats(warning_count=0, error_count=1),
            )
        )

        records = audit.log_records()
        serialized_records = repr(records)

        self.assertEqual("relation-batch:001", records[0]["relation_batch_id"])
        self.assertEqual("relation_write_failed", records[0]["category"])
        self.assertNotIn("abc123", serialized_records)
        self.assertNotIn("hunter2", serialized_records)
        self.assertNotIn("bolt://neo4j:hunter2@localhost:7687", serialized_records)


if __name__ == "__main__":
    unittest.main()
