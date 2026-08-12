"""Tests for clarification policy."""

import unittest

from drawing_graph.assistant_clarification import ClarificationPolicy
from drawing_graph.assistant_models import (
    AssistantRequest,
    AssistantScope,
    EvidenceRequirement,
    EvidenceType,
    ReasonCode,
)
from drawing_graph.assistant_question_rules import QuestionRouteResult
from drawing_graph.assistant_scope_resolution import ScopeResolutionResult


def make_request() -> AssistantRequest:
    return AssistantRequest(request_id="req:1", question="q")


def make_route(
    question_type: str,
    ambiguities: tuple[str, ...] = (),
) -> QuestionRouteResult:
    return QuestionRouteResult(
        question_type=question_type,
        confidence=1.0,
        ambiguities=ambiguities,
    )


def make_scope_result(
    scope: AssistantScope | None = None,
    conflicts: tuple[str, ...] = (),
    ambiguities: tuple[str, ...] = (),
) -> ScopeResolutionResult:
    return ScopeResolutionResult(
        scope=scope,
        conflicts=conflicts,
        ambiguities=ambiguities,
    )


class ClarificationPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = ClarificationPolicy()

    def test_missing_block_scope_returns_scope_missing_item(self):
        route = make_route("block_relations")
        decision = self.policy.evaluate(
            make_request(),
            route,
            make_scope_result(scope=None),
            (),
        )
        self.assertTrue(decision.required)
        self.assertTrue(decision.items)
        self.assertEqual(ReasonCode.SCOPE_MISSING, decision.items[0].reason_code)
        self.assertEqual("block_id", decision.items[0].target_field)
        self.assertIn("scope_missing", decision.reason_codes)

    def test_scope_conflict_returns_required_clarification(self):
        route = make_route("page_summary")
        decision = self.policy.evaluate(
            make_request(),
            route,
            make_scope_result(scope=None, conflicts=("scope_conflict",)),
            (),
        )
        self.assertTrue(decision.required)
        self.assertEqual(ReasonCode.SCOPE_CONFLICT, decision.items[0].reason_code)
        self.assertIn("scope_conflict", decision.reason_codes)

    def test_ambiguous_reference_returns_required_clarification(self):
        route = make_route("block_relations")
        decision = self.policy.evaluate(
            make_request(),
            route,
            make_scope_result(scope=None, ambiguities=("ambiguous_reference",)),
            (),
        )
        self.assertTrue(decision.required)
        self.assertEqual(ReasonCode.AMBIGUOUS_REFERENCE, decision.items[0].reason_code)

    def test_ambiguous_question_type_returns_required_clarification(self):
        route = make_route(
            "clarification_required",
            ambiguities=("ambiguous_question_type",),
        )
        decision = self.policy.evaluate(
            make_request(),
            route,
            make_scope_result(scope=AssistantScope(page_id="page:1")),
            (),
        )
        self.assertTrue(decision.required)
        self.assertEqual(
            ReasonCode.AMBIGUOUS_QUESTION_TYPE,
            decision.items[0].reason_code,
        )

    def test_clarification_does_not_force_required_evidence(self):
        requirement = EvidenceRequirement(
            requirement_id="req:1",
            evidence_type=EvidenceType.BLOCK_RELATIONS,
            target_scope=AssistantScope(block_id="block:1"),
        )
        route = make_route("block_relations")
        decision = self.policy.evaluate(
            make_request(),
            route,
            make_scope_result(scope=None),
            (requirement,),
        )
        self.assertTrue(decision.required)
        self.assertTrue(decision.items)

    def test_supported_question_with_full_scope_is_not_clarified(self):
        route = make_route("page_summary")
        decision = self.policy.evaluate(
            make_request(),
            route,
            make_scope_result(scope=AssistantScope(page_id="page:1")),
            (),
        )
        self.assertFalse(decision.required)
        self.assertEqual((), decision.items)

    def test_unsupported_question_is_not_clarification(self):
        route = make_route("unknown_or_unsupported")
        decision = self.policy.evaluate(
            make_request(),
            route,
            make_scope_result(scope=None),
            (),
        )
        self.assertFalse(decision.required)
        self.assertEqual((), decision.items)


if __name__ == "__main__":
    unittest.main()
