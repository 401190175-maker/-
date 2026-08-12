import json
import sys
import unittest
from pathlib import Path
from uuid import uuid4

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.qwen_semantic_client import QwenMultimodalRecognitionClient, QwenRecognitionConfig
from drawing_graph.semantic_client import RecognitionClientRequest
from drawing_graph.tool_models import BBox, ToolModelError


class QwenSemanticClientTest(unittest.TestCase):
    def test_recognize_posts_openai_compatible_payload_and_parses_structured_output(self):
        captured = {}

        def handler(request):
            captured["headers"] = dict(request.headers)
            captured["payload"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                200,
                json={
                    "model": "qwen3-vl-plus",
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "status": "succeeded",
                                        "observations": [
                                            {
                                                "target_element_id": "block:1",
                                                "target_element_type": "DrawingBlock",
                                                "raw_text": "A1",
                                                "normalized_text": "A1",
                                                "confidence": 0.91,
                                                "status": "confirmed",
                                            }
                                        ],
                                        "interpretations": [
                                            {
                                                "target_element_id": "block:1",
                                                "target_element_type": "DrawingBlock",
                                                "summary": "钢筋混凝土构件详图",
                                                "interpreted_type": "structural_detail",
                                                "analysis_status": "interpreted",
                                            }
                                        ],
                                        "model_version": "qwen3-vl-plus",
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ],
                },
            )

        with _temporary_png() as image_path:
            client = QwenMultimodalRecognitionClient(
                QwenRecognitionConfig(api_key="test-key"),
                http_client=httpx.Client(transport=httpx.MockTransport(handler)),
            )

            result = client.recognize(_request(image_path))

        self.assertEqual("succeeded", result.status)
        self.assertEqual("A1", result.observations[0]["normalized_text"])
        self.assertEqual("structural_detail", result.interpretations[0]["interpreted_type"])
        self.assertEqual("Bearer test-key", captured["headers"]["authorization"])
        self.assertEqual("qwen3-vl-plus", captured["payload"]["model"])
        user_content = captured["payload"]["messages"][1]["content"]
        self.assertEqual("image_url", user_content[1]["type"])
        self.assertTrue(user_content[1]["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertIn("block:1", user_content[0]["text"])

    def test_config_from_env_reads_dashscope_key_without_accepting_empty_values(self):
        previous = __import__("os").environ.get("DASHSCOPE_API_KEY")
        try:
            __import__("os").environ["DASHSCOPE_API_KEY"] = "env-key"
            config = QwenRecognitionConfig.from_env()

            self.assertEqual("env-key", config.api_key)
            self.assertIn("qwen", config.model)
        finally:
            if previous is None:
                __import__("os").environ.pop("DASHSCOPE_API_KEY", None)
            else:
                __import__("os").environ["DASHSCOPE_API_KEY"] = previous

        with self.assertRaises(ToolModelError):
            QwenRecognitionConfig(api_key="")

    def test_recognize_maps_provider_error_to_recognition_failed(self):
        def handler(request):
            return httpx.Response(429, json={"error": {"message": "rate limited"}})

        with _temporary_png() as image_path:
            client = QwenMultimodalRecognitionClient(
                QwenRecognitionConfig(api_key="test-key"),
                http_client=httpx.Client(transport=httpx.MockTransport(handler)),
            )

            with self.assertRaises(ToolModelError) as error:
                client.recognize(_request(image_path))

        self.assertEqual("RECOGNITION_FAILED", error.exception.category)
        self.assertNotIn("test-key", str(error.exception))

    def test_recognize_rejects_unparseable_model_content(self):
        def handler(request):
            return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})

        with _temporary_png() as image_path:
            client = QwenMultimodalRecognitionClient(
                QwenRecognitionConfig(api_key="test-key"),
                http_client=httpx.Client(transport=httpx.MockTransport(handler)),
            )

            with self.assertRaises(ToolModelError) as error:
                client.recognize(_request(image_path))

        self.assertEqual("RECOGNITION_FAILED", error.exception.category)


def _request(image_path: str) -> RecognitionClientRequest:
    return RecognitionClientRequest(
        page_id="page:1",
        image_path=image_path,
        targets=(("block:1", "DrawingBlock", BBox(1, 2, 3, 4), BBox(0.1, 0.2, 0.3, 0.4)),),
        model_profile="qwen3-vl-plus",
        prompt_version="qwen-vision-v1",
        context={"page_number": 24},
    )


class _temporary_png:
    def __enter__(self):
        self._tmpdir = Path(__file__).resolve().parents[1] / ".test_tmp" / f"qwen-client-{uuid4().hex}"
        self._tmpdir.mkdir(parents=True, exist_ok=False)
        path = self._tmpdir / "road_24.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        return str(path)

    def __exit__(self, exc_type, exc, traceback):
        for child in self._tmpdir.iterdir():
            child.unlink()
        self._tmpdir.rmdir()


if __name__ == "__main__":
    unittest.main()
