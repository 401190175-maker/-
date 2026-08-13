"""Offline contract tests for the graph-external attempt log."""

from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

from drawing_graph.recognition_attempt_log import (
    InMemoryRecognitionAttemptLog,
    RecognitionAttemptLogPort,
)
from drawing_graph.recognition_models import RecognitionAttempt


def _attempt(
    *,
    attempt_id: str = "attempt-1",
    recognition_run_id: str = "run-1",
    attempt_number: int = 1,
    latency_ms: float = 10.0,
    safe_error_summary: str | None = None,
) -> RecognitionAttempt:
    return RecognitionAttempt(
        attempt_id=attempt_id,
        recognition_run_id=recognition_run_id,
        attempt_number=attempt_number,
        task_type="page_summary",
        provider="qwen",
        model_name="qwen3-vl-plus",
        request_fingerprint=f"fp-{attempt_id}",
        prompt_version="prompt-v1",
        output_contract_version="1",
        status="succeeded",
        latency_ms=latency_ms,
        safe_error_summary=safe_error_summary,
    )


class RecognitionAttemptLogTests(unittest.TestCase):
    """Attempts are appended once, never overwritten and listable by run."""

    def test_append_and_list_roundtrip(self) -> None:
        log = InMemoryRecognitionAttemptLog()
        attempt = _attempt()
        stored = log.append_attempt(attempt)
        self.assertIs(attempt, stored)
        self.assertEqual((attempt,), log.list_attempts("run-1"))

    def test_append_is_idempotent_by_attempt_id(self) -> None:
        log = InMemoryRecognitionAttemptLog()
        attempt = _attempt()
        log.append_attempt(attempt)
        log.append_attempt(attempt)
        self.assertEqual(1, len(log.list_attempts("run-1")))

    def test_existing_record_is_not_overwritten(self) -> None:
        log = InMemoryRecognitionAttemptLog()
        original = _attempt(latency_ms=10.0)
        log.append_attempt(original)
        modified = replace(original, latency_ms=99.0)
        log.append_attempt(modified)
        self.assertEqual(10.0, log.list_attempts("run-1")[0].latency_ms)

    def test_list_preserves_append_order(self) -> None:
        log = InMemoryRecognitionAttemptLog()
        first = _attempt(attempt_id="attempt-1", attempt_number=1)
        second = _attempt(attempt_id="attempt-2", attempt_number=2)
        third = _attempt(attempt_id="attempt-3", attempt_number=3)
        log.append_attempt(first)
        log.append_attempt(second)
        log.append_attempt(third)
        self.assertEqual(
            ["attempt-1", "attempt-2", "attempt-3"],
            [attempt.attempt_id for attempt in log.list_attempts("run-1")],
        )

    def test_list_unknown_run_returns_empty_tuple(self) -> None:
        log = InMemoryRecognitionAttemptLog()
        log.append_attempt(_attempt())
        self.assertEqual((), log.list_attempts("unknown-run"))

    def test_append_rejects_non_attempt_objects(self) -> None:
        log = InMemoryRecognitionAttemptLog()
        with self.assertRaises(ValueError):
            log.append_attempt("not-an-attempt")

    def test_attempt_dto_cannot_carry_secret_or_prompt_fields(self) -> None:
        with self.assertRaises(TypeError):
            _attempt(api_key="secret")
        with self.assertRaises(TypeError):
            _attempt(prompt="full prompt")
        with self.assertRaises(TypeError):
            _attempt(authorization="Bearer x")

    def test_log_redacts_unsafe_error_summary(self) -> None:
        log = InMemoryRecognitionAttemptLog()
        attempt = _attempt(
            safe_error_summary="failed reading C:\\Users\\me\\drawings\\page-1.png",
        )
        stored = log.append_attempt(attempt)
        self.assertNotIn("C:\\Users", stored.safe_error_summary)
        self.assertEqual("<redacted>", stored.safe_error_summary)

    def test_port_contract_and_purity(self) -> None:
        self.assertTrue(hasattr(RecognitionAttemptLogPort, "append_attempt"))
        self.assertTrue(hasattr(RecognitionAttemptLogPort, "list_attempts"))

        import drawing_graph.recognition_attempt_log as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        import_lines = "\n".join(
            line.strip().lower()
            for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))
        )
        for forbidden in ("neo4j", "repository", "cypher", "httpx", "qwen", "facade", "os.environ", "pathlib"):
            self.assertNotIn(forbidden, import_lines)


if __name__ == "__main__":
    unittest.main()
