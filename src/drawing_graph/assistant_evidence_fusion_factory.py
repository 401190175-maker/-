"""Factory for assembling the evidence fusion (05) service without side effects."""

from __future__ import annotations

from .assistant_evidence_fusion import EvidenceFusionService
from .assistant_evidence_lineage import StalePolicy, StalePolicyRegistry, EvidenceLineageResolver
from .assistant_evidence_normalization import (
    ClaimCapabilityRegistry,
    EvidenceNormalizer,
    NormalizationRule,
    NormalizationRuleRegistry,
)
from .assistant_models import FactKind


def _default_stale_policy_registry() -> StalePolicyRegistry:
    return StalePolicyRegistry(
        policies=(
            StalePolicy(fact_kind=FactKind.SEMANTIC_OBSERVATION, policy_id="obs-stale", version="v1"),
            StalePolicy(fact_kind=FactKind.SEMANTIC_INTERPRETATION, policy_id="interp-stale", version="v1"),
        )
    )


def _default_normalization_registry() -> NormalizationRuleRegistry:
    """生产默认规范化规则表：覆盖七类事实的默认 task type 与 value slot。

    05 融合层的真实链路必须能规范化检索到的证据，否则所有证据都会被
    隔离，答案层只能返回 partial（实测即为此现象）。默认规则与
    ``assistant_evidence_normalization`` 的 ``_DEFAULT_TASK_TYPE_BY_KIND`` /
    ``_VALUE_SLOT_BY_KIND`` 保持一致；调用方仍可注入自定义注册表覆盖。
    """

    return NormalizationRuleRegistry(
        rules=(
            NormalizationRule(
                fact_kind=FactKind.SOURCE_FACT,
                task_type="source_fact",
                value_slot="identity",
                rule_version="normalize-v1",
            ),
            NormalizationRule(
                fact_kind=FactKind.DERIVED_RELATION,
                task_type="relation_derivation",
                value_slot="relation",
                rule_version="normalize-v1",
            ),
            NormalizationRule(
                fact_kind=FactKind.SEMANTIC_OBSERVATION,
                task_type="element_text_observation",
                value_slot="text",
                rule_version="normalize-v1",
            ),
            NormalizationRule(
                fact_kind=FactKind.SEMANTIC_INTERPRETATION,
                task_type="block_semantic_identification",
                value_slot="summary",
                rule_version="normalize-v1",
            ),
            NormalizationRule(
                fact_kind=FactKind.CANDIDATE_RELATION,
                task_type="relation_evidence_extraction",
                value_slot="relation",
                rule_version="normalize-v1",
            ),
            NormalizationRule(
                fact_kind=FactKind.FORMAL_RELATION,
                task_type="relation_formal",
                value_slot="relation",
                rule_version="normalize-v1",
            ),
            NormalizationRule(
                fact_kind=FactKind.DIAGNOSTIC,
                task_type="diagnostic",
                value_slot="summary",
                rule_version="normalize-v1",
            ),
        )
    )


def create_evidence_fusion_service(
    controlled_write_port: object | None = None,
    normalization_registry: NormalizationRuleRegistry | None = None,
    capability_registry: ClaimCapabilityRegistry | None = None,
    stale_policy_registry: StalePolicyRegistry | None = None,
) -> EvidenceFusionService:
    """装配默认纯融合服务，默认 ``controlled_write_port=None``。

    默认规范化规则表覆盖七类事实；未注入 ``normalization_registry`` 时使用
    生产默认规则，避免真实链路证据被全部隔离。import/创建不连接数据库、
    不读取 secret、不发网络请求、不扫描数据目录。
    """

    normalizer = EvidenceNormalizer(
        rule_registry=normalization_registry or _default_normalization_registry(),
        capability_registry=capability_registry or ClaimCapabilityRegistry(),
    )
    lineage_resolver = EvidenceLineageResolver(
        stale_policy_registry=stale_policy_registry or _default_stale_policy_registry()
    )
    return EvidenceFusionService(
        normalizer=normalizer,
        lineage_resolver=lineage_resolver,
        controlled_write_port=controlled_write_port,
    )


__all__ = ("create_evidence_fusion_service",)
