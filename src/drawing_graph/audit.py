"""Import audit records and sanitized batch summaries."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING


BATCH_STATUSES = ("running", "success", "failed", "skipped")
RELATION_BATCH_STATUSES = ("running", "success", "failed", "partial")
RELATION_ISSUE_CATEGORIES = frozenset(
    (
        "block_caption_unmatched",
        "block_caption_conflict",
        "caption_candidate_not_found",
        "caption_candidate_ambiguous",
        "basic_info_not_found",
        "basic_info_previous_page_missing",
        "basic_info_previous_page_unavailable",
        "basic_info_not_evaluated",
        "basic_info_partial",
        "basic_info_ambiguous",
        "annotation_not_found",
        "cross_section_unmatched",
        "cross_section_conflict",
        "cross_section_ambiguous_overlap",
        "cross_section_low_overlap",
        "section_candidate_ambiguous",
        "section_candidate_low_evidence",
        "section_mark_write_failed",
        "relation_write_failed",
        "table_caption_missing_table",
        "table_caption_invalid_input",
        "table_caption_legacy_conflict",
        "table_caption_write_failed",
    )
)

if TYPE_CHECKING:
    from drawing_graph.block_relation_enrichment import EnrichmentResult, EnrichmentScope


class AuditError(ValueError):
    """Raised when audit data cannot be recorded or summarized."""

    def __init__(self, category: str, message: str):
        self.category = category
        super().__init__(message)


@dataclass(frozen=True)
class AuditIssue:
    """Classified file or element issue stored for audit output."""

    source_path: str
    category: str
    message: str
    shape_index: int | None = None


@dataclass(frozen=True)
class DuplicateShapeRecord:
    """Duplicate shape evidence for deterministic ID de-duplication."""

    source_path: str
    shape_hash: str
    first_shape_index: int
    duplicate_shape_index: int


@dataclass(frozen=True)
class RelationAuditIssue:
    """Classified relation-enrichment issue stored for batch audit output."""

    category: str
    severity: str
    message: str
    page_id: str | None = None
    element_id: str | None = None

    def __post_init__(self) -> None:
        _require_relation_category(self.category)
        if self.severity not in ("warning", "error"):
            raise AuditError("invalid_relation_issue_severity", "severity must be warning or error")
        object.__setattr__(self, "message", sanitize_message(self.message))


@dataclass
class ImportAudit:
    """Accumulate import counts, classified issues, and sanitized summaries."""

    batch_id: str
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    success_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    element_warnings: list[AuditIssue] = field(default_factory=list)
    file_errors: list[AuditIssue] = field(default_factory=list)
    duplicate_shapes: list[DuplicateShapeRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.batch_id:
            raise AuditError("missing_batch_id", "batch_id must not be empty")

    def record_page_success(self, source_path: str) -> None:
        """Record a successfully imported page."""

        _require_text(source_path, "source_path")
        self.success_count += 1

    def record_page_skipped(self, source_path: str, category: str, message: str) -> None:
        """Record a skipped page with a classified reason."""

        self.skipped_count += 1
        self.file_errors.append(_make_issue(source_path, category, message))

    def record_page_failure(self, source_path: str, category: str, message: str) -> None:
        """Record a failed page with a classified reason."""

        self.failed_count += 1
        self.file_errors.append(_make_issue(source_path, category, message))

    def record_element_warning(self, source_path: str, shape_index: int, category: str, message: str) -> None:
        """Record a non-fatal element warning."""

        if not isinstance(shape_index, int) or shape_index < 0:
            raise AuditError("invalid_shape_index", "shape_index must be a non-negative integer")
        self.element_warnings.append(_make_issue(source_path, category, message, shape_index=shape_index))

    def record_duplicate_shape(
        self,
        source_path: str,
        shape_hash: str,
        first_shape_index: int,
        duplicate_shape_index: int,
    ) -> None:
        """Record a duplicate annotation shape without changing page counts."""

        _require_text(source_path, "source_path")
        _require_text(shape_hash, "shape_hash")
        if first_shape_index < 0 or duplicate_shape_index < 0:
            raise AuditError("invalid_shape_index", "shape indexes must be non-negative")
        self.duplicate_shapes.append(
            DuplicateShapeRecord(
                source_path=source_path,
                shape_hash=shape_hash,
                first_shape_index=first_shape_index,
                duplicate_shape_index=duplicate_shape_index,
            )
        )

    def summary(self, status: str = "running") -> dict[str, object]:
        """Return sanitized batch counts and classified error summary."""

        if status not in BATCH_STATUSES:
            raise AuditError("invalid_batch_status", "status must be running, success, failed, or skipped")

        error_summary = Counter(issue.category for issue in self.file_errors)
        return {
            "batch_id": self.batch_id,
            "status": status,
            "started_at": self.started_at.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "total_count": self.success_count + self.skipped_count + self.failed_count,
            "success_count": self.success_count,
            "skipped_count": self.skipped_count,
            "failed_count": self.failed_count,
            "warning_count": len(self.element_warnings),
            "duplicate_shape_count": len(self.duplicate_shapes),
            "error_summary": dict(error_summary),
        }

    def log_records(self) -> list[dict[str, object]]:
        """Return minimal sanitized records suitable for logging."""

        records: list[dict[str, object]] = []
        for issue in self.file_errors:
            records.append(_issue_log_record(self.batch_id, issue))
        for issue in self.element_warnings:
            records.append(_issue_log_record(self.batch_id, issue))
        return records


@dataclass
class RelationBatchAudit:
    """Accumulate relation-enrichment counts, issues, and sanitized summaries."""

    relation_batch_id: str
    project_id: str
    rule_version: str
    drawing_set_id: str | None = None
    page_id: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    page_count: int = 0
    block_count: int = 0
    caption_count: int = 0
    basic_info_count: int = 0
    annotation_count: int = 0
    cross_section_count: int = 0
    table_count: int = 0
    table_caption_count: int = 0
    table_caption_relation_count: int = 0
    uses_basic_info_count: int = 0
    candidate_count: int = 0
    ambiguous_count: int = 0
    not_evaluated_count: int = 0
    reviewing_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    unresolved_count: int = 0
    relation_count: int = 0
    warning_count: int = 0
    error_count: int = 0
    issues: list[RelationAuditIssue] = field(default_factory=list)

    def __post_init__(self) -> None:
        _require_text(self.relation_batch_id, "relation_batch_id")
        _require_text(self.project_id, "project_id")
        _require_text(self.rule_version, "rule_version")
        _require_optional_text(self.drawing_set_id, "drawing_set_id")
        _require_optional_text(self.page_id, "page_id")

    @classmethod
    def from_scope(cls, scope: "EnrichmentScope") -> "RelationBatchAudit":
        """Create a relation audit batch from an enrichment scope."""

        return cls(
            relation_batch_id=scope.relation_batch_id,
            project_id=scope.project_id,
            drawing_set_id=scope.drawing_set_id,
            page_id=scope.page_id,
            rule_version=scope.rule_version,
        )

    def record_enrichment_result(self, result: "EnrichmentResult") -> None:
        """Accumulate one page or scope enrichment result."""

        if result.scope.relation_batch_id != self.relation_batch_id:
            raise AuditError("relation_batch_mismatch", "result relation_batch_id does not match audit batch")
        if result.scope.rule_version != self.rule_version:
            raise AuditError("relation_rule_version_mismatch", "result rule_version does not match audit batch")

        self.page_count += result.stats.page_count
        self.block_count += result.stats.block_count
        self.caption_count += result.stats.caption_count
        self.basic_info_count += result.stats.basic_info_count
        self.annotation_count += result.stats.annotation_count
        self.cross_section_count += result.stats.cross_section_count
        self.table_count += result.stats.table_count
        self.table_caption_count += result.stats.table_caption_count
        self.table_caption_relation_count += result.stats.table_caption_relation_count
        self.uses_basic_info_count += result.stats.uses_basic_info_count
        self.candidate_count += result.stats.candidate_count
        self.ambiguous_count += result.stats.ambiguous_count
        self.not_evaluated_count += result.stats.not_evaluated_count
        self.reviewing_count += result.stats.reviewing_count
        self.accepted_count += result.stats.accepted_count
        self.rejected_count += result.stats.rejected_count
        self.unresolved_count += result.stats.unresolved_count
        self.relation_count += result.stats.relation_count
        self.warning_count += result.stats.warning_count
        self.error_count += result.stats.error_count
        for issue in result.issues:
            self.record_issue(
                category=issue.category,
                severity=issue.severity,
                message=issue.message,
                page_id=issue.page_id,
                element_id=issue.element_id,
            )

    def record_issue(
        self,
        *,
        category: str,
        severity: str,
        message: str,
        page_id: str | None = None,
        element_id: str | None = None,
    ) -> None:
        """Record one classified relation warning or error."""

        self.issues.append(
            RelationAuditIssue(
                category=category,
                severity=severity,
                message=message,
                page_id=page_id,
                element_id=element_id,
            )
        )

    def record_write_failure(
        self,
        *,
        message: str,
        page_id: str | None = None,
        element_id: str | None = None,
    ) -> None:
        """Record a relation-write failure without exposing credentials."""

        self.error_count += 1
        self.record_issue(
            category="relation_write_failed",
            severity="error",
            message=message,
            page_id=page_id,
            element_id=element_id,
        )

    def summary(self, status: str = "running") -> dict[str, object]:
        """Return sanitized relation batch status, counts, and issue summary."""

        if status not in RELATION_BATCH_STATUSES:
            raise AuditError("invalid_relation_batch_status", "status must be running, success, failed, or partial")

        return {
            "relation_batch_id": self.relation_batch_id,
            "status": status,
            "started_at": self.started_at.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "project_id": self.project_id,
            "drawing_set_id": self.drawing_set_id,
            "page_id": self.page_id,
            "rule_version": self.rule_version,
            "page_count": self.page_count,
            "block_count": self.block_count,
            "caption_count": self.caption_count,
            "basic_info_count": self.basic_info_count,
            "annotation_count": self.annotation_count,
            "cross_section_count": self.cross_section_count,
            "table_count": self.table_count,
            "table_caption_count": self.table_caption_count,
            "table_caption_relation_count": self.table_caption_relation_count,
            "uses_basic_info_count": self.uses_basic_info_count,
            "candidate_count": self.candidate_count,
            "ambiguous_count": self.ambiguous_count,
            "not_evaluated_count": self.not_evaluated_count,
            "reviewing_count": self.reviewing_count,
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "unresolved_count": self.unresolved_count,
            "relation_count": self.relation_count,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "issue_summary": dict(Counter(issue.category for issue in self.issues)),
        }

    def log_records(self) -> list[dict[str, object]]:
        """Return minimal sanitized relation audit records suitable for logging."""

        records: list[dict[str, object]] = []
        for issue in self.issues:
            record: dict[str, object] = {
                "relation_batch_id": self.relation_batch_id,
                "project_id": self.project_id,
                "rule_version": self.rule_version,
                "category": issue.category,
                "severity": issue.severity,
                "message": issue.message,
            }
            if issue.page_id is not None:
                record["page_id"] = issue.page_id
            if issue.element_id is not None:
                record["element_id"] = issue.element_id
            records.append(record)
        return records


@dataclass
class RelationAuditStore:
    """In-memory lookup for relation audit batches by relation_batch_id."""

    batches: dict[str, RelationBatchAudit] = field(default_factory=dict)

    def create_batch(self, scope: "EnrichmentScope") -> RelationBatchAudit:
        """Create and store a relation audit batch for the given scope."""

        audit = RelationBatchAudit.from_scope(scope)
        self.batches[audit.relation_batch_id] = audit
        return audit

    def get_summary(self, relation_batch_id: str, status: str = "running") -> dict[str, object] | None:
        """Return a relation audit summary by batch ID, or None when absent."""

        _require_text(relation_batch_id, "relation_batch_id")
        audit = self.batches.get(relation_batch_id)
        if audit is None:
            return None
        return audit.summary(status=status)


def _make_issue(source_path: str, category: str, message: str, shape_index: int | None = None) -> AuditIssue:
    _require_text(source_path, "source_path")
    _require_text(category, "category")
    return AuditIssue(
        source_path=source_path,
        category=category,
        message=sanitize_message(message),
        shape_index=shape_index,
    )


def _issue_log_record(batch_id: str, issue: AuditIssue) -> dict[str, object]:
    record: dict[str, object] = {
        "batch_id": batch_id,
        "source_path": issue.source_path,
        "category": issue.category,
        "message": issue.message,
    }
    if issue.shape_index is not None:
        record["shape_index"] = issue.shape_index
    return record


def sanitize_message(message: str) -> str:
    """Mask passwords, tokens, and URI credentials from audit text."""

    if not isinstance(message, str):
        raise AuditError("invalid_message", "message must be a string")

    sanitized = re.sub(r"\b(password|token)=\S+", r"\1=********", message, flags=re.IGNORECASE)
    sanitized = re.sub(r"\b([a-z][a-z0-9+.-]*://)([^/\s:@]+):([^@\s/]+)@([^\s/]+)", r"\1********:********@\4", sanitized)
    return sanitized


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise AuditError("missing_required_field", f"{field_name} must be a non-empty string")


def _require_optional_text(value: str | None, field_name: str) -> None:
    if value is not None:
        _require_text(value, field_name)


def _require_relation_category(category: str) -> None:
    _require_text(category, "category")
    if category not in RELATION_ISSUE_CATEGORIES:
        raise AuditError("invalid_relation_issue_category", "category must be a supported relation audit category")


__all__ = (
    "AuditError",
    "AuditIssue",
    "DuplicateShapeRecord",
    "ImportAudit",
    "RELATION_ISSUE_CATEGORIES",
    "RelationAuditIssue",
    "RelationAuditStore",
    "RelationBatchAudit",
    "sanitize_message",
)
