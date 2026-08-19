"""Recognition result projection to unified evidence for the 05 fusion layer.

本模块把 04 返回的 ``SemanticRecognitionResult`` 安全投影为统一
``EvidenceItem``，固定映射规则：

- ``TextObservation`` -> ``semantic_observation``；
- 三类 ``Interpretation`` -> ``semantic_interpretation``；
- ``RecognitionCandidateEvidence`` -> ``candidate_relation``；
- 执行摘要/usage/cost/latency/attempt 状态/safe error/persisted -> ``diagnostic``。

投影器永不产生 ``source_fact``、``derived_relation`` 或 ``formal_relation``，
不访问文件、缓存、provider 或数据库，也不触发关系写入或候选提升。
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Mapping

from .assistant_models import (
    AssistantScope,
    EvidenceItem,
    EvidenceRef,
    FactKind,
    ReasonCode,
)
from .recognition_models import RecognitionCandidateEvidence
from .semantic_models import (
    BasicInfoInterpretation,
    BlockInterpretation,
    TableInterpretation,
    TextObservation,
)

if TYPE_CHECKING:
    from .assistant_models import RecognitionTarget
    from .semantic_service import SemanticRecognitionResult

SOURCE_SYSTEM = "semantic_recognition"


@dataclass(frozen=True)
class ProjectionResult:
    """一次投影的输出，区分可回答证据、diagnostic 与被隔离输出。"""

    evidence: tuple[EvidenceItem, ...] = field(default_factory=tuple)
    diagnostics: tuple[EvidenceItem, ...] = field(default_factory=tuple)
    rejected_outputs: tuple[Any, ...] = field(default_factory=tuple)


class RecognitionEvidenceProjector:
    """将 ``SemanticRecognitionResult`` 投影为统一证据的纯组件。

    传入 ``targets`` 时对每个输出做 fail-closed scope 校验；无法安全归属
    的输出进入 ``rejected_outputs`` 并生成 ``recognition_scope_mismatch``
    diagnostic，投影器不猜测或扩张请求 scope。
    """

    def project(
        self,
        result: SemanticRecognitionResult,
        targets: tuple[RecognitionTarget, ...] = (),
    ) -> ProjectionResult:
        """投影一次识别结果；``targets`` 非空时校验 scope 归属。"""

        evidence: list[EvidenceItem] = []
        diagnostics: list[EvidenceItem] = []
        rejected: list[Any] = []
        validator = _ScopeValidator.from_targets(targets) if targets else None

        for observation in result.observations:
            if validator is not None and not validator.observation_in_scope(observation):
                rejected.append(observation)
                diagnostics.append(
                    _scope_mismatch_diagnostic(
                        result.recognition_run_id,
                        len(diagnostics),
                        "observation",
                        observation.page_id,
                        observation.target_element_id,
                    )
                )
            else:
                evidence.append(_project_observation(observation))

        for interpretation in result.interpretations:
            page_id, element_ref = _interpretation_ref(interpretation)
            if validator is not None and not validator.interpretation_in_scope(page_id, element_ref):
                rejected.append(interpretation)
                diagnostics.append(
                    _scope_mismatch_diagnostic(
                        result.recognition_run_id,
                        len(diagnostics),
                        "interpretation",
                        page_id,
                        element_ref,
                    )
                )
            else:
                evidence.append(_project_interpretation(interpretation))

        for index, candidate in enumerate(result.candidate_evidence):
            if validator is not None and not validator.candidate_in_scope(candidate):
                rejected.append(candidate)
                diagnostics.append(
                    _scope_mismatch_diagnostic(
                        result.recognition_run_id,
                        len(diagnostics),
                        "candidate",
                        None,
                        candidate.source_target_id,
                    )
                )
            else:
                evidence.append(_project_candidate(candidate, result.recognition_run_id, index))

        diagnostics.append(_project_diagnostic(result))
        return ProjectionResult(
            evidence=tuple(evidence),
            diagnostics=tuple(diagnostics),
            rejected_outputs=tuple(rejected),
        )


@dataclass(frozen=True)
class _ScopeValidator:
    """根据 selected targets 构建的 scope 索引，用于 fail-closed 校验。"""

    page_ids: frozenset[str]
    element_ids: frozenset[str]
    target_ids: frozenset[str]
    targets_by_element: Mapping[str, Any]

    @classmethod
    def from_targets(cls, targets: tuple[Any, ...]) -> "_ScopeValidator":
        return cls(
            page_ids=frozenset(target.page_id for target in targets if target.page_id),
            element_ids=frozenset(target.target_element_id for target in targets if target.target_element_id),
            target_ids=frozenset(target.target_id for target in targets),
            targets_by_element={
                target.target_element_id: target
                for target in targets
                if target.target_element_id
            },
        )

    def observation_in_scope(self, observation: TextObservation) -> bool:
        if observation.page_id not in self.page_ids:
            return False
        if observation.target_element_id not in self.element_ids:
            return False
        target = self.targets_by_element.get(observation.target_element_id)
        if target is not None and getattr(target, "bbox", None) is not None:
            if _bbox_mapping(observation.bbox) != dict(target.bbox):
                return False
        return True

    def interpretation_in_scope(self, page_id: str | None, element_ref: str | None) -> bool:
        if page_id is None or page_id not in self.page_ids:
            return False
        if element_ref is None or element_ref not in self.element_ids:
            return False
        return True

    def candidate_in_scope(self, candidate: RecognitionCandidateEvidence) -> bool:
        if candidate.source_target_id not in self.target_ids:
            return False
        return all(
            supporting_id in self.target_ids
            for supporting_id in candidate.supporting_target_ids
        )


def _interpretation_ref(
    interpretation: BlockInterpretation | BasicInfoInterpretation | TableInterpretation,
) -> tuple[str | None, str | None]:
    if isinstance(interpretation, BlockInterpretation):
        return interpretation.page_id, interpretation.block_id
    if isinstance(interpretation, BasicInfoInterpretation):
        return interpretation.page_id, interpretation.basic_info_id
    if isinstance(interpretation, TableInterpretation):
        return interpretation.page_id, interpretation.table_id
    raise TypeError(f"unsupported interpretation type: {type(interpretation).__name__}")


def _scope_mismatch_diagnostic(
    recognition_run_id: str,
    index: int,
    output_kind: str,
    page_id: str | None,
    element_ref: str | None,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=f"diagnostic:{recognition_run_id}:scope-mismatch:{index}",
        fact_kind=FactKind.DIAGNOSTIC,
        scope=AssistantScope(page_id=page_id),
        value={
            "reason_code": ReasonCode.RECOGNITION_SCOPE_MISMATCH.value,
            "output_kind": output_kind,
            "page_id": page_id,
            "element_ref": element_ref,
        },
        source_system=SOURCE_SYSTEM,
        recognition_run_id=recognition_run_id,
        evidence_metadata={
            "reason_code": ReasonCode.RECOGNITION_SCOPE_MISMATCH.value,
            "output_kind": output_kind,
        },
    )


def _project_observation(observation: TextObservation) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=observation.observation_id,
        fact_kind=FactKind.SEMANTIC_OBSERVATION,
        status=_enum_value(observation.status),
        scope=AssistantScope(
            page_id=observation.page_id,
            element_id=observation.target_element_id,
        ),
        value=_to_plain(observation),
        confidence=observation.confidence,
        source_system=SOURCE_SYSTEM,
        recognition_run_id=observation.recognition_run_id,
        model_profile=observation.model_profile,
        prompt_version=observation.prompt_version,
        created_at_or_version=observation.created_at,
        evidence_refs=(
            EvidenceRef(
                page_id=observation.page_id,
                element_id=observation.target_element_id,
                bbox=_bbox_mapping(observation.bbox),
                recognition_run_id=observation.recognition_run_id,
            ),
        ),
        evidence_metadata={
            "status": _enum_value(observation.status),
            "normalized_text": observation.normalized_text,
            "target_element_type": observation.target_element_type,
            "image_hash": observation.image_hash,
            "cache_key": observation.cache_key,
            "input_contract_version": observation.input_contract_version,
            "output_contract_version": observation.output_contract_version,
            "preprocessing_version": observation.preprocessing_version,
        },
    )


def _project_interpretation(
    interpretation: BlockInterpretation | BasicInfoInterpretation | TableInterpretation,
) -> EvidenceItem:
    if isinstance(interpretation, BlockInterpretation):
        return _project_block_interpretation(interpretation)
    if isinstance(interpretation, BasicInfoInterpretation):
        return _project_basic_info_interpretation(interpretation)
    if isinstance(interpretation, TableInterpretation):
        return _project_table_interpretation(interpretation)
    raise TypeError(f"unsupported interpretation type: {type(interpretation).__name__}")


def _project_block_interpretation(interpretation: BlockInterpretation) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=interpretation.interpretation_id,
        fact_kind=FactKind.SEMANTIC_INTERPRETATION,
        status=_enum_value(interpretation.analysis_status),
        scope=AssistantScope(
            page_id=interpretation.page_id,
            block_id=interpretation.block_id,
        ),
        value=_to_plain(interpretation),
        source_system=SOURCE_SYSTEM,
        recognition_run_id=interpretation.recognition_run_id,
        payload_ref=interpretation.payload_ref,
        model_profile=interpretation.model_profile,
        prompt_version=interpretation.prompt_version,
        evidence_refs=(
            EvidenceRef(
                page_id=interpretation.page_id,
                block_id=interpretation.block_id,
                recognition_run_id=interpretation.recognition_run_id,
                payload_ref=interpretation.payload_ref,
            ),
        ),
        evidence_metadata={
            "status": _enum_value(interpretation.analysis_status),
            "interpreted_type": interpretation.interpreted_type,
            "supported_by_observation_ids": interpretation.supported_by_observation_ids,
            "cache_key": interpretation.cache_key,
            "contract_version": interpretation.contract_version,
            "input_contract_version": interpretation.input_contract_version,
            "preprocessing_version": interpretation.preprocessing_version,
        },
    )


def _project_basic_info_interpretation(interpretation: BasicInfoInterpretation) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=interpretation.interpretation_id,
        fact_kind=FactKind.SEMANTIC_INTERPRETATION,
        status=_enum_value(interpretation.analysis_status),
        scope=AssistantScope(page_id=interpretation.page_id),
        value=_to_plain(interpretation),
        source_system=SOURCE_SYSTEM,
        recognition_run_id=interpretation.recognition_run_id,
        payload_ref=interpretation.payload_ref,
        model_profile=interpretation.model_profile,
        prompt_version=interpretation.prompt_version,
        evidence_refs=(
            EvidenceRef(
                page_id=interpretation.page_id,
                recognition_run_id=interpretation.recognition_run_id,
                payload_ref=interpretation.payload_ref,
            ),
        ),
        evidence_metadata={
            "status": _enum_value(interpretation.analysis_status),
            "basic_info_id": interpretation.basic_info_id,
            "supported_by_observation_ids": interpretation.supported_by_observation_ids,
            "cache_key": interpretation.cache_key,
            "contract_version": interpretation.contract_version,
            "input_contract_version": interpretation.input_contract_version,
            "preprocessing_version": interpretation.preprocessing_version,
        },
    )


def _project_table_interpretation(interpretation: TableInterpretation) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=interpretation.interpretation_id,
        fact_kind=FactKind.SEMANTIC_INTERPRETATION,
        status=_enum_value(interpretation.analysis_status),
        scope=AssistantScope(
            page_id=interpretation.page_id,
            table_id=interpretation.table_id,
        ),
        value=_to_plain(interpretation),
        source_system=SOURCE_SYSTEM,
        recognition_run_id=interpretation.recognition_run_id,
        payload_ref=interpretation.payload_ref,
        model_profile=interpretation.model_profile,
        prompt_version=interpretation.prompt_version,
        evidence_refs=(
            EvidenceRef(
                page_id=interpretation.page_id,
                recognition_run_id=interpretation.recognition_run_id,
                payload_ref=interpretation.payload_ref,
            ),
        ),
        evidence_metadata={
            "status": _enum_value(interpretation.analysis_status),
            "table_id": interpretation.table_id,
            "caption_ref": interpretation.caption_ref,
            "supported_by_observation_ids": interpretation.supported_by_observation_ids,
            "cache_key": interpretation.cache_key,
            "contract_version": interpretation.contract_version,
            "input_contract_version": interpretation.input_contract_version,
            "preprocessing_version": interpretation.preprocessing_version,
        },
    )


def _project_candidate(
    candidate: RecognitionCandidateEvidence,
    recognition_run_id: str,
    index: int,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=f"candidate:{recognition_run_id}:{index}",
        fact_kind=FactKind.CANDIDATE_RELATION,
        status=candidate.status,
        scope=None,
        value=_to_plain(candidate),
        confidence=candidate.confidence,
        source_system=SOURCE_SYSTEM,
        recognition_run_id=recognition_run_id,
        evidence_metadata={
            "status": candidate.status,
            "relation_type": candidate.relation_type,
            "source_target_id": candidate.source_target_id,
            "supporting_target_ids": candidate.supporting_target_ids,
            "candidate_group_id": None,
        },
    )


def _project_diagnostic(result: SemanticRecognitionResult) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=f"diagnostic:{result.recognition_run_id}",
        fact_kind=FactKind.DIAGNOSTIC,
        scope=None,
        value={
            "run_status": result.status,
            "persisted": result.persisted,
            "error_summary": result.error_summary,
            "summary": _to_plain(result.summary),
            "usage_summary": _to_plain(result.usage_summary),
            "cost_summary": _to_plain(result.cost_summary),
            "latency_summary": _to_plain(result.latency_summary),
            "attempt_statuses": tuple(_enum_value(attempt.status) for attempt in result.attempts),
            "payload_ref": result.payload_ref,
            "warnings": tuple(result.warnings),
        },
        source_system=SOURCE_SYSTEM,
        recognition_run_id=result.recognition_run_id,
        payload_ref=result.payload_ref,
        evidence_metadata={
            "run_status": result.status,
            "persisted": result.persisted,
        },
    )


def _enum_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, Enum):
        return value.value
    return str(value)


def _bbox_mapping(bbox: object) -> dict[str, float]:
    return {
        "x_min": float(bbox.x_min),
        "y_min": float(bbox.y_min),
        "x_max": float(bbox.x_max),
        "y_max": float(bbox.y_max),
    }


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
