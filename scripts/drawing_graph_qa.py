"""Thin QA CLI adapter for DrawingGraphQAService."""

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
from drawing_graph.qa_models import QAError, QARequest, QAScope, QuestionType
from drawing_graph.qa_rendering import render_qa_answer_zh_brief
from drawing_graph.qa_service import DrawingGraphQAService
from drawing_graph.tool_factory import create_neo4j_tool_facade


def main(
    argv: list[str] | None = None,
    *,
    config_loader: Callable[[], ImportConfig] = ImportConfig.from_env,
    driver_factory: Callable[[str, tuple[str, str]], Any] | None = None,
    facade_factory: Callable[[Any], Any] = create_neo4j_tool_facade,
    service_factory: Callable[[Any], Any] = DrawingGraphQAService,
) -> int:
    """Parse one QA command, build the facade, and print the structured answer."""

    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code) if isinstance(error.code, int) else 2

    driver = None
    service = None
    try:
        config = config_loader()
        driver = (driver_factory or _build_driver)(
            config.neo4j_uri,
            (config.neo4j_user, config.neo4j_password),
        )
        facade = facade_factory(driver)
        service = service_factory(facade)
    except Exception as error:
        _print_error("configuration_failed" if driver is None else "initialization_failed", error)
        return 2
    finally:
        if service is None:
            _close_driver(driver)

    try:
        request = _build_request(args)
        answer = service.ask(request)
    except QAError as error:
        _print_error(error.category.value, str(error))
        return 1
    except Exception as error:
        _print_error("qa_call_failed", error)
        return 1
    finally:
        _close_driver(driver)

    if args.format == "zh-brief":
        print(render_qa_answer_zh_brief(answer))
    else:
        _print_json({"status": "ok", "data": _jsonable(answer)})
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Answer drawing-graph QA questions through DrawingGraphQAService."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    page = subparsers.add_parser("ask-page", help="Summarize one drawing page.")
    page.add_argument("--page-id")

    block = subparsers.add_parser("ask-block", help="Summarize relations for one DrawingBlock.")
    block.add_argument("--block-id")

    candidates = subparsers.add_parser("ask-candidates", help="List candidate relations.")
    candidates.add_argument("--page-id")
    candidates.add_argument("--block-id")

    section = subparsers.add_parser("ask-section", help="Query or dry-run section caption matches.")
    section.add_argument("--cross-section-id")
    section.add_argument("--page-id")

    table_caption = subparsers.add_parser(
        "ask-table-caption",
        help="Report table caption source elements and capability gaps.",
    )
    table_caption.add_argument("--page-id")
    table_caption.add_argument("--table-id")
    table_caption.add_argument("--table-caption-id")

    diagnose = subparsers.add_parser("diagnose", help="Report read-only diagnostic status.")
    diagnose.add_argument("--page-id")
    diagnose.add_argument("--block-id")

    for subparser in (page, block, candidates, section, table_caption, diagnose):
        subparser.add_argument(
            "--format",
            choices=("json", "zh-brief"),
            default="json",
            help="output format (default: json)",
        )
    return parser


def _build_request(args: argparse.Namespace) -> QARequest:
    format_hint = args.format
    if args.command == "ask-page":
        return QARequest(
            question_type=QuestionType.PAGE_SUMMARY,
            scope=QAScope(page_id=args.page_id),
            format_hint=format_hint,
        )
    if args.command == "ask-block":
        return QARequest(
            question_type=QuestionType.BLOCK_RELATIONS,
            scope=QAScope(block_id=args.block_id),
            format_hint=format_hint,
        )
    if args.command == "ask-candidates":
        return QARequest(
            question_type=QuestionType.CANDIDATE_RELATIONS,
            scope=QAScope(page_id=args.page_id, block_id=args.block_id),
            format_hint=format_hint,
        )
    if args.command == "ask-section":
        return QARequest(
            question_type=QuestionType.SECTION_MATCHES,
            scope=QAScope(cross_section_id=args.cross_section_id, page_id=args.page_id),
            format_hint=format_hint,
        )
    if args.command == "ask-table-caption":
        return QARequest(
            question_type=QuestionType.TABLE_CAPTION_STATUS,
            scope=QAScope(
                page_id=args.page_id,
                table_id=args.table_id,
                table_caption_id=args.table_caption_id,
            ),
            format_hint=format_hint,
        )
    if args.command == "diagnose":
        return QARequest(
            question_type=QuestionType.DIAGNOSTIC_STATUS,
            scope=QAScope(page_id=args.page_id, block_id=args.block_id),
            format_hint=format_hint,
        )
    raise ValueError(f"unsupported QA command: {args.command}")


def _build_driver(uri: str, auth: tuple[str, str]) -> Any:
    from neo4j import GraphDatabase

    return GraphDatabase.driver(uri, auth=auth)


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
    if any(token in lowered for token in ("password", "secret", "token", "cypher", "driver")):
        return "sensitive or low-level backend detail is unavailable"
    return message


if __name__ == "__main__":
    raise SystemExit(main())
