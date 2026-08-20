"""Tests for semantic understanding wiring in the product factory."""

from __future__ import annotations

import unittest

from drawing_graph.assistant_question_llm import FakeQuestionUnderstandingModelClient


class FactoryWiringTests(unittest.TestCase):
    def test_factory_injects_model_client(self) -> None:
        from drawing_graph.drawing_assistant_factory import create_drawing_assistant_service

        class _Facade:
            pass

        client = FakeQuestionUnderstandingModelClient()
        service = create_drawing_assistant_service(
            facade=_Facade(),
            question_understanding_client=client,
        )
        self.assertIs(service.question_service.model_client, client)


if __name__ == "__main__":
    unittest.main()
