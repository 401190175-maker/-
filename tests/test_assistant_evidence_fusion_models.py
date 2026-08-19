"""Contract tests for the evidence fusion (05) models module."""

import unittest

from drawing_graph.assistant_evidence_fusion_models import (
    Answerability,
    AnswerabilityResult,
    CacheClosureStatus,
    CacheSummary,
    CacheTargetSummary,
    ClaimCapability,
    ClaimSupportAssessment,
    ClaimSupportStatus,
    ConflictRecord,
    ConflictSeverity,
    ConflictType,
    EvidenceComparison,
    EvidenceBundle,
    EvidenceFusionRequest,
    EvidenceLineage,
    EvidenceProvenance,
    FUSION_CONTRACT_VERSION,
    FusionEvidence,
    FusionMetadata,
    LineagePlan,
    SemanticWriteBatch,
    WriteBackItemResult,
    WriteBackItemStatus,
    WriteBackPolicy,
    WriteBackResult,
    WriteBackStatus,
)
from drawing_graph.assistant_models import (
    AssistantRequest,
    CacheDisposition,
    EvidenceItem,
    EvidenceRef,
    FactKind,
    FreshnessResult,
    QuestionUnderstandingResult,
    ReasonCode,
    RetrievalBundle,
    SemanticGapDecision,
)


class FusionContractVersionTests(unittest.TestCase):
    def test_fusion_contract_version_is_stable(self):
        self.assertEqual("drawing-assistant-fusion-v1", FUSION_CONTRACT_VERSION)


class AnswerabilityTests(unittest.TestCase):
    def test_contains_all_required_values(self):
        self.assertEqual(
            {
                "answerable",
                "partially_answerable",
                "clarification_required",
                "unsupported",
            },
            {item.value for item in Answerability},
        )

    def test_values_are_stable_strings(self):
        self.assertEqual("answerable", Answerability.ANSWERABLE.value)
        self.assertEqual("clarification_required", Answerability.CLARIFICATION_REQUIRED.value)

    def test_unknown_value_is_rejected(self):
        with self.assertRaises(ValueError):
            Answerability("not_a_real_status")


class ClaimCapabilityTests(unittest.TestCase):
    def test_contains_all_required_values(self):
        self.assertEqual(
            {
                "identity_and_location",
                "confirmed_relation",
                "rule_derived_context",
                "observed_text_or_symbol",
                "semantic_meaning",
                "possible_relation",
                "runtime_or_cache_status",
            },
            {item.value for item in ClaimCapability},
        )

    def test_values_are_stable_strings(self):
        self.assertEqual("identity_and_location", ClaimCapability.IDENTITY_AND_LOCATION.value)
        self.assertEqual("runtime_or_cache_status", ClaimCapability.RUNTIME_OR_CACHE_STATUS.value)


class ClaimSupportStatusTests(unittest.TestCase):
    def test_contains_all_required_values(self):
        self.assertEqual(
            {
                "supported",
                "supported_with_qualifier",
                "conflicting",
                "missing",
                "stale_only",
                "formal_review_required",
                "unsupported",
            },
            {item.value for item in ClaimSupportStatus},
        )

    def test_formal_review_is_a_support_status_not_a_confirmed_relation(self):
        self.assertEqual("formal_review_required", ClaimSupportStatus.FORMAL_REVIEW_REQUIRED.value)


class EvidenceComparisonTests(unittest.TestCase):
    def test_contains_all_required_values(self):
        self.assertEqual(
            {
                "consistent",
                "complementary",
                "conflicting",
                "superseded",
                "ambiguous",
                "not_comparable",
            },
            {item.value for item in EvidenceComparison},
        )


class ConflictTypeTests(unittest.TestCase):
    def test_contains_all_required_values(self):
        self.assertEqual(
            {
                "hard_conflict",
                "rule_conflict",
                "model_vs_source",
                "semantic_vs_rule",
                "peer_conflict",
                "support_conflict",
                "relation_conflict",
                "formal_vs_semantic",
                "critical_integrity_conflict",
                "candidate_ambiguity",
                "diagnostic_conflict",
            },
            {item.value for item in ConflictType},
        )


class ConflictSeverityTests(unittest.TestCase):
    def test_contains_all_required_values(self):
        self.assertEqual(
            {"info", "warning", "blocking", "critical"},
            {item.value for item in ConflictSeverity},
        )


class CacheClosureStatusTests(unittest.TestCase):
    def test_contains_all_required_values(self):
        self.assertEqual(
            {
                "full_hit",
                "partial_hit",
                "miss",
                "stale",
                "bypassed",
                "mixed",
                "unknown",
            },
            {item.value for item in CacheClosureStatus},
        )

    def test_unknown_stale_and_miss_are_distinct(self):
        self.assertEqual("unknown", CacheClosureStatus.UNKNOWN.value)
        self.assertEqual("stale", CacheClosureStatus.STALE.value)
        self.assertEqual("miss", CacheClosureStatus.MISS.value)
        self.assertNotEqual(CacheClosureStatus.UNKNOWN.value, CacheClosureStatus.STALE.value)
        self.assertNotEqual(CacheClosureStatus.STALE.value, CacheClosureStatus.MISS.value)


class WriteBackStatusTests(unittest.TestCase):
    def test_contains_all_required_values(self):
        self.assertEqual(
            {"not_requested", "skipped", "persisted", "partial", "failed"},
            {item.value for item in WriteBackStatus},
        )


class WriteBackItemStatusTests(unittest.TestCase):
    def test_contains_all_required_values(self):
        self.assertEqual(
            {"persisted", "skipped", "failed"},
            {item.value for item in WriteBackItemStatus},
        )


class ReasonCodeFusionTests(unittest.TestCase):
    def test_fusion_reason_codes_exist(self):
        self.assertEqual("fusion_input_invalid", ReasonCode.FUSION_INPUT_INVALID.value)
        self.assertEqual("evidence_projection_failed", ReasonCode.EVIDENCE_PROJECTION_FAILED.value)
        self.assertEqual("evidence_normalization_failed", ReasonCode.EVIDENCE_NORMALIZATION_FAILED.value)
        self.assertEqual("conflict_policy_invalid", ReasonCode.CONFLICT_POLICY_INVALID.value)
        self.assertEqual("claim_support_failed", ReasonCode.CLAIM_SUPPORT_FAILED.value)
        self.assertEqual("cache_closure_inconsistent", ReasonCode.CACHE_CLOSURE_INCONSISTENT.value)
        self.assertEqual("write_back_denied", ReasonCode.WRITE_BACK_DENIED.value)
        self.assertEqual("persistence_unavailable", ReasonCode.PERSISTENCE_UNAVAILABLE.value)
        self.assertEqual("write_back_partial", ReasonCode.WRITE_BACK_PARTIAL.value)
        self.assertEqual("lineage_write_failed", ReasonCode.LINEAGE_WRITE_FAILED.value)
        self.assertEqual("internal_error", ReasonCode.INTERNAL_ERROR.value)
        self.assertEqual("recognition_scope_mismatch", ReasonCode.RECOGNITION_SCOPE_MISMATCH.value)


class FusionMetadataTests(unittest.TestCase):
    def test_metadata_carries_four_keys_capabilities_and_freshness(self):
        metadata = FusionMetadata(
            normalized_value={"text": "ABC"},
            comparison_key="scope:page:1:slot:text",
            evidence_family_key="family:target:1:text",
            content_fingerprint="fingerprint-1",
            claim_capabilities=(ClaimCapability.OBSERVED_TEXT_OR_SYMBOL,),
            cache_key="cache-key-1",
            task_type="element_text_observation",
            freshness_result=FreshnessResult(is_current=True),
            normalization_rule_version="normalize-v1",
            is_current_for_request=True,
        )
        self.assertEqual({"text": "ABC"}, metadata.normalized_value)
        self.assertEqual("scope:page:1:slot:text", metadata.comparison_key)
        self.assertEqual("family:target:1:text", metadata.evidence_family_key)
        self.assertEqual("fingerprint-1", metadata.content_fingerprint)
        self.assertEqual((ClaimCapability.OBSERVED_TEXT_OR_SYMBOL,), metadata.claim_capabilities)
        self.assertEqual("cache-key-1", metadata.cache_key)
        self.assertTrue(metadata.is_current_for_request)

    def test_metadata_accepts_stable_capability_strings(self):
        metadata = FusionMetadata(claim_capabilities=("possible_relation",))
        self.assertEqual((ClaimCapability.POSSIBLE_RELATION,), metadata.claim_capabilities)

    def test_metadata_defaults_are_empty_and_not_current(self):
        metadata = FusionMetadata()
        self.assertIsNone(metadata.normalized_value)
        self.assertIsNone(metadata.comparison_key)
        self.assertEqual((), metadata.claim_capabilities)
        self.assertFalse(metadata.is_current_for_request)


class EvidenceProvenanceTests(unittest.TestCase):
    def test_provenance_carries_run_attempt_payload_and_refs(self):
        provenance = EvidenceProvenance(
            source_call_id="call:1",
            recognition_run_id="run:1",
            attempt_ids=("attempt:1", "attempt:2"),
            payload_ref="payload:1",
            rule_version="v1",
            evidence_refs=(EvidenceRef(page_id="page:1"),),
        )
        self.assertEqual("call:1", provenance.source_call_id)
        self.assertEqual("run:1", provenance.recognition_run_id)
        self.assertEqual(("attempt:1", "attempt:2"), provenance.attempt_ids)
        self.assertEqual("payload:1", provenance.payload_ref)
        self.assertEqual(1, len(provenance.evidence_refs))

    def test_provenance_defaults_are_empty(self):
        provenance = EvidenceProvenance()
        self.assertIsNone(provenance.recognition_run_id)
        self.assertEqual((), provenance.attempt_ids)
        self.assertEqual((), provenance.evidence_refs)


class FusionEvidenceTests(unittest.TestCase):
    def test_fusion_evidence_wraps_item_without_changing_it(self):
        item = EvidenceItem(
            evidence_id="evidence:1",
            fact_kind=FactKind.SEMANTIC_OBSERVATION,
            value={"raw_text": "ABC"},
        )
        metadata = FusionMetadata(normalized_value={"text": "ABC"})
        fusion = FusionEvidence(item=item, metadata=metadata)
        self.assertEqual(item, fusion.item)
        self.assertEqual(FactKind.SEMANTIC_OBSERVATION, fusion.item.fact_kind)
        self.assertEqual({"raw_text": "ABC"}, fusion.item.value)
        self.assertEqual(metadata, fusion.metadata)

    def test_fusion_evidence_defaults_are_empty(self):
        item = EvidenceItem(evidence_id="evidence:2", fact_kind=FactKind.DIAGNOSTIC, value={})
        fusion = FusionEvidence(item=item, metadata=FusionMetadata())
        self.assertEqual((), fusion.provenance)
        self.assertEqual((), fusion.original_evidence_ids)

    def test_fusion_evidence_rejects_non_evidence_item(self):
        with self.assertRaises(ValueError):
            FusionEvidence(item="not-an-item", metadata=FusionMetadata())


class ConflictRecordTests(unittest.TestCase):
    def test_conflict_record_carries_sorted_evidence_ids_and_type(self):
        record = ConflictRecord(
            conflict_id="conflict:1",
            comparison_key="scope:page:1:slot:text",
            conflict_type=ConflictType.PEER_CONFLICT,
            severity=ConflictSeverity.WARNING,
            evidence_ids=("evidence:a", "evidence:b"),
            preferred_for_current_claim_ids=("evidence:a",),
            blocks_answer=False,
            reason_codes=(ReasonCode.EVIDENCE_CONFLICT,),
            review_recommended=True,
        )
        self.assertEqual("conflict:1", record.conflict_id)
        self.assertEqual("scope:page:1:slot:text", record.comparison_key)
        self.assertEqual(ConflictType.PEER_CONFLICT, record.conflict_type)
        self.assertEqual(("evidence:a", "evidence:b"), record.evidence_ids)
        self.assertFalse(record.blocks_answer)
        self.assertTrue(record.review_recommended)

    def test_blocking_severity_forces_blocks_answer_true(self):
        record = ConflictRecord(
            conflict_id="conflict:2",
            severity=ConflictSeverity.BLOCKING,
            evidence_ids=("evidence:a", "evidence:b"),
        )
        self.assertTrue(record.blocks_answer)

    def test_critical_severity_forces_blocks_answer_true(self):
        record = ConflictRecord(
            conflict_id="conflict:3",
            severity="critical",
            evidence_ids=("evidence:a",),
        )
        self.assertTrue(record.blocks_answer)

    def test_info_severity_defaults_to_not_blocking(self):
        record = ConflictRecord(
            conflict_id="conflict:4",
            severity=ConflictSeverity.INFO,
            evidence_ids=("evidence:a",),
        )
        self.assertFalse(record.blocks_answer)

    def test_conflict_record_requires_evidence_id(self):
        with self.assertRaises(ValueError):
            ConflictRecord(conflict_id="", severity=ConflictSeverity.WARNING)


class ClaimSupportAssessmentTests(unittest.TestCase):
    def test_assessment_carries_support_qualifying_rejected_and_conflicts(self):
        assessment = ClaimSupportAssessment(
            requirement_id="req-ev:1",
            subrequest_id="sub:1",
            claim_capability=ClaimCapability.OBSERVED_TEXT_OR_SYMBOL,
            status=ClaimSupportStatus.SUPPORTED,
            supporting_evidence_ids=("evidence:1",),
            qualifying_evidence_ids=("evidence:2",),
            rejected_evidence_ids=("evidence:3",),
            conflict_ids=("conflict:1",),
            qualifiers=("partial",),
            confidence=0.8,
            confidence_basis="model",
            reason_codes=(ReasonCode.EVIDENCE_COMPLETE,),
        )
        self.assertEqual("req-ev:1", assessment.requirement_id)
        self.assertEqual(ClaimCapability.OBSERVED_TEXT_OR_SYMBOL, assessment.claim_capability)
        self.assertEqual(ClaimSupportStatus.SUPPORTED, assessment.status)
        self.assertEqual(("evidence:1",), assessment.supporting_evidence_ids)
        self.assertEqual(("evidence:3",), assessment.rejected_evidence_ids)
        self.assertEqual(("conflict:1",), assessment.conflict_ids)
        self.assertEqual(0.8, assessment.confidence)

    def test_deterministic_confidence_can_be_null_with_basis(self):
        assessment = ClaimSupportAssessment(
            requirement_id="req-ev:2",
            claim_capability=ClaimCapability.CONFIRMED_RELATION,
            status=ClaimSupportStatus.SUPPORTED,
            supporting_evidence_ids=("evidence:formal:1",),
            confidence=None,
            confidence_basis="deterministic",
        )
        self.assertIsNone(assessment.confidence)
        self.assertEqual("deterministic", assessment.confidence_basis)

    def test_formal_review_required_is_a_support_status(self):
        assessment = ClaimSupportAssessment(
            requirement_id="req-ev:3",
            claim_capability=ClaimCapability.CONFIRMED_RELATION,
            status=ClaimSupportStatus.FORMAL_REVIEW_REQUIRED,
        )
        self.assertEqual(ClaimSupportStatus.FORMAL_REVIEW_REQUIRED, assessment.status)

    def test_confidence_must_be_between_zero_and_one(self):
        with self.assertRaises(ValueError):
            ClaimSupportAssessment(
                requirement_id="req-ev:4",
                status=ClaimSupportStatus.SUPPORTED,
                confidence=1.5,
            )


class AnswerabilityResultTests(unittest.TestCase):
    def test_subrequest_result_carries_status_and_blocking_reasons(self):
        result = AnswerabilityResult(
            status=Answerability.PARTIALLY_ANSWERABLE,
            subrequest_id="sub:1",
            blocking_reason_codes=(ReasonCode.EVIDENCE_MISSING,),
            affected_requirement_ids=("req-ev:1",),
        )
        self.assertEqual(Answerability.PARTIALLY_ANSWERABLE, result.status)
        self.assertEqual("sub:1", result.subrequest_id)
        self.assertEqual((ReasonCode.EVIDENCE_MISSING,), result.blocking_reason_codes)
        self.assertEqual(("req-ev:1",), result.affected_requirement_ids)
        self.assertEqual((), result.subrequest_results)

    def test_request_result_aggregates_subrequest_results(self):
        sub = AnswerabilityResult(status=Answerability.ANSWERABLE, subrequest_id="sub:1")
        request = AnswerabilityResult(
            status=Answerability.ANSWERABLE,
            subrequest_results=(sub,),
        )
        self.assertEqual((sub,), request.subrequest_results)
        self.assertEqual(Answerability.ANSWERABLE, request.subrequest_results[0].status)

    def test_accepts_stable_status_string(self):
        result = AnswerabilityResult(status="clarification_required")
        self.assertEqual(Answerability.CLARIFICATION_REQUIRED, result.status)

    def test_rejects_unknown_status(self):
        with self.assertRaises(ValueError):
            AnswerabilityResult(status="not_a_status")


class EvidenceLineageTests(unittest.TestCase):
    def test_lineage_carries_current_and_superseded(self):
        lineage = EvidenceLineage(
            lineage_id="lineage:1",
            evidence_family_key="family:target:1:text",
            current_evidence_id="evidence:new",
            superseded_evidence_ids=("evidence:old",),
            stale_reason="superseded_by_newer_evidence",
        )
        self.assertEqual("lineage:1", lineage.lineage_id)
        self.assertEqual("family:target:1:text", lineage.evidence_family_key)
        self.assertEqual("evidence:new", lineage.current_evidence_id)
        self.assertEqual(("evidence:old",), lineage.superseded_evidence_ids)
        self.assertEqual("superseded_by_newer_evidence", lineage.stale_reason)

    def test_lineage_is_not_a_formal_relation(self):
        lineage = EvidenceLineage(
            lineage_id="lineage:2",
            evidence_family_key="family:1",
            current_evidence_id="evidence:a",
        )
        self.assertEqual((), lineage.superseded_evidence_ids)
        self.assertEqual((), lineage.reason_codes)


class LineagePlanTests(unittest.TestCase):
    def test_plan_carries_stale_targets_and_superseding_id(self):
        plan = LineagePlan(
            plan_id="plan:1",
            evidence_family_key="family:1",
            evidence_ids=("evidence:old",),
            superseded_by_evidence_id="evidence:new",
            stale_reason="superseded",
            stale_at="2026-08-13T00:00:00Z",
        )
        self.assertEqual("plan:1", plan.plan_id)
        self.assertEqual(("evidence:old",), plan.evidence_ids)
        self.assertEqual("evidence:new", plan.superseded_by_evidence_id)

    def test_plan_defaults_are_empty(self):
        plan = LineagePlan(plan_id="plan:2", evidence_family_key="family:2")
        self.assertEqual((), plan.evidence_ids)
        self.assertIsNone(plan.superseded_by_evidence_id)


class CacheTargetSummaryTests(unittest.TestCase):
    def test_target_summary_carries_expected_and_actual(self):
        summary = CacheTargetSummary(
            target_id="target:1",
            expected_cache_key="cache-key-1",
            expected_disposition=CacheDisposition.MISS,
            actual_cache_key="cache-key-1",
            actual_disposition=CacheClosureStatus.MISS,
            reused_evidence_ids=(),
            new_evidence_ids=("evidence:1",),
            recognition_run_id="run:1",
            provider_called=True,
            persisted=False,
        )
        self.assertEqual("target:1", summary.target_id)
        self.assertEqual(CacheDisposition.MISS, summary.expected_disposition)
        self.assertEqual(CacheClosureStatus.MISS, summary.actual_disposition)
        self.assertEqual(("evidence:1",), summary.new_evidence_ids)
        self.assertTrue(summary.provider_called)
        self.assertFalse(summary.persisted)

    def test_target_summary_defaults_are_empty(self):
        summary = CacheTargetSummary(target_id="target:2")
        self.assertIsNone(summary.expected_cache_key)
        self.assertIsNone(summary.actual_disposition)
        self.assertFalse(summary.provider_called)
        self.assertFalse(summary.persisted)


class CacheSummaryTests(unittest.TestCase):
    def test_cache_summary_carries_targets_and_commit_flag(self):
        target = CacheTargetSummary(target_id="target:1", actual_disposition=CacheClosureStatus.FULL_HIT)
        summary = CacheSummary(
            status=CacheClosureStatus.FULL_HIT,
            targets=(target,),
            persistent_cache_committed=False,
            request_memo_used=True,
            new_recognition_run_ids=(),
        )
        self.assertEqual(CacheClosureStatus.FULL_HIT, summary.status)
        self.assertEqual(1, len(summary.targets))
        self.assertFalse(summary.persistent_cache_committed)
        self.assertTrue(summary.request_memo_used)

    def test_unknown_stale_and_miss_are_distinct(self):
        self.assertEqual(CacheClosureStatus.UNKNOWN, CacheSummary(status="unknown").status)
        self.assertEqual(CacheClosureStatus.STALE, CacheSummary(status="stale").status)
        self.assertEqual(CacheClosureStatus.MISS, CacheSummary(status="miss").status)

    def test_cache_summary_defaults_to_unknown(self):
        summary = CacheSummary()
        self.assertEqual(CacheClosureStatus.UNKNOWN, summary.status)
        self.assertEqual((), summary.targets)
        self.assertFalse(summary.persistent_cache_committed)


class WriteBackPolicyTests(unittest.TestCase):
    def test_policy_defaults_all_false(self):
        policy = WriteBackPolicy()
        self.assertFalse(policy.request_allow_write_back)
        self.assertFalse(policy.module_allow_write_back)
        self.assertFalse(policy.environment_allow_write_back)
        self.assertFalse(policy.allow_persistent_cache)
        self.assertEqual((), policy.allowed_fact_kinds)

    def test_policy_carries_three_layer_authorization_and_gates(self):
        policy = WriteBackPolicy(
            request_allow_write_back=True,
            module_allow_write_back=True,
            environment_allow_write_back=True,
            allowed_fact_kinds=(FactKind.SEMANTIC_OBSERVATION, FactKind.SEMANTIC_INTERPRETATION),
            require_valid_scope=True,
            require_sanitized_payload=True,
            require_audit_material=True,
            block_on_conflict_severities=(ConflictSeverity.BLOCKING, ConflictSeverity.CRITICAL),
            allow_persistent_cache=True,
        )
        self.assertTrue(policy.request_allow_write_back)
        self.assertEqual(
            (FactKind.SEMANTIC_OBSERVATION, FactKind.SEMANTIC_INTERPRETATION),
            policy.allowed_fact_kinds,
        )
        self.assertEqual(
            (ConflictSeverity.BLOCKING, ConflictSeverity.CRITICAL),
            policy.block_on_conflict_severities,
        )

    def test_policy_rejects_non_boolean_authorization(self):
        with self.assertRaises(ValueError):
            WriteBackPolicy(request_allow_write_back="yes")


class SemanticWriteBatchTests(unittest.TestCase):
    def test_batch_carries_run_id_and_integrity_flags(self):
        batch = SemanticWriteBatch(
            recognition_run_id="run:1",
            schema_valid=True,
            scope_valid=True,
            payload_sanitized=True,
            audit_material_complete=True,
            sanitized_payload_envelope={"run_id": "run:1"},
        )
        self.assertEqual("run:1", batch.recognition_run_id)
        self.assertTrue(batch.schema_valid)
        self.assertTrue(batch.scope_valid)
        self.assertTrue(batch.payload_sanitized)
        self.assertTrue(batch.audit_material_complete)
        self.assertEqual({"run_id": "run:1"}, dict(batch.sanitized_payload_envelope))

    def test_batch_defaults_flags_false_and_collections_empty(self):
        batch = SemanticWriteBatch(recognition_run_id="run:2")
        self.assertFalse(batch.schema_valid)
        self.assertEqual((), batch.attempts)
        self.assertEqual((), batch.observations)
        self.assertEqual((), batch.interpretations)
        self.assertEqual((), batch.candidate_evidence)
        self.assertEqual((), batch.cache_entries)

    def test_batch_requires_run_id(self):
        with self.assertRaises(ValueError):
            SemanticWriteBatch(recognition_run_id="")


class WriteBackItemResultTests(unittest.TestCase):
    def test_item_result_carries_stage_status_and_reason(self):
        item = WriteBackItemResult(
            stage="semantic_evidence",
            status=WriteBackItemStatus.PERSISTED,
            evidence_ids=("evidence:1",),
            reason_code=None,
            message=None,
        )
        self.assertEqual("semantic_evidence", item.stage)
        self.assertEqual(WriteBackItemStatus.PERSISTED, item.status)
        self.assertEqual(("evidence:1",), item.evidence_ids)

    def test_item_result_accepts_stable_status_string(self):
        item = WriteBackItemResult(stage="lineage_stale", status="failed", reason_code=ReasonCode.LINEAGE_WRITE_FAILED)
        self.assertEqual(WriteBackItemStatus.FAILED, item.status)
        self.assertEqual(ReasonCode.LINEAGE_WRITE_FAILED, item.reason_code)


class WriteBackResultTests(unittest.TestCase):
    def test_write_back_result_carries_status_and_committed_flag(self):
        item = WriteBackItemResult(stage="semantic_evidence", status="persisted", evidence_ids=("evidence:1",))
        result = WriteBackResult(
            status=WriteBackStatus.PERSISTED,
            items=(item,),
            persisted_evidence_ids=("evidence:1",),
            recognition_run_ids=("run:1",),
            payload_refs=("payload:1",),
            persistent_cache_committed=True,
        )
        self.assertEqual(WriteBackStatus.PERSISTED, result.status)
        self.assertEqual(1, len(result.items))
        self.assertEqual(("evidence:1",), result.persisted_evidence_ids)
        self.assertEqual(("run:1",), result.recognition_run_ids)
        self.assertTrue(result.persistent_cache_committed)

    def test_not_requested_skipped_persisted_partial_failed_are_distinct(self):
        self.assertEqual(WriteBackStatus.NOT_REQUESTED, WriteBackResult().status)
        self.assertEqual(WriteBackStatus.SKIPPED, WriteBackResult(status="skipped").status)
        self.assertEqual(WriteBackStatus.PERSISTED, WriteBackResult(status="persisted").status)
        self.assertEqual(WriteBackStatus.PARTIAL, WriteBackResult(status="partial").status)
        self.assertEqual(WriteBackStatus.FAILED, WriteBackResult(status="failed").status)

    def test_write_back_result_defaults_to_not_requested(self):
        result = WriteBackResult()
        self.assertEqual(WriteBackStatus.NOT_REQUESTED, result.status)
        self.assertEqual((), result.items)
        self.assertFalse(result.persistent_cache_committed)


class EvidenceFusionRequestTests(unittest.TestCase):
    def _request(self):
        return EvidenceFusionRequest(
            assistant_request=AssistantRequest(request_id="req:1", question="q"),
            question_result=QuestionUnderstandingResult(
                request_id="req:1",
                question_type="page_summary",
            ),
            retrieval_bundle=RetrievalBundle(request_id="req:1"),
            semantic_gap_decision=SemanticGapDecision(request_id="req:1"),
        )

    def test_request_carries_all_required_context(self):
        request = self._request()
        self.assertEqual("req:1", request.assistant_request.request_id)
        self.assertEqual("req:1", request.question_result.request_id)
        self.assertEqual("req:1", request.retrieval_bundle.request_id)
        self.assertEqual("req:1", request.semantic_gap_decision.request_id)
        self.assertEqual((), request.recognition_results)
        self.assertIsNone(request.write_back_policy)

    def test_request_carries_write_back_policy(self):
        policy = WriteBackPolicy(request_allow_write_back=False)
        request = EvidenceFusionRequest(
            assistant_request=AssistantRequest(request_id="req:1", question="q"),
            question_result=QuestionUnderstandingResult(request_id="req:1", question_type="page_summary"),
            retrieval_bundle=RetrievalBundle(request_id="req:1"),
            semantic_gap_decision=SemanticGapDecision(request_id="req:1"),
            write_back_policy=policy,
        )
        self.assertEqual(policy, request.write_back_policy)

    def test_request_rejects_wrong_context_types(self):
        with self.assertRaises(ValueError):
            EvidenceFusionRequest(
                assistant_request="not-a-request",
                question_result=QuestionUnderstandingResult(request_id="req:1", question_type="page_summary"),
                retrieval_bundle=RetrievalBundle(request_id="req:1"),
                semantic_gap_decision=SemanticGapDecision(request_id="req:1"),
            )


class EvidenceBundleTests(unittest.TestCase):
    def _fusion_evidence(self, evidence_id="evidence:1"):
        return FusionEvidence(
            item=EvidenceItem(evidence_id=evidence_id, fact_kind=FactKind.SEMANTIC_OBSERVATION, value={}),
            metadata=FusionMetadata(),
        )

    def test_bundle_carries_accepted_and_conflicting_evidence(self):
        bundle = EvidenceBundle(
            request_id="req:1",
            accepted_evidence=(self._fusion_evidence("evidence:1"),),
            conflicting_evidence=(self._fusion_evidence("evidence:2"),),
        )
        self.assertEqual("req:1", bundle.request_id)
        self.assertEqual(1, len(bundle.accepted_evidence))
        self.assertEqual(1, len(bundle.conflicting_evidence))
        self.assertEqual(FUSION_CONTRACT_VERSION, bundle.contract_version)

    def test_bundle_defaults_are_empty(self):
        bundle = EvidenceBundle(request_id="req:1")
        self.assertEqual((), bundle.accepted_evidence)
        self.assertEqual((), bundle.conflicts)
        self.assertEqual((), bundle.claim_support)
        self.assertEqual((), bundle.unsupported_claims)
        self.assertEqual((), bundle.lineage)
        self.assertIsNone(bundle.cache_summary)
        self.assertIsNone(bundle.answerability)
        self.assertIsNone(bundle.write_back_result)

    def test_bundle_can_carry_answerability_and_write_back(self):
        bundle = EvidenceBundle(
            request_id="req:1",
            answerability=AnswerabilityResult(status=Answerability.ANSWERABLE),
            write_back_result=WriteBackResult(status=WriteBackStatus.SKIPPED),
        )
        self.assertEqual(Answerability.ANSWERABLE, bundle.answerability.status)
        self.assertEqual(WriteBackStatus.SKIPPED, bundle.write_back_result.status)

    def test_bundle_rejects_wrong_accepted_evidence_type(self):
        with self.assertRaises(ValueError):
            EvidenceBundle(request_id="req:1", accepted_evidence=("not-fusion-evidence",))


if __name__ == "__main__":
    unittest.main()
