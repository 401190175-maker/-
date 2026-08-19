"""Tests for recognition result projection to unified evidence (Task 8-10)."""

import unittest

from drawing_graph.assistant_models import FactKind, RecognitionTarget
from drawing_graph.assistant_recognition_projection import (
    ProjectionResult,
    RecognitionEvidenceProjector,
)
from drawing_graph.recognition_models import (
    RecognitionAttempt,
    RecognitionCandidateEvidence,
    RecognitionCostSummary,
    RecognitionLatencySummary,
    RecognitionProviderUsage,
)
from drawing_graph.semantic_models import (
    BasicInfoInterpretation,
    BlockInterpretation,
    TableInterpretation,
    TextObservation,
)
from drawing_graph.semantic_service import SemanticRecognitionResult
from drawing_graph.tool_models import BBox


def make_observation(observation_id="obs:1", raw_text="  A1  ", normalized_text="A1"):
    return TextObservation(
        observation_id=observation_id,
        recognition_run_id="run:1",
        target_element_id="element:1",
        target_element_type="DrawingBlock",
        page_id="page:1",
        raw_text=raw_text,
        normalized_text=normalized_text,
        bbox=BBox(1, 2, 3, 4),
        normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
        confidence=0.8,
        status="confirmed",
        image_hash="image-hash",
        cache_key="cache-key",
        model_profile="vision-v1",
        prompt_version="prompt-v1",
        created_at="2026-08-13T00:00:00Z",
    )


def make_block_interpretation():
    return BlockInterpretation(
        interpretation_id="interp:1",
        recognition_run_id="run:1",
        block_id="block:1",
        summary="a pump block",
        page_id="page:1",
        interpreted_type="equipment",
        components=("valve",),
        materials=("steel",),
        dimensions=("100mm",),
        construction_features=("welded",),
        spatial_relations=("above",),
        analysis_status="interpreted",
        uncertainties=("low",),
        supported_by_observation_ids=("obs:1",),
        payload_ref="payload:1",
        cache_key="cache-key",
        contract_version="1",
        model_profile="vision-v1",
        prompt_version="prompt-v1",
        input_contract_version="1",
        preprocessing_version="preprocess-v1",
    )


def make_basic_info_interpretation():
    return BasicInfoInterpretation(
        interpretation_id="interp:2",
        recognition_run_id="run:1",
        basic_info_id="basic-info:1",
        raw_text="project X",
        summary="basic info",
        page_id="page:1",
        project_name="project X",
        drawing_name="drawing Y",
        discipline="mechanical",
        drawing_number="D-001",
        scale="1:100",
        date="2026-08-13",
        analysis_status="interpreted",
        supported_by_observation_ids=("obs:2",),
        cache_key="cache-key-2",
        contract_version="1",
        model_profile="vision-v1",
        prompt_version="prompt-v1",
        input_contract_version="1",
        preprocessing_version="preprocess-v1",
    )


def make_table_interpretation():
    return TableInterpretation(
        interpretation_id="interp:3",
        recognition_run_id="run:1",
        table_id="table:1",
        summary="a material table",
        page_id="page:1",
        caption_ref="caption:1",
        analysis_status="interpreted",
        supported_by_observation_ids=("obs:3",),
        cache_key="cache-key-3",
        contract_version="1",
        model_profile="vision-v1",
        prompt_version="prompt-v1",
        input_contract_version="1",
        preprocessing_version="preprocess-v1",
    )


def make_candidate():
    return RecognitionCandidateEvidence(
        relation_type="connected_to",
        source_target_id="target:1",
        supporting_target_ids=("target:2",),
        confidence=0.7,
        status="candidate_relation",
    )


def make_target(target_id="target:1", page_id="page:1", element_id="element:1", bbox=None):
    return RecognitionTarget(
        target_id=target_id,
        target_type="DrawingBlock",
        task_type="element_text_observation",
        page_id=page_id,
        target_element_id=element_id,
        required_outputs=("observations",),
        covered_requirement_ids=("req-ev:1",),
        bbox=bbox,
    )


class RecognitionObservationProjectionTests(unittest.TestCase):
    def test_observation_projects_to_semantic_observation(self):
        result = SemanticRecognitionResult(
            recognition_run_id="run:1",
            status="succeeded",
            observations=(make_observation(),),
            persisted=False,
        )
        projection = RecognitionEvidenceProjector().project(result)

        self.assertIsInstance(projection, ProjectionResult)
        self.assertEqual(1, len(projection.evidence))
        item = projection.evidence[0]
        self.assertEqual("obs:1", item.evidence_id)
        self.assertEqual(FactKind.SEMANTIC_OBSERVATION, item.fact_kind)

    def test_observation_scope_bbox_run_and_confidence_are_preserved(self):
        result = SemanticRecognitionResult(
            recognition_run_id="run:1",
            status="succeeded",
            observations=(make_observation(),),
            persisted=False,
        )
        item = RecognitionEvidenceProjector().project(result).evidence[0]

        self.assertEqual("page:1", item.scope.page_id)
        self.assertEqual("element:1", item.scope.element_id)
        self.assertEqual("run:1", item.recognition_run_id)
        self.assertEqual(0.8, item.confidence)
        self.assertEqual("vision-v1", item.model_profile)
        self.assertEqual("prompt-v1", item.prompt_version)
        self.assertEqual("2026-08-13T00:00:00Z", item.created_at_or_version)
        self.assertEqual(1, len(item.evidence_refs))
        self.assertEqual(
            {"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
            dict(item.evidence_refs[0].bbox),
        )

    def test_raw_text_is_not_overwritten_by_normalized(self):
        result = SemanticRecognitionResult(
            recognition_run_id="run:1",
            status="succeeded",
            observations=(make_observation(raw_text="  A1  ", normalized_text="A1"),),
            persisted=False,
        )
        item = RecognitionEvidenceProjector().project(result).evidence[0]

        self.assertEqual("  A1  ", item.value["raw_text"])
        self.assertEqual("A1", item.evidence_metadata["normalized_text"])

    def test_observation_fact_kind_cannot_be_model_controlled(self):
        result = SemanticRecognitionResult(
            recognition_run_id="run:1",
            status="succeeded",
            observations=(make_observation(),),
            persisted=False,
        )
        item = RecognitionEvidenceProjector().project(result).evidence[0]
        self.assertEqual(FactKind.SEMANTIC_OBSERVATION, item.fact_kind)
        self.assertNotEqual(FactKind.SOURCE_FACT, item.fact_kind)


class RecognitionInterpretationProjectionTests(unittest.TestCase):
    def test_block_interpretation_projects_to_semantic_interpretation(self):
        result = SemanticRecognitionResult(
            recognition_run_id="run:1",
            status="succeeded",
            observations=(),
            persisted=False,
            interpretations=(make_block_interpretation(),),
        )
        item = RecognitionEvidenceProjector().project(result).evidence[0]

        self.assertEqual("interp:1", item.evidence_id)
        self.assertEqual(FactKind.SEMANTIC_INTERPRETATION, item.fact_kind)
        self.assertEqual("page:1", item.scope.page_id)
        self.assertEqual("block:1", item.scope.block_id)

    def test_supported_by_observation_refs_are_preserved(self):
        result = SemanticRecognitionResult(
            recognition_run_id="run:1",
            status="succeeded",
            observations=(),
            persisted=False,
            interpretations=(make_block_interpretation(),),
        )
        item = RecognitionEvidenceProjector().project(result).evidence[0]
        self.assertEqual(("obs:1",), item.evidence_metadata["supported_by_observation_ids"])
        self.assertEqual(FactKind.SEMANTIC_INTERPRETATION, item.fact_kind)

    def test_interpreted_type_does_not_imply_block_type_change(self):
        result = SemanticRecognitionResult(
            recognition_run_id="run:1",
            status="succeeded",
            observations=(),
            persisted=False,
            interpretations=(make_block_interpretation(),),
        )
        item = RecognitionEvidenceProjector().project(result).evidence[0]
        self.assertEqual("equipment", item.evidence_metadata["interpreted_type"])
        self.assertEqual(FactKind.SEMANTIC_INTERPRETATION, item.fact_kind)

    def test_all_three_interpretation_kinds_project(self):
        result = SemanticRecognitionResult(
            recognition_run_id="run:1",
            status="succeeded",
            observations=(),
            persisted=False,
            interpretations=(
                make_block_interpretation(),
                make_basic_info_interpretation(),
                make_table_interpretation(),
            ),
        )
        items = RecognitionEvidenceProjector().project(result).evidence
        self.assertEqual(3, len(items))
        for item in items:
            self.assertEqual(FactKind.SEMANTIC_INTERPRETATION, item.fact_kind)

    def test_table_interpretation_scope_uses_table_id(self):
        result = SemanticRecognitionResult(
            recognition_run_id="run:1",
            status="succeeded",
            observations=(),
            persisted=False,
            interpretations=(make_table_interpretation(),),
        )
        item = RecognitionEvidenceProjector().project(result).evidence[0]
        self.assertEqual("table:1", item.scope.table_id)
        self.assertEqual("page:1", item.scope.page_id)


class RecognitionCandidateDiagnosticProjectionTests(unittest.TestCase):
    def test_candidate_projects_to_candidate_relation(self):
        result = SemanticRecognitionResult(
            recognition_run_id="run:1",
            status="succeeded",
            observations=(),
            persisted=False,
            candidate_evidence=(make_candidate(),),
        )
        items = RecognitionEvidenceProjector().project(result).evidence

        self.assertEqual(1, len(items))
        item = items[0]
        self.assertEqual(FactKind.CANDIDATE_RELATION, item.fact_kind)
        self.assertEqual("connected_to", item.evidence_metadata["relation_type"])
        self.assertEqual("target:1", item.evidence_metadata["source_target_id"])
        self.assertEqual(("target:2",), item.evidence_metadata["supporting_target_ids"])
        self.assertEqual(0.7, item.confidence)

    def test_diagnostic_captures_run_status_and_persisted(self):
        result = SemanticRecognitionResult(
            recognition_run_id="run:1",
            status="succeeded",
            observations=(),
            persisted=False,
            error_summary=None,
        )
        projection = RecognitionEvidenceProjector().project(result)
        self.assertEqual(1, len(projection.diagnostics))
        diagnostic = projection.diagnostics[0]
        self.assertEqual(FactKind.DIAGNOSTIC, diagnostic.fact_kind)
        self.assertEqual("succeeded", diagnostic.evidence_metadata["run_status"])
        self.assertFalse(diagnostic.evidence_metadata["persisted"])

    def test_diagnostic_captures_attempt_statuses(self):
        attempt = RecognitionAttempt(
            attempt_id="attempt:1",
            recognition_run_id="run:1",
            attempt_number=1,
            task_type="element_text_observation",
            provider="fake",
            model_name="fake-multimodal",
            request_fingerprint="fp",
            prompt_version="default",
            output_contract_version="1",
            status="succeeded",
        )
        result = SemanticRecognitionResult(
            recognition_run_id="run:1",
            status="succeeded",
            observations=(),
            persisted=False,
            attempts=(attempt,),
            usage_summary=RecognitionProviderUsage(input_tokens=1, output_tokens=2),
            cost_summary=RecognitionCostSummary(status="unavailable"),
            latency_summary=RecognitionLatencySummary(total_ms=10.0),
        )
        diagnostic = RecognitionEvidenceProjector().project(result).diagnostics[0]
        self.assertEqual(("succeeded",), diagnostic.value["attempt_statuses"])
        self.assertEqual("unavailable", diagnostic.value["cost_summary"]["status"])

    def test_projector_never_produces_source_derived_or_formal(self):
        result = SemanticRecognitionResult(
            recognition_run_id="run:1",
            status="succeeded",
            observations=(make_observation(),),
            persisted=False,
            interpretations=(make_block_interpretation(),),
            candidate_evidence=(make_candidate(),),
        )
        projection = RecognitionEvidenceProjector().project(result)
        for item in (*projection.evidence, *projection.diagnostics):
            self.assertNotIn(
                item.fact_kind,
                {FactKind.SOURCE_FACT, FactKind.DERIVED_RELATION, FactKind.FORMAL_RELATION},
            )


class RecognitionScopeProjectionTests(unittest.TestCase):
    def _result(self, **overrides):
        values = dict(
            recognition_run_id="run:1",
            status="succeeded",
            observations=(make_observation(),),
            persisted=False,
        )
        values.update(overrides)
        return SemanticRecognitionResult(**values)

    def test_matching_observation_is_accepted(self):
        target = make_target(bbox={"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4})
        projection = RecognitionEvidenceProjector().project(self._result(), (target,))
        self.assertEqual(1, len(projection.evidence))
        self.assertEqual((), projection.rejected_outputs)

    def test_cross_page_observation_is_rejected(self):
        target = make_target(page_id="page:2")
        projection = RecognitionEvidenceProjector().project(self._result(), (target,))
        self.assertEqual((), projection.evidence)
        self.assertEqual(1, len(projection.rejected_outputs))

    def test_extra_target_observation_is_rejected(self):
        target = make_target(element_id="element:99")
        projection = RecognitionEvidenceProjector().project(self._result(), (target,))
        self.assertEqual((), projection.evidence)
        self.assertEqual(1, len(projection.rejected_outputs))

    def test_bbox_mismatch_is_rejected(self):
        target = make_target(bbox={"x_min": 9, "y_min": 9, "x_max": 9, "y_max": 9})
        projection = RecognitionEvidenceProjector().project(self._result(), (target,))
        self.assertEqual((), projection.evidence)
        self.assertEqual(1, len(projection.rejected_outputs))

    def test_scope_mismatch_generates_diagnostic_with_stable_reason_code(self):
        target = make_target(page_id="page:2")
        projection = RecognitionEvidenceProjector().project(self._result(), (target,))
        mismatch_diagnostics = [
            item for item in projection.diagnostics
            if item.evidence_metadata.get("reason_code") == "recognition_scope_mismatch"
        ]
        self.assertEqual(1, len(mismatch_diagnostics))
        self.assertEqual(FactKind.DIAGNOSTIC, mismatch_diagnostics[0].fact_kind)

    def test_rejected_output_is_not_in_evidence(self):
        target = make_target(page_id="page:2")
        projection = RecognitionEvidenceProjector().project(self._result(), (target,))
        self.assertEqual((), projection.evidence)
        self.assertEqual(1, len(projection.rejected_outputs))

    def test_cross_page_interpretation_is_rejected(self):
        result = self._result(observations=(), interpretations=(make_block_interpretation(),))
        target = make_target(page_id="page:2", element_id="block:1")
        projection = RecognitionEvidenceProjector().project(result, (target,))
        self.assertEqual((), projection.evidence)
        self.assertEqual(1, len(projection.rejected_outputs))

    def test_candidate_with_unknown_target_is_rejected(self):
        result = self._result(observations=(), candidate_evidence=(make_candidate(),))
        target = make_target(target_id="target:unknown", element_id="element:1")
        projection = RecognitionEvidenceProjector().project(result, (target,))
        self.assertEqual((), projection.evidence)
        self.assertEqual(1, len(projection.rejected_outputs))


class ProjectionDataMinimizationTests(unittest.TestCase):
    def test_diagnostic_only_carries_summary_not_full_payload(self):
        result = SemanticRecognitionResult(
            recognition_run_id="run:1",
            status="succeeded",
            observations=(),
            persisted=False,
        )
        diagnostic = RecognitionEvidenceProjector().project(result).diagnostics[0]
        self.assertIn("run_status", diagnostic.value)
        self.assertIn("payload_ref", diagnostic.value)
        self.assertNotIn("image_bytes", diagnostic.value)
        self.assertNotIn("base64", diagnostic.value)
        self.assertNotIn("prompt", diagnostic.value)

    def test_projection_does_not_carry_absolute_paths_or_secrets(self):
        result = SemanticRecognitionResult(
            recognition_run_id="run:1",
            status="succeeded",
            observations=(),
            persisted=False,
        )
        diagnostic = RecognitionEvidenceProjector().project(result).diagnostics[0]
        serialized = str(diagnostic.value).lower()
        self.assertNotIn("secret", serialized)
        self.assertNotIn("password", serialized)
        self.assertNotIn("c:\\", serialized)

    def test_observation_projection_carries_stable_refs_not_raw_provider_output(self):
        result = SemanticRecognitionResult(
            recognition_run_id="run:1",
            status="succeeded",
            observations=(make_observation(),),
            persisted=False,
        )
        item = RecognitionEvidenceProjector().project(result).evidence[0]
        self.assertIn("raw_text", item.value)
        self.assertNotIn("provider_response", item.value)
        self.assertNotIn("api_key", item.value)


if __name__ == "__main__":
    unittest.main()
