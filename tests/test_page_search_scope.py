"""Scope resolution tests for drawing_set extraction."""

from __future__ import annotations

import unittest

from drawing_graph.assistant_scope_resolution import ScopeResolver


class DrawingSetScopeTests(unittest.TestCase):
    def test_extracts_set_prefix(self) -> None:
        result = ScopeResolver().resolve(
            "在 set:road-project:lslq_yhd_2_2 里哪些图关于排水"
        )
        self.assertEqual(result.scope.drawing_set_id, "set:road-project:lslq_yhd_2_2")

    def test_missing_drawing_set_leaves_scope_none(self) -> None:
        result = ScopeResolver().resolve("哪些图关于排水")
        self.assertIsNone(result.scope)


if __name__ == "__main__":
    unittest.main()
