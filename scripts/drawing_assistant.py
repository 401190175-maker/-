"""Product-level read-only CLI adapter for DrawingAssistantService.

本脚本是现有 QA CLI 的同级 adapter，只负责参数解析、配置读取、driver/facade
生命周期、service 调用、输出与退出码；不承载问题路由、检索规划、识别分组、
claim/citation 构造或文本生成规则，也不提供任何 write-back 参数。
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from drawing_graph.assistant_models import (
    AssistantExecutionPolicy,
    AssistantRequest,
    AssistantScope,
    RecognitionPolicy,
)
from drawing_graph.config import ImportConfig
from drawing_graph.qa_serialization import sanitize_error_message, to_jsonable
from drawing_graph.tool_factory import create_neo4j_tool_facade


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="drawing_assistant",
        description="Read-only product assistant: natural-language question to answer.",
    )
    parser.add_argument("--question", required=True, help="自然语言问题")
    parser.add_argument("--request-id", default=None, help="稳定请求 ID")
    parser.add_argument("--project-id", default=None)
    parser.add_argument("--drawing-set-id", default=None)
    parser.add_argument("--page-id", default=None)
    parser.add_argument("--block-id", default=None)
    parser.add_argument("--element-id", default=None)
    parser.add_argument("--cross-section-id", default=None)
    parser.add_argument("--allow-recognition", action="store_true", default=False)
    parser.add_argument("--no-recognition", action="store_true", default=False)
    parser.add_argument("--text-generation", action="store_true", default=False)
    parser.add_argument("--output", choices=["json", "text"], default="json")
    return parser


def build_scope(args) -> AssistantScope | None:
    scope = AssistantScope(
        project_id=args.project_id,
        drawing_set_id=args.drawing_set_id,
        page_id=args.page_id,
        block_id=args.block_id,
        element_id=args.element_id,
        cross_section_id=args.cross_section_id,
    )
    if all(
        getattr(scope, name) is None
        for name in (
            "project_id",
            "drawing_set_id",
            "page_id",
            "block_id",
            "element_id",
            "cross_section_id",
        )
    ):
        return None
    return scope


def _allow_recognition(args) -> bool:
    return bool(args.allow_recognition) and not bool(args.no_recognition)


def build_request(args) -> AssistantRequest:
    scope = build_scope(args)
    return AssistantRequest(
        request_id=args.request_id or _new_request_id(),
        question=args.question,
        scope_hint=scope,
        allow_recognition=_allow_recognition(args),
    )


def build_policy(args) -> AssistantExecutionPolicy:
    return AssistantExecutionPolicy(
        recognition_policy=RecognitionPolicy(allow_recognition=_allow_recognition(args)),
        enable_constrained_text=bool(args.text_generation),
    )


def _new_request_id() -> str:
    return f"req:{uuid.uuid4().hex}"


def _build_driver(uri: str, auth: tuple[str, str]) -> Any:
    from neo4j import GraphDatabase

    return GraphDatabase.driver(uri, auth=auth)


def _close_driver(driver: Any) -> None:
    close = getattr(driver, "close", None)
    if close is not None:
        close()


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _print_error(code: str, error: Exception) -> None:
    print(
        json.dumps(
            {"ok": False, "error": {"code": code, "message": sanitize_error_message(str(error))}},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        file=sys.stderr,
    )


def _success_payload(package: Any) -> dict[str, Any]:
    return {
        "answer_contract_version": package.answer_contract_version,
        "request_id": package.request_id,
        "status": package.status,
        "machine_answer": to_jsonable(package.machine_answer),
        "text_answer": package.text_answer,
    }


def _print_success(package: Any) -> None:
    _print_json({"ok": True, "data": _success_payload(package)})


def _error_code(reason_code: Any) -> str:
    return getattr(reason_code, "value", str(reason_code))


def main(
    argv: list[str] | None = None,
    *,
    config_loader: Callable[[], Any] = ImportConfig.from_env,
    driver_factory: Callable[[str, tuple[str, str]], Any] = _build_driver,
    facade_factory: Callable[[Any], Any] = create_neo4j_tool_facade,
    service_factory: Callable[[Any], Any] = None,
) -> int:
    """解析参数、管理 driver/facade 生命周期并只调用 DrawingAssistantService.answer。"""

    if service_factory is None:
        from drawing_graph.drawing_assistant_factory import create_drawing_assistant_service
        from drawing_graph.question_understanding_client import (
            question_understanding_client_from_env,
        )

        def _assistant_service_factory(facade):
            return create_drawing_assistant_service(
                facade,
                question_understanding_client=question_understanding_client_from_env(),
            )

        service_factory = _assistant_service_factory

    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code) if isinstance(error.code, int) else 2

    try:
        config = config_loader()
    except Exception as error:  # noqa: BLE001
        _print_error("configuration_failed", error)
        return 2

    driver = None
    service = None
    try:
        driver = driver_factory(config.neo4j_uri, (config.neo4j_user, config.neo4j_password))
        facade = facade_factory(driver)
        service = service_factory(facade)
    except Exception as error:  # noqa: BLE001
        _print_error("initialization_failed", error)
        return 1
    finally:
        if service is None:
            _close_driver(driver)

    try:
        request = build_request(args)
        policy = build_policy(args)
        package = service.answer(request, policy)
    except Exception as error:  # noqa: BLE001
        return _map_call_error(error)
    finally:
        _close_driver(driver)

    if args.output == "text":
        print(package.text_answer or "")
    else:
        _print_success(package)
    return 0


def _map_call_error(error: Exception) -> int:
    from drawing_graph.assistant_answer_generation import AnswerValidationError
    from drawing_graph.drawing_assistant_service import (
        AssistantExecutionError,
        ReadOnlyViolationError,
    )

    if isinstance(error, ReadOnlyViolationError):
        _print_error("read_only_violation", error)
        return 2
    if isinstance(error, AnswerValidationError):
        _print_error("answer_validation_failed", error)
        return 2
    if isinstance(error, AssistantExecutionError):
        _print_error(_error_code(error.reason_code), error)
        return 1
    _print_error("assistant_call_failed", error)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
