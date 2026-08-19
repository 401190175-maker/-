"""Tests for the deterministic Chinese answer template renderer."""

import unittest

from drawing_graph.assistant_answer_templates import (
    ChineseAnswerTemplateRenderer,
    fact_kind_wording,
)
from drawing_graph.assistant_models import (
    ANSWER_CONTRACT_VERSION,
    AnswerStatus,
    Claim,
    FactKind,
    MachineAnswer,
)


def make_machine(status=AnswerStatus.ANSWERED, claims=(), unsupported_parts=(), follow_up_actions=()):
    return MachineAnswer(
        answer_contract_version=ANSWER_CONTRACT_VERSION,
        request_id="req:1",
        question_type="page_summary",
        status=status,
        claims=claims,
        unsupported_parts=unsupported_parts,
        follow_up_actions=follow_up_actions,
    )


class TemplateStructureTests(unittest.TestCase):
    def test_five_sections_in_fixed_order(self):
        text = ChineseAnswerTemplateRenderer().render(make_machine())
        headers = ("结论：", "依据：", "候选/冲突/限定语：", "注意：", "后续动作：")
        positions = [text.index(header) for header in headers]
        self.assertEqual(positions, sorted(positions))

    def test_each_answer_status_has_stable_text(self):
        renderer = ChineseAnswerTemplateRenderer()
        for status in AnswerStatus:
            text = renderer.render(make_machine(status=status))
            self.assertIn("结论：", text)
            self.assertTrue(text.strip())

    def test_status_produces_deterministic_text(self):
        renderer = ChineseAnswerTemplateRenderer()
        first = renderer.render(make_machine(status=AnswerStatus.ANSWERED))
        second = renderer.render(make_machine(status=AnswerStatus.ANSWERED))
        self.assertEqual(first, second)

    def test_empty_sections_are_handled(self):
        text = ChineseAnswerTemplateRenderer().render(make_machine())
        self.assertIn("（无依据）", text)
        self.assertIn("（无）", text)

    def test_no_new_claims_introduced(self):
        claim = Claim(
            claim_id="claim:1",
            statement="该图块包含标题",
            claim_type="observed_text_or_symbol",
            status="supported",
            evidence_ids=("evidence:1",),
            fact_kinds=(FactKind.SEMANTIC_OBSERVATION,),
        )
        text = ChineseAnswerTemplateRenderer().render(make_machine(claims=(claim,)))
        self.assertIn("该图块包含标题", text)
        self.assertNotIn("该图块是一个泵", text)


class FactKindWordingTests(unittest.TestCase):
    def test_wording_is_distinct_per_fact_kind(self):
        wordings = {
            fact_kind_wording(kind)
            for kind in (
                FactKind.SEMANTIC_OBSERVATION,
                FactKind.SEMANTIC_INTERPRETATION,
                FactKind.CANDIDATE_RELATION,
                FactKind.FORMAL_RELATION,
                FactKind.DIAGNOSTIC,
            )
        }
        self.assertEqual(5, len(wordings))

    def test_observation_uses_observe_wording(self):
        self.assertEqual("图中观察到", fact_kind_wording(FactKind.SEMANTIC_OBSERVATION))

    def test_interpretation_uses_interpret_wording(self):
        self.assertEqual("语义解释为", fact_kind_wording(FactKind.SEMANTIC_INTERPRETATION))

    def test_candidate_not_promoted_to_formal(self):
        self.assertEqual("候选关系", fact_kind_wording(FactKind.CANDIDATE_RELATION))
        self.assertNotEqual(
            fact_kind_wording(FactKind.CANDIDATE_RELATION),
            fact_kind_wording(FactKind.FORMAL_RELATION),
        )

    def test_interpretation_not_written_as_source_fact(self):
        self.assertNotEqual(
            fact_kind_wording(FactKind.SEMANTIC_INTERPRETATION),
            fact_kind_wording(FactKind.SOURCE_FACT),
        )

    def test_claim_renders_qualifiers_without_losing_them(self):
        claim = Claim(
            claim_id="claim:1",
            statement="该图块是标题",
            claim_type="observed_text_or_symbol",
            status="qualified",
            evidence_ids=("evidence:1",),
            fact_kinds=(FactKind.SEMANTIC_OBSERVATION,),
            qualifiers=("low_confidence",),
        )
        machine = MachineAnswer(
            answer_contract_version=ANSWER_CONTRACT_VERSION,
            request_id="req:1",
            question_type="page_summary",
            status=AnswerStatus.PARTIAL,
            claims=(claim,),
        )
        text = ChineseAnswerTemplateRenderer().render(machine)
        self.assertIn("low_confidence", text)


if __name__ == "__main__":
    unittest.main()
