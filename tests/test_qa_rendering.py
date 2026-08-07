import unittest

from drawing_graph.qa_models import (
    AnswerFact,
    QAAnswer,
    QAAnswerStatus,
    QAScope,
    QuestionType,
)
from drawing_graph.qa_rendering import render_qa_answer_zh_brief


def _answer(status=QAAnswerStatus.ANSWERED, summary="摘要", facts=(), warnings=(), unsupported=()):
    return QAAnswer(
        question_type=QuestionType.PAGE_SUMMARY,
        scope=QAScope(page_id="page:1"),
        status=status,
        summary=summary,
        facts=facts,
        warnings=warnings,
        unsupported_parts=unsupported,
    )


def _fact(fact_kind, label, status="confirmed"):
    return AnswerFact(fact_kind=fact_kind, label=label, status=status)


class RenderQaAnswerZhBriefTests(unittest.TestCase):
    def test_renders_summary_and_facts(self):
        answer = _answer(
            summary="页面有 3 个元素",
            facts=(_fact("source_fact", "页面元素"),),
        )
        rendered = render_qa_answer_zh_brief(answer)
        self.assertIn("摘要：页面有 3 个元素", rendered)
        self.assertIn("来源事实", rendered)
        self.assertIn("页面元素", rendered)

    def test_candidate_relation_is_rendered_as_candidate(self):
        answer = _answer(
            facts=(
                _fact("candidate_relation", "候选标题关系", status="candidate"),
            ),
        )
        rendered = render_qa_answer_zh_brief(answer)
        self.assertIn("候选关系", rendered)
        self.assertIn("候选", rendered)
        self.assertNotIn("已确认关系", rendered)
        self.assertNotIn("正式关系", rendered)

    def test_formal_relation_is_rendered_as_formal(self):
        answer = _answer(
            facts=(_fact("formal_relation", "断面正式匹配", status="confirmed"),),
        )
        rendered = render_qa_answer_zh_brief(answer)
        self.assertIn("正式关系", rendered)

    def test_conservative_statuses_are_preserved(self):
        answer = _answer(
            facts=(
                _fact("derived_relation", "关系", status="partial"),
                _fact("candidate_relation", "候选", status="ambiguous"),
                _fact("diagnostic", "诊断", status="not_found"),
                _fact("diagnostic", "识别", status="not_recognized"),
                _fact("diagnostic", "识别失败", status="recognition_failed"),
            ),
        )
        rendered = render_qa_answer_zh_brief(answer)
        self.assertIn("部分可用", rendered)
        self.assertIn("歧义", rendered)
        self.assertIn("未找到", rendered)
        self.assertIn("未识别", rendered)
        self.assertIn("识别失败", rendered)

    def test_warnings_and_unsupported_parts_are_rendered(self):
        answer = _answer(
            warnings=("语义证据查询不可用",),
            unsupported=("缺少 facade 专用查询",),
        )
        rendered = render_qa_answer_zh_brief(answer)
        self.assertIn("语义证据查询不可用", rendered)
        self.assertIn("缺少 facade 专用查询", rendered)

    def test_unsupported_answer_status_is_conservative(self):
        answer = _answer(
            status=QAAnswerStatus.UNSUPPORTED,
            summary="该问题类型不受支持",
        )
        rendered = render_qa_answer_zh_brief(answer)
        self.assertIn("不受支持", rendered)


if __name__ == "__main__":
    unittest.main()
