"""Offline contract tests for the 04 recognition execution-layer models."""

from __future__ import annotations

import unittest

from drawing_graph.recognition_models import (
    CostStatus,
    ProviderErrorCategory,
    RecognitionAttemptStatus,
    RecognitionExecutionStatus,
    RecognitionImageRole,
    RecognitionTaskType,
    UsageStatus,
)


class RecognitionTaskTypeTests(unittest.TestCase):
    """RecognitionTaskType must expose exactly the seven stable task types."""

    def test_contains_exactly_seven_design_tasks(self) -> None:
        expected = {
            "page_summary",
            "element_text_observation",
            "block_semantic_identification",
            "basic_info_interpretation",
            "table_interpretation",
            "section_label_observation",
            "relation_evidence_extraction",
        }
        actual = {item.value for item in RecognitionTaskType}
        self.assertEqual(expected, actual)
        self.assertEqual(7, len(RecognitionTaskType))

    def test_values_are_stable_lowercase_strings(self) -> None:
        for item in RecognitionTaskType:
            self.assertIsInstance(item.value, str)
            self.assertEqual(item.value, item.value.lower())

    def test_members_can_be_constructed_from_string(self) -> None:
        self.assertIs(RecognitionTaskType("page_summary"), RecognitionTaskType.PAGE_SUMMARY)

    def test_unknown_value_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RecognitionTaskType("unknown_task")


class RecognitionExecutionStatusTests(unittest.TestCase):
    """RecognitionExecutionStatus must match the design status set."""

    def test_contains_design_statuses(self) -> None:
        expected = {
            "succeeded",
            "partial",
            "ambiguous",
            "not_found",
            "contract_failed",
            "provider_failed",
            "deadline_exceeded",
            "recognition_failed",
        }
        self.assertEqual(expected, {item.value for item in RecognitionExecutionStatus})

    def test_unknown_status_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RecognitionExecutionStatus("unknown")


class RecognitionAttemptStatusTests(unittest.TestCase):
    """RecognitionAttemptStatus must keep attempt-level states distinct."""

    def test_contains_design_attempt_statuses(self) -> None:
        expected = {"succeeded", "retryable_failed", "terminal_failed", "contract_failed"}
        self.assertEqual(expected, {item.value for item in RecognitionAttemptStatus})

    def test_unknown_attempt_status_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RecognitionAttemptStatus("unknown")


class ProviderErrorCategoryTests(unittest.TestCase):
    """Provider error categories used by retry decisions."""

    def test_contains_design_categories(self) -> None:
        expected = {
            "authentication",
            "permission",
            "rate_limited",
            "temporary",
            "timeout",
            "permanent",
            "invalid_response",
        }
        self.assertEqual(expected, {item.value for item in ProviderErrorCategory})

    def test_unknown_category_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ProviderErrorCategory("unknown")


class UsageStatusTests(unittest.TestCase):
    """Usage status must distinguish unavailable from zero."""

    def test_contains_design_usage_statuses(self) -> None:
        self.assertEqual(
            {"available", "partial", "unavailable"},
            {item.value for item in UsageStatus},
        )

    def test_unknown_usage_status_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            UsageStatus("unknown")


class CostStatusTests(unittest.TestCase):
    """Cost status must separate calculated, estimated and unavailable."""

    def test_contains_design_cost_statuses(self) -> None:
        self.assertEqual(
            {"calculated", "estimated", "unavailable"},
            {item.value for item in CostStatus},
        )

    def test_unknown_cost_status_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CostStatus("unknown")


class RecognitionImageRoleTests(unittest.TestCase):
    """Image roles used by the preprocessor and prompt renderer."""

    def test_contains_design_roles(self) -> None:
        self.assertEqual(
            {"target", "context", "page"},
            {item.value for item in RecognitionImageRole},
        )

    def test_unknown_role_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RecognitionImageRole("unknown")


class RecognitionModelPurityTests(unittest.TestCase):
    """The models module must stay free of external-layer imports."""

    def test_module_does_not_import_forbidden_layers(self) -> None:
        from pathlib import Path

        import drawing_graph.recognition_models as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        import_lines = "\n".join(
            line.strip().lower()
            for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))
        )
        for forbidden in ("neo4j", "repository", "cypher", "httpx", "qwen", "facade", "os.environ"):
            self.assertNotIn(forbidden, import_lines)


if __name__ == "__main__":
    unittest.main()
