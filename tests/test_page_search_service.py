"""Tests for the full-set page search service (no recognition yet)."""

from __future__ import annotations

import unittest

from drawing_graph.page_search_service import PageContentSearchService
from drawing_graph.tool_models import PageSummary, ToolModelError


class _FakeFacade:
    def __init__(self, pages: list[PageSummary]) -> None:
        self._pages = pages

    def list_pages(self, drawing_set_id: str, limit: int = 100, offset: int = 0):
        return tuple(self._pages[offset : offset + limit])

    def get_page_source_facts(self, page_id: str, element_types=None, include_image_meta=True):
        return None

    def list_text_observations(self, page_id=None, element_id=None, recognition_run_id=None, statuses=None, write_back=False):
        raise ToolModelError("NOT_FOUND", "no observations")

    def list_interpretations(self, page_id=None, element_id=None, recognition_run_id=None, statuses=None, write_back=False):
        raise ToolModelError("NOT_FOUND", "no interpretations")


class _ObservingFacade(_FakeFacade):
    def __init__(self, pages: list[PageSummary], observed_page_id: str, text: str) -> None:
        super().__init__(pages)
        self._observed_page_id = observed_page_id
        self._text = text

    def list_text_observations(self, page_id=None, element_id=None, recognition_run_id=None, statuses=None, write_back=False):
        if page_id == self._observed_page_id:
            return (
                type(
                    "O",
                    (),
                    {
                        "raw_text": self._text,
                        "normalized_text": self._text,
                        "target_element_id": "element:o",
                    },
                )(),
            )
        raise ToolModelError("NOT_FOUND", "no observations")


def _page(index: int) -> PageSummary:
    return PageSummary(
        drawing_set_id="set:1",
        page_id=f"page:{index}",
        file_stem=f"road_{index}",
    )


class PageContentSearchServiceTests(unittest.TestCase):
    def test_search_matches_observed_text(self) -> None:
        pages = [_page(1), _page(2)]
        facade = _ObservingFacade(pages, observed_page_id="page:2", text="排水管道")
        service = PageContentSearchService(facade, page_batch_size=1)
        result = service.search("set:1", "排水")
        self.assertEqual([match.page_id for match in result.matches], ["page:2"])
        self.assertEqual(result.coverage.total_pages, 2)
        self.assertEqual(result.coverage.scanned, 2)

    def test_search_no_match_returns_empty_matches(self) -> None:
        facade = _FakeFacade([_page(1)])
        service = PageContentSearchService(facade)
        result = service.search("set:1", "挡土墙")
        self.assertEqual(result.matches, ())
        self.assertEqual(result.coverage.total_pages, 1)


if __name__ == "__main__":
    unittest.main()
