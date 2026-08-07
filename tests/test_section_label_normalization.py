import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.section_label_normalization import (
    SectionLabelNormalizer,
    SectionSymbolSystem,
)


class SectionLabelNormalizationTest(unittest.TestCase):
    def setUp(self):
        self.normalizer = SectionLabelNormalizer()

    def test_alphabetic_roman_numeric_and_alphanumeric_keys(self):
        self.assertEqual(
            ("SECTION_ALPHA_A", SectionSymbolSystem.ALPHABETIC, True),
            (
                self.normalizer.normalize_pair("A", "A").normalized_key,
                self.normalizer.normalize_pair("A", "A").symbol_system,
                self.normalizer.normalize_pair("A", "A").deterministic,
            ),
        )
        self.assertEqual(
            "SECTION_NUMERIC_1",
            self.normalizer.normalize_pair("1", "1").normalized_key,
        )
        self.assertEqual(
            "SECTION_ALPHANUMERIC_A1",
            self.normalizer.normalize_pair("A1", "A1").normalized_key,
        )

    def test_full_pair_labels_with_separators_normalize(self):
        self.assertEqual(
            "SECTION_ALPHA_A",
            self.normalizer.normalize_pair("A - A", "A-A").normalized_key,
        )
        self.assertEqual(
            "SECTION_NUMERIC_1",
            self.normalizer.normalize_pair("1－1", "1-1").normalized_key,
        )

    def test_ascii_roman_fullwidth_roman_and_numeric_do_not_merge(self):
        ascii_key = self.normalizer.normalize_pair("I", "I").normalized_key
        fullwidth_key = self.normalizer.normalize_pair("Ⅰ", "Ⅰ").normalized_key
        numeric_key = self.normalizer.normalize_pair("1", "1").normalized_key

        self.assertEqual("SECTION_ROMAN_I", ascii_key)
        self.assertEqual("SECTION_ROMAN_Ⅰ", fullwidth_key)
        self.assertEqual("SECTION_NUMERIC_1", numeric_key)
        self.assertEqual(3, len({ascii_key, fullwidth_key, numeric_key}))

    def test_mismatched_endpoints_are_not_deterministic(self):
        result = self.normalizer.normalize_pair("A", "B")

        self.assertFalse(result.deterministic)
        self.assertIsNone(result.normalized_key)
        self.assertEqual("section label endpoints do not match", result.reason)

    def test_cross_symbol_system_is_not_deterministic(self):
        result = self.normalizer.normalize_pair("1", "A")

        self.assertFalse(result.deterministic)
        self.assertIsNone(result.normalized_key)
        self.assertIn("alias rule", result.reason)

    def test_unknown_and_empty_labels_return_unknown(self):
        result = self.normalizer.normalize_pair("??", "??")
        empty_result = self.normalizer.normalize_pair("", "")

        self.assertEqual(SectionSymbolSystem.UNKNOWN, result.symbol_system)
        self.assertFalse(result.deterministic)
        self.assertIsNone(result.normalized_key)
        self.assertEqual(SectionSymbolSystem.UNKNOWN, empty_result.symbol_system)
        self.assertFalse(empty_result.deterministic)


if __name__ == "__main__":
    unittest.main()
