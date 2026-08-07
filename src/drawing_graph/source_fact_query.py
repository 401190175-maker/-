"""Projection of single-page source facts into facade DTOs."""

from __future__ import annotations

from typing import Any

from .tool_models import BBox, ElementEvidence, PageSourceFacts, ToolModelError


class SourceFactQuery:
    """Read one page through an injected reader and return stable source facts."""

    def __init__(self, page_reader: Any):
        self.page_reader = page_reader

    def get_page_source_facts(
        self,
        page_id: str,
        element_types: tuple[str, ...] | None = None,
        include_image_meta: bool = True,
    ) -> PageSourceFacts:
        raw_page = self.page_reader.read_page_source_facts(page_id)
        if raw_page is None:
            raise ToolModelError("NOT_FOUND", "page source facts were not found")
        allowed_types = set(element_types) if element_types is not None else None
        elements = tuple(
            _element(raw_element)
            for raw_element in raw_page.get("elements", ())
            if allowed_types is None or raw_element.get("element_type") in allowed_types
        )
        image_size = None
        if include_image_meta:
            image_size = _image_size(raw_page)
        return PageSourceFacts(
            page_id=_text(raw_page.get("page_id"), "page_id"),
            image_path=raw_page.get("image_path"),
            image_size=image_size,
            image_hash=raw_page.get("image_hash"),
            elements=elements,
        )


class Neo4jPageSourceFactReader:
    """Read source page facts directly from Neo4j for facade use."""

    def __init__(self, driver: Any):
        self.driver = driver

    def read_page_source_facts(self, page_id: str) -> dict[str, Any] | None:
        _text(page_id, "page_id")
        with self.driver.session() as session:
            return session.execute_read(lambda transaction: _read_page_source_facts(transaction, page_id))


def _read_page_source_facts(transaction: Any, page_id: str) -> dict[str, Any] | None:
    records = list(transaction.run(_page_source_facts_query(), page_id=page_id))
    if not records:
        return None
    record = records[0]
    return {
        "page_id": record["page_id"],
        "image_path": record["image_path"],
        "image_width": record["image_width"],
        "image_height": record["image_height"],
        "image_hash": record["image_hash"],
        "elements": [
            _raw_element(element)
            for element in (record["elements"] or ())
            if element and element.get("id") is not None
        ],
    }


def _page_source_facts_query() -> str:
    return (
        "MATCH (page:DrawingPage {id: $page_id})\n"
        "OPTIONAL MATCH (page)-[:HAS_BLOCK|HAS_TABLE|HAS_ELEMENT|HAS_BASIC_INFO|HAS_ANNOTATION|HAS_TEXT]->(element)\n"
        "WHERE element IS NULL OR coalesce(element.queryable, true) = true\n"
        "RETURN page.id AS page_id,\n"
        "       page.image_path AS image_path,\n"
        "       page.image_width AS image_width,\n"
        "       page.image_height AS image_height,\n"
        "       page.image_hash AS image_hash,\n"
        "       collect(DISTINCT {\n"
        "           id: element.id,\n"
        "           labels: labels(element),\n"
        "           source_label: element.source_label,\n"
        "           bbox: element.bbox,\n"
        "           normalized_bbox: element.normalized_bbox\n"
        "       }) AS elements\n"
        "LIMIT 1"
    )


def _raw_element(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _text(value.get("id"), "id"),
        "element_type": _element_type(value.get("labels") or ()),
        "source_label": _text(value.get("source_label"), "source_label"),
        "bbox": _bbox_dict(value.get("bbox")),
        "normalized_bbox": _bbox_dict(value.get("normalized_bbox")),
    }


def _element_type(labels: Any) -> str:
    priority = (
        "DrawingBlock",
        "BlockCaption",
        "CrossSection",
        "DrawingBasicInfo",
        "DrawingAnnotation",
        "Table",
        "TableCaption",
        "Title",
        "PlainText",
    )
    label_set = set(labels)
    for label in priority:
        if label in label_set:
            return label
    raise ToolModelError("unknown_element_type", "element has no supported source fact label")


def _bbox_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, (list, tuple)):
        if len(value) != 4:
            raise ToolModelError("invalid_bbox", "bbox must contain four coordinates")
        return {
            "x_min": value[0],
            "y_min": value[1],
            "x_max": value[2],
            "y_max": value[3],
        }
    if isinstance(value, dict):
        return {
            "x_min": value.get("x_min"),
            "y_min": value.get("y_min"),
            "x_max": value.get("x_max"),
            "y_max": value.get("y_max"),
        }
    raise ToolModelError("invalid_bbox", "bbox must be a mapping or four-coordinate list")


def _element(raw_element: dict[str, Any]) -> ElementEvidence:
    return ElementEvidence(
        element_id=_text(raw_element.get("id"), "id"),
        element_type=_text(raw_element.get("element_type"), "element_type"),
        source_label=_text(raw_element.get("source_label"), "source_label"),
        bbox=_bbox(raw_element.get("bbox")),
        normalized_bbox=_bbox(raw_element.get("normalized_bbox")),
    )


def _bbox(value: Any) -> BBox:
    if not isinstance(value, dict):
        raise ToolModelError("invalid_bbox", "bbox must be a mapping")
    return BBox(value.get("x_min"), value.get("y_min"), value.get("x_max"), value.get("y_max"))


def _image_size(raw_page: dict[str, Any]) -> tuple[int, int] | None:
    width = raw_page.get("image_width")
    height = raw_page.get("image_height")
    if width is None and height is None:
        return None
    return (width, height)


def _text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolModelError("missing_required_field", f"{field_name} must be a non-empty string")
    return value


__all__ = ("Neo4jPageSourceFactReader", "SourceFactQuery")
