"""Tests for rule-based question routing."""

import unittest

from drawing_graph.assistant_models import AssistantScope
from drawing_graph.assistant_question_rules import (
    QuestionRouteResult,
    RuleQuestionRouter,
)


class RuleQuestionRouterSkeletonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = RuleQuestionRouter()

    def test_route_returns_stable_result_fields(self):
        result = self.router.route("这是什么", None)
        self.assertIsInstance(result, QuestionRouteResult)
        for attribute in (
            "question_type",
            "confidence",
            "matched_rules",
            "unsupported_parts",
            "ambiguities",
        ):
            self.assertTrue(hasattr(result, attribute))

    def test_no_rule_match_returns_unknown_or_unsupported(self):
        result = self.router.route("今天天气怎么样", None)
        self.assertEqual("unknown_or_unsupported", result.question_type)
        self.assertEqual((), result.matched_rules)
        self.assertIn("question_type", result.unsupported_parts)

    def test_single_rule_match_returns_question_type_and_rule(self):
        result = self.router.route(
            "这张图主要讲什么",
            AssistantScope(page_id="page:1"),
        )
        self.assertEqual("page_summary", result.question_type)
        self.assertEqual(1, len(result.matched_rules))
        self.assertEqual((), result.ambiguities)
        self.assertEqual((), result.unsupported_parts)

    def test_multiple_equal_rules_return_ambiguous_question_type(self):
        result = self.router.route(
            "这张图主要讲什么并列出候选关系",
            AssistantScope(page_id="page:1"),
        )
        self.assertEqual("clarification_required", result.question_type)
        self.assertIn("ambiguous_question_type", result.ambiguities)
        self.assertGreaterEqual(len(result.matched_rules), 2)


class FirstVersionRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = RuleQuestionRouter()

    def test_each_question_type_has_a_chinese_typical_question(self):
        cases = (
            ("page_summary", "这张图主要讲什么"),
            ("block_relations", "这个图块有哪些关系"),
            ("block_semantic_identification", "这个图块是什么构件"),
            ("element_text_or_meaning", "这个元素的文本是什么"),
            ("candidate_relations", "列出这个图块的候选关系"),
            ("section_matches", "这个断面对应哪个标题"),
            ("table_caption_status", "table:1 的标题是什么"),
            ("drawing_diagnostic", "这张图纸的诊断结果是什么"),
            ("source_trace", "claim:1 的来源是什么"),
            ("comparison", "比较 page:1 与 page:2 的图块"),
        )
        for expected_type, question in cases:
            with self.subTest(question_type=expected_type, question=question):
                result = self.router.route(question, None)
                self.assertEqual(expected_type, result.question_type)
                self.assertEqual((), result.ambiguities)
                self.assertEqual((), result.unsupported_parts)
                self.assertTrue(result.matched_rules)

    def test_what_component_maps_to_block_semantic_identification(self):
        result = self.router.route("block:1 是什么构件", None)
        self.assertEqual("block_semantic_identification", result.question_type)
        self.assertEqual((), result.ambiguities)

    def test_which_title_maps_to_section_matches(self):
        result = self.router.route("这个断面对应哪个标题", None)
        self.assertEqual("section_matches", result.question_type)

    def test_section_title_question_does_not_steal_table_caption_status(self):
        result = self.router.route("这个断面对应哪个标题", None)
        self.assertNotEqual("table_caption_status", result.question_type)

    def test_candidate_relations_question_is_not_block_relations(self):
        result = self.router.route("列出这个图块的候选关系", None)
        self.assertEqual("candidate_relations", result.question_type)
        self.assertEqual((), result.ambiguities)


if __name__ == "__main__":
    unittest.main()
