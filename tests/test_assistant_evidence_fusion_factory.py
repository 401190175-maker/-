"""Tests for evidence fusion factory (Task 48)."""

import unittest

from drawing_graph.assistant_evidence_fusion import EvidenceFusionService
from drawing_graph.assistant_evidence_fusion_factory import create_evidence_fusion_service
from drawing_graph.assistant_evidence_normalization import (
    EvidenceNormalizer,
    NormalizationRuleRegistry,
)
from drawing_graph.assistant_evidence_fusion_models import (
    EvidenceFusionRequest,
    WriteBackPolicy,
    WriteBackStatus,
)
from drawing_graph.assistant_models import (
    AssistantScope,
    AssistantRequest,
    EvidenceItem,
    FactKind,
    QuestionUnderstandingResult,
    RetrievalBundle,
    SemanticGapDecision,
)


def make_request():
    return EvidenceFusionRequest(
        assistant_request=AssistantRequest(request_id="req:1", question="q", allow_write_back=True),
        question_result=QuestionUnderstandingResult(request_id="req:1", question_type="page_summary"),
        retrieval_bundle=RetrievalBundle(request_id="req:1"),
        semantic_gap_decision=SemanticGapDecision(request_id="req:1"),
        write_back_policy=WriteBackPolicy(request_allow_write_back=True),
    )


class EvidenceFusionFactoryTests(unittest.TestCase):
    def test_factory_returns_fusion_service(self):
        service = create_evidence_fusion_service()
        self.assertIsInstance(service, EvidenceFusionService)

    def test_default_has_no_controlled_write_port(self):
        service = create_evidence_fusion_service()
        self.assertIsNone(service.controlled_write_port)

    def test_default_write_back_request_is_skipped(self):
        service = create_evidence_fusion_service()
        bundle = service.fuse(make_request())
        self.assertEqual(WriteBackStatus.SKIPPED, bundle.write_back_result.status)

    def test_factory_accepts_injected_port(self):
        from drawing_graph.assistant_evidence_fusion_models import SemanticWriteBatch
        from drawing_graph.semantic_service import SemanticRecognitionResult

        class RecordingPort:
            def __init__(self):
                self.calls = []

            def persist(self, batch, policy, lineage_plan=None):
                self.calls.append((batch, policy))
                from drawing_graph.assistant_evidence_fusion_models import WriteBackResult, WriteBackStatus

                return WriteBackResult(status=WriteBackStatus.PERSISTED)

        port = RecordingPort()
        service = create_evidence_fusion_service(controlled_write_port=port)
        request = make_request()
        request = EvidenceFusionRequest(
            assistant_request=request.assistant_request,
            question_result=request.question_result,
            retrieval_bundle=request.retrieval_bundle,
            semantic_gap_decision=request.semantic_gap_decision,
            recognition_results=(
                SemanticRecognitionResult(
                    recognition_run_id="run:1",
                    status="succeeded",
                    observations=(),
                    persisted=False,
                    write_batch=SemanticWriteBatch(
                        recognition_run_id="run:1",
                        schema_valid=True,
                        scope_valid=True,
                        payload_sanitized=True,
                        audit_material_complete=True,
                        sanitized_payload_envelope={"run_id": "run:1"},
                    ),
                ),
            ),
            write_back_policy=request.write_back_policy,
        )
        bundle = service.fuse(request)
        self.assertEqual(WriteBackStatus.PERSISTED, bundle.write_back_result.status)
        self.assertEqual(1, len(port.calls))

    def test_factory_has_no_side_effects(self):
        service = create_evidence_fusion_service()
        self.assertIsNotNone(service.normalizer)
        self.assertIsNotNone(service.lineage_resolver)


class DefaultNormalizationRegistryTests(unittest.TestCase):
    """默认工厂必须注册生产规范化规则，否则真实链路证据会被全部隔离。"""

    def test_default_factory_registers_rules_for_all_fact_kinds(self):
        service = create_evidence_fusion_service()
        self.assertIsInstance(service.normalizer, EvidenceNormalizer)
        registry = service.normalizer.rule_registry
        self.assertIsInstance(registry, NormalizationRuleRegistry)
        for fact_kind, task_type, slot in (
            (FactKind.SOURCE_FACT, "source_fact", "identity"),
            (FactKind.DERIVED_RELATION, "relation_derivation", "relation"),
            (FactKind.SEMANTIC_OBSERVATION, "element_text_observation", "text"),
            (FactKind.SEMANTIC_INTERPRETATION, "block_semantic_identification", "summary"),
            (FactKind.CANDIDATE_RELATION, "relation_evidence_extraction", "relation"),
            (FactKind.FORMAL_RELATION, "relation_formal", "relation"),
            (FactKind.DIAGNOSTIC, "diagnostic", "summary"),
        ):
            rule = registry.lookup(fact_kind, task_type, slot)
            self.assertEqual("normalize-v1", rule.rule_version)

    def test_default_factory_normalizes_source_fact_evidence(self):
        service = create_evidence_fusion_service()
        item = EvidenceItem(
            evidence_id="evidence:src:1",
            fact_kind=FactKind.SOURCE_FACT,
            scope=AssistantScope(page_id="page:1", element_id="element:1"),
            value={
                "page_id": "page:1",
                "element_id": "element:1",
                "element_type": "Table",
                "bbox": {"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
            },
        )
        result = service.normalizer.normalize((item,))
        self.assertEqual(1, len(result.normalized))
        self.assertEqual((), result.isolated)


if __name__ == "__main__":
    unittest.main()
