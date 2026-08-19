"""Read-only retrieval bundle builder for the product assistant layer.

归一化器把 facade 返回的 DTO 投影为统一 ``EvidenceItem`` 并按事实层级
放入 ``RetrievalBundle``；只读、不提升事实等级、不触发识别或写回。
"""

from __future__ import annotations

import dataclasses
from enum import Enum
from typing import Any, Mapping

from .assistant_models import (
    AssistantScope,
    EvidenceItem,
    EvidenceRef,
    EvidenceRequirement,
    FactKind,
    MissingEvidence,
    PlanWarning,
    QuestionUnderstandingResult,
    RawRetrievalResult,
    ReasonCode,
    RetrievalBundle,
    RetrievalPlan,
    RetrievalStatus,
    SourceCallRecord,
)


class RetrievalBundleBuilder:
    """把原始检索结果归一化为按事实层级分组的 ``RetrievalBundle``。"""

    def build(
        self,
        question_result: QuestionUnderstandingResult,
        plan: RetrievalPlan,
        raw_result: RawRetrievalResult,
        source_calls: tuple[SourceCallRecord, ...],
    ) -> RetrievalBundle:
        calls_by_step = {call.step_id: call for call in source_calls}
        requirements_by_id = {
            requirement.requirement_id: requirement
            for requirement in question_result.required_evidence
        }
        buckets: dict[str, list[EvidenceItem]] = {
            "source_facts": [],
            "derived_relations": [],
            "semantic_observations": [],
            "semantic_interpretations": [],
            "candidate_relations": [],
            "formal_relations": [],
            "diagnostics": [],
        }
        missing_evidence: list[MissingEvidence] = []
        warnings = list(plan.warnings)
        for step in plan.steps:
            if step.step_id not in raw_result.results:
                call = calls_by_step.get(step.step_id)
                if call is not None and call.status == RetrievalStatus.ERROR:
                    missing_evidence.append(
                        self._missing_evidence(
                            step,
                            call.reason_code or ReasonCode.FACADE_CALL_FAILED,
                            requirements_by_id,
                            call.warning or "facade call failed",
                        )
                    )
                continue
            value = raw_result.results[step.step_id]
            if _is_empty_result(value):
                missing_evidence.append(
                    self._missing_evidence(
                        step,
                        ReasonCode.EMPTY_RESULT,
                        requirements_by_id,
                        "query succeeded but returned no results",
                    )
                )
                continue
            for bucket_name, item in self._project_step(
                step,
                value,
                calls_by_step,
            ):
                buckets[bucket_name].append(item)
        for step_id in raw_result.truncated_step_ids:
            step = next((item for item in plan.steps if item.step_id == step_id), None)
            if step is None:
                continue
            requirement_id = step.requirement_ids[0] if step.requirement_ids else None
            warnings.append(
                PlanWarning(
                    reason_code=ReasonCode.RESULT_TRUNCATED,
                    message=f"result for step {step_id} exceeded its limit and was truncated",
                    requirement_id=requirement_id,
                )
            )
        has_evidence = any(bucket for bucket in buckets.values())
        required_failed = any(
            call.status == RetrievalStatus.ERROR
            for call in source_calls
            if _step_is_required(plan, call.step_id)
        )
        optional_failed = any(
            call.status == RetrievalStatus.ERROR
            for call in source_calls
            if not _step_is_required(plan, call.step_id)
        )
        if required_failed:
            status = RetrievalStatus.ERROR
        elif optional_failed and has_evidence:
            status = RetrievalStatus.PARTIAL
        else:
            status = RetrievalStatus.OK
        return RetrievalBundle(
            request_id=question_result.request_id,
            subrequest_id=plan.subrequest_id,
            scope=question_result.scope,
            source_facts=tuple(buckets["source_facts"]),
            derived_relations=tuple(buckets["derived_relations"]),
            semantic_observations=tuple(buckets["semantic_observations"]),
            semantic_interpretations=tuple(buckets["semantic_interpretations"]),
            candidate_relations=tuple(buckets["candidate_relations"]),
            formal_relations=tuple(buckets["formal_relations"]),
            diagnostics=tuple(buckets["diagnostics"]),
            missing_evidence=tuple(missing_evidence),
            warnings=tuple(warnings),
            source_calls=source_calls,
            status=status,
        )

    def _project_step(
        self,
        step,
        value: object,
        calls_by_step: Mapping[str, SourceCallRecord],
    ) -> list[tuple[str, EvidenceItem]]:
        """把单个 facade 返回对象投影为 (证据桶, EvidenceItem) 列表。"""

        source_call_id = self._source_call_id(step.step_id, calls_by_step)
        method = step.facade_method

        if method == "list_drawing_sets":
            return [
                (
                    "source_facts",
                    EvidenceItem(
                        evidence_id=f"evidence:{step.step_id}:{index}",
                        fact_kind=FactKind.SOURCE_FACT,
                        scope=AssistantScope(
                            project_id=item.project_id,
                            drawing_set_id=item.drawing_set_id,
                        ),
                        value=_to_plain(item),
                        source_call_id=source_call_id,
                    ),
                )
                for index, item in enumerate(_as_sequence(value))
            ]

        if method == "list_pages":
            return [
                (
                    "source_facts",
                    EvidenceItem(
                        evidence_id=f"evidence:{step.step_id}:{index}",
                        fact_kind=FactKind.SOURCE_FACT,
                        scope=AssistantScope(
                            drawing_set_id=item.drawing_set_id,
                            page_id=item.page_id,
                        ),
                        value=_to_plain(item),
                        source_call_id=source_call_id,
                    ),
                )
                for index, item in enumerate(_as_sequence(value))
            ]

        if method == "get_page_source_facts":
            return self._project_page_source_facts(step, value, source_call_id)

        if method == "get_block_trace":
            refs = (
                EvidenceRef(
                    project_id=value.project_id,
                    drawing_set_id=value.drawing_set_id,
                    page_id=value.page_id,
                    block_id=value.block_id,
                    bbox=_bbox_mapping(value.bbox),
                ),
            )
            return [
                (
                    "source_facts",
                    EvidenceItem(
                        evidence_id=f"evidence:{step.step_id}:0",
                        fact_kind=FactKind.SOURCE_FACT,
                        scope=AssistantScope(
                            project_id=value.project_id,
                            drawing_set_id=value.drawing_set_id,
                            page_id=value.page_id,
                            block_id=value.block_id,
                        ),
                        value=_to_plain(value),
                        source_call_id=source_call_id,
                        evidence_refs=refs,
                        evidence_metadata={
                            "page_id": value.page_id,
                            "block_id": value.block_id,
                            "image_path": value.image_path,
                            "bbox": _bbox_mapping(value.bbox),
                            "normalized_bbox": _bbox_mapping(value.normalized_bbox),
                        },
                    ),
                )
            ]

        if method == "get_block_relations":
            return self._project_block_relations(step, value, source_call_id)

        if method == "list_text_observations":
            return [
                (
                    "semantic_observations",
                    EvidenceItem(
                        evidence_id=f"evidence:{step.step_id}:{index}",
                        fact_kind=FactKind.SEMANTIC_OBSERVATION,
                        scope=AssistantScope(
                            page_id=item.page_id,
                            element_id=item.target_element_id,
                        ),
                        value=_to_plain(item),
                        source_call_id=source_call_id,
                        status=item.status,
                        recognition_run_id=item.recognition_run_id,
                        model_profile=item.model_profile,
                        prompt_version=item.prompt_version,
                        created_at_or_version=item.created_at,
                        evidence_refs=(
                            EvidenceRef(
                                page_id=item.page_id,
                                element_id=item.target_element_id,
                                bbox=_bbox_mapping(item.bbox),
                                recognition_run_id=item.recognition_run_id,
                            ),
                        ),
                        evidence_metadata={
                            "status": item.status,
                            "image_hash": item.image_hash,
                            "cache_key": item.cache_key,
                            "task_type": None,
                            "model_profile": item.model_profile,
                            "model_version": item.model_version,
                            "prompt_version": item.prompt_version,
                            "contract_version": item.contract_version,
                            "preprocessing_version": item.preprocessing_version,
                            "normalization_rule_version": item.normalization_rule_version,
                        },
                    ),
                )
                for index, item in enumerate(_as_sequence(value))
            ]

        if method == "list_interpretations":
            return [
                (
                    "semantic_interpretations",
                    EvidenceItem(
                        evidence_id=f"evidence:{step.step_id}:{index}",
                        fact_kind=FactKind.SEMANTIC_INTERPRETATION,
                        scope=AssistantScope(
                            page_id=item.page_id,
                            element_id=item.element_id,
                        ),
                        value=_to_plain(item),
                        source_call_id=source_call_id,
                        status=item.analysis_status,
                        recognition_run_id=item.recognition_run_id,
                        payload_ref=item.payload_ref,
                        created_at_or_version=item.created_at,
                        evidence_refs=(
                            EvidenceRef(
                                page_id=item.page_id,
                                element_id=item.element_id,
                                recognition_run_id=item.recognition_run_id,
                                payload_ref=item.payload_ref,
                            ),
                        ),
                        evidence_metadata={
                            "status": item.analysis_status,
                            "image_hash": item.image_hash,
                            "cache_key": item.cache_key,
                            "task_type": None,
                            "model_profile": item.model_profile,
                            "model_version": item.model_version,
                            "prompt_version": item.prompt_version,
                            "contract_version": item.contract_version,
                            "preprocessing_version": None,
                            "normalization_rule_version": None,
                        },
                    ),
                )
                for index, item in enumerate(_as_sequence(value))
            ]

        if method == "list_candidate_relations":
            return [
                (
                    "candidate_relations",
                    EvidenceItem(
                        evidence_id=f"evidence:{step.step_id}:{index}",
                        fact_kind=FactKind.CANDIDATE_RELATION,
                        scope=AssistantScope(
                            page_id=item.page_id,
                            block_id=item.block_id,
                        ),
                        value=_candidate_relation_value(item),
                        source_call_id=source_call_id,
                        status=item.status,
                        recognition_run_id=item.recognition_run_id,
                        evidence_refs=(
                            EvidenceRef(
                                page_id=item.page_id,
                                block_id=item.block_id,
                                recognition_run_id=item.recognition_run_id,
                            ),
                        ),
                        evidence_metadata={
                            "status": item.status,
                            "recognition_run_id": item.recognition_run_id,
                            "candidate_group_id": getattr(item, "candidate_group_id", None),
                            "relation_type": getattr(item, "relation_type", None),
                            "direction": _relation_direction(item),
                            "cache_key": None,
                            "task_type": None,
                            "model_profile": None,
                            "model_version": None,
                            "prompt_version": None,
                            "contract_version": None,
                            "preprocessing_version": None,
                            "normalization_rule_version": None,
                        },
                    ),
                )
                for index, item in enumerate(_as_sequence(value))
            ]

        if method == "list_section_matches":
            return [
                self._project_section_match(step, index, item, source_call_id)
                for index, item in enumerate(_as_sequence(value))
            ]

        return []

    def _project_page_source_facts(
        self,
        step,
        facts,
        source_call_id: str,
    ) -> list[tuple[str, EvidenceItem]]:
        elements = tuple(getattr(facts, "elements", ()) or ())
        image_hash = getattr(facts, "image_hash", None)
        page_metadata = {
            "page_id": facts.page_id,
            "image_path": facts.image_path,
            "image_hash": image_hash,
            "image_size": list(facts.image_size) if facts.image_size else None,
        }
        if not elements:
            return [
                (
                    "source_facts",
                    EvidenceItem(
                        evidence_id=f"evidence:{step.step_id}:0",
                        fact_kind=FactKind.SOURCE_FACT,
                        scope=AssistantScope(page_id=facts.page_id),
                        value=_to_plain(facts),
                        source_call_id=source_call_id,
                        evidence_metadata=page_metadata,
                    ),
                )
            ]
        items: list[tuple[str, EvidenceItem]] = []
        for index, element in enumerate(elements):
            bbox = _bbox_mapping(element.bbox)
            normalized_bbox = _bbox_mapping(element.normalized_bbox)
            items.append(
                (
                    "source_facts",
                    EvidenceItem(
                        evidence_id=f"evidence:{step.step_id}:{index}",
                        fact_kind=FactKind.SOURCE_FACT,
                        scope=AssistantScope(
                            page_id=facts.page_id,
                            element_id=element.element_id,
                        ),
                        value={
                            "page_id": facts.page_id,
                            "image_path": facts.image_path,
                            "image_hash": image_hash,
                            "image_size": list(facts.image_size) if facts.image_size else None,
                            "element_id": element.element_id,
                            "element_type": element.element_type,
                            "source_label": element.source_label,
                            "bbox": bbox,
                            "normalized_bbox": normalized_bbox,
                            "metadata": dict(element.metadata),
                        },
                        source_call_id=source_call_id,
                        evidence_refs=(
                            EvidenceRef(
                                page_id=facts.page_id,
                                element_id=element.element_id,
                                bbox=bbox,
                            ),
                        ),
                        evidence_metadata={
                            **page_metadata,
                            "element_id": element.element_id,
                            "element_type": element.element_type,
                            "bbox": bbox,
                            "normalized_bbox": normalized_bbox,
                        },
                    ),
                )
            )
        return items

    def _project_block_relations(
        self,
        step,
        relations,
        source_call_id: str,
    ) -> list[tuple[str, EvidenceItem]]:
        items: list[tuple[str, EvidenceItem]] = []
        index = 0
        for relation_kind, target_ids in (
            ("caption", relations.caption_ids),
            ("basic_info", relations.basic_info_ids),
            ("annotation", relations.annotation_ids),
            ("section_mark", relations.section_mark_ids),
        ):
            for target_id in target_ids:
                items.append(
                    (
                        "derived_relations",
                        EvidenceItem(
                            evidence_id=f"evidence:{step.step_id}:{index}",
                            fact_kind=FactKind.DERIVED_RELATION,
                            scope=AssistantScope(block_id=relations.block_id),
                            value={
                                "block_id": relations.block_id,
                                "relation_type": f"has_{relation_kind}",
                                "target_id": target_id,
                                "subject": relations.block_id,
                                "predicate": f"has_{relation_kind}",
                                "objects": (target_id,),
                            },
                            source_call_id=source_call_id,
                            evidence_metadata={
                                "relation_type": f"has_{relation_kind}",
                                "direction": f"{relations.block_id}->{target_id}",
                                "candidate_group_id": None,
                            },
                        ),
                    )
                )
                index += 1
        for relation_kind, target_ids in (
            ("candidate_caption", relations.candidate_caption_ids),
            ("candidate_section_mark", relations.candidate_section_mark_ids),
        ):
            for target_id in target_ids:
                items.append(
                    (
                        "candidate_relations",
                        EvidenceItem(
                            evidence_id=f"evidence:{step.step_id}:{index}",
                            fact_kind=FactKind.CANDIDATE_RELATION,
                            scope=AssistantScope(block_id=relations.block_id),
                            value={
                                "block_id": relations.block_id,
                                "relation_type": relation_kind,
                                "target_id": target_id,
                                "subject": relations.block_id,
                                "predicate": relation_kind,
                                "objects": (target_id,),
                            },
                            source_call_id=source_call_id,
                            evidence_metadata={
                                "relation_type": relation_kind,
                                "direction": f"{relations.block_id}->{target_id}",
                                "candidate_group_id": f"{relations.block_id}:{relation_kind}:{target_id}",
                            },
                        ),
                    )
                )
                index += 1
        return items

    def _project_section_match(
        self,
        step,
        index: int,
        item,
        source_call_id: str,
    ) -> tuple[str, EvidenceItem]:
        fact_kind = getattr(item, "fact_kind", "candidate_relation")
        is_formal = fact_kind == "formal_relation"
        bucket = "formal_relations" if is_formal else "candidate_relations"
        scope = AssistantScope(
            cross_section_id=item.cross_section_id,
            page_id=getattr(item, "page_id", None),
        )
        return (
            bucket,
            EvidenceItem(
                evidence_id=f"evidence:{step.step_id}:{index}",
                fact_kind=FactKind.FORMAL_RELATION if is_formal else FactKind.CANDIDATE_RELATION,
                scope=scope,
                value=_to_plain(item),
                source_call_id=source_call_id,
                status=item.status,
                rule_version=getattr(item, "rule_version", None),
                evidence_refs=(
                    EvidenceRef(
                        page_id=getattr(item, "page_id", None),
                        rule_version=getattr(item, "rule_version", None),
                    ),
                ),
                evidence_metadata={
                    "status": item.status,
                    "match_status": item.match_status,
                    "rule_version": getattr(item, "rule_version", None),
                    "alias_rule_id": getattr(item, "alias_rule_id", None),
                    "candidate_group_id": getattr(item, "candidate_group_id", None),
                    "relation_type": "section_match",
                    "direction": f"{item.cross_section_id}->caption",
                    "cache_key": None,
                    "task_type": None,
                    "model_profile": None,
                    "model_version": None,
                    "prompt_version": None,
                    "contract_version": None,
                    "preprocessing_version": None,
                    "normalization_rule_version": None,
                },
            ),
        )

    @staticmethod
    def _source_call_id(
        step_id: str,
        calls_by_step: Mapping[str, SourceCallRecord],
    ) -> str:
        call = calls_by_step.get(step_id)
        return call.source_call_id if call is not None else f"call:{step_id}"

    @staticmethod
    def _missing_evidence(
        step,
        reason_code: ReasonCode,
        requirements_by_id: Mapping[str, EvidenceRequirement],
        message: str,
    ) -> MissingEvidence:
        requirement = (
            requirements_by_id.get(step.requirement_ids[0])
            if step.requirement_ids
            else None
        )
        return MissingEvidence(
            requirement_id=step.requirement_ids[0] if step.requirement_ids else step.step_id,
            evidence_type=requirement.evidence_type if requirement is not None else EvidenceType.CANDIDATE_RELATIONS,
            target_scope=requirement.target_scope if requirement is not None else None,
            reason_code=reason_code,
            message=message,
        )


def _as_sequence(value: object) -> tuple[object, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return (value,)


def _is_empty_result(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, tuple)):
        return len(value) == 0
    return False


def _step_is_required(plan: RetrievalPlan, step_id: str) -> bool:
    step = next((item for item in plan.steps if item.step_id == step_id), None)
    return step is not None and step.required


def _bbox_mapping(bbox: object) -> dict[str, float]:
    return {
        "x_min": float(bbox.x_min),
        "y_min": float(bbox.y_min),
        "x_max": float(bbox.x_max),
        "y_max": float(bbox.y_max),
    }


def _relation_direction(item: object) -> str | None:
    source = (
        getattr(item, "source_element_id", None)
        or getattr(item, "block_id", None)
        or getattr(item, "cross_section_id", None)
    )
    if source is None:
        return None
    target = getattr(item, "relation_type", None)
    return f"{source}->{target or 'target'}"


def _candidate_relation_value(item: object) -> dict[str, object]:
    """Enrich candidate summaries with the 05 normalization contract fields.

    ``subject/predicate/objects`` 是候选关系参与比较/冲突分组的稳定结构；
    source 缺失时回退到 block_id，target 缺失时 objects 为空元组，不猜测
    方向也不把候选提升为正式关系。
    """

    value = _to_plain(item)
    source = getattr(item, "source_element_id", None)
    target = getattr(item, "target_element_id", None)
    value["subject"] = source or getattr(item, "block_id", None)
    value["predicate"] = getattr(item, "relation_type", None)
    value["objects"] = (target,) if target else ()
    return value


def _to_plain(value: object) -> object:
    """把 dataclass/枚举/映射/序列递归转为纯字典/列表，供 EvidenceItem.value 使用。"""

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {field.name: _to_plain(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _to_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_plain(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value
