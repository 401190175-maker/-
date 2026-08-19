"""Tests for the feedback permission policy (08 feedback loop)."""

import unittest

from drawing_graph.assistant_feedback_models import (
    FeedbackAction,
    FeedbackPermission,
)
from drawing_graph.assistant_feedback_permissions import (
    FeedbackPermissionPolicy,
    PermissionDecision,
)


class _Actor:
    def __init__(self, permissions=()):
        self.permissions = frozenset(permissions)


class FeedbackPermissionPolicyTests(unittest.TestCase):
    def test_default_is_fail_closed(self):
        policy = FeedbackPermissionPolicy()
        for action in FeedbackAction:
            decision = policy.authorize(_Actor(), action)
            self.assertFalse(decision.allowed, action)

    def test_record_feedback_allows_confirm_reject_correct(self):
        policy = FeedbackPermissionPolicy()
        actor = _Actor((FeedbackPermission.RECORD_FEEDBACK,))
        for action in (FeedbackAction.CONFIRM, FeedbackAction.REJECT, FeedbackAction.CORRECT):
            decision = policy.authorize(actor, action)
            self.assertTrue(decision.allowed, action)

    def test_request_review_requires_candidate_review_permission(self):
        policy = FeedbackPermissionPolicy(allow_write_back=True)
        actor = _Actor((FeedbackPermission.RECORD_FEEDBACK,))
        decision = policy.authorize(actor, FeedbackAction.REQUEST_REVIEW)
        self.assertFalse(decision.allowed)
        self.assertIn(FeedbackPermission.REQUEST_CANDIDATE_REVIEW, decision.denied)

    def test_request_review_blocked_when_write_back_false(self):
        policy = FeedbackPermissionPolicy(allow_write_back=False)
        actor = _Actor(
            (
                FeedbackPermission.RECORD_FEEDBACK,
                FeedbackPermission.REQUEST_CANDIDATE_REVIEW,
            )
        )
        decision = policy.authorize(actor, FeedbackAction.REQUEST_REVIEW)
        self.assertFalse(decision.allowed)

    def test_request_review_allowed_with_permission_and_write_back(self):
        policy = FeedbackPermissionPolicy(allow_write_back=True)
        actor = _Actor(
            (
                FeedbackPermission.RECORD_FEEDBACK,
                FeedbackPermission.REQUEST_CANDIDATE_REVIEW,
            )
        )
        decision = policy.authorize(actor, FeedbackAction.REQUEST_REVIEW)
        self.assertTrue(decision.allowed)

    def test_feedback_action_never_grants_promote_formal_relation(self):
        policy = FeedbackPermissionPolicy(allow_write_back=True)
        actor = _Actor(
            (
                FeedbackPermission.RECORD_FEEDBACK,
                FeedbackPermission.PROMOTE_FORMAL_RELATION,
            )
        )
        decision = policy.authorize(actor, FeedbackAction.CONFIRM)
        self.assertTrue(decision.allowed)
        self.assertNotIn(FeedbackPermission.PROMOTE_FORMAL_RELATION, decision.granted)

    def test_invalid_action_raises(self):
        policy = FeedbackPermissionPolicy()
        with self.assertRaises(ValueError):
            policy.authorize(_Actor(), "not_an_action")


class PermissionDecisionTests(unittest.TestCase):
    def test_decision_defaults_denied(self):
        decision = PermissionDecision(allowed=False)
        self.assertFalse(decision.allowed)
        self.assertEqual(frozenset(), decision.granted)


if __name__ == "__main__":
    unittest.main()
