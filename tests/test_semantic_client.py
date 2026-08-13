"""Offline contract tests for the narrowed prepared-image provider port."""

from __future__ import annotations

import unittest
from pathlib import Path

from drawing_graph.recognition_image_preprocessing import PreparedRecognitionImage
from drawing_graph.recognition_models import RecognitionImageRole, RecognitionProviderUsage
from drawing_graph.recognition_prompting import RenderedRecognitionPrompt
from drawing_graph.recognition_retry import RecognitionProviderError
from drawing_graph.semantic_client import (
    FakeMultimodalRecognitionClient,
    MultimodalRecognitionClient,
    RecognitionClientRequest,
    RecognitionClientResult,
)
from drawing_graph.tool_models import BBox, ToolModelError


def _prompt() -> RenderedRecognitionPrompt:
    return RenderedRecognitionPrompt(
        system_instruction="system",
        user_instruction="user",
        schema_id="output/page-summary",
        schema_version="1",
        prompt_version="prompt-v1",
        fingerprint="f" * 64,
        image_role_order=("page",),
    )


def _image() -> PreparedRecognitionImage:
    return PreparedRecognitionImage(
        role=RecognitionImageRole.PAGE,
        mime="image/png",
        content=b"\x89PNG\r\n\x1a\n",
        source_hash="a" * 64,
        prepared_hash="b" * 64,
        source_size=(100, 80),
        crop_bbox=BBox(0, 0, 100, 80),
        padding=0,
        output_size=(100, 80),
        scale=1.0,
        preprocessing_version="preprocess-v1",
    )


def _request(**overrides) -> RecognitionClientRequest:
    values = {
        "model_profile": "qwen3-vl-plus",
        "rendered_prompt": _prompt(),
        "prepared_images": (_image(),),
        "output_contract_version": "1",
        "timeout_seconds": 60.0,
        "request_fingerprint": "fp-1",
    }
    values.update(overrides)
    return RecognitionClientRequest(**values)


class ProviderPortContractTests(unittest.TestCase):
    """RecognitionClientRequest must carry only provider inputs."""

    def test_request_carries_rendered_prompt_images_and_contract(self) -> None:
        request = _request()
        self.assertEqual("qwen3-vl-plus", request.model_profile)
        self.assertIsInstance(request.rendered_prompt, RenderedRecognitionPrompt)
        self.assertEqual(1, len(request.prepared_images))
        self.assertEqual("1", request.output_contract_version)
        self.assertEqual(60.0, request.timeout_seconds)
        self.assertEqual("fp-1", request.request_fingerprint)

    def test_request_has_no_local_image_path_or_page_id(self) -> None:
        request = _request()
        self.assertFalse(hasattr(request, "image_path"))
        self.assertFalse(hasattr(request, "page_id"))
        self.assertFalse(hasattr(request, "context"))

    def test_request_rejects_credentials_and_headers(self) -> None:
        with self.assertRaises(TypeError):
            _request(api_key="secret")
        with self.assertRaises(TypeError):
            _request(authorization="Bearer secret")
        with self.assertRaises(TypeError):
            _request(image_path=r"C:\drawings\page-1.png")

    def test_request_timeout_must_be_positive(self) -> None:
        with self.assertRaises(ToolModelError):
            _request(timeout_seconds=0)

    def test_request_requires_prepared_images_tuple(self) -> None:
        with self.assertRaises(ToolModelError):
            _request(prepared_images=[_image()])
        with self.assertRaises(ToolModelError):
            _request(prepared_images=("not-an-image",))

    def test_request_requires_rendered_prompt(self) -> None:
        with self.assertRaises(ToolModelError):
            _request(rendered_prompt="plain text")

    def test_result_contains_only_adapted_payload_and_metadata(self) -> None:
        result = RecognitionClientResult(
            payload={"summary": "page text"},
            provider_request_id="req-id-1",
            model_name="qwen3-vl-plus",
            model_version="qwen3-vl-plus-v1",
            usage=RecognitionProviderUsage(input_tokens=10, output_tokens=5, status="available"),
        )
        self.assertEqual({"summary": "page text"}, result.payload)
        self.assertEqual("req-id-1", result.provider_request_id)
        self.assertEqual(10, result.usage.input_tokens)

    def test_result_rejects_header_or_traceback_fields(self) -> None:
        with self.assertRaises(TypeError):
            RecognitionClientResult(payload={}, headers={"authorization": "x"})
        with self.assertRaises(TypeError):
            RecognitionClientResult(payload={}, traceback="tb")

    def test_protocol_is_implemented_by_fake(self) -> None:
        self.assertTrue(issubclass(FakeMultimodalRecognitionClient, MultimodalRecognitionClient))


class FakeProviderScriptTests(unittest.TestCase):
    """The fake must deterministically simulate every provider failure mode."""

    def test_success_returns_payload_and_records_request(self) -> None:
        client = FakeMultimodalRecognitionClient(script=({"summary": "x"},))
        result = client.recognize(_request())
        self.assertIsInstance(result, RecognitionClientResult)
        self.assertEqual({"summary": "x"}, result.payload)
        self.assertEqual("fake-multimodal", result.model_name)
        self.assertEqual(1, len(client.requests))
        self.assertEqual("fp-1", client.requests[0].request_fingerprint)

    def test_failure_tokens_raise_classified_provider_errors(self) -> None:
        expected = {
            "http_429": ("rate_limited", True),
            "http_5xx": ("temporary", True),
            "timeout": ("timeout", True),
            "invalid_json": ("invalid_response", False),
            "schema_failure": ("invalid_response", False),
        }
        for token, (category, retryable) in expected.items():
            with self.subTest(token=token):
                client = FakeMultimodalRecognitionClient(script=(token,))
                with self.assertRaises(RecognitionProviderError) as caught:
                    client.recognize(_request())
                self.assertEqual(category, caught.exception.category.value)
                self.assertEqual(retryable, caught.exception.retryable)

    def test_retry_after_tuple_token_is_honored(self) -> None:
        client = FakeMultimodalRecognitionClient(script=(("http_429", 5),))
        with self.assertRaises(RecognitionProviderError) as caught:
            client.recognize(_request())
        self.assertEqual(5.0, caught.exception.retry_after_seconds)

    def test_script_is_consumed_in_order(self) -> None:
        client = FakeMultimodalRecognitionClient(script=({"summary": "first"}, {"summary": "second"}))
        self.assertEqual("first", client.recognize(_request()).payload["summary"])
        self.assertEqual("second", client.recognize(_request()).payload["summary"])

    def test_exhausted_script_repeats_last_outcome_deterministically(self) -> None:
        client = FakeMultimodalRecognitionClient(script=({"summary": "last"},))
        self.assertEqual("last", client.recognize(_request()).payload["summary"])
        self.assertEqual("last", client.recognize(_request()).payload["summary"])

    def test_empty_script_returns_empty_success_payload(self) -> None:
        client = FakeMultimodalRecognitionClient()
        self.assertEqual({}, client.recognize(_request()).payload)

    def test_unknown_script_token_is_rejected(self) -> None:
        client = FakeMultimodalRecognitionClient(script=("bogus",))
        with self.assertRaises(ValueError):
            client.recognize(_request())

    def test_provider_port_module_is_pure(self) -> None:
        import drawing_graph.semantic_client as module

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
