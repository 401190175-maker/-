"""Offline CLI for enriching derived drawing relationships."""

from __future__ import annotations

import argparse
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from drawing_graph.config import ImportConfig
from drawing_graph.identifiers import make_project_id
from drawing_graph.relation_repository import RelationRepository
from drawing_graph.relation_service import EnrichmentScope, RelationEnrichmentService


SUCCESS_STATUSES = {"success"}


def main(
    argv: list[str] | None = None,
    *,
    config_loader: Callable[[], Any] = ImportConfig.from_env,
    repository_factory: Callable[[Any], Any] | None = None,
    service_factory: Callable[[Any], Any] = RelationEnrichmentService,
    batch_id_factory: Callable[[], str] | None = None,
) -> int:
    """Parse CLI arguments, load configuration, and dispatch one enrichment scope."""

    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code)

    try:
        config = config_loader()
    except Exception as error:  # pragma: no cover - exact config failures depend on environment
        _print_error("config_error", error)
        return 2

    try:
        repository = (
            repository_factory(config) if repository_factory is not None else _build_repository(config)
        )
        service = service_factory(repository)
        scope = _build_scope(args, config, batch_id_factory or _new_relation_batch_id)
        _run_selected_mode(service, args.mode, scope)
        summary = service.get_batch_summary(scope.relation_batch_id)
    except Exception as error:
        _print_error("relation_enrichment_failed", error)
        return 1

    print(_summary_for_output(summary))
    return 0 if _summary_status(summary) in SUCCESS_STATUSES else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Enrich inferred derived relationships for an already imported graph; "
            "does not automatically run AI candidate review."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    project_parser = subparsers.add_parser("project", help="Enrich all pages in the configured project.")
    _add_required_rule_version(project_parser)

    drawing_set_parser = subparsers.add_parser(
        "drawing-set",
        help="Enrich all pages in one drawing set.",
    )
    drawing_set_parser.add_argument("drawing_set_id", help="Stable DrawingSet ID, for example set:project:set-a.")
    _add_required_rule_version(drawing_set_parser)

    page_parser = subparsers.add_parser("page", help="Enrich one drawing page.")
    page_parser.add_argument("page_id", help="Stable DrawingPage ID, for example page:project:set-a:road_1.")
    _add_required_rule_version(page_parser)

    return parser


def _add_required_rule_version(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--rule-version", required=True, help="Version string for the relation rules used.")


def _build_repository(config: Any) -> RelationRepository:
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(config.neo4j_uri, auth=(config.neo4j_user, config.neo4j_password))
    return RelationRepository(driver)


def _build_scope(
    args: argparse.Namespace,
    config: Any,
    batch_id_factory: Callable[[], str],
) -> EnrichmentScope:
    project_slug = config.project_slug
    project_id = project_slug if str(project_slug).startswith("project:") else make_project_id(project_slug)
    return EnrichmentScope(
        project_id=project_id,
        relation_batch_id=batch_id_factory(),
        rule_version=args.rule_version,
        drawing_set_id=getattr(args, "drawing_set_id", None),
        page_id=getattr(args, "page_id", None),
    )


def _run_selected_mode(service: Any, mode: str, scope: EnrichmentScope) -> None:
    if mode == "project":
        service.enrich_project(scope)
        return
    if mode == "drawing-set":
        service.enrich_drawing_set(scope)
        return
    if mode == "page":
        service.enrich_page(scope)
        return
    raise ValueError(f"unsupported enrichment mode: {mode}")


def _new_relation_batch_id() -> str:
    return f"relation-batch:{uuid.uuid4()}"


def _summary_status(summary: Any) -> str | None:
    if isinstance(summary, dict):
        return summary.get("status")
    return getattr(summary, "status", None)


def _summary_for_output(summary: Any) -> Any:
    if not isinstance(summary, dict):
        return summary

    output = dict(summary)
    output.setdefault("cross_section_count", 0)
    output.setdefault("table_count", 0)
    output.setdefault("table_caption_count", 0)
    output.setdefault("table_caption_relation_count", 0)
    output.setdefault("uses_basic_info_count", 0)
    output.setdefault("candidate_count", 0)
    output.setdefault("ambiguous_count", 0)
    output.setdefault("not_evaluated_count", 0)
    output.setdefault("relation_count", 0)
    output.setdefault("warning_count", 0)
    output.setdefault("error_count", 0)
    output.setdefault("issue_summary", {})
    return output


def _print_error(category: str, error: Exception) -> None:
    print(f"{category}: {_sanitize_message(str(error))}", file=sys.stderr)


def _sanitize_message(message: str) -> str:
    if "password" in message.lower():
        return "sensitive configuration value is missing or invalid"
    return message


if __name__ == "__main__":
    raise SystemExit(main())
