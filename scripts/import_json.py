"""Command-line entry point for drawing graph imports."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from drawing_graph.config import ImportConfig
from drawing_graph.import_service import ImportService
from drawing_graph.neo4j_repository import Neo4jRepository


SUCCESS_STATUSES = frozenset({"success", "skipped"})


def main(
    argv: list[str] | None = None,
    *,
    config_loader: Callable[[], ImportConfig] = ImportConfig.from_env,
    repository_factory: Callable[[ImportConfig], Any] | None = None,
    service_factory: Callable[[ImportConfig, Any], ImportService] = ImportService,
) -> int:
    """Parse CLI arguments, create services, and run the selected import mode."""

    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code) if isinstance(error.code, int) else 2

    try:
        config = config_loader()
        repository = (repository_factory or _build_repository)(config)
    except Exception as error:
        _print_error("configuration_failed", error)
        return 2

    service = service_factory(config, repository)
    try:
        result = _run_selected_mode(service, args)
    except Exception as error:
        _print_error("import_failed", error)
        return 1

    _print_result(result)
    return 0 if getattr(result, "status", None) in SUCCESS_STATUSES else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import XAnyLabeling JSON into the drawing graph.")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    subparsers.add_parser("all", help="Import all drawing sets under DRAWING_GRAPH_DATA_ROOT.")

    drawing_set_parser = subparsers.add_parser("drawing-set", help="Import a single drawing set directory.")
    drawing_set_parser.add_argument("batch_id")
    drawing_set_parser.add_argument("drawing_set_path")

    page_parser = subparsers.add_parser("page", help="Import a single JSON page.")
    page_parser.add_argument("batch_id")
    page_parser.add_argument("json_path")

    return parser


def _build_repository(config: ImportConfig) -> Neo4jRepository:
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(
        config.neo4j_uri,
        auth=(config.neo4j_user, config.neo4j_password),
    )
    return Neo4jRepository(driver=driver, batch_size=config.batch_size)


def _run_selected_mode(service: ImportService, args: argparse.Namespace) -> Any:
    if args.mode == "all":
        return service.import_all()
    if args.mode == "drawing-set":
        return service.import_drawing_set(args.batch_id, Path(args.drawing_set_path))
    if args.mode == "page":
        return service.import_page(args.batch_id, Path(args.json_path))
    raise ValueError(f"unsupported import mode: {args.mode}")


def _print_result(result: Any) -> None:
    fields = {
        "status": getattr(result, "status", None),
        "batch_id": getattr(result, "batch_id", None),
        "drawing_set_id": getattr(result, "drawing_set_id", None),
        "page_id": getattr(result, "page_id", None),
        "total_count": getattr(result, "total_count", None),
        "success_count": getattr(result, "success_count", None),
        "skipped_count": getattr(result, "skipped_count", None),
        "failed_count": getattr(result, "failed_count", None),
        "warning_count": getattr(result, "warning_count", None),
        "errors": getattr(result, "errors", ()),
    }
    summary = {key: value for key, value in fields.items() if value is not None}
    print(summary)


def _print_error(category: str, error: Exception) -> None:
    print({"status": "failed", "category": category, "message": _sanitize_message(str(error))}, file=sys.stderr)


def _sanitize_message(message: str) -> str:
    sanitized = message
    lowered = sanitized.lower()
    if "password" in lowered:
        return "sensitive configuration value is missing or invalid"
    return sanitized


if __name__ == "__main__":
    raise SystemExit(main())
