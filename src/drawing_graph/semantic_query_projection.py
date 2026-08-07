"""Project semantic evidence into stable facade-facing query output."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from .semantic_models import (
    BasicInfoInterpretation,
    BlockInterpretation,
    RecognitionRunSummary,
    TableInterpretation,
    TextObservation,
)
from .tool_models import (
    BlockRelations,
    PageSourceFacts,
    SectionMatchSummary,
    SemanticCandidateRelationSummary,
    SemanticInterpretationSummary,
    SemanticObservationSummary,
    ToolModelError,
)


SUPPORTED_FACT_KINDS = frozenset(
    (
        "source_fact",
        "derived_relation",
        "semantic_observation",
        "semantic_interpretation",
        "candidate_relation",
        "formal_relation",
    )
)


@dataclass(frozen=True)
class SemanticFactItem:
    """One projected fact with an explicit fact kind."""

    fact_kind: str
    fact_id: str
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.fact_kind not in SUPPORTED_FACT_KINDS:
            raise ToolModelError("invalid_fact_kind", "fact_kind must be a supported semantic fact kind")
        _require_text(self.fact_id, "fact_id")
        if not isinstance(self.payload, Mapping):
            raise ToolModelError("invalid_payload", "payload must be a mapping")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True)
class SemanticPageProjection:
    """Unified read-only semantic view for one page."""

    page_id: str
    observation_status: str
    interpretation_status: str
    source_facts: tuple[SemanticFactItem, ...] = ()
    derived_relations: tuple[SemanticFactItem, ...] = ()
    observations: tuple[SemanticObservationSummary, ...] = ()
    interpretations: tuple[SemanticInterpretationSummary, ...] = ()
    candidate_relations: tuple[SemanticCandidateRelationSummary, ...] = ()
    formal_relations: tuple[SectionMatchSummary, ...] = ()
    run_summary: RecognitionRunSummary | None = None
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.page_id, "page_id")
        _require_text(self.observation_status, "observation_status")
        _require_text(self.interpretation_status, "interpretation_status")
        if self.observation_status not in {"recognized", "not_recognized"}:
            raise ToolModelError("invalid_observation_status", "observation_status must be recognized or not_recognized")
        if self.interpretation_status not in {"interpreted", "not_interpreted"}:
            raise ToolModelError(
                "invalid_interpretation_status",
                "interpretation_status must be interpreted or not_interpreted",
            )
        for field_name in (
            "source_facts",
            "derived_relations",
            "observations",
            "interpretations",
            "candidate_relations",
            "formal_relations",
            "warnings",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, tuple):
                raise ToolModelError("invalid_sequence", f"{field_name} must be a tuple")


class SemanticQueryProjection:
    """Combine source facts, relations, evidence, and run summaries into stable output."""

    def project_page(
        self,
        *,
        page_id: str | None = None,
        page_facts: PageSourceFacts | None = None,
        block_relations: BlockRelations | None = None,
        observations: tuple[TextObservation, ...] = (),
        interpretations: tuple[BlockInterpretation | BasicInfoInterpretation | TableInterpretation, ...] = (),
        run_summary: RecognitionRunSummary | None = None,
        candidate_relations: tuple[SemanticCandidateRelationSummary, ...] = (),
        formal_relations: tuple[SectionMatchSummary, ...] = (),
    ) -> SemanticPageProjection:
        """Project one page into distinct source, derived, and semantic collections."""

        if not isinstance(observations, tuple) or not all(isinstance(item, TextObservation) for item in observations):
            raise ToolModelError("invalid_observations", "observations must be a tuple of TextObservation")
        if not isinstance(interpretations, tuple) or not all(
            isinstance(item, (BlockInterpretation, BasicInfoInterpretation, TableInterpretation))
            for item in interpretations
        ):
            raise ToolModelError("invalid_interpretations", "interpretations must be a tuple of interpretation DTOs")
        source_facts = _project_source_facts(page_facts) if page_facts is not None else ()
        derived_relations = _project_derived_relations(block_relations) if block_relations is not None else ()
        resolved_page_id = page_id or _projection_page_id(block_relations, observations)
        _require_text(resolved_page_id, "page_id")
        return SemanticPageProjection(
            page_id=resolved_page_id,
            observation_status="recognized" if observations else "not_recognized",
            interpretation_status="interpreted" if interpretations else "not_interpreted",
            source_facts=source_facts,
            derived_relations=derived_relations,
            observations=self.project_observations(observations),
            interpretations=self.project_interpretations(interpretations),
            candidate_relations=tuple(candidate_relations),
            formal_relations=tuple(formal_relations),
            run_summary=run_summary,
        )

    def project_observations(
        self,
        observations: tuple[TextObservation, ...],
    ) -> tuple[SemanticObservationSummary, ...]:
        """Project TextObservation DTOs into stable facade summaries."""

        if not isinstance(observations, tuple) or not all(isinstance(item, TextObservation) for item in observations):
            raise ToolModelError("invalid_observations", "observations must be a tuple of TextObservation")
        return tuple(
            SemanticObservationSummary(
                observation_id=item.observation_id,
                recognition_run_id=item.recognition_run_id,
                target_element_id=item.target_element_id,
                target_element_type=item.target_element_type,
                page_id=item.page_id,
                raw_text=item.raw_text,
                normalized_text=item.normalized_text,
                bbox=item.bbox,
                normalized_bbox=item.normalized_bbox,
                confidence=item.confidence,
                status=item.status.value,
                model_profile=item.model_profile,
                prompt_version=item.prompt_version,
                created_at=item.created_at,
                image_hash=item.image_hash,
                cache_key=item.cache_key,
                evidence={"target_element_id": item.target_element_id, "page_id": item.page_id},
                persisted=False,
            )
            for item in observations
        )

    def project_interpretations(
        self,
        interpretations: tuple[BlockInterpretation | BasicInfoInterpretation | TableInterpretation, ...],
    ) -> tuple[SemanticInterpretationSummary, ...]:
        """Project interpretation DTOs into stable facade summaries."""

        if not isinstance(interpretations, tuple) or not all(
            isinstance(item, (BlockInterpretation, BasicInfoInterpretation, TableInterpretation))
            for item in interpretations
        ):
            raise ToolModelError("invalid_interpretations", "interpretations must be a tuple of interpretation DTOs")
        return tuple(
            SemanticInterpretationSummary(
                interpretation_id=item.interpretation_id,
                recognition_run_id=item.recognition_run_id,
                element_id=_source_element_id(item),
                element_type=_source_element_type(item),
                page_id=item.page_id,
                summary=item.summary,
                analysis_status=item.analysis_status.value,
                interpreted_type=item.interpreted_type if isinstance(item, BlockInterpretation) else None,
                payload_ref=item.payload_ref,
                cache_key=item.cache_key,
                contract_version=item.contract_version,
                uncertainties=item.uncertainties,
                supported_by_observation_ids=item.supported_by_observation_ids,
                evidence={
                    "element_id": _source_element_id(item),
                    "page_id": item.page_id,
                    "payload_ref": item.payload_ref,
                },
                persisted=False,
            )
            for item in interpretations
        )


def _project_source_facts(page_facts: PageSourceFacts) -> tuple[SemanticFactItem, ...]:
    if not isinstance(page_facts, PageSourceFacts):
        raise ToolModelError("invalid_page_facts", "page_facts must be a PageSourceFacts")
    return tuple(
        SemanticFactItem(
            fact_kind="source_fact",
            fact_id=element.element_id,
            payload={
                "element_type": element.element_type,
                "bbox": {
                    "x_min": element.bbox.x_min,
                    "y_min": element.bbox.y_min,
                    "x_max": element.bbox.x_max,
                    "y_max": element.bbox.y_max,
                },
                "normalized_bbox": {
                    "x_min": element.normalized_bbox.x_min,
                    "y_min": element.normalized_bbox.y_min,
                    "x_max": element.normalized_bbox.x_max,
                    "y_max": element.normalized_bbox.y_max,
                },
                "source_label": element.source_label,
            },
        )
        for element in page_facts.elements
    )


def _project_derived_relations(block_relations: BlockRelations) -> tuple[SemanticFactItem, ...]:
    if not isinstance(block_relations, BlockRelations):
        raise ToolModelError("invalid_block_relations", "block_relations must be a BlockRelations")
    relation_groups = (
        ("HAS_CAPTION", block_relations.caption_ids),
        ("HAS_BASIC_INFO", block_relations.basic_info_ids),
        ("HAS_ANNOTATION", block_relations.annotation_ids),
        ("HAS_SECTION_MARK", block_relations.section_mark_ids),
        ("CANDIDATE_CAPTION_OF", block_relations.candidate_caption_ids),
        ("CANDIDATE_HAS_SECTION_MARK", block_relations.candidate_section_mark_ids),
    )
    return tuple(
        SemanticFactItem(
            fact_kind="derived_relation",
            fact_id=element_id,
            payload={"relation_type": relation_type, "block_id": block_relations.block_id},
        )
        for relation_type, element_ids in relation_groups
        for element_id in element_ids
    )


def _projection_page_id(
    block_relations: BlockRelations | None,
    observations: tuple[TextObservation, ...],
) -> str:
    if observations:
        return observations[0].page_id
    if block_relations is not None:
        return f"page-for:{block_relations.block_id}"
    raise ToolModelError("INVALID_ARGUMENT", "page projection requires page facts, relations, or observations")


def _source_element_id(
    item: BlockInterpretation | BasicInfoInterpretation | TableInterpretation,
) -> str:
    if isinstance(item, BlockInterpretation):
        return item.block_id
    if isinstance(item, BasicInfoInterpretation):
        return item.basic_info_id
    return item.table_id


def _source_element_type(
    item: BlockInterpretation | BasicInfoInterpretation | TableInterpretation,
) -> str:
    if isinstance(item, BlockInterpretation):
        return "DrawingBlock"
    if isinstance(item, BasicInfoInterpretation):
        return "DrawingBasicInfo"
    return "Table"


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolModelError("missing_required_field", f"{field_name} must be a non-empty string")
    return value


__all__ = (
    "SemanticFactItem",
    "SemanticPageProjection",
    "SemanticQueryProjection",
)
