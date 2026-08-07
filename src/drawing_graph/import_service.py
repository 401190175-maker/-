"""Single-page import orchestration for the drawing graph ETL."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from drawing_graph.config import ImportConfig
from drawing_graph.geometry import GeometryError, normalize_geometry
from drawing_graph.identifiers import make_element_id, make_page_id, make_project_id, make_set_id, make_shape_hash
from drawing_graph.image_paths import ImagePathError, ImagePathStatus, normalize_image_path
from drawing_graph.mapping import MappingError, map_element
from drawing_graph.models import BBox, ElementRecord, GraphNode, GraphRelation, ImportResult, NormalizedBBox
from drawing_graph.page_number import PageNumberError, parse_page_number
from drawing_graph.scanner import ScannerError, scan_drawing_sets
from drawing_graph.validation import ValidationStatus, validate_document


class ImportService:
    """Coordinate validation, normalization, mapping, and persistence."""

    def __init__(self, config: ImportConfig, repository: Any):
        self.config = config
        self.repository = repository

    def import_page(self, batch_id: str, json_path: str | Path) -> ImportResult:
        """Import one JSON page and return classified page-level status."""

        warnings: list[str] = []
        json_file = Path(json_path)

        try:
            document = _read_json_document(json_file)
        except (OSError, json.JSONDecodeError):
            return ImportResult(status="failed", page_id=None, errors=("json_parse_error",))

        validation_result = validate_document(document)
        if validation_result.status == ValidationStatus.INVALID:
            return ImportResult(
                status="failed",
                page_id=None,
                errors=tuple(_issue_categories(validation_result.issues)),
            )
        warnings.extend(_issue_categories(validation_result.issues))

        try:
            image_result = normalize_image_path(json_file, document, self.config.data_root)
        except ImagePathError as error:
            return ImportResult(status="failed", page_id=None, errors=(error.category,))

        if image_result.status == ImagePathStatus.MISSING_IMAGE:
            issue_category = image_result.issue.category if image_result.issue is not None else "missing_image"
            return ImportResult(status="skipped", page_id=None, errors=(issue_category,))

        try:
            page_number = parse_page_number(json_file)
        except PageNumberError as error:
            return ImportResult(status="failed", page_id=None, errors=(error.category,))

        drawing_set_name = json_file.parent.name
        page_id = make_page_id(self.config.project_slug, drawing_set_name, json_file.stem)
        nodes, relations, element_warnings = _build_graph_payload(
            config=self.config,
            json_file=json_file,
            document=document,
            image_path=image_result.image_path,
            original_image_path=image_result.original_image_path,
            page_id=page_id,
            page_number=page_number,
            drawing_set_name=drawing_set_name,
        )
        warnings.extend(element_warnings)

        try:
            self.repository.merge_nodes(nodes)
            self.repository.merge_relations(relations)
            self.repository.link_page_to_batch(page_id, batch_id)
        except Exception:
            return ImportResult(
                status="failed",
                page_id=page_id,
                warnings=tuple(warnings),
                errors=("persistence_failed",),
            )

        return ImportResult(status="success", page_id=page_id, warnings=tuple(warnings), errors=())

    def import_drawing_set(self, batch_id: str, drawing_set_path: str | Path) -> "DrawingSetImportResult":
        """Import all JSON pages in one drawing set while isolating page failures."""

        drawing_set_dir = Path(drawing_set_path)
        drawing_set_id = make_set_id(self.config.project_slug, drawing_set_dir.name)
        json_files = _sorted_json_files(drawing_set_dir, self.config.data_root)

        if not json_files:
            return DrawingSetImportResult(
                status="skipped",
                drawing_set_id=drawing_set_id,
                total_count=0,
                success_count=0,
                skipped_count=0,
                failed_count=0,
                warning_count=0,
                warnings=(),
                errors=("empty_drawing_set",),
            )

        success_count = 0
        skipped_count = 0
        failed_count = 0
        warnings: list[str] = []
        errors: list[str] = []

        for json_file in json_files:
            page_result = self.import_page(batch_id, json_file)
            if page_result.status == "success":
                success_count += 1
            elif page_result.status == "skipped":
                skipped_count += 1
            else:
                failed_count += 1
            warnings.extend(page_result.warnings)
            errors.extend(page_result.errors)

        return DrawingSetImportResult(
            status="failed" if failed_count else "success",
            drawing_set_id=drawing_set_id,
            total_count=len(json_files),
            success_count=success_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
            warning_count=len(warnings),
            warnings=tuple(_unique_in_order(warnings)),
            errors=tuple(_unique_in_order(errors)),
        )

    def import_all(self) -> "AllImportResult":
        """Create one batch and import every drawing set under the configured data root."""

        batch_id = _make_batch_id()
        started_at = _utc_now()
        try:
            self.repository.create_batch(
                batch_id=batch_id,
                project_id=make_project_id(self.config.project_slug),
                source_root=str(self.config.data_root),
                started_at=started_at,
            )
        except Exception:
            return AllImportResult(
                status="failed",
                batch_id=None,
                total_count=0,
                success_count=0,
                skipped_count=0,
                failed_count=0,
                warning_count=0,
                warnings=(),
                errors=("batch_create_failed",),
            )

        total_count = 0
        success_count = 0
        skipped_count = 0
        failed_count = 0
        warning_count = 0
        warnings: list[str] = []
        errors: list[str] = []

        try:
            drawing_sets = scan_drawing_sets(self.config.data_root)
            for drawing_set in drawing_sets:
                drawing_set_result = self.import_drawing_set(batch_id, drawing_set.path)
                total_count += drawing_set_result.total_count
                success_count += drawing_set_result.success_count
                skipped_count += drawing_set_result.skipped_count
                failed_count += drawing_set_result.failed_count
                warning_count += drawing_set_result.warning_count
                warnings.extend(drawing_set_result.warnings)
                errors.extend(drawing_set_result.errors)
                if "persistence_failed" in drawing_set_result.errors:
                    break
        except ScannerError as error:
            errors.append("scan_failed")
            failed_count += 1
        except Exception:
            errors.append("persistence_failed")
            failed_count += 1

        status = "failed" if failed_count else "success"
        unique_errors = tuple(_unique_in_order(errors))
        unique_warnings = tuple(_unique_in_order(warnings))
        self.repository.finish_batch(
            batch_id=batch_id,
            status=status,
            finished_at=_utc_now(),
            total_files=total_count,
            success_count=success_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
            warning_count=warning_count,
            error_summary=unique_errors,
        )

        return AllImportResult(
            status=status,
            batch_id=batch_id,
            total_count=total_count,
            success_count=success_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
            warning_count=warning_count,
            warnings=unique_warnings,
            errors=unique_errors,
        )


@dataclass(frozen=True)
class DrawingSetImportResult:
    """Drawing-set import summary with isolated page counts and issues."""

    status: str
    drawing_set_id: str
    total_count: int
    success_count: int
    skipped_count: int
    failed_count: int
    warning_count: int
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class AllImportResult:
    """Full data-root import summary with final batch status and counts."""

    status: str
    batch_id: str | None
    total_count: int
    success_count: int
    skipped_count: int
    failed_count: int
    warning_count: int
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


def _read_json_document(json_file: Path) -> dict[str, Any]:
    with json_file.open("r", encoding="utf-8") as file:
        document = json.load(file)
    if not isinstance(document, dict):
        raise json.JSONDecodeError("document must be an object", "", 0)
    return document


def _sorted_json_files(drawing_set_dir: Path, data_root: Path) -> tuple[Path, ...]:
    root_resolved = data_root.expanduser().resolve()
    try:
        drawing_set_dir.resolve().relative_to(root_resolved)
    except ValueError:
        return ()
    if not drawing_set_dir.is_dir():
        return ()
    return tuple(sorted(drawing_set_dir.glob("*.json"), key=lambda path: path.name))


def _build_graph_payload(
    config: ImportConfig,
    json_file: Path,
    document: dict[str, Any],
    image_path: Path | None,
    original_image_path: str | None,
    page_id: str,
    page_number: int,
    drawing_set_name: str,
) -> tuple[list[GraphNode], list[GraphRelation], list[str]]:
    project_id = make_project_id(config.project_slug)
    set_id = make_set_id(config.project_slug, drawing_set_name)
    image_path_text = str(image_path) if image_path is not None else str(json_file.with_suffix(".png"))
    original_path_text = original_image_path or document["imagePath"]

    nodes = [
        GraphNode(
            id=project_id,
            labels=("Project",),
            properties={
                "id": project_id,
                "name": config.project_slug,
                "project_code": config.project_slug,
                "source_root": str(config.data_root),
                "metadata_status": "minimal",
            },
        ),
        GraphNode(
            id=set_id,
            labels=("DrawingSet",),
            properties={
                "id": set_id,
                "name": drawing_set_name,
                "source_dir": str(json_file.parent),
                "page_count": 1,
                "json_count": 1,
                "image_count": 1,
            },
        ),
        GraphNode(
            id=page_id,
            labels=("DrawingPage",),
            properties={
                "id": page_id,
                "page_number": page_number,
                "file_name": json_file.name,
                "json_path": str(json_file),
                "image_path": image_path_text,
                "original_image_path": original_path_text,
                "image_width": document["imageWidth"],
                "image_height": document["imageHeight"],
            },
        ),
    ]
    relations = [
        GraphRelation(start_id=project_id, end_id=set_id, relation_type="HAS_SET", properties={}),
        GraphRelation(start_id=set_id, end_id=page_id, relation_type="HAS_PAGE", properties={}),
    ]

    element_records, element_warnings = _build_element_records(config, json_file, document, page_id, drawing_set_name)
    for element_record in element_records:
        node, relation = map_element(element_record)
        nodes.append(node)
        relations.append(relation)

    return nodes, relations, element_warnings


def _build_element_records(
    config: ImportConfig,
    json_file: Path,
    document: dict[str, Any],
    page_id: str,
    drawing_set_name: str,
) -> tuple[list[ElementRecord], list[str]]:
    records: list[ElementRecord] = []
    warnings: list[str] = []
    seen_hashes: dict[str, int] = {}

    for shape_index, shape in enumerate(document.get("shapes", [])):
        try:
            element_record, shape_hash = _build_element_record(
                config,
                json_file,
                document,
                page_id,
                drawing_set_name,
                shape,
                shape_index,
            )
        except (GeometryError, MappingError, TypeError, ValueError) as error:
            warnings.append(getattr(error, "category", "invalid_shape"))
            continue

        if shape_hash in seen_hashes:
            warnings.append("duplicate_shape")
            continue

        seen_hashes[shape_hash] = shape_index
        records.append(element_record)

    return records, warnings


def _build_element_record(
    config: ImportConfig,
    json_file: Path,
    document: dict[str, Any],
    page_id: str,
    drawing_set_name: str,
    shape: Any,
    shape_index: int,
) -> tuple[ElementRecord, str]:
    if not isinstance(shape, dict):
        raise ValueError("invalid_shape")

    normalized_shape = dict(shape)
    normalized_shape["label"] = _normalize_label(shape.get("label"))
    shape_hash = make_shape_hash(normalized_shape)
    element_kind = "block" if normalized_shape["label"] == "block" else "element"
    element_id = make_element_id(element_kind, config.project_slug, drawing_set_name, json_file.stem, shape_hash)
    geometry = normalize_geometry(shape.get("points"), document["imageWidth"], document["imageHeight"])

    return (
        ElementRecord(
            id=element_id,
            page_id=page_id,
            label=normalized_shape["label"],
            confidence=_read_confidence(shape),
            shape_type=str(shape.get("shape_type")),
            bbox=BBox(**geometry.bbox),
            normalized_bbox=NormalizedBBox(**geometry.normalized_bbox),
            source_label=str(shape.get("label")),
            original_points=tuple((float(point[0]), float(point[1])) for point in shape["points"]),
            citation_ref=f"{drawing_set_name}/{json_file.stem}#shape-{shape_index}",
        ),
        shape_hash,
    )


def _normalize_label(label: Any) -> str:
    if not isinstance(label, str) or not label.strip():
        raise ValueError("missing_label")
    return " ".join(label.strip().lower().split())


def _read_confidence(shape: dict[str, Any]) -> float | None:
    confidence = shape.get("score", shape.get("confidence"))
    if confidence is None:
        return None
    return float(confidence)


def _issue_categories(issues: Any) -> list[str]:
    return [issue.category for issue in issues]


def _unique_in_order(values: list[str]) -> list[str]:
    seen_values: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        if value in seen_values:
            continue
        seen_values.add(value)
        unique_values.append(value)
    return unique_values


def _make_batch_id() -> str:
    return f"batch:{uuid4().hex}"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


__all__ = ("AllImportResult", "DrawingSetImportResult", "ImportService")
