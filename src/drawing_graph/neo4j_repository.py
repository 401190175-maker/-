"""Neo4j persistence helpers for graph nodes."""

from __future__ import annotations

from collections import OrderedDict, defaultdict
from typing import Any, Iterable

from drawing_graph.models import GraphNode, GraphRelation


ALLOWED_NODE_LABELS = frozenset(
    {
        "Project",
        "DrawingSet",
        "DrawingPage",
        "DrawingBlock",
        "Table",
        "TableCaption",
        "BlockCaption",
        "CrossSection",
        "DrawingBasicInfo",
        "DrawingAnnotation",
        "PlainText",
        "Title",
        "IgnoredElement",
        "ImportBatch",
    }
)

ALLOWED_RELATION_TYPES = frozenset(
    {
        "HAS_SET",
        "HAS_PAGE",
        "HAS_BLOCK",
        "HAS_CAPTION",
        "HAS_TABLE",
        "HAS_BASIC_INFO",
        "HAS_ANNOTATION",
        "HAS_SECTION_MARK",
        "HAS_TEXT",
        "HAS_ELEMENT",
        "IMPORTED_IN",
    }
)


class RepositoryError(ValueError):
    """Raised when repository input violates persistence rules."""

    def __init__(self, category: str, message: str):
        self.category = category
        super().__init__(message)


class Neo4jRepository:
    """Persist graph nodes through an injected Neo4j driver."""

    def __init__(self, driver: Any, batch_size: int = 500):
        if batch_size < 1:
            raise RepositoryError("invalid_batch_size", "batch_size must be a positive integer")
        self.driver = driver
        self.batch_size = batch_size

    def merge_nodes(self, nodes: Iterable[GraphNode]) -> None:
        """Merge graph nodes by stable business ID and update properties."""

        grouped_nodes = _group_nodes_by_label(nodes)
        if not grouped_nodes:
            return

        with self.driver.session() as session:
            for label, label_nodes in grouped_nodes.items():
                for batch in _batches(label_nodes, self.batch_size):
                    session.execute_write(lambda transaction, current_label=label, current_batch=batch: _merge_node_batch(
                        transaction,
                        current_label,
                        current_batch,
                    ))

    def merge_relations(self, relations: Iterable[GraphRelation]) -> None:
        """Merge graph relations by stable endpoints and allowed relation type."""

        grouped_relations = _group_relations_by_type(relations)
        if not grouped_relations:
            return

        with self.driver.session() as session:
            for relation_type, type_relations in grouped_relations.items():
                for batch in _batches(type_relations, self.batch_size):
                    session.execute_write(
                        lambda transaction, current_type=relation_type, current_batch=batch: _merge_relation_batch(
                            transaction,
                            current_type,
                            current_batch,
                        )
                    )

    def create_batch(self, batch_id: str, project_id: str, source_root: str, started_at: str) -> str:
        """Create or reset an import batch to the running state."""

        _require_text(batch_id, "batch_id")
        _require_text(project_id, "project_id")
        _require_text(source_root, "source_root")
        _require_text(started_at, "started_at")

        with self.driver.session() as session:
            session.execute_write(
                lambda transaction: _create_batch(
                    transaction,
                    batch_id,
                    project_id,
                    source_root,
                    started_at,
                )
            )
        return batch_id

    def finish_batch(
        self,
        batch_id: str,
        status: str,
        finished_at: str,
        total_files: int,
        success_count: int,
        skipped_count: int,
        failed_count: int,
        warning_count: int,
        error_summary: Iterable[str] = (),
    ) -> None:
        """Move an import batch to a terminal state with final audit counts."""

        _require_text(batch_id, "batch_id")
        _require_terminal_batch_status(status)
        _require_text(finished_at, "finished_at")
        counts = {
            "total_files": _require_non_negative_int(total_files, "total_files"),
            "success_count": _require_non_negative_int(success_count, "success_count"),
            "skipped_count": _require_non_negative_int(skipped_count, "skipped_count"),
            "failed_count": _require_non_negative_int(failed_count, "failed_count"),
            "warning_count": _require_non_negative_int(warning_count, "warning_count"),
        }
        errors = _read_error_summary(error_summary)

        with self.driver.session() as session:
            session.execute_write(
                lambda transaction: _finish_batch(
                    transaction,
                    batch_id,
                    status,
                    finished_at,
                    counts,
                    errors,
                )
            )

    def link_page_to_batch(self, page_id: str, batch_id: str) -> None:
        """Link a page to an import batch without writing a page batch property."""

        _require_text(page_id, "page_id")
        _require_text(batch_id, "batch_id")

        with self.driver.session() as session:
            session.execute_write(lambda transaction: _link_page_to_batch(transaction, page_id, batch_id))


def _group_nodes_by_label(nodes: Iterable[GraphNode]) -> dict[str, list[dict[str, object]]]:
    grouped_nodes: dict[str, OrderedDict[str, dict[str, object]]] = defaultdict(OrderedDict)
    for node in nodes:
        label = _single_allowed_label(node)
        properties = dict(node.properties)
        properties["id"] = node.id
        grouped_nodes[label][node.id] = {
            "id": node.id,
            "properties": properties,
        }

    return {
        label: list(nodes_by_id.values())
        for label, nodes_by_id in grouped_nodes.items()
    }


def _group_relations_by_type(relations: Iterable[GraphRelation]) -> dict[str, list[dict[str, object]]]:
    grouped_relations: dict[str, OrderedDict[tuple[str, str], dict[str, object]]] = defaultdict(OrderedDict)
    for relation in relations:
        relation_type = _allowed_relation_type(relation)
        relation_key = (relation.start_id, relation.end_id)
        grouped_relations[relation_type][relation_key] = {
            "start_id": relation.start_id,
            "end_id": relation.end_id,
            "properties": dict(relation.properties),
        }

    return {
        relation_type: list(relations_by_key.values())
        for relation_type, relations_by_key in grouped_relations.items()
    }


def _single_allowed_label(node: GraphNode) -> str:
    if not isinstance(node, GraphNode):
        raise RepositoryError("invalid_node", "nodes must contain GraphNode values")
    if len(node.labels) != 1 or node.labels[0] not in ALLOWED_NODE_LABELS:
        raise RepositoryError("invalid_node_label", "node label must be a single allowed label")
    return node.labels[0]


def _allowed_relation_type(relation: GraphRelation) -> str:
    if not isinstance(relation, GraphRelation):
        raise RepositoryError("invalid_relation", "relations must contain GraphRelation values")
    if not relation.start_id.strip() or not relation.end_id.strip():
        raise RepositoryError("missing_relation_endpoint", "relation endpoints must not be empty")
    if relation.relation_type not in ALLOWED_RELATION_TYPES:
        raise RepositoryError("invalid_relation_type", "relation type must be allowed by the graph schema")
    return relation.relation_type


def _batches(nodes: list[dict[str, object]], batch_size: int) -> Iterable[list[dict[str, object]]]:
    for start_index in range(0, len(nodes), batch_size):
        yield nodes[start_index:start_index + batch_size]


def _merge_node_batch(transaction: Any, label: str, nodes: list[dict[str, object]]) -> None:
    cypher = (
        "UNWIND $nodes AS node\n"
        f"MERGE (n:{label} {{id: node.id}})\n"
        "SET n += node.properties"
    )
    transaction.run(cypher, nodes=nodes)


def _merge_relation_batch(transaction: Any, relation_type: str, relations: list[dict[str, object]]) -> None:
    cypher = (
        "UNWIND $relations AS relation\n"
        "MATCH (start {id: relation.start_id})\n"
        "MATCH (end {id: relation.end_id})\n"
        f"MERGE (start)-[r:{relation_type}]->(end)\n"
        "SET r += relation.properties"
    )
    transaction.run(cypher, relations=relations)


def _create_batch(transaction: Any, batch_id: str, project_id: str, source_root: str, started_at: str) -> None:
    cypher = (
        "MERGE (batch:ImportBatch {id: $batch_id})\n"
        "SET batch.status = 'running',\n"
        "    batch.project_id = $project_id,\n"
        "    batch.source_root = $source_root,\n"
        "    batch.started_at = $started_at,\n"
        "    batch.finished_at = null,\n"
        "    batch.total_files = 0,\n"
        "    batch.success_count = 0,\n"
        "    batch.skipped_count = 0,\n"
        "    batch.failed_count = 0,\n"
        "    batch.warning_count = 0,\n"
        "    batch.error_summary = []"
    )
    transaction.run(
        cypher,
        batch_id=batch_id,
        project_id=project_id,
        source_root=source_root,
        started_at=started_at,
    )


def _finish_batch(
    transaction: Any,
    batch_id: str,
    status: str,
    finished_at: str,
    counts: dict[str, int],
    error_summary: list[str],
) -> None:
    cypher = (
        "MATCH (batch:ImportBatch {id: $batch_id})\n"
        "SET batch.status = $status,\n"
        "    batch.finished_at = $finished_at,\n"
        "    batch.total_files = $total_files,\n"
        "    batch.success_count = $success_count,\n"
        "    batch.skipped_count = $skipped_count,\n"
        "    batch.failed_count = $failed_count,\n"
        "    batch.warning_count = $warning_count,\n"
        "    batch.error_summary = $error_summary"
    )
    transaction.run(
        cypher,
        batch_id=batch_id,
        status=status,
        finished_at=finished_at,
        error_summary=error_summary,
        **counts,
    )


def _link_page_to_batch(transaction: Any, page_id: str, batch_id: str) -> None:
    cypher = (
        "MATCH (page:DrawingPage {id: $page_id})\n"
        "MATCH (batch:ImportBatch {id: $batch_id})\n"
        "MERGE (page)-[:IMPORTED_IN]->(batch)"
    )
    transaction.run(cypher, page_id=page_id, batch_id=batch_id)


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RepositoryError("missing_required_field", f"{field_name} must be a non-empty string")
    return value


def _require_terminal_batch_status(status: str) -> None:
    if status not in ("success", "failed"):
        raise RepositoryError("invalid_batch_status", "batch status must be success or failed")


def _require_non_negative_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RepositoryError("invalid_batch_count", f"{field_name} must be a non-negative integer")
    return value


def _read_error_summary(error_summary: Iterable[str]) -> list[str]:
    if isinstance(error_summary, (str, bytes)):
        raise RepositoryError("invalid_error_summary", "error_summary must be an iterable of strings")
    errors = list(error_summary)
    for index, error in enumerate(errors):
        if not isinstance(error, str) or not error:
            raise RepositoryError("invalid_error_summary", f"error_summary[{index}] must be a non-empty string")
    return errors


__all__ = (
    "ALLOWED_NODE_LABELS",
    "ALLOWED_RELATION_TYPES",
    "Neo4jRepository",
    "RepositoryError",
)
