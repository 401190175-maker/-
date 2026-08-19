"""Framework-independent JSON serialization shared by product adapters.

本模块是产品 adapter 的共享序列化与错误映射层：只把 ``AnswerPackage``
转换为 JSON-safe 的稳定 envelope，并统一稳定错误类别与脱敏规则。它只依赖
Python 标准库、产品公共合同 DTO（``assistant_models``）与旧 QA 序列化工具
（``qa_serialization.to_jsonable``/``sanitize_error_message``），不依赖
FastAPI、Pydantic、Uvicorn、MCP SDK、Neo4j driver、repository 或
Qwen/DashScope provider，也不读取环境变量或调用 service/facade。

产品 adapter 的成功/失败 envelope 与旧 QA envelope 命名保持独立，避免把
``AnswerPackage`` 与 ``QAAnswer`` 混成一个输出合同。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Mapping

from .qa_serialization import sanitize_error_message, to_jsonable


ASSISTANT_HTTP_CONTRACT_VERSION = "drawing-assistant-http-v1"
ASSISTANT_MCP_CONTRACT_VERSION = "drawing-assistant-mcp-v1"


class AssistantErrorCode(str, Enum):
    """产品 adapter 的稳定错误类别，不透出底层异常类或 traceback。"""

    INVALID_ARGUMENT = "invalid_argument"
    READ_ONLY_VIOLATION = "read_only_violation"
    CONFIGURATION_FAILED = "configuration_failed"
    INITIALIZATION_FAILED = "initialization_failed"
    ASSISTANT_CALL_FAILED = "assistant_call_failed"
    TIMEOUT = "timeout"
    CONCURRENCY_LIMIT_REACHED = "concurrency_limit_reached"
    REQUEST_TOO_LARGE = "request_too_large"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    INTERNAL_ERROR = "internal_error"


class AssistantAdapterError(Exception):
    """产品 adapter 自身的稳定错误：固定 code 与 retryable，不携带底层对象。"""

    def __init__(self, code: str | AssistantErrorCode, message: str, retryable: bool = False):
        self.code = code.value if isinstance(code, AssistantErrorCode) else code
        self.retryable = bool(retryable)
        super().__init__(message)


def answer_package_to_data(package: Any) -> dict[str, Any]:
    """Project an ``AnswerPackage`` into a JSON-safe success ``data`` payload.

    只序列化稳定合同字段；不重新分类候选/正式、不补查 payload、不把 traceback
    或凭据带入输出。``machine_answer`` 通过 ``to_jsonable`` 递归投影，保证与
    CLI/HTTP/MCP 三入口同源一致。
    """

    machine_answer = to_jsonable(getattr(package, "machine_answer", None))
    return {
        "answer_contract_version": getattr(package, "answer_contract_version", None),
        "request_id": package.request_id,
        "status": package.status,
        "machine_answer": machine_answer,
        "text_answer": getattr(package, "text_answer", None),
        "claims": to_jsonable(getattr(package, "claims", ())),
        "citations": to_jsonable(getattr(package, "citations", ())),
        "warnings": to_jsonable(getattr(package, "warnings", ())),
        "unsupported_parts": to_jsonable(getattr(package, "unsupported_parts", ())),
        "recognition_run_ids": to_jsonable(getattr(package, "recognition_run_ids", ())),
    }


def build_success_envelope(data: Any, meta: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build a stable product success envelope with ``ok=True`` and ``data``."""

    envelope: dict[str, Any] = {"ok": True, "data": data}
    if meta is not None:
        envelope["meta"] = meta
    return envelope


def build_error_envelope(
    code: str | AssistantErrorCode,
    message: str,
    retryable: bool,
    meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a stable product failure envelope with ``ok=False`` and structured error."""

    code_value = code.value if isinstance(code, AssistantErrorCode) else code
    error: dict[str, Any] = {
        "code": code_value,
        "message": sanitize_error_message(message) or "internal error",
        "retryable": bool(retryable),
    }
    envelope: dict[str, Any] = {"ok": False, "error": error}
    if meta is not None:
        envelope["meta"] = meta
    return envelope


def map_exception_to_error(error: BaseException) -> tuple[str, bool]:
    """Map a raised exception to a stable ``(code, retryable)`` tuple.

    ``AssistantAdapterError`` 直接透传其固定 code/retryable；领域只读违规与
    编排失败映射到稳定类别；参数校验失败映射为 ``invalid_argument``；其余
    未分类异常统一映射为 ``internal_error``。
    """

    from .assistant_answer_generation import AnswerValidationError
    from .drawing_assistant_service import AssistantExecutionError, ReadOnlyViolationError

    if isinstance(error, AssistantAdapterError):
        return error.code, error.retryable
    if isinstance(error, ReadOnlyViolationError):
        return AssistantErrorCode.READ_ONLY_VIOLATION.value, False
    if isinstance(error, AnswerValidationError):
        return AssistantErrorCode.ASSISTANT_CALL_FAILED.value, False
    if isinstance(error, AssistantExecutionError):
        return AssistantErrorCode.ASSISTANT_CALL_FAILED.value, False
    if isinstance(error, ValueError):
        return AssistantErrorCode.INVALID_ARGUMENT.value, False
    return AssistantErrorCode.INTERNAL_ERROR.value, False


__all__ = (
    "ASSISTANT_HTTP_CONTRACT_VERSION",
    "ASSISTANT_MCP_CONTRACT_VERSION",
    "AssistantAdapterError",
    "AssistantErrorCode",
    "answer_package_to_data",
    "build_error_envelope",
    "build_success_envelope",
    "map_exception_to_error",
    "sanitize_error_message",
    "to_jsonable",
)
