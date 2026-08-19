"""Product trace DTO contracts (07 traceability loop).

本模块定义产品级追溯数据合同：模块事件、成本/时延摘要、富版
``TraceRecord``、trace 写入结果、claim 追溯投影与 trace 查询结果。

模块只依赖 ``assistant_models`` 这一公共合同，不依赖数据库驱动、
仓储、查询语句、HTTP 框架、MCP SDK 或模型客户端；也不保存 secret、
图数据库 URI、查询语言、绝对路径、完整 payload、完整 prompt 或 traceback。

富版 ``TraceRecord`` 是 ``assistant_models.TraceRecord`` 薄版字段的
超集，保持字段兼容；薄版仍保留在 ``assistant_models`` 中。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from .assistant_models import (
    AssistantScope,
    FactKind,
    SemanticGapDecision,
    SourceCallRecord,
)


class TraceWriteStatus(str, Enum):
    """trace 写入的稳定状态。"""

    RECORDED = "recorded"
    DUPLICATE = "duplicate"
    UNAVAILABLE = "unavailable"


def _require_text(value: str | None, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _require_optional_text(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be None or a non-empty string")
    return value


def _require_text_tuple(values: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(values, tuple) or not all(
        isinstance(item, str) and item.strip() for item in values
    ):
        raise ValueError(f"{field_name} must be a tuple of non-empty strings")
    return values


def _coerce_enum(enum_type: type[Enum], value: object, field_name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        try:
            return enum_type(value)
        except ValueError as exc:
            raise ValueError(f"{field_name} is not a valid {enum_type.__name__}") from exc
    raise ValueError(f"{field_name} must be a {enum_type.__name__} or its stable string")


@dataclass(frozen=True)
class TraceModuleEvent:
    """一个模块阶段的轻量追溯事件，只承载稳定数据，不携带敏感字段。"""

    event_id: str
    module: str
    status: str
    detail: str | None = None
    reason_codes: tuple[object, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _require_text(self.event_id, "event_id")
        _require_text(self.module, "module")
        _require_text(self.status, "status")
        _require_optional_text(self.detail, "detail")
        if not isinstance(self.reason_codes, tuple):
            raise ValueError("reason_codes must be a tuple")


@dataclass(frozen=True)
class TraceCostSummary:
    """识别成本估算摘要，不代表真实账单。"""

    estimated_cost: float | None = None
    currency: str | None = None
    selected_target_count: int = 0
    deferred_target_count: int = 0
    estimator_version: str = "semantic-gap-estimator-v1"

    def __post_init__(self) -> None:
        if self.estimated_cost is not None and (
            not isinstance(self.estimated_cost, (int, float))
            or isinstance(self.estimated_cost, bool)
            or self.estimated_cost < 0
        ):
            raise ValueError("estimated_cost must be a non-negative number or None")
        _require_optional_text(self.currency, "currency")
        for field_name in ("selected_target_count", "deferred_target_count"):
            if (
                not isinstance(getattr(self, field_name), int)
                or isinstance(getattr(self, field_name), bool)
                or getattr(self, field_name) < 0
            ):
                raise ValueError(f"{field_name} must be a non-negative integer")
        _require_text(self.estimator_version, "estimator_version")


@dataclass(frozen=True)
class TraceLatencySummary:
    """识别时延估算摘要。"""

    estimated_latency_ms: float | None = None

    def __post_init__(self) -> None:
        if self.estimated_latency_ms is not None and (
            not isinstance(self.estimated_latency_ms, (int, float))
            or isinstance(self.estimated_latency_ms, bool)
            or self.estimated_latency_ms < 0
        ):
            raise ValueError("estimated_latency_ms must be a non-negative number or None")


@dataclass(frozen=True)
class TraceRecord:
    """产品级追溯记录，薄版 ``assistant_models.TraceRecord`` 的超集。

    只承载稳定业务 ID 与摘要，不承载 secret、URI、Cypher、绝对路径、
    完整 payload、完整 prompt 或 traceback。
    """

    request_id: str
    question: str | None = None
    question_type: str | None = None
    scope: AssistantScope | None = None
    module_events: tuple[TraceModuleEvent, ...] = field(default_factory=tuple)
    retrieval_calls: tuple[SourceCallRecord, ...] = field(default_factory=tuple)
    semantic_gap_decision: SemanticGapDecision | None = None
    recognition_run_ids: tuple[str, ...] = field(default_factory=tuple)
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    claim_ids: tuple[str, ...] = field(default_factory=tuple)
    answer_status: str | None = None
    model_profiles: tuple[str, ...] = field(default_factory=tuple)
    prompt_versions: tuple[str, ...] = field(default_factory=tuple)
    cache_status: str | None = None
    cost_summary: TraceCostSummary | None = None
    latency_summary: TraceLatencySummary | None = None
    created_at: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.request_id, "request_id")
        _require_optional_text(self.question, "question")
        _require_optional_text(self.question_type, "question_type")
        if self.scope is not None and not isinstance(self.scope, AssistantScope):
            raise ValueError("scope must be an AssistantScope or None")
        for event in self.module_events:
            if not isinstance(event, TraceModuleEvent):
                raise ValueError("module_events must contain only TraceModuleEvent instances")
        for call in self.retrieval_calls:
            if not isinstance(call, SourceCallRecord):
                raise ValueError("retrieval_calls must contain only SourceCallRecord instances")
        if self.semantic_gap_decision is not None and not isinstance(
            self.semantic_gap_decision, SemanticGapDecision
        ):
            raise ValueError("semantic_gap_decision must be a SemanticGapDecision or None")
        for field_name in (
            "recognition_run_ids",
            "evidence_ids",
            "claim_ids",
            "model_profiles",
            "prompt_versions",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_text_tuple(getattr(self, field_name), field_name),
            )
        _require_optional_text(self.answer_status, "answer_status")
        _require_optional_text(self.cache_status, "cache_status")
        if self.cost_summary is not None and not isinstance(self.cost_summary, TraceCostSummary):
            raise ValueError("cost_summary must be a TraceCostSummary or None")
        if self.latency_summary is not None and not isinstance(self.latency_summary, TraceLatencySummary):
            raise ValueError("latency_summary must be a TraceLatencySummary or None")
        _require_optional_text(self.created_at, "created_at")


@dataclass(frozen=True)
class TraceWriteResult:
    """trace 写入结果，重复 request_id 或 store 不可用时状态不静默。"""

    request_id: str
    status: TraceWriteStatus | str = TraceWriteStatus.RECORDED
    warning: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.request_id, "request_id")
        object.__setattr__(self, "status", _coerce_enum(TraceWriteStatus, self.status, "status"))
        _require_optional_text(self.warning, "warning")


def _require_bboxes(values: object, field_name: str) -> tuple[Mapping[str, float], ...]:
    if not isinstance(values, tuple):
        raise ValueError(f"{field_name} must be a tuple")
    result: list[Mapping[str, float]] = []
    for bbox in values:
        if not isinstance(bbox, Mapping):
            raise ValueError(f"{field_name} entries must be mappings")
        for key, item in bbox.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError(f"{field_name} keys must be non-empty strings")
            if not isinstance(item, (int, float)) or isinstance(item, bool):
                raise ValueError(f"{field_name} values must be numeric")
        result.append(MappingProxyType(dict(bbox)))
    return tuple(result)


@dataclass(frozen=True)
class ClaimTrace:
    """claim_id 到 evidence/citation/run/payload/candidate/review 的追溯投影。

    candidate 关系仍标记为 candidate，不使用数据库内部 ID。``candidates``
    承载候选审核所需的稳定候选映射，缺省为空表示候选集合不完整。
    """

    claim_id: str
    request_id: str
    claim_status: str | None = None
    statement: str = ""
    fact_kinds: tuple[FactKind | str, ...] = field(default_factory=tuple)
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    citation_ids: tuple[str, ...] = field(default_factory=tuple)
    page_ids: tuple[str, ...] = field(default_factory=tuple)
    block_ids: tuple[str, ...] = field(default_factory=tuple)
    element_ids: tuple[str, ...] = field(default_factory=tuple)
    bboxes: tuple[Mapping[str, float], ...] = field(default_factory=tuple)
    recognition_run_ids: tuple[str, ...] = field(default_factory=tuple)
    candidate_group_ids: tuple[str, ...] = field(default_factory=tuple)
    review_run_ids: tuple[str, ...] = field(default_factory=tuple)
    payload_refs: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    relation_spec: str | None = None
    rule_version: str | None = None
    candidates: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _require_text(self.claim_id, "claim_id")
        _require_text(self.request_id, "request_id")
        _require_optional_text(self.claim_status, "claim_status")
        if not isinstance(self.statement, str):
            raise ValueError("statement must be a string")
        object.__setattr__(
            self,
            "fact_kinds",
            tuple(_coerce_enum(FactKind, item, "fact_kinds") for item in self.fact_kinds),
        )
        for field_name in (
            "evidence_ids",
            "citation_ids",
            "page_ids",
            "block_ids",
            "element_ids",
            "recognition_run_ids",
            "candidate_group_ids",
            "review_run_ids",
            "payload_refs",
            "warnings",
            "evidence_refs",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_text_tuple(getattr(self, field_name), field_name),
            )
        object.__setattr__(self, "bboxes", _require_bboxes(self.bboxes, "bboxes"))
        _require_optional_text(self.relation_spec, "relation_spec")
        _require_optional_text(self.rule_version, "rule_version")
        if not isinstance(self.candidates, tuple):
            raise ValueError("candidates must be a tuple")
        for candidate in self.candidates:
            if not isinstance(candidate, Mapping):
                raise ValueError("candidates entries must be mappings")
        object.__setattr__(
            self,
            "candidates",
            tuple(MappingProxyType(dict(candidate)) for candidate in self.candidates),
        )


@dataclass(frozen=True)
class TraceQueryResult:
    """按 request_id 回查 trace 的只读查询结果。"""

    request_id: str
    found: bool = False
    record: TraceRecord | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _require_text(self.request_id, "request_id")
        if not isinstance(self.found, bool):
            raise ValueError("found must be a boolean")
        if self.record is not None and not isinstance(self.record, TraceRecord):
            raise ValueError("record must be a TraceRecord or None")
        object.__setattr__(
            self,
            "warnings",
            _require_text_tuple(self.warnings, "warnings"),
        )


__all__ = (
    "ClaimTrace",
    "TraceCostSummary",
    "TraceLatencySummary",
    "TraceModuleEvent",
    "TraceQueryResult",
    "TraceRecord",
    "TraceWriteResult",
    "TraceWriteStatus",
)
