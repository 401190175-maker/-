"""Evidence fusion (05) public contract DTOs and stable enums.

本模块是产品实现层 05 证据融合与缓存闭环的专用合同：定义
answerability、claim capability、冲突、lineage、缓存汇总和受控写回
所需的稳定枚举与不可变 DTO，并包装 01–04 已有的 ``EvidenceItem``。

模块只依赖 ``assistant_models`` 这一公共合同，不依赖数据库驱动、
仓储、查询语句、模型客户端或 adapter。
``SemanticRecognitionResult`` 等 04/语义类型仅在类型标注中使用，
通过 ``TYPE_CHECKING`` 引用，运行时不被导入。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping

from .assistant_models import (
    CONTRACT_VERSION,
    AssistantRequest,
    AssistantScope,
    CacheDisposition,
    EvidenceItem,
    EvidenceRef,
    FactKind,
    FreshnessResult,
    QuestionUnderstandingResult,
    ReasonCode,
    RetrievalBundle,
    SemanticGapDecision,
)

if TYPE_CHECKING:
    from .recognition_models import (
        RecognitionAttempt,
        RecognitionCandidateEvidence,
    )
    from .semantic_models import (
        BasicInfoInterpretation,
        BlockInterpretation,
        RecognitionRunSummary,
        TableInterpretation,
        TextObservation,
    )
    from .semantic_service import SemanticRecognitionResult

FUSION_CONTRACT_VERSION = "drawing-assistant-fusion-v1"


class Answerability(str, Enum):
    """请求/子请求的整体可回答性状态。"""

    ANSWERABLE = "answerable"
    PARTIALLY_ANSWERABLE = "partially_answerable"
    CLARIFICATION_REQUIRED = "clarification_required"
    UNSUPPORTED = "unsupported"


class ClaimCapability(str, Enum):
    """证据可支撑的命题能力，由可信 fact kind + schema field 推导。"""

    IDENTITY_AND_LOCATION = "identity_and_location"
    CONFIRMED_RELATION = "confirmed_relation"
    RULE_DERIVED_CONTEXT = "rule_derived_context"
    OBSERVED_TEXT_OR_SYMBOL = "observed_text_or_symbol"
    SEMANTIC_MEANING = "semantic_meaning"
    POSSIBLE_RELATION = "possible_relation"
    RUNTIME_OR_CACHE_STATUS = "runtime_or_cache_status"


class ClaimSupportStatus(str, Enum):
    """单个证据需求在融合后的支撑状态。"""

    SUPPORTED = "supported"
    SUPPORTED_WITH_QUALIFIER = "supported_with_qualifier"
    CONFLICTING = "conflicting"
    MISSING = "missing"
    STALE_ONLY = "stale_only"
    FORMAL_REVIEW_REQUIRED = "formal_review_required"
    UNSUPPORTED = "unsupported"


class EvidenceComparison(str, Enum):
    """两条证据在相同 comparison key 下的比较结果。"""

    CONSISTENT = "consistent"
    COMPLEMENTARY = "complementary"
    CONFLICTING = "conflicting"
    SUPERSEDED = "superseded"
    AMBIGUOUS = "ambiguous"
    NOT_COMPARABLE = "not_comparable"


class ConflictType(str, Enum):
    """确定性冲突矩阵的稳定冲突类型。"""

    HARD_CONFLICT = "hard_conflict"
    RULE_CONFLICT = "rule_conflict"
    MODEL_VS_SOURCE = "model_vs_source"
    SEMANTIC_VS_RULE = "semantic_vs_rule"
    PEER_CONFLICT = "peer_conflict"
    SUPPORT_CONFLICT = "support_conflict"
    RELATION_CONFLICT = "relation_conflict"
    FORMAL_VS_SEMANTIC = "formal_vs_semantic"
    CRITICAL_INTEGRITY_CONFLICT = "critical_integrity_conflict"
    CANDIDATE_AMBIGUITY = "candidate_ambiguity"
    DIAGNOSTIC_CONFLICT = "diagnostic_conflict"


class ConflictSeverity(str, Enum):
    """冲突严重度，用于写回门控与 answerability 阻断判断。"""

    INFO = "info"
    WARNING = "warning"
    BLOCKING = "blocking"
    CRITICAL = "critical"


class CacheClosureStatus(str, Enum):
    """请求级缓存闭环状态，与预期 CacheDisposition 相互独立。"""

    FULL_HIT = "full_hit"
    PARTIAL_HIT = "partial_hit"
    MISS = "miss"
    STALE = "stale"
    BYPASSED = "bypassed"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class WriteBackStatus(str, Enum):
    """受控写回的整体状态。"""

    NOT_REQUESTED = "not_requested"
    SKIPPED = "skipped"
    PERSISTED = "persisted"
    PARTIAL = "partial"
    FAILED = "failed"


class WriteBackItemStatus(str, Enum):
    """单条/单组持久化结果的状态。"""

    PERSISTED = "persisted"
    SKIPPED = "skipped"
    FAILED = "failed"


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


def _coerce_reason_codes(values: object, field_name: str) -> tuple[ReasonCode, ...]:
    if not isinstance(values, tuple):
        raise ValueError(f"{field_name} must be a tuple")
    return tuple(_coerce_enum(ReasonCode, code, field_name) for code in values)


@dataclass(frozen=True)
class FusionMetadata:
    """强类型融合元数据，承载规范化值、四类 key、能力、freshness 与版本。

    不包含 secret、原始 payload、绝对图片路径或 provider 原文。
    """

    normalized_value: Any = None
    comparison_key: str | None = None
    evidence_family_key: str | None = None
    content_fingerprint: str | None = None
    claim_capabilities: tuple[ClaimCapability | str, ...] = field(default_factory=tuple)
    cache_key: str | None = None
    task_type: str | None = None
    freshness_result: FreshnessResult | None = None
    normalization_rule_version: str | None = None
    is_current_for_request: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "comparison_key",
            "evidence_family_key",
            "content_fingerprint",
            "cache_key",
            "task_type",
            "normalization_rule_version",
        ):
            _require_optional_text(getattr(self, field_name), field_name)
        object.__setattr__(
            self,
            "claim_capabilities",
            tuple(
                _coerce_enum(ClaimCapability, item, "claim_capabilities")
                for item in self.claim_capabilities
            ),
        )
        if self.freshness_result is not None and not isinstance(self.freshness_result, FreshnessResult):
            raise ValueError("freshness_result must be a FreshnessResult or None")
        if not isinstance(self.is_current_for_request, bool):
            raise ValueError("is_current_for_request must be a boolean")


@dataclass(frozen=True)
class EvidenceProvenance:
    """聚合一条证据的 source call、run、attempt、payload、规则与原始 refs。"""

    source_call_id: str | None = None
    recognition_run_id: str | None = None
    attempt_ids: tuple[str, ...] = field(default_factory=tuple)
    payload_ref: str | None = None
    rule_version: str | None = None
    evidence_refs: tuple[EvidenceRef, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for field_name in (
            "source_call_id",
            "recognition_run_id",
            "payload_ref",
            "rule_version",
        ):
            _require_optional_text(getattr(self, field_name), field_name)
        object.__setattr__(
            self,
            "attempt_ids",
            _require_text_tuple(self.attempt_ids, "attempt_ids"),
        )
        for ref in self.evidence_refs:
            if not isinstance(ref, EvidenceRef):
                raise ValueError("evidence_refs must contain only EvidenceRef instances")


@dataclass(frozen=True)
class FusionEvidence:
    """包装原始 ``EvidenceItem`` 的融合证据，不修改原始值或事实等级。"""

    item: EvidenceItem
    metadata: FusionMetadata
    provenance: tuple[EvidenceProvenance, ...] = field(default_factory=tuple)
    original_evidence_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.item, EvidenceItem):
            raise ValueError("item must be an EvidenceItem")
        if not isinstance(self.metadata, FusionMetadata):
            raise ValueError("metadata must be a FusionMetadata")
        for prov in self.provenance:
            if not isinstance(prov, EvidenceProvenance):
                raise ValueError("provenance must contain only EvidenceProvenance instances")
        object.__setattr__(
            self,
            "original_evidence_ids",
            _require_text_tuple(self.original_evidence_ids, "original_evidence_ids"),
        )


@dataclass(frozen=True)
class ConflictRecord:
    """可解释、可稳定排序的冲突记录，可表达多方冲突，不要求选出 winner。

    严重度为 blocking/critical 时 ``blocks_answer`` 被规范化为 True；
    信息/warning 级冲突默认不阻断回答。记录只承载稳定 ID 与安全摘要，
    不携带 traceback、Cypher、provider 原文或完整 payload。
    """

    conflict_id: str
    comparison_key: str | None = None
    conflict_type: ConflictType | str = ConflictType.HARD_CONFLICT
    severity: ConflictSeverity | str = ConflictSeverity.WARNING
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    preferred_for_current_claim_ids: tuple[str, ...] = field(default_factory=tuple)
    blocks_answer: bool = False
    reason_codes: tuple[ReasonCode | str, ...] = field(default_factory=tuple)
    review_recommended: bool = False

    def __post_init__(self) -> None:
        _require_text(self.conflict_id, "conflict_id")
        _require_optional_text(self.comparison_key, "comparison_key")
        object.__setattr__(
            self,
            "conflict_type",
            _coerce_enum(ConflictType, self.conflict_type, "conflict_type"),
        )
        severity = _coerce_enum(ConflictSeverity, self.severity, "severity")
        object.__setattr__(self, "severity", severity)
        object.__setattr__(
            self,
            "evidence_ids",
            _require_text_tuple(self.evidence_ids, "evidence_ids"),
        )
        object.__setattr__(
            self,
            "preferred_for_current_claim_ids",
            _require_text_tuple(self.preferred_for_current_claim_ids, "preferred_for_current_claim_ids"),
        )
        if not isinstance(self.blocks_answer, bool):
            raise ValueError("blocks_answer must be a boolean")
        if severity in (ConflictSeverity.BLOCKING, ConflictSeverity.CRITICAL):
            object.__setattr__(self, "blocks_answer", True)
        object.__setattr__(
            self,
            "reason_codes",
            _coerce_reason_codes(self.reason_codes, "reason_codes"),
        )
        if not isinstance(self.review_recommended, bool):
            raise ValueError("review_recommended must be a boolean")


@dataclass(frozen=True)
class ClaimSupportAssessment:
    """逐 requirement 的 claim 支撑评估结果。

    ``status=formal_review_required`` 是支撑状态，表示当前只有候选等
    受限证据，不表示正式关系已确认。
    """

    requirement_id: str
    subrequest_id: str | None = None
    claim_capability: ClaimCapability | str | None = None
    status: ClaimSupportStatus | str = ClaimSupportStatus.MISSING
    supporting_evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    qualifying_evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    rejected_evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    conflict_ids: tuple[str, ...] = field(default_factory=tuple)
    qualifiers: tuple[str, ...] = field(default_factory=tuple)
    confidence: float | None = None
    confidence_basis: str | None = None
    reason_codes: tuple[ReasonCode | str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _require_text(self.requirement_id, "requirement_id")
        _require_optional_text(self.subrequest_id, "subrequest_id")
        if self.claim_capability is not None:
            object.__setattr__(
                self,
                "claim_capability",
                _coerce_enum(ClaimCapability, self.claim_capability, "claim_capability"),
            )
        object.__setattr__(
            self,
            "status",
            _coerce_enum(ClaimSupportStatus, self.status, "status"),
        )
        for field_name in (
            "supporting_evidence_ids",
            "qualifying_evidence_ids",
            "rejected_evidence_ids",
            "conflict_ids",
            "qualifiers",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_text_tuple(getattr(self, field_name), field_name),
            )
        if self.confidence is not None:
            if not isinstance(self.confidence, (int, float)) or isinstance(self.confidence, bool):
                raise ValueError("confidence must be numeric or None")
            if not 0.0 <= self.confidence <= 1.0:
                raise ValueError("confidence must be between 0 and 1")
        _require_optional_text(self.confidence_basis, "confidence_basis")
        object.__setattr__(
            self,
            "reason_codes",
            _coerce_reason_codes(self.reason_codes, "reason_codes"),
        )


@dataclass(frozen=True)
class AnswerabilityResult:
    """subrequest 或 request 级的可回答性计算结果。

    请求级结果通过 ``subrequest_results`` 携带各子请求状态，并保留
    局部可答结果；状态字段本身不生成最终答案。
    """

    status: Answerability | str
    subrequest_id: str | None = None
    blocking_reason_codes: tuple[ReasonCode | str, ...] = field(default_factory=tuple)
    affected_requirement_ids: tuple[str, ...] = field(default_factory=tuple)
    reason_codes: tuple[ReasonCode | str, ...] = field(default_factory=tuple)
    subrequest_results: tuple[AnswerabilityResult, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _coerce_enum(Answerability, self.status, "status"))
        _require_optional_text(self.subrequest_id, "subrequest_id")
        object.__setattr__(
            self,
            "blocking_reason_codes",
            _coerce_reason_codes(self.blocking_reason_codes, "blocking_reason_codes"),
        )
        object.__setattr__(
            self,
            "affected_requirement_ids",
            _require_text_tuple(self.affected_requirement_ids, "affected_requirement_ids"),
        )
        object.__setattr__(
            self,
            "reason_codes",
            _coerce_reason_codes(self.reason_codes, "reason_codes"),
        )
        for result in self.subrequest_results:
            if not isinstance(result, AnswerabilityResult):
                raise ValueError("subrequest_results must contain only AnswerabilityResult instances")


@dataclass(frozen=True)
class EvidenceLineage:
    """同一证据家族的取代关系解析结果，不把 lineage 当作 formal relation。"""

    lineage_id: str
    evidence_family_key: str
    current_evidence_id: str
    superseded_evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    stale_reason: str | None = None
    reason_codes: tuple[ReasonCode | str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _require_text(self.lineage_id, "lineage_id")
        _require_text(self.evidence_family_key, "evidence_family_key")
        _require_text(self.current_evidence_id, "current_evidence_id")
        object.__setattr__(
            self,
            "superseded_evidence_ids",
            _require_text_tuple(self.superseded_evidence_ids, "superseded_evidence_ids"),
        )
        _require_optional_text(self.stale_reason, "stale_reason")
        object.__setattr__(
            self,
            "reason_codes",
            _coerce_reason_codes(self.reason_codes, "reason_codes"),
        )


@dataclass(frozen=True)
class LineagePlan:
    """待写回的 stale/supersede 标记计划，不修改持久化旧证据本身。"""

    plan_id: str
    evidence_family_key: str
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    superseded_by_evidence_id: str | None = None
    stale_reason: str | None = None
    stale_at: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.plan_id, "plan_id")
        _require_text(self.evidence_family_key, "evidence_family_key")
        object.__setattr__(
            self,
            "evidence_ids",
            _require_text_tuple(self.evidence_ids, "evidence_ids"),
        )
        _require_optional_text(self.superseded_by_evidence_id, "superseded_by_evidence_id")
        _require_optional_text(self.stale_reason, "stale_reason")
        _require_optional_text(self.stale_at, "stale_at")


@dataclass(frozen=True)
class CacheTargetSummary:
    """逐识别目标的 expected/actual 缓存处置与命中证据摘要。"""

    target_id: str
    expected_cache_key: str | None = None
    expected_disposition: CacheDisposition | str | None = None
    actual_cache_key: str | None = None
    actual_disposition: CacheClosureStatus | str | None = None
    reused_evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    new_evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    recognition_run_id: str | None = None
    provider_called: bool = False
    persisted: bool = False

    def __post_init__(self) -> None:
        _require_text(self.target_id, "target_id")
        _require_optional_text(self.expected_cache_key, "expected_cache_key")
        if self.expected_disposition is not None:
            object.__setattr__(
                self,
                "expected_disposition",
                _coerce_enum(CacheDisposition, self.expected_disposition, "expected_disposition"),
            )
        _require_optional_text(self.actual_cache_key, "actual_cache_key")
        if self.actual_disposition is not None:
            object.__setattr__(
                self,
                "actual_disposition",
                _coerce_enum(CacheClosureStatus, self.actual_disposition, "actual_disposition"),
            )
        object.__setattr__(
            self,
            "reused_evidence_ids",
            _require_text_tuple(self.reused_evidence_ids, "reused_evidence_ids"),
        )
        object.__setattr__(
            self,
            "new_evidence_ids",
            _require_text_tuple(self.new_evidence_ids, "new_evidence_ids"),
        )
        _require_optional_text(self.recognition_run_id, "recognition_run_id")
        for field_name in ("provider_called", "persisted"):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"{field_name} must be a boolean")


@dataclass(frozen=True)
class CacheSummary:
    """请求级缓存闭环状态与逐目标摘要。

    只有 ``persistent_cache_committed=True`` 才报告跨请求缓存已建立；
    ``unknown``、``stale`` 和 ``miss`` 语义彼此独立。
    """

    status: CacheClosureStatus | str = CacheClosureStatus.UNKNOWN
    targets: tuple[CacheTargetSummary, ...] = field(default_factory=tuple)
    persistent_cache_committed: bool = False
    request_memo_used: bool = False
    new_recognition_run_ids: tuple[str, ...] = field(default_factory=tuple)
    reason_codes: tuple[ReasonCode | str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "status",
            _coerce_enum(CacheClosureStatus, self.status, "status"),
        )
        for target in self.targets:
            if not isinstance(target, CacheTargetSummary):
                raise ValueError("targets must contain only CacheTargetSummary instances")
        for field_name in ("persistent_cache_committed", "request_memo_used"):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"{field_name} must be a boolean")
        object.__setattr__(
            self,
            "new_recognition_run_ids",
            _require_text_tuple(self.new_recognition_run_ids, "new_recognition_run_ids"),
        )
        object.__setattr__(
            self,
            "reason_codes",
            _coerce_reason_codes(self.reason_codes, "reason_codes"),
        )
        object.__setattr__(
            self,
            "warnings",
            _require_text_tuple(self.warnings, "warnings"),
        )


@dataclass(frozen=True)
class WriteBackPolicy:
    """集中表达受控写回的三层授权与安全门控，默认全部关闭。"""

    request_allow_write_back: bool = False
    module_allow_write_back: bool = False
    environment_allow_write_back: bool = False
    allowed_fact_kinds: tuple[FactKind | str, ...] = field(default_factory=tuple)
    require_valid_scope: bool = True
    require_sanitized_payload: bool = True
    require_audit_material: bool = True
    block_on_conflict_severities: tuple[ConflictSeverity | str, ...] = field(default_factory=tuple)
    allow_persistent_cache: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "request_allow_write_back",
            "module_allow_write_back",
            "environment_allow_write_back",
            "require_valid_scope",
            "require_sanitized_payload",
            "require_audit_material",
            "allow_persistent_cache",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"{field_name} must be a boolean")
        object.__setattr__(
            self,
            "allowed_fact_kinds",
            tuple(_coerce_enum(FactKind, item, "allowed_fact_kinds") for item in self.allowed_fact_kinds),
        )
        object.__setattr__(
            self,
            "block_on_conflict_severities",
            tuple(
                _coerce_enum(ConflictSeverity, item, "block_on_conflict_severities")
                for item in self.block_on_conflict_severities
            ),
        )


@dataclass(frozen=True)
class SemanticWriteBatch:
    """04 合同校验后构造、可延迟持久化但尚未写入的强类型批次。

    只接受已验证的 run/attempt/payload envelope/observation/interpretation
    /candidate audit/cache entry，不接受任意 Cypher、Label 或 dict 写命令。
    """

    recognition_run_id: str
    schema_valid: bool = False
    scope_valid: bool = False
    payload_sanitized: bool = False
    audit_material_complete: bool = False
    run_summary: RecognitionRunSummary | None = None
    attempts: tuple[RecognitionAttempt, ...] = field(default_factory=tuple)
    sanitized_payload_envelope: Mapping[str, Any] | None = None
    observations: tuple[TextObservation, ...] = field(default_factory=tuple)
    interpretations: tuple[
        BlockInterpretation | BasicInfoInterpretation | TableInterpretation, ...
    ] = field(default_factory=tuple)
    candidate_evidence: tuple[RecognitionCandidateEvidence, ...] = field(default_factory=tuple)
    cache_entries: tuple[Any, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _require_text(self.recognition_run_id, "recognition_run_id")
        for field_name in ("schema_valid", "scope_valid", "payload_sanitized", "audit_material_complete"):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"{field_name} must be a boolean")
        for field_name in ("attempts", "observations", "interpretations", "candidate_evidence", "cache_entries"):
            if not isinstance(getattr(self, field_name), tuple):
                raise ValueError(f"{field_name} must be a tuple")
        if self.sanitized_payload_envelope is not None and not isinstance(
            self.sanitized_payload_envelope, Mapping
        ):
            raise ValueError("sanitized_payload_envelope must be a mapping or None")


@dataclass(frozen=True)
class WriteBackItemResult:
    """单个持久化阶段的逐项结果与原因码。"""

    stage: str
    status: WriteBackItemStatus | str
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    reason_code: ReasonCode | str | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.stage, "stage")
        object.__setattr__(self, "status", _coerce_enum(WriteBackItemStatus, self.status, "status"))
        object.__setattr__(
            self,
            "evidence_ids",
            _require_text_tuple(self.evidence_ids, "evidence_ids"),
        )
        if self.reason_code is not None:
            object.__setattr__(
                self,
                "reason_code",
                _coerce_enum(ReasonCode, self.reason_code, "reason_code"),
            )
        _require_optional_text(self.message, "message")


@dataclass(frozen=True)
class WriteBackResult:
    """受控写回的总体结果、逐项结果、stale/supersede 与实际 commit 状态。"""

    status: WriteBackStatus | str = WriteBackStatus.NOT_REQUESTED
    items: tuple[WriteBackItemResult, ...] = field(default_factory=tuple)
    persisted_evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    stale_evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    supersede_links: tuple[str, ...] = field(default_factory=tuple)
    payload_refs: tuple[str, ...] = field(default_factory=tuple)
    recognition_run_ids: tuple[str, ...] = field(default_factory=tuple)
    persistent_cache_committed: bool = False
    reason_codes: tuple[ReasonCode | str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _coerce_enum(WriteBackStatus, self.status, "status"))
        for item in self.items:
            if not isinstance(item, WriteBackItemResult):
                raise ValueError("items must contain only WriteBackItemResult instances")
        for field_name in (
            "persisted_evidence_ids",
            "stale_evidence_ids",
            "supersede_links",
            "payload_refs",
            "recognition_run_ids",
            "warnings",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_text_tuple(getattr(self, field_name), field_name),
            )
        if not isinstance(self.persistent_cache_committed, bool):
            raise ValueError("persistent_cache_committed must be a boolean")
        object.__setattr__(
            self,
            "reason_codes",
            _coerce_reason_codes(self.reason_codes, "reason_codes"),
        )


@dataclass(frozen=True)
class EvidenceFusionRequest:
    """05 唯一输入容器，显式携带原始授权请求与完整证据需求上下文。"""

    assistant_request: AssistantRequest
    question_result: QuestionUnderstandingResult
    retrieval_bundle: RetrievalBundle
    semantic_gap_decision: SemanticGapDecision
    recognition_results: tuple[SemanticRecognitionResult, ...] = field(default_factory=tuple)
    write_back_policy: WriteBackPolicy | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.assistant_request, AssistantRequest):
            raise ValueError("assistant_request must be an AssistantRequest")
        if not isinstance(self.question_result, QuestionUnderstandingResult):
            raise ValueError("question_result must be a QuestionUnderstandingResult")
        if not isinstance(self.retrieval_bundle, RetrievalBundle):
            raise ValueError("retrieval_bundle must be a RetrievalBundle")
        if not isinstance(self.semantic_gap_decision, SemanticGapDecision):
            raise ValueError("semantic_gap_decision must be a SemanticGapDecision")
        if not isinstance(self.recognition_results, tuple):
            raise ValueError("recognition_results must be a tuple")
        if self.write_back_policy is not None and not isinstance(self.write_back_policy, WriteBackPolicy):
            raise ValueError("write_back_policy must be a WriteBackPolicy or None")


@dataclass(frozen=True)
class EvidenceBundle:
    """05 唯一输出，供 06/07 消费。

    ``accepted_evidence`` 仅表示可用于当前回答，不等于已持久化或已成为
    正式事实。
    """

    request_id: str
    subrequest_id: str | None = None
    accepted_evidence: tuple[FusionEvidence, ...] = field(default_factory=tuple)
    conflicting_evidence: tuple[FusionEvidence, ...] = field(default_factory=tuple)
    conflicts: tuple[ConflictRecord, ...] = field(default_factory=tuple)
    claim_support: tuple[ClaimSupportAssessment, ...] = field(default_factory=tuple)
    unsupported_claims: tuple[str, ...] = field(default_factory=tuple)
    lineage: tuple[EvidenceLineage, ...] = field(default_factory=tuple)
    cache_summary: CacheSummary | None = None
    provenance: tuple[EvidenceProvenance, ...] = field(default_factory=tuple)
    overall_confidence: float | None = None
    answerability: AnswerabilityResult | None = None
    reason_codes: tuple[ReasonCode | str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    write_back_result: WriteBackResult | None = None
    contract_version: str = FUSION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_text(self.request_id, "request_id")
        _require_optional_text(self.subrequest_id, "subrequest_id")
        for field_name, expected_type in (
            ("accepted_evidence", FusionEvidence),
            ("conflicting_evidence", FusionEvidence),
        ):
            values = getattr(self, field_name)
            if not isinstance(values, tuple) or not all(isinstance(item, expected_type) for item in values):
                raise ValueError(f"{field_name} must contain only {expected_type.__name__} instances")
        for field_name, expected_type in (
            ("conflicts", ConflictRecord),
            ("claim_support", ClaimSupportAssessment),
            ("lineage", EvidenceLineage),
            ("provenance", EvidenceProvenance),
        ):
            values = getattr(self, field_name)
            if not isinstance(values, tuple) or not all(isinstance(item, expected_type) for item in values):
                raise ValueError(f"{field_name} must contain only {expected_type.__name__} instances")
        object.__setattr__(
            self,
            "unsupported_claims",
            _require_text_tuple(self.unsupported_claims, "unsupported_claims"),
        )
        if self.cache_summary is not None and not isinstance(self.cache_summary, CacheSummary):
            raise ValueError("cache_summary must be a CacheSummary or None")
        if self.overall_confidence is not None:
            if not isinstance(self.overall_confidence, (int, float)) or isinstance(self.overall_confidence, bool):
                raise ValueError("overall_confidence must be numeric or None")
            if not 0.0 <= self.overall_confidence <= 1.0:
                raise ValueError("overall_confidence must be between 0 and 1")
        if self.answerability is not None and not isinstance(self.answerability, AnswerabilityResult):
            raise ValueError("answerability must be an AnswerabilityResult or None")
        object.__setattr__(
            self,
            "reason_codes",
            _coerce_reason_codes(self.reason_codes, "reason_codes"),
        )
        object.__setattr__(
            self,
            "warnings",
            _require_text_tuple(self.warnings, "warnings"),
        )
        if self.write_back_result is not None and not isinstance(self.write_back_result, WriteBackResult):
            raise ValueError("write_back_result must be a WriteBackResult or None")
        _require_text(self.contract_version, "contract_version")
