"""Tests for deterministic page-search text matching."""

from __future__ import annotations

import unittest

from drawing_graph.page_search_matcher import TextMatcher, normalize_text


class TextMatcherTests(unittest.TestCase):
    def test_normalize_removes_punctuation(self) -> None:
        # 连字符也会被剥离：A-A -> aa
        self.assertEqual(normalize_text("A-A剖面！"), "aa剖面")

    def test_all_query_tokens_must_match(self) -> None:
        matcher = TextMatcher()
        self.assertTrue(matcher.matches("排水", "本页含排水管道"))
        self.assertFalse(matcher.matches("排水 挡土墙", "本页含排水管道"))

    def test_query_tokens_are_normalized(self) -> None:
        matcher = TextMatcher()
        self.assertTrue(matcher.matches("A-A", "图上有 a-a 剖面"))

    def test_empty_query_never_matches(self) -> None:
        matcher = TextMatcher()
        self.assertFalse(matcher.matches("   ", "任意文本"))


class SynonymExpansionMatcherTests(unittest.TestCase):
    def test_expands_query_token(self) -> None:
        from drawing_graph.page_search_matcher import SynonymExpansionMatcher

        matcher = SynonymExpansionMatcher()
        self.assertTrue(matcher.matches("排水", "本页含雨水管"))
        self.assertTrue(matcher.matches("挡土墙", "挡墙结构"))
        self.assertTrue(matcher.matches("混凝土", "砼"))

    def test_plain_token_still_matches(self) -> None:
        from drawing_graph.page_search_matcher import SynonymExpansionMatcher

        matcher = SynonymExpansionMatcher()
        self.assertTrue(matcher.matches("C35", "强度 C35"))
        self.assertFalse(matcher.matches("C35", "强度 C30"))


if __name__ == "__main__":
    unittest.main()
