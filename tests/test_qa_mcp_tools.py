import unittest


class McpSuccessMappingTests(unittest.TestCase):
    """QAAnswer -> MCP success structured content and same-source text summary."""

    def test_success_mapping_preserves_full_qa_answer(self):
        from drawing_graph.qa_mcp_tools import map_qa_answer_to_success
        from drawing_graph.qa_models import (
            AnswerFact,
            EvidenceRef,
            QAAnswer,
            QAAnswerStatus,
            QAScope,
            QuestionType,
        )

        answer = QAAnswer(
            question_type=QuestionType.BLOCK_RELATIONS,
            scope=QAScope(block_id="block:1"),
            status=QAAnswerStatus.ANSWERED,
            summary="图块关系可用",
            facts=(
                AnswerFact(
                    fact_kind="derived_relation",
                    label="标题关系",
                    status="confirmed",
                    ids={"block_id": "block:1", "page_id": "page:1"},
                    relation_type="HAS_CAPTION",
                    value=("caption:1",),
                    evidence=(EvidenceRef(block_id="block:1", page_id="page:1"),),
                ),
            ),
            warnings=("warn-a",),
            unsupported_parts=("part-b",),
            source_calls=("get_block_trace",),
        )

        outcome = map_qa_answer_to_success("ask_drawing_block", "call-1", answer)

        self.assertEqual("ok", outcome.status)
        self.assertEqual("call-1", outcome.meta.call_id)
        self.assertEqual("ask_drawing_block", outcome.meta.tool_name)
        self.assertEqual("drawing-qa-mcp-v1", outcome.meta.contract_version)
        self.assertEqual("answered", outcome.data["status"])
        self.assertEqual("图块关系可用", outcome.data["summary"])
        self.assertEqual("block:1", outcome.data["scope"]["block_id"])
        self.assertEqual("HAS_CAPTION", outcome.data["facts"][0]["relation_type"])
        self.assertEqual("derived_relation", outcome.data["facts"][0]["fact_kind"])
        evidence = outcome.data["facts"][0]["evidence"][0]
        self.assertEqual("block:1", evidence["block_id"])
        self.assertEqual("page:1", evidence["page_id"])
        self.assertEqual(["warn-a"], outcome.data["warnings"])
        self.assertEqual(["part-b"], outcome.data["unsupported_parts"])
        self.assertEqual(["get_block_trace"], outcome.data["source_calls"])

    def test_text_summary_is_generated_from_same_structured_content(self):
        from drawing_graph.qa_mcp_tools import build_mcp_text_summary, map_qa_answer_to_success
        from drawing_graph.qa_models import QAAnswer, QAAnswerStatus, QAScope, QuestionType

        answer = QAAnswer(
            question_type=QuestionType.PAGE_SUMMARY,
            scope=QAScope(page_id="page:1"),
            status=QAAnswerStatus.ANSWERED,
            summary="页面摘要可用",
            warnings=("warn-a",),
            unsupported_parts=("part-b",),
            source_calls=("get_page_source_facts",),
        )
        outcome = map_qa_answer_to_success("ask_drawing_page", "call-2", answer)

        text = build_mcp_text_summary(outcome)

        self.assertIn("answered", text)
        self.assertIn("页面摘要可用", text)
        self.assertIn("facts=0", text)
        self.assertIn("warnings=1", text)
        self.assertIn("unsupported=1", text)

    def test_partial_answer_remains_success_and_text_mentions_partial(self):
        from drawing_graph.qa_mcp_tools import build_mcp_text_summary, map_qa_answer_to_success
        from drawing_graph.qa_models import QAAnswer, QAAnswerStatus, QAScope, QuestionType

        answer = QAAnswer(
            question_type=QuestionType.TABLE_CAPTION_STATUS,
            scope=QAScope(page_id="page:1"),
            status=QAAnswerStatus.PARTIAL,
            summary="仅返回来源元素",
            unsupported_parts=("表格标题派生状态未查询",),
        )

        outcome = map_qa_answer_to_success("get_table_caption_status", "call-3", answer)

        self.assertEqual("ok", outcome.status)
        self.assertEqual("partial", outcome.data["status"])
        text = build_mcp_text_summary(outcome)
        self.assertIn("partial", text)
        self.assertIn("部分回答", text)
        self.assertIn("unsupported=1", text)


if __name__ == "__main__":
    unittest.main()
