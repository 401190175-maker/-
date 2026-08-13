"""Graph-external append-only attempt log port and in-memory implementation."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from .recognition_models import RecognitionAttempt
from .recognition_redaction import RecognitionRedactor


class RecognitionAttemptLogPort(Protocol):
    """Persistence boundary for graph-external recognition attempts."""

    def append_attempt(self, attempt: RecognitionAttempt) -> RecognitionAttempt:
        """Append one attempt idempotently and return the stored record."""

    def list_attempts(self, recognition_run_id: str) -> tuple[RecognitionAttempt, ...]:
        """Return attempts for one run in append order."""


class InMemoryRecognitionAttemptLog:
    """Append-only in-memory attempt log with redacted summaries."""

    def __init__(self):
        self._attempts: dict[str, RecognitionAttempt] = {}
        self._by_run: dict[str, list[str]] = {}
        self._redactor = RecognitionRedactor()

    def append_attempt(self, attempt: RecognitionAttempt) -> RecognitionAttempt:
        """Store one attempt by id; existing ids are never overwritten."""

        if not isinstance(attempt, RecognitionAttempt):
            raise ValueError("attempt must be a RecognitionAttempt")
        existing = self._attempts.get(attempt.attempt_id)
        if existing is not None:
            return existing
        stored = self._sanitize(attempt)
        self._attempts[stored.attempt_id] = stored
        self._by_run.setdefault(stored.recognition_run_id, []).append(stored.attempt_id)
        return stored

    def list_attempts(self, recognition_run_id: str) -> tuple[RecognitionAttempt, ...]:
        """Return stored attempts for one run in append order."""

        if not isinstance(recognition_run_id, str) or not recognition_run_id.strip():
            raise ValueError("recognition_run_id must be a non-empty string")
        return tuple(
            self._attempts[attempt_id]
            for attempt_id in self._by_run.get(recognition_run_id, ())
        )

    def _sanitize(self, attempt: RecognitionAttempt) -> RecognitionAttempt:
        if attempt.safe_error_summary is None:
            return attempt
        redacted = self._redactor.redact_payload({"message": attempt.safe_error_summary})["message"]
        return replace(attempt, safe_error_summary=redacted)


__all__ = ("InMemoryRecognitionAttemptLog", "RecognitionAttemptLogPort")
