"""Freshness and cache disposition evaluation for the semantic gap loop.

评估器判断已匹配证据是否仍满足图片、bbox、模型、prompt、预处理、
规范化和输出合同等 freshness 维度，并复用 ``semantic_cache`` 的统一定向
cache key 构造。本模块是纯决策层：只读判断，不写缓存、不读取缓存存储、
不调用模型或图谱，缺失数据时输出 unknown，不把未知状态默认为有效。
"""

from __future__ import annotations

import dataclasses
from typing import Mapping, Sequence

from .assistant_models import (
    CacheCandidate,
    CacheDisposition,
    EvidenceItem,
    EvidenceRequirement,
    FreshnessRequirement,
    FreshnessResult,
    ReasonCode,
    RecognitionPolicy,
    RequirementAssessment,
    RequirementAssessmentStatus,
    RetrievalBundle,
)
from .semantic_cache import SemanticCacheKeyInput, build_semantic_cache_key


_BUCKET_NAMES = (
    "source_facts",
    "derived_relations",
    "semantic_observations",
    "semantic_interpretations",
    "candidate_relations",
    "formal_relations",
    "diagnostics",
)

_STALE_REASON_CODES = frozenset(
    {
        ReasonCode.IMAGE_CHANGED,
        ReasonCode.BBOX_CHANGED,
        ReasonCode.MODEL_PROFILE_CHANGED,
        ReasonCode.PROMPT_VERSION_CHANGED,
        ReasonCode.CONTRACT_VERSION_CHANGED,
        ReasonCode.PREPROCESSING_VERSION_CHANGED,
        ReasonCode.NORMALIZATION_RULE_CHANGED,
        ReasonCode.EVIDENCE_STALE,
    }
)


@dataclasses.dataclass(frozen=True)
class _FreshnessOutcome:
    """单个需求的 freshness/缓存判定结果。"""

    freshness_result: FreshnessResult
    disposition: CacheDisposition
    cache_key: str | None
    reusable_evidence_ids: tuple[str, ...]
    reason_codes: tuple[ReasonCode, ...]
    missing_metadata: tuple[str, ...]


class EvidenceFreshnessEvaluator:
    """按图片/bbox/模型/prompt/合同维度判断证据是否当前有效。"""

    def evaluate(
        self,
        assessments: tuple[RequirementAssessment, ...],
        retrieval_bundle: RetrievalBundle,
        recognition_policy: RecognitionPolicy,
        requirements: Mapping[str, EvidenceRequirement] | None = None,
    ) -> tuple[RequirementAssessment, ...]:
        """为每个 assessment 附加 freshness 结果，不改变匹配证据集合。"""

        requirements = requirements or {}
        updated = []
        for assessment in assessments:
            outcome = self._outcome_for_assessment(
                assessment,
                retrieval_bundle,
                recognition_policy,
                requirements,
            )
            status = assessment.status
            reason_codes = list(assessment.reason_codes)
            missing_metadata = list(assessment.missing_metadata)
            if outcome.disposition in (
                CacheDisposition.STALE,
                CacheDisposition.PARTIAL_HIT,
            ):
                status = RequirementAssessmentStatus.STALE
                if ReasonCode.EVIDENCE_STALE not in reason_codes:
                    reason_codes.append(ReasonCode.EVIDENCE_STALE)
            for metadata_name in outcome.missing_metadata:
                if metadata_name not in missing_metadata:
                    missing_metadata.append(metadata_name)
            updated.append(
                dataclasses.replace(
                    assessment,
                    status=status,
                    reason_codes=tuple(reason_codes),
                    missing_metadata=tuple(missing_metadata),
                    freshness_result=outcome.freshness_result,
                    cache_disposition=outcome.disposition,
                )
            )
        return tuple(updated)

    def cache_candidates(
        self,
        assessments: tuple[RequirementAssessment, ...],
        retrieval_bundle: RetrievalBundle,
        recognition_policy: RecognitionPolicy,
        requirements: Mapping[str, EvidenceRequirement] | None = None,
    ) -> tuple[CacheCandidate, ...]:
        """为每个需求构造预期 cache key 与处置结果（只读，不访问缓存存储）。"""

        requirements = requirements or {}
        candidates = []
        for assessment in assessments:
            outcome = self._outcome_for_assessment(
                assessment,
                retrieval_bundle,
                recognition_policy,
                requirements,
            )
            candidates.append(
                CacheCandidate(
                    requirement_id=assessment.requirement_id,
                    cache_key=outcome.cache_key,
                    disposition=outcome.disposition,
                    reusable_evidence_ids=outcome.reusable_evidence_ids,
                    reason_codes=outcome.reason_codes,
                )
            )
        return tuple(candidates)

    def _outcome_for_assessment(
        self,
        assessment: RequirementAssessment,
        bundle: RetrievalBundle,
        policy: RecognitionPolicy,
        requirements: Mapping[str, EvidenceRequirement],
    ) -> _FreshnessOutcome:
        """计算单个需求的 freshness 结果与缓存处置。"""

        items = self._matched_items(assessment, bundle)
        requirement = requirements.get(assessment.requirement_id)
        if policy.cache_mode == "bypass":
            return _FreshnessOutcome(
                freshness_result=FreshnessResult(dimensions={}, is_current=False),
                disposition=CacheDisposition.BYPASSED,
                cache_key=None,
                reusable_evidence_ids=(),
                reason_codes=(),
                missing_metadata=(),
            )
        if not items:
            return _FreshnessOutcome(
                freshness_result=FreshnessResult(dimensions={}, is_current=False),
                disposition=CacheDisposition.MISS,
                cache_key=None,
                reusable_evidence_ids=(),
                reason_codes=(),
                missing_metadata=(),
            )
        per_item = [
            (item, self._freshness_for_item(item, requirement, policy, bundle))
            for item in items
        ]
        freshness_result = self._aggregate_freshness(
            [result for _, result in per_item]
        )
        cache_key = self._expected_cache_key(
            requirement,
            items[0],
            policy,
            bundle,
        )
        missing_metadata = tuple(
            dict.fromkeys(
                metadata_name
                for _, result in per_item
                for metadata_name in result.missing_metadata
            )
        )
        reason_codes = tuple(
            dict.fromkeys(
                code
                for _, result in per_item
                for code in result.reason_codes
            )
        )
        if cache_key is None or missing_metadata:
            outcome_reasons = list(reason_codes)
            if cache_key is None:
                outcome_reasons.append(ReasonCode.CACHE_KEY_UNAVAILABLE)
            return _FreshnessOutcome(
                freshness_result=freshness_result,
                disposition=CacheDisposition.UNKNOWN,
                cache_key=cache_key,
                reusable_evidence_ids=(),
                reason_codes=tuple(dict.fromkeys(outcome_reasons)),
                missing_metadata=missing_metadata,
            )
        fresh_ids = tuple(
            item.evidence_id
            for item, result in per_item
            if result.is_current
        )
        if len(fresh_ids) == len(per_item):
            return _FreshnessOutcome(
                freshness_result=freshness_result,
                disposition=CacheDisposition.FULL_HIT,
                cache_key=cache_key,
                reusable_evidence_ids=fresh_ids,
                reason_codes=(),
                missing_metadata=(),
            )
        if fresh_ids:
            return _FreshnessOutcome(
                freshness_result=freshness_result,
                disposition=CacheDisposition.PARTIAL_HIT,
                cache_key=cache_key,
                reusable_evidence_ids=fresh_ids,
                reason_codes=reason_codes,
                missing_metadata=(),
            )
        if any(code in _STALE_REASON_CODES for code in reason_codes):
            return _FreshnessOutcome(
                freshness_result=freshness_result,
                disposition=CacheDisposition.STALE,
                cache_key=cache_key,
                reusable_evidence_ids=(),
                reason_codes=reason_codes,
                missing_metadata=(),
            )
        return _FreshnessOutcome(
            freshness_result=freshness_result,
            disposition=CacheDisposition.UNKNOWN,
            cache_key=cache_key,
            reusable_evidence_ids=(),
            reason_codes=reason_codes,
            missing_metadata=(),
        )

    @staticmethod
    def _aggregate_freshness(
        results: Sequence[FreshnessResult],
    ) -> FreshnessResult:
        """把多个证据的 freshness 结果聚合为一个需求级结果。"""

        all_dimensions: list[str] = []
        for result in results:
            all_dimensions.extend(result.dimensions.keys())
        dimensions = {
            dimension: all(
                result.dimensions.get(dimension, True) for result in results
            )
            for dimension in dict.fromkeys(all_dimensions)
        }
        missing_metadata = tuple(
            dict.fromkeys(
                item
                for result in results
                for item in result.missing_metadata
            )
        )
        reason_codes = tuple(
            dict.fromkeys(
                code
                for result in results
                for code in result.reason_codes
            )
        )
        return FreshnessResult(
            dimensions=dimensions,
            missing_metadata=missing_metadata,
            reason_codes=reason_codes,
            is_current=all(result.is_current for result in results),
        )

    @staticmethod
    def _matched_items(
        assessment: RequirementAssessment,
        bundle: RetrievalBundle,
    ) -> list[EvidenceItem]:
        """按 assessment 的 matched evidence IDs 从 bundle 中定位证据。"""

        by_id: dict[str, EvidenceItem] = {}
        for bucket_name in _BUCKET_NAMES:
            for item in getattr(bundle, bucket_name):
                by_id[item.evidence_id] = item
        return [
            by_id[evidence_id]
            for evidence_id in assessment.matched_evidence_ids
            if evidence_id in by_id
        ]

    @staticmethod
    def _freshness_for_item(
        item: EvidenceItem,
        requirement: EvidenceRequirement | None,
        policy: RecognitionPolicy,
        bundle: RetrievalBundle,
    ) -> FreshnessResult:
        """判断单个证据的各 freshness 维度。"""

        required = EvidenceFreshnessEvaluator._required_dimensions(requirement, policy)
        dimensions: dict[str, bool] = {}
        missing: list[str] = []
        reasons: list[ReasonCode] = []
        metadata = dict(item.evidence_metadata)
        current = EvidenceFreshnessEvaluator._current_target(item, bundle)

        if "image_hash" in required:
            evidence_hash = metadata.get("image_hash")
            current_hash = current.get("image_hash") if current else None
            if evidence_hash is None or current_hash is None:
                missing.append("image_hash")
                dimensions["image_hash"] = False
            elif evidence_hash == current_hash:
                dimensions["image_hash"] = True
            else:
                dimensions["image_hash"] = False
                reasons.append(ReasonCode.IMAGE_CHANGED)

        if "bbox" in required:
            evidence_bbox = metadata.get("bbox")
            current_bbox = current.get("bbox") if current else None
            if evidence_bbox is None or current_bbox is None:
                missing.append("bbox")
                dimensions["bbox"] = False
            elif EvidenceFreshnessEvaluator._bbox_equal(evidence_bbox, current_bbox):
                dimensions["bbox"] = True
            else:
                dimensions["bbox"] = False
                reasons.append(ReasonCode.BBOX_CHANGED)

        if "model" in required:
            if (
                policy.model_profile is None
                or policy.model_version is None
                or metadata.get("model_profile") is None
                or metadata.get("model_version") is None
            ):
                missing.append("model_profile")
                dimensions["model"] = False
            elif (
                policy.model_profile == metadata.get("model_profile")
                and policy.model_version == metadata.get("model_version")
            ):
                dimensions["model"] = True
            else:
                dimensions["model"] = False
                reasons.append(ReasonCode.MODEL_PROFILE_CHANGED)

        if "prompt" in required:
            evidence_version = metadata.get("prompt_version")
            current_version = policy.prompt_version
            if evidence_version is None or current_version is None:
                missing.append("prompt_version")
                dimensions["prompt"] = False
            elif evidence_version == current_version:
                dimensions["prompt"] = True
            else:
                dimensions["prompt"] = False
                reasons.append(ReasonCode.PROMPT_VERSION_CHANGED)

        if "preprocessing" in required:
            evidence_version = metadata.get("preprocessing_version")
            current_version = policy.preprocessing_version
            if evidence_version is None or current_version is None:
                missing.append("preprocessing_version")
                dimensions["preprocessing"] = False
            elif evidence_version == current_version:
                dimensions["preprocessing"] = True
            else:
                dimensions["preprocessing"] = False
                reasons.append(ReasonCode.PREPROCESSING_VERSION_CHANGED)

        if "normalization" in required:
            evidence_version = metadata.get("normalization_rule_version")
            current_version = policy.normalization_rule_version
            if evidence_version is None or current_version is None:
                missing.append("normalization_rule_version")
                dimensions["normalization"] = False
            elif evidence_version == current_version:
                dimensions["normalization"] = True
            else:
                dimensions["normalization"] = False
                reasons.append(ReasonCode.NORMALIZATION_RULE_CHANGED)

        if "contract" in required:
            evidence_version = metadata.get("contract_version")
            current_version = policy.contract_version
            if evidence_version is None or current_version is None:
                missing.append("contract_version")
                dimensions["contract"] = False
            elif evidence_version == current_version:
                dimensions["contract"] = True
            else:
                dimensions["contract"] = False
                reasons.append(ReasonCode.CONTRACT_VERSION_CHANGED)

        return FreshnessResult(
            dimensions=dimensions,
            missing_metadata=tuple(missing),
            reason_codes=tuple(reasons),
            is_current=bool(required) and all(dimensions.values()) and not missing,
        )

    @staticmethod
    def _required_dimensions(
        requirement: EvidenceRequirement | None,
        policy: RecognitionPolicy,
    ) -> frozenset[str]:
        """把需求 freshness 约束映射为需要检查的维度集合。"""

        del policy
        if requirement is None:
            return frozenset()
        freshness = requirement.freshness_requirement
        if freshness is None:
            freshness = FreshnessRequirement.from_policy(requirement.freshness_policy)
        dimensions = set()
        if freshness.require_current_image:
            dimensions.add("image_hash")
        if freshness.require_current_bbox:
            dimensions.add("bbox")
        if freshness.require_current_model:
            dimensions.add("model")
        if freshness.require_current_prompt:
            dimensions.add("prompt")
        if freshness.require_current_preprocessing:
            dimensions.add("preprocessing")
        if freshness.require_current_normalization:
            dimensions.add("normalization")
        if freshness.require_current_contract:
            dimensions.add("contract")
        return frozenset(dimensions)

    @staticmethod
    def _current_target(
        item: EvidenceItem,
        bundle: RetrievalBundle,
    ) -> dict[str, object]:
        """从来源事实中查找当前图片 hash 与目标元素 bbox。"""

        scope = item.scope
        page_id = scope.page_id if scope is not None else None
        element_id = scope.element_id if scope is not None else None
        lookup: dict[tuple[str | None, str | None], dict[str, object]] = {}
        for fact in bundle.source_facts:
            metadata = dict(fact.evidence_metadata)
            fact_page = metadata.get("page_id")
            if fact_page is None and fact.scope is not None:
                fact_page = fact.scope.page_id
            fact_element = metadata.get("element_id")
            if fact_element is None and fact.scope is not None:
                fact_element = fact.scope.element_id
            lookup[(fact_page, fact_element)] = {
                "image_hash": metadata.get("image_hash"),
                "bbox": metadata.get("bbox"),
            }
        current = lookup.get((page_id, element_id))
        if current is None:
            current = lookup.get((page_id, None))
        return current or {}

    @staticmethod
    def _expected_cache_key(
        requirement: EvidenceRequirement | None,
        item: EvidenceItem | None,
        policy: RecognitionPolicy,
        bundle: RetrievalBundle,
    ) -> str | None:
        """用当前图片/bbox、目标元素、任务类型与策略版本构造预期 cache key。"""

        if item is None:
            return None
        current = EvidenceFreshnessEvaluator._current_target(item, bundle)
        image_hash = current.get("image_hash")
        bbox = current.get("bbox")
        if not isinstance(image_hash, str) or not image_hash.strip():
            return None
        if not isinstance(bbox, Mapping):
            return None
        try:
            bbox_tuple = (
                bbox["x_min"],
                bbox["y_min"],
                bbox["x_max"],
                bbox["y_max"],
            )
        except (KeyError, TypeError):
            return None
        metadata = dict(item.evidence_metadata)
        element_id = None
        if requirement is not None and requirement.target_scope.element_id is not None:
            element_id = requirement.target_scope.element_id
        elif item.scope is not None:
            element_id = item.scope.element_id
        if element_id is None:
            element_id = metadata.get("element_id")
        task_type = metadata.get("task_type")
        required = (
            element_id,
            task_type,
            policy.model_profile,
            policy.model_version,
            policy.prompt_version,
            policy.preprocessing_version,
            policy.normalization_rule_version,
            policy.contract_version,
        )
        if any(
            value is None or (isinstance(value, str) and not value.strip())
            for value in required
        ):
            return None
        try:
            inputs = SemanticCacheKeyInput(
                image_hash=image_hash,
                bbox=bbox_tuple,
                target_element_id=element_id,
                task_type=task_type,
                model_profile=policy.model_profile,
                model_version=policy.model_version,
                prompt_version=policy.prompt_version,
                preprocessing_version=policy.preprocessing_version,
                normalization_rule_version=policy.normalization_rule_version,
                contract_version=policy.contract_version,
            )
        except (KeyError, TypeError, ValueError):
            return None
        return build_semantic_cache_key(inputs)

    @staticmethod
    def _bbox_equal(left: object, right: object) -> bool:
        """按四个坐标值比较 bbox 映射，忽略数值类型差异。"""

        if not isinstance(left, Mapping) or not isinstance(right, Mapping):
            return False
        keys = ("x_min", "y_min", "x_max", "y_max")
        try:
            return all(
                float(left[key]) == float(right[key]) for key in keys
            )
        except (KeyError, TypeError, ValueError):
            return False


__all__ = ("EvidenceFreshnessEvaluator",)
