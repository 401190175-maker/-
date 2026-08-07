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
from .tool_models import PageSourceFacts, ToolModelError


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
                    "target_types": tuple(target_types),
                    "element_ids": tuple(element.element_id for element in page_facts.elements),
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
            ) = self._recognize_with_cache(
                page_facts=page_facts,
                target_types=target_types,
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

    def _recognize_with_cache(
        self,
        *,
        page_facts: PageSourceFacts,
        target_types: tuple[str, ...],
        model_profile: str,
        prompt_version: str,
        run_id: str,
    ):
        targets = tuple(
            (element.element_id, element.element_type, element.bbox, element.normalized_bbox)
            for element in page_facts.elements
            if not target_types or element.element_type in set(target_types)
        )
        image_inputs = {}
        cache_keys = {}
        for element_id in tuple(target[0] for target in targets):
            image_input = None
            if self.input_builder is not None:
                image_input = self.input_builder.build_input(page_facts, element_id)
            image_inputs[element_id] = image_input
            if image_input is not None and self.cache_service is not None:
                cache_keys[element_id] = build_semantic_cache_key(
                    SemanticCacheKeyInput(
                        image_hash=image_input.image_hash,
                        bbox=image_input.bbox,
                        target_element_id=element_id,
                        task_type="text_observation",
                        model_profile=model_profile,
                        model_version=getattr(self.client, "model_version", "unknown"),
                        prompt_version=prompt_version,
                        preprocessing_version="preprocess-v1",
                        normalization_rule_version="normalize-v1",
                        contract_version="1",
                    )
                )
        cached_observations: list[TextObservation] = []
        cached_interpretations: list[
            BlockInterpretation | BasicInfoInterpretation | TableInterpretation
        ] = []
        pending_targets = []
        for target in targets:
            cache_key = cache_keys.get(target[0])
            cached = self.cache_service.get(cache_key) if cache_key is not None else None
            if cached is not None:
                for item in cached:
                    if isinstance(item, TextObservation):
                        cached_observations.append(item)
                    else:
                        cached_interpretations.append(item)
            else:
                pending_targets.append(target)
        if not pending_targets:
            return (
                tuple(cached_observations),
                tuple(cached_interpretations),
                "succeeded",
                getattr(self.client, "model_name", None),
                getattr(self.client, "model_version", None),
                None,
            )
        result = self.client.recognize(
            RecognitionClientRequest(
                page_id=page_facts.page_id,
                image_path=page_facts.image_path or "unknown",
                targets=tuple(pending_targets),
                model_profile=model_profile,
                prompt_version=prompt_version,
            )
        )
        try:
            observations = tuple(
                _observation(item, page_facts, run_id, model_profile, prompt_version, image_inputs, cache_keys)
                for item in result.observations
            )
            interpretations = tuple(
                interpretation
                for item in result.interpretations
                if (interpretation := _interpretation(item, page_facts, run_id)) is not None
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
