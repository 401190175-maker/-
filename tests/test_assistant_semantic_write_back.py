"""Tests for controlled semantic write-back (Task 43-44)."""

import unittest

from drawing_graph.assistant_evidence_fusion_models import (
    ConflictRecord,
    ConflictSeverity,
    ConflictType,
    LineagePlan,
    SemanticWriteBatch,
    WriteBackPolicy,
    WriteBackStatus,
)
from drawing_graph.assistant_models import AssistantRequest, FactKind, ReasonCode
from drawing_graph.assistant_semantic_write_back import SemanticServiceWriteAdapter, WriteBackGate


def policy(**overrides):
    values = dict(
        request_allow_write_back=True,
        module_allow_write_back=True,
        environment_allow_write_back=True,
        allowed_fact_kinds=(FactKind.SEMANTIC_OBSERVATION, FactKind.SEMANTIC_INTERPRETATION),
        block_on_conflict_severities=(ConflictSeverity.BLOCKING, ConflictSeverity.CRITICAL),
    )
    values.update(overrides)
    return WriteBackPolicy(**values)


def batch(**overrides):
    values = dict(
        recognition_run_id="run:1",
        schema_valid=True,
        scope_valid=True,
        payload_sanitized=True,
        audit_material_complete=True,
        sanitized_payload_envelope={"run_id": "run:1"},
    )
    values.update(overrides)
    return SemanticWriteBatch(**values)


def request(allow_write_back=True):
    return AssistantRequest(request_id="req:1", question="q", allow_write_back=allow_write_back)


class WriteBackGateTests(unittest.TestCase):
    def test_all_gates_pass_allows_write_back(self):
        result = WriteBackGate().evaluate(policy(), batch(), assistant_request=request())
        self.assertTrue(result.allowed)
        self.assertEqual((), result.reason_codes)

    def test_request_deny_blocks(self):
        result = WriteBackGate().evaluate(policy(request_allow_write_back=False), batch())
        self.assertFalse(result.allowed)
        self.assertIn(ReasonCode.WRITE_BACK_DENIED, result.reason_codes)

    def test_module_deny_blocks(self):
        result = WriteBackGate().evaluate(policy(module_allow_write_back=False), batch())
        self.assertFalse(result.allowed)

    def test_environment_deny_blocks(self):
        result = WriteBackGate().evaluate(policy(environment_allow_write_back=False), batch())
        self.assertFalse(result.allowed)

    def test_policy_cannot_broaden_beyond_request(self):
        result = WriteBackGate().evaluate(policy(), batch(), assistant_request=request(allow_write_back=False))
        self.assertFalse(result.allowed)
        self.assertIn(ReasonCode.WRITE_BACK_DENIED, result.reason_codes)

    def test_schema_invalid_fails_closed(self):
        result = WriteBackGate().evaluate(policy(), batch(schema_valid=False))
        self.assertFalse(result.allowed)

    def test_scope_invalid_fails_closed(self):
        result = WriteBackGate().evaluate(policy(), batch(scope_valid=False))
        self.assertFalse(result.allowed)

    def test_payload_not_sanitized_fails_closed(self):
        result = WriteBackGate().evaluate(policy(), batch(payload_sanitized=False))
        self.assertFalse(result.allowed)

    def test_audit_incomplete_fails_closed(self):
        result = WriteBackGate().evaluate(policy(), batch(audit_material_complete=False))
        self.assertFalse(result.allowed)

    def test_dependency_unavailable_fails_closed(self):
        result = WriteBackGate().evaluate(policy(), batch(), persistence_available=False)
        self.assertFalse(result.allowed)
        self.assertIn(ReasonCode.PERSISTENCE_UNAVAILABLE, result.reason_codes)

    def test_blocking_conflict_fails_closed(self):
        conflict = ConflictRecord(
            conflict_id="conflict:1",
            comparison_key="comparison:1",
            conflict_type=ConflictType.HARD_CONFLICT,
            severity=ConflictSeverity.BLOCKING,
            evidence_ids=("e:1", "e:2"),
        )
        result = WriteBackGate().evaluate(policy(), batch(), conflicts=(conflict,))
        self.assertFalse(result.allowed)
        self.assertIn(ReasonCode.EVIDENCE_CONFLICT, result.reason_codes)

    def test_recommendation_confidence_and_text_cannot_broaden_authorization(self):
        result = WriteBackGate().evaluate(policy(request_allow_write_back=False), batch())
        self.assertFalse(result.allowed)


class RecordingPersist:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def __call__(self, batch):
        self.calls.append(batch)
        if self.fail:
            raise RuntimeError("boom")
        return "payload:1"


class RecordingMarkStale:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def __call__(self, evidence_ids, **kwargs):
        self.calls.append((evidence_ids, kwargs))
        if self.fail:
            raise RuntimeError("stale fail")
        return tuple(evidence_ids)


class WriteBackStateMachineTests(unittest.TestCase):
    def _adapter(self, persist=None, mark_stale=None):
        return SemanticServiceWriteAdapter(
            persist_validated_batch=persist or RecordingPersist(),
            mark_evidence_stale=mark_stale,
        )

    def test_gate_denied_returns_skipped_without_persist(self):
        persist = RecordingPersist()
        adapter = self._adapter(persist=persist)
        result = adapter.persist(batch(), policy(request_allow_write_back=False))
        self.assertEqual(WriteBackStatus.SKIPPED, result.status)
        self.assertEqual([], persist.calls)

    def test_success_returns_persisted(self):
        adapter = self._adapter()
        result = adapter.persist(batch(), policy())
        self.assertEqual(WriteBackStatus.PERSISTED, result.status)
        self.assertEqual(("run:1",), result.recognition_run_ids)

    def test_semantic_failure_returns_failed(self):
        adapter = self._adapter(persist=RecordingPersist(fail=True))
        result = adapter.persist(batch(), policy())
        self.assertEqual(WriteBackStatus.FAILED, result.status)

    def test_lineage_failure_after_semantic_is_partial(self):
        adapter = self._adapter(persist=RecordingPersist(), mark_stale=RecordingMarkStale(fail=True))
        lineage_plan = LineagePlan(
            plan_id="plan:1",
            evidence_family_key="family:1",
            evidence_ids=("obs:1",),
            superseded_by_evidence_id="obs:2",
        )
        result = adapter.persist(batch(), policy(), lineage_plan=lineage_plan)
        self.assertEqual(WriteBackStatus.PARTIAL, result.status)
        self.assertIn(ReasonCode.LINEAGE_WRITE_FAILED, result.reason_codes)

    def test_replay_uses_same_stable_ids(self):
        adapter = self._adapter()
        first = adapter.persist(batch(), policy())
        second = adapter.persist(batch(), policy())
        self.assertEqual(first.recognition_run_ids, second.recognition_run_ids)
        self.assertEqual(first.status, second.status)


if __name__ == "__main__":
    unittest.main()
