"""Offline contract tests for the fail-closed recognition redactor."""

from __future__ import annotations

import unittest
from pathlib import Path

from drawing_graph.recognition_redaction import (
    RecognitionRedactionError,
    RecognitionRedactor,
    SafeRecognitionError,
)
from drawing_graph.recognition_retry import RecognitionProviderError
from drawing_graph.tool_models import ToolModelError


class RecognitionRedactorTests(unittest.TestCase):
    """Secrets, paths, binaries and unknown objects must be masked recursively."""

    def test_redact_error_extracts_category_code_and_safe_message(self) -> None:
        error = RecognitionProviderError(
            category="rate_limited",
            retryable=True,
            safe_message="provider is rate limited",
            retry_after_seconds=5.0,
        )
        safe = RecognitionRedactor().redact_error(error)
        self.assertIsInstance(safe, SafeRecognitionError)
        self.assertEqual("rate_limited", safe.code)
        self.assertEqual("rate_limited", safe.category)
        self.assertEqual("provider is rate limited", safe.safe_message)

    def test_redact_error_masks_paths_in_message(self) -> None:
        error = ToolModelError("RECOGNITION_FAILED", "failed reading C:\\Users\\me\\drawings\\page-1.png")
        safe = RecognitionRedactor().redact_error(error)
        self.assertNotIn("C:\\Users", safe.safe_message)
        self.assertNotIn("page-1.png", safe.safe_message)

    def test_redact_error_unknown_exception_uses_fallback_category(self) -> None:
        safe = RecognitionRedactor().redact_error(ValueError("boom"))
        self.assertEqual("recognition_failed", safe.category)
        self.assertEqual("recognition failed", safe.safe_message)

    def test_redact_error_keeps_run_and_attempt_ids_when_provided(self) -> None:
        safe = SafeRecognitionError(
            code="recognition_failed",
            category="recognition_failed",
            safe_message="failed",
            run_id="run-1",
            attempt_id="attempt-1",
        )
        self.assertEqual("run-1", safe.run_id)
        self.assertEqual("attempt-1", safe.attempt_id)

    def test_redact_payload_masks_nested_secret_fields(self) -> None:
        payload = {
            "summary": "page",
            "provider": {
                "api_key": "sk-123",
                "Authorization": "Bearer abc",
                "token": "tok",
                "password": "pw",
                "secret": "s",
                "cookie": "c",
                "prompt": "full prompt",
                "traceback": "Traceback (most recent call last):",
                "headers": {"x-auth": "x"},
                "safe": "keep",
            },
            "items": [{"api_key": "nested-secret", "keep": 1}],
        }
        redacted = RecognitionRedactor().redact_payload(payload)
        self.assertEqual("page", redacted["summary"])
        self.assertEqual("<redacted>", redacted["provider"]["api_key"])
        self.assertEqual("<redacted>", redacted["provider"]["Authorization"])
        self.assertEqual("<redacted>", redacted["provider"]["token"])
        self.assertEqual("<redacted>", redacted["provider"]["password"])
        self.assertEqual("<redacted>", redacted["provider"]["secret"])
        self.assertEqual("<redacted>", redacted["provider"]["cookie"])
        self.assertEqual("<redacted>", redacted["provider"]["prompt"])
        self.assertEqual("<redacted>", redacted["provider"]["traceback"])
        self.assertEqual("<redacted>", redacted["provider"]["headers"])
        self.assertEqual("keep", redacted["provider"]["safe"])
        self.assertEqual("<redacted>", redacted["items"][0]["api_key"])
        self.assertEqual(1, redacted["items"][0]["keep"])

    def test_redact_payload_masks_paths_base64_data_urls_and_bytes(self) -> None:
        payload = {
            "image_path": r"C:\Users\me\drawings\page-1.png",
            "unix_path": "/home/me/page.png",
            "base64": "aGVsbG8gd29ybGQgdGhpcyBpcyBhIGxvbmcgYmFzZTY0IHN0cmluZyB3aXRoIG1vcmUgdGV4dA==",
            "data_url": "data:image/png;base64,aGVsbG8=",
            "image_bytes": b"\x89PNG\r\n",
            "keep_text": "summary text",
        }
        redacted = RecognitionRedactor().redact_payload(payload)
        self.assertEqual("<redacted>", redacted["image_path"])
        self.assertEqual("<redacted>", redacted["unix_path"])
        self.assertEqual("<redacted>", redacted["base64"])
        self.assertEqual("<redacted>", redacted["data_url"])
        self.assertEqual("<redacted>", redacted["image_bytes"])
        self.assertEqual("summary text", redacted["keep_text"])

    def test_redact_payload_replaces_unknown_objects(self) -> None:
        redacted = RecognitionRedactor().redact_payload({"weird": object(), "set": {1, 2}})
        self.assertEqual("<redacted>", redacted["weird"])
        self.assertEqual("<redacted>", redacted["set"])

    def test_redact_payload_keeps_safe_fields(self) -> None:
        payload = {
            "summary": "page text",
            "target_id": "target-page",
            "confidence": 0.9,
            "status": "succeeded",
            "count": 3,
            "flag": True,
            "none": None,
        }
        self.assertEqual(payload, RecognitionRedactor().redact_payload(payload))

    def test_redact_trace_recurses_and_keeps_ids(self) -> None:
        trace = {
            "recognition_run_id": "run-1",
            "attempt_id": "attempt-1",
            "error_category": "temporary",
            "api_key": "sk-1",
        }
        redacted = RecognitionRedactor().redact_trace(trace)
        self.assertEqual("run-1", redacted["recognition_run_id"])
        self.assertEqual("attempt-1", redacted["attempt_id"])
        self.assertEqual("temporary", redacted["error_category"])
        self.assertEqual("<redacted>", redacted["api_key"])

    def test_redaction_fails_closed_on_unexpected_error(self) -> None:
        class BadMapping(dict):
            def items(self):
                raise RuntimeError("boom")

        with self.assertRaises(RecognitionRedactionError):
            RecognitionRedactor().redact_payload(BadMapping({"x": 1}))

    def test_redactor_module_is_pure(self) -> None:
        import drawing_graph.recognition_redaction as module

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
