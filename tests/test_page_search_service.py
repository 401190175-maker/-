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


class SearchPagesCliTests(unittest.TestCase):
    def test_cli_search_pages_prints_ok(self) -> None:
        import io
        import json
        import sys

        import scripts.drawing_graph_tool as cli

        class _Config:
            neo4j_uri = "bolt://127.0.0.1:7687"
            neo4j_user = "neo4j"
            neo4j_password = "x"

        class _Driver:
            pass

        captured = io.StringIO()
        original = sys.stdout
        sys.stdout = captured
        try:
            code = cli.main(
                ["search-pages", "--drawing-set-id", "set:1", "--query", "排水"],
                config_loader=lambda: _Config(),
                driver_factory=lambda uri, auth: _Driver(),
                facade_factory=lambda driver: _ObservingFacade(
                    [_page(1)],
                    observed_page_id="page:1",
                    text="排水管道",
                ),
            )
        finally:
            sys.stdout = original
        self.assertEqual(code, 0)
        payload = json.loads(captured.getvalue())
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["data"]["matches"][0]["page_id"], "page:1")


class RecognitionBackfillTests(unittest.TestCase):
    def test_recognizes_unrecognized_page_then_matches(self) -> None:
        class _RecognitionFacade(_FakeFacade):
            def __init__(self, pages):
                super().__init__(pages)
                self.recognized: list[str] = []

            def get_page_source_facts(self, page_id, element_types=None, include_image_meta=True):
                return type("F", (), {"elements": ()})()

            def list_text_observations(self, page_id=None, element_id=None, recognition_run_id=None, statuses=None, write_back=False):
                if page_id == "page:1":
                    return (
                        type(
                            "O",
                            (),
                            {
                                "raw_text": "道路平面图",
                                "normalized_text": "道路平面图",
                                "target_element_id": "element:1",
                            },
                        )(),
                    )
                if page_id == "page:2" and "page:2" in self.recognized:
                    return (
                        type(
                            "O",
                            (),
                            {
                                "raw_text": "排水管道",
                                "normalized_text": "排水管道",
                                "target_element_id": "element:o",
                            },
                        )(),
                    )
                raise ToolModelError("NOT_FOUND", "no observations")

            def recognize_page_semantics(self, page_id, target_types, model_profile="default", prompt_version="default", write_back=False):
                self.recognized.append(page_id)
                return object()

        facade = _RecognitionFacade([_page(1), _page(2)])
        service = PageContentSearchService(facade, page_batch_size=1)
        result = service.search("set:1", "排水", allow_recognition=True, recognize_page_limit=1)
        self.assertEqual([m.page_id for m in result.matches], ["page:2"])
        self.assertEqual(facade.recognized, ["page:2"])
        self.assertEqual(result.coverage.recognized_now, 1)


class CacheWriteAuthorizationTests(unittest.TestCase):
    def test_cli_write_back_flag_forwards_to_recognition(self) -> None:
        import io
        import sys

        import scripts.drawing_graph_tool as cli

        class _Config:
            neo4j_uri = "bolt://127.0.0.1:7687"
            neo4j_user = "neo4j"
            neo4j_password = "x"

        class _Driver:
            pass

        calls: list[dict[str, object]] = []

        class _RecordingFacade(_FakeFacade):
            def get_page_source_facts(self, page_id, element_types=None, include_image_meta=True):
                return type("F", (), {"elements": ()})()

            def list_text_observations(self, page_id=None, element_id=None, recognition_run_id=None, statuses=None, write_back=False):
                raise ToolModelError("NOT_FOUND", "no observations")

            def recognize_page_semantics(self, page_id, target_types, model_profile="default", prompt_version="default", write_back=False):
                calls.append({"page_id": page_id, "write_back": write_back})
                return object()

        captured = io.StringIO()
        original = sys.stdout
        sys.stdout = captured
        try:
            code = cli.main(
                [
                    "search-pages",
                    "--drawing-set-id",
                    "set:1",
                    "--query",
                    "排水",
                    "--allow-recognition",
                    "--write-back",
                ],
                config_loader=lambda: _Config(),
                driver_factory=lambda uri, auth: _Driver(),
                facade_factory=lambda driver: _RecordingFacade([_page(1)]),
            )
        finally:
            sys.stdout = original
        self.assertEqual(code, 0)
        self.assertEqual(calls[0]["write_back"], True)


class SynonymSearchTests(unittest.TestCase):
    def test_search_hits_synonym_text(self) -> None:
        facade = _ObservingFacade(
            [_page(1)],
            observed_page_id="page:1",
            text="雨水管布置",
        )
        service = PageContentSearchService(facade)
        result = service.search("set:1", "排水")
        self.assertEqual([m.page_id for m in result.matches], ["page:1"])


class SemanticSearchTests(unittest.TestCase):
    def test_semantic_candidate_added_when_client_and_store_configured(self) -> None:
        from drawing_graph.hybrid_search_scorer import HybridScorer
        from drawing_graph.text_embedding_client import TextEmbeddingClient

        class _EmbeddingClient(TextEmbeddingClient):
            def embed(self, texts):
                return [[1.0, 0.0] for _ in texts]

        class _Store:
            def __init__(self):
                self._data: dict[tuple[object, ...], list[float]] = {}

            def has_page(self, page_id):
                return page_id == "page:2"

            def page_vectors(self, page_id):
                if page_id == "page:2":
                    return (("observation", "h", [1.0, 0.0]),)
                return ()

            def upsert(self, page_id, kind, element_id, text_hash, model_version, vector):
                self._data[(page_id, kind, element_id, text_hash)] = vector

        service = PageContentSearchService(
            _ObservingFacade(
                [_page(1), _page(2)],
                observed_page_id="page:1",
                text="道路平面图",
            ),
            embedding_client=_EmbeddingClient(),
            embedding_store=_Store(),
            hybrid_scorer=HybridScorer(),
            semantic_threshold=0.5,
            semantic_top_k=20,
        )
        result = service.search("set:1", "排水")
        self.assertEqual(result.coverage.embedded_pages, 1)
        self.assertTrue(
            any(match.page_id == "page:2" and match.semantic for match in result.matches)
        )


if __name__ == "__main__":
    unittest.main()
