"""Tests for the constrained answer text generation port, fake and validator."""

import inspect
from pathlib import Path
import unittest

from drawing_graph.assistant_answer_text import (
    ConstrainedAnswerTextGenerator,
    ConstrainedClaimInput,
    ConstrainedTextRequest,
    ConstrainedTextResult,
    ConstrainedTextValidator,
    FakeConstrainedTextGenerator,
    TextGenerationError,
    render_text_with_fallback,
)
from drawing_graph.assistant_models import ReasonCode


class TextPortContractTests(unittest.TestCase):
    def test_request_carries_only_approved_fields(self):
        request = ConstrainedTextRequest(
            claims=(
                ConstrainedClaimInput(
                    claim_id="claim:1",
                    statement="该图块是标题",
                    status="qualified",
                    qualifiers=("low_confidence",),
                ),
            ),
            citation_ids=("citation:1",),
            sections=("conclusion", "evidence"),
        )
        self.assertEqual("claim:1", request.claims[0].claim_id)
        self.assertEqual("low_confidence", request.claims[0].qualifiers[0])
        self.assertFalse(hasattr(request.claims[0], "payload"))
        self.assertFalse(hasattr(request.claims[0], "image_path"))
        self.assertFalse(hasattr(request.claims[0], "evidence_id"))

    def test_fake_returns_deterministic_result(self):
        fake = FakeConstrainedTextGenerator()
        request = ConstrainedTextRequest(
            claims=(
                ConstrainedClaimInput(claim_id="claim:1", statement="该图块是标题", status="supported"),
            ),
            citation_ids=("citation:1",),
        )
        first = fake.generate(request)
        second = fake.generate(request)
        self.assertEqual(first, second)
        self.assertEqual(("claim:1",), first.used_claim_ids)
        self.assertEqual(("citation:1",), first.used_citation_ids)

    def test_port_raises_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            ConstrainedAnswerTextGenerator().generate(ConstrainedTextRequest(claims=()))

    def test_module_does_not_access_network_or_env(self):
        import drawing_graph.assistant_answer_text as module

        source = Path(inspect.getfile(module)).read_text(encoding="utf-8")
        self.assertNotIn("import os", source)
        self.assertNotIn("socket", source)
        self.assertNotIn("requests", source)
        self.assertNotIn("urllib", source)


class TextIdentifierAllowlistTests(unittest.TestCase):
    def _request(self):
        return ConstrainedTextRequest(
            claims=(
                ConstrainedClaimInput(claim_id="claim:1", statement="该图块是标题", status="supported"),
                ConstrainedClaimInput(claim_id="claim:2", statement="该图块是表格", status="supported"),
            ),
            citation_ids=("citation:1", "citation:2"),
        )

    def test_valid_result_passes(self):
        result = ConstrainedTextResult(
            sections=("text",),
            used_claim_ids=("claim:1", "claim:2"),
            used_citation_ids=("citation:1",),
        )
        validated = ConstrainedTextValidator().validate(self._request(), result)
        self.assertTrue(validated.valid)

    def test_missing_claim_id_rejected(self):
        result = ConstrainedTextResult(
            sections=("text",),
            used_claim_ids=("claim:1",),
            used_citation_ids=(),
        )
        validated = ConstrainedTextValidator().validate(self._request(), result)
        self.assertFalse(validated.valid)
        self.assertIn(ReasonCode.TEXT_OUTPUT_INVALID, validated.reason_codes)

    def test_unknown_claim_id_rejected(self):
        result = ConstrainedTextResult(
            sections=("text",),
            used_claim_ids=("claim:1", "claim:2", "claim:3"),
            used_citation_ids=(),
        )
        validated = ConstrainedTextValidator().validate(self._request(), result)
        self.assertFalse(validated.valid)

    def test_duplicate_claim_id_rejected(self):
        result = ConstrainedTextResult(
            sections=("text",),
            used_claim_ids=("claim:1", "claim:2", "claim:1"),
            used_citation_ids=(),
        )
        validated = ConstrainedTextValidator().validate(self._request(), result)
        self.assertFalse(validated.valid)

    def test_unknown_citation_rejected(self):
        result = ConstrainedTextResult(
            sections=("text",),
            used_claim_ids=("claim:1", "claim:2"),
            used_citation_ids=("citation:9",),
        )
        validated = ConstrainedTextValidator().validate(self._request(), result)
        self.assertFalse(validated.valid)


class TextSemanticGateTests(unittest.TestCase):
    def _request(self):
        return ConstrainedTextRequest(
            claims=(
                ConstrainedClaimInput(
                    claim_id="claim:1",
                    statement="该图块是标题",
                    status="qualified",
                    qualifiers=("待复核",),
                ),
            ),
            citation_ids=("citation:1",),
        )

    def test_required_qualifier_deletion_rejected(self):
        result = ConstrainedTextResult(
            sections=("该图块是标题",),
            used_claim_ids=("claim:1",),
            used_citation_ids=("citation:1",),
        )
        validated = ConstrainedTextValidator().validate(self._request(), result)
        self.assertFalse(validated.valid)

    def test_qualifier_present_passes(self):
        result = ConstrainedTextResult(
            sections=("该图块是标题（待复核）",),
            used_claim_ids=("claim:1",),
            used_citation_ids=("citation:1",),
        )
        validated = ConstrainedTextValidator().validate(self._request(), result)
        self.assertTrue(validated.valid)

    def test_new_number_rejected(self):
        result = ConstrainedTextResult(
            sections=("该图块是标题（待复核）编号42",),
            used_claim_ids=("claim:1",),
            used_citation_ids=("citation:1",),
        )
        validated = ConstrainedTextValidator().validate(self._request(), result)
        self.assertFalse(validated.valid)

    def test_new_business_id_rejected(self):
        result = ConstrainedTextResult(
            sections=("该图块是标题（待复核）见 block:999",),
            used_claim_ids=("claim:1",),
            used_citation_ids=("citation:1",),
        )
        validated = ConstrainedTextValidator().validate(self._request(), result)
        self.assertFalse(validated.valid)


class TextFallbackTests(unittest.TestCase):
    def _request(self):
        return ConstrainedTextRequest(
            claims=(
                ConstrainedClaimInput(claim_id="claim:1", statement="该图块是标题", status="supported"),
            ),
            citation_ids=("citation:1",),
        )

    def test_no_generator_returns_template_without_warning(self):
        text, warnings = render_text_with_fallback(
            None,
            self._request(),
            ConstrainedTextValidator(),
            "模板文本",
        )
        self.assertEqual("模板文本", text)
        self.assertEqual((), warnings)

    def test_generator_exception_falls_back(self):
        class Raising(FakeConstrainedTextGenerator):
            def generate(self, request):
                raise TextGenerationError("provider exploded")

        text, warnings = render_text_with_fallback(
            Raising(),
            self._request(),
            ConstrainedTextValidator(),
            "模板文本",
        )
        self.assertEqual("模板文本", text)
        self.assertEqual(("text_generation_failed",), warnings)

    def test_timeout_falls_back(self):
        class TimingOut(FakeConstrainedTextGenerator):
            def generate(self, request):
                raise TimeoutError()

        text, warnings = render_text_with_fallback(
            TimingOut(),
            self._request(),
            ConstrainedTextValidator(),
            "模板文本",
        )
        self.assertEqual("模板文本", text)
        self.assertEqual(("text_generation_failed",), warnings)

    def test_invalid_result_falls_back(self):
        class Missing(FakeConstrainedTextGenerator):
            def generate(self, request):
                return ConstrainedTextResult(
                    sections=("s",),
                    used_claim_ids=(),
                    used_citation_ids=(),
                )

        text, warnings = render_text_with_fallback(
            Missing(),
            self._request(),
            ConstrainedTextValidator(),
            "模板文本",
        )
        self.assertEqual("模板文本", text)
        self.assertEqual(("text_output_invalid",), warnings)

    def test_valid_result_returns_generated_text(self):
        text, warnings = render_text_with_fallback(
            FakeConstrainedTextGenerator(),
            self._request(),
            ConstrainedTextValidator(),
            "模板文本",
        )
        self.assertIn("该图块是标题", text)
        self.assertEqual((), warnings)

    def test_no_provider_response_leak(self):
        class Raising(FakeConstrainedTextGenerator):
            def generate(self, request):
                raise TextGenerationError("provider secret token 12345")

        text, warnings = render_text_with_fallback(
            Raising(),
            self._request(),
            ConstrainedTextValidator(),
            "模板文本",
        )
        self.assertNotIn("secret", text)
        self.assertNotIn("12345", text)
        self.assertNotIn("secret", " ".join(warnings))

    def test_slow_generator_times_out(self):
        import time

        class Slow(FakeConstrainedTextGenerator):
            def generate(self, request):
                time.sleep(0.3)
                return ConstrainedTextResult(
                    sections=("s",),
                    used_claim_ids=("claim:1",),
                    used_citation_ids=(),
                )

        text, warnings = render_text_with_fallback(
            Slow(),
            self._request(),
            ConstrainedTextValidator(),
            "模板文本",
            timeout_seconds=0.05,
        )
        self.assertEqual("模板文本", text)
        self.assertEqual(("text_generation_failed",), warnings)


if __name__ == "__main__":
    unittest.main()
