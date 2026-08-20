"""Thin command-line adapter for stable drawing graph facade calls."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from drawing_graph.config import ImportConfig
from drawing_graph.tool_factory import create_neo4j_tool_facade
from drawing_graph.tool_models import ToolModelError


def main(
    argv: list[str] | None = None,
    *,
    config_loader: Callable[[], ImportConfig] = ImportConfig.from_env,
    driver_factory: Callable[[str, tuple[str, str]], Any] | None = None,
    facade_factory: Callable[[Any], Any] = create_neo4j_tool_facade,
) -> int:
    """Parse one tool call, build the facade, and print JSON output."""

    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code) if isinstance(error.code, int) else 2

    driver = None
    try:
        config = config_loader()
        driver = (driver_factory or _build_driver)(
            config.neo4j_uri,
            (config.neo4j_user, config.neo4j_password),
        )
        facade = facade_factory(driver)
        result = _run_selected_command(facade, args)
    except ToolModelError as error:
        _print_error(error.category, error)
        return 1
    except Exception as error:
        _print_error("configuration_failed" if driver is None else "tool_call_failed", error)
        return 2 if driver is None else 1
    finally:
        _close_driver(driver)

    _print_json({"status": "ok", "data": _jsonable(result)})
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Call DrawingGraphToolFacade through a Neo4j-backed command-line adapter."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    drawing_sets = subparsers.add_parser("list-drawing-sets", help="List drawing sets for one project.")
    drawing_sets.add_argument("--project-id", required=True)
    drawing_sets.add_argument("--limit", type=int, default=100)

    pages = subparsers.add_parser("list-pages", help="List pages for one drawing set.")
    pages.add_argument("--drawing-set-id", required=True)
    pages.add_argument("--limit", type=int, default=100)
    pages.add_argument("--offset", type=int, default=0)

    source_facts = subparsers.add_parser("page-source-facts", help="Return page source facts.")
    source_facts.add_argument("--page-id", required=True)
    source_facts.add_argument("--element-type", action="append", dest="element_types")
    source_facts.add_argument("--no-image-meta", action="store_true")

    block_trace = subparsers.add_parser("block-trace", help="Return trace evidence for one DrawingBlock.")
    block_trace.add_argument("--block-id", required=True)

    block_relations = subparsers.add_parser("block-relations", help="Return relations for one DrawingBlock.")
    block_relations.add_argument("--block-id", required=True)

    recognition = subparsers.add_parser(
        "recognize-page-semantics",
        help="Run controlled single-page semantic recognition through the facade.",
    )
    recognition.add_argument("--page-id", required=True)
    recognition.add_argument("--target-type", action="append", dest="target_types")
    recognition.add_argument("--model-profile", default="default")
    recognition.add_argument("--prompt-version", default="default")
    recognition.add_argument("--write-back", action="store_true")

    observations = subparsers.add_parser("list-text-observations", help="Query persisted TextObservation evidence.")
    _add_semantic_filters(observations)
    observations.add_argument("--status", action="append", dest="statuses")

    interpretations = subparsers.add_parser("list-interpretations", help="Query persisted semantic interpretations.")
    _add_semantic_filters(interpretations)
    interpretations.add_argument("--status", action="append", dest="statuses")

    candidate_relations = subparsers.add_parser(
        "list-candidate-relations",
        help="Query persisted block-level candidate relations.",
    )
    candidate_relations.add_argument("--page-id")
    candidate_relations.add_argument("--block-id")
    candidate_relations.add_argument("--relation-type")
    candidate_relations.add_argument("--status")

    section_matches = subparsers.add_parser(
        "list-section-matches",
        help="Query persisted section-caption candidate and formal matches.",
    )
    section_matches.add_argument("--cross-section-id")
    section_matches.add_argument("--page-id")
    section_matches.add_argument("--status", action="append", dest="statuses")

    search_pages = subparsers.add_parser(
        "search-pages",
        help="Search page content across one drawing set (read-only).",
    )
    search_pages.add_argument("--drawing-set-id", required=True)
    search_pages.add_argument("--query", required=True)
    search_pages.add_argument("--allow-recognition", action="store_true")
    search_pages.add_argument("--recognize-page-limit", type=int, default=10)
    search_pages.add_argument(
        "--write-back",
        action="store_true",
        help="Explicitly authorize persisting recognition cache.",
    )
    search_pages.add_argument("--semantic-threshold", type=float, default=0.25)
    search_pages.add_argument("--semantic-top-k", type=int, default=20)
    search_pages.add_argument("--embed-page-limit", type=int, default=20)

    return parser


def _add_semantic_filters(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--page-id")
    group.add_argument("--element-id")
    group.add_argument("--recognition-run-id")


def _build_driver(uri: str, auth: tuple[str, str]) -> Any:
    from neo4j import GraphDatabase

    return GraphDatabase.driver(uri, auth=auth)


def _run_selected_command(facade: Any, args: argparse.Namespace) -> Any:
    if args.command == "list-drawing-sets":
        return facade.list_drawing_sets(args.project_id, limit=args.limit)
    if args.command == "list-pages":
        return facade.list_pages(args.drawing_set_id, limit=args.limit, offset=args.offset)
    if args.command == "page-source-facts":
        element_types = tuple(args.element_types) if args.element_types else None
        return facade.get_page_source_facts(
            args.page_id,
            element_types=element_types,
            include_image_meta=not args.no_image_meta,
        )
    if args.command == "block-trace":
        return facade.get_block_trace(args.block_id)
    if args.command == "block-relations":
        return facade.get_block_relations(args.block_id)
    if args.command == "recognize-page-semantics":
        # Recognition is intentionally routed through the facade so dry-run and
        # write-back boundaries stay in one application-level place.
        return facade.recognize_page_semantics(
            args.page_id,
            target_types=tuple(args.target_types) if args.target_types else (),
            model_profile=args.model_profile,
            prompt_version=args.prompt_version,
            write_back=args.write_back,
        )
    if args.command == "list-text-observations":
        return facade.list_text_observations(
            page_id=args.page_id,
            element_id=args.element_id,
            recognition_run_id=args.recognition_run_id,
            statuses=tuple(args.statuses) if args.statuses else None,
        )
    if args.command == "list-interpretations":
        return facade.list_interpretations(
            page_id=args.page_id,
            element_id=args.element_id,
            recognition_run_id=args.recognition_run_id,
            statuses=tuple(args.statuses) if args.statuses else None,
        )
    if args.command == "list-candidate-relations":
        return facade.list_candidate_relations(
            page_id=args.page_id,
            block_id=args.block_id,
            relation_type=args.relation_type,
            status=args.status,
        )
    if args.command == "list-section-matches":
        return facade.list_section_matches(
            cross_section_id=args.cross_section_id,
            page_id=args.page_id,
            statuses=tuple(args.statuses) if args.statuses else None,
        )
    if args.command == "search-pages":
        from drawing_graph.hybrid_search_scorer import HybridScorer
        from drawing_graph.page_embedding_store import PageEmbeddingStore
        from drawing_graph.page_search_service import PageContentSearchService
        from drawing_graph.text_embedding_client import text_embedding_client_from_env

        embedding_client = text_embedding_client_from_env()
        embedding_store = None
        if embedding_client is not None:
            cache_dir = PROJECT_ROOT / ".search_cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            embedding_store = PageEmbeddingStore(cache_dir / "page_embeddings.sqlite")
        service = PageContentSearchService(
            facade,
            embedding_client=embedding_client,
            embedding_store=embedding_store,
            hybrid_scorer=HybridScorer(),
            semantic_threshold=args.semantic_threshold,
            semantic_top_k=args.semantic_top_k,
            embed_page_limit=args.embed_page_limit,
        )
        return service.search(
            args.drawing_set_id,
            args.query,
            allow_recognition=args.allow_recognition,
            recognize_page_limit=args.recognize_page_limit,
            write_back=args.write_back,
        )
    raise ValueError(f"unsupported tool command: {args.command}")


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {field.name: _jsonable(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, MappingProxyType):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    return value


def _close_driver(driver: Any) -> None:
    close = getattr(driver, "close", None)
    if close is not None:
        close()


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _print_error(category: str, error: Exception) -> None:
    print(
        json.dumps(
            {
                "status": "failed",
                "category": category,
                "message": _sanitize_message(str(error)),
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        file=sys.stderr,
    )


def _sanitize_message(message: str) -> str:
    lowered = message.lower()
    if any(token in lowered for token in ("password", "secret", "cypher")):
        return "sensitive or low-level backend detail is unavailable"
    return message


if __name__ == "__main__":
    raise SystemExit(main())
