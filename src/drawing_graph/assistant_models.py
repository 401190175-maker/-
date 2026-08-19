"""Product assistant public contract DTOs and stable enums.

本模块是产品实现层的公共合同：定义产品请求、证据需求、检索计划、
统一证据、答案、追溯与反馈的稳定 DTO，以及事实类型、状态和原因码。
模块不依赖数据库驱动、仓储、查询语句、HTTP 框架、MCP SDK 或
Qwen/DashScope 客户端；默认只读，默认 ``write_back=false``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from .assistant_evidence_fusion_models import EvidenceBundle

CONTRACT_VERSION = "drawing-assistant-contract-v1"
RETRIEVAL_CONTRACT_VERSION = "drawing-assistant-retrieval-v1"
ANSWER_CONTRACT_VERSION = "drawing-assistant-answer-v1"


class FactKind(str, Enum):
    """统一事实层级，归一化后不允许被后续模块提升或篡改。"""

    SOURCE_FACT = "source_fact"
    DERIVED_RELATION = "derived_relation"
    SEMANTIC_OBSERVATION = "semantic_observation"
    SEMANTIC_INTERPRETATION = "semantic_interpretation"
    CANDIDATE_RELATION = "candidate_relation"
    FORMAL_RELATION = "formal_relation"
    DIAGNOSTIC = "diagnostic"
    UNSUPPORTED = "unsupported"


class RetrievalStatus(str, Enum):
    """通用检索闭环的整体状态。"""

    OK = "ok"
    PARTIAL = "partial"
    ERROR = "error"
    UNSUPPORTED = "unsupported"
    CLARIFICATION_REQUIRED = "clarification_required"


class QuestionType(str, Enum):
    """产品层稳定问题类型，供问题理解闭环与下游检索消费。"""

    PAGE_SUMMARY = "page_summary"
    BLOCK_RELATIONS = "block_relations"
    BLOCK_SEMANTIC_IDENTIFICATION = "block_semantic_identification"
    ELEMENT_TEXT_OR_MEANING = "element_text_or_meaning"
    CANDIDATE_RELATIONS = "candidate_relations"
    SECTION_MATCHES = "section_matches"
    TABLE_CAPTION_STATUS = "table_caption_status"
    DRAWING_DIAGNOSTIC = "drawing_diagnostic"
    SOURCE_TRACE = "source_trace"
    COMPARISON = "comparison"
    CLARIFICATION_REQUIRED = "clarification_required"
    UNKNOWN_OR_UNSUPPORTED = "unknown_or_unsupported"


class AnswerStatus(str, Enum):
    """产品答案的整体稳定状态，由确定性代码解析，不由文本模型决定。"""

    ANSWERED = "answered"
    PARTIAL = "partial"
    CLARIFICATION_REQUIRED = "clarification_required"
    UNSUPPORTED = "unsupported"
    RECOGNITION_FAILED = "recognition_failed"


class ClaimStatus(str, Enum):
    """单个 claim 的稳定支撑状态，约束其 statement 可使用的确定性措辞。"""

    SUPPORTED = "supported"
    QUALIFIED = "qualified"
    CONFLICTING = "conflicting"
    FORMAL_REVIEW_REQUIRED = "formal_review_required"
    DIAGNOSTIC = "diagnostic"


class TextRenderMode(str, Enum):
    """文本答案的渲染模式：确定性模板或受约束文本生成。"""

    TEMPLATE = "template"
    CONSTRAINED_TEXT = "constrained_text"


class EvidenceType(str, Enum):
    """产品层证据类型，对应通用检索可映射的 facade 只读能力。"""

    PROJECT_DRAWING_SETS = "project_drawing_sets"
    DRAWING_SET_PAGES = "drawing_set_pages"
    PAGE_SOURCE_FACTS = "page_source_facts"
    BLOCK_TRACE = "block_trace"
    BLOCK_RELATIONS = "block_relations"
    TEXT_OBSERVATIONS = "text_observations"
    STRUCTURED_INTERPRETATIONS = "structured_interpretations"
    SEMANTIC_PAYLOAD = "semantic_payload"
    CANDIDATE_RELATIONS = "candidate_relations"
    SECTION_MATCHES = "section_matches"


class ReasonCode(str, Enum):
    """稳定原因码，用于 missing evidence、warning 与 source call 失败分类。"""

    SCOPE_MISSING = "scope_missing"
    SCOPE_CONFLICT = "scope_conflict"
    UNSUPPORTED_EVIDENCE_TYPE = "unsupported_evidence_type"
    TARGET_NOT_FOUND = "target_not_found"
    EMPTY_RESULT = "empty_result"
    FACADE_CALL_FAILED = "facade_call_failed"
    PAYLOAD_UNAVAILABLE = "payload_unavailable"
    RESULT_TRUNCATED = "result_truncated"
    AMBIGUOUS_REFERENCE = "ambiguous_reference"
    AMBIGUOUS_QUESTION_TYPE = "ambiguous_question_type"
    MULTI_INTENT_AMBIGUOUS = "multi_intent_ambiguous"
    UNSUPPORTED_QUESTION = "unsupported_question"
    MODEL_OUTPUT_INVALID = "model_output_invalid"
    EVIDENCE_COMPLETE = "evidence_complete"
    EVIDENCE_MISSING = "evidence_missing"
    OBSERVATION_MISSING = "observation_missing"
    INTERPRETATION_MISSING = "interpretation_missing"
    EVIDENCE_STALE = "evidence_stale"
    IMAGE_CHANGED = "image_changed"
    BBOX_CHANGED = "bbox_changed"
    MODEL_PROFILE_CHANGED = "model_profile_changed"
    PROMPT_VERSION_CHANGED = "prompt_version_changed"
    CONTRACT_VERSION_CHANGED = "contract_version_changed"
    PREPROCESSING_VERSION_CHANGED = "preprocessing_version_changed"
    NORMALIZATION_RULE_CHANGED = "normalization_rule_changed"
    EVIDENCE_CONFLICT = "evidence_conflict"
    STATUS_INSUFFICIENT = "status_insufficient"
    EVIDENCE_KIND_MISMATCH = "evidence_kind_mismatch"
    RECOGNITION_FORBIDDEN = "recognition_forbidden"
    BUDGET_EXCEEDED = "budget_exceeded"
    LATENCY_EXCEEDED = "latency_exceeded"
    ESTIMATE_UNAVAILABLE = "estimate_unavailable"
    FORMAL_REVIEW_REQUIRED = "formal_review_required"
    UNSUPPORTED_GENERATION = "unsupported_generation"
    CACHE_KEY_UNAVAILABLE = "cache_key_unavailable"
    TARGET_LOCATION_MISSING = "target_location_missing"
    FUSION_INPUT_INVALID = "fusion_input_invalid"
    EVIDENCE_PROJECTION_FAILED = "evidence_projection_failed"
    EVIDENCE_NORMALIZATION_FAILED = "evidence_normalization_failed"
    CONFLICT_POLICY_INVALID = "conflict_policy_invalid"
    CLAIM_SUPPORT_FAILED = "claim_support_failed"
    CACHE_CLOSURE_INCONSISTENT = "cache_closure_inconsistent"
    WRITE_BACK_DENIED = "write_back_denied"
    PERSISTENCE_UNAVAILABLE = "persistence_unavailable"
    WRITE_BACK_PARTIAL = "write_back_partial"
    LINEAGE_WRITE_FAILED = "lineage_write_failed"
    INTERNAL_ERROR = "internal_error"
    RECOGNITION_SCOPE_MISMATCH = "recognition_scope_mismatch"
    TEXT_GENERATION_FAILED = "text_generation_failed"
    TEXT_OUTPUT_INVALID = "text_output_invalid"
    ANSWER_VALIDATION_FAILED = "answer_validation_failed"
    RECOGNITION_FAILED = "recognition_failed"
    MAX_SUBREQUESTS_EXCEEDED = "max_subrequests_exceeded"
    MAX_PAGE_GROUPS_EXCEEDED = "max_page_groups_exceeded"
    MAX_CLAIMS_EXCEEDED = "max_claims_exceeded"
    MAX_CITATIONS_EXCEEDED = "max_citations_exceeded"


class FreshnessPolicy(str, Enum):
    """证据时效策略，检索阶段只读消费，不触发任何写回。"""

    ANY = "any"
    CURRENT_IMAGE = "current_image"
    CURRENT_PROMPT = "current_prompt"
    CURRENT_CONTRACT = "current_contract"


class SemanticGapDecisionType(str, Enum):
    """语义缺口决策闭环的稳定最终决策值。"""

    REUSE_EXISTING = "reuse_existing"
    RECOGNIZE_REQUIRED = "recognize_required"
    CLARIFICATION_REQUIRED = "clarification_required"
    UNSUPPORTED = "unsupported"


class RequirementAssessmentStatus(str, Enum):
    """单个证据需求在充分性评估后的稳定状态。"""

    SATISFIED = "satisfied"
    MISSING = "missing"
    STALE = "stale"
    CONFLICTING = "conflicting"
    FORBIDDEN = "forbidden"
    UNSUPPORTED = "unsupported"
    FORMAL_REVIEW_REQUIRED = "formal_review_required"


class CacheDisposition(str, Enum):
    """决策阶段对既有语义证据的缓存处置分类。"""

    FULL_HIT = "full_hit"
    PARTIAL_HIT = "partial_hit"
    MISS = "miss"
    STALE = "stale"
    BYPASSED = "bypassed"
    UNKNOWN = "unknown"


class RecognitionTargetStatus(str, Enum):
    """识别目标在预算/时延门控后的稳定状态。"""

    SELECTED = "selected"
    DEFERRED = "deferred"
    BLOCKED = "blocked"


class EstimateStatus(str, Enum):
    """识别成本/时延估算的稳定状态。"""

    ESTIMATED = "estimated"
    NOT_REQUIRED = "not_required"
    ESTIMATE_UNAVAILABLE = "estimate_unavailable"
    BUDGET_EXCEEDED = "budget_exceeded"
    LATENCY_EXCEEDED = "latency_exceeded"


def _require_text(value: str | None, field_name: str) -> str:
    """校验必填文本字段，拒绝空字符串或纯空白。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _require_optional_text(value: str | None, field_name: str) -> str | None:
    """校验可选文本字段，允许 None，拒绝空字符串或纯空白。"""

    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be None or a non-empty string")
    return value


def _require_positive_int(value: int | None, field_name: str) -> int | None:
    """校验可选正整数（limit 等），拒绝 0、负数或非整数。"""

    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer or None")
    return value


def _require_non_negative_int(value: int | None, field_name: str) -> int | None:
    """校验可选非负整数（result_count 等），拒绝负数或非整数。"""

    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer or None")
    return value


def _require_non_negative_number(value: float | None, field_name: str) -> float | None:
    """校验可选非负数（预算/时延等），拒绝负数或非数值。"""

    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative number or None")
    return value


def _require_text_tuple(values: object, field_name: str) -> tuple[str, ...]:
    """校验非空字符串元组并原样返回。"""

    if not isinstance(values, tuple) or not all(
        isinstance(item, str) and item.strip() for item in values
    ):
        raise ValueError(f"{field_name} must be a tuple of non-empty strings")
    return values


def _require_bbox_mapping(
    value: Mapping[str, float] | None,
    field_name: str,
) -> Mapping[str, float] | None:
    """校验并冻结 bbox 映射，只接受稳定数值字段。"""

    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a mapping or None")
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError(f"{field_name} keys must be non-empty strings")
        if not isinstance(item, (int, float)) or isinstance(item, bool):
            raise ValueError(f"{field_name} values must be numeric")
    return MappingProxyType(dict(value))


def _coerce_enum(enum_type: type[Enum], value: object, field_name: str) -> Enum:
    """将稳定字符串或枚举成员规整为对应枚举。"""

    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        try:
            return enum_type(value)
        except ValueError as exc:
            raise ValueError(f"{field_name} is not a valid {enum_type.__name__}") from exc
    raise ValueError(f"{field_name} must be a {enum_type.__name__} or its stable string")


@dataclass(frozen=True)
class AssistantScope:
    """产品请求范围，只承载稳定业务 ID，不接受数据库内部 ID 或自由查询语句。"""

    project_id: str | None = None
    drawing_set_id: str | None = None
    page_id: str | None = None
    block_id: str | None = None
    element_id: str | None = None
    cross_section_id: str | None = None
    table_id: str | None = None
    table_caption_id: str | None = None
    claim_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "project_id",
            "drawing_set_id",
            "page_id",
            "block_id",
            "element_id",
            "cross_section_id",
            "table_id",
            "table_caption_id",
            "claim_id",
        ):
            _require_optional_text(getattr(self, field_name), field_name)


@dataclass(frozen=True)
class AssistantRequest:
    """产品助手请求，默认只读（``allow_write_back=False``）。"""

    request_id: str
    question: str
    conversation_context: str | None = None
    scope_hint: AssistantScope | None = None
    language: str = "zh-CN"
    allow_recognition: bool = True
    allow_write_back: bool = False
    answer_format: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.request_id, "request_id")
        _require_text(self.question, "question")
        _require_optional_text(self.conversation_context, "conversation_context")
        _require_optional_text(self.language, "language")
        _require_optional_text(self.answer_format, "answer_format")
        if self.scope_hint is not None and not isinstance(self.scope_hint, AssistantScope):
            raise ValueError("scope_hint must be an AssistantScope or None")
        for field_name in ("allow_recognition", "allow_write_back"):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"{field_name} must be a boolean")


@dataclass(frozen=True)
class EvidenceRequirement:
    """描述“回答问题需要什么证据”，只表达检索意图，不代表允许写数据库。"""

    requirement_id: str
    evidence_type: EvidenceType | str
    target_scope: AssistantScope
    required: bool = True
    minimum_status: str | None = None
    freshness_policy: FreshnessPolicy | str = FreshnessPolicy.ANY
    freshness_requirement: FreshnessRequirement | None = None
    allow_model_generation: bool = False
    include_payload: bool = False
    limit: int | None = None
    payload_ref: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.requirement_id, "requirement_id")
        object.__setattr__(self, "evidence_type", _coerce_enum(EvidenceType, self.evidence_type, "evidence_type"))
        if not isinstance(self.target_scope, AssistantScope):
            raise ValueError("target_scope must be an AssistantScope")
        for field_name in ("required", "allow_model_generation", "include_payload"):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"{field_name} must be a boolean")
        _require_optional_text(self.minimum_status, "minimum_status")
        object.__setattr__(
            self,
            "freshness_policy",
            _coerce_enum(FreshnessPolicy, self.freshness_policy, "freshness_policy"),
        )
        if self.freshness_requirement is not None and not isinstance(
            self.freshness_requirement, FreshnessRequirement
        ):
            raise ValueError("freshness_requirement must be a FreshnessRequirement or None")
        _require_positive_int(self.limit, "limit")
        _require_optional_text(self.payload_ref, "payload_ref")


@dataclass(frozen=True)
class FreshnessRequirement:
    """可组合的 freshness 维度约束，兼容旧 ``FreshnessPolicy``。"""

    require_current_image: bool = False
    require_current_bbox: bool = False
    require_current_model: bool = False
    require_current_prompt: bool = False
    require_current_preprocessing: bool = False
    require_current_normalization: bool = False
    require_current_contract: bool = False
    allow_stale: bool = False
    max_age_seconds: int | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "require_current_image",
            "require_current_bbox",
            "require_current_model",
            "require_current_prompt",
            "require_current_preprocessing",
            "require_current_normalization",
            "require_current_contract",
            "allow_stale",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"{field_name} must be a boolean")
        _require_non_negative_int(self.max_age_seconds, "max_age_seconds")

    @classmethod
    def from_policy(cls, policy: FreshnessPolicy | str) -> "FreshnessRequirement":
        """把旧版单一 ``FreshnessPolicy`` 映射为组合 freshness 约束。"""

        normalized = _coerce_enum(FreshnessPolicy, policy, "freshness_policy")
        if normalized is FreshnessPolicy.ANY:
            return cls()
        if normalized is FreshnessPolicy.CURRENT_IMAGE:
            return cls(require_current_image=True, require_current_bbox=True)
        if normalized is FreshnessPolicy.CURRENT_PROMPT:
            return cls(require_current_prompt=True)
        if normalized is FreshnessPolicy.CURRENT_CONTRACT:
            return cls(require_current_contract=True)
        raise ValueError(f"unsupported freshness policy: {normalized.value}")


@dataclass(frozen=True)
class FreshnessResult:
    """单个证据的 freshness 判断结果：维度满足情况、缺失元数据与原因码。"""

    dimensions: Mapping[str, bool] = field(default_factory=dict)
    missing_metadata: tuple[str, ...] = field(default_factory=tuple)
    reason_codes: tuple[ReasonCode | str, ...] = field(default_factory=tuple)
    is_current: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.dimensions, Mapping):
            raise ValueError("dimensions must be a mapping")
        for key, value in self.dimensions.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("dimensions keys must be non-empty strings")
            if not isinstance(value, bool):
                raise ValueError("dimensions values must be booleans")
        object.__setattr__(self, "dimensions", MappingProxyType(dict(self.dimensions)))
        if not isinstance(self.missing_metadata, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.missing_metadata
        ):
            raise ValueError("missing_metadata must be a tuple of non-empty strings")
        if not isinstance(self.reason_codes, tuple):
            raise ValueError("reason_codes must be a tuple")
        object.__setattr__(
            self,
            "reason_codes",
            tuple(_coerce_enum(ReasonCode, code, "reason_codes") for code in self.reason_codes),
        )
        if not isinstance(self.is_current, bool):
            raise ValueError("is_current must be a boolean")


@dataclass(frozen=True)
class CacheCandidate:
    """预期缓存键与处置结果，供目标规划与后续执行追溯。"""

    requirement_id: str
    target_id: str | None = None
    cache_key: str | None = None
    disposition: CacheDisposition | str = CacheDisposition.UNKNOWN
    reusable_evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    reason_codes: tuple[ReasonCode | str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _require_text(self.requirement_id, "requirement_id")
        _require_optional_text(self.target_id, "target_id")
        _require_optional_text(self.cache_key, "cache_key")
        object.__setattr__(
            self,
            "disposition",
            _coerce_enum(CacheDisposition, self.disposition, "disposition"),
        )
        if not isinstance(self.reusable_evidence_ids, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.reusable_evidence_ids
        ):
            raise ValueError("reusable_evidence_ids must be a tuple of non-empty strings")
        if not isinstance(self.reason_codes, tuple):
            raise ValueError("reason_codes must be a tuple")
        object.__setattr__(
            self,
            "reason_codes",
            tuple(_coerce_enum(ReasonCode, code, "reason_codes") for code in self.reason_codes),
        )


@dataclass(frozen=True)
class RecognitionPolicy:
    """识别授权、目标数、成本/时延上限与模型/版本策略。"""

    allow_recognition: bool = True
    max_targets: int | None = None
    max_estimated_cost: float | None = None
    max_latency_seconds: float | None = None
    model_profile: str | None = None
    model_version: str | None = None
    prompt_version: str | None = None
    preprocessing_version: str | None = None
    normalization_rule_version: str | None = None
    contract_version: str = CONTRACT_VERSION
    cache_mode: str = "default"
    retry_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.allow_recognition, bool):
            raise ValueError("allow_recognition must be a boolean")
        _require_positive_int(self.max_targets, "max_targets")
        _require_non_negative_number(self.max_estimated_cost, "max_estimated_cost")
        _require_non_negative_number(self.max_latency_seconds, "max_latency_seconds")
        for field_name in (
            "model_profile",
            "model_version",
            "prompt_version",
            "preprocessing_version",
            "normalization_rule_version",
        ):
            _require_optional_text(getattr(self, field_name), field_name)
        _require_text(self.contract_version, "contract_version")
        if self.cache_mode not in {"default", "bypass"}:
            raise ValueError("cache_mode must be 'default' or 'bypass'")
        if not isinstance(self.retry_count, int) or isinstance(self.retry_count, bool) or self.retry_count < 0:
            raise ValueError("retry_count must be a non-negative integer")


@dataclass(frozen=True)
class RequirementAssessment:
    """单个证据需求的充分性评估结果，携带证据 ID 与稳定原因码。"""

    requirement_id: str
    status: RequirementAssessmentStatus | str = RequirementAssessmentStatus.MISSING
    matched_evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    rejected_evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    reason_codes: tuple[ReasonCode | str, ...] = field(default_factory=tuple)
    missing_metadata: tuple[str, ...] = field(default_factory=tuple)
    freshness_result: FreshnessResult | None = None
    cache_disposition: CacheDisposition | str | None = None
    allow_model_generation: bool = False

    def __post_init__(self) -> None:
        _require_text(self.requirement_id, "requirement_id")
        object.__setattr__(
            self,
            "status",
            _coerce_enum(RequirementAssessmentStatus, self.status, "status"),
        )
        object.__setattr__(
            self,
            "matched_evidence_ids",
            _require_text_tuple(self.matched_evidence_ids, "matched_evidence_ids"),
        )
        object.__setattr__(
            self,
            "rejected_evidence_ids",
            _require_text_tuple(self.rejected_evidence_ids, "rejected_evidence_ids"),
        )
        if not isinstance(self.reason_codes, tuple):
            raise ValueError("reason_codes must be a tuple")
        object.__setattr__(
            self,
            "reason_codes",
            tuple(_coerce_enum(ReasonCode, code, "reason_codes") for code in self.reason_codes),
        )
        object.__setattr__(
            self,
            "missing_metadata",
            _require_text_tuple(self.missing_metadata, "missing_metadata"),
        )
        if self.freshness_result is not None and not isinstance(self.freshness_result, FreshnessResult):
            raise ValueError("freshness_result must be a FreshnessResult or None")
        if self.cache_disposition is not None:
            object.__setattr__(
                self,
                "cache_disposition",
                _coerce_enum(CacheDisposition, self.cache_disposition, "cache_disposition"),
            )
        if not isinstance(self.allow_model_generation, bool):
            raise ValueError("allow_model_generation must be a boolean")


@dataclass(frozen=True)
class RecognitionTarget:
    """最小识别目标，精确到 page/block/element/bbox 与任务/输出合同。"""

    target_id: str
    target_type: str
    task_type: str
    page_id: str | None = None
    target_element_id: str | None = None
    required_outputs: tuple[str, ...] = field(default_factory=tuple)
    bbox: Mapping[str, float] | None = None
    normalized_bbox: Mapping[str, float] | None = None
    context_element_ids: tuple[str, ...] = field(default_factory=tuple)
    covered_requirement_ids: tuple[str, ...] = field(default_factory=tuple)
    cache_key: str | None = None
    priority: int = 0
    status: RecognitionTargetStatus | str = RecognitionTargetStatus.SELECTED
    reason_codes: tuple[ReasonCode | str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _require_text(self.target_id, "target_id")
        _require_text(self.target_type, "target_type")
        _require_text(self.task_type, "task_type")
        _require_optional_text(self.page_id, "page_id")
        _require_optional_text(self.target_element_id, "target_element_id")
        object.__setattr__(
            self,
            "required_outputs",
            _require_text_tuple(self.required_outputs, "required_outputs"),
        )
        object.__setattr__(self, "bbox", _require_bbox_mapping(self.bbox, "bbox"))
        object.__setattr__(
            self,
            "normalized_bbox",
            _require_bbox_mapping(self.normalized_bbox, "normalized_bbox"),
        )
        object.__setattr__(
            self,
            "context_element_ids",
            _require_text_tuple(self.context_element_ids, "context_element_ids"),
        )
        object.__setattr__(
            self,
            "covered_requirement_ids",
            _require_text_tuple(self.covered_requirement_ids, "covered_requirement_ids"),
        )
        if not self.covered_requirement_ids:
            raise ValueError("covered_requirement_ids must not be empty")
        _require_optional_text(self.cache_key, "cache_key")
        if not isinstance(self.priority, int) or isinstance(self.priority, bool) or self.priority < 0:
            raise ValueError("priority must be a non-negative integer")
        object.__setattr__(
            self,
            "status",
            _coerce_enum(RecognitionTargetStatus, self.status, "status"),
        )
        if not isinstance(self.reason_codes, tuple):
            raise ValueError("reason_codes must be a tuple")
        object.__setattr__(
            self,
            "reason_codes",
            tuple(_coerce_enum(ReasonCode, code, "reason_codes") for code in self.reason_codes),
        )


@dataclass(frozen=True)
class RecognitionEstimate:
    """识别目标数、估算成本与时延的决策元数据，不代表实际账单。"""

    status: EstimateStatus | str = EstimateStatus.ESTIMATE_UNAVAILABLE
    selected_target_count: int = 0
    deferred_target_count: int = 0
    estimated_cost: float | None = None
    estimated_latency_ms: float | None = None
    currency: str | None = None
    estimator_version: str = "semantic-gap-estimator-v1"
    reason_codes: tuple[ReasonCode | str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "status",
            _coerce_enum(EstimateStatus, self.status, "status"),
        )
        for field_name in ("selected_target_count", "deferred_target_count"):
            if (
                not isinstance(getattr(self, field_name), int)
                or isinstance(getattr(self, field_name), bool)
                or getattr(self, field_name) < 0
            ):
                raise ValueError(f"{field_name} must be a non-negative integer")
        _require_non_negative_number(self.estimated_cost, "estimated_cost")
        _require_non_negative_number(self.estimated_latency_ms, "estimated_latency_ms")
        _require_optional_text(self.currency, "currency")
        _require_text(self.estimator_version, "estimator_version")
        if not isinstance(self.reason_codes, tuple):
            raise ValueError("reason_codes must be a tuple")
        object.__setattr__(
            self,
            "reason_codes",
            tuple(_coerce_enum(ReasonCode, code, "reason_codes") for code in self.reason_codes),
        )


@dataclass(frozen=True)
class SemanticGapDecision:
    """语义缺口决策闭环的统一输出，只承载决策数据，不触发任何副作用。"""

    request_id: str
    decision: SemanticGapDecisionType | str = SemanticGapDecisionType.UNSUPPORTED
    subrequest_id: str | None = None
    requirement_assessments: tuple[RequirementAssessment, ...] = field(default_factory=tuple)
    missing_requirements: tuple[str, ...] = field(default_factory=tuple)
    cache_candidates: tuple[CacheCandidate, ...] = field(default_factory=tuple)
    selected_targets: tuple[RecognitionTarget, ...] = field(default_factory=tuple)
    deferred_targets: tuple[RecognitionTarget, ...] = field(default_factory=tuple)
    estimate: RecognitionEstimate | None = None
    reason_codes: tuple[ReasonCode | str, ...] = field(default_factory=tuple)
    write_back_recommendation: bool = False
    warnings: tuple[object, ...] = field(default_factory=tuple)
    contract_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_text(self.request_id, "request_id")
        object.__setattr__(
            self,
            "decision",
            _coerce_enum(SemanticGapDecisionType, self.decision, "decision"),
        )
        _require_optional_text(self.subrequest_id, "subrequest_id")
        for field_name, expected_type in (
            ("requirement_assessments", RequirementAssessment),
            ("cache_candidates", CacheCandidate),
            ("selected_targets", RecognitionTarget),
            ("deferred_targets", RecognitionTarget),
        ):
            values = getattr(self, field_name)
            if not isinstance(values, tuple) or not all(
                isinstance(item, expected_type) for item in values
            ):
                raise ValueError(f"{field_name} must contain only {expected_type.__name__} instances")
        object.__setattr__(
            self,
            "missing_requirements",
            _require_text_tuple(self.missing_requirements, "missing_requirements"),
        )
        if self.estimate is not None and not isinstance(self.estimate, RecognitionEstimate):
            raise ValueError("estimate must be a RecognitionEstimate or None")
        if not isinstance(self.reason_codes, tuple):
            raise ValueError("reason_codes must be a tuple")
        object.__setattr__(
            self,
            "reason_codes",
            tuple(_coerce_enum(ReasonCode, code, "reason_codes") for code in self.reason_codes),
        )
        if not isinstance(self.write_back_recommendation, bool):
            raise ValueError("write_back_recommendation must be a boolean")
        if not isinstance(self.warnings, tuple):
            raise ValueError("warnings must be a tuple")
        _require_text(self.contract_version, "contract_version")


@dataclass(frozen=True)
class RetrievalPolicy:
    """检索阶段策略：limit 上限与 payload 默认展开开关。"""

    default_limit: int = 100
    max_limit: int = 500
    include_payload_by_default: bool = False

    def __post_init__(self) -> None:
        _require_positive_int(self.default_limit, "default_limit")
        _require_positive_int(self.max_limit, "max_limit")
        if self.max_limit < self.default_limit:
            raise ValueError("max_limit must be greater than or equal to default_limit")
        if not isinstance(self.include_payload_by_default, bool):
            raise ValueError("include_payload_by_default must be a boolean")


@dataclass(frozen=True)
class RetrievalStep:
    """一个可执行、可审计、可去重的只读 facade 查询步骤。"""

    step_id: str
    facade_method: str
    scope: AssistantScope | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)
    required: bool = True
    depends_on: tuple[str, ...] = field(default_factory=tuple)
    limit: int | None = None
    include_payload: bool = False
    requirement_ids: tuple[str, ...] = field(default_factory=tuple)
    dedupe_key: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.step_id, "step_id")
        _require_text(self.facade_method, "facade_method")
        if self.scope is not None and not isinstance(self.scope, AssistantScope):
            raise ValueError("scope must be an AssistantScope or None")
        if not isinstance(self.parameters, Mapping):
            raise ValueError("parameters must be a mapping")
        if not isinstance(self.required, bool):
            raise ValueError("required must be a boolean")
        if not isinstance(self.include_payload, bool):
            raise ValueError("include_payload must be a boolean")
        _require_positive_int(self.limit, "limit")
        _require_optional_text(self.dedupe_key, "dedupe_key")
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))


@dataclass(frozen=True)
class RetrievalPlan:
    """通用检索闭环的只读查询计划。"""

    request_id: str
    subrequest_id: str | None = None
    steps: tuple[RetrievalStep, ...] = field(default_factory=tuple)
    dedupe_keys: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[object, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _require_text(self.request_id, "request_id")
        _require_optional_text(self.subrequest_id, "subrequest_id")
        for step in self.steps:
            if not isinstance(step, RetrievalStep):
                raise ValueError("steps must contain only RetrievalStep instances")


@dataclass(frozen=True)
class PlanWarning:
    """检索规划阶段的结构化 warning，携带稳定原因码。"""

    reason_code: ReasonCode | str
    message: str
    requirement_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reason_code",
            _coerce_enum(ReasonCode, self.reason_code, "reason_code"),
        )
        _require_text(self.message, "message")
        _require_optional_text(self.requirement_id, "requirement_id")


@dataclass(frozen=True)
class SourceCallRecord:
    """一次受控 facade 只读调用的审计记录。"""

    source_call_id: str
    step_id: str
    facade_method: str
    status: RetrievalStatus | str
    reason_code: ReasonCode | str | None = None
    result_count: int | None = None
    warning: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.source_call_id, "source_call_id")
        _require_text(self.step_id, "step_id")
        _require_text(self.facade_method, "facade_method")
        object.__setattr__(self, "status", _coerce_enum(RetrievalStatus, self.status, "status"))
        if self.reason_code is not None:
            object.__setattr__(
                self,
                "reason_code",
                _coerce_enum(ReasonCode, self.reason_code, "reason_code"),
            )
        _require_non_negative_int(self.result_count, "result_count")
        _require_optional_text(self.warning, "warning")


@dataclass(frozen=True)
class EvidenceRef:
    """统一证据引用，保留稳定业务 ID、bbox、识别与 payload 引用。"""

    project_id: str | None = None
    drawing_set_id: str | None = None
    page_id: str | None = None
    block_id: str | None = None
    element_id: str | None = None
    bbox: Mapping[str, float] | None = None
    recognition_run_id: str | None = None
    payload_ref: str | None = None
    rule_version: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "project_id",
            "drawing_set_id",
            "page_id",
            "block_id",
            "element_id",
            "recognition_run_id",
            "payload_ref",
            "rule_version",
        ):
            _require_optional_text(getattr(self, field_name), field_name)
        if self.bbox is not None:
            if not isinstance(self.bbox, Mapping):
                raise ValueError("bbox must be a mapping or None")
            object.__setattr__(self, "bbox", MappingProxyType(dict(self.bbox)))


@dataclass(frozen=True)
class EvidenceItem:
    """统一证据载体，fact_kind 在归一化后不允许被提升或篡改。"""

    evidence_id: str
    fact_kind: FactKind | str
    status: str | None = None
    scope: AssistantScope | None = None
    value: Any = None
    confidence: float | None = None
    source_system: str | None = None
    source_call_id: str | None = None
    recognition_run_id: str | None = None
    payload_ref: str | None = None
    model_profile: str | None = None
    prompt_version: str | None = None
    rule_version: str | None = None
    created_at_or_version: str | None = None
    evidence_refs: tuple[EvidenceRef, ...] = field(default_factory=tuple)
    evidence_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.evidence_id, "evidence_id")
        object.__setattr__(self, "fact_kind", _coerce_enum(FactKind, self.fact_kind, "fact_kind"))
        _require_optional_text(self.status, "status")
        if self.scope is not None and not isinstance(self.scope, AssistantScope):
            raise ValueError("scope must be an AssistantScope or None")
        if self.confidence is not None:
            if not isinstance(self.confidence, (int, float)) or isinstance(self.confidence, bool):
                raise ValueError("confidence must be numeric or None")
            if not 0.0 <= self.confidence <= 1.0:
                raise ValueError("confidence must be between 0 and 1")
        for field_name in (
            "source_system",
            "source_call_id",
            "recognition_run_id",
            "payload_ref",
            "model_profile",
            "prompt_version",
            "rule_version",
            "created_at_or_version",
        ):
            _require_optional_text(getattr(self, field_name), field_name)
        for ref in self.evidence_refs:
            if not isinstance(ref, EvidenceRef):
                raise ValueError("evidence_refs must contain only EvidenceRef instances")
        if not isinstance(self.evidence_metadata, Mapping):
            raise ValueError("evidence_metadata must be a mapping")
        for key in self.evidence_metadata:
            if not isinstance(key, str) or not key.strip():
                raise ValueError("evidence_metadata keys must be non-empty strings")
        object.__setattr__(
            self,
            "evidence_metadata",
            MappingProxyType(dict(self.evidence_metadata)),
        )


@dataclass(frozen=True)
class MissingEvidence:
    """检索闭环中的缺失证据条目，原因码保持稳定。"""

    requirement_id: str
    evidence_type: EvidenceType | str
    target_scope: AssistantScope | None = None
    reason_code: ReasonCode | str = ReasonCode.EMPTY_RESULT
    message: str = ""

    def __post_init__(self) -> None:
        _require_text(self.requirement_id, "requirement_id")
        object.__setattr__(
            self,
            "evidence_type",
            _coerce_enum(EvidenceType, self.evidence_type, "evidence_type"),
        )
        if self.target_scope is not None and not isinstance(self.target_scope, AssistantScope):
            raise ValueError("target_scope must be an AssistantScope or None")
        object.__setattr__(
            self,
            "reason_code",
            _coerce_enum(ReasonCode, self.reason_code, "reason_code"),
        )
        _require_text(self.message, "message")


def _require_bucket_kind(
    items: tuple[EvidenceItem, ...],
    bucket_name: str,
    allowed_kinds: frozenset[FactKind],
) -> None:
    """校验证据桶与 fact_kind 一致，防止候选/解释被放入错误层级。"""

    for item in items:
        if not isinstance(item, EvidenceItem):
            raise ValueError(f"{bucket_name} must contain only EvidenceItem instances")
        if item.fact_kind not in allowed_kinds:
            raise ValueError(
                f"{bucket_name} cannot contain {item.fact_kind.value} evidence"
            )


@dataclass(frozen=True)
class RetrievalBundle:
    """通用检索闭环的统一输出，按事实层级分组。"""

    request_id: str
    subrequest_id: str | None = None
    scope: AssistantScope | None = None
    source_facts: tuple[EvidenceItem, ...] = field(default_factory=tuple)
    derived_relations: tuple[EvidenceItem, ...] = field(default_factory=tuple)
    semantic_observations: tuple[EvidenceItem, ...] = field(default_factory=tuple)
    semantic_interpretations: tuple[EvidenceItem, ...] = field(default_factory=tuple)
    candidate_relations: tuple[EvidenceItem, ...] = field(default_factory=tuple)
    formal_relations: tuple[EvidenceItem, ...] = field(default_factory=tuple)
    diagnostics: tuple[EvidenceItem, ...] = field(default_factory=tuple)
    missing_evidence: tuple[MissingEvidence, ...] = field(default_factory=tuple)
    warnings: tuple[object, ...] = field(default_factory=tuple)
    source_calls: tuple[SourceCallRecord, ...] = field(default_factory=tuple)
    status: RetrievalStatus | str = RetrievalStatus.OK

    def __post_init__(self) -> None:
        _require_text(self.request_id, "request_id")
        _require_optional_text(self.subrequest_id, "subrequest_id")
        if self.scope is not None and not isinstance(self.scope, AssistantScope):
            raise ValueError("scope must be an AssistantScope or None")
        _require_bucket_kind(self.source_facts, "source_facts", frozenset({FactKind.SOURCE_FACT}))
        _require_bucket_kind(
            self.derived_relations,
            "derived_relations",
            frozenset({FactKind.DERIVED_RELATION}),
        )
        _require_bucket_kind(
            self.semantic_observations,
            "semantic_observations",
            frozenset({FactKind.SEMANTIC_OBSERVATION}),
        )
        _require_bucket_kind(
            self.semantic_interpretations,
            "semantic_interpretations",
            frozenset({FactKind.SEMANTIC_INTERPRETATION}),
        )
        _require_bucket_kind(
            self.candidate_relations,
            "candidate_relations",
            frozenset({FactKind.CANDIDATE_RELATION}),
        )
        _require_bucket_kind(
            self.formal_relations,
            "formal_relations",
            frozenset({FactKind.FORMAL_RELATION}),
        )
        _require_bucket_kind(
            self.diagnostics,
            "diagnostics",
            frozenset({FactKind.DIAGNOSTIC, FactKind.UNSUPPORTED}),
        )
        for missing in self.missing_evidence:
            if not isinstance(missing, MissingEvidence):
                raise ValueError("missing_evidence must contain only MissingEvidence instances")
        for call in self.source_calls:
            if not isinstance(call, SourceCallRecord):
                raise ValueError("source_calls must contain only SourceCallRecord instances")
        object.__setattr__(self, "status", _coerce_enum(RetrievalStatus, self.status, "status"))


@dataclass(frozen=True)
class RawRetrievalResult:
    """检索执行的原始结果：step_id 到 facade 返回对象的稳定映射。"""

    results: Mapping[str, Any] = field(default_factory=dict)
    truncated_step_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.results, Mapping):
            raise ValueError("results must be a mapping")
        for key in self.results:
            _require_text(key, "results key")
        object.__setattr__(self, "results", MappingProxyType(dict(self.results)))
        if not isinstance(self.truncated_step_ids, tuple) or not all(
            isinstance(item, str) for item in self.truncated_step_ids
        ):
            raise ValueError("truncated_step_ids must be a tuple of strings")


@dataclass(frozen=True)
class Claim:
    """答案中的一个可追溯声明，只承载数据，不执行任何写回或外部调用。"""

    claim_id: str
    statement: str
    claim_type: str | None = None
    status: str | None = None
    confidence: float | None = None
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    fact_kinds: tuple[FactKind | str, ...] = field(default_factory=tuple)
    scope: AssistantScope | None = None
    qualifiers: tuple[str, ...] = field(default_factory=tuple)
    subrequest_id: str | None = None
    reason_codes: tuple[ReasonCode | str, ...] = field(default_factory=tuple)
    citation_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _require_text(self.claim_id, "claim_id")
        _require_text(self.statement, "statement")
        _require_optional_text(self.claim_type, "claim_type")
        _require_optional_text(self.status, "status")
        if self.confidence is not None:
            if not isinstance(self.confidence, (int, float)) or isinstance(self.confidence, bool):
                raise ValueError("confidence must be numeric or None")
            if not 0.0 <= self.confidence <= 1.0:
                raise ValueError("confidence must be between 0 and 1")
        if self.scope is not None and not isinstance(self.scope, AssistantScope):
            raise ValueError("scope must be an AssistantScope or None")
        object.__setattr__(
            self,
            "fact_kinds",
            tuple(_coerce_enum(FactKind, item, "fact_kinds") for item in self.fact_kinds),
        )
        _require_optional_text(self.subrequest_id, "subrequest_id")
        if not isinstance(self.reason_codes, tuple):
            raise ValueError("reason_codes must be a tuple")
        object.__setattr__(
            self,
            "reason_codes",
            tuple(_coerce_enum(ReasonCode, code, "reason_codes") for code in self.reason_codes),
        )
        object.__setattr__(
            self,
            "citation_ids",
            _require_text_tuple(self.citation_ids, "citation_ids"),
        )


@dataclass(frozen=True)
class Citation:
    """答案引用来源，保留稳定 ID、bbox 与识别引用。"""

    citation_id: str | None = None
    evidence_id: str | None = None
    claim_ids: tuple[str, ...] = field(default_factory=tuple)
    project_id: str | None = None
    drawing_set_id: str | None = None
    page_id: str | None = None
    block_id: str | None = None
    element_id: str | None = None
    bbox: Mapping[str, float] | None = None
    observation_id: str | None = None
    interpretation_id: str | None = None
    candidate_group_id: str | None = None
    recognition_run_id: str | None = None
    payload_ref: str | None = None
    rule_version: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "citation_id",
            "evidence_id",
            "project_id",
            "drawing_set_id",
            "page_id",
            "block_id",
            "element_id",
            "observation_id",
            "interpretation_id",
            "candidate_group_id",
            "recognition_run_id",
            "payload_ref",
            "rule_version",
        ):
            _require_optional_text(getattr(self, field_name), field_name)
        object.__setattr__(
            self,
            "claim_ids",
            _require_text_tuple(self.claim_ids, "claim_ids"),
        )
        if self.bbox is not None:
            if not isinstance(self.bbox, Mapping):
                raise ValueError("bbox must be a mapping or None")
            object.__setattr__(self, "bbox", MappingProxyType(dict(self.bbox)))


@dataclass(frozen=True)
class Subanswer:
    """多意图聚合中单个子请求的稳定答案片段，只承载数据，不执行编排。"""

    subrequest_id: str
    question_type: str
    scope: AssistantScope | None = None
    status: AnswerStatus | str = AnswerStatus.UNSUPPORTED
    claim_ids: tuple[str, ...] = field(default_factory=tuple)
    citation_ids: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[object, ...] = field(default_factory=tuple)
    unsupported_parts: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _require_text(self.subrequest_id, "subrequest_id")
        _require_text(self.question_type, "question_type")
        if self.scope is not None and not isinstance(self.scope, AssistantScope):
            raise ValueError("scope must be an AssistantScope or None")
        object.__setattr__(
            self,
            "status",
            _coerce_enum(AnswerStatus, self.status, "status"),
        )
        object.__setattr__(
            self,
            "claim_ids",
            _require_text_tuple(self.claim_ids, "claim_ids"),
        )
        object.__setattr__(
            self,
            "citation_ids",
            _require_text_tuple(self.citation_ids, "citation_ids"),
        )
        if not isinstance(self.warnings, tuple):
            raise ValueError("warnings must be a tuple")
        object.__setattr__(
            self,
            "unsupported_parts",
            _require_text_tuple(self.unsupported_parts, "unsupported_parts"),
        )


@dataclass(frozen=True)
class MachineAnswer:
    """权威机器答案，字段顺序固定，只由确定性代码构造。"""

    answer_contract_version: str
    request_id: str
    question_type: str
    scope: AssistantScope | None = None
    status: AnswerStatus | str = AnswerStatus.UNSUPPORTED
    subanswers: tuple[Subanswer, ...] = field(default_factory=tuple)
    claims: tuple[Claim, ...] = field(default_factory=tuple)
    citations: tuple[Citation, ...] = field(default_factory=tuple)
    warnings: tuple[object, ...] = field(default_factory=tuple)
    unsupported_parts: tuple[str, ...] = field(default_factory=tuple)
    recognition_run_ids: tuple[str, ...] = field(default_factory=tuple)
    follow_up_actions: tuple[str, ...] = field(default_factory=tuple)
    reason_codes: tuple[ReasonCode | str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _require_text(self.answer_contract_version, "answer_contract_version")
        _require_text(self.request_id, "request_id")
        _require_text(self.question_type, "question_type")
        if self.scope is not None and not isinstance(self.scope, AssistantScope):
            raise ValueError("scope must be an AssistantScope or None")
        object.__setattr__(
            self,
            "status",
            _coerce_enum(AnswerStatus, self.status, "status"),
        )
        for subanswer in self.subanswers:
            if not isinstance(subanswer, Subanswer):
                raise ValueError("subanswers must contain only Subanswer instances")
        for claim in self.claims:
            if not isinstance(claim, Claim):
                raise ValueError("claims must contain only Claim instances")
        for citation in self.citations:
            if not isinstance(citation, Citation):
                raise ValueError("citations must contain only Citation instances")
        if not isinstance(self.warnings, tuple):
            raise ValueError("warnings must be a tuple")
        object.__setattr__(
            self,
            "unsupported_parts",
            _require_text_tuple(self.unsupported_parts, "unsupported_parts"),
        )
        object.__setattr__(
            self,
            "recognition_run_ids",
            _require_text_tuple(self.recognition_run_ids, "recognition_run_ids"),
        )
        object.__setattr__(
            self,
            "follow_up_actions",
            _require_text_tuple(self.follow_up_actions, "follow_up_actions"),
        )
        if not isinstance(self.reason_codes, tuple):
            raise ValueError("reason_codes must be a tuple")
        object.__setattr__(
            self,
            "reason_codes",
            tuple(_coerce_enum(ReasonCode, code, "reason_codes") for code in self.reason_codes),
        )


@dataclass(frozen=True)
class AnswerPackage:
    """完整产品答案容器，为后续答案生成预留，不在此处生成答案。"""

    request_id: str
    question_type: str
    scope: AssistantScope | None = None
    status: str | None = None
    machine_answer: Any = None
    text_answer: str | None = None
    claims: tuple[Claim, ...] = field(default_factory=tuple)
    citations: tuple[Citation, ...] = field(default_factory=tuple)
    warnings: tuple[object, ...] = field(default_factory=tuple)
    unsupported_parts: tuple[str, ...] = field(default_factory=tuple)
    recognition_run_ids: tuple[str, ...] = field(default_factory=tuple)
    follow_up_actions: tuple[str, ...] = field(default_factory=tuple)
    answer_contract_version: str = ANSWER_CONTRACT_VERSION
    subanswers: tuple[Subanswer, ...] = field(default_factory=tuple)
    reason_codes: tuple[ReasonCode | str, ...] = field(default_factory=tuple)
    render_mode: TextRenderMode | str = TextRenderMode.TEMPLATE

    def __post_init__(self) -> None:
        _require_text(self.request_id, "request_id")
        _require_text(self.question_type, "question_type")
        if self.scope is not None and not isinstance(self.scope, AssistantScope):
            raise ValueError("scope must be an AssistantScope or None")
        _require_optional_text(self.status, "status")
        _require_optional_text(self.text_answer, "text_answer")
        for claim in self.claims:
            if not isinstance(claim, Claim):
                raise ValueError("claims must contain only Claim instances")
        for citation in self.citations:
            if not isinstance(citation, Citation):
                raise ValueError("citations must contain only Citation instances")
        _require_text(self.answer_contract_version, "answer_contract_version")
        for subanswer in self.subanswers:
            if not isinstance(subanswer, Subanswer):
                raise ValueError("subanswers must contain only Subanswer instances")
        if not isinstance(self.reason_codes, tuple):
            raise ValueError("reason_codes must be a tuple")
        object.__setattr__(
            self,
            "reason_codes",
            tuple(_coerce_enum(ReasonCode, code, "reason_codes") for code in self.reason_codes),
        )
        object.__setattr__(
            self,
            "render_mode",
            _coerce_enum(TextRenderMode, self.render_mode, "render_mode"),
        )


@dataclass(frozen=True)
class TraceRecord:
    """产品请求的追溯记录，只承载数据，不执行任何写回。"""

    request_id: str
    question: str | None = None
    question_type: str | None = None
    scope: AssistantScope | None = None
    module_events: tuple[object, ...] = field(default_factory=tuple)
    retrieval_calls: tuple[SourceCallRecord, ...] = field(default_factory=tuple)
    recognition_run_ids: tuple[str, ...] = field(default_factory=tuple)
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    claim_ids: tuple[str, ...] = field(default_factory=tuple)
    answer_status: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.request_id, "request_id")
        _require_optional_text(self.question, "question")
        _require_optional_text(self.question_type, "question_type")
        if self.scope is not None and not isinstance(self.scope, AssistantScope):
            raise ValueError("scope must be an AssistantScope or None")
        _require_optional_text(self.answer_status, "answer_status")
        for call in self.retrieval_calls:
            if not isinstance(call, SourceCallRecord):
                raise ValueError("retrieval_calls must contain only SourceCallRecord instances")


@dataclass(frozen=True)
class FeedbackEvent:
    """用户反馈事件，只承载数据；反馈写回逻辑不在本模块。"""

    feedback_id: str
    request_id: str
    claim_id: str | None = None
    action: str | None = None
    reason: str | None = None
    correction: str | None = None
    user_id: str | None = None
    created_at: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.feedback_id, "feedback_id")
        _require_text(self.request_id, "request_id")
        for field_name in ("claim_id", "action", "reason", "correction", "user_id", "created_at"):
            _require_optional_text(getattr(self, field_name), field_name)


@dataclass(frozen=True)
class AssistantSubrequest:
    """问题理解后拆分出的单个子请求，携带自己的 scope 与证据需求。"""

    subrequest_id: str
    question_type: str
    scope: AssistantScope | None = None
    required_evidence: tuple[EvidenceRequirement, ...] = field(default_factory=tuple)
    answer_requirements: tuple[object, ...] = field(default_factory=tuple)
    confidence: float | None = None
    ambiguities: tuple[str, ...] = field(default_factory=tuple)
    unsupported_parts: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _require_text(self.subrequest_id, "subrequest_id")
        _require_text(self.question_type, "question_type")
        if self.scope is not None and not isinstance(self.scope, AssistantScope):
            raise ValueError("scope must be an AssistantScope or None")
        if self.confidence is not None and not isinstance(self.confidence, (int, float)):
            raise ValueError("confidence must be numeric or None")


@dataclass(frozen=True)
class QuestionUnderstandingResult:
    """问题理解结果，供检索规划稳定消费问题类型、scope 和证据需求。"""

    request_id: str
    question_type: str
    subrequest_id: str | None = None
    scope: AssistantScope | None = None
    required_evidence: tuple[EvidenceRequirement, ...] = field(default_factory=tuple)
    subrequests: tuple[AssistantSubrequest, ...] = field(default_factory=tuple)
    answer_requirements: tuple[object, ...] = field(default_factory=tuple)
    confidence: float | None = None
    ambiguities: tuple[str, ...] = field(default_factory=tuple)
    unsupported_parts: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _require_text(self.request_id, "request_id")
        _require_text(self.question_type, "question_type")
        _require_optional_text(self.subrequest_id, "subrequest_id")
        if self.scope is not None and not isinstance(self.scope, AssistantScope):
            raise ValueError("scope must be an AssistantScope or None")
        if self.confidence is not None and not isinstance(self.confidence, (int, float)):
            raise ValueError("confidence must be numeric or None")


@dataclass(frozen=True)
class RecognitionFailure:
    """只读识别失败记录，不保存 traceback、provider 原始响应或凭据。"""

    page_id: str | None = None
    target_ids: tuple[str, ...] = field(default_factory=tuple)
    reason_code: ReasonCode | str = ReasonCode.INTERNAL_ERROR
    message: str = ""

    def __post_init__(self) -> None:
        _require_optional_text(self.page_id, "page_id")
        object.__setattr__(
            self,
            "target_ids",
            _require_text_tuple(self.target_ids, "target_ids"),
        )
        object.__setattr__(
            self,
            "reason_code",
            _coerce_enum(ReasonCode, self.reason_code, "reason_code"),
        )
        if not isinstance(self.message, str):
            raise ValueError("message must be a string")


@dataclass(frozen=True)
class AnswerGenerationPolicy:
    """06 的表现层与资源策略，不包含写回或事实等级/状态覆写字段。"""

    enable_constrained_text: bool = False
    max_claims: int | None = None
    max_citations: int | None = None
    max_text_length: int | None = None
    text_generation_timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.enable_constrained_text, bool):
            raise ValueError("enable_constrained_text must be a boolean")
        for field_name in ("max_claims", "max_citations", "max_text_length"):
            _require_positive_int(getattr(self, field_name), field_name)
        _require_non_negative_number(
            self.text_generation_timeout_seconds,
            "text_generation_timeout_seconds",
        )


@dataclass(frozen=True)
class AnswerGenerationRequest:
    """06 答案生成的输入，`evidence_bundle=None` 仅允许用于终止态。"""

    assistant_request: AssistantRequest
    question_result: QuestionUnderstandingResult
    evidence_bundle: EvidenceBundle | None = None
    subrequest_id: str | None = None
    stage_warnings: tuple[object, ...] = field(default_factory=tuple)
    recognition_failures: tuple[RecognitionFailure, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.assistant_request, AssistantRequest):
            raise ValueError("assistant_request must be an AssistantRequest")
        if not isinstance(self.question_result, QuestionUnderstandingResult):
            raise ValueError("question_result must be a QuestionUnderstandingResult")
        _require_optional_text(self.subrequest_id, "subrequest_id")
        if not isinstance(self.stage_warnings, tuple):
            raise ValueError("stage_warnings must be a tuple")
        for failure in self.recognition_failures:
            if not isinstance(failure, RecognitionFailure):
                raise ValueError("recognition_failures must contain only RecognitionFailure instances")


@dataclass(frozen=True)
class AssistantExecutionPolicy:
    """07 只读总编排的执行策略，组合检索/识别策略与资源上限，不含写回授权。"""

    retrieval_policy: RetrievalPolicy = field(default_factory=RetrievalPolicy)
    recognition_policy: RecognitionPolicy = field(default_factory=RecognitionPolicy)
    enable_constrained_text: bool = False
    max_subrequests: int | None = None
    max_page_groups: int | None = None
    max_claims: int | None = None
    max_citations: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.retrieval_policy, RetrievalPolicy):
            raise ValueError("retrieval_policy must be a RetrievalPolicy")
        if not isinstance(self.recognition_policy, RecognitionPolicy):
            raise ValueError("recognition_policy must be a RecognitionPolicy")
        if not isinstance(self.enable_constrained_text, bool):
            raise ValueError("enable_constrained_text must be a boolean")
        for field_name in (
            "max_subrequests",
            "max_page_groups",
            "max_claims",
            "max_citations",
        ):
            _require_positive_int(getattr(self, field_name), field_name)


@dataclass(frozen=True)
class ClarificationItem:
    """结构化澄清项：表达需要用户补充的信息，不触发检索或写回。"""

    clarification_id: str
    reason_code: ReasonCode | str
    target_field: str
    message: str
    allowed_scope_types: tuple[str, ...] = field(default_factory=tuple)
    candidate_refs: tuple[str, ...] = field(default_factory=tuple)
    required: bool = True

    def __post_init__(self) -> None:
        _require_text(self.clarification_id, "clarification_id")
        object.__setattr__(
            self,
            "reason_code",
            _coerce_enum(ReasonCode, self.reason_code, "reason_code"),
        )
        _require_text(self.target_field, "target_field")
        _require_text(self.message, "message")
        if not isinstance(self.allowed_scope_types, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.allowed_scope_types
        ):
            raise ValueError("allowed_scope_types must be a tuple of non-empty strings")
        if not isinstance(self.candidate_refs, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.candidate_refs
        ):
            raise ValueError("candidate_refs must be a tuple of non-empty strings")
        if not isinstance(self.required, bool):
            raise ValueError("required must be a boolean")


@dataclass(frozen=True)
class QuestionUnderstandingEvent:
    """问题理解阶段的轻量追溯事件，只承载数据，不持久化、不执行外部调用。"""

    event_id: str
    request_id: str
    stage: str
    question_type: str
    confidence: float | None = None
    reason_codes: tuple[ReasonCode | str, ...] = field(default_factory=tuple)
    details: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        _require_text(self.event_id, "event_id")
        _require_text(self.request_id, "request_id")
        _require_text(self.stage, "stage")
        question_type_value = (
            self.question_type.value if isinstance(self.question_type, Enum) else self.question_type
        )
        if not isinstance(question_type_value, str) or not question_type_value.strip():
            raise ValueError("question_type must be a non-empty string")
        object.__setattr__(self, "question_type", question_type_value)
        if self.confidence is not None:
            if not isinstance(self.confidence, (int, float)) or isinstance(self.confidence, bool):
                raise ValueError("confidence must be numeric or None")
            if not 0.0 <= self.confidence <= 1.0:
                raise ValueError("confidence must be between 0 and 1")
        if not isinstance(self.reason_codes, tuple):
            raise ValueError("reason_codes must be a tuple")
        object.__setattr__(
            self,
            "reason_codes",
            tuple(_coerce_enum(ReasonCode, code, "reason_codes") for code in self.reason_codes),
        )
        if self.details is not None:
            if not isinstance(self.details, Mapping):
                raise ValueError("details must be a mapping or None")
            object.__setattr__(self, "details", MappingProxyType(dict(self.details)))
