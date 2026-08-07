import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class ImportAuditTest(unittest.TestCase):
    def test_counts_accumulate_for_pages_and_warnings(self):
        from drawing_graph.audit import ImportAudit

        audit = ImportAudit(batch_id="batch-001")
        audit.record_page_success("data/set-a/road_1.json")
        audit.record_page_skipped("data/set-a/road_2.json", "missing_image", "same-name PNG missing")
        audit.record_page_failure("data/set-a/road_3.json", "json_parse_error", "invalid JSON")
        audit.record_element_warning("data/set-a/road_1.json", 3, "coordinate_out_of_bounds", "bbox outside image")

        summary = audit.summary()

        self.assertEqual(3, summary["total_count"])
        self.assertEqual(1, summary["success_count"])
        self.assertEqual(1, summary["skipped_count"])
        self.assertEqual(1, summary["failed_count"])
        self.assertEqual(1, summary["warning_count"])

    def test_file_errors_keep_category_source_and_sanitized_reason(self):
        from drawing_graph.audit import ImportAudit

        audit = ImportAudit(batch_id="batch-001")
        audit.record_page_failure(
            "data/set-a/road_3.json",
            "neo4j_connection_failed",
            "could not connect to neo4j://user:secret@localhost:7687 with password=secret",
        )

        error = audit.file_errors[0]

        self.assertEqual("neo4j_connection_failed", error.category)
        self.assertEqual("data/set-a/road_3.json", error.source_path)
        self.assertNotIn("secret", error.message)
        self.assertNotIn("neo4j://user:secret@localhost:7687", error.message)

    def test_duplicate_shapes_are_recorded_without_changing_page_counts(self):
        from drawing_graph.audit import ImportAudit

        audit = ImportAudit(batch_id="batch-001")
        audit.record_duplicate_shape("data/set-a/road_1.json", "abc123", first_shape_index=2, duplicate_shape_index=7)

        summary = audit.summary()

        self.assertEqual(0, summary["total_count"])
        self.assertEqual(1, summary["duplicate_shape_count"])
        self.assertEqual("abc123", audit.duplicate_shapes[0].shape_hash)
        self.assertEqual(2, audit.duplicate_shapes[0].first_shape_index)
        self.assertEqual(7, audit.duplicate_shapes[0].duplicate_shape_index)

    def test_batch_summary_contains_status_and_error_summary(self):
        from drawing_graph.audit import ImportAudit

        audit = ImportAudit(batch_id="batch-001")
        audit.record_page_skipped("data/set-a/road_2.json", "missing_image", "same-name PNG missing")
        audit.record_page_failure("data/set-a/road_3.json", "json_parse_error", "invalid JSON")
        audit.record_page_failure("data/set-a/road_4.json", "json_parse_error", "invalid JSON")

        summary = audit.summary(status="failed")

        self.assertEqual("batch-001", summary["batch_id"])
        self.assertEqual("failed", summary["status"])
        self.assertEqual({"missing_image": 1, "json_parse_error": 2}, summary["error_summary"])
        self.assertIn("started_at", summary)
        self.assertIn("finished_at", summary)

    def test_rejects_invalid_batch_status(self):
        from drawing_graph.audit import AuditError, ImportAudit

        audit = ImportAudit(batch_id="batch-001")

        with self.assertRaises(AuditError) as context:
            audit.summary(status="done")

        self.assertEqual("invalid_batch_status", context.exception.category)

    def test_log_records_are_sanitized_and_minimal(self):
        from drawing_graph.audit import ImportAudit

        audit = ImportAudit(batch_id="batch-001")
        audit.record_page_failure(
            "data/set-a/road_3.json",
            "auth_error",
            "token=abc123 password=hunter2 bolt://neo4j:hunter2@localhost:7687",
        )

        log_records = audit.log_records()
        serialized_records = repr(log_records)

        self.assertEqual("batch-001", log_records[0]["batch_id"])
        self.assertEqual("auth_error", log_records[0]["category"])
        self.assertNotIn("abc123", serialized_records)
        self.assertNotIn("hunter2", serialized_records)
        self.assertNotIn("bolt://neo4j:hunter2@localhost:7687", serialized_records)


if __name__ == "__main__":
    unittest.main()
