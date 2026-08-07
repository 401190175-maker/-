"""Neo4j implementation of the semantic evidence repository port."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

from .semantic_models import (
    BasicInfoInterpretation,
    BlockInterpretation,
    TableInterpretation,
    TextObservation,
)
from .semantic_schema import INTERPRETATION_SOURCE_LABELS, OBSERVATION_SOURCE_LABELS
from .tool_models import ToolModelError


class SemanticNeo4jRepository:
    """Write graph-internal semantic evidence through controlled Cypher."""

    def __init__(self, driver: Any):
        self.driver = driver

    def save_observations(self, observations: tuple[TextObservation, ...]) -> tuple[TextObservation, ...]:
        """Idempotently persist TextObservation nodes and HAS_OBSERVATION edges."""

        grouped = _group_observations(observations)
        if not grouped:
            return observations
        with self.driver.session() as session:
            for label, payloads in grouped.items():
                session.execute_write(
                    lambda transaction, current_label=label, current_payloads=payloads: _write_observation_batch(
                        transaction,
                        current_label,
                        current_payloads,
                    )
                )
        return observations

    def find_by_page(self, page_id: str) -> tuple[TextObservation, ...]:
        """Query observations for one page."""

        return _find_observations(self.driver, "text_observation.page_id = $page_id", page_id=page_id)

    def find_by_element(self, element_id: str) -> tuple[TextObservation, ...]:
        """Query observations for one element."""

        return _find_observations(
            self.driver,
            "text_observation.target_element_id = $element_id",
            element_id=element_id,
        )

    def find_by_run(self, recognition_run_id: str) -> tuple[TextObservation, ...]:
        """Query observations for one run."""

        return _find_observations(
            self.driver,
            "text_observation.recognition_run_id = $recognition_run_id",
            recognition_run_id=recognition_run_id,
        )

    def save_interpretations(
        self,
        interpretations: tuple[BlockInterpretation | BasicInfoInterpretation | TableInterpretation, ...],
    ) -> tuple[BlockInterpretation | BasicInfoInterpretation | TableInterpretation, ...]:
        """Idempotently persist interpretation nodes, edges, and stale markers."""

        grouped = _group_interpretations(interpretations)
        if not grouped:
            return interpretations
        with self.driver.session() as session:
            for label, payloads in grouped.items():
                session.execute_write(
                    lambda transaction, current_label=label, current_payloads=payloads: _write_interpretation_batch(
                        transaction,
                        current_label,
                        current_payloads,
                    )
                )
        return interpretations

    def find_interpretations(
        self,
        *,
        page_id: str | None = None,
        element_id: str | None = None,
        recognition_run_id: str | None = None,
        statuses: tuple[str, ...] | None = None,
    ) -> tuple[BlockInterpretation | BasicInfoInterpretation | TableInterpretation, ...]:
        """Query structured interpretations by page, source element, run, and status."""

        return _find_interpretations(
            self.driver,
            page_id=page_id,
            element_id=element_id,
            recognition_run_id=recognition_run_id,
            statuses=statuses,
        )


def _group_observations(
    observations: tuple[TextObservation, ...],
) -> OrderedDict[str, list[dict[str, Any]]]:
    if not isinstance(observations, tuple) or not all(isinstance(item, TextObservation) for item in observations):
        raise ToolModelError("invalid_observations", "observations must be a tuple of TextObservation")
    grouped: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    for observation in observations:
        if observation.target_element_type not in OBSERVATION_SOURCE_LABELS:
            raise ToolModelError(
                "invalid_target_element_type",
                "target element type must be a controlled observation source label",
            )
        grouped.setdefault(observation.target_element_type, []).append(_observation_payload(observation))
    return grouped


def _find_observations(driver: Any, where_clause: str, **parameters: Any) -> tuple[TextObservation, ...]:
    cypher = (
        "MATCH (text_observation:TextObservation)\n"
        f"WHERE {where_clause}\n"
        "RETURN text_observation.id AS id,\n"
        "       text_observation.recognition_run_id AS recognition_run_id,\n"
        "       text_observation.target_element_id AS target_element_id,\n"
        "       text_observation.target_element_type AS target_element_type,\n"
        "       text_observation.page_id AS page_id,\n"
        "       text_observation.raw_text AS raw_text,\n"
        "       text_observation.normalized_text AS normalized_text,\n"
        "       text_observation.bbox AS bbox,\n"
        "       text_observation.normalized_bbox AS normalized_bbox,\n"
        "       text_observation.confidence AS confidence,\n"
        "       text_observation.status AS status,\n"
        "       text_observation.image_hash AS image_hash,\n"
        "       text_observation.cache_key AS cache_key,\n"
        "       text_observation.model_profile AS model_profile,\n"
        "       text_observation.prompt_version AS prompt_version,\n"
        "       text_observation.created_at AS created_at\n"
        "ORDER BY text_observation.id ASC"
    )
    with driver.session() as session:
        records = session.execute_read(lambda transaction: list(transaction.run(cypher, **parameters)))
    return tuple(_observation_from_record(record) for record in records)


def _find_interpretations(
    driver: Any,
    *,
    page_id: str | None,
    element_id: str | None,
    recognition_run_id: str | None,
    statuses: tuple[str, ...] | None,
) -> tuple[BlockInterpretation | BasicInfoInterpretation | TableInterpretation, ...]:
    where_clauses = [
        "any(label IN labels(interpretation) WHERE label IN ['BlockInterpretation', 'BasicInfoInterpretation', 'TableInterpretation'])"
    ]
    parameters: dict[str, Any] = {}
    if page_id is not None:
        where_clauses.append("interpretation.page_id = $page_id")
        parameters["page_id"] = page_id
    if element_id is not None:
        where_clauses.append("source.id = $element_id")
        parameters["element_id"] = element_id
    if recognition_run_id is not None:
        where_clauses.append("interpretation.recognition_run_id = $recognition_run_id")
        parameters["recognition_run_id"] = recognition_run_id
    if statuses is not None:
        where_clauses.append("interpretation.analysis_status IN $statuses")
        parameters["statuses"] = statuses
    cypher = (
        "MATCH (source)-[:HAS_INTERPRETATION]->(interpretation)\n"
        f"WHERE {' AND '.join(where_clauses)}\n"
        "OPTIONAL MATCH (interpretation)-[:SUPPORTED_BY]->(observation:TextObservation)\n"
        "RETURN labels(interpretation) AS labels,\n"
        "       source.id AS source_element_id,\n"
        "       properties(interpretation) AS properties,\n"
        "       collect(DISTINCT observation.id) AS supported_by_observation_ids\n"
        "ORDER BY properties.id ASC"
    )
    with driver.session() as session:
        records = session.execute_read(lambda transaction: list(transaction.run(cypher, **parameters)))
    return tuple(_interpretation_from_record(record) for record in records)


def _observation_from_record(record: Any) -> TextObservation:
    return TextObservation(
        observation_id=record["id"],
        recognition_run_id=record["recognition_run_id"],
        target_element_id=record["target_element_id"],
        target_element_type=record["target_element_type"],
        page_id=record["page_id"],
        raw_text=record["raw_text"],
        normalized_text=record["normalized_text"],
        bbox=_bbox_from_property(record["bbox"]),
        normalized_bbox=_bbox_from_property(record["normalized_bbox"]),
        confidence=record["confidence"],
        status=record["status"],
        image_hash=record["image_hash"],
        cache_key=record["cache_key"],
        model_profile=record["model_profile"],
        prompt_version=record["prompt_version"],
        created_at=record["created_at"],
    )


def _interpretation_from_record(record: Any) -> BlockInterpretation | BasicInfoInterpretation | TableInterpretation:
    labels = set(record["labels"])
    properties = _record_properties(record)
    common = {
        "interpretation_id": properties["id"],
        "recognition_run_id": properties["recognition_run_id"],
        "page_id": properties.get("page_id"),
        "summary": properties["summary"],
        "analysis_status": properties["analysis_status"],
        "uncertainties": tuple(properties.get("uncertainties") or ()),
        "supported_by_observation_ids": tuple(item for item in (record["supported_by_observation_ids"] or ()) if item),
        "payload_ref": properties.get("payload_ref"),
        "cache_key": properties.get("cache_key"),
        "contract_version": properties.get("contract_version") or "1",
    }
    if "BlockInterpretation" in labels:
        return BlockInterpretation(
            block_id=record["source_element_id"],
            interpreted_type=properties.get("interpreted_type"),
            components=tuple(properties.get("components") or ()),
            materials=tuple(properties.get("materials") or ()),
            dimensions=tuple(properties.get("dimensions") or ()),
            construction_features=tuple(properties.get("construction_features") or ()),
            spatial_relations=tuple(properties.get("spatial_relations") or ()),
            **common,
        )
    if "BasicInfoInterpretation" in labels:
        return BasicInfoInterpretation(
            basic_info_id=record["source_element_id"],
            raw_text=properties.get("raw_text") or "",
            project_name=properties.get("project_name"),
            drawing_name=properties.get("drawing_name"),
            discipline=properties.get("discipline"),
            drawing_number=properties.get("drawing_number"),
            scale=properties.get("scale"),
            date=properties.get("date"),
            **common,
        )
    if "TableInterpretation" in labels:
        return TableInterpretation(
            table_id=record["source_element_id"],
            caption_ref=properties.get("caption_ref"),
            **common,
        )
    raise ToolModelError("invalid_interpretation_label", "interpretation label must be controlled")


def _record_properties(record: Any) -> dict[str, Any]:
    try:
        properties = record["properties"]
    except Exception:  # noqa: BLE001 - fake unit records may expose flattened fields.
        properties = None
    if isinstance(properties, dict):
        return properties
    return {
        key: record[key]
        for key in (
            "id",
            "recognition_run_id",
            "page_id",
            "summary",
            "analysis_status",
            "uncertainties",
            "payload_ref",
            "cache_key",
            "contract_version",
            "interpreted_type",
            "components",
            "materials",
            "dimensions",
            "construction_features",
            "spatial_relations",
            "raw_text",
            "project_name",
            "drawing_name",
            "discipline",
            "drawing_number",
            "scale",
            "date",
            "caption_ref",
        )
    }


def _observation_payload(observation: TextObservation) -> dict[str, Any]:
    return {
        "id": observation.observation_id,
        "recognition_run_id": observation.recognition_run_id,
        "target_element_id": observation.target_element_id,
        "target_element_type": observation.target_element_type,
        "page_id": observation.page_id,
        "raw_text": observation.raw_text,
        "normalized_text": observation.normalized_text,
        "bbox": _bbox_properties(observation.bbox),
        "normalized_bbox": _bbox_properties(observation.normalized_bbox),
        "confidence": observation.confidence,
        "status": observation.status.value,
        "image_hash": observation.image_hash,
        "cache_key": observation.cache_key,
        "model_profile": observation.model_profile,
        "prompt_version": observation.prompt_version,
        "created_at": observation.created_at,
    }


def _bbox_properties(bbox: Any) -> list[float]:
    return [bbox.x_min, bbox.y_min, bbox.x_max, bbox.y_max]


def _bbox_from_property(value: Any):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ToolModelError("invalid_bbox", "bbox property must contain four coordinates")
    from .tool_models import BBox

    return BBox(value[0], value[1], value[2], value[3])


def _write_observation_batch(transaction: Any, label: str, payloads: list[dict[str, Any]]) -> None:
    cypher = (
        "UNWIND $observations AS observation\n"
        f"MATCH (source:{label} {{id: observation.target_element_id}})\n"
        "MERGE (text_observation:TextObservation {id: observation.id})\n"
        "SET text_observation += observation\n"
        "MERGE (source)-[r:HAS_OBSERVATION]->(text_observation)"
    )
    transaction.run(cypher, observations=payloads)


def _group_interpretations(
    interpretations: tuple[BlockInterpretation | BasicInfoInterpretation | TableInterpretation, ...],
) -> OrderedDict[str, list[dict[str, Any]]]:
    if not isinstance(interpretations, tuple) or not all(
        isinstance(item, (BlockInterpretation, BasicInfoInterpretation, TableInterpretation)) for item in interpretations
    ):
        raise ToolModelError("invalid_interpretations", "interpretations must be a tuple of interpretation DTOs")
    grouped: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    for interpretation in interpretations:
        label, source_element_id, payload = _interpretation_payload(interpretation)
        grouped.setdefault(label, []).append(payload)
    return grouped


def _interpretation_payload(
    interpretation: BlockInterpretation | BasicInfoInterpretation | TableInterpretation,
) -> tuple[str, str, dict[str, Any]]:
    if isinstance(interpretation, BlockInterpretation):
        label = "BlockInterpretation"
        source_element_id = interpretation.block_id
        properties = {
            "interpreted_type": interpretation.interpreted_type,
            "components": list(interpretation.components),
            "materials": list(interpretation.materials),
            "dimensions": list(interpretation.dimensions),
            "construction_features": list(interpretation.construction_features),
            "spatial_relations": list(interpretation.spatial_relations),
        }
    elif isinstance(interpretation, BasicInfoInterpretation):
        label = "BasicInfoInterpretation"
        source_element_id = interpretation.basic_info_id
        properties = {
            "raw_text": interpretation.raw_text,
            "project_name": interpretation.project_name,
            "drawing_name": interpretation.drawing_name,
            "discipline": interpretation.discipline,
            "drawing_number": interpretation.drawing_number,
            "scale": interpretation.scale,
            "date": interpretation.date,
        }
    else:
        label = "TableInterpretation"
        source_element_id = interpretation.table_id
        properties = {
            "caption_ref": interpretation.caption_ref,
        }
    payload: dict[str, Any] = {
        "id": interpretation.interpretation_id,
        "recognition_run_id": interpretation.recognition_run_id,
        "source_element_id": source_element_id,
        "page_id": interpretation.page_id,
        "summary": interpretation.summary,
        "analysis_status": interpretation.analysis_status.value,
        "uncertainties": list(interpretation.uncertainties),
        "supported_by_observation_ids": list(interpretation.supported_by_observation_ids),
        "payload_ref": interpretation.payload_ref,
        "cache_key": interpretation.cache_key,
        "contract_version": interpretation.contract_version,
    }
    payload.update(properties)
    if interpretation.cache_key is not None:
        payload["stale_cache_key"] = interpretation.cache_key
    return label, source_element_id, payload


def _write_interpretation_batch(transaction: Any, label: str, payloads: list[dict[str, Any]]) -> None:
    source_label = _source_label_for_interpretation(label)
    cypher = (
        "UNWIND $interpretations AS interpretation\n"
        f"MATCH (source:{source_label} {{id: interpretation.source_element_id}})\n"
        f"MERGE (node:{label} {{id: interpretation.id}})\n"
        "WITH source, node, interpretation\n"
        f"OPTIONAL MATCH (old:{label} {{cache_key: interpretation.stale_cache_key}})\n"
        "WHERE old.id <> interpretation.id AND interpretation.stale_cache_key IS NOT NULL\n"
        "SET old.analysis_status = 'stale'\n"
        "SET node += interpretation\n"
        "REMOVE node.stale_cache_key\n"
        "MERGE (source)-[r:HAS_INTERPRETATION]->(node)\n"
        "FOREACH (observation_id IN interpretation.supported_by_observation_ids |\n"
        "  MERGE (text_observation:TextObservation {id: observation_id})\n"
        "  MERGE (node)-[s:SUPPORTED_BY]->(text_observation))"
    )
    transaction.run(cypher, interpretations=payloads)


def _source_label_for_interpretation(label: str) -> str:
    mapping = {
        "BlockInterpretation": "DrawingBlock",
        "BasicInfoInterpretation": "DrawingBasicInfo",
        "TableInterpretation": "Table",
    }
    source_label = mapping[label]
    if source_label not in INTERPRETATION_SOURCE_LABELS:
        raise ToolModelError(
            "invalid_interpretation_source",
            "interpretation source label must be a controlled source label",
        )
    return source_label


__all__ = ("SemanticNeo4jRepository",)
