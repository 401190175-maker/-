"""Semantic recognition orchestration for dry-run and write-back facade calls."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from uuid import uuid4

from .assistant_evidence_fusion_models import SemanticWriteBatch
from .recognition_execution import MultimodalRecognitionExecutionService
from .recognition_metrics import RecognitionRateCard, RecognitionUsageMeter
from .recognition_models import (
    CacheOutcome,
    RecognitionAttempt,
    RecognitionCandidateEvidence,
    RecognitionCostSummary,
    RecognitionExecutionPolicy,
    RecognitionExecutionRequest,
    RecognitionExecutionResult,
    RecognitionLatencySummary,
    RecognitionProviderUsage,
)
from .recognition_tasks import RecognitionTaskRegistry, build_default_task_registry
from .semantic_cache import (
    RequestSemanticMemo,
    SemanticCacheKeyInput,
    build_semantic_cache_key,
)
from .semantic_client import FakeMultimodalRecognitionClient, MultimodalRecognitionClient
from .semantic_models import (
    BasicInfoInterpretation,
    BlockInterpretation,
    PageSummaryResult,
    TableInterpretation,
    TextObservation,
)
from .tool_models import BBox, PageSourceFacts, SemanticTargetInput, ToolModelError


@dataclass(frozen=True)
class SemanticRecognitionResult:
    recognition_run_id: str
    status: str
    observations: tuple[TextObservation, ...]
    persisted: bool
    error_summary: str | None = None
    interpretations: tuple[BlockInterpretation | BasicInfoInterpretation | TableInterpretation, ...] = ()
    summary: PageSummaryResult | None = None
    candidate_evidence: tuple[RecognitionCandidateEvidence, ...] = ()
    attempts: tuple[RecognitionAttempt, ...] = ()
    usage_summary: RecognitionProviderUsage | None = None
    cost_summary: RecognitionCostSummary | None = None
    latency_summary: RecognitionLatencySummary | None = None
    payload_ref: str | None = None
    warnings: tuple[str, ...] = ()
    cache_outcomes: tuple[CacheOutcome, ...] = ()
    write_batch: SemanticWriteBatch | None = None


class SemanticRecognitionService:
    """Run single-page recognition through an injected multimodal client."""

    def __init__(
        self,
        client: MultimodalRecognitionClient | None = None,
        run_log: object | None = None,
        semantic_repository: object | None = None,
        input_builder: object | None = None,
        cache_service: object | None = None,
        execution_service: MultimodalRecognitionExecutionService | None = None,
        task_registry: RecognitionTaskRegistry | None = None,
        usage_meter: RecognitionUsageMeter | None = None,
        rate_card: RecognitionRateCard | None = None,
        payload_store: object | None = None,
        attempt_log: object | None = None,
        execution_policy: RecognitionExecutionPolicy | None = None,
        request_memo_factory: object | None = None,
    ):
        if execution_service is None:
            provider = client or FakeMultimodalRecognitionClient()
            execution_service = MultimodalRecognitionExecutionService(provider=provider)
        self.execution_service = execution_service
        self.client = client or getattr(execution_service, "provider", None)
        self.run_log = run_log
        self.semantic_repository = semantic_repository
        self.input_builder = input_builder
        self.cache_service = cache_service
        self.task_registry = task_registry or build_default_task_registry()
        self.usage_meter = usage_meter or RecognitionUsageMeter()
        self.rate_card = rate_card or RecognitionRateCard(
            provider="unknown",
            model="unknown",
            currency="USD",
            version_id="unversioned",
        )
        self.payload_store = payload_store
        self.attempt_log = attempt_log
        self.default_execution_policy = execution_policy or RecognitionExecutionPolicy()
        self.request_memo_factory = request_memo_factory or RequestSemanticMemo

    def recognize_page(
        self,
        page_facts: PageSourceFacts,
        target_types: tuple[str, ...],
        model_profile: str = "default",
        prompt_version: str = "default",
        write_back: bool = False,
    ) -> SemanticRecognitionResult:
        """按页面元素批量识别，兼容旧入口；内部转为精确目标路径。"""

        targets = tuple(
            SemanticTargetInput(
                target_id=f"target:{element.element_id}",
                page_id=page_facts.page_id,
                target_element_id=element.element_id,
                target_type=element.element_type,
                task_type="element_text_observation",
                required_outputs=("observations",),
                bbox=element.bbox,
                normalized_bbox=element.normalized_bbox,
                output_contract_version="1",
            )
            for element in page_facts.elements
            if not target_types or element.element_type in set(target_types)
        )
        if not targets:
            return SemanticRecognitionResult(
                recognition_run_id=f"run:temp:{uuid4()}",
                status="succeeded",
                observations=(),
                persisted=False,
                error_summary=None,
                interpretations=(),
            )
        return self.recognize_targets(
            page_facts=page_facts,
            targets=targets,
            model_profile=model_profile,
            prompt_version=prompt_version,
            contract_version="1",
            write_back=write_back,
        )

    def recognize_targets(
        self,
        page_facts: PageSourceFacts,
        targets: tuple[SemanticTargetInput, ...],
        model_profile: str = "default",
        prompt_version: str = "default",
        contract_version: str = "1",
        write_back: bool = False,
        execution_policy: RecognitionExecutionPolicy | None = None,
    ) -> SemanticRecognitionResult:
        """按精确目标识别：供应商调用前二次缓存校验，命中不建持久化 run log。"""

        if not isinstance(targets, tuple) or not targets:
            raise ToolModelError("INVALID_ARGUMENT", "targets must be a non-empty tuple")
        for target in targets:
            if not isinstance(target, SemanticTargetInput):
                raise ToolModelError(
                    "INVALID_ARGUMENT",
                    "targets must contain only SemanticTargetInput",
                )
            if target.page_id != page_facts.page_id:
                raise ToolModelError(
                    "INVALID_ARGUMENT",
                    "target page_id must match page facts",
                )
        request_memo = self.request_memo_factory()
        (
            cached_observations,
            cached_interpretations,
            pending_targets,
            image_inputs,
            cache_keys,
        ) = self._partition_targets(
            page_facts,
            targets,
            model_profile,
            prompt_version,
            contract_version,
            request_memo,
        )
        if not pending_targets:
            return SemanticRecognitionResult(
                recognition_run_id=f"run:temp:{uuid4()}",
                status="succeeded",
                observations=tuple(cached_observations),
                persisted=False,
                error_summary=None,
                interpretations=tuple(cached_interpretations),
                cache_outcomes=_build_cache_outcomes(
                    targets, cached_observations, cached_interpretations, pending_targets, cache_keys
                ),
            )
        run_id = f"run:{uuid4()}" if write_back else f"run:temp:{uuid4()}"
        run_summary = None
        if write_back:
            if self.run_log is None:
                raise ToolModelError("RUN_LOG_UNAVAILABLE", "recognition run log is not configured")
            if self.semantic_repository is None:
                raise ToolModelError("SEMANTIC_EVIDENCE_UNAVAILABLE", "semantic evidence repository is not configured")
            if self.attempt_log is None:
                raise ToolModelError("ATTEMPT_LOG_UNAVAILABLE", "recognition attempt log is not configured")
            if self.payload_store is None:
                raise ToolModelError("PAYLOAD_STORE_UNAVAILABLE", "semantic payload store is not configured")
            run_summary = self.run_log.create_run(
                page_id=page_facts.page_id,
                model_profile=model_profile,
                prompt_version=prompt_version,
                input_refs={
                    "page_id": page_facts.page_id,
                    "target_ids": tuple(target.target_id for target in targets),
                    "element_ids": tuple(
                        target.target_element_id for target in targets
                    ),
                },
                write_back=True,
                recognition_run_id=run_id,
            )
        execution_results: list[RecognitionExecutionResult] = []
        targets_by_id = {target.target_id: target for target in targets}
        effective_policy = execution_policy or self.default_execution_policy
        try:
            groups = self._group_pending(
                pending_targets,
                model_profile,
                prompt_version,
                contract_version,
            )
            for _, group in groups:
                request = RecognitionExecutionRequest(
                    request_id=f"req:{uuid4()}",
                    recognition_run_id=run_id,
                    page_id=page_facts.page_id,
                    task_type=group[0].task_type,
                    targets=group,
                    model_profile=model_profile,
                    prompt_version=prompt_version,
                    input_contract_version="1",
                    output_contract_version=group[0].output_contract_version or contract_version,
                    preprocessing_version="preprocess-v1",
                    write_back=write_back,
                    deadline_seconds=effective_policy.deadline_seconds,
                )
                execution_results.append(
                    self.execution_service.execute(
                        request,
                        page_facts,
                        effective_policy,
                    )
                )
            result_status = _merge_execution_status(execution_results)
            (
                observations,
                interpretations,
                error_message,
            ) = _project_execution_results(
                page_facts=page_facts,
                execution_results=execution_results,
                targets_by_id=targets_by_id,
                model_profile=model_profile,
                prompt_version=prompt_version,
                contract_version=contract_version,
                cache_keys=cache_keys,
            )
            observations = (*observations, *cached_observations)
            interpretations = (*interpretations, *cached_interpretations)
            error_message = _first_execution_error(execution_results)
            attempts = tuple(attempt for result in execution_results for attempt in result.attempts)
            usage_summary = self.usage_meter.summarize_usage(attempts)
            cost_summary, latency_summary = self.usage_meter.summarize(attempts, self.rate_card)
            summary = _collect_page_summary(page_facts, execution_results)
            candidate_evidence = _collect_candidate_evidence(execution_results)
            warnings = tuple(warning for result in execution_results for warning in result.warnings)
        except Exception as exc:
            if write_back and run_summary is not None:
                self.run_log.fail_run(run_id, _error_summary(exc))
            if isinstance(exc, ToolModelError):
                raise
            raise ToolModelError("RECOGNITION_FAILED", "semantic recognition failed") from exc
        for element_id, cache_key in cache_keys.items():
            element_evidence = tuple(
                item
                for item in (*observations, *interpretations)
                if _evidence_element_id(item) == element_id
            )
            if cache_key is not None and element_evidence:
                request_memo.put(cache_key, element_evidence)
                if write_back and self.cache_service is not None:
                    self.cache_service.put(cache_key, element_evidence)
        envelope, content_hash = _build_payload_envelope(
            page_id=page_facts.page_id,
            run_id=run_id,
            status=result_status,
            execution_results=execution_results,
            summary=summary,
            candidate_evidence=candidate_evidence,
        )
        write_batch = SemanticWriteBatch(
            recognition_run_id=run_id,
            schema_valid=True,
            scope_valid=True,
            payload_sanitized=True,
            audit_material_complete=True,
            run_summary=run_summary,
            attempts=attempts,
            sanitized_payload_envelope=envelope,
            observations=observations,
            interpretations=interpretations,
            candidate_evidence=candidate_evidence,
            cache_entries=(),
        )
        payload_ref = None
        if write_back:
            try:
                payload_ref = self.persist_validated_batch(write_batch)
            except Exception as exc:
                if run_summary is not None:
                    self.run_log.fail_run(run_id, _error_summary(exc))
                payload_ref = getattr(exc, "payload_ref", None)
                return SemanticRecognitionResult(
                    recognition_run_id=run_id,
                    status=result_status,
                    observations=observations,
                    persisted=False,
                    error_summary=_error_summary(exc),
                    interpretations=interpretations,
                    summary=summary,
                    candidate_evidence=candidate_evidence,
                    attempts=attempts,
                    usage_summary=usage_summary,
                    cost_summary=cost_summary,
                    latency_summary=latency_summary,
                    payload_ref=payload_ref,
                    warnings=warnings,
                )
            try:
                self.run_log.complete_run(
                    run_id,
                    model_name=attempts[0].model_name if attempts else None,
                    model_version=attempts[0].model_name if attempts else None,
                    attempt_ids=tuple(attempt.attempt_id for attempt in attempts),
                    usage_summary=usage_summary,
                    latency_summary=latency_summary,
                    payload_ref=payload_ref,
                    input_contract_version="1",
                    output_contract_version=(
                        pending_targets[0].output_contract_version
                        if pending_targets
                        else "1"
                    ),
                    preprocessing_version="preprocess-v1",
                )
            except Exception as exc:
                if run_summary is not None:
                    self.run_log.fail_run(run_id, _error_summary(exc))
                return SemanticRecognitionResult(
                    recognition_run_id=run_id,
                    status=result_status,
                    observations=observations,
                    persisted=False,
                    error_summary=_error_summary(exc),
                    interpretations=interpretations,
                    summary=summary,
                    candidate_evidence=candidate_evidence,
                    attempts=attempts,
                    usage_summary=usage_summary,
                    cost_summary=cost_summary,
                    latency_summary=latency_summary,
                    payload_ref=payload_ref,
                    warnings=warnings,
                )
        return SemanticRecognitionResult(
            recognition_run_id=run_id,
            status=result_status,
            observations=observations,
            persisted=write_back,
            error_summary=error_message,
            interpretations=interpretations,
            summary=summary,
            candidate_evidence=candidate_evidence,
            attempts=attempts,
            usage_summary=usage_summary,
            cost_summary=cost_summary,
            latency_summary=latency_summary,
            payload_ref=payload_ref,
            warnings=warnings,
            cache_outcomes=_build_cache_outcomes(
                targets, cached_observations, cached_interpretations, pending_targets, cache_keys
            ),
            write_batch=write_batch,
        )

    def persist_validated_batch(self, batch: SemanticWriteBatch) -> str | None:
        """持久化一个已验证批次；不重新调用 provider，不重新生成 run ID。

        若 payload 已成功但语义节点写入失败，异常上会保留 ``payload_ref``
        以便上层按部分成功处理（不伪造全量成功）。
        """

        if batch.sanitized_payload_envelope is None:
            raise ToolModelError("INVALID_ARGUMENT", "batch has no sanitized payload envelope")
        if not (
            batch.schema_valid
            and batch.scope_valid
            and batch.payload_sanitized
            and batch.audit_material_complete
        ):
            raise ToolModelError("INVALID_ARGUMENT", "batch must be schema/scope/payload/audit validated")
        if self.attempt_log is None or self.payload_store is None or self.semantic_repository is None:
            raise ToolModelError("PERSISTENCE_UNAVAILABLE", "persistence dependencies are not configured")
        for attempt in batch.attempts:
            self.attempt_log.append_attempt(attempt)
        envelope = dict(batch.sanitized_payload_envelope)
        content_hash = _envelope_content_hash(envelope)
        payload_ref = self.payload_store.put_payload(envelope, content_hash, contract_version="1")
        try:
            if batch.observations:
                self.semantic_repository.save_observations(batch.observations)
            if batch.interpretations:
                self.semantic_repository.save_interpretations(batch.interpretations)
        except Exception as exc:
            setattr(exc, "payload_ref", payload_ref)
            raise
        return payload_ref

    def _group_pending(
        self,
        pending_targets: tuple[SemanticTargetInput, ...],
        model_profile: str,
        prompt_version: str,
        contract_version: str,
    ):
        """Group cache-miss targets by the execution compatibility key."""

        groups: dict[tuple, list[SemanticTargetInput]] = {}
        for target in pending_targets:
            spec = self.task_registry.get(target.task_type)
            key = (
                target.page_id,
                str(target.task_type),
                model_profile,
                prompt_version,
                "1",
                target.output_contract_version or contract_version,
                "preprocess-v1",
                spec.crop_policy_id,
            )
            groups.setdefault(key, []).append(target)
        ordered: list[tuple[tuple, tuple[SemanticTargetInput, ...]]] = []
        for key in sorted(groups):
            ordered.append((key, tuple(sorted(groups[key], key=lambda item: item.target_id))))
        return ordered

    def _partition_targets(
        self,
        page_facts: PageSourceFacts,
        targets: tuple[SemanticTargetInput, ...],
        model_profile: str,
        prompt_version: str,
        contract_version: str,
        request_memo: RequestSemanticMemo | None = None,
    ):
        """按目标 cache key 划分缓存命中与待识别目标，不做外部调用。"""

        cached_observations: list[TextObservation] = []
        cached_interpretations: list[
            BlockInterpretation | BasicInfoInterpretation | TableInterpretation
        ] = []
        pending_targets: list[SemanticTargetInput] = []
        image_inputs = {}
        cache_keys = {}
        for target in targets:
            element_id = target.target_element_id
            if element_id is None:
                pending_targets.append(target)
                continue
            image_input = self._image_input(page_facts, element_id)
            image_inputs[element_id] = image_input
            cache_key = self._build_cache_key(
                page_facts,
                element_id,
                model_profile,
                prompt_version,
                task_type=target.task_type,
                contract_version=contract_version,
                image_input=image_input,
            )
            cache_keys[element_id] = cache_key
            cached = None
            if cache_key is not None:
                if self.cache_service is not None:
                    cached = self.cache_service.get(cache_key)
                if cached is None and request_memo is not None:
                    cached = request_memo.get(cache_key)
            if cached is not None:
                for item in cached:
                    if isinstance(item, TextObservation):
                        cached_observations.append(item)
                    else:
                        cached_interpretations.append(item)
            else:
                pending_targets.append(target)
        return (
            cached_observations,
            cached_interpretations,
            pending_targets,
            image_inputs,
            cache_keys,
        )

    def _image_input(self, page_facts: PageSourceFacts, element_id: str):
        """构建图片输入，缺 builder 时返回 None。"""

        if self.input_builder is None:
            return None
        return self.input_builder.build_input(page_facts, element_id)

    def _build_cache_key(
        self,
        page_facts: PageSourceFacts,
        element_id: str,
        model_profile: str,
        prompt_version: str,
        *,
        task_type: str = "text_observation",
        contract_version: str = "1",
        image_input=None,
    ) -> str | None:
        """按统一 SemanticCacheKeyInput 构造与 03 目标一致的 cache key。"""

        if self.cache_service is None:
            return None
        if image_input is None:
            image_input = self._image_input(page_facts, element_id)
        if image_input is None:
            return None
        return build_semantic_cache_key(
            SemanticCacheKeyInput(
                image_hash=image_input.image_hash,
                bbox=image_input.bbox,
                target_element_id=element_id,
                task_type=task_type,
                model_profile=model_profile,
                model_version=getattr(self.client, "model_version", "unknown"),
                prompt_version=prompt_version,
                preprocessing_version="preprocess-v1",
                normalization_rule_version="normalize-v1",
                contract_version=contract_version,
            )
        )


def _merge_execution_status(execution_results: list[RecognitionExecutionResult]) -> str:
    """Merge per-group execution statuses into one run-level status."""

    if not execution_results:
        return "succeeded"
    statuses = [str(result.status.value) for result in execution_results]
    if all(status == "succeeded" for status in statuses):
        return "succeeded"
    if any(status == "succeeded" for status in statuses):
        return "partial"
    if any(status == "ambiguous" for status in statuses):
        return "ambiguous"
    if any(status == "not_found" for status in statuses):
        return "not_found"
    return statuses[0]


def _first_execution_error(execution_results: list[RecognitionExecutionResult]) -> str | None:
    """Return the first safe error category from a failed execution group."""

    for result in execution_results:
        if str(result.status.value) == "succeeded":
            continue
        if result.safe_error is not None:
            category = result.safe_error.get("category") or result.safe_error.get("code")
            if category:
                return str(category)
        return str(result.status.value)
    return None


def _project_execution_results(
    *,
    page_facts: PageSourceFacts,
    execution_results: list[RecognitionExecutionResult],
    targets_by_id: dict[str, SemanticTargetInput],
    model_profile: str,
    prompt_version: str,
    contract_version: str,
    cache_keys: dict,
):
    """Project contract-valid execution outputs into existing semantic DTOs."""

    observations: list[TextObservation] = []
    interpretations: list[
        BlockInterpretation | BasicInfoInterpretation | TableInterpretation
    ] = []
    failed_statuses = {"contract_failed", "provider_failed", "deadline_exceeded", "recognition_failed"}
    for result in execution_results:
        if str(result.status.value) in failed_statuses:
            continue
        for output in result.validated_outputs:
            if str(output.status.value) in {"ambiguous", "not_found"}:
                continue
            target = targets_by_id.get(output.target_id)
            if target is None or target.target_element_id is None:
                continue
            element = _find_element(page_facts, target.target_element_id)
            if element is None:
                continue
            output_contract_version = target.output_contract_version or contract_version
            if str(output.task_type.value) == "element_text_observation":
                for item in output.output.get("observations") or ():
                    observations.append(
                        _project_text_observation(
                            item=item,
                            output=output,
                            target=target,
                            element=element,
                            result=result,
                            page_facts=page_facts,
                            model_profile=model_profile,
                            prompt_version=prompt_version,
                            output_contract_version=output_contract_version,
                            cache_keys=cache_keys,
                        )
                    )
            elif str(output.task_type.value) == "section_label_observation":
                observations.append(
                    _project_text_observation(
                        item={
                            "raw_text": output.output.get("raw_label", ""),
                            "normalized_text": output.output.get("normalized_label", ""),
                            "confidence": output.confidence,
                            "status": "confirmed",
                        },
                        output=output,
                        target=target,
                        element=element,
                        result=result,
                        page_facts=page_facts,
                        model_profile=model_profile,
                        prompt_version=prompt_version,
                        output_contract_version=output_contract_version,
                        cache_keys=cache_keys,
                    )
                )
            elif str(output.task_type.value) == "block_semantic_identification":
                block_observations: list[TextObservation] = []
                for index, item in enumerate(output.output.get("observations") or ()):
                    observation = _project_text_observation(
                        item=item,
                        output=output,
                        target=target,
                        element=element,
                        result=result,
                        page_facts=page_facts,
                        model_profile=model_profile,
                        prompt_version=prompt_version,
                        output_contract_version=output_contract_version,
                        cache_keys=cache_keys,
                        observation_id=(
                            f"obs:{result.recognition_run_id}:"
                            f"{target.target_element_id}:{index}"
                        ),
                    )
                    block_observations.append(observation)
                    observations.append(observation)
                interpretations.append(
                    _project_block_interpretation(
                        output=output,
                        target=target,
                        element=element,
                        result=result,
                        page_facts=page_facts,
                        model_profile=model_profile,
                        prompt_version=prompt_version,
                        output_contract_version=output_contract_version,
                        cache_keys=cache_keys,
                        linked_observation_ids=tuple(
                            observation.observation_id
                            for observation in block_observations
                        ),
                    )
                )
            elif str(output.task_type.value) == "basic_info_interpretation":
                interpretations.append(
                    _project_basic_info_interpretation(
                        output=output,
                        target=target,
                        element=element,
                        result=result,
                        page_facts=page_facts,
                        model_profile=model_profile,
                        prompt_version=prompt_version,
                        output_contract_version=output_contract_version,
                        cache_keys=cache_keys,
                    )
                )
            elif str(output.task_type.value) == "table_interpretation":
                interpretations.append(
                    _project_table_interpretation(
                        output=output,
                        target=target,
                        element=element,
                        result=result,
                        page_facts=page_facts,
                        model_profile=model_profile,
                        prompt_version=prompt_version,
                        output_contract_version=output_contract_version,
                        cache_keys=cache_keys,
                    )
                )
    return tuple(observations), tuple(interpretations), None


def _collect_page_summary(
    page_facts: PageSourceFacts,
    execution_results: list[RecognitionExecutionResult],
) -> PageSummaryResult | None:
    """Carry page_summary output as a transient summary, never a graph node."""

    for result in execution_results:
        for output in result.validated_outputs:
            if str(output.task_type.value) != "page_summary":
                continue
            if str(output.status.value) in {"ambiguous", "not_found"}:
                continue
            return PageSummaryResult(
                recognition_run_id=result.recognition_run_id,
                page_id=page_facts.page_id,
                summary=str(output.output.get("summary") or ""),
                key_elements=tuple(output.output.get("key_elements") or ()),
                uncertainties=tuple(output.output.get("uncertainties") or ()),
            )
    return None


def _collect_candidate_evidence(
    execution_results: list[RecognitionExecutionResult],
) -> tuple[RecognitionCandidateEvidence, ...]:
    """Project relation outputs only as candidate_relation evidence."""

    evidence: list[RecognitionCandidateEvidence] = []
    for result in execution_results:
        for output in result.validated_outputs:
            if str(output.task_type.value) != "relation_evidence_extraction":
                continue
            for entry in output.output.get("candidate_evidence") or ():
                evidence.append(
                    RecognitionCandidateEvidence(
                        relation_type=str(entry.get("relation_type") or ""),
                        source_target_id=output.target_id,
                        supporting_target_ids=tuple(entry.get("supporting_ids") or ()),
                        confidence=entry.get("confidence") if entry.get("confidence") is not None else output.confidence,
                        status="candidate_relation",
                    )
                )
    return tuple(evidence)


def _build_payload_envelope(
    *,
    page_id: str,
    run_id: str,
    status: str,
    execution_results: list[RecognitionExecutionResult],
    summary,
    candidate_evidence,
) -> tuple[dict, str]:
    """Build a redactable, immutable audit envelope for one logical run."""

    envelope = {
        "run_id": run_id,
        "page_id": page_id,
        "status": status,
        "execution_results": [
            {
                "status": result.status.value,
                "task_types": sorted(
                    {str(output.task_type.value) for output in result.validated_outputs}
                ),
                "validated_outputs": [
                    {
                        "task_type": output.task_type.value,
                        "target_id": output.target_id,
                        "target_type": output.target_type,
                        "status": output.status.value,
                        "output": dict(output.output),
                        "confidence": output.confidence,
                        "uncertainties": list(output.uncertainties),
                    }
                    for output in result.validated_outputs
                ],
                "attempt_ids": [attempt.attempt_id for attempt in result.attempts],
            }
            for result in execution_results
        ],
        "summary": asdict(summary) if summary is not None else None,
        "candidate_evidence": [asdict(evidence) for evidence in candidate_evidence],
    }
    content = json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return envelope, hashlib.sha256(content.encode("utf-8")).hexdigest()


def _envelope_content_hash(envelope: dict) -> str:
    content = json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _project_text_observation(
    *,
    item,
    output,
    target: SemanticTargetInput,
    element,
    result: RecognitionExecutionResult,
    page_facts: PageSourceFacts,
    model_profile: str,
    prompt_version: str,
    output_contract_version: str,
    cache_keys: dict,
    observation_id: str | None = None,
) -> TextObservation:
    return TextObservation(
        observation_id=observation_id
        or f"obs:{result.recognition_run_id}:{target.target_element_id}",
        recognition_run_id=result.recognition_run_id,
        target_element_id=target.target_element_id,
        target_element_type=target.target_type,
        page_id=page_facts.page_id,
        raw_text=str(item.get("raw_text") or ""),
        normalized_text=str(item.get("normalized_text") or ""),
        bbox=element.bbox,
        normalized_bbox=element.normalized_bbox,
        confidence=float(item.get("confidence") if item.get("confidence") is not None else (output.confidence or 0.0)),
        status=_observation_status(item.get("status") or output.status.value),
        image_hash=page_facts.image_hash,
        cache_key=cache_keys.get(target.target_element_id),
        model_profile=model_profile,
        prompt_version=prompt_version,
        input_contract_version="1",
        output_contract_version=output_contract_version,
        preprocessing_version="preprocess-v1",
        created_at=_now(),
    )


def _project_block_interpretation(
    *,
    output,
    target: SemanticTargetInput,
    element,
    result: RecognitionExecutionResult,
    page_facts: PageSourceFacts,
    model_profile: str,
    prompt_version: str,
    output_contract_version: str,
    cache_keys: dict,
    linked_observation_ids: tuple[str, ...] = (),
) -> BlockInterpretation:
    data = output.output.get("interpretation") or {}
    return BlockInterpretation(
        interpretation_id=f"interpretation:{result.recognition_run_id}:{target.target_element_id}",
        recognition_run_id=result.recognition_run_id,
        block_id=target.target_element_id,
        page_id=page_facts.page_id,
        summary=str(data.get("summary") or ""),
        interpreted_type=data.get("interpreted_type"),
        components=_semantic_text_tuple(data.get("components")),
        materials=_semantic_text_tuple(data.get("materials")),
        dimensions=_semantic_text_tuple(data.get("dimensions")),
        construction_features=_semantic_text_tuple(data.get("construction_features")),
        spatial_relations=_semantic_text_tuple(data.get("spatial_relations")),
        analysis_status=_interpretation_status(data.get("analysis_status")),
        uncertainties=_semantic_text_tuple(data.get("uncertainties")),
        supported_by_observation_ids=_linked_observation_ids(
            data,
            linked_observation_ids,
        ),
        payload_ref=None,
        cache_key=cache_keys.get(target.target_element_id),
        contract_version=output_contract_version,
        model_profile=model_profile,
        prompt_version=prompt_version,
        input_contract_version="1",
        preprocessing_version="preprocess-v1",
    )


def _linked_observation_ids(
    data: Mapping,
    linked_observation_ids: tuple[str, ...],
) -> tuple[str, ...]:
    """把同一输出的 observations 确定性链接为 interpretation 的支撑证据。

    优先使用服务端生成的同 run 同目标 observation ID；模型无法预知稳定
    ID，因此显式声明只在没有可链接 observation 时作为后备。
    """

    if linked_observation_ids:
        return tuple(dict.fromkeys(linked_observation_ids))
    return _semantic_text_tuple(data.get("supported_by_observation_ids"))


def _project_basic_info_interpretation(
    *,
    output,
    target: SemanticTargetInput,
    element,
    result: RecognitionExecutionResult,
    page_facts: PageSourceFacts,
    model_profile: str,
    prompt_version: str,
    output_contract_version: str,
    cache_keys: dict,
) -> BasicInfoInterpretation:
    return BasicInfoInterpretation(
        interpretation_id=f"interpretation:{result.recognition_run_id}:{target.target_element_id}",
        recognition_run_id=result.recognition_run_id,
        basic_info_id=target.target_element_id,
        page_id=page_facts.page_id,
        raw_text=str(output.output.get("raw_text") or ""),
        summary=str(output.output.get("summary") or ""),
        project_name=output.output.get("project_name"),
        drawing_name=output.output.get("drawing_name"),
        discipline=output.output.get("discipline"),
        drawing_number=output.output.get("drawing_number"),
        scale=output.output.get("scale"),
        date=output.output.get("date"),
        analysis_status=_interpretation_status(output.output.get("analysis_status")),
        uncertainties=tuple(output.output.get("uncertainties") or ()),
        supported_by_observation_ids=(),
        payload_ref=None,
        cache_key=cache_keys.get(target.target_element_id),
        contract_version=output_contract_version,
        model_profile=model_profile,
        prompt_version=prompt_version,
        input_contract_version="1",
        preprocessing_version="preprocess-v1",
    )


def _project_table_interpretation(
    *,
    output,
    target: SemanticTargetInput,
    element,
    result: RecognitionExecutionResult,
    page_facts: PageSourceFacts,
    model_profile: str,
    prompt_version: str,
    output_contract_version: str,
    cache_keys: dict,
) -> TableInterpretation:
    return TableInterpretation(
        interpretation_id=f"interpretation:{result.recognition_run_id}:{target.target_element_id}",
        recognition_run_id=result.recognition_run_id,
        table_id=target.target_element_id,
        page_id=page_facts.page_id,
        summary=str(output.output.get("summary") or ""),
        caption_ref=output.output.get("caption_ref"),
        analysis_status=_interpretation_status(output.output.get("analysis_status")),
        uncertainties=tuple(output.output.get("uncertainties") or ()),
        supported_by_observation_ids=(),
        payload_ref=None,
        cache_key=cache_keys.get(target.target_element_id),
        contract_version=output_contract_version,
        model_profile=model_profile,
        prompt_version=prompt_version,
        input_contract_version="1",
        preprocessing_version="preprocess-v1",
    )


def _observation_status(status) -> str:
    mapping = {
        "succeeded": "confirmed",
        "partial": "partial",
        "ambiguous": "ambiguous",
        "not_found": "not_found",
    }
    return mapping.get(str(status), str(status))


def _interpretation_status(status) -> str:
    value = str(status or "").strip().lower()
    mapping = {
        "": "interpreted",
        "succeeded": "interpreted",
        "success": "interpreted",
        "complete": "interpreted",
        "completed": "interpreted",
        "confirmed": "interpreted",
        "interpreted": "interpreted",
        "partial": "partial",
        "ambiguous": "ambiguous",
        "not_found": "not_found",
        "failed": "failed",
        "recognition_failed": "failed",
        "stale": "stale",
    }
    return mapping.get(value, "interpreted")


def _semantic_text_tuple(value) -> tuple[str, ...]:
    if value is None:
        return ()
    values = value if isinstance(value, (list, tuple)) else (value,)
    result: list[str] = []
    for item in values:
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, (dict, list, tuple)):
            text = json.dumps(item, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        else:
            text = str(item).strip()
        if text:
            result.append(text)
    return tuple(result)


def _find_element(page_facts: PageSourceFacts, element_id: str):
    for element in page_facts.elements:
        if element.element_id == element_id:
            return element
    return None


def _evidence_element_id(
    item: TextObservation | BlockInterpretation | BasicInfoInterpretation | TableInterpretation,
) -> str:
    if isinstance(item, TextObservation):
        return item.target_element_id
    if isinstance(item, BlockInterpretation):
        return item.block_id
    if isinstance(item, BasicInfoInterpretation):
        return item.basic_info_id
    return item.table_id


def _build_cache_outcomes(
    targets: tuple[SemanticTargetInput, ...],
    cached_observations: list[TextObservation],
    cached_interpretations: list,
    pending_targets: list[SemanticTargetInput],
    cache_keys: dict,
) -> tuple[CacheOutcome, ...]:
    """逐目标汇总实际缓存处置：hit 必须引用实际可复用 evidence ID。"""

    pending_ids = {target.target_id for target in pending_targets}
    reused_by_element: dict[str, list[str]] = {}
    for observation in cached_observations:
        reused_by_element.setdefault(observation.target_element_id, []).append(
            observation.observation_id
        )
    for interpretation in cached_interpretations:
        element_id = _evidence_element_id(interpretation)
        reused_by_element.setdefault(element_id, []).append(
            interpretation.interpretation_id
        )
    outcomes: list[CacheOutcome] = []
    for target in targets:
        element_id = target.target_element_id
        cache_key = cache_keys.get(element_id)
        provider_called = target.target_id in pending_ids
        if not provider_called:
            reused = tuple(reused_by_element.get(element_id, ()))
            outcomes.append(
                CacheOutcome(
                    target_id=target.target_id,
                    disposition="hit",
                    cache_key=cache_key,
                    reused_evidence_ids=reused,
                    provider_called=False,
                )
            )
        elif cache_key is None:
            outcomes.append(
                CacheOutcome(
                    target_id=target.target_id,
                    disposition="bypassed",
                    cache_key=None,
                    provider_called=True,
                )
            )
        else:
            outcomes.append(
                CacheOutcome(
                    target_id=target.target_id,
                    disposition="miss",
                    cache_key=cache_key,
                    provider_called=True,
                )
            )
    return tuple(outcomes)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _error_summary(error: Exception) -> str:
    if isinstance(error, ToolModelError):
        return error.category
    return error.__class__.__name__


__all__ = ("SemanticRecognitionResult", "SemanticRecognitionService")
