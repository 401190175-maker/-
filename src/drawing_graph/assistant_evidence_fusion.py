"""Evidence fusion (05) orchestration service and input validation.

本模块是 05 唯一编排入口。输入校验先于任何投影/规范化/写回；fatal 输入
错误抛出稳定脱敏 ``FusionInputError``，下游组件与写回 port 零调用。
"""

from __future__ import annotations

import dataclasses
from typing import Sequence

from dataclasses import dataclass

from .assistant_answerability import AnswerabilityEvaluator
from .assistant_cache_closure import CacheClosureEvaluator
from .assistant_claim_support import ClaimSupportEvaluator, RequirementCapabilityMapper
from .assistant_evidence_freshness import EvidenceFreshnessEvaluator
from .assistant_evidence_conflicts import EvidenceConflictDetector
from .assistant_evidence_deduplication import EvidenceDeduplicator
from .assistant_evidence_fusion_models import (
    ClaimSupportAssessment,
    ClaimSupportStatus,
    ConflictRecord,
    EvidenceBundle,
    EvidenceFusionRequest,
    EvidenceProvenance,
    FUSION_CONTRACT_VERSION,
    FusionEvidence,
    WriteBackResult,
    WriteBackStatus,
)
from .assistant_evidence_lineage import EvidenceLineageResolver, StalePolicyRegistry
from .assistant_evidence_normalization import EvidenceNormalizer
from .assistant_models import (
    AssistantScope,
    EvidenceItem,
    EvidenceType,
    FactKind,
    ReasonCode,
    RecognitionPolicy,
)
from .assistant_recognition_projection import RecognitionEvidenceProjector


class FusionInputError(ValueError):
    """融合输入不一致时抛出的稳定脱敏错误。"""

    def __init__(self, reason_code: ReasonCode, message: str):
        self.reason_code = reason_code
        super().__init__(message)


@dataclass(frozen=True)
class FusionResourceLimits:
    """融合各集合的确定性资源上限；非法配置被拒绝。"""

    max_evidence: int = 1000
    max_recognition_results: int = 100
    max_conflicts: int = 1000
    max_provenance: int = 100

    def __post_init__(self) -> None:
        for field_name in (
            "max_evidence",
            "max_recognition_results",
            "max_conflicts",
            "max_provenance",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")


_STALE_ELIGIBLE_KINDS = frozenset(
    {FactKind.SEMANTIC_OBSERVATION, FactKind.SEMANTIC_INTERPRETATION}
)

_EVIDENCE_TYPE_BY_KIND = {
    FactKind.SEMANTIC_OBSERVATION: EvidenceType.TEXT_OBSERVATIONS,
    FactKind.SEMANTIC_INTERPRETATION: EvidenceType.STRUCTURED_INTERPRETATIONS,
}


def validate_fusion_input(request: EvidenceFusionRequest) -> None:
    """校验 request/subrequest/decision/result/policy 的关联一致性。"""

    assistant_request = request.assistant_request
    question_result = request.question_result
    retrieval_bundle = request.retrieval_bundle
    decision = request.semantic_gap_decision
    policy = request.write_back_policy

    request_ids = {
        assistant_request.request_id,
        question_result.request_id,
        retrieval_bundle.request_id,
        decision.request_id,
    }
    if len(request_ids) != 1:
        raise FusionInputError(
            ReasonCode.FUSION_INPUT_INVALID,
            "request IDs across AssistantRequest/QuestionUnderstandingResult/"
            "RetrievalBundle/SemanticGapDecision must be identical",
        )

    subrequest_ids = [subrequest.subrequest_id for subrequest in question_result.subrequests]
    if len(subrequest_ids) != len(set(subrequest_ids)):
        raise FusionInputError(
            ReasonCode.FUSION_INPUT_INVALID,
            "subrequest IDs must be unique",
        )

    if policy is not None and policy.request_allow_write_back and not assistant_request.allow_write_back:
        raise FusionInputError(
            ReasonCode.FUSION_INPUT_INVALID,
            "write-back policy cannot broaden the AssistantRequest authorization",
        )

    _validate_recognition_results(request.recognition_results)


def _validate_recognition_results(results: Sequence[object]) -> None:
    status_by_run: dict[str, str] = {}
    for result in results:
        run_id = getattr(result, "recognition_run_id", None)
        status = getattr(result, "status", None)
        if run_id is None:
            continue
        if run_id in status_by_run and status_by_run[run_id] != status:
            raise FusionInputError(
                ReasonCode.FUSION_INPUT_INVALID,
                f"recognition run {run_id} carries contradictory statuses",
            )
        status_by_run[run_id] = status


class EvidenceFusionService:
    """05 唯一编排入口，固定执行融合流水线。"""

    def __init__(
        self,
        projector: RecognitionEvidenceProjector | None = None,
        normalizer: EvidenceNormalizer | None = None,
        deduplicator: EvidenceDeduplicator | None = None,
        lineage_resolver: EvidenceLineageResolver | None = None,
        conflict_detector: EvidenceConflictDetector | None = None,
        claim_evaluator: ClaimSupportEvaluator | None = None,
        answerability_evaluator: AnswerabilityEvaluator | None = None,
        cache_closure_evaluator: CacheClosureEvaluator | None = None,
        controlled_write_port: object | None = None,
        resource_limits: FusionResourceLimits | None = None,
    ) -> None:
        self.projector = projector or RecognitionEvidenceProjector()
        self.normalizer = normalizer or EvidenceNormalizer()
        self.deduplicator = deduplicator or EvidenceDeduplicator()
        self.lineage_resolver = lineage_resolver or EvidenceLineageResolver()
        self.conflict_detector = conflict_detector or EvidenceConflictDetector()
        self.claim_evaluator = claim_evaluator or ClaimSupportEvaluator()
        self.answerability_evaluator = answerability_evaluator or AnswerabilityEvaluator()
        self.cache_closure_evaluator = cache_closure_evaluator or CacheClosureEvaluator()
        self.controlled_write_port = controlled_write_port
        self.resource_limits = resource_limits or FusionResourceLimits()

    def fuse(self, request: EvidenceFusionRequest) -> EvidenceBundle:
        """固定执行 校验 -> 收集 -> 投影 -> 规范化 -> 去重 -> lineage -> 冲突
        -> claim -> answerability -> 可选写回 -> bundle。"""

        validate_fusion_input(request)

        evidence: list[EvidenceItem] = list(_collect_evidence(request.retrieval_bundle))

        if len(request.recognition_results) > self.resource_limits.max_recognition_results:
            raise FusionInputError(
                ReasonCode.RESULT_TRUNCATED,
                "recognition results exceed the resource limit",
            )

        recognition_evidence_ids: set[str] = set()
        for recognition_result in request.recognition_results:
            projection = self.projector.project(
                recognition_result,
                request.semantic_gap_decision.selected_targets,
            )
            recognition_evidence_ids.update(
                item.evidence_id for item in projection.evidence
            )
            evidence.extend(projection.evidence)

        truncated = False
        if len(evidence) > self.resource_limits.max_evidence:
            evidence = sorted(evidence, key=lambda item: item.evidence_id)[
                : self.resource_limits.max_evidence
            ]
            truncated = True

        normalization = self.normalizer.normalize(tuple(evidence))
        dedup = self.deduplicator.deduplicate(normalization.normalized)

        current_evidence = self._mark_request_current(
            dedup.deduplicated,
            request.question_result.required_evidence,
            request.retrieval_bundle,
            frozenset(recognition_evidence_ids),
        )

        lineage_result = self.lineage_resolver.resolve(current_evidence)

        conflicts = self.conflict_detector.detect(current_evidence)

        assessments = self.claim_evaluator.evaluate(
            request.question_result.required_evidence,
            current_evidence,
            conflicts,
            subrequest_id=request.question_result.subrequest_id,
        )

        answerability = self.answerability_evaluator.evaluate(
            request.question_result,
            assessments,
            conflicts,
            request.semantic_gap_decision,
        )

        write_back_result = self._execute_write_back(request)

        cache_summary = self.cache_closure_evaluator.evaluate(
            request.semantic_gap_decision.cache_candidates,
            _cache_outcomes(request.recognition_results),
            lineage=lineage_result,
            write_back_result=write_back_result,
        )

        reason_codes = list(normalization.reason_codes)
        if truncated:
            reason_codes.append(ReasonCode.RESULT_TRUNCATED)

        accepted_evidence, conflicting_evidence = _split_evidence(
            current_evidence,
            conflicts,
        )
        provenance = _build_provenance(current_evidence)
        overall_confidence = _overall_confidence(accepted_evidence)
        unsupported_claims = _unsupported_claims(assessments)
        warnings = _build_warnings(truncated, normalization, cache_summary, write_back_result)

        return EvidenceBundle(
            request_id=request.assistant_request.request_id,
            subrequest_id=request.retrieval_bundle.subrequest_id,
            accepted_evidence=accepted_evidence,
            conflicting_evidence=conflicting_evidence,
            conflicts=conflicts,
            claim_support=assessments,
            unsupported_claims=unsupported_claims,
            lineage=lineage_result.lineages,
            cache_summary=cache_summary,
            provenance=provenance,
            overall_confidence=overall_confidence,
            answerability=answerability,
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            warnings=warnings,
            write_back_result=write_back_result,
            contract_version=FUSION_CONTRACT_VERSION,
        )

    def _mark_request_current(
        self,
        evidence: Sequence[FusionEvidence],
        requirements: Sequence[object],
        bundle,
        recognition_evidence_ids: frozenset[str],
    ) -> tuple[FusionEvidence, ...]:
        """把请求内证据标记为 current，供 claim support 的 freshness gate 消费。

        方案只对语义证据层定义 stale（原图/bbox/模型/提示词/规则版本变化时旧
        解析失效）：来源事实、派生关系、候选/正式关系与诊断本次请求刚从 live
        图谱读取，没有 stale 概念，直接标记 current；语义 observation/
        interpretation 若来自本次识别结果（刚产生）也标记 current，否则按
        03 的 freshness 规则评估并写入 ``freshness_result``，缺元数据时
        fail-closed 保持 not current，不伪造 current。
        """

        requirement_by_type = {
            requirement.evidence_type: requirement
            for requirement in requirements
        }
        evaluator = EvidenceFreshnessEvaluator()
        policy = RecognitionPolicy()
        updated: list[FusionEvidence] = []
        for fusion in evidence:
            metadata = fusion.metadata
            kind = fusion.item.fact_kind
            if kind not in _STALE_ELIGIBLE_KINDS:
                updated.append(
                    dataclasses.replace(
                        fusion,
                        metadata=dataclasses.replace(
                            metadata,
                            is_current_for_request=True,
                        ),
                    )
                )
                continue
            if fusion.item.evidence_id in recognition_evidence_ids:
                updated.append(
                    dataclasses.replace(
                        fusion,
                        metadata=dataclasses.replace(
                            metadata,
                            is_current_for_request=True,
                        ),
                    )
                )
                continue
            evidence_type = _EVIDENCE_TYPE_BY_KIND.get(kind)
            requirement = (
                requirement_by_type.get(evidence_type)
                if evidence_type is not None
                else None
            )
            freshness = evaluator.evaluate_evidence(
                (fusion.item,),
                policy,
                bundle,
                requirement,
            )[0]
            updated.append(
                dataclasses.replace(
                    fusion,
                    metadata=dataclasses.replace(
                        metadata,
                        freshness_result=freshness,
                        is_current_for_request=freshness.is_current,
                    ),
                )
            )
        return tuple(updated)

    def _execute_write_back(self, request: EvidenceFusionRequest) -> WriteBackResult | None:
        policy = request.write_back_policy
        if policy is None or not policy.request_allow_write_back:
            return WriteBackResult(status=WriteBackStatus.NOT_REQUESTED)
        if self.controlled_write_port is None:
            return WriteBackResult(
                status=WriteBackStatus.SKIPPED,
                reason_codes=(ReasonCode.PERSISTENCE_UNAVAILABLE,),
            )
        batch = _first_write_batch(request.recognition_results)
        if batch is None:
            return WriteBackResult(
                status=WriteBackStatus.SKIPPED,
                reason_codes=(ReasonCode.PERSISTENCE_UNAVAILABLE,),
            )
        return self.controlled_write_port.persist(batch, policy)


def _collect_evidence(bundle) -> tuple[EvidenceItem, ...]:
    buckets = (
        bundle.source_facts,
        bundle.derived_relations,
        bundle.semantic_observations,
        bundle.semantic_interpretations,
        bundle.candidate_relations,
        bundle.formal_relations,
        bundle.diagnostics,
    )
    return tuple(item for bucket in buckets for item in bucket)


def _blocking_evidence_ids(conflicts: Sequence[ConflictRecord]) -> frozenset[str]:
    """收集所有阻断冲突涉及的证据 ID，用于 accepted/conflicting 分桶。"""

    ids: set[str] = set()
    for conflict in conflicts:
        if conflict.blocks_answer:
            ids.update(conflict.evidence_ids)
    return frozenset(ids)


def _split_evidence(
    evidence: Sequence[FusionEvidence],
    conflicts: Sequence[ConflictRecord],
) -> tuple[tuple[FusionEvidence, ...], tuple[FusionEvidence, ...]]:
    """把去重后的证据分成 accepted 与 conflicting 两桶，不选择冲突 winner。"""

    blocking = _blocking_evidence_ids(conflicts)
    accepted = tuple(item for item in evidence if item.item.evidence_id not in blocking)
    conflicting = tuple(item for item in evidence if item.item.evidence_id in blocking)
    return accepted, conflicting


def _build_provenance(evidence: Sequence[FusionEvidence]) -> tuple[EvidenceProvenance, ...]:
    """从 surviving/merged 证据稳定投影最小来源信息，不复制完整 payload。"""

    return tuple(
        EvidenceProvenance(
            source_call_id=item.item.source_call_id,
            recognition_run_id=item.item.recognition_run_id,
            attempt_ids=(),
            payload_ref=item.item.payload_ref,
            rule_version=item.item.rule_version,
            evidence_refs=item.item.evidence_refs,
        )
        for item in evidence
    )


def _overall_confidence(evidence: Sequence[FusionEvidence]) -> float | None:
    """按已批准证据的置信度均值确定性地计算整体置信度。

    不读取文本模型结果；候选证据的高置信度不改变其 fact kind。
    """

    confidences = [
        item.item.confidence
        for item in evidence
        if item.item.confidence is not None
    ]
    if not confidences:
        return None
    return round(sum(confidences) / len(confidences), 4)


_NON_GENERATING_STATUSES = frozenset(
    {
        ClaimSupportStatus.UNSUPPORTED,
        ClaimSupportStatus.MISSING,
        ClaimSupportStatus.STALE_ONLY,
    }
)


def _unsupported_claims(
    assessments: Sequence[ClaimSupportAssessment],
) -> tuple[str, ...]:
    """把 unsupported/missing/stale-only 投影为稳定 requirement/capability 标识。"""

    identifiers: list[str] = []
    for assessment in assessments:
        if assessment.status not in _NON_GENERATING_STATUSES:
            continue
        capability = assessment.claim_capability
        if capability is not None:
            identifiers.append(f"{assessment.requirement_id}:{capability.value}")
        else:
            identifiers.append(assessment.requirement_id)
    return tuple(sorted(dict.fromkeys(identifiers)))


def _build_warnings(
    truncated: bool,
    normalization,
    cache_summary,
    write_back_result,
) -> tuple[str, ...]:
    """把 05 阶段的安全、截断和降级信息稳定投影为已脱敏 warnings。

    ``write_back_result=not_requested`` 不产生工程 warning。
    """

    warnings: list[str] = []
    if truncated:
        warnings.append("result truncated to the evidence resource limit")
    isolated = getattr(normalization, "isolated", ())
    if isolated:
        warnings.append(
            f"{len(isolated)} evidence items could not be normalized and were isolated"
        )
    if cache_summary is not None:
        warnings.extend(getattr(cache_summary, "warnings", ()))
    if (
        write_back_result is not None
        and write_back_result.status is not WriteBackStatus.NOT_REQUESTED
    ):
        warnings.extend(getattr(write_back_result, "warnings", ()))
    return tuple(dict.fromkeys(warnings))


def _first_write_batch(results: Sequence[object]) -> object | None:
    for result in results:
        batch = getattr(result, "write_batch", None)
        if batch is not None:
            return batch
    return None


def _cache_outcomes(results: Sequence[object]) -> tuple[object, ...]:
    outcomes: list[object] = []
    for result in results:
        outcomes.extend(getattr(result, "cache_outcomes", ()))
    return tuple(outcomes)
