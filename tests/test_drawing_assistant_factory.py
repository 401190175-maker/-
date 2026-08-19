"""Tests for the side-effect-free drawing assistant factory."""

import unittest

from drawing_graph.drawing_assistant_factory import create_drawing_assistant_service
from drawing_graph.drawing_assistant_service import DrawingAssistantService
from drawing_graph.assistant_trace_store import InMemoryTraceStore
from drawing_graph.assistant_traceability_service import TraceabilityService


class _RecordingFacade:
    def __init__(self):
        self.calls = 0

    def __getattr__(self, name):
        def method(*args, **kwargs):
            self.calls += 1
            return None

        return method


class DrawingAssistantFactoryTests(unittest.TestCase):
    def test_factory_returns_drawing_assistant_service(self):
        service = create_drawing_assistant_service(_RecordingFacade())
        self.assertIsInstance(service, DrawingAssistantService)

    def test_default_has_no_text_generator(self):
        service = create_drawing_assistant_service(_RecordingFacade())
        self.assertIsNone(service.answer_service.text_generator)

    def test_factory_has_no_side_effects(self):
        facade = _RecordingFacade()
        service = create_drawing_assistant_service(facade)
        self.assertEqual(0, facade.calls)
        self.assertIs(service.facade, facade)

    def test_factory_accepts_injected_services(self):
        class _Dummy:
            pass

        question_service = _Dummy()
        facade = _RecordingFacade()
        service = create_drawing_assistant_service(
            facade,
            question_service=question_service,
        )
        self.assertIs(question_service, service.question_service)

    def test_default_has_no_traceability_service(self):
        service = create_drawing_assistant_service(_RecordingFacade())
        self.assertIsNone(service.traceability_service)

    def test_factory_accepts_traceability_service(self):
        trace_service = TraceabilityService(InMemoryTraceStore())
        service = create_drawing_assistant_service(
            _RecordingFacade(),
            traceability_service=trace_service,
        )
        self.assertIs(trace_service, service.traceability_service)

    def test_factory_accepts_trace_store(self):
        store = InMemoryTraceStore()
        service = create_drawing_assistant_service(
            _RecordingFacade(),
            trace_store=store,
        )
        self.assertIsInstance(service.traceability_service, TraceabilityService)
        self.assertIs(store, service.traceability_service.store)

    def test_factory_with_trace_store_has_no_side_effects(self):
        facade = _RecordingFacade()
        create_drawing_assistant_service(facade, trace_store=InMemoryTraceStore())
        self.assertEqual(0, facade.calls)


if __name__ == "__main__":
    unittest.main()
