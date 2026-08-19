"""Tests for the feedback state machine (08 feedback loop)."""

import unittest

from drawing_graph.assistant_feedback_models import (
    FeedbackAction,
    FeedbackStatus,
)
from drawing_graph.assistant_feedback_state_machine import (
    FeedbackStateMachine,
    InvalidFeedbackTransitionError,
)


class FeedbackStateMachineTests(unittest.TestCase):
    def setUp(self):
        self.machine = FeedbackStateMachine()

    def test_confirm_moves_received_to_recorded(self):
        status, transitions = self.machine.apply_action(FeedbackStatus.RECEIVED, FeedbackAction.CONFIRM)
        self.assertEqual(FeedbackStatus.RECORDED, status)
        self.assertEqual(2, len(transitions))
        self.assertEqual((FeedbackStatus.RECEIVED, FeedbackStatus.VALIDATED), (transitions[0].from_status, transitions[0].to_status))
        self.assertEqual((FeedbackStatus.VALIDATED, FeedbackStatus.RECORDED), (transitions[1].from_status, transitions[1].to_status))

    def test_request_review_moves_received_to_review_required(self):
        status, transitions = self.machine.apply_action(
            FeedbackStatus.RECEIVED, FeedbackAction.REQUEST_REVIEW
        )
        self.assertEqual(FeedbackStatus.REVIEW_REQUIRED, status)
        self.assertEqual(3, len(transitions))
        self.assertEqual(FeedbackStatus.REVIEW_REQUIRED, transitions[-1].to_status)

    def test_reject_and_correct_stop_at_recorded(self):
        for action in (FeedbackAction.REJECT, FeedbackAction.CORRECT):
            status, _ = self.machine.apply_action(FeedbackStatus.RECEIVED, action)
            self.assertEqual(FeedbackStatus.RECORDED, status)

    def test_confirm_never_reaches_formal_promotion(self):
        status, transitions = self.machine.apply_action(FeedbackStatus.RECEIVED, FeedbackAction.CONFIRM)
        self.assertNotEqual(FeedbackStatus.ACCEPTED, status)
        self.assertNotEqual(FeedbackStatus.REVIEW_REQUIRED, status)
        for transition in transitions:
            self.assertNotEqual(FeedbackStatus.ACCEPTED, transition.to_status)

    def test_review_result_from_review_required(self):
        status, transitions = self.machine.apply_review_result(
            FeedbackStatus.REVIEW_REQUIRED, "accepted"
        )
        self.assertEqual(FeedbackStatus.ACCEPTED, status)
        self.assertEqual(1, len(transitions))

    def test_review_result_requires_review_required(self):
        with self.assertRaises(InvalidFeedbackTransitionError):
            self.machine.apply_review_result(FeedbackStatus.RECEIVED, "accepted")

    def test_action_from_terminal_is_illegal(self):
        with self.assertRaises(InvalidFeedbackTransitionError):
            self.machine.apply_action(FeedbackStatus.ACCEPTED, FeedbackAction.CONFIRM)

    def test_every_transition_is_recorded(self):
        _, transitions = self.machine.apply_action(
            FeedbackStatus.RECEIVED, FeedbackAction.REQUEST_REVIEW
        )
        for transition in transitions:
            self.assertIsInstance(transition.from_status, FeedbackStatus)
            self.assertIsInstance(transition.to_status, FeedbackStatus)


if __name__ == "__main__":
    unittest.main()
