"""Tests for canonical product-answer JSON serialization."""

import unittest

from drawing_graph.assistant_answer_generation import (
    CanonicalAnswerSerializer,
    MachineAnswerBuilder,
)
from drawing_graph.assistant_models import (
    ANSWER_CONTRACT_VERSION,
    AnswerStatus,
    AssistantScope,
    Citation,
    Claim,
    FactKind,
    MachineAnswer,
)


def make_machine_answer():
    claim = Claim(
        claim_id="claim:1",
        statement="该图块包含标题",
        claim_type="observed_text_or_symbol",
        status="supported",
        evidence_ids=("evidence:1",),
        fact_kinds=(FactKind.SEMANTIC_OBSERVATION,),
        scope=AssistantScope(page_id="page:1"),
    )
    citation = Citation(
        citation_id="citation:1",
        evidence_id="evidence:1",
        claim_ids=("claim:1",),
        page_id="page:1",
    )
    return MachineAnswerBuilder().build(
        request_id="req:1",
        question_type="page_summary",
        scope=AssistantScope(page_id="page:1"),
        status=AnswerStatus.ANSWERED,
        claims=(claim,),
        citations=(citation,),
        recognition_run_ids=("run:1",),
    )


class CanonicalSerializationTests(unittest.TestCase):
    def test_same_input_produces_byte_identical_json(self):
        serializer = CanonicalAnswerSerializer()
        first = serializer.serialize(make_machine_answer())
        second = serializer.serialize(make_machine_answer())
        self.assertEqual(first, second)

    def test_output_is_utf8_chinese(self):
        serializer = CanonicalAnswerSerializer()
        text = serializer.serialize(make_machine_answer())
        self.assertIn("该图块包含标题", text)
        self.assertIn("drawing-assistant-answer-v1", text)

    def test_output_is_valid_json(self):
        import json

        serializer = CanonicalAnswerSerializer()
        text = serializer.serialize(make_machine_answer())
        parsed = json.loads(text)
        self.assertEqual("drawing-assistant-answer-v1", parsed["answer_contract_version"])
        self.assertEqual("req:1", parsed["request_id"])

    def test_rejects_nan_or_infinity(self):
        serializer = CanonicalAnswerSerializer()
        machine = MachineAnswer(
            answer_contract_version=ANSWER_CONTRACT_VERSION,
            request_id="req:1",
            question_type="page_summary",
            status=AnswerStatus.ANSWERED,
            warnings=(float("nan"),),
        )
        with self.assertRaises(ValueError):
            serializer.serialize(machine)

    def test_rejects_non_serializable_object(self):
        serializer = CanonicalAnswerSerializer()
        machine = MachineAnswer(
            answer_contract_version=ANSWER_CONTRACT_VERSION,
            request_id="req:1",
            question_type="page_summary",
            status=AnswerStatus.ANSWERED,
            warnings=(object(),),
        )
        with self.assertRaises(TypeError):
            serializer.serialize(machine)


if __name__ == "__main__":
    unittest.main()
