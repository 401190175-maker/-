import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.semantic_client import FakeMultimodalRecognitionClient, RecognitionClientRequest
from drawing_graph.tool_models import BBox, SemanticTargetInput, ToolModelError


class SemanticClientTest(unittest.TestCase):
    def test_fake_client_returns_successful_observation_payloads(self):
        client = FakeMultimodalRecognitionClient(
            outputs=[
                {
                    "target_element_id": "block:1",
                    "target_element_type": "DrawingBlock",
                    "raw_text": "A1",
                    "normalized_text": "A1",
                    "confidence": 0.9,
                    "status": "confirmed",
                }
            ]
        )
        request = RecognitionClientRequest(
            page_id="page:1",
            image_path="road_24.png",
            targets=(("block:1", "DrawingBlock", BBox(1, 2, 3, 4), BBox(0.1, 0.2, 0.3, 0.4)),),
            model_profile="default",
            prompt_version="p1",
        )

        result = client.recognize(request)

        self.assertEqual("succeeded", result.status)
        self.assertEqual("A1", result.observations[0]["normalized_text"])

    def test_fake_client_can_return_partial_failed_and_unparseable_results(self):
        request = RecognitionClientRequest(
            page_id="page:1",
            image_path="road_24.png",
            targets=(),
            model_profile="default",
            prompt_version="p1",
        )

        self.assertEqual("partial", FakeMultimodalRecognitionClient(status="partial").recognize(request).status)
        self.assertEqual("failed", FakeMultimodalRecognitionClient(status="failed").recognize(request).status)
        with self.assertRaises(ToolModelError):
            FakeMultimodalRecognitionClient(unparseable=True).recognize(request)

    def test_fake_client_simulates_timeout_as_recognition_failed(self):
        request = RecognitionClientRequest(
            page_id="page:1",
            image_path="road_24.png",
            targets=(("block:1", "DrawingBlock", BBox(1, 2, 3, 4), BBox(0.1, 0.2, 0.3, 0.4)),),
            model_profile="default",
            prompt_version="p1",
            context={"page_number": 24},
        )

        with self.assertRaises(ToolModelError) as error:
            FakeMultimodalRecognitionClient(timeout=True).recognize(request)

        self.assertEqual("RECOGNITION_FAILED", error.exception.category)

    def test_request_carries_image_bbox_target_and_minimal_page_context(self):
        request = RecognitionClientRequest(
            page_id="page:1",
            image_path="road_24.png",
            targets=(("block:1", "DrawingBlock", BBox(1, 2, 3, 4), BBox(0.1, 0.2, 0.3, 0.4)),),
            model_profile="vision-v1",
            prompt_version="prompt-v1",
            context={"page_number": 24, "context_element_ids": ("caption:1",)},
        )

        self.assertEqual("road_24.png", request.image_path)
        self.assertEqual(("block:1", "DrawingBlock", BBox(1, 2, 3, 4), BBox(0.1, 0.2, 0.3, 0.4)), request.targets[0])
        self.assertEqual(24, request.context["page_number"])

    def test_request_rejects_api_key_free_text(self):
        with self.assertRaises(ToolModelError):
            RecognitionClientRequest(
                page_id="page:1",
                image_path="road_24.png",
                targets=(),
                model_profile="default",
                prompt_version="p1",
                context={"api_key": "secret"},
            )

    def test_fake_client_consumes_precise_target_inputs(self):
        client = FakeMultimodalRecognitionClient(
            outputs=[
                {
                    "target_element_id": "element:1",
                    "target_element_type": "DrawingBlock",
                    "raw_text": "A1",
                    "normalized_text": "A1",
                    "confidence": 0.9,
                    "status": "confirmed",
                }
            ]
        )
        request = RecognitionClientRequest(
            page_id="page:1",
            image_path="road_24.png",
            targets=(),
            model_profile="qwen-vl",
            prompt_version="prompt-v1",
            target_inputs=(
                SemanticTargetInput(
                    target_id="target:1",
                    page_id="page:1",
                    target_element_id="element:1",
                    target_type="DrawingBlock",
                    task_type="text_observation",
                    required_outputs=("observation",),
                    bbox=BBox(1, 2, 3, 4),
                    normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
                    context_element_ids=("element:2",),
                    output_contract_version="1",
                ),
            ),
        )

        result = client.recognize(request)

        self.assertEqual("succeeded", result.status)
        self.assertEqual(1, len(client.requests))
        consumed = client.requests[0].target_inputs[0]
        self.assertEqual("text_observation", consumed.task_type)
        self.assertEqual(("observation",), consumed.required_outputs)
        self.assertEqual("1", consumed.output_contract_version)

    def test_request_rejects_invalid_target_inputs(self):
        with self.assertRaises(ToolModelError):
            RecognitionClientRequest(
                page_id="page:1",
                image_path="road_24.png",
                targets=(),
                model_profile="default",
                prompt_version="p1",
                target_inputs=("not-a-target",),
            )


if __name__ == "__main__":
    unittest.main()
