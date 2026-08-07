"""Service orchestration for offline block-level relation enrichment."""

from __future__ import annotations

from typing import Any

from drawing_graph.audit import RelationAuditStore
from drawing_graph.block_relation_enrichment import (
    EnrichmentResult,
    EnrichmentScope,
    EnrichmentStats,
    enrich_page_relations,
)


ENRICHMENT_SCOPE_READ_LIMIT = 10000


class RelationServiceError(ValueError):
    """Raised when relation enrichment service inputs are invalid."""

    def __init__(self, category: str, message: str):
        self.category = category
        super().__init__(message)


class RelationEnrichmentService:
    """Coordinate page reads, rule calculation, relation writes, and audit summaries."""

    def __init__(self, repository: Any, audit_store: RelationAuditStore | None = None):
        self.repository = repository
        self.audit_store = audit_store or RelationAuditStore()
        self._batch_statuses: dict[str, str] = {}

    def enrich_page(self, scope: EnrichmentScope) -> EnrichmentResult:
        """Run block-level relation enrichment for exactly one page scope."""

        if not isinstance(scope, EnrichmentScope):
            raise RelationServiceError("invalid_scope", "scope must be an EnrichmentScope")
        if scope.page_id is None:
            raise RelationServiceError("missing_page_id", "page_id is required for page enrichment")

        audit = self.audit_store.create_batch(scope)
        self._batch_statuses[scope.relation_batch_id] = "running"
        pages = tuple(self.repository.read_pages(scope, limit=1))
        if not pages:
            self._batch_statuses[scope.relation_batch_id] = "failed"
            return EnrichmentResult(
                scope=scope,
                stats=EnrichmentStats(),
            )

        page = pages[0]
        result = enrich_page_relations(
            scope,
            page,
            previous_page=None,
            previous_page_context_available=False,
        )
        audit.record_enrichment_result(result)

        if result.relations:
            write_result = _write_page_relations(self.repository, audit, page_id=page.page_id, relations=result.relations)
            if write_result == "failed":
                self._batch_statuses[scope.relation_batch_id] = "failed"
                return result
            if write_result == "partial":
                self._batch_statuses[scope.relation_batch_id] = "partial"
                return result

        self._batch_statuses[scope.relation_batch_id] = _status_for_result(result)
        return result

    def enrich_drawing_set(self, scope: EnrichmentScope) -> EnrichmentResult:
        """Run block-level relation enrichment for all pages in one drawing set."""

        if not isinstance(scope, EnrichmentScope):
            raise RelationServiceError("invalid_scope", "scope must be an EnrichmentScope")
        if scope.drawing_set_id is None:
            raise RelationServiceError("missing_drawing_set_id", "drawing_set_id is required for drawing-set enrichment")
        if scope.page_id is not None:
            raise RelationServiceError("invalid_drawing_set_scope", "page_id must be omitted for drawing-set enrichment")

        audit = self.audit_store.create_batch(scope)
        self._batch_statuses[scope.relation_batch_id] = "running"
        pages = tuple(
            sorted(
                self.repository.read_pages(scope, limit=ENRICHMENT_SCOPE_READ_LIMIT),
                key=lambda page: (page.page_number, page.page_id),
            )
        )
        if not pages:
            result = EnrichmentResult(scope=scope, stats=EnrichmentStats())
            self._batch_statuses[scope.relation_batch_id] = "success"
            return result

        previous_page = None
        page_results = []
        write_failed = False
        write_partial = False
        for page in pages:
            current_previous_page = previous_page if _is_immediate_previous_page(page, previous_page) else None
            result = enrich_page_relations(
                scope,
                page,
                previous_page=current_previous_page,
                previous_page_context_available=True,
            )
            audit.record_enrichment_result(result)
            page_results.append(result)

            if result.relations:
                write_result = _write_page_relations(
                    self.repository,
                    audit,
                    page_id=page.page_id,
                    relations=result.relations,
                )
                if write_result == "failed":
                    write_failed = True
                elif write_result == "partial":
                    write_partial = True

            previous_page = page

        combined_result = _combine_results(scope, page_results)
        if write_failed or write_partial or combined_result.stats.warning_count or combined_result.stats.error_count:
            self._batch_statuses[scope.relation_batch_id] = "partial"
        else:
            self._batch_statuses[scope.relation_batch_id] = "success"
        return combined_result

    def enrich_project(self, scope: EnrichmentScope) -> EnrichmentResult:
        """Run block-level relation enrichment for all drawing sets in one project."""

        if not isinstance(scope, EnrichmentScope):
            raise RelationServiceError("invalid_scope", "scope must be an EnrichmentScope")
        if scope.drawing_set_id is not None or scope.page_id is not None:
            raise RelationServiceError("invalid_project_scope", "drawing_set_id and page_id must be omitted for project enrichment")

        audit = self.audit_store.create_batch(scope)
        self._batch_statuses[scope.relation_batch_id] = "running"
        pages = tuple(
            sorted(
                self.repository.read_pages(scope, limit=ENRICHMENT_SCOPE_READ_LIMIT),
                key=lambda page: (page.drawing_set_id, page.page_number, page.page_id),
            )
        )
        if not pages:
            result = EnrichmentResult(scope=scope, stats=EnrichmentStats())
            self._batch_statuses[scope.relation_batch_id] = "failed"
            return result

        previous_pages_by_set = {}
        page_results = []
        write_failed = False
        write_partial = False
        for page in pages:
            previous_page = previous_pages_by_set.get(page.drawing_set_id)
            current_previous_page = previous_page if _is_immediate_previous_page(page, previous_page) else None
            result = enrich_page_relations(
                scope,
                page,
                previous_page=current_previous_page,
                previous_page_context_available=True,
            )
            audit.record_enrichment_result(result)
            page_results.append(result)

            if result.relations:
                write_result = _write_page_relations(
                    self.repository,
                    audit,
                    page_id=page.page_id,
                    relations=result.relations,
                )
                if write_result == "failed":
                    write_failed = True
                elif write_result == "partial":
                    write_partial = True

            previous_pages_by_set[page.drawing_set_id] = page

        combined_result = _combine_results(scope, page_results)
        if write_failed or write_partial or combined_result.stats.warning_count or combined_result.stats.error_count:
            self._batch_statuses[scope.relation_batch_id] = "partial"
        else:
            self._batch_statuses[scope.relation_batch_id] = "success"
        return combined_result

    def get_batch_summary(self, relation_batch_id: str) -> dict[str, object] | None:
        """Return the latest audit summary for a relation-enrichment batch."""

        if not isinstance(relation_batch_id, str) or not relation_batch_id:
            raise RelationServiceError("missing_relation_batch_id", "relation_batch_id must be a non-empty string")
        status = self._batch_statuses.get(relation_batch_id, "running")
        return self.audit_store.get_summary(relation_batch_id, status=status)


def _status_for_result(result: EnrichmentResult) -> str:
    if result.stats.error_count:
        return "failed"
    if result.stats.warning_count:
        return "partial"
    return "success"


def _record_page_write_failure(audit: Any, *, message: str, page_id: str, relations: tuple[Any, ...]) -> None:
    section_mark_relation = next(
        (relation for relation in relations if relation.relation_type == "HAS_SECTION_MARK"),
        None,
    )
    if section_mark_relation is None:
        audit.record_write_failure(message=message, page_id=page_id)
        return

    audit.error_count += 1
    audit.record_issue(
        category="section_mark_write_failed",
        severity="error",
        message=message,
        page_id=page_id,
        element_id=section_mark_relation.end_id,
    )


def _write_page_relations(repository: Any, audit: Any, *, page_id: str, relations: tuple[Any, ...]) -> str:
    """Write block relations in batch and table-caption relations one candidate at a time."""

    block_relations = tuple(relation for relation in relations if relation.relation_spec != "table_caption")
    table_caption_relations = tuple(relation for relation in relations if relation.relation_spec == "table_caption")
    had_warning = False
    had_error = False

    if block_relations:
        try:
            repository.write_relations(block_relations)
        except Exception as exc:  # noqa: BLE001 - service boundary classifies repository failures.
            _record_page_write_failure(audit, message=str(exc), page_id=page_id, relations=block_relations)
            return "failed"

    for relation in table_caption_relations:
        try:
            repository.write_relations((relation,))
        except Exception as exc:  # noqa: BLE001 - service boundary classifies repository failures.
            category = getattr(exc, "category", None)
            if category == "table_caption_legacy_conflict":
                had_warning = True
                audit.warning_count += 1
                audit.record_issue(
                    category="table_caption_legacy_conflict",
                    severity="warning",
                    message=str(exc),
                    page_id=page_id,
                    element_id=relation.end_id,
                )
            else:
                had_error = True
                audit.error_count += 1
                audit.record_issue(
                    category="table_caption_write_failed",
                    severity="error",
                    message=str(exc),
                    page_id=page_id,
                    element_id=relation.end_id,
                )

    if had_error:
        return "failed"
    if had_warning:
        return "partial"
    return "success"


def _combine_results(scope: EnrichmentScope, results: list[EnrichmentResult]) -> EnrichmentResult:
    relations = tuple(relation for result in results for relation in result.relations)
    issues = tuple(issue for result in results for issue in result.issues)
    return EnrichmentResult(
        scope=scope,
        relations=relations,
        issues=issues,
        stats=EnrichmentStats(
            page_count=sum(result.stats.page_count for result in results),
            block_count=sum(result.stats.block_count for result in results),
            caption_count=sum(result.stats.caption_count for result in results),
            basic_info_count=sum(result.stats.basic_info_count for result in results),
            annotation_count=sum(result.stats.annotation_count for result in results),
            cross_section_count=sum(result.stats.cross_section_count for result in results),
            table_count=sum(result.stats.table_count for result in results),
            table_caption_count=sum(result.stats.table_caption_count for result in results),
            table_caption_relation_count=sum(result.stats.table_caption_relation_count for result in results),
            uses_basic_info_count=sum(result.stats.uses_basic_info_count for result in results),
            candidate_count=sum(result.stats.candidate_count for result in results),
            ambiguous_count=sum(result.stats.ambiguous_count for result in results),
            not_evaluated_count=sum(result.stats.not_evaluated_count for result in results),
            reviewing_count=sum(result.stats.reviewing_count for result in results),
            accepted_count=sum(result.stats.accepted_count for result in results),
            rejected_count=sum(result.stats.rejected_count for result in results),
            unresolved_count=sum(result.stats.unresolved_count for result in results),
            relation_count=sum(result.stats.relation_count for result in results),
            warning_count=sum(result.stats.warning_count for result in results),
            error_count=sum(result.stats.error_count for result in results),
        ),
    )


def _is_immediate_previous_page(page: Any, previous_page: Any | None) -> bool:
    return (
        previous_page is not None
        and previous_page.drawing_set_id == page.drawing_set_id
        and previous_page.page_number == page.page_number - 1
    )


__all__ = (
    "RelationEnrichmentService",
    "RelationServiceError",
)
