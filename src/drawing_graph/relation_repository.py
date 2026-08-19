"""Read-only repository for block-level relation enrichment inputs."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Iterable

from drawing_graph.block_relation_enrichment import (
    EnrichmentScope,
    PageElementSnapshot,
    PageRelationSnapshot,
    RelationCandidate,
)
from drawing_graph.models import BBox
from drawing_graph.tool_models import CandidateRelationSummary, SectionMatchSummary


RELATION_END_LABELS = {
    "HAS_CAPTION": "BlockCaption",
    "HAS_BASIC_INFO": "DrawingBasicInfo",
    "HAS_ANNOTATION": "DrawingAnnotation",
    "HAS_SECTION_MARK": "CrossSection",
    "USES_BASIC_INFO": "DrawingBasicInfo",
    "CANDIDATE_CAPTION_OF": "DrawingBlock",
    "CANDIDATE_HAS_SECTION_MARK": "CrossSection",
    "CANDIDATE_MATCHES_SECTION_CAPTION": "BlockCaption",
    "MATCHES_SECTION_CAPTION": "BlockCaption",
}
SECTION_MARK_REQUIRED_PROPERTIES = frozenset(("overlap_area", "overlap_ratio", "containment_status"))
CANDIDATE_RELATION_SPECS = frozenset(
    ("candidate_caption_of", "candidate_section_mark", "candidate_matches_section_caption")
)
REVIEW_STATUSES = frozenset(("not_started", "reviewing", "accepted", "rejected", "unresolved"))
RELATION_SPECS = {
    "block_caption": {
        "start_label": "DrawingBlock",
        "relation_type": "HAS_CAPTION",
        "end_label": "BlockCaption",
        "required_properties": frozenset(("distance", "match_direction")),
    },
    "block_basic_info": {
        "start_label": "DrawingBlock",
        "relation_type": "HAS_BASIC_INFO",
        "end_label": "DrawingBasicInfo",
        "required_properties": frozenset(("match_direction",)),
        "legacy_only": True,
    },
    "block_annotation": {
        "start_label": "DrawingBlock",
        "relation_type": "HAS_ANNOTATION",
        "end_label": "DrawingAnnotation",
        "required_properties": frozenset(("match_direction",)),
    },
    "block_section_mark": {
        "start_label": "DrawingBlock",
        "relation_type": "HAS_SECTION_MARK",
        "end_label": "CrossSection",
        "required_properties": SECTION_MARK_REQUIRED_PROPERTIES,
    },
    "table_caption": {
        "start_label": "Table",
        "relation_type": "HAS_CAPTION",
        "end_label": "TableCaption",
        "required_properties": frozenset(),
    },
    "page_uses_basic_info": {
        "start_label": "DrawingPage",
        "relation_type": "USES_BASIC_INFO",
        "end_label": "DrawingBasicInfo",
        "required_properties": frozenset(("status", "source", "source_page_id", "rule_version")),
    },
    "candidate_caption_of": {
        "start_label": "BlockCaption",
        "relation_type": "CANDIDATE_CAPTION_OF",
        "end_label": "DrawingBlock",
        "required_properties": frozenset(
            ("status", "candidate_count", "score", "distance", "match_direction", "conflict_reason", "rule_version")
        ),
    },
    "candidate_section_mark": {
        "start_label": "DrawingBlock",
        "relation_type": "CANDIDATE_HAS_SECTION_MARK",
        "end_label": "CrossSection",
        "required_properties": frozenset(
            (
                "status",
                "candidate_count",
                "score",
                "overlap_area",
                "overlap_ratio",
                "containment_status",
                "conflict_reason",
                "rule_version",
            )
        ),
    },
    "candidate_matches_section_caption": {
        "start_label": "CrossSection",
        "relation_type": "CANDIDATE_MATCHES_SECTION_CAPTION",
        "end_label": "BlockCaption",
        "required_properties": frozenset(
            (
                "status",
                "candidate_group_id",
                "candidate_count",
                "score",
                "conflict_reason",
                "observation_ids",
                "rule_version",
            )
        ),
    },
    "matches_section_caption": {
        "start_label": "CrossSection",
        "relation_type": "MATCHES_SECTION_CAPTION",
        "end_label": "BlockCaption",
        "required_properties": frozenset(
            (
                "confirmation_method",
                "rule_version",
                "observation_ids",
            )
        ),
    },
}


class RelationRepositoryError(ValueError):
    """Raised when relation repository input or records are invalid."""

    def __init__(self, category: str, message: str):
        self.category = category
        super().__init__(message)


class RelationRepository:
    """Read imported pages and page elements through fixed Neo4j queries."""

    def __init__(self, driver: Any):
        self.driver = driver

    def read_pages(self, scope: EnrichmentScope, limit: int = 100) -> tuple[PageRelationSnapshot, ...]:
        """Read page snapshots within a project, drawing-set, or page scope."""

        if not isinstance(scope, EnrichmentScope):
            raise RelationRepositoryError("invalid_scope", "scope must be an EnrichmentScope")
        result_limit = _require_positive_int(limit, "limit")

        with self.driver.session() as session:
            return session.execute_read(lambda transaction: _read_pages(transaction, scope, result_limit))

    def read_previous_page_basic_infos(self, page: PageRelationSnapshot) -> PageRelationSnapshot | None:
        """Read the immediate previous page's basic info within the same drawing set."""

        if not isinstance(page, PageRelationSnapshot):
            raise RelationRepositoryError("invalid_page_snapshot", "page must be a PageRelationSnapshot")
        previous_page_number = page.page_number - 1
        if previous_page_number < 1:
            return None

        with self.driver.session() as session:
            previous_page = session.execute_read(
                lambda transaction: _read_previous_page_basic_infos(
                    transaction,
                    page.drawing_set_id,
                    previous_page_number,
                )
            )

        if previous_page is None:
            return None
        if previous_page.drawing_set_id != page.drawing_set_id:
            raise RelationRepositoryError(
                "previous_page_drawing_set_mismatch",
                "previous page basic info must come from the same drawing set",
            )
        return previous_page

    def write_relations(self, relations: Iterable[RelationCandidate]) -> None:
        """Idempotently write block-level derived relations."""

        grouped_relations = _group_write_relations(relations)
        if not grouped_relations:
            return

        with self.driver.session() as session:
            for relation_spec, payloads in grouped_relations.items():
                session.execute_write(
                    lambda transaction, current_spec=relation_spec, current_payloads=payloads: _write_relation_batch(
                        transaction,
                        current_spec,
                        current_payloads,
                    )
                )

    def update_candidate_review(
        self,
        *,
        relation_spec: str,
        start_id: str,
        end_id: str,
        rule_version: str,
        review_status: str,
        review_run_id: str,
        review_model_version: str | None = None,
        review_prompt_version: str | None = None,
        review_score: float | None = None,
        review_reason: str | None = None,
        reviewed_at: str | None = None,
    ) -> None:
        """Update review metadata on a fixed candidate relation."""

        spec = _require_candidate_relation_spec(relation_spec)
        _require_relation_endpoint(start_id, "start_id")
        _require_relation_endpoint(end_id, "end_id")
        _require_text(rule_version, "rule_version")
        if review_status not in REVIEW_STATUSES:
            raise RelationRepositoryError("invalid_review_status", "review_status must be a supported review status")
        _require_text(review_run_id, "review_run_id")
        _require_optional_text(review_model_version, "review_model_version")
        _require_optional_text(review_prompt_version, "review_prompt_version")
        _require_optional_text(review_reason, "review_reason")
        _require_optional_text(reviewed_at, "reviewed_at")
        if review_score is not None and (
            not isinstance(review_score, (int, float)) or isinstance(review_score, bool)
        ):
            raise RelationRepositoryError("invalid_review_score", "review_score must be numeric when provided")

        properties = {
            "review_status": review_status,
            "review_run_id": review_run_id,
        }
        for key, value in (
            ("review_model_version", review_model_version),
            ("review_prompt_version", review_prompt_version),
            ("review_score", review_score),
            ("review_reason", review_reason),
            ("reviewed_at", reviewed_at),
        ):
            if value is not None:
                properties[key] = value

        with self.driver.session() as session:
            session.execute_write(
                lambda transaction: _update_candidate_review(
                    transaction,
                    spec,
                    start_id,
                    end_id,
                    rule_version,
                    properties,
                )
            )

    def promote_candidate_relation(
        self,
        *,
        relation_spec: str,
        candidate_start_id: str,
        candidate_end_id: str,
        candidate_rule_version: str,
        review_status: str,
        review_run_id: str,
        formal_rule_version: str,
        confirmation_method: str,
    ) -> None:
        """Promote an accepted fixed candidate relation into its formal relation."""

        candidate_spec = _require_candidate_relation_spec(relation_spec)
        _require_relation_endpoint(candidate_start_id, "candidate_start_id")
        _require_relation_endpoint(candidate_end_id, "candidate_end_id")
        _require_text(candidate_rule_version, "candidate_rule_version")
        if review_status != "accepted":
            raise RelationRepositoryError("candidate_not_accepted", "only accepted candidate relations can be promoted")
        _require_text(review_run_id, "review_run_id")
        _require_text(formal_rule_version, "formal_rule_version")
        _require_text(confirmation_method, "confirmation_method")

        formal_properties = {
            "review_run_id": review_run_id,
            "rule_version": formal_rule_version,
            "confirmation_method": confirmation_method,
        }

        with self.driver.session() as session:
            session.execute_write(
                lambda transaction: _promote_candidate_relation(
                    transaction,
                    candidate_spec,
                    relation_spec,
                    candidate_start_id,
                    candidate_end_id,
                    candidate_rule_version,
                    formal_rule_version,
                    formal_properties,
                )
            )


class RelationRepositorySectionMatchPort:
    """Adapt RelationRepository to the controlled section-match write port."""

    def __init__(self, repository: RelationRepository):
        self.repository = repository

    def write_section_relation(
        self,
        *,
        relation_type: str,
        start_id: str,
        end_id: str,
        properties: dict[str, object],
    ) -> None:
        """Write one whitelisted section candidate or formal relation."""

        relation_spec = {
            "CANDIDATE_MATCHES_SECTION_CAPTION": "candidate_matches_section_caption",
            "MATCHES_SECTION_CAPTION": "matches_section_caption",
        }.get(relation_type)
        if relation_spec is None:
            raise RelationRepositoryError(
                "invalid_section_relation_type",
                "section relation type must be a whitelisted semantic type",
            )
        rule_version = str(properties.get("rule_version") or "")
        if not rule_version:
            raise RelationRepositoryError("missing_rule_version", "section relation requires rule_version")
        self.repository.write_relations(
            (
                RelationCandidate(
                    start_id=start_id,
                    end_id=end_id,
                    relation_spec=relation_spec,
                    relation_type=relation_type,
                    relation_batch_id="semantic-section-batch",
                    rule_version=rule_version,
                    link_rule="section_match_v1",
                    properties=dict(properties),
                ),
            )
        )


class RelationRepositoryCandidateRelationPort:
    """Project persisted block-level candidate relations as facade DTOs."""

    def __init__(self, repository: RelationRepository):
        self.repository = repository

    def list_candidate_relations(
        self,
        *,
        page_id: str | None = None,
        block_id: str | None = None,
        relation_type: str | None = None,
        status: str | None = None,
    ) -> tuple[CandidateRelationSummary, ...]:
        """Read persisted CANDIDATE_* block relations without promoting them."""

        _require_optional_text(page_id, "page_id")
        _require_optional_text(block_id, "block_id")
        _require_optional_text(relation_type, "relation_type")
        _require_optional_text(status, "status")
        with self.repository.driver.session() as session:
            records = session.execute_read(
                lambda transaction: list(
                    transaction.run(
                        _candidate_relation_query(),
                        page_id=page_id,
                        block_id=block_id,
                        relation_type=relation_type,
                        status=status,
                    )
                )
            )
        return tuple(_candidate_summary_from_record(record) for record in records)


class RelationRepositorySectionMatchQueryPort:
    """Project persisted section-caption candidate/formal relations."""

    def __init__(self, repository: RelationRepository):
        self.repository = repository

    def list_section_matches(
        self,
        *,
        cross_section_id: str | None = None,
        page_id: str | None = None,
        statuses: tuple[str, ...] | None = None,
    ) -> tuple[SectionMatchSummary, ...]:
        """Read CANDIDATE_MATCHES_SECTION_CAPTION and MATCHES_SECTION_CAPTION projections."""

        _require_optional_text(cross_section_id, "cross_section_id")
        _require_optional_text(page_id, "page_id")
        if statuses is not None:
            for item in statuses:
                _require_text(item, "statuses")
        with self.repository.driver.session() as session:
            records = session.execute_read(
                lambda transaction: list(
                    transaction.run(
                        _section_match_query(),
                        cross_section_id=cross_section_id,
                        page_id=page_id,
                        statuses=statuses,
                    )
                )
            )
        return tuple(_section_match_summary_from_record(record) for record in records)


def _read_pages(transaction: Any, scope: EnrichmentScope, limit: int) -> tuple[PageRelationSnapshot, ...]:
    if scope.page_id is not None:
        cypher = _page_scope_query("page")
        records = transaction.run(cypher, project_id=scope.project_id, page_id=scope.page_id, limit=limit)
    elif scope.drawing_set_id is not None:
        cypher = _page_scope_query("drawing_set")
        records = transaction.run(
            cypher,
            project_id=scope.project_id,
            drawing_set_id=scope.drawing_set_id,
            limit=limit,
        )
    else:
        cypher = _page_scope_query("project")
        records = transaction.run(cypher, project_id=scope.project_id, limit=limit)
    return tuple(_page_snapshot_from_record(record) for record in records)


def _candidate_relation_query() -> str:
    return (
        "MATCH (page:DrawingPage)-[:HAS_ELEMENT]->(caption:BlockCaption)"
        "-[relation:CANDIDATE_CAPTION_OF]->(block:DrawingBlock)\n"
        "WITH page, caption.id AS start_id, block.id AS end_id, block.id AS block_id, relation,\n"
        "     'candidate_caption_of' AS relation_type, properties(relation) AS properties\n"
        "WHERE ($page_id IS NULL OR page.id = $page_id)\n"
        "  AND ($block_id IS NULL OR block_id = $block_id)\n"
        "  AND ($relation_type IS NULL OR relation_type = $relation_type)\n"
        "  AND ($status IS NULL OR coalesce(properties.status, properties.review_status, 'candidate') = $status)\n"
        "RETURN coalesce(properties.candidate_group_id, start_id + ':' + end_id + ':' + coalesce(properties.rule_version, 'unknown')) AS candidate_group_id,\n"
        "       page.id AS page_id,\n"
        "       block_id AS block_id,\n"
        "       start_id AS source_element_id,\n"
        "       end_id AS target_element_id,\n"
        "       relation_type AS relation_type,\n"
        "       coalesce(properties.status, properties.review_status, 'candidate') AS status,\n"
        "       properties.score AS score,\n"
        "       properties.conflict_reason AS conflict_reason,\n"
        "       coalesce(properties.observation_ids, []) AS evidence_ids,\n"
        "       properties.recognition_run_id AS recognition_run_id\n"
        "UNION ALL\n"
        "MATCH (page:DrawingPage)-[:HAS_BLOCK]->(block:DrawingBlock)"
        "-[relation:CANDIDATE_HAS_SECTION_MARK]->(cross_section:CrossSection)\n"
        "WITH page, block.id AS start_id, cross_section.id AS end_id, block.id AS block_id, relation,\n"
        "     'candidate_section_mark' AS relation_type, properties(relation) AS properties\n"
        "WHERE ($page_id IS NULL OR page.id = $page_id)\n"
        "  AND ($block_id IS NULL OR block_id = $block_id)\n"
        "  AND ($relation_type IS NULL OR relation_type = $relation_type)\n"
        "  AND ($status IS NULL OR coalesce(properties.status, properties.review_status, 'candidate') = $status)\n"
        "RETURN coalesce(properties.candidate_group_id, start_id + ':' + end_id + ':' + coalesce(properties.rule_version, 'unknown')) AS candidate_group_id,\n"
        "       page.id AS page_id,\n"
        "       block_id AS block_id,\n"
        "       start_id AS source_element_id,\n"
        "       end_id AS target_element_id,\n"
        "       relation_type AS relation_type,\n"
        "       coalesce(properties.status, properties.review_status, 'candidate') AS status,\n"
        "       properties.score AS score,\n"
        "       properties.conflict_reason AS conflict_reason,\n"
        "       coalesce(properties.observation_ids, []) AS evidence_ids,\n"
        "       properties.recognition_run_id AS recognition_run_id\n"
        "ORDER BY page_id ASC, block_id ASC, relation_type ASC, candidate_group_id ASC"
    )


def _section_match_query() -> str:
    return (
        "MATCH (page:DrawingPage)-[:HAS_ELEMENT]->(cross_section:CrossSection)"
        "-[relation:CANDIDATE_MATCHES_SECTION_CAPTION]->(caption:BlockCaption)\n"
        "WITH page, cross_section, caption, relation, properties(relation) AS properties\n"
        "WITH page, cross_section, caption, relation, properties,\n"
        "     coalesce(properties.status, 'candidate') AS projected_status\n"
        "WHERE ($cross_section_id IS NULL OR cross_section.id = $cross_section_id)\n"
        "  AND ($page_id IS NULL OR page.id = $page_id)\n"
        "  AND ($statuses IS NULL OR projected_status IN $statuses)\n"
        "RETURN cross_section.id AS cross_section_id,\n"
        "       projected_status AS match_status,\n"
        "       properties.logical_key AS logical_key,\n"
        "       caption.id AS matched_caption_id,\n"
        "       coalesce(properties.candidate_count, 1) AS candidate_count,\n"
        "       properties.conflict_reason AS conflict_reason,\n"
        "       coalesce(properties.observation_ids, []) AS observation_ids,\n"
        "       properties.rule_version AS rule_version,\n"
        "       'candidate_relation' AS fact_kind,\n"
        "       projected_status AS status,\n"
        "       page.id AS page_id\n"
        "UNION ALL\n"
        "MATCH (page:DrawingPage)-[:HAS_ELEMENT]->(cross_section:CrossSection)"
        "-[relation:MATCHES_SECTION_CAPTION]->(caption:BlockCaption)\n"
        "WITH page, cross_section, caption, relation, properties(relation) AS properties\n"
        "WITH page, cross_section, caption, relation, properties,\n"
        "     'confirmed' AS projected_status\n"
        "WHERE ($cross_section_id IS NULL OR cross_section.id = $cross_section_id)\n"
        "  AND ($page_id IS NULL OR page.id = $page_id)\n"
        "  AND ($statuses IS NULL OR projected_status IN $statuses OR 'formal' IN $statuses)\n"
        "RETURN cross_section.id AS cross_section_id,\n"
        "       'formal' AS match_status,\n"
        "       properties.logical_key AS logical_key,\n"
        "       caption.id AS matched_caption_id,\n"
        "       1 AS candidate_count,\n"
        "       properties.conflict_reason AS conflict_reason,\n"
        "       coalesce(properties.observation_ids, []) AS observation_ids,\n"
        "       properties.rule_version AS rule_version,\n"
        "       'formal_relation' AS fact_kind,\n"
        "       projected_status AS status,\n"
        "       page.id AS page_id\n"
        "ORDER BY cross_section_id ASC, fact_kind ASC, matched_caption_id ASC"
    )


def _candidate_summary_from_record(record: Any) -> CandidateRelationSummary:
    return CandidateRelationSummary(
        candidate_group_id=_require_text(_record_value(record, "candidate_group_id"), "candidate_group_id"),
        page_id=_require_text(_record_value(record, "page_id"), "page_id"),
        block_id=_require_text(_record_value(record, "block_id"), "block_id"),
        relation_type=_require_text(_record_value(record, "relation_type"), "relation_type"),
        status=_require_text(_record_value(record, "status"), "status"),
        score=_record_value_or_none(record, "score"),
        conflict_reason=_record_value_or_none(record, "conflict_reason"),
        evidence_ids=_text_tuple(_record_value_or_none(record, "evidence_ids") or ()),
        recognition_run_id=_record_value_or_none(record, "recognition_run_id"),
        source_element_id=_record_value_or_none(record, "source_element_id"),
        target_element_id=_record_value_or_none(record, "target_element_id"),
    )


def _section_match_summary_from_record(record: Any) -> SectionMatchSummary:
    matched_caption_id = _record_value_or_none(record, "matched_caption_id")
    page_id = _record_value_or_none(record, "page_id")
    return SectionMatchSummary(
        cross_section_id=_require_text(_record_value(record, "cross_section_id"), "cross_section_id"),
        match_status=_require_text(_record_value(record, "match_status"), "match_status"),
        logical_key=_record_value_or_none(record, "logical_key"),
        matched_caption_ids=(matched_caption_id,) if matched_caption_id else (),
        candidate_count=_record_value_or_none(record, "candidate_count") or 0,
        conflict_reason=_record_value_or_none(record, "conflict_reason"),
        observation_ids=_text_tuple(_record_value_or_none(record, "observation_ids") or ()),
        rule_version=_record_value_or_none(record, "rule_version"),
        fact_kind=_require_text(_record_value(record, "fact_kind"), "fact_kind"),
        status=_require_text(_record_value(record, "status"), "status"),
        evidence={"page_id": page_id} if page_id else {},
        persisted=True,
    )


def _read_previous_page_basic_infos(
    transaction: Any,
    drawing_set_id: str,
    previous_page_number: int,
) -> PageRelationSnapshot | None:
    cypher = (
        "MATCH (drawing_set:DrawingSet {id: $drawing_set_id})-[:HAS_PAGE]->(page:DrawingPage)\n"
        "WHERE page.page_number = $previous_page_number\n"
        "OPTIONAL MATCH (page)-[:HAS_BASIC_INFO]->(basic_info:DrawingBasicInfo)\n"
        "RETURN page.id AS page_id,\n"
        "       drawing_set.id AS drawing_set_id,\n"
        "       page.page_number AS page_number,\n"
        "       [] AS blocks,\n"
        "       [] AS captions,\n"
        "       [] AS tables,\n"
        "       [] AS table_captions,\n"
        "       collect({id: basic_info.id, page_id: page.id, bbox: basic_info.bbox, properties: properties(basic_info)}) AS basic_infos,\n"
        "       [] AS annotations,\n"
        "       [] AS cross_sections\n"
        "ORDER BY page.page_number ASC\n"
        "LIMIT 1"
    )
    records = list(
        transaction.run(
            cypher,
            drawing_set_id=drawing_set_id,
            previous_page_number=previous_page_number,
        )
    )
    if not records:
        return None
    return _page_snapshot_from_record(records[0])


def _write_relation_batch(transaction: Any, relation_spec: str, relations: list[dict[str, object]]) -> None:
    if relation_spec == "table_caption":
        for relation in relations:
            _write_table_caption_relation(transaction, relation)
        return

    spec = RELATION_SPECS[relation_spec]
    start_label = spec["start_label"]
    relation_type = spec["relation_type"]
    end_label = spec["end_label"]
    cypher = (
        "UNWIND $relations AS relation\n"
        f"MATCH (start:{start_label} {{id: relation.start_id}})\n"
        f"MATCH (end:{end_label} {{id: relation.end_id}})\n"
        f"MERGE (start)-[r:{relation_type} {{rule_version: relation.properties.rule_version}}]->(end)\n"
        "SET r += relation.properties"
    )
    transaction.run(cypher, relations=relations)


def _write_table_caption_relation(transaction: Any, relation: dict[str, object]) -> None:
    precheck_cypher = (
        "MATCH (start:Table {id: $start_id})\n"
        "MATCH (end:TableCaption {id: $end_id})\n"
        "OPTIONAL MATCH (legacy_start:Table)-[legacy:HAS_CAPTION]->(end)\n"
        "WHERE legacy.rule_version IS NULL\n"
        "RETURN legacy_start.id AS legacy_start_id\n"
        "LIMIT 1"
    )
    legacy_records = list(
        transaction.run(
            precheck_cypher,
            start_id=relation["start_id"],
            end_id=relation["end_id"],
        )
        or ()
    )
    if legacy_records:
        legacy_start_id = _record_value(legacy_records[0], "legacy_start_id")
        if legacy_start_id is not None:
            if legacy_start_id == relation["start_id"]:
                adopted_relation = dict(relation)
                adopted_properties = dict(adopted_relation["properties"])
                adopted_properties["legacy_adopted"] = True
                adopted_relation["properties"] = adopted_properties
                adopt_cypher = (
                    "MATCH (start:Table {id: $start_id})\n"
                    "MATCH (end:TableCaption {id: $end_id})\n"
                    "MATCH (start)-[legacy:HAS_CAPTION]->(end)\n"
                    "WHERE legacy.rule_version IS NULL\n"
                    "SET legacy += $properties"
                )
                transaction.run(
                    adopt_cypher,
                    start_id=adopted_relation["start_id"],
                    end_id=adopted_relation["end_id"],
                    properties=adopted_relation["properties"],
                )
                return
            raise RelationRepositoryError(
                "table_caption_legacy_conflict",
                "table caption already has a legacy HAS_CAPTION relation from a different table",
            )

    write_cypher = (
        "MATCH (start:Table {id: $start_id})\n"
        "MATCH (end:TableCaption {id: $end_id})\n"
        "MERGE (start)-[r:HAS_CAPTION {rule_version: $rule_version}]->(end)\n"
        "SET r += $properties"
    )
    properties = relation["properties"]
    transaction.run(
        write_cypher,
        start_id=relation["start_id"],
        end_id=relation["end_id"],
        rule_version=properties["rule_version"],
        properties=properties,
    )


def _update_candidate_review(
    transaction: Any,
    spec: dict[str, object],
    start_id: str,
    end_id: str,
    rule_version: str,
    properties: dict[str, object],
) -> None:
    start_label = spec["start_label"]
    relation_type = spec["relation_type"]
    end_label = spec["end_label"]
    cypher = (
        f"MATCH (start:{start_label} {{id: $start_id}})\n"
        f"MATCH (end:{end_label} {{id: $end_id}})\n"
        f"MATCH (start)-[r:{relation_type} {{rule_version: $rule_version}}]->(end)\n"
        "SET r += $properties"
    )
    transaction.run(
        cypher,
        start_id=start_id,
        end_id=end_id,
        rule_version=rule_version,
        properties=properties,
    )


def _promote_candidate_relation(
    transaction: Any,
    candidate_spec: dict[str, object],
    relation_spec: str,
    candidate_start_id: str,
    candidate_end_id: str,
    candidate_rule_version: str,
    formal_rule_version: str,
    formal_properties: dict[str, object],
) -> None:
    candidate_start_label = candidate_spec["start_label"]
    candidate_relation_type = candidate_spec["relation_type"]
    candidate_end_label = candidate_spec["end_label"]
    if relation_spec == "candidate_caption_of":
        formal_cypher = (
            "MERGE (candidate_end)-[formal:HAS_CAPTION {rule_version: $formal_rule_version}]->(candidate_start)\n"
        )
    elif relation_spec == "candidate_section_mark":
        formal_cypher = (
            "MERGE (candidate_start)-[formal:HAS_SECTION_MARK {rule_version: $formal_rule_version}]->(candidate_end)\n"
        )
    else:
        formal_cypher = (
            "MERGE (candidate_start)-[formal:MATCHES_SECTION_CAPTION "
            "{rule_version: $formal_rule_version}]->(candidate_end)\n"
        )
    cypher = (
        f"MATCH (candidate_start:{candidate_start_label} {{id: $candidate_start_id}})\n"
        f"MATCH (candidate_end:{candidate_end_label} {{id: $candidate_end_id}})\n"
        f"MATCH (candidate_start)-[candidate:{candidate_relation_type} "
        "{rule_version: $candidate_rule_version, review_status: 'accepted'}]->(candidate_end)\n"
        f"{formal_cypher}"
        "SET formal += $formal_properties\n"
        "SET candidate.status = 'promoted', candidate.updated_at = $promoted_at"
    )
    promoted_at = formal_properties.get("reviewed_at")
    transaction.run(
        cypher,
        candidate_start_id=candidate_start_id,
        candidate_end_id=candidate_end_id,
        candidate_rule_version=candidate_rule_version,
        formal_rule_version=formal_rule_version,
        formal_properties=formal_properties,
        promoted_at=promoted_at,
    )


def _page_scope_query(scope_type: str) -> str:
    if scope_type == "page":
        match_clause = (
            "MATCH (project:Project {id: $project_id})-[:HAS_SET]->(drawing_set:DrawingSet)"
            "-[:HAS_PAGE]->(page:DrawingPage {id: $page_id})"
        )
    elif scope_type == "drawing_set":
        match_clause = (
            "MATCH (project:Project {id: $project_id})-[:HAS_SET]->(drawing_set:DrawingSet {id: $drawing_set_id})"
            "-[:HAS_PAGE]->(page:DrawingPage)"
        )
    else:
        match_clause = (
            "MATCH (project:Project {id: $project_id})-[:HAS_SET]->(drawing_set:DrawingSet)"
            "-[:HAS_PAGE]->(page:DrawingPage)"
        )

    return (
        f"{match_clause}\n"
        "OPTIONAL MATCH (page)-[:HAS_BLOCK]->(block:DrawingBlock)\n"
        "OPTIONAL MATCH (page)-[:HAS_ELEMENT]->(caption:BlockCaption)\n"
        "OPTIONAL MATCH (page)-[:HAS_TABLE]->(table:Table)\n"
        "OPTIONAL MATCH (page)-[:HAS_ELEMENT]->(table_caption:TableCaption)\n"
        "OPTIONAL MATCH (page)-[:HAS_BASIC_INFO]->(basic_info:DrawingBasicInfo)\n"
        "OPTIONAL MATCH (page)-[:HAS_ANNOTATION]->(annotation:DrawingAnnotation)\n"
        "OPTIONAL MATCH (page)-[:HAS_ELEMENT]->(cross_section:CrossSection)\n"
        "RETURN page.id AS page_id,\n"
        "       drawing_set.id AS drawing_set_id,\n"
        "       page.page_number AS page_number,\n"
        "       collect(DISTINCT {id: block.id, page_id: page.id, bbox: block.bbox, properties: properties(block)}) AS blocks,\n"
        "       collect(DISTINCT {id: caption.id, page_id: page.id, bbox: caption.bbox, properties: properties(caption)}) AS captions,\n"
        "       collect(DISTINCT {id: table.id, page_id: page.id, bbox: table.bbox, properties: properties(table)}) AS tables,\n"
        "       collect(DISTINCT {id: table_caption.id, page_id: page.id, bbox: table_caption.bbox, properties: properties(table_caption)}) AS table_captions,\n"
        "       collect(DISTINCT {id: basic_info.id, page_id: page.id, bbox: basic_info.bbox, properties: properties(basic_info)}) AS basic_infos,\n"
        "       collect(DISTINCT {id: annotation.id, page_id: page.id, bbox: annotation.bbox, properties: properties(annotation)}) AS annotations,\n"
        "       collect(DISTINCT {id: cross_section.id, page_id: page.id, bbox: cross_section.bbox, properties: properties(cross_section)}) AS cross_sections\n"
        "ORDER BY drawing_set.id ASC, page.page_number ASC, page.id ASC\n"
        "LIMIT $limit"
    )


def _page_snapshot_from_record(record: Any) -> PageRelationSnapshot:
    page_id = _record_value(record, "page_id")
    drawing_set_id = _record_value(record, "drawing_set_id")
    page_number = _record_value(record, "page_number")
    _require_text(page_id, "page_id")
    _require_text(drawing_set_id, "drawing_set_id")
    if not isinstance(page_number, int) or isinstance(page_number, bool) or page_number < 1:
        raise RelationRepositoryError("invalid_page_number", "page_number must be a positive integer")

    return PageRelationSnapshot(
        page_id=page_id,
        drawing_set_id=drawing_set_id,
        page_number=page_number,
        blocks=_element_snapshots(_record_value(record, "blocks") or ()),
        captions=_element_snapshots(_record_value(record, "captions") or ()),
        tables=_element_snapshots(_record_value(record, "tables") or ()),
        table_captions=_element_snapshots(_record_value(record, "table_captions") or ()),
        basic_infos=_element_snapshots(_record_value(record, "basic_infos") or ()),
        annotations=_element_snapshots(_record_value(record, "annotations") or ()),
        cross_sections=_element_snapshots(_record_value(record, "cross_sections") or ()),
    )


def _element_snapshots(values: Iterable[Any]) -> tuple[PageElementSnapshot, ...]:
    snapshots = []
    for value in values:
        if not value or _record_value(value, "id") is None:
            continue
        element_id = _record_value(value, "id")
        page_id = _record_value(value, "page_id")
        properties = _record_value(value, "properties") or {}
        if not isinstance(properties, dict):
            raise RelationRepositoryError("invalid_properties", "element properties must be a mapping")
        snapshots.append(
            PageElementSnapshot(
                id=element_id,
                page_id=page_id,
                bbox=_bbox_from_value(_record_value(value, "bbox")),
                properties=properties,
            )
        )
    return tuple(snapshots)


def _group_write_relations(relations: Iterable[RelationCandidate]) -> dict[str, list[dict[str, object]]]:
    grouped_relations: dict[str, OrderedDict[tuple[str, str, str, str, str], dict[str, object]]] = {
        relation_spec: OrderedDict()
        for relation_spec in RELATION_SPECS
    }
    for relation in relations:
        if not isinstance(relation, RelationCandidate):
            raise RelationRepositoryError("invalid_relation", "relations must contain RelationCandidate values")
        _require_relation_endpoint(relation.start_id, "start_id")
        _require_relation_endpoint(relation.end_id, "end_id")
        if relation.relation_type not in {spec["relation_type"] for spec in RELATION_SPECS.values()}:
            raise RelationRepositoryError("invalid_relation_type", "relation type must be a block-level derived type")
        spec = RELATION_SPECS.get(relation.relation_spec)
        if spec is None:
            raise RelationRepositoryError("invalid_relation_spec", "relation spec must be a fixed derived relation spec")
        if spec.get("legacy_only"):
            raise RelationRepositoryError(
                "legacy_relation_spec_not_writable",
                "legacy relation spec is not writable from new enrichment flow",
            )
        if relation.relation_type != spec["relation_type"]:
            raise RelationRepositoryError(
                "relation_spec_type_mismatch",
                "relation type must match the fixed derived relation spec",
            )
        _require_relation_properties(relation.properties, spec["required_properties"])

        key = (relation.start_id, relation.end_id, relation.relation_spec, relation.relation_type, relation.rule_version)
        grouped_relations[relation.relation_spec][key] = {
            "start_id": relation.start_id,
            "end_id": relation.end_id,
            "properties": dict(relation.properties),
        }
    return {
        relation_spec: list(relations_by_key.values())
        for relation_spec, relations_by_key in grouped_relations.items()
        if relations_by_key
    }


def _bbox_from_value(value: Any) -> BBox:
    if isinstance(value, (list, tuple)):
        if len(value) != 4:
            raise RelationRepositoryError("invalid_bbox", "bbox must contain four coordinates")
        return BBox(
            x_min=value[0],
            y_min=value[1],
            x_max=value[2],
            y_max=value[3],
        )
    if not isinstance(value, dict):
        raise RelationRepositoryError("invalid_bbox", "bbox must be an object or four-coordinate list")
    missing_fields = [field for field in ("x_min", "y_min", "x_max", "y_max") if field not in value]
    if missing_fields:
        raise RelationRepositoryError("invalid_bbox", "bbox is missing required fields")
    return BBox(
        x_min=value["x_min"],
        y_min=value["y_min"],
        x_max=value["x_max"],
        y_max=value["y_max"],
    )


def _record_value(record: Any, key: str) -> Any:
    if isinstance(record, dict):
        return record.get(key)
    return record[key]


def _record_value_or_none(record: Any, key: str) -> Any:
    if isinstance(record, dict):
        return record.get(key)
    try:
        return record[key]
    except KeyError:
        return None


def _text_tuple(values: Iterable[Any]) -> tuple[str, ...]:
    return tuple(str(value) for value in values if value is not None)


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RelationRepositoryError("missing_required_field", f"{field_name} must be a non-empty string")
    return value


def _require_optional_text(value: Any, field_name: str) -> str | None:
    if value is not None:
        return _require_text(value, field_name)
    return None


def _require_candidate_relation_spec(relation_spec: str) -> dict[str, object]:
    _require_text(relation_spec, "relation_spec")
    if relation_spec not in CANDIDATE_RELATION_SPECS:
        raise RelationRepositoryError(
            "invalid_candidate_relation_spec",
            "relation_spec must be a fixed candidate relation spec",
        )
    return RELATION_SPECS[relation_spec]


def _require_relation_endpoint(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RelationRepositoryError("missing_relation_endpoint", f"{field_name} must be a non-empty string")
    return value


def _require_relation_properties(properties: Any, required_properties: frozenset[str]) -> None:
    missing_fields = sorted(field for field in required_properties if field not in properties)
    if missing_fields:
        if required_properties == SECTION_MARK_REQUIRED_PROPERTIES:
            raise RelationRepositoryError(
                "missing_section_mark_evidence",
                "section mark relations require overlap_area, overlap_ratio, and containment_status",
            )
        raise RelationRepositoryError("missing_relation_property", "relation is missing required properties")


def _require_positive_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise RelationRepositoryError("invalid_limit", f"{field_name} must be a positive integer")
    return value


__all__ = (
    "RELATION_END_LABELS",
    "RelationRepository",
    "RelationRepositoryCandidateRelationPort",
    "RelationRepositorySectionMatchPort",
    "RelationRepositorySectionMatchQueryPort",
    "RelationRepositoryError",
    "SECTION_MARK_REQUIRED_PROPERTIES",
)
