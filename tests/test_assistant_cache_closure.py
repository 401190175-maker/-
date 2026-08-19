"""Tests for cache closure summary (Task 36)."""

import unittest

from drawing_graph.assistant_cache_closure import CacheClosureEvaluator
from drawing_graph.assistant_evidence_fusion_models import (
    CacheClosureStatus,
    LineagePlan,
    WriteBackResult,
    WriteBackStatus,
)
from drawing_graph.assistant_evidence_lineage import LineageResult
from drawing_graph.assistant_models import CacheCandidate, CacheDisposition
from drawing_graph.recognition_models import CacheOutcome


def outcome(target_id, disposition="hit", cache_key="semantic:1", reused=()):
    return CacheOutcome(
        target_id=target_id,
        disposition=disposition,
        cache_key=cache_key,
        reused_evidence_ids=reused,
        provider_called=(disposition == "miss"),
    )


def candidate(target_id, disposition=CacheDisposition.FULL_HIT):
    return CacheCandidate(
        requirement_id=f"req:{target_id}",
        target_id=target_id,
        cache_key="semantic:1",
        disposition=disposition,
    )


class CacheClosureEvaluatorTests(unittest.TestCase):
    def _status(self, outcomes, expected=()):
        return CacheClosureEvaluator().evaluate(expected, outcomes).status

    def test_full_hit(self):
        self.assertEqual(
            CacheClosureStatus.FULL_HIT,
            self._status((outcome("t1", "hit", reused=("obs:1",)),)),
        )

    def test_partial_hit(self):
        self.assertEqual(
            CacheClosureStatus.PARTIAL_HIT,
            self._status((outcome("t1", "hit"), outcome("t2", "miss"))),
        )

    def test_miss(self):
        self.assertEqual(
            CacheClosureStatus.MISS,
            self._status((outcome("t1", "miss"),)),
        )

    def test_stale(self):
        lineage = LineageResult(
            plans=(
                LineagePlan(
                    plan_id="plan:1",
                    evidence_family_key="family:1",
                    evidence_ids=("obs:1",),
                ),
            )
        )
        summary = CacheClosureEvaluator().evaluate(
            (),
            (outcome("t1", "hit", reused=("obs:1",)),),
            lineage=lineage,
        )
        self.assertEqual(CacheClosureStatus.STALE, summary.status)

    def test_bypassed(self):
        self.assertEqual(
            CacheClosureStatus.BYPASSED,
            self._status((outcome("t1", "bypassed"),)),
        )

    def test_mixed(self):
        self.assertEqual(
            CacheClosureStatus.MIXED,
            self._status((outcome("t1", "hit"), outcome("t2", "bypassed"))),
        )

    def test_unknown_when_no_outcomes(self):
        self.assertEqual(CacheClosureStatus.UNKNOWN, self._status(()))

    def test_unmatched_expected_target_is_unknown_with_warning(self):
        summary = CacheClosureEvaluator().evaluate(
            (candidate("t1"), candidate("t2")),
            (outcome("t1", "hit"),),
        )
        self.assertEqual(CacheClosureStatus.UNKNOWN, summary.status)
        self.assertEqual(1, len(summary.warnings))

    def test_only_reports_committed_when_persistent_cache_committed(self):
        summary = CacheClosureEvaluator().evaluate(
            (),
            (outcome("t1", "hit"),),
            write_back_result=WriteBackResult(
                status=WriteBackStatus.PERSISTED,
                persistent_cache_committed=True,
            ),
        )
        self.assertTrue(summary.persistent_cache_committed)

    def test_not_committed_by_default(self):
        summary = CacheClosureEvaluator().evaluate((), (outcome("t1", "hit"),))
        self.assertFalse(summary.persistent_cache_committed)

    def test_target_summary_carries_expected_and_actual(self):
        summary = CacheClosureEvaluator().evaluate(
            (candidate("t1", CacheDisposition.MISS),),
            (outcome("t1", "miss"),),
        )
        target = summary.targets[0]
        self.assertEqual("t1", target.target_id)
        self.assertEqual(CacheDisposition.MISS, target.expected_disposition)
        self.assertEqual(CacheClosureStatus.MISS, target.actual_disposition)
        self.assertTrue(target.provider_called)


if __name__ == "__main__":
    unittest.main()
