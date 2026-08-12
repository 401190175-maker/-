"""Semantic recognition orchestration for dry-run and write-back facade calls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from .semantic_cache import SemanticCacheKeyInput, build_semantic_cache_key
from .semantic_client import MultimodalRecognitionClient, RecognitionClientRequest
from .semantic_models import (
    BasicInfoInterpretation,
    BlockInterpretation,
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


class SemanticRecognitionService:
    """Run single-page recognition through an injected multimodal client."""

    def __init__(
        self,
        client: MultimodalRecognitionClient,
        run_log: object | None = None,
        semantic_repository: object | None = None,
        input_builder: object | None = None,
        cache_service: object | None = None,
    ):
        self.client = client
        self.run_log = run_log
        self.semantic_repository = semantic_repository
        self.input_builder = input_builder
        self.cache_service = cache_service

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
                task_type="text_observation",
                required_outputs=("observation",),
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
        )
        if not pending_targets:
            return SemanticRecognitionResult(
                recognition_run_id=f"run:temp:{uuid4()}",
                status="succeeded",
                observations=tuple(cached_observations),
                persisted=False,
                error_summary=None,
                interpretations=tuple(cached_interpretations),
            )
        run_id = f"run:temp:{uuid4()}"
        run_summary = None
        if write_back:
            if self.run_log is None:
                raise ToolModelError("RUN_LOG_UNAVAILABLE", "recognition run log is not configured")
            if self.semantic_repository is None:
                raise ToolModelError("SEMANTIC_EVIDENCE_UNAVAILABLE", "semantic evidence repository is not configured")
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
            )
            run_id = run_summary.recognition_run_id
        try:
            (
                observations,
                interpretations,
                result_status,
                model_name,
                model_version,
                error_message,
            ) = self._recognize_pending(
                page_facts=page_facts,
                pending_targets=pending_targets,
                image_inputs=image_inputs,
                cache_keys=cache_keys,
                model_profile=model_profile,
                prompt_version=prompt_version,
                run_id=run_id,
            )
        except Exception as exc:
            if write_back and run_summary is not None:
                self.run_log.fail_run(run_id, _error_summary(exc))
            if isinstance(exc, ToolModelError):
                raise
            raise ToolModelError("RECOGNITION_FAILED", "semantic recognition failed") from exc
        if write_back:
            try:
                if observations:
                    self.semantic_repository.save_observations(observations)
                if interpretations:
                    self.semantic_repository.save_interpretations(interpretations)
            except Exception as exc:
                if run_summary is not None:
                    self.run_log.fail_run(run_id, _error_summary(exc))
                if isinstance(exc, ToolModelError) and exc.category == "SEMANTIC_EVIDENCE_UNAVAILABLE":
                    raise
                raise ToolModelError("SEMANTIC_EVIDENCE_UNAVAILABLE", "semantic evidence write-back failed") from exc
            self.run_log.complete_run(
                run_id,
                model_name=model_name,
                model_version=model_version,
            )
        return SemanticRecognitionResult(
            recognition_run_id=run_id,
            status=result_status,
            observations=observations,
            persisted=write_back,
            error_summary=error_message,
            interpretations=interpretations,
        )

    def _partition_targets(
        self,
        page_facts: PageSourceFacts,
        targets: tuple[SemanticTargetInput, ...],
        model_profile: str,
        prompt_version: str,
        contract_version: str,
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
            cached = (
                self.cache_service.get(cache_key)
                if cache_key is not None and self.cache_service is not None
                else None
            )
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

    def _recognize_pending(
        self,
        *,
        page_facts: PageSourceFacts,
        pending_targets: tuple[SemanticTargetInput, ...],
        image_inputs,
        cache_keys,
        model_profile: str,
        prompt_version: str,
        run_id: str,
    ):
        """只对未命中目标调用供应商，并把新证据写入缓存。"""

        refs = tuple(
            (
                target.target_element_id,
                target.target_type,
                target.bbox,
                target.normalized_bbox,
            )
            for target in pending_targets
            if (
                target.target_element_id is not None
                and target.bbox is not None
                and target.normalized_bbox is not None
            )
        )
        if not refs:
            raise ToolModelError(
                "INVALID_ARGUMENT",
                "pending targets require element id and bboxes",
            )
        result = self.client.recognize(
            RecognitionClientRequest(
                page_id=page_facts.page_id,
                image_path=page_facts.image_path or "unknown",
                targets=refs,
                model_profile=model_profile,
                prompt_version=prompt_version,
                target_inputs=tuple(pending_targets),
            )
        )
        try:
            observations = tuple(
                _observation(
                    item,
                    page_facts,
                    run_id,
                    model_profile,
                    prompt_version,
                    image_inputs,
                    cache_keys,
                )
                for item in result.observations
            )
            interpretations = tuple(
                interpretation
                for item in result.interpretations
                if (interpretation := _interpretation(item, page_facts, run_id))
                is not None
            )
        except ToolModelError as exc:
            raise ToolModelError("RECOGNITION_FAILED", "recognition output failed validation") from exc
        if self.cache_service is not None:
            for element_id, cache_key in cache_keys.items():
                element_evidence = tuple(
                    item
                    for item in (*observations, *interpretations)
                    if _evidence_element_id(item) == element_id
                )
                if element_evidence:
                    self.cache_service.put(cache_key, element_evidence)
        return (
            observations,
            interpretations,
            result.status,
            result.model_name,
            result.model_version,
            result.error_message,
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


def _target_bbox(target_element_id: str, page_facts: PageSourceFacts, normalized: bool):
    for element in page_facts.elements:
        if element.element_id == target_element_id:
            return element.normalized_bbox if normalized else element.bbox
    raise ToolModelError("NOT_FOUND", "recognition output referenced an unknown target element")


def _observation(
    item,
    page_facts: PageSourceFacts,
    run_id: str,
    model_profile: str,
    prompt_version: str,
    image_inputs,
    cache_keys,
) -> TextObservation:
    target_element_id = item["target_element_id"]
    image_input = image_inputs.get(target_element_id)
    return TextObservation(
        observation_id=f"obs:{run_id}:{target_element_id}",
        recognition_run_id=run_id,
        target_element_id=target_element_id,
        target_element_type=item["target_element_type"],
        page_id=page_facts.page_id,
        raw_text=item["raw_text"],
        normalized_text=item["normalized_text"],
        bbox=_target_bbox(target_element_id, page_facts, normalized=False),
        normalized_bbox=_target_bbox(target_element_id, page_facts, normalized=True),
        confidence=item["confidence"],
        status=item["status"],
        image_hash=item.get("image_hash") or (image_input.image_hash if image_input is not None else None),
        cache_key=item.get("cache_key") or cache_keys.get(target_element_id),
        model_profile=model_profile,
        prompt_version=prompt_version,
        created_at=_now(),
    )


def _interpretation(
    item,
    page_facts: PageSourceFacts,
    run_id: str,
) -> BlockInterpretation | BasicInfoInterpretation | TableInterpretation | None:
    target_element_id = item["target_element_id"]
    target_element_type = item.get("target_element_type")
    interpretation_id = f"interpretation:{run_id}:{target_element_id}"
    if target_element_type == "DrawingBlock":
        return BlockInterpretation(
            interpretation_id=interpretation_id,
            recognition_run_id=run_id,
            block_id=target_element_id,
            page_id=page_facts.page_id,
            summary=item.get("summary") or "",
            interpreted_type=item.get("interpreted_type"),
            components=item.get("components") or (),
            materials=item.get("materials") or (),
            dimensions=item.get("dimensions") or (),
            construction_features=item.get("construction_features") or (),
            spatial_relations=item.get("spatial_relations") or (),
            analysis_status=item.get("analysis_status") or "interpreted",
            uncertainties=item.get("uncertainties") or (),
            supported_by_observation_ids=item.get("supported_by_observation_ids") or (),
            payload_ref=item.get("payload_ref"),
            cache_key=item.get("cache_key"),
            contract_version=item.get("contract_version") or "1",
        )
    if target_element_type == "DrawingBasicInfo":
        return BasicInfoInterpretation(
            interpretation_id=interpretation_id,
            recognition_run_id=run_id,
            basic_info_id=target_element_id,
            page_id=page_facts.page_id,
            raw_text=item.get("raw_text") or "",
            summary=item.get("summary") or "",
            project_name=item.get("project_name"),
            drawing_name=item.get("drawing_name"),
            discipline=item.get("discipline"),
            drawing_number=item.get("drawing_number"),
            scale=item.get("scale"),
            date=item.get("date"),
            analysis_status=item.get("analysis_status") or "interpreted",
            uncertainties=item.get("uncertainties") or (),
            supported_by_observation_ids=item.get("supported_by_observation_ids") or (),
            payload_ref=item.get("payload_ref"),
            cache_key=item.get("cache_key"),
            contract_version=item.get("contract_version") or "1",
        )
    if target_element_type == "Table":
        return TableInterpretation(
            interpretation_id=interpretation_id,
            recognition_run_id=run_id,
            table_id=target_element_id,
            page_id=page_facts.page_id,
            summary=item.get("summary") or "",
            caption_ref=item.get("caption_ref"),
            analysis_status=item.get("analysis_status") or "interpreted",
            uncertainties=item.get("uncertainties") or (),
            supported_by_observation_ids=item.get("supported_by_observation_ids") or (),
            payload_ref=item.get("payload_ref"),
            cache_key=item.get("cache_key"),
            contract_version=item.get("contract_version") or "1",
        )
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _error_summary(error: Exception) -> str:
    if isinstance(error, ToolModelError):
        return error.category
    return error.__class__.__name__


__all__ = ("SemanticRecognitionResult", "SemanticRecognitionService")
