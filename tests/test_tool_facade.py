"""Tests for the reserved precise semantic target facade entry."""

import unittest

from drawing_graph.query_ports import FakeDrawingGraphReadPort
from drawing_graph.semantic_client import FakeMultimodalRecognitionClient
from drawing_graph.semantic_service import (
    SemanticRecognitionResult,
    SemanticRecognitionService,
)
from drawing_graph.tool_facade import DrawingGraphToolFacade
from drawing_graph.tool_models import (
    BBox,
    ElementEvidence,
    PageSourceFacts,
    SemanticTargetInput,
    ToolModelError,
)


def page_facts() -> PageSourceFacts:
    return PageSourceFacts(
        page_id="page:1",
        image_path="road_24.png",
        elements=(
            ElementEvidence(
                element_id="element:1",
                element_type="DrawingBlock",
                source_label="block",
                bbox=BBox(1, 2, 3, 4),
                normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
            ),
        ),
    )


def precise_target() -> SemanticTargetInput:
    return SemanticTargetInput(
        target_id="target:1",
        page_id="page:1",
        target_element_id="element:1",
        target_type="DrawingBlock",
        task_type="text_observation",
        required_outputs=("observation",),
        bbox=BBox(1, 2, 3, 4),
        normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
        output_contract_version="1",
    )


class RecordingSemanticService:
    def __init__(self):
        self.calls = []
        self.result = SemanticRecognitionResult(
            recognition_run_id="run:temp:1",
            status="succeeded",
            observations=(),
            persisted=False,
            interpretations=(),
        )

    def recognize_targets(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class ToolFacadePreciseTargetTests(unittest.TestCase):
    def test_entry_defaults_to_write_back_false(self):
        service = RecordingSemanticService()
        facade = DrawingGraphToolFacade(
            read_port=FakeDrawingGraphReadPort(source_facts={"page:1": page_facts()}),
            semantic_service=service,
        )

        result = facade.recognize_semantic_targets(
            (precise_target(),),
            model_profile="qwen-vl",
            prompt_version="prompt-v1",
            contract_version="1",
        )

        self.assertFalse(result.persisted)
        self.assertEqual(1, len(service.calls))
        forwarded = service.calls[0]
        self.assertFalse(forwarded["write_back"])
        self.assertEqual("qwen-vl", forwarded["model_profile"])
        self.assertEqual("1", forwarded["contract_version"])
        self.assertEqual("element:1", forwarded["targets"][0].target_element_id)

    def test_entry_forwards_explicit_write_back(self):
        service = RecordingSemanticService()
        facade = DrawingGraphToolFacade(
            read_port=FakeDrawingGraphReadPort(source_facts={"page:1": page_facts()}),
            semantic_service=service,
        )

        facade.recognize_semantic_targets(
            (precise_target(),),
            write_back=True,
        )

        self.assertTrue(service.calls[0]["write_back"])

    def test_entry_rejects_empty_or_invalid_targets(self):
        service = RecordingSemanticService()
        facade = DrawingGraphToolFacade(
            read_port=FakeDrawingGraphReadPort(source_facts={"page:1": page_facts()}),
            semantic_service=service,
        )

        with self.assertRaises(ToolModelError) as empty:
            facade.recognize_semantic_targets(())
        self.assertEqual("INVALID_ARGUMENT", empty.exception.category)
        with self.assertRaises(ToolModelError) as invalid:
            facade.recognize_semantic_targets(("not-a-target",))
        self.assertEqual("INVALID_ARGUMENT", invalid.exception.category)

    def test_entry_rejects_targets_from_different_pages(self):
        service = RecordingSemanticService()
        facade = DrawingGraphToolFacade(
            read_port=FakeDrawingGraphReadPort(source_facts={"page:1": page_facts()}),
            semantic_service=service,
        )
        other = SemanticTargetInput(
            target_id="target:2",
            page_id="page:2",
            target_type="page",
            task_type="page_summary",
            output_contract_version="1",
        )

        with self.assertRaises(ToolModelError) as error:
            facade.recognize_semantic_targets((precise_target(), other))
        self.assertEqual("INVALID_ARGUMENT", error.exception.category)

    def test_existing_page_entry_remains_compatible(self):
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
        service = SemanticRecognitionService(client=client)
        facade = DrawingGraphToolFacade(
            read_port=FakeDrawingGraphReadPort(source_facts={"page:1": page_facts()}),
            semantic_service=service,
        )

        result = facade.recognize_page_semantics(
            page_id="page:1",
            target_types=("DrawingBlock",),
        )

        self.assertFalse(result.persisted)
        self.assertEqual("element:1", result.observations[0].target_element_id)


if __name__ == "__main__":
    unittest.main()
