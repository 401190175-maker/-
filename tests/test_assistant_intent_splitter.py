"""Tests for multi-intent splitting."""

import unittest

from drawing_graph.assistant_intent_splitter import IntentSplitter
from drawing_graph.assistant_models import AssistantScope
from drawing_graph.assistant_question_rules import RuleQuestionRouter


class IntentSplitterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.splitter = IntentSplitter()
        self.router = RuleQuestionRouter()
        self.scope = AssistantScope(page_id="page:1")

    def test_splits_two_explicit_intents_into_subrequests(self):
        route = self.router.route("这张图主要讲什么，并列出候选关系", self.scope)
        subrequests = self.splitter.split(
            "这张图主要讲什么，并列出候选关系",
            route,
            self.scope,
        )
        self.assertEqual(2, len(subrequests))
        self.assertEqual("page_summary", subrequests[0].question_type)
        self.assertEqual("candidate_relations", subrequests[1].question_type)

    def test_each_subrequest_has_stable_unique_id(self):
        route = self.router.route("这张图主要讲什么，并列出候选关系", self.scope)
        subrequests = self.splitter.split(
            "这张图主要讲什么，并列出候选关系",
            route,
            self.scope,
        )
        ids = [subrequest.subrequest_id for subrequest in subrequests]
        self.assertTrue(all(ids))
        self.assertEqual(len(ids), len(set(ids)))

    def test_single_intent_returns_single_subrequest(self):
        question = "这个图块有哪些关系"
        route = self.router.route(question, self.scope)
        subrequests = self.splitter.split(question, route, self.scope)
        self.assertEqual(1, len(subrequests))
        self.assertEqual("block_relations", subrequests[0].question_type)
        self.assertEqual((), subrequests[0].ambiguities)

    def test_ambiguous_whole_question_returns_multi_intent_ambiguous(self):
        question = "这个图块是什么构件候选关系"
        route = self.router.route(question, self.scope)
        subrequests = self.splitter.split(question, route, self.scope)
        self.assertEqual(1, len(subrequests))
        self.assertEqual("clarification_required", subrequests[0].question_type)
        self.assertIn("multi_intent_ambiguous", subrequests[0].ambiguities)

    def test_unsupported_subquestion_is_not_dropped(self):
        question = "这张图主要讲什么，并计算面积"
        route = self.router.route(question, self.scope)
        subrequests = self.splitter.split(question, route, self.scope)
        self.assertEqual(2, len(subrequests))
        unsupported = subrequests[1]
        self.assertEqual("unknown_or_unsupported", unsupported.question_type)
        self.assertTrue(any("计算面积" in part for part in unsupported.unsupported_parts))


if __name__ == "__main__":
    unittest.main()
