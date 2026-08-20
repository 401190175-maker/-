"""Pagination tests for the page read path."""

from __future__ import annotations

import unittest

from drawing_graph.query_port_adapter import QueryServiceReadPortAdapter


class _FakeQueryService:
    def __init__(self, page_count: int) -> None:
        self._page_count = page_count

    def get_set_pages(
        self,
        drawing_set_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        pages = [
            {
                "id": f"page:{index}",
                "file_name": f"road_{index}.json",
                "page_number": index,
                "image_path": None,
            }
            for index in range(self._page_count)
        ]
        return pages[offset : offset + limit]


class PagePaginationTests(unittest.TestCase):
    def test_list_pages_honors_offset(self) -> None:
        adapter = QueryServiceReadPortAdapter(_FakeQueryService(page_count=5))
        pages = adapter.list_pages("set:1", limit=2, offset=3)
        self.assertEqual([page.page_id for page in pages], ["page:3", "page:4"])

    def test_list_pages_default_offset_is_zero(self) -> None:
        adapter = QueryServiceReadPortAdapter(_FakeQueryService(page_count=3))
        pages = adapter.list_pages("set:1", limit=2)
        self.assertEqual([page.page_id for page in pages], ["page:0", "page:1"])


if __name__ == "__main__":
    unittest.main()
