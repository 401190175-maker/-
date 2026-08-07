import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.recognition_run_log import InMemoryRecognitionRunLog
from drawing_graph.query_ports import FakeDrawingGraphReadPort
from drawing_graph.semantic_client import FakeMultimodalRecognitionClient
from drawing_graph.semantic_repository import InMemorySemanticEvidenceRepository
from drawing_graph.semantic_service import SemanticRecognitionService
from drawing_graph.tool_facade import DrawingGraphToolFacade
from drawing_graph.tool_models import BBox, ElementEvidence, PageSourceFacts, ToolModelError


class FailingRunLog:
    def create_run(self, *args, **kwargs):
        raise ToolModelError("RUN_LOG_UNAVAILABLE", "run log unavailable")


class FailingClient:
    def recognize(self, request):
        raise ToolModelError("RECOGNITION_FAILED", "provider timeout")


def page_facts():
    return PageSourceFacts(
        page_id="page:1",
        image_path="road_24.png",
        elements=(
            ElementEvidence(
                element_id="block:1",
                element_type="DrawingBlock",
                source_label="block",
                bbox=BBox(1, 2, 3, 4),
                normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
            ),
        ),
    )


def successful_client():
    return FakeMultimodalRecognitionClient(
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


def successful_client_with_interpretation():
    return FakeMultimodalRecognitionClient(
        outputs=[
            {
                "target_element_id": "block:1",
                "target_element_type": "DrawingBlock",
                "raw_text": "A1",
                "normalized_text": "A1",
                "confidence": 0.9,
                "status": "confirmed",
            }
        ],
        interpretations=[
            {
                "target_element_id": "block:1",
                "target_element_type": "DrawingBlock",
                "summary": "wall block",
                "interpreted_type": "structural_wall",
                "analysis_status": "interpreted",
                "supported_by_observation_ids": (),
            }
        ],
    )


class FailingInterpretationRepository(InMemorySemanticEvidenceRepository):
    def save_interpretations(self, interpretations):
        raise ToolModelError("SEMANTIC_EVIDENCE_UNAVAILABLE", "semantic evidence repository is unavailable")


class RelationWriteSpy:
    def __init__(self):
        self.calls = []

    def create_run(self, *args, **kwargs):
        self.calls.append(("create_run", args, kwargs))

    def save_observations(self, *args, **kwargs):
        self.calls.append(("save_observations", args, kwargs))

    def save_interpretations(self, *args, **kwargs):
        self.calls.append(("save_interpretations", args, kwargs))

    def write_relations(self, *args, **kwargs):
        self.calls.append(("write_relations", args, kwargs))

    def promote_candidate_relation(self, *args, **kwargs):
        self.calls.append(("promote_candidate_relation", args, kwargs))


class SemanticServiceWriteBackTest(unittest.TestCase):
    def test_default_false_keeps_dry_run_without_writes(self):
        run_log = InMemoryRecognitionRunLog()
        repository = InMemorySemanticEvidenceRepository()
        service = SemanticRecognitionService(successful_client(), run_log, repository)

        result = service.recognize_page(page_facts(), ("DrawingBlock",), "default", "p1")

        self.assertFalse(result.persisted)
        self.assertTrue(result.recognition_run_id.startswith("run:temp:"))
        self.assertEqual((), repository.find_by_run(result.recognition_run_id))

    def test_write_back_true_creates_run_then_persists_observations(self):
        run_log = InMemoryRecognitionRunLog()
        repository = InMemorySemanticEvidenceRepository()
        service = SemanticRecognitionService(successful_client(), run_log, repository)

        result = service.recognize_page(page_facts(), ("DrawingBlock",), "default", "p1", write_back=True)

        self.assertTrue(result.persisted)
        self.assertEqual("succeeded", run_log.get_run(result.recognition_run_id).status)
        self.assertEqual(("block:1",), tuple(item.target_element_id for item in repository.find_by_run(result.recognition_run_id)))

    def test_run_log_unavailable_blocks_write_back_before_recognition(self):
        service = SemanticRecognitionService(successful_client(), FailingRunLog(), InMemorySemanticEvidenceRepository())

        with self.assertRaises(ToolModelError) as error:
            service.recognize_page(page_facts(), ("DrawingBlock",), "default", "p1", write_back=True)

        self.assertEqual("RUN_LOG_UNAVAILABLE", error.exception.category)

    def test_semantic_repository_failure_does_not_return_dry_run_success(self):
        service = SemanticRecognitionService(
            successful_client(),
            InMemoryRecognitionRunLog(),
            InMemorySemanticEvidenceRepository(fail_writes=True),
        )

        with self.assertRaises(ToolModelError) as error:
            service.recognize_page(page_facts(), ("DrawingBlock",), "default", "p1", write_back=True)

        self.assertEqual("SEMANTIC_EVIDENCE_UNAVAILABLE", error.exception.category)

    def test_recognition_failure_marks_existing_run_failed(self):
        run_log = InMemoryRecognitionRunLog()
        service = SemanticRecognitionService(FailingClient(), run_log, InMemorySemanticEvidenceRepository())

        with self.assertRaises(ToolModelError) as error:
            service.recognize_page(page_facts(), ("DrawingBlock",), "default", "p1", write_back=True)

        self.assertEqual("RECOGNITION_FAILED", error.exception.category)
        runs = list(run_log._runs.values())
        self.assertEqual("failed", runs[0].status)

    def test_write_back_true_persists_observations_and_interpretations(self):
        run_log = InMemoryRecognitionRunLog()
        repository = InMemorySemanticEvidenceRepository()
        service = SemanticRecognitionService(successful_client_with_interpretation(), run_log, repository)

        result = service.recognize_page(page_facts(), ("DrawingBlock",), "default", "p1", write_back=True)

        self.assertTrue(result.persisted)
        self.assertEqual("succeeded", run_log.get_run(result.recognition_run_id).status)
        self.assertEqual(
            ("block:1",),
            tuple(item.target_element_id for item in repository.find_by_run(result.recognition_run_id)),
        )
        interpretations = repository.find_interpretations(element_id="block:1")
        self.assertEqual(1, len(interpretations))
        self.assertEqual("structural_wall", interpretations[0].interpreted_type)
        self.assertEqual(result.recognition_run_id, interpretations[0].recognition_run_id)

    def test_interpretation_write_failure_marks_run_failed_and_never_returns_dry_run_success(self):
        run_log = InMemoryRecognitionRunLog()
        repository = FailingInterpretationRepository()
        service = SemanticRecognitionService(successful_client_with_interpretation(), run_log, repository)

        with self.assertRaises(ToolModelError) as error:
            service.recognize_page(page_facts(), ("DrawingBlock",), "default", "p1", write_back=True)

        self.assertEqual("SEMANTIC_EVIDENCE_UNAVAILABLE", error.exception.category)
        runs = list(run_log._runs.values())
        self.assertEqual("failed", runs[0].status)

    def test_write_back_never_writes_candidate_or_formal_relations(self):
        run_log = InMemoryRecognitionRunLog()
        relation_spy = RelationWriteSpy()
        service = SemanticRecognitionService(successful_client_with_interpretation(), run_log, relation_spy)

        result = service.recognize_page(page_facts(), ("DrawingBlock",), "default", "p1", write_back=True)

        self.assertTrue(result.persisted)
        relation_writes = [call for call in relation_spy.calls if call[0] in {"write_relations", "promote_candidate_relation"}]
        self.assertEqual([], relation_writes)

    def test_facade_write_back_persists_through_injected_service(self):
        run_log = InMemoryRecognitionRunLog()
        repository = InMemorySemanticEvidenceRepository()
        service = SemanticRecognitionService(successful_client_with_interpretation(), run_log, repository)
        facade = DrawingGraphToolFacade(
            read_port=FakeDrawingGraphReadPort(source_facts={"page:1": page_facts()}),
            semantic_service=service,
            run_log=run_log,
            semantic_repository=repository,
        )

        result = facade.recognize_page_semantics(
            page_id="page:1",
            target_types=("DrawingBlock",),
            write_back=True,
        )

        self.assertTrue(result.persisted)
        self.assertEqual("succeeded", run_log.get_run(result.recognition_run_id).status)
        self.assertEqual(1, len(repository.find_interpretations(element_id="block:1")))


if __name__ == "__main__":
    unittest.main()
