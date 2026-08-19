"""Controlled write-back contracts for runs, attempts, payloads and evidence."""

from __future__ import annotations

import unittest

from drawing_graph.recognition_attempt_log import InMemoryRecognitionAttemptLog
from drawing_graph.recognition_models import RecognitionExecutionResult, ValidatedRecognitionOutput
from drawing_graph.recognition_run_log import InMemoryRecognitionRunLog
from drawing_graph.semantic_payload_store import InMemorySemanticPayloadStore
from drawing_graph.semantic_repository import InMemorySemanticEvidenceRepository
from drawing_graph.semantic_service import SemanticRecognitionService
from drawing_graph.tool_models import BBox, ElementEvidence, PageSourceFacts, SemanticTargetInput, ToolModelError

def _element(element_id: str = "block:1", element_type: str = "DrawingBlock") -> ElementEvidence:
    return ElementEvidence(
        element_id=element_id,
        element_type=element_type,
        source_label=element_id,
        bbox=BBox(1, 2, 3, 4),
        normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
    )


def page_facts(*elements: ElementEvidence) -> PageSourceFacts:
    return PageSourceFacts(
        page_id="page:1",
        image_path="road_24.png",
        elements=tuple(elements or (_element(),)),
        image_size=(10, 10),
        image_hash="hash:provided",
    )


def block_target() -> SemanticTargetInput:
    return SemanticTargetInput(
        target_id="t1",
        page_id="page:1",
        target_element_id="block:1",
        target_type="DrawingBlock",
        task_type="block_semantic_identification",
        bbox=BBox(1, 2, 3, 4),
        normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
    )


def block_output() -> ValidatedRecognitionOutput:
    return ValidatedRecognitionOutput(
        task_type="block_semantic_identification",
        target_id="t1",
        target_type="DrawingBlock",
        status="succeeded",
        output={
            "interpretation": {
                "summary": "wall block",
                "interpreted_type": "structural_wall",
            }
        },
    )


class StubExecutionService:
    def __init__(self, results=None):
        self.calls = []
        self.results = list(results or [])

    def execute(self, request, page_facts, execution_policy=None):
        self.calls.append(request)
        if self.results:
            return self.results.pop(0)
        return RecognitionExecutionResult(
            recognition_run_id=request.recognition_run_id,
            status="succeeded",
        )


class FailingRunLog:
    def create_run(self, *args, **kwargs):
        raise ToolModelError("RUN_LOG_UNAVAILABLE", "run log unavailable")


class RelationWriteSpy:
    def __init__(self):
        self.calls = []

    def save_observations(self, *args, **kwargs):
        self.calls.append(("save_observations", args, kwargs))

    def save_interpretations(self, *args, **kwargs):
        self.calls.append(("save_interpretations", args, kwargs))

    def write_relations(self, *args, **kwargs):
        self.calls.append(("write_relations", args, kwargs))

    def promote_candidate_relation(self, *args, **kwargs):
        self.calls.append(("promote_candidate_relation", args, kwargs))


class FailingInterpretationRepository(InMemorySemanticEvidenceRepository):
    def save_interpretations(self, interpretations):
        raise ToolModelError("SEMANTIC_EVIDENCE_UNAVAILABLE", "semantic evidence repository is unavailable")


class FailingPayloadStore:
    def put_payload(self, *args, **kwargs):
        raise ToolModelError("PAYLOAD_STORE_UNAVAILABLE", "payload store is unavailable")


def _service(
    *,
    stub,
    run_log=None,
    repository=None,
    attempt_log=None,
    payload_store=None,
) -> SemanticRecognitionService:
    return SemanticRecognitionService(
        client=None,
        run_log=run_log,
        semantic_repository=repository,
        cache_service=None,
        execution_service=stub,
        attempt_log=attempt_log,
        payload_store=payload_store,
    )


class SemanticServiceWriteBackTest(unittest.TestCase):
    """Dry-run writes nothing; write-back writes only allowed targets."""

    def test_dry_run_never_writes_run_attempt_payload_or_repository(self) -> None:
        run_log = InMemoryRecognitionRunLog()
        repository = InMemorySemanticEvidenceRepository()
        attempt_log = InMemoryRecognitionAttemptLog()
        payload_store = InMemorySemanticPayloadStore()
        stub = StubExecutionService(
            results=(
                RecognitionExecutionResult(
                    recognition_run_id="run:temp:1",
                    status="succeeded",
                    validated_outputs=(block_output(),),
                ),
            )
        )
        service = _service(
            stub=stub,
            run_log=run_log,
            repository=repository,
            attempt_log=attempt_log,
            payload_store=payload_store,
        )

        result = service.recognize_targets(
            page_facts(),
            (block_target(),),
            "default",
            "prompt-v1",
            write_back=False,
        )

        self.assertFalse(result.persisted)
        self.assertEqual(0, len(run_log._runs))
        self.assertEqual(0, len(attempt_log._attempts))
        self.assertEqual(0, len(payload_store._payloads))
        self.assertEqual((), repository.find_by_run("run:temp:1"))

    def test_write_back_persists_run_attempt_payload_and_evidence(self) -> None:
        run_log = InMemoryRecognitionRunLog()
        repository = InMemorySemanticEvidenceRepository()
        attempt_log = InMemoryRecognitionAttemptLog()
        payload_store = InMemorySemanticPayloadStore()
        stub = StubExecutionService(
            results=(
                RecognitionExecutionResult(
                    recognition_run_id="run:1",
                    status="succeeded",
                    validated_outputs=(block_output(),),
                ),
            )
        )
        service = _service(
            stub=stub,
            run_log=run_log,
            repository=repository,
            attempt_log=attempt_log,
            payload_store=payload_store,
        )

        result = service.recognize_targets(
            page_facts(),
            (block_target(),),
            "default",
            "prompt-v1",
            write_back=True,
        )

        self.assertTrue(result.persisted)
        self.assertEqual("succeeded", run_log.get_run(result.recognition_run_id).status)
        self.assertEqual(1, len(repository.find_interpretations(element_id="block:1")))
        self.assertIsNotNone(result.payload_ref)
        stored = payload_store.get_payload(result.payload_ref)
        self.assertEqual("succeeded", stored["status"])

    def test_run_log_unavailable_blocks_write_back_before_execution(self) -> None:
        stub = StubExecutionService()
        service = _service(
            stub=stub,
            run_log=FailingRunLog(),
            repository=InMemorySemanticEvidenceRepository(),
            attempt_log=InMemoryRecognitionAttemptLog(),
            payload_store=InMemorySemanticPayloadStore(),
        )

        with self.assertRaises(ToolModelError) as error:
            service.recognize_targets(page_facts(), (block_target(),), "default", "p1", write_back=True)

        self.assertEqual("RUN_LOG_UNAVAILABLE", error.exception.category)
        self.assertEqual([], stub.calls)

    def test_page_summary_write_back_never_writes_graph_nodes(self) -> None:
        run_log = InMemoryRecognitionRunLog()
        repository = InMemorySemanticEvidenceRepository()
        attempt_log = InMemoryRecognitionAttemptLog()
        payload_store = InMemorySemanticPayloadStore()
        stub = StubExecutionService(
            results=(
                RecognitionExecutionResult(
                    recognition_run_id="run:1",
                    status="succeeded",
                    validated_outputs=(
                        ValidatedRecognitionOutput(
                            task_type="page_summary",
                            target_id="t-page",
                            target_type="DrawingPage",
                            status="succeeded",
                            output={"summary": "page text", "key_elements": [], "uncertainties": []},
                        ),
                    ),
                ),
            )
        )
        service = _service(
            stub=stub,
            run_log=run_log,
            repository=repository,
            attempt_log=attempt_log,
            payload_store=payload_store,
        )
        page_target = SemanticTargetInput(
            target_id="t-page",
            page_id="page:1",
            target_type="DrawingPage",
            task_type="page_summary",
        )

        result = service.recognize_targets(
            page_facts(),
            (page_target,),
            "default",
            "prompt-v1",
            write_back=True,
        )

        self.assertTrue(result.persisted)
        self.assertIsNotNone(result.summary)
        self.assertEqual((), repository.find_by_run(result.recognition_run_id))
        self.assertIsNotNone(result.payload_ref)

    def test_write_back_never_writes_candidate_or_formal_relations(self) -> None:
        run_log = InMemoryRecognitionRunLog()
        relation_spy = RelationWriteSpy()
        payload_store = InMemorySemanticPayloadStore()
        stub = StubExecutionService(
            results=(
                RecognitionExecutionResult(
                    recognition_run_id="run:1",
                    status="succeeded",
                    validated_outputs=(block_output(),),
                ),
            )
        )
        service = _service(
            stub=stub,
            run_log=run_log,
            repository=relation_spy,
            attempt_log=InMemoryRecognitionAttemptLog(),
            payload_store=payload_store,
        )

        result = service.recognize_targets(
            page_facts(),
            (block_target(),),
            "default",
            "prompt-v1",
            write_back=True,
        )

        self.assertTrue(result.persisted)
        relation_writes = [
            call
            for call in relation_spy.calls
            if call[0] in {"write_relations", "promote_candidate_relation"}
        ]
        self.assertEqual([], relation_writes)

    def test_persistence_failure_returns_persisted_false_and_keeps_payload_ref(self) -> None:
        run_log = InMemoryRecognitionRunLog()
        repository = FailingInterpretationRepository()
        payload_store = InMemorySemanticPayloadStore()
        stub = StubExecutionService(
            results=(
                RecognitionExecutionResult(
                    recognition_run_id="run:1",
                    status="succeeded",
                    validated_outputs=(block_output(),),
                ),
            )
        )
        service = _service(
            stub=stub,
            run_log=run_log,
            repository=repository,
            attempt_log=InMemoryRecognitionAttemptLog(),
            payload_store=payload_store,
        )

        result = service.recognize_targets(
            page_facts(),
            (block_target(),),
            "default",
            "prompt-v1",
            write_back=True,
        )

        self.assertFalse(result.persisted)
        self.assertIsNotNone(result.payload_ref)
        self.assertEqual(1, len(result.interpretations))
        self.assertEqual("failed", run_log.get_run(result.recognition_run_id).status)
        self.assertEqual("SEMANTIC_EVIDENCE_UNAVAILABLE", result.error_summary)

    def test_payload_failure_returns_persisted_false_without_payload_ref(self) -> None:
        run_log = InMemoryRecognitionRunLog()
        repository = InMemorySemanticEvidenceRepository()
        stub = StubExecutionService(
            results=(
                RecognitionExecutionResult(
                    recognition_run_id="run:1",
                    status="succeeded",
                    validated_outputs=(block_output(),),
                ),
            )
        )
        service = _service(
            stub=stub,
            run_log=run_log,
            repository=repository,
            attempt_log=InMemoryRecognitionAttemptLog(),
            payload_store=FailingPayloadStore(),
        )

        result = service.recognize_targets(
            page_facts(),
            (block_target(),),
            "default",
            "prompt-v1",
            write_back=True,
        )

        self.assertFalse(result.persisted)
        self.assertIsNone(result.payload_ref)
        self.assertEqual("PAYLOAD_STORE_UNAVAILABLE", result.error_summary)
        self.assertEqual("failed", run_log.get_run(result.recognition_run_id).status)


class ValidatedBatchPersistenceTests(unittest.TestCase):
    def _service(self, repository, payload_store, attempt_log):
        return SemanticRecognitionService(
            client=None,
            run_log=InMemoryRecognitionRunLog(),
            semantic_repository=repository,
            cache_service=None,
            attempt_log=attempt_log,
            payload_store=payload_store,
        )

    def _batch(self, observations=(), interpretations=(), candidate_evidence=()):
        from drawing_graph.assistant_evidence_fusion_models import SemanticWriteBatch
        return SemanticWriteBatch(
            recognition_run_id='run:1',
            schema_valid=True,
            scope_valid=True,
            payload_sanitized=True,
            audit_material_complete=True,
            attempts=(),
            sanitized_payload_envelope={'run_id': 'run:1', 'status': 'succeeded'},
            observations=observations,
            interpretations=interpretations,
            candidate_evidence=candidate_evidence,
            cache_entries=(),
        )

    def test_persist_validated_batch_writes_without_provider_call(self):
        from drawing_graph.semantic_models import BlockInterpretation
        repository = InMemorySemanticEvidenceRepository()
        payload_store = InMemorySemanticPayloadStore()
        attempt_log = InMemoryRecognitionAttemptLog()
        service = self._service(repository, payload_store, attempt_log)
        interpretation = BlockInterpretation(
            interpretation_id="interp:1",
            recognition_run_id="run:1",
            block_id="block:1",
            page_id="page:1",
            summary="wall block",
        )

        payload_ref = service.persist_validated_batch(self._batch(interpretations=(interpretation,)))

        self.assertIsNotNone(payload_ref)
        self.assertIsNotNone(payload_store.get_payload(payload_ref))
        self.assertEqual(1, len(repository.find_interpretations(element_id="block:1")))

    def test_persist_validated_batch_rejects_unvalidated_batch(self):
        from drawing_graph.assistant_evidence_fusion_models import SemanticWriteBatch
        repository = InMemorySemanticEvidenceRepository()
        payload_store = InMemorySemanticPayloadStore()
        attempt_log = InMemoryRecognitionAttemptLog()
        service = self._service(repository, payload_store, attempt_log)
        unvalidated = SemanticWriteBatch(
            recognition_run_id="run:1",
            schema_valid=False,
            sanitized_payload_envelope={"run_id": "run:1"},
        )

        with self.assertRaises(ToolModelError):
            service.persist_validated_batch(unvalidated)

    def test_candidate_evidence_is_audit_only_and_not_written_as_edges(self):
        from drawing_graph.recognition_models import RecognitionCandidateEvidence
        repository = InMemorySemanticEvidenceRepository()
        payload_store = InMemorySemanticPayloadStore()
        attempt_log = InMemoryRecognitionAttemptLog()
        service = self._service(repository, payload_store, attempt_log)
        candidate = RecognitionCandidateEvidence(
            relation_type='connected_to',
            source_target_id='t1',
            supporting_target_ids=('t2',),
            status='candidate_relation',
        )

        payload_ref = service.persist_validated_batch(self._batch(candidate_evidence=(candidate,)))

        self.assertIsNotNone(payload_ref)
        self.assertFalse(hasattr(repository, 'write_relations'))


if __name__ == '__main__':
    unittest.main()
