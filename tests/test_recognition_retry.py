"""Offline contract tests for provider error classification and retry."""

from __future__ import annotations

import unittest

import httpx

from drawing_graph.recognition_retry import (
    RecognitionProviderError,
    classify_http_status,
    classify_exception,
    parse_retry_after,
)


class ProviderErrorClassificationTests(unittest.TestCase):
    """HTTP, transport and timeout errors map to stable provider categories."""

    def test_429_is_retryable_rate_limited_with_retry_after(self) -> None:
        error = classify_http_status(429, retry_after_header="5")
        self.assertEqual("rate_limited", error.category.value)
        self.assertTrue(error.retryable)
        self.assertEqual(5.0, error.retry_after_seconds)

    def test_retry_after_unparseable_or_over_cap_yields_none(self) -> None:
        self.assertIsNone(parse_retry_after("abc"))
        self.assertIsNone(parse_retry_after("99999"))
        self.assertEqual(2.5, parse_retry_after("2.5"))

    def test_temporary_5xx_is_retryable(self) -> None:
        for status in (500, 502, 503, 504):
            with self.subTest(status=status):
                error = classify_http_status(status)
                self.assertEqual("temporary", error.category.value)
                self.assertTrue(error.retryable)

    def test_408_is_retryable_timeout(self) -> None:
        error = classify_http_status(408)
        self.assertEqual("timeout", error.category.value)
        self.assertTrue(error.retryable)

    def test_authentication_and_permission_are_terminal(self) -> None:
        auth = classify_http_status(401)
        self.assertEqual("authentication", auth.category.value)
        self.assertFalse(auth.retryable)
        permission = classify_http_status(403)
        self.assertEqual("permission", permission.category.value)
        self.assertFalse(permission.retryable)

    def test_other_4xx_is_permanent_terminal(self) -> None:
        for status in (400, 404, 422):
            with self.subTest(status=status):
                error = classify_http_status(status)
                self.assertEqual("permanent", error.category.value)
                self.assertFalse(error.retryable)

    def test_timeout_exception_is_retryable_timeout(self) -> None:
        error = classify_exception(httpx.TimeoutException("slow"))
        self.assertEqual("timeout", error.category.value)
        self.assertTrue(error.retryable)

    def test_connection_error_is_retryable_temporary(self) -> None:
        error = classify_exception(httpx.ConnectError("reset"))
        self.assertEqual("temporary", error.category.value)
        self.assertTrue(error.retryable)

    def test_error_object_holds_only_safe_fields(self) -> None:
        error = RecognitionProviderError(
            category="invalid_response",
            retryable=False,
            safe_message="provider returned malformed JSON",
        )
        self.assertEqual("invalid_response", error.category.value)
        self.assertFalse(error.retryable)
        self.assertIsNone(error.retry_after_seconds)
        self.assertFalse(hasattr(error, "headers"))
        self.assertFalse(hasattr(error, "body"))

    def test_error_validation_rejects_unknown_category_and_negative_retry_after(self) -> None:
        with self.assertRaises(ValueError):
            RecognitionProviderError(category="bogus", retryable=False, safe_message="x")
        with self.assertRaises(ValueError):
            RecognitionProviderError(
                category="temporary",
                retryable=True,
                safe_message="x",
                retry_after_seconds=-1,
            )


if __name__ == "__main__":
    unittest.main()
