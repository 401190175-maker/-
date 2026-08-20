"""Routing tests for civil-engineer phrasing."""

from __future__ import annotations

import unittest

from drawing_graph.assistant_question_rules import RuleQuestionRouter


class CivilEngineerRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = RuleQuestionRouter()

    def assert_routes(self, question: str, expected: str) -> None:
        self.assertEqual(self.router.route(question, None).question_type, expected)

    def test_full_set_search_phrasings(self) -> None:
        self.assert_routes("挡土墙的横断面图在哪一页", "page_content_search")
        self.assert_routes("哪些图是关于排水的", "page_content_search")
        self.assert_routes("哪块砖的混凝土强度等级是C35", "page_content_search")

    def test_section_location_phrasing(self) -> None:
        self.assert_routes("A-A剖面在哪个图块上", "section_matches")

    def test_short_component_phrasing(self) -> None:
        self.assert_routes("这块是什么", "block_semantic_identification")

    def test_existing_intents_are_not_regressed(self) -> None:
        self.assert_routes("这张图主要讲什么", "page_summary")
        self.assert_routes("这个图块有哪些候选关系", "candidate_relations")
        self.assert_routes("这个图块是什么构件", "block_semantic_identification")
        self.assert_routes("这个元素是什么", "element_text_or_meaning")
        self.assert_routes("这个断面对应哪个标题", "section_matches")


if __name__ == "__main__":
    unittest.main()
