"""Evidence normalization (05) rules, keys, fingerprints and capabilities.

本模块把统一 ``EvidenceItem`` 规范化为 ``FusionEvidence``，并承载
comparison key、evidence family key、content fingerprint 和 claim
capability 的构造。模块是纯逻辑：不访问文件、网络、环境变量、数据库、
模型客户端或 adapter；规范化不覆盖 ``EvidenceItem.value``，不改变
``fact_kind``。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .assistant_evidence_fusion_models import (
    ClaimCapability,
    FusionEvidence,
    FusionMetadata,
)
from .assistant_models import AssistantScope, EvidenceItem, FactKind, ReasonCode
from .section_label_normalization import SectionLabelNormalizer
from .semantic_cache import EvidenceFamilyKeyInput, build_evidence_family_key

KNOWN_VALUE_SLOTS = frozenset(
    {
        "text",
        "bbox",
        "relation",
        "summary",
        "section_label",
        "identity",
    }
)


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _require_optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be None or a non-empty string")
    return value


def _coerce_fact_kind(value: FactKind | str) -> FactKind:
    if isinstance(value, FactKind):
        return value
    if isinstance(value, str):
        try:
            return FactKind(value)
        except ValueError as exc:
            raise ValueError(f"unknown fact kind: {value!r}") from exc
    raise ValueError("fact_kind must be a FactKind or its stable string")


def _canonical_json(payload: Mapping[str, Any]) -> str:
    """生成与字典键顺序、进程无关的规范 JSON。"""

    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _hash_payload(payload: Mapping[str, Any], prefix: str) -> str:
    canonical = _canonical_json(payload)
    return f"{prefix}:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


@dataclass(frozen=True)
class NormalizationRule:
    """一条按 (fact kind, task type, value slot) 唯一路由的规范化规则。"""

    fact_kind: FactKind | str
    task_type: str
    value_slot: str
    rule_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "fact_kind", _coerce_fact_kind(self.fact_kind))
        _require_text(self.task_type, "task_type")
        _require_text(self.value_slot, "value_slot")
        _require_text(self.rule_version, "rule_version")


class NormalizationRuleLookupError(LookupError):
    """没有匹配规范化规则时抛出的稳定失败。"""


class EvidenceNormalizationError(ValueError):
    """不可规范化证据时抛出的稳定失败，用于隔离而非猜测补值。"""


class NormalizationRuleRegistry:
    """不可变、版本化的规范化规则注册表。

    按 (fact kind, task type, value slot) 唯一路由；重复规则、空版本、
    未知 value slot 和可变注册表在构造时被拒绝。规则缺失时 lookup 返回
    稳定失败，不回退到通用字符串猜测。
    """

    def __init__(
        self,
        rules: Sequence[NormalizationRule] = (),
        registry_version: str = "normalize-v1",
    ) -> None:
        _require_text(registry_version, "registry_version")
        self._registry_version = registry_version
        indexed: dict[tuple[FactKind, str, str], NormalizationRule] = {}
        for rule in rules:
            if not isinstance(rule, NormalizationRule):
                raise TypeError("rules must contain only NormalizationRule instances")
            if rule.value_slot not in KNOWN_VALUE_SLOTS:
                raise ValueError(f"unknown value slot: {rule.value_slot!r}")
            key = (rule.fact_kind, rule.task_type, rule.value_slot)
            if key in indexed:
                raise ValueError(f"duplicate normalization rule for {key!r}")
            indexed[key] = rule
        self._rules = MappingProxyType(dict(indexed))

    @property
    def registry_version(self) -> str:
        return self._registry_version

    @property
    def rules(self) -> Mapping[tuple[FactKind, str, str], NormalizationRule]:
        return self._rules

    def lookup(
        self,
        fact_kind: FactKind | str,
        task_type: str,
        value_slot: str,
    ) -> NormalizationRule:
        """返回唯一匹配规则；无规则时抛出稳定失败。"""

        kind = _coerce_fact_kind(fact_kind)
        _require_text(task_type, "task_type")
        _require_text(value_slot, "value_slot")
        key = (kind, task_type, value_slot)
        rule = self._rules.get(key)
        if rule is None:
            raise NormalizationRuleLookupError(
                f"no normalization rule for fact_kind={kind.value} "
                f"task_type={task_type!r} value_slot={value_slot!r}"
            )
        return rule


class ComparisonKeyBuilder:
    """生成只用于可比证据分组的稳定 ``comparison_key``。

    key 由 scope、predicate/value slot 和 qualifiers 的规范 JSON 生成，
    不包含 confidence、secret、绝对路径、payload 或 provider 原文；
    qualifiers 会排序，因此相同输入跨顺序与进程产生相同结果。
    """

    def build(
        self,
        scope: AssistantScope | None,
        slot: str,
        qualifiers: Sequence[str] = (),
    ) -> str:
        """按 scope + slot + 排序后的 qualifiers 生成 comparison key。"""

        _require_text(slot, "slot")
        if not isinstance(qualifiers, (tuple, list)):
            raise ValueError("qualifiers must be a sequence of strings")
        for qualifier in qualifiers:
            _require_text(qualifier, "qualifier")
        payload = {
            "scope": _scope_payload(scope),
            "slot": slot,
            "qualifiers": tuple(sorted(qualifiers)),
        }
        return _hash_payload(payload, "comparison")


class EvidenceFamilyKeyBuilder:
    """生成只用于 lineage/stale 的稳定 ``evidence_family_key``。

    family key 只含稳定 target、task、output slot 和 normalization scope，
    不含 image/model/prompt/contract 版本维度，因此不能用于缓存命中。
    """

    def build(
        self,
        target_id: str,
        task_type: str,
        output_slot: str,
        normalization_scope: str = "default",
    ) -> str:
        return build_evidence_family_key(
            EvidenceFamilyKeyInput(
                target_id=target_id,
                task_type=task_type,
                output_slot=output_slot,
                normalization_scope=normalization_scope,
            )
        )


class ContentFingerprintBuilder:
    """为确定性去重生成版本化的内容 fingerprint。

    fingerprint 使用 fact kind、comparison key、normalized value 和可信
    source fingerprint 的规范 JSON；字典键顺序变化不改变结果。fingerprint
    不承担 cache hit 或 lineage 判定职责。
    """

    def build(
        self,
        fact_kind: FactKind | str,
        comparison_key: str,
        normalized_value: Any,
        source_fingerprint: str | None = None,
    ) -> str:
        kind = _coerce_fact_kind(fact_kind)
        _require_text(comparison_key, "comparison_key")
        _require_optional_text(source_fingerprint, "source_fingerprint")
        payload = {
            "fact_kind": kind.value,
            "comparison_key": comparison_key,
            "normalized_value": normalized_value,
            "source_fingerprint": source_fingerprint,
        }
        return _hash_payload(payload, "fingerprint")


_CAPABILITIES_BY_KIND: Mapping[FactKind, tuple[ClaimCapability, ...]] = MappingProxyType(
    {
        FactKind.SOURCE_FACT: (ClaimCapability.IDENTITY_AND_LOCATION,),
        FactKind.DERIVED_RELATION: (ClaimCapability.RULE_DERIVED_CONTEXT,),
        FactKind.SEMANTIC_OBSERVATION: (ClaimCapability.OBSERVED_TEXT_OR_SYMBOL,),
        FactKind.SEMANTIC_INTERPRETATION: (ClaimCapability.SEMANTIC_MEANING,),
        FactKind.CANDIDATE_RELATION: (ClaimCapability.POSSIBLE_RELATION,),
        FactKind.FORMAL_RELATION: (ClaimCapability.CONFIRMED_RELATION,),
        FactKind.DIAGNOSTIC: (ClaimCapability.RUNTIME_OR_CACHE_STATUS,),
    }
)


class ClaimCapabilityRegistry:
    """从可信 fact kind（及可选 schema field / relation type）推导 claim capability。

    只接受稳定的 ``FactKind`` 枚举，模型自由文本中的 capability 或
    fact kind 声明不作为权威输入；未注册 fact kind fail closed 为空能力。
    """

    def capabilities(
        self,
        fact_kind: FactKind | str,
        schema_field: str | None = None,
        relation_type: str | None = None,
    ) -> tuple[ClaimCapability, ...]:
        kind = _coerce_fact_kind(fact_kind)
        return _CAPABILITIES_BY_KIND.get(kind, ())


def _scope_payload(scope: AssistantScope | None) -> dict[str, str]:
    """把 AssistantScope 转成只含非空字段的规范字典，不包含任何 secret/路径。"""

    if scope is None:
        return {}
    return {
        field_name: value
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
        )
        if (value := getattr(scope, field_name, None)) is not None
    }


_VALUE_SLOT_BY_KIND: Mapping[FactKind, str] = MappingProxyType(
    {
        FactKind.SOURCE_FACT: "identity",
        FactKind.DERIVED_RELATION: "relation",
        FactKind.SEMANTIC_OBSERVATION: "text",
        FactKind.SEMANTIC_INTERPRETATION: "summary",
        FactKind.CANDIDATE_RELATION: "relation",
        FactKind.FORMAL_RELATION: "relation",
        FactKind.DIAGNOSTIC: "summary",
    }
)

_DEFAULT_TASK_TYPE_BY_KIND: Mapping[FactKind, str] = MappingProxyType(
    {
        FactKind.SOURCE_FACT: "source_fact",
        FactKind.DERIVED_RELATION: "relation_derivation",
        FactKind.SEMANTIC_OBSERVATION: "element_text_observation",
        FactKind.SEMANTIC_INTERPRETATION: "block_semantic_identification",
        FactKind.CANDIDATE_RELATION: "relation_evidence_extraction",
        FactKind.FORMAL_RELATION: "relation_formal",
        FactKind.DIAGNOSTIC: "diagnostic",
    }
)

_RELATION_KINDS = frozenset(
    {FactKind.CANDIDATE_RELATION, FactKind.DERIVED_RELATION, FactKind.FORMAL_RELATION}
)


@dataclass(frozen=True)
class FusionNormalizationContext:
    """规范化上下文，只承载稳定 target 映射与规范化 scope。"""

    normalization_scope: str = "default"


@dataclass(frozen=True)
class NormalizationResult:
    """一次规范化的输出，隔离不可规范化证据而不猜测补值。"""

    normalized: tuple[FusionEvidence, ...] = field(default_factory=tuple)
    isolated: tuple[EvidenceItem, ...] = field(default_factory=tuple)
    reason_codes: tuple[ReasonCode, ...] = field(default_factory=tuple)


class EvidenceNormalizer:
    """把 ``EvidenceItem`` 规范化为 ``FusionEvidence`` 的纯组件。

    文本规范化不覆盖 ``EvidenceItem.value``；bbox 统一为四坐标结构；
    关系固定为 subject/predicate/object 方向。不可规范化值被隔离并保留
    原 evidence ID。
    """

    def __init__(
        self,
        rule_registry: NormalizationRuleRegistry | None = None,
        capability_registry: ClaimCapabilityRegistry | None = None,
        comparison_key_builder: ComparisonKeyBuilder | None = None,
        family_key_builder: EvidenceFamilyKeyBuilder | None = None,
        fingerprint_builder: ContentFingerprintBuilder | None = None,
    ) -> None:
        self.rule_registry = rule_registry or NormalizationRuleRegistry()
        self.capability_registry = capability_registry or ClaimCapabilityRegistry()
        self.comparison_key_builder = comparison_key_builder or ComparisonKeyBuilder()
        self.family_key_builder = family_key_builder or EvidenceFamilyKeyBuilder()
        self.fingerprint_builder = fingerprint_builder or ContentFingerprintBuilder()

    def normalize(
        self,
        evidence: Sequence[EvidenceItem],
        context: FusionNormalizationContext | None = None,
    ) -> NormalizationResult:
        context = context or FusionNormalizationContext()
        normalized: list[FusionEvidence] = []
        isolated: list[EvidenceItem] = []
        for item in evidence:
            try:
                normalized.append(self._normalize_one(item, context))
            except (NormalizationRuleLookupError, EvidenceNormalizationError):
                isolated.append(item)
        reasons = (
            (ReasonCode.EVIDENCE_NORMALIZATION_FAILED,)
            if isolated
            else ()
        )
        return NormalizationResult(
            normalized=tuple(normalized),
            isolated=tuple(isolated),
            reason_codes=reasons,
        )

    def _normalize_one(
        self,
        item: EvidenceItem,
        context: FusionNormalizationContext,
    ) -> FusionEvidence:
        value_slot = _VALUE_SLOT_BY_KIND.get(item.fact_kind)
        if value_slot is None:
            raise NormalizationRuleLookupError(
                f"no value slot for fact_kind={item.fact_kind.value}"
            )
        task_type = _task_type(item)
        rule = self.rule_registry.lookup(item.fact_kind, task_type, value_slot)
        normalized_value = _normalize_value(item.fact_kind, item.value)
        if normalized_value is None:
            raise EvidenceNormalizationError(
                f"un-normalizable value for evidence {item.evidence_id!r}"
            )
        qualifiers = _comparison_qualifiers(item.fact_kind, normalized_value)
        comparison_key = self.comparison_key_builder.build(item.scope, value_slot, qualifiers)
        target_ref = _scope_target_ref(item.scope) or _value_target_ref(
            item.fact_kind, item.value
        )
        family_key = (
            self.family_key_builder.build(
                target_ref, task_type, value_slot, context.normalization_scope
            )
            if target_ref is not None
            else None
        )
        fingerprint = self.fingerprint_builder.build(
            item.fact_kind,
            comparison_key,
            normalized_value,
        )
        capabilities = self.capability_registry.capabilities(item.fact_kind)
        metadata = FusionMetadata(
            normalized_value=normalized_value,
            comparison_key=comparison_key,
            evidence_family_key=family_key,
            content_fingerprint=fingerprint,
            claim_capabilities=capabilities,
            cache_key=_metadata_text(item, "cache_key"),
            task_type=task_type,
            freshness_result=None,
            normalization_rule_version=rule.rule_version,
            is_current_for_request=False,
        )
        return FusionEvidence(
            item=item,
            metadata=metadata,
            provenance=(),
            original_evidence_ids=(item.evidence_id,),
        )


def _task_type(item: EvidenceItem) -> str:
    value = _metadata_text(item, "task_type")
    if value is not None:
        return value
    return _DEFAULT_TASK_TYPE_BY_KIND.get(item.fact_kind, "default")


def _metadata_text(item: EvidenceItem, key: str) -> str | None:
    metadata = item.evidence_metadata
    if not isinstance(metadata, Mapping):
        return None
    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _scope_target_ref(scope: AssistantScope | None) -> str | None:
    if scope is None:
        return None
    for field_name in ("element_id", "block_id", "table_id", "cross_section_id", "page_id"):
        value = getattr(scope, field_name, None)
        if value is not None:
            return value
    return None


def _value_target_ref(fact_kind: FactKind, value: Any) -> str | None:
    """关系证据从 source/subject 侧推导稳定的 family target 引用。"""

    if fact_kind in _RELATION_KINDS and isinstance(value, Mapping):
        target = value.get("source_target_id") or value.get("subject")
        if isinstance(target, str) and target.strip():
            return target
    return None


def _normalize_value(fact_kind: FactKind, value: Any) -> Any:
    if fact_kind in _RELATION_KINDS:
        return _normalize_relation(value)
    if fact_kind is FactKind.SEMANTIC_OBSERVATION:
        return _normalize_observation(value)
    if fact_kind is FactKind.SEMANTIC_INTERPRETATION:
        return _normalize_interpretation(value)
    return _canonicalize(value)


def _comparison_qualifiers(fact_kind: FactKind, normalized_value: Any) -> tuple[str, ...]:
    """关系证据把方向（subject + predicate）作为比较限定条件。

    objects 属于值而非键：同 subject+predicate、不同 objects 的关系应落在
    同一比较组以检出冲突，而反向关系（不同 subject）不落入同一组。
    """

    if fact_kind in _RELATION_KINDS and isinstance(normalized_value, Mapping):
        subject = normalized_value.get("subject")
        predicate = normalized_value.get("predicate")
        return (
            f"subject:{subject}",
            f"predicate:{predicate}",
        )
    return ()


def _normalize_relation(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    subject = value.get("subject", value.get("source_target_id"))
    predicate = value.get("predicate", value.get("relation_type"))
    objects = value.get("objects", value.get("supporting_target_ids", ()))
    if subject is None or predicate is None:
        return None
    if isinstance(objects, (list, tuple)):
        object_tuple = tuple(objects)
    else:
        object_tuple = (objects,)
    return {"subject": subject, "predicate": predicate, "objects": object_tuple}


def _normalize_observation(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        text = _normalize_text(value)
        return {"text": text} if text is not None else None
    if not isinstance(value, Mapping):
        return None
    result: dict[str, Any] = {}
    raw = value.get("raw_text", value.get("text"))
    if raw is not None:
        text = _normalize_text(str(raw))
        if text is not None:
            result["text"] = text
    bbox = value.get("bbox")
    if bbox is not None:
        normalized_bbox = _normalize_bbox(bbox)
        if normalized_bbox is not None:
            result["bbox"] = normalized_bbox
    return result or None


def _normalize_interpretation(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        summary = _normalize_text(value)
        return {"summary": summary} if summary is not None else None
    if not isinstance(value, Mapping):
        return None
    summary = value.get("summary")
    if summary is None:
        return None
    return {"summary": str(summary)}


def _canonicalize(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _canonicalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    return None


def _normalize_text(value: str) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if text else None


def _normalize_bbox(value: Any) -> dict[str, float] | None:
    if isinstance(value, Mapping):
        if all(key in value for key in ("x_min", "y_min", "x_max", "y_max")):
            return {
                "x_min": float(value["x_min"]),
                "y_min": float(value["y_min"]),
                "x_max": float(value["x_max"]),
                "y_max": float(value["y_max"]),
            }
        return None
    if hasattr(value, "x_min") and hasattr(value, "y_min"):
        return {
            "x_min": float(value.x_min),
            "y_min": float(value.y_min),
            "x_max": float(value.x_max),
            "y_max": float(value.y_max),
        }
    return None


class SectionLabelValueNormalizer:
    """复用现有 ``SectionLabelNormalizer`` 规范化断面标签对。

    不新增第二套断面符号规则；保留原始标签与符号体系；未经 alias rule
    不自动合并 ``I-I``、``Ⅰ-Ⅰ`` 与 ``1-1``。
    """

    def __init__(self, normalizer: SectionLabelNormalizer | None = None) -> None:
        self._normalizer = normalizer or SectionLabelNormalizer()

    def normalize(self, start_label: str, end_label: str) -> dict[str, Any] | None:
        result = self._normalizer.normalize_pair(start_label, end_label)
        return {
            "start_label": start_label,
            "end_label": end_label,
            "symbol_system": result.symbol_system.value,
            "normalized_key": result.normalized_key,
            "deterministic": result.deterministic,
            "reason": result.reason,
        }
