"""Recognition target planning for the semantic gap loop.

规划器只从 ``RetrievalBundle`` 的来源事实中查找图片路径、图片 hash、
bbox 与稳定业务 ID，把未满足且允许模型生成的缺口转为最小
``RecognitionTarget``。本模块是纯决策层：不调用 facade、不访问文件系统、
不调用模型、不写缓存或图谱；缺少定位信息时输出 ``blocked`` 目标，
不静默丢弃缺口。
"""

from __future__ import annotations

import dataclasses
from typing import Mapping, Sequence

from .assistant_models import (
    AssistantScope,
    EvidenceItem,
    EvidenceRequirement,
    EvidenceType,
    ReasonCode,
    RecognitionPolicy,
    RecognitionTarget,
    RecognitionTargetStatus,
    RequirementAssessment,
    RequirementAssessmentStatus,
    RetrievalBundle,
)
from .semantic_cache import SemanticCacheKeyInput, build_semantic_cache_key


_GENERATABLE_STATUSES = frozenset(
    {
        RequirementAssessmentStatus.MISSING,
        RequirementAssessmentStatus.STALE,
    }
)

_TASK_TYPE_BY_EVIDENCE_TYPE = {
    EvidenceType.TEXT_OBSERVATIONS: "element_text_observation",
}

_REQUIRED_OUTPUTS_BY_EVIDENCE_TYPE = {
    EvidenceType.TEXT_OBSERVATIONS: ("observation",),
    EvidenceType.STRUCTURED_INTERPRETATIONS: ("interpretation",),
}

_GRANULARITY_RANK = {
    "DrawingElement": 0,
    "DrawingBlock": 1,
    "page": 2,
}


@dataclasses.dataclass(frozen=True)
class _Location:
    """目标定位元数据，来自来源事实。"""

    page_id: str | None
    target_type: str
    element_id: str | None = None
    block_id: str | None = None
    image_path: str | None = None
    image_hash: str | None = None
    bbox: Mapping[str, float] | None = None
    normalized_bbox: Mapping[str, float] | None = None


class RecognitionTargetPlanner:
    """把可生成缺口规划为最小识别目标。"""

    def plan(
        self,
        assessments: tuple[RequirementAssessment, ...],
        retrieval_bundle: RetrievalBundle,
        recognition_policy: RecognitionPolicy,
        requirements: Mapping[str, EvidenceRequirement] | None = None,
    ) -> tuple[RecognitionTarget, ...]:
        """为可生成缺口生成目标；定位不足时输出 blocked，不静默丢弃。"""

        requirements = requirements or {}
        targets: list[RecognitionTarget] = []
        for assessment in assessments:
            if (
                assessment.status not in _GENERATABLE_STATUSES
                or not assessment.allow_model_generation
            ):
                continue
            requirement = requirements.get(assessment.requirement_id)
            if requirement is None:
                targets.append(
                    self._blocked(
                        assessment.requirement_id,
                        ReasonCode.SCOPE_MISSING,
                    )
                )
                continue
            targets.extend(
                self._plan_requirement(
                    requirement,
                    assessment,
                    retrieval_bundle,
                    recognition_policy,
                )
            )
        return tuple(sorted(self._merge_targets(targets), key=self._sort_key))

    @staticmethod
    def _merge_targets(
        targets: Sequence[RecognitionTarget],
    ) -> list[RecognitionTarget]:
        """合并同一目标/任务/输出合同的目标，保留全部 covered requirement IDs。"""

        merged: list[RecognitionTarget] = []
        by_key: dict[tuple[object, ...], int] = {}
        for target in targets:
            if target.status is not RecognitionTargetStatus.SELECTED:
                merged.append(target)
                continue
            key = RecognitionTargetPlanner._merge_key(target)
            index = by_key.get(key)
            if index is None:
                by_key[key] = len(merged)
                merged.append(target)
                continue
            existing = merged[index]
            merged[index] = dataclasses.replace(
                existing,
                covered_requirement_ids=tuple(
                    dict.fromkeys(
                        existing.covered_requirement_ids
                        + target.covered_requirement_ids
                    )
                ),
                reason_codes=tuple(
                    dict.fromkeys(existing.reason_codes + target.reason_codes)
                ),
                priority=max(existing.priority, target.priority),
            )
        return merged

    @staticmethod
    def _merge_key(target: RecognitionTarget) -> tuple[object, ...]:
        """目标合并键：page/element/task/output contract 与 bbox 一致才合并。"""

        bbox = target.bbox
        bbox_key = tuple(sorted(bbox.items())) if bbox is not None else None
        return (
            target.page_id,
            target.target_element_id,
            target.target_type,
            target.task_type,
            target.required_outputs,
            bbox_key,
        )

    @staticmethod
    def _plan_requirement(
        requirement: EvidenceRequirement,
        assessment: RequirementAssessment,
        bundle: RetrievalBundle,
        policy: RecognitionPolicy,
    ) -> list[RecognitionTarget]:
        """为单个需求生成 element/block/page 级目标。"""

        if not RecognitionTargetPlanner._scope_present(requirement):
            return [
                RecognitionTargetPlanner._blocked(
                    requirement.requirement_id,
                    ReasonCode.SCOPE_MISSING,
                )
            ]
        location = RecognitionTargetPlanner._locate(requirement, bundle)
        if location is None or not RecognitionTargetPlanner._location_usable(
            requirement,
            location,
        ):
            return [
                RecognitionTargetPlanner._blocked(
                    requirement.requirement_id,
                    ReasonCode.TARGET_LOCATION_MISSING,
                )
            ]
        task_type = RecognitionTargetPlanner._task_type(requirement, location)
        if task_type is None:
            return [
                RecognitionTargetPlanner._blocked(
                    requirement.requirement_id,
                    ReasonCode.UNSUPPORTED_EVIDENCE_TYPE,
                )
            ]
        cache_key = RecognitionTargetPlanner._build_cache_key(
            location,
            task_type,
            policy,
        )
        reason_code = (
            ReasonCode.EVIDENCE_MISSING
            if assessment.status is RequirementAssessmentStatus.MISSING
            else ReasonCode.EVIDENCE_STALE
        )
        return [
            RecognitionTarget(
                target_id=f"target:{requirement.requirement_id}",
                page_id=location.page_id,
                target_element_id=location.element_id or location.block_id,
                target_type=location.target_type,
                task_type=task_type,
                required_outputs=_REQUIRED_OUTPUTS_BY_EVIDENCE_TYPE.get(
                    requirement.evidence_type,
                    (),
                ),
                bbox=location.bbox,
                normalized_bbox=location.normalized_bbox,
                context_element_ids=(),
                covered_requirement_ids=(requirement.requirement_id,),
                cache_key=cache_key,
                priority=100 if requirement.required else 50,
                status=RecognitionTargetStatus.SELECTED,
                reason_codes=(reason_code,),
            )
        ]

    @staticmethod
    def _scope_present(requirement: EvidenceRequirement) -> bool:
        """需求是否携带至少一个稳定业务 ID，供用户澄清决策使用。"""

        scope = requirement.target_scope
        return any(
            value is not None
            for value in (
                scope.page_id,
                scope.block_id,
                scope.element_id,
                scope.cross_section_id,
                scope.table_id,
                scope.table_caption_id,
                scope.claim_id,
            )
        )

    @staticmethod
    def _locate(
        requirement: EvidenceRequirement,
        bundle: RetrievalBundle,
    ) -> _Location | None:
        """从来源事实中查找需求目标的定位元数据。"""

        element_idx, block_idx, page_idx = RecognitionTargetPlanner._indexes(
            bundle
        )
        scope = requirement.target_scope
        if scope.element_id is not None:
            return element_idx.get(scope.element_id)
        if scope.block_id is not None:
            block = block_idx.get(scope.block_id)
            if block is None:
                return None
            page = page_idx.get(block.page_id) if block.page_id else None
            if page is not None:
                block = dataclasses.replace(
                    block,
                    image_path=block.image_path or page.image_path,
                    image_hash=page.image_hash,
                )
            return block
        if scope.page_id is not None:
            return page_idx.get(scope.page_id)
        return None

    @staticmethod
    def _indexes(
        bundle: RetrievalBundle,
    ) -> tuple[
        dict[str, _Location],
        dict[str, _Location],
        dict[str, _Location],
    ]:
        """构建 element/block/page 三个定位索引（只读 bundle 内存数据）。"""

        element_idx: dict[str, _Location] = {}
        block_idx: dict[str, _Location] = {}
        page_idx: dict[str, _Location] = {}
        for item in bundle.source_facts:
            metadata = dict(item.evidence_metadata)
            scope = item.scope
            page_id = metadata.get("page_id")
            if page_id is None and scope is not None:
                page_id = scope.page_id
            element_id = metadata.get("element_id")
            if element_id is None and scope is not None:
                element_id = scope.element_id
            block_id = metadata.get("block_id")
            if block_id is None and scope is not None:
                block_id = scope.block_id
            image_path = metadata.get("image_path")
            image_hash = metadata.get("image_hash")
            bbox = metadata.get("bbox")
            normalized_bbox = metadata.get("normalized_bbox")
            if element_id:
                element_idx.setdefault(
                    element_id,
                    _Location(
                        page_id=page_id,
                        element_id=element_id,
                        image_path=image_path,
                        image_hash=image_hash,
                        bbox=bbox,
                        normalized_bbox=normalized_bbox,
                        target_type=metadata.get("element_type")
                        or "DrawingElement",
                    ),
                )
            if block_id:
                block_idx.setdefault(
                    block_id,
                    _Location(
                        page_id=page_id,
                        block_id=block_id,
                        image_path=image_path,
                        bbox=bbox,
                        normalized_bbox=normalized_bbox,
                        target_type="DrawingBlock",
                    ),
                )
            if page_id:
                existing_page = page_idx.get(page_id)
                if existing_page is None:
                    page_idx[page_id] = _Location(
                        page_id=page_id,
                        image_path=image_path,
                        image_hash=image_hash,
                        target_type="page",
                    )
                else:
                    page_idx[page_id] = dataclasses.replace(
                        existing_page,
                        image_path=existing_page.image_path or image_path,
                        image_hash=existing_page.image_hash or image_hash,
                    )
        return element_idx, block_idx, page_idx

    @staticmethod
    def _location_usable(
        requirement: EvidenceRequirement,
        location: _Location,
    ) -> bool:
        """校验定位元数据完整：缺 image path/hash/bbox/ID 时不生成目标。"""

        scope = requirement.target_scope
        if scope.element_id is not None:
            return all(
                (
                    location.page_id,
                    location.element_id,
                    location.image_path,
                    location.bbox,
                )
            )
        if scope.block_id is not None:
            return all(
                (
                    location.page_id,
                    location.block_id,
                    location.image_path,
                    location.bbox,
                )
            )
        return all(
            (
                location.page_id,
                location.image_path,
            )
        )

    @staticmethod
    def _task_type(
        requirement: EvidenceRequirement,
        location: _Location,
    ) -> str | None:
        """Map semantic evidence gaps to concrete 04 recognition task types."""

        if requirement.evidence_type is EvidenceType.TEXT_OBSERVATIONS:
            if location.target_type == "CrossSection":
                return "section_label_observation"
            return _TASK_TYPE_BY_EVIDENCE_TYPE[EvidenceType.TEXT_OBSERVATIONS]
        if requirement.evidence_type is EvidenceType.STRUCTURED_INTERPRETATIONS:
            if location.target_type == "DrawingBlock":
                return "block_semantic_identification"
            if location.target_type == "DrawingBasicInfo":
                return "basic_info_interpretation"
            if location.target_type == "Table":
                return "table_interpretation"
        return None

    @staticmethod
    def _build_cache_key(
        location: _Location,
        task_type: str,
        policy: RecognitionPolicy,
    ) -> str | None:
        """按目标定位与策略版本构造预期 cache key，缺输入时返回 None。"""

        element_id = location.element_id or location.block_id
        bbox = location.bbox
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
        required = (
            location.image_hash,
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
                image_hash=location.image_hash,
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
    def _blocked(
        requirement_id: str,
        reason_code: ReasonCode,
    ) -> RecognitionTarget:
        """构造 blocked 目标，保证被阻断的缺口可追溯、不静默丢弃。"""

        return RecognitionTarget(
            target_id=f"blocked:{requirement_id}",
            target_type="blocked",
            task_type="blocked",
            covered_requirement_ids=(requirement_id,),
            status=RecognitionTargetStatus.BLOCKED,
            reason_codes=(reason_code,),
            priority=0,
        )

    @staticmethod
    def _sort_key(target: RecognitionTarget) -> tuple[object, ...]:
        """稳定排序：selected 优先、required 优先、覆盖数多优先、粒度细优先。"""

        status_rank = (
            0
            if target.status is RecognitionTargetStatus.SELECTED
            else 1
        )
        required_rank = 0 if target.priority >= 100 else 1
        granularity = _GRANULARITY_RANK.get(target.target_type, 9)
        return (
            status_rank,
            required_rank,
            -len(target.covered_requirement_ids),
            granularity,
            target.target_id,
        )


__all__ = ("RecognitionTargetPlanner",)
