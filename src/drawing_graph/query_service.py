"""Read-only query service for drawing graph traceability."""

from __future__ import annotations

from typing import Any


class QueryError(ValueError):
    """Raised when query input is invalid before touching Neo4j."""

    def __init__(self, category: str, message: str):
        self.category = category
        super().__init__(message)


class QueryService:
    """Run predefined, parameterized read queries through an injected Neo4j driver."""

    def __init__(self, driver: Any):
        self.driver = driver

    def get_project_sets(self, project_id: str, limit: int = 100) -> list[dict[str, object]]:
        """Return drawing sets that belong to a project by stable business ID."""

        _require_text(project_id, "project_id")
        result_limit = _require_positive_int(limit, "limit")

        with self.driver.session() as session:
            return session.execute_read(
                lambda transaction: _get_project_sets(transaction, project_id, result_limit)
            )

    def get_set_pages(self, drawing_set_id: str, limit: int = 100) -> list[dict[str, object]]:
        """Return pages that belong to a drawing set ordered by page number."""

        _require_text(drawing_set_id, "drawing_set_id")
        result_limit = _require_positive_int(limit, "limit")

        with self.driver.session() as session:
            return session.execute_read(
                lambda transaction: _get_set_pages(transaction, drawing_set_id, result_limit)
            )

    def get_page_blocks(self, page_id: str, limit: int = 100) -> list[dict[str, object]]:
        """Return drawing blocks that belong to a page with geometry evidence."""

        _require_text(page_id, "page_id")
        result_limit = _require_positive_int(limit, "limit")

        with self.driver.session() as session:
            return session.execute_read(
                lambda transaction: _get_page_blocks(transaction, page_id, result_limit)
            )

    def get_block_trace(self, block_id: str) -> dict[str, object] | None:
        """Return the full project, set, page, and geometry trace for one block."""

        _require_text(block_id, "block_id")

        with self.driver.session() as session:
            return session.execute_read(lambda transaction: _get_block_trace(transaction, block_id))

    def get_block_relations(self, block_id: str) -> dict[str, object] | None:
        """Return derived relation IDs and enrichment status for one block."""

        _require_text(block_id, "block_id")

        with self.driver.session() as session:
            return session.execute_read(lambda transaction: _get_block_relations(transaction, block_id))

    def get_batch_status(self, import_batch_id: str) -> dict[str, object] | None:
        """Return import batch status, timing, counts, and classified errors."""

        _require_text(import_batch_id, "import_batch_id")

        with self.driver.session() as session:
            return session.execute_read(lambda transaction: _get_batch_status(transaction, import_batch_id))


def _get_project_sets(transaction: Any, project_id: str, limit: int) -> list[dict[str, object]]:
    cypher = (
        "MATCH (project:Project {id: $project_id})-[:HAS_SET]->(drawing_set:DrawingSet)\n"
        "RETURN drawing_set.id AS id,\n"
        "       drawing_set.name AS name,\n"
        "       drawing_set.page_count AS page_count\n"
        "ORDER BY drawing_set.name ASC, drawing_set.id ASC\n"
        "LIMIT $limit"
    )
    records = transaction.run(cypher, project_id=project_id, limit=limit)
    return [
        {
            "id": _record_value(record, "id"),
            "name": _record_value(record, "name"),
            "page_count": _record_value(record, "page_count"),
        }
        for record in records
    ]


def _get_set_pages(transaction: Any, drawing_set_id: str, limit: int) -> list[dict[str, object]]:
    cypher = (
        "MATCH (drawing_set:DrawingSet {id: $drawing_set_id})-[:HAS_PAGE]->(page:DrawingPage)\n"
        "RETURN page.id AS id,\n"
        "       page.file_name AS file_name,\n"
        "       page.page_number AS page_number,\n"
        "       page.image_path AS image_path\n"
        "ORDER BY page.page_number ASC, page.file_name ASC, page.id ASC\n"
        "LIMIT $limit"
    )
    records = transaction.run(cypher, drawing_set_id=drawing_set_id, limit=limit)
    return [
        {
            "id": _record_value(record, "id"),
            "file_name": _record_value(record, "file_name"),
            "page_number": _record_value(record, "page_number"),
            "image_path": _record_value(record, "image_path"),
        }
        for record in records
    ]


def _get_page_blocks(transaction: Any, page_id: str, limit: int) -> list[dict[str, object]]:
    cypher = (
        "MATCH (page:DrawingPage {id: $page_id})-[:HAS_BLOCK]->(block:DrawingBlock)\n"
        "RETURN block.id AS id,\n"
        "       block.label AS label,\n"
        "       block.confidence AS confidence,\n"
        "       block.bbox AS bbox,\n"
        "       block.normalized_bbox AS normalized_bbox\n"
        "ORDER BY block.id ASC\n"
        "LIMIT $limit"
    )
    records = transaction.run(cypher, page_id=page_id, limit=limit)
    return [
        {
            "id": _record_value(record, "id"),
            "label": _record_value(record, "label"),
            "confidence": _record_value(record, "confidence"),
            "bbox": _bbox_value(record, "bbox"),
            "normalized_bbox": _normalized_bbox_value(record, "normalized_bbox"),
        }
        for record in records
    ]


def _get_block_trace(transaction: Any, block_id: str) -> dict[str, object] | None:
    cypher = (
        "MATCH (project:Project)-[:HAS_SET]->(drawing_set:DrawingSet)"
        "-[:HAS_PAGE]->(page:DrawingPage)-[:HAS_BLOCK]->(block:DrawingBlock {id: $block_id})\n"
        "RETURN project.id AS project_id,\n"
        "       drawing_set.id AS drawing_set_id,\n"
        "       page.id AS page_id,\n"
        "       page.page_number AS page_number,\n"
        "       page.image_path AS image_path,\n"
        "       block.bbox AS bbox,\n"
        "       block.normalized_bbox AS normalized_bbox,\n"
        "       block.citation_ref AS citation_ref\n"
        "LIMIT 1"
    )
    records = list(transaction.run(cypher, block_id=block_id))
    if not records:
        return None

    record = records[0]
    return {
        "project_id": _record_value(record, "project_id"),
        "drawing_set_id": _record_value(record, "drawing_set_id"),
        "page_id": _record_value(record, "page_id"),
        "page_number": _record_value(record, "page_number"),
        "image_path": _record_value(record, "image_path"),
        "bbox": _bbox_value(record, "bbox"),
        "normalized_bbox": _normalized_bbox_value(record, "normalized_bbox"),
        "citation_ref": _record_value(record, "citation_ref"),
    }


def _get_block_relations(transaction: Any, block_id: str) -> dict[str, object] | None:
    cypher = (
        "MATCH (page:DrawingPage)-[:HAS_BLOCK]->(block:DrawingBlock {id: $block_id})\n"
        "OPTIONAL MATCH (block)-[:HAS_CAPTION]->(caption:BlockCaption)\n"
        "WITH page, block, collect(DISTINCT caption.id) AS caption_ids\n"
        "OPTIONAL MATCH (page)-[basic_info_relation:HAS_BASIC_INFO|USES_BASIC_INFO]->(basic_info:DrawingBasicInfo)\n"
        "WITH page, block, caption_ids,\n"
        "     collect(DISTINCT basic_info.id) AS basic_info_ids,\n"
        "     collect(DISTINCT coalesce(basic_info_relation.status, 'confirmed')) AS basic_info_statuses,\n"
        "     collect(DISTINCT coalesce(basic_info_relation.source, 'current_page')) AS basic_info_sources\n"
        "OPTIONAL MATCH (block)-[:HAS_ANNOTATION]->(annotation:DrawingAnnotation)\n"
        "WITH page, block, caption_ids, basic_info_ids, basic_info_statuses, basic_info_sources,\n"
        "     collect(DISTINCT annotation.id) AS annotation_ids\n"
        "OPTIONAL MATCH (block)-[:HAS_SECTION_MARK]->(section_mark:CrossSection)\n"
        "WITH page, block, caption_ids, basic_info_ids, basic_info_statuses, basic_info_sources,\n"
        "     annotation_ids, collect(DISTINCT section_mark.id) AS section_mark_ids\n"
        "OPTIONAL MATCH (candidate_caption:BlockCaption)-[:CANDIDATE_CAPTION_OF]->(block)\n"
        "WITH page, block, caption_ids, basic_info_ids, basic_info_statuses, basic_info_sources,\n"
        "     annotation_ids, section_mark_ids, collect(DISTINCT candidate_caption.id) AS candidate_caption_ids\n"
        "OPTIONAL MATCH (block)-[:CANDIDATE_HAS_SECTION_MARK]->(candidate_section_mark:CrossSection)\n"
        "RETURN block.id AS block_id,\n"
        "       caption_ids AS caption_ids,\n"
        "       basic_info_ids AS basic_info_ids,\n"
        "       CASE\n"
        "         WHEN size(basic_info_ids) = 0 THEN 'not_evaluated'\n"
        "         WHEN 'ambiguous' IN basic_info_statuses THEN 'ambiguous'\n"
        "         WHEN 'partial' IN basic_info_statuses THEN 'partial'\n"
        "         ELSE 'confirmed'\n"
        "       END AS basic_info_status,\n"
        "       head(basic_info_sources) AS basic_info_source,\n"
        "       annotation_ids AS annotation_ids,\n"
        "       section_mark_ids AS section_mark_ids,\n"
        "       candidate_caption_ids AS candidate_caption_ids,\n"
        "       collect(DISTINCT candidate_section_mark.id) AS candidate_section_mark_ids\n"
        "LIMIT 1"
    )
    records = list(transaction.run(cypher, block_id=block_id))
    if not records:
        return None

    record = records[0]
    caption_ids = _relation_ids_value(record, "caption_ids")
    basic_info_ids = _relation_ids_value(record, "basic_info_ids")
    basic_info_status = _optional_text_value(record, "basic_info_status", "not_evaluated")
    basic_info_source = _optional_nullable_text_value(record, "basic_info_source")
    annotation_ids = _relation_ids_value(record, "annotation_ids")
    section_mark_ids = _relation_ids_value(record, "section_mark_ids")
    candidate_caption_ids = _optional_relation_ids_value(record, "candidate_caption_ids")
    candidate_section_mark_ids = _optional_relation_ids_value(record, "candidate_section_mark_ids")
    return {
        "block_id": _record_value(record, "block_id"),
        "caption_ids": caption_ids,
        "basic_info_ids": basic_info_ids,
        "basic_info_status": basic_info_status,
        "basic_info_source": basic_info_source,
        "annotation_ids": annotation_ids,
        "section_mark_ids": section_mark_ids,
        "candidate_caption_ids": candidate_caption_ids,
        "candidate_section_mark_ids": candidate_section_mark_ids,
        "relation_status": _relation_status(
            caption_ids,
            basic_info_ids,
            annotation_ids,
            section_mark_ids,
            candidate_caption_ids,
            candidate_section_mark_ids,
        ),
    }


def _get_batch_status(transaction: Any, import_batch_id: str) -> dict[str, object] | None:
    cypher = (
        "MATCH (batch:ImportBatch {id: $import_batch_id})\n"
        "RETURN batch.id AS id,\n"
        "       batch.status AS status,\n"
        "       batch.started_at AS started_at,\n"
        "       batch.finished_at AS finished_at,\n"
        "       batch.total_files AS total_files,\n"
        "       batch.success_count AS success_count,\n"
        "       batch.skipped_count AS skipped_count,\n"
        "       batch.failed_count AS failed_count,\n"
        "       batch.warning_count AS warning_count,\n"
        "       batch.error_summary AS error_summary\n"
        "LIMIT 1"
    )
    records = list(transaction.run(cypher, import_batch_id=import_batch_id))
    if not records:
        return None

    record = records[0]
    return {
        "id": _record_value(record, "id"),
        "status": _record_value(record, "status"),
        "started_at": _record_value(record, "started_at"),
        "finished_at": _record_value(record, "finished_at"),
        "total_files": _non_negative_int_value(record, "total_files"),
        "success_count": _non_negative_int_value(record, "success_count"),
        "skipped_count": _non_negative_int_value(record, "skipped_count"),
        "failed_count": _non_negative_int_value(record, "failed_count"),
        "warning_count": _non_negative_int_value(record, "warning_count"),
        "error_summary": _error_summary_value(record, "error_summary"),
    }


def _record_value(record: Any, key: str) -> Any:
    if isinstance(record, dict):
        return record.get(key)
    return record[key]


def _bbox_value(record: Any, key: str) -> dict[str, object]:
    value = _record_value(record, key)
    if isinstance(value, (list, tuple)):
        if len(value) != 4:
            raise QueryError("invalid_bbox", f"{key} must contain four coordinates")
        return {
            "x_min": value[0],
            "y_min": value[1],
            "x_max": value[2],
            "y_max": value[3],
        }
    if not isinstance(value, dict):
        raise QueryError("invalid_bbox", f"{key} must be a bbox object or four-coordinate list")
    missing_fields = [field for field in ("x_min", "y_min", "x_max", "y_max") if field not in value]
    if missing_fields:
        raise QueryError("invalid_bbox", f"{key} is missing required bbox fields")
    return {
        "x_min": value["x_min"],
        "y_min": value["y_min"],
        "x_max": value["x_max"],
        "y_max": value["y_max"],
    }


def _normalized_bbox_value(record: Any, key: str) -> dict[str, object]:
    value = _bbox_value(record, key)
    if not all(_is_normalized_coordinate(value[field]) for field in ("x_min", "y_min", "x_max", "y_max")):
        raise QueryError("invalid_normalized_bbox", f"{key} values must be between 0 and 1")
    return value


def _non_negative_int_value(record: Any, key: str) -> int:
    value = _record_value(record, key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise QueryError("invalid_batch_count", f"{key} must be a non-negative integer")
    return value


def _error_summary_value(record: Any, key: str) -> list[str]:
    value = _record_value(record, key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise QueryError("invalid_error_summary", f"{key} must be a list of strings")
    return list(value)


def _relation_ids_value(record: Any, key: str) -> list[str]:
    value = _record_value(record, key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise QueryError("invalid_relation_ids", f"{key} must be a list of strings")
    return sorted(value)


def _optional_relation_ids_value(record: Any, key: str) -> list[str]:
    value = _record_value(record, key)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise QueryError("invalid_relation_ids", f"{key} must be a list of strings")
    return sorted(value)


def _optional_text_value(record: Any, key: str, default: str) -> str:
    value = _record_value(record, key)
    if value is None:
        return default
    if not isinstance(value, str):
        raise QueryError("invalid_relation_status", f"{key} must be a string")
    return value


def _optional_nullable_text_value(record: Any, key: str) -> str | None:
    value = _record_value(record, key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise QueryError("invalid_relation_status", f"{key} must be a string when provided")
    return value


def _relation_status(
    caption_ids: list[str],
    basic_info_ids: list[str],
    annotation_ids: list[str],
    section_mark_ids: list[str],
    candidate_caption_ids: list[str] | None = None,
    candidate_section_mark_ids: list[str] | None = None,
) -> str:
    if candidate_caption_ids or candidate_section_mark_ids:
        return "candidate"
    present_groups = sum(bool(values) for values in (caption_ids, basic_info_ids, annotation_ids, section_mark_ids))
    if present_groups == 0:
        return "not_enhanced"
    if present_groups == 4:
        return "enhanced"
    return "partial"


def _is_normalized_coordinate(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise QueryError("missing_required_field", f"{field_name} must be a non-empty string")
    return value


def _require_positive_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise QueryError("invalid_limit", f"{field_name} must be a positive integer")
    return value


__all__ = ("QueryError", "QueryService")
