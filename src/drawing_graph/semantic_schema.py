"""Static Neo4j schema specification for the semantic evidence layer.

``RecognitionRun`` is intentionally absent: run logs live outside the core
graph, so no node constraint or index for that label may be created.
"""

from __future__ import annotations


SEMANTIC_NODE_LABELS = frozenset(
    (
        "TextObservation",
        "BlockInterpretation",
        "BasicInfoInterpretation",
        "TableInterpretation",
    )
)

SEMANTIC_RELATION_TYPES = frozenset(
    (
        "HAS_OBSERVATION",
        "HAS_INTERPRETATION",
        "SUPPORTED_BY",
        "CANDIDATE_MATCHES_SECTION_CAPTION",
        "MATCHES_SECTION_CAPTION",
    )
)

OBSERVATION_SOURCE_LABELS = frozenset(
    (
        "DrawingBlock",
        "DrawingBasicInfo",
        "Table",
        "BlockCaption",
        "TableCaption",
        "CrossSection",
        "DrawingAnnotation",
        "PlainText",
        "Title",
    )
)

INTERPRETATION_SOURCE_LABELS = frozenset(("DrawingBlock", "DrawingBasicInfo", "Table"))

_SNAKE_CASE_LABELS = {
    "TextObservation": "text_observation",
    "BlockInterpretation": "block_interpretation",
    "BasicInfoInterpretation": "basic_info_interpretation",
    "TableInterpretation": "table_interpretation",
}

SEMANTIC_UNIQUE_CONSTRAINTS = tuple(
    (f"{_SNAKE_CASE_LABELS[label]}_id_unique", label)
    for label in SEMANTIC_NODE_LABELS
)

SEMANTIC_INDEXES = tuple(
    (f"{_SNAKE_CASE_LABELS[label]}_{property_name}_index", label, property_name)
    for label, property_names in (
        (
            "TextObservation",
            ("page_id", "target_element_id", "recognition_run_id", "status", "cache_key"),
        ),
        (
            "BlockInterpretation",
            ("block_id", "recognition_run_id", "status", "cache_key"),
        ),
        (
            "BasicInfoInterpretation",
            ("basic_info_id", "recognition_run_id", "status"),
        ),
        (
            "TableInterpretation",
            ("table_id", "recognition_run_id", "status"),
        ),
    )
    for property_name in property_names
)


__all__ = (
    "INTERPRETATION_SOURCE_LABELS",
    "OBSERVATION_SOURCE_LABELS",
    "SEMANTIC_INDEXES",
    "SEMANTIC_NODE_LABELS",
    "SEMANTIC_RELATION_TYPES",
    "SEMANTIC_UNIQUE_CONSTRAINTS",
)
