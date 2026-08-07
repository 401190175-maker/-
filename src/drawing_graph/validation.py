"""JSON structure validation for XAnyLabeling annotation documents."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ValidationStatus(str, Enum):
    """Classified validation outcome for one annotation document."""

    IMPORTABLE = "importable"
    REPAIRABLE = "repairable"
    INVALID = "invalid"


@dataclass(frozen=True)
class ValidationIssue:
    """A categorized validation problem with a stable location string."""

    category: str
    location: str
    message: str


@dataclass(frozen=True)
class ValidationResult:
    """Validation result containing a status and categorized issues."""

    status: ValidationStatus
    issues: tuple[ValidationIssue, ...]


PAGE_REQUIRED_FIELDS = ("imagePath", "imageWidth", "imageHeight", "shapes")
SHAPE_REQUIRED_FIELDS = ("label", "points", "shape_type")


def validate_document(document: Any) -> ValidationResult:
    """Validate page-level and shape-level JSON structure without mutating input."""

    parsed_document, parse_issue = _parse_document(document)
    if parse_issue is not None:
        return ValidationResult(ValidationStatus.INVALID, (parse_issue,))

    if not isinstance(parsed_document, dict):
        return ValidationResult(
            ValidationStatus.INVALID,
            (
                ValidationIssue(
                    category="invalid_document_type",
                    location="$",
                    message="document must be a JSON object",
                ),
            ),
        )

    issues = [
        issue
        for field_name in PAGE_REQUIRED_FIELDS
        if (issue := _missing_page_field_issue(parsed_document, field_name)) is not None
    ]

    shapes = parsed_document.get("shapes")
    if "shapes" in parsed_document and not isinstance(shapes, list):
        issues.append(
            ValidationIssue(
                category="invalid_page_field",
                location="shapes",
                message="shapes must be a list",
            )
        )
    elif isinstance(shapes, list):
        issues.extend(_validate_shapes(shapes))

    return ValidationResult(_status_for_issues(issues), tuple(issues))


def _parse_document(document: Any) -> tuple[Any, ValidationIssue | None]:
    if isinstance(document, bytes):
        document = document.decode("utf-8")

    if isinstance(document, str):
        try:
            return json.loads(document), None
        except json.JSONDecodeError as error:
            return None, ValidationIssue(
                category="json_parse_error",
                location="$",
                message=f"invalid JSON: {error.msg}",
            )

    return document, None


def _missing_page_field_issue(document: dict[str, Any], field_name: str) -> ValidationIssue | None:
    if field_name in document:
        return None

    return ValidationIssue(
        category="missing_page_field",
        location=field_name,
        message=f"missing required page field: {field_name}",
    )


def _validate_shapes(shapes: list[Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    for index, shape in enumerate(shapes):
        location = f"shapes[{index}]"
        if not isinstance(shape, dict):
            issues.append(
                ValidationIssue(
                    category="invalid_shape_type",
                    location=location,
                    message="shape must be a JSON object",
                )
            )
            continue

        for field_name in SHAPE_REQUIRED_FIELDS:
            if field_name not in shape:
                issues.append(
                    ValidationIssue(
                        category="missing_shape_field",
                        location=location,
                        message=f"missing required shape field: {field_name}",
                    )
                )

        if "points" in shape and not shape["points"]:
            issues.append(
                ValidationIssue(
                    category="empty_points",
                    location=f"{location}.points",
                    message="shape points must not be empty",
                )
            )

    return issues


def _status_for_issues(issues: list[ValidationIssue]) -> ValidationStatus:
    if not issues:
        return ValidationStatus.IMPORTABLE

    if any(issue.category.startswith(("missing_page_", "invalid_page_")) for issue in issues):
        return ValidationStatus.INVALID

    return ValidationStatus.REPAIRABLE


__all__ = (
    "ValidationIssue",
    "ValidationResult",
    "ValidationStatus",
    "validate_document",
)
