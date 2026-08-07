"""Map normalized page elements to fixed graph nodes and page relations."""

from __future__ import annotations

from dataclasses import dataclass

from drawing_graph.models import ElementRecord, GraphNode, GraphRelation


@dataclass(frozen=True)
class ElementMapping:
    """Fixed graph label and owning-page relationship for an annotation label."""

    graph_label: str
    relation_type: str
    queryable: bool = True
    ignore_reason: str | None = None


class MappingError(ValueError):
    """Raised when an element cannot be mapped through the fixed whitelist."""

    def __init__(self, category: str, message: str):
        self.category = category
        super().__init__(message)


ELEMENT_MAPPINGS: dict[str, ElementMapping] = {
    "block": ElementMapping("DrawingBlock", "HAS_BLOCK"),
    "table": ElementMapping("Table", "HAS_TABLE"),
    "table caption": ElementMapping("TableCaption", "HAS_ELEMENT"),
    "block caption": ElementMapping("BlockCaption", "HAS_ELEMENT"),
    "cross section": ElementMapping("CrossSection", "HAS_ELEMENT"),
    "drawing basic info": ElementMapping("DrawingBasicInfo", "HAS_BASIC_INFO"),
    "drawing annotation": ElementMapping("DrawingAnnotation", "HAS_ANNOTATION"),
    "plain text": ElementMapping("PlainText", "HAS_TEXT"),
    "title": ElementMapping("Title", "HAS_TEXT"),
    "abandon": ElementMapping("IgnoredElement", "HAS_ELEMENT", queryable=False, ignore_reason="abandon"),
}


def map_element(element_record: ElementRecord) -> tuple[GraphNode, GraphRelation]:
    """Map a normalized element into one graph node and its page containment relation."""

    if not isinstance(element_record, ElementRecord):
        raise MappingError("invalid_element_record", "element_record must be an ElementRecord")

    mapping = ELEMENT_MAPPINGS.get(element_record.label)
    if mapping is None:
        raise MappingError("unknown_element_label", f"unsupported element label: {element_record.label}")

    properties = _element_properties(element_record, mapping)
    node = GraphNode(
        id=element_record.id,
        labels=(mapping.graph_label,),
        properties=properties,
    )
    relation = GraphRelation(
        start_id=element_record.page_id,
        end_id=element_record.id,
        relation_type=mapping.relation_type,
        properties={},
    )

    return node, relation


def _element_properties(element_record: ElementRecord, mapping: ElementMapping) -> dict[str, object]:
    properties: dict[str, object] = {
        "id": element_record.id,
        "label": element_record.label,
        "confidence": element_record.confidence,
        "shape_type": element_record.shape_type,
        "bbox": _bbox_property(element_record.bbox),
        "normalized_bbox": _bbox_property(element_record.normalized_bbox),
        "source_label": element_record.source_label,
        "original_points": _points_property(element_record.original_points),
        "citation_ref": element_record.citation_ref,
        "queryable": mapping.queryable,
    }
    if mapping.ignore_reason is not None:
        properties["ignore_reason"] = mapping.ignore_reason
    return properties


def _bbox_property(bbox) -> list[float]:
    return [bbox.x_min, bbox.y_min, bbox.x_max, bbox.y_max]


def _points_property(points: tuple[tuple[float, float], ...]) -> list[float]:
    return [coordinate for point in points for coordinate in point]


__all__ = (
    "ELEMENT_MAPPINGS",
    "ElementMapping",
    "MappingError",
    "map_element",
)
