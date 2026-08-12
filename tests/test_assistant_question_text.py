"""Tests for question text normalization."""

import unittest

from drawing_graph.assistant_question_text import QuestionTextNormalizer


class QuestionTextNormalizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.normalizer = QuestionTextNormalizer()

    def test_normalize_strips_leading_and_trailing_whitespace(self):
        self.assertEqual(
            "这张图主要讲什么",
            self.normalizer.normalize("  这张图主要讲什么  \n"),
        )

    def test_normalize_collapses_repeated_whitespace(self):
        self.assertEqual(
            "这张图 主要讲什么",
            self.normalizer.normalize("这张图   主要讲什么"),
        )

    def test_normalize_unifies_full_width_punctuation(self):
        self.assertEqual(
            "这张图主要讲什么,并列出候选关系?",
            self.normalizer.normalize("这张图主要讲什么，并列出候选关系？"),
        )
        self.assertEqual(
            "(block:1)是什么构件",
            self.normalizer.normalize("（block:1）是什么构件"),
        )

    def test_normalize_preserves_stable_business_ids(self):
        normalized = self.normalizer.normalize("请查询 page:1 与 block:B-01 的关系")
        self.assertIn("page:1", normalized)
        self.assertIn("block:B-01", normalized)

    def test_normalize_preserves_case_sensitive_id_content(self):
        normalized = self.normalizer.normalize("block:aBc-01 与 block:ABC-01 是否相同")
        self.assertIn("block:aBc-01", normalized)
        self.assertIn("block:ABC-01", normalized)

    def test_normalize_preserves_chinese_semantics(self):
        self.assertEqual(
            "这个图块是什么构件?",
            self.normalizer.normalize("这个图块是什么构件？"),
        )

    def test_normalize_rejects_empty_question_instead_of_swallowing(self):
        with self.assertRaises(ValueError):
            self.normalizer.normalize("")
        with self.assertRaises(ValueError):
            self.normalizer.normalize("   \n\t  ")


if __name__ == "__main__":
    unittest.main()
