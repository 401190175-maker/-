"""Tests for per-page searchable content collection."""

from __future__ import annotations

import unittest

from drawing_graph.page_search_collector import PageContentCollector
from drawing_graph.tool_models import PageSourceFacts, PageSummary, ToolModelError


class _FakeFacade:
    def __init__(
        self,
        facts: PageSourceFacts | None = None,
        observations: tuple[object, ...] = (),
        interpretations: tuple[object, ...] = (),
    ) -> None:
        self._facts = facts
        self._observations = observations
        self._interpretations = interpretations

    def get_page_source_facts(self, page_id: str, element_types=None, include_image_meta=True):
        return self._facts

    def list_text_observations(self, page_id=None, element_id=None, recognition_run_id=None, statuses=None, write_back=False):
        if not self._observations:
            raise ToolModelError("NOT_FOUND", "text observations were not found")
        return self._observations

    def list_interpretations(self, page_id=None, element_id=None, recognition_run_id=None, statuses=None, write_back=False):
        if not self._interpretations:
            raise ToolModelError("NOT_FOUND", "interpretations were not found")
        return self._interpretations


class _FakeObservation:
    raw_text = "排水管道"
    normalized_text = "排水管道"
    target_element_id = "element:1"


class _FakeInterpretation:
    summary = "挡土墙"
    interpreted_type = "retaining_wall"
    element_id = "element:2"


class PageContentCollectorTests(unittest.TestCase):
    def _page(self) -> PageSummary:
        return PageSummary(
            drawing_set_id="set:1",
            page_id="page:1",
            file_stem="road_68",
        )

    def test_collect_includes_title_and_observations(self) -> None:
        collector = PageContentCollector(_FakeFacade(observations=(_FakeObservation(),)))
        content = collector.collect(self._page())
        kinds = {item.kind for item in content.items}
        self.assertIn("page_title", kinds)
        self.assertIn("observation", kinds)
        self.assertTrue(content.has_semantic_content)

    def test_collect_empty_page_has_no_semantic_content(self) -> None:
        collector = PageContentCollector(_FakeFacade())
        content = collector.collect(self._page())
        self.assertFalse(content.has_semantic_content)
        self.assertTrue(any(item.kind == "page_title" for item in content.items))


if __name__ == "__main__":
    unittest.main()
