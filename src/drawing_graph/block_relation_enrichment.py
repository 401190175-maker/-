"""Data contracts for offline block-level relation enrichment."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal, Mapping

from drawing_graph.caption_matching import CaptionMatchingError, TableCaptionMatchInput, match_table_caption_inputs
from drawing_graph.models import BBox, ModelError


RelationIssueSeverity = Literal["warning", "error"]
BasicInfoContextStatus = Literal["confirmed", "partial", "ambiguous", "not_evaluated"]
BasicInfoContextSource = Literal["current_page", "group_start", "group_end", "unavailable"]
SpatialCandidateRelationSpec = Literal["candidate_caption_of", "candidate_section_mark"]
BLOCK_CAPTION_LINK_RULE = "block_caption_center_direction_v1"
CURRENT_PAGE_BASIC_INFO_LINK_RULE = "basic_info_current_page_v1"
PREVIOUS_PAGE_BASIC_INFO_LINK_RULE = "basic_info_previous_page_v1"
ANNOTATION_SAME_PAGE_LINK_RULE = "annotation_same_page_shared_v1"
CROSS_SECTION_GEOMETRY_OWNERSHIP_LINK_RULE = "cross_section_geometry_ownership_v1"
TABLE_CAPTION_BBOX_DISTANCE_LINK_RULE = "table_caption_bbox_distance_v1"
CROSS_SECTION_MIN_OVERLAP_RATIO = 0.5
CROSS_SECTION_AMBIGUOUS_RATIO_DELTA = 0.05
BLOCK_CAPTION_AMBIGUOUS_DISTANCE_DELTA = 5.0


@dataclass(frozen=True)
class EnrichmentScope:
    """Input range and audit identity for one relation-enrichment run."""

    project_id: str
    relation_batch_id: str
    rule_version: str
    drawing_set_id: str | None = None
    page_id: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.project_id, "project_id")
        _require_text(self.relation_batch_id, "relation_batch_id")
        _require_text(self.rule_version, "rule_version")
        _require_optional_text(self.drawing_set_id, "drawing_set_id")
        _require_optional_text(self.page_id, "page_id")


@dataclass(frozen=True)
class PageElementSnapshot:
    """Immutable page-element evidence read from the existing page graph."""

    id: str
    page_id: str
    bbox: BBox
    properties: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.id, "id")
        _require_text(self.page_id, "page_id")
        if not isinstance(self.bbox, BBox):
            raise ModelError("invalid_bbox", "bbox must be a BBox")
        if not isinstance(self.properties, Mapping):
            raise ModelError("invalid_properties", "properties must be a mapping")
        object.__setattr__(self, "properties", MappingProxyType(dict(self.properties)))


@dataclass(frozen=True)
class PageRelationSnapshot:
    """Immutable single-page input for block-level relation enrichment."""

    page_id: str
    drawing_set_id: str
    page_number: int
    blocks: tuple[PageElementSnapshot, ...] = ()
    captions: tuple[PageElementSnapshot, ...] = ()
    tables: tuple[PageElementSnapshot, ...] = ()
    table_captions: tuple[PageElementSnapshot, ...] = ()
    basic_infos: tuple[PageElementSnapshot, ...] = ()
    annotations: tuple[PageElementSnapshot, ...] = ()
    cross_sections: tuple[PageElementSnapshot, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.page_id, "page_id")
        _require_text(self.drawing_set_id, "drawing_set_id")
        _require_positive_int(self.page_number, "page_number")
        object.__setattr__(self, "blocks", _read_snapshot_tuple(self.blocks, "blocks"))
        object.__setattr__(self, "captions", _read_snapshot_tuple(self.captions, "captions"))
        object.__setattr__(self, "tables", _read_snapshot_tuple(self.tables, "tables"))
        object.__setattr__(self, "table_captions", _read_snapshot_tuple(self.table_captions, "table_captions"))
        object.__setattr__(self, "basic_infos", _read_snapshot_tuple(self.basic_infos, "basic_infos"))
        object.__setattr__(self, "annotations", _read_snapshot_tuple(self.annotations, "annotations"))
        object.__setattr__(self, "cross_sections", _read_snapshot_tuple(self.cross_sections, "cross_sections"))


@dataclass(frozen=True)
class RelationCandidate:
    """Candidate relationship from a DrawingBlock to an enriched element."""

    start_id: str
    end_id: str
    relation_spec: str
    relation_type: str
    relation_batch_id: str
    rule_version: str
    link_rule: str
    properties: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.start_id, "start_id")
        _require_text(self.end_id, "end_id")
        _require_text(self.relation_spec, "relation_spec")
        _require_text(self.relation_type, "relation_type")
        _require_text(self.relation_batch_id, "relation_batch_id")
        _require_text(self.rule_version, "rule_version")
        _require_text(self.link_rule, "link_rule")
        if not isinstance(self.properties, Mapping):
            raise ModelError("invalid_properties", "properties must be a mapping")
        relation_properties = dict(self.properties)
        relation_properties["relation_batch_id"] = self.relation_batch_id
        relation_properties["rule_version"] = self.rule_version
        relation_properties["link_rule"] = self.link_rule
        object.__setattr__(self, "properties", MappingProxyType(relation_properties))


@dataclass(frozen=True)
class BasicInfoContextResult:
    """Page-level DrawingBasicInfo context decision for USES_BASIC_INFO."""

    page_id: str
    status: BasicInfoContextStatus
    source: BasicInfoContextSource
    source_page_id: str | None = None
    group_id: str | None = None
    basic_info_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.page_id, "page_id")
        if self.status not in ("confirmed", "partial", "ambiguous", "not_evaluated"):
            raise ModelError("invalid_basic_info_status", "status must be a supported basic-info context status")
        if self.source not in ("current_page", "group_start", "group_end", "unavailable"):
            raise ModelError("invalid_basic_info_source", "source must be a supported basic-info context source")
        _require_optional_text(self.source_page_id, "source_page_id")
        _require_optional_text(self.group_id, "group_id")
        object.__setattr__(self, "basic_info_ids", _read_text_tuple(self.basic_info_ids, "basic_info_ids"))


@dataclass(frozen=True)
class SpatialCandidateGroup:
    """Complete spatial candidate set for one ambiguous caption or section mark."""

    group_key: str
    relation_spec: SpatialCandidateRelationSpec
    source_element_id: str
    candidates: tuple[Mapping[str, Any], ...]
    candidate_count: int
    conflict_reason: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.group_key, "group_key")
        if self.relation_spec not in ("candidate_caption_of", "candidate_section_mark"):
            raise ModelError("invalid_candidate_relation_spec", "relation_spec must be a supported candidate spec")
        _require_text(self.source_element_id, "source_element_id")
        _require_non_negative_int(self.candidate_count, "candidate_count")
        _require_optional_text(self.conflict_reason, "conflict_reason")
        candidates = _read_spatial_candidate_tuple(self.candidates, "candidates")
        if len(candidates) != self.candidate_count:
            raise ModelError("candidate_count_mismatch", "candidate_count must match candidates length")
        object.__setattr__(self, "candidates", candidates)


@dataclass(frozen=True)
class EnrichmentIssue:
    """Classified warning or error produced during relation enrichment."""

    category: str
    message: str
    severity: RelationIssueSeverity
    page_id: str | None = None
    element_id: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.category, "category")
        _require_text(self.message, "message")
        if self.severity not in ("warning", "error"):
            raise ModelError("invalid_issue_severity", "severity must be warning or error")
        _require_optional_text(self.page_id, "page_id")
        _require_optional_text(self.element_id, "element_id")


@dataclass(frozen=True)
class EnrichmentStats:
    """Aggregate counters for one relation-enrichment result."""

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

    def __post_init__(self) -> None:
        for field_name in (
            "page_count",
            "block_count",
            "caption_count",
            "basic_info_count",
            "annotation_count",
            "cross_section_count",
            "table_count",
            "table_caption_count",
            "table_caption_relation_count",
            "uses_basic_info_count",
            "candidate_count",
            "ambiguous_count",
            "not_evaluated_count",
            "reviewing_count",
            "accepted_count",
            "rejected_count",
            "unresolved_count",
            "relation_count",
            "warning_count",
            "error_count",
        ):
            _require_non_negative_int(getattr(self, field_name), field_name)


@dataclass(frozen=True)
class EnrichmentResult:
    """Candidate relations, classified issues, and counters for a scope."""

    scope: EnrichmentScope
    relations: tuple[RelationCandidate, ...] = ()
    issues: tuple[EnrichmentIssue, ...] = ()
    stats: EnrichmentStats | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.scope, EnrichmentScope):
            raise ModelError("invalid_scope", "scope must be an EnrichmentScope")
        relations = _read_relation_tuple(self.relations, "relations")
        issues = _read_issue_tuple(self.issues, "issues")
        object.__setattr__(self, "relations", relations)
        object.__setattr__(self, "issues", issues)
        if self.stats is None:
            object.__setattr__(
                self,
                "stats",
                EnrichmentStats(
                    relation_count=len(relations),
                    warning_count=sum(1 for issue in issues if issue.severity == "warning"),
                    error_count=sum(1 for issue in issues if issue.severity == "error"),
                ),
            )
        elif not isinstance(self.stats, EnrichmentStats):
            raise ModelError("invalid_stats", "stats must be an EnrichmentStats")


def enrich_block_captions(scope: EnrichmentScope, page: PageRelationSnapshot) -> EnrichmentResult:
    """Match same-page BlockCaption snapshots to DrawingBlock snapshots."""

    if not isinstance(scope, EnrichmentScope):
        raise ModelError("invalid_scope", "scope must be an EnrichmentScope")
    if not isinstance(page, PageRelationSnapshot):
        raise ModelError("invalid_page_snapshot", "page must be a PageRelationSnapshot")

    blocks = _dedupe_elements_by_id(tuple(block for block in page.blocks if block.page_id == page.page_id))
    captions = _dedupe_elements_by_id(tuple(caption for caption in page.captions if caption.page_id == page.page_id))
    draft_matches: list[_CaptionMatch] = []
    candidate_relations: list[RelationCandidate] = []
    issues: list[EnrichmentIssue] = []

    for caption in captions:
        candidates = _select_block_caption_candidates(caption, blocks)
        if not candidates:
            issues.append(
                EnrichmentIssue(
                    category="caption_candidate_not_found",
                    message="block caption did not match any same-page drawing block",
                    severity="warning",
                    page_id=page.page_id,
                    element_id=caption.id,
                )
            )
        elif _caption_candidates_are_ambiguous(candidates):
            candidate_relations.extend(
                _make_caption_candidate_relation(
                    scope,
                    match,
                    candidate_count=len(candidates),
                    conflict_reason="distance_too_close",
                )
                for match in candidates
            )
            issues.append(
                EnrichmentIssue(
                    category="caption_candidate_ambiguous",
                    message="block caption has multiple spatial candidates with close evidence",
                    severity="warning",
                    page_id=page.page_id,
                    element_id=caption.id,
                )
            )
        else:
            draft_matches.append(candidates[0])

    accepted_matches: dict[str, _CaptionMatch] = {}
    conflicting_matches: dict[str, list[_CaptionMatch]] = {}
    for match in draft_matches:
        previous = accepted_matches.get(match.block.id)
        if previous is None:
            accepted_matches[match.block.id] = match
            continue
        conflicting_matches.setdefault(match.block.id, [previous]).append(match)

    for block_id, matches in conflicting_matches.items():
        accepted_matches.pop(block_id, None)
        candidate_relations.extend(
            _make_caption_candidate_relation(
                scope,
                match,
                candidate_count=len(matches),
                conflict_reason="caption_conflict",
            )
            for match in matches
        )
        issues.append(
            EnrichmentIssue(
                category="caption_candidate_ambiguous",
                message="multiple block captions matched the same drawing block",
                severity="warning",
                page_id=page.page_id,
                element_id=block_id,
            )
        )

    formal_relations = [
        RelationCandidate(
            start_id=match.block.id,
            end_id=match.caption.id,
            relation_spec="block_caption",
            relation_type="HAS_CAPTION",
            relation_batch_id=scope.relation_batch_id,
            rule_version=scope.rule_version,
            link_rule=BLOCK_CAPTION_LINK_RULE,
            properties={
                "distance": match.distance,
                "match_direction": match.direction,
            },
        )
        for match in sorted(accepted_matches.values(), key=lambda item: (item.block.id, item.caption.id))
    ]
    relations = formal_relations + sorted(candidate_relations, key=lambda item: (item.start_id, item.end_id))

    return EnrichmentResult(
        scope=scope,
        relations=relations,
        issues=issues,
        stats=EnrichmentStats(
            page_count=1,
            block_count=len(blocks),
            caption_count=len(captions),
            relation_count=len(relations),
            candidate_count=len(candidate_relations),
            ambiguous_count=sum(1 for issue in issues if issue.category == "caption_candidate_ambiguous"),
            warning_count=sum(1 for issue in issues if issue.severity == "warning"),
            error_count=sum(1 for issue in issues if issue.severity == "error"),
        ),
    )


def enrich_current_page_basic_infos(scope: EnrichmentScope, page: PageRelationSnapshot) -> EnrichmentResult:
    """Link a page with blocks to its current-page DrawingBasicInfo context."""

    if not isinstance(scope, EnrichmentScope):
        raise ModelError("invalid_scope", "scope must be an EnrichmentScope")
    if not isinstance(page, PageRelationSnapshot):
        raise ModelError("invalid_page_snapshot", "page must be a PageRelationSnapshot")

    blocks = tuple(block for block in page.blocks if block.page_id == page.page_id)
    basic_infos = tuple(basic_info for basic_info in page.basic_infos if basic_info.page_id == page.page_id)
    relations = [
        RelationCandidate(
            start_id=page.page_id,
            end_id=basic_info.id,
            relation_spec="page_uses_basic_info",
            relation_type="USES_BASIC_INFO",
            relation_batch_id=scope.relation_batch_id,
            rule_version=scope.rule_version,
            link_rule=CURRENT_PAGE_BASIC_INFO_LINK_RULE,
            properties={
                "status": "confirmed",
                "source": "current_page",
                "source_page_id": page.page_id,
                "group_id": page.drawing_set_id,
                "evidence_page_ids": [page.page_id],
            },
        )
        for basic_info in sorted(basic_infos, key=lambda item: item.id)
    ]
    if not blocks:
        relations = []

    return EnrichmentResult(
        scope=scope,
        relations=relations,
        issues=(),
        stats=EnrichmentStats(
            page_count=1,
            block_count=len(blocks),
            basic_info_count=len(basic_infos),
            uses_basic_info_count=len(relations),
            relation_count=len(relations),
        ),
    )


def enrich_previous_page_basic_infos(
    scope: EnrichmentScope,
    page: PageRelationSnapshot,
    previous_page: PageRelationSnapshot | None,
    *,
    previous_page_context_available: bool = True,
) -> EnrichmentResult:
    """Evaluate missing current-page basic-info context without creating block-level facts."""

    if not isinstance(scope, EnrichmentScope):
        raise ModelError("invalid_scope", "scope must be an EnrichmentScope")
    if not isinstance(page, PageRelationSnapshot):
        raise ModelError("invalid_page_snapshot", "page must be a PageRelationSnapshot")
    if previous_page is not None and not isinstance(previous_page, PageRelationSnapshot):
        raise ModelError("invalid_page_snapshot", "previous_page must be a PageRelationSnapshot or None")
    if not isinstance(previous_page_context_available, bool):
        raise ModelError("invalid_context_flag", "previous_page_context_available must be a boolean")

    blocks = tuple(block for block in page.blocks if block.page_id == page.page_id)
    current_basic_infos = tuple(basic_info for basic_info in page.basic_infos if basic_info.page_id == page.page_id)
    if current_basic_infos or not blocks:
        return _basic_info_previous_result(
            scope=scope,
            page=page,
            blocks=blocks,
            basic_infos=current_basic_infos,
            relations=(),
            issues=(),
        )

    if previous_page is None:
        return _basic_info_previous_result(
            scope=scope,
            page=page,
            blocks=blocks,
            basic_infos=(),
            relations=(),
            issues=(_make_basic_info_issue("basic_info_not_evaluated", page),),
        )

    if not _is_immediate_previous_page(page, previous_page):
        return _basic_info_previous_result(
            scope=scope,
            page=page,
            blocks=blocks,
            basic_infos=(),
            relations=(),
            issues=(_make_basic_info_issue("basic_info_not_evaluated", page),),
        )

    previous_basic_infos = tuple(
        basic_info for basic_info in previous_page.basic_infos if basic_info.page_id == previous_page.page_id
    )
    if not previous_basic_infos:
        return _basic_info_previous_result(
            scope=scope,
            page=page,
            blocks=blocks,
            basic_infos=(),
            relations=(),
            issues=(_make_basic_info_issue("basic_info_not_evaluated", page),),
        )

    if _has_basic_info_anchor_conflict(previous_basic_infos):
        return _basic_info_previous_result(
            scope=scope,
            page=page,
            blocks=blocks,
            basic_infos=previous_basic_infos,
            relations=(),
            issues=(_make_basic_info_issue("basic_info_ambiguous", page),),
        )

    return _basic_info_previous_result(
        scope=scope,
        page=page,
        blocks=blocks,
        basic_infos=previous_basic_infos,
        relations=(),
        issues=(_make_basic_info_issue("basic_info_partial", page),),
    )


def enrich_page_annotations(scope: EnrichmentScope, page: PageRelationSnapshot) -> EnrichmentResult:
    """Link every same-page DrawingBlock to every same-page DrawingAnnotation."""

    if not isinstance(scope, EnrichmentScope):
        raise ModelError("invalid_scope", "scope must be an EnrichmentScope")
    if not isinstance(page, PageRelationSnapshot):
        raise ModelError("invalid_page_snapshot", "page must be a PageRelationSnapshot")

    blocks = tuple(block for block in page.blocks if block.page_id == page.page_id)
    annotations = tuple(annotation for annotation in page.annotations if annotation.page_id == page.page_id)
    relations = [
        RelationCandidate(
            start_id=block.id,
            end_id=annotation.id,
            relation_spec="block_annotation",
            relation_type="HAS_ANNOTATION",
            relation_batch_id=scope.relation_batch_id,
            rule_version=scope.rule_version,
            link_rule=ANNOTATION_SAME_PAGE_LINK_RULE,
            properties={"match_direction": "same_page_shared"},
        )
        for block in sorted(blocks, key=lambda item: item.id)
        for annotation in sorted(annotations, key=lambda item: item.id)
    ]

    return EnrichmentResult(
        scope=scope,
        relations=relations,
        issues=(),
        stats=EnrichmentStats(
            page_count=1,
            block_count=len(blocks),
            annotation_count=len(annotations),
            relation_count=len(relations),
        ),
    )


def enrich_cross_sections(scope: EnrichmentScope, page: PageRelationSnapshot) -> EnrichmentResult:
    """Link contained same-page CrossSection snapshots to DrawingBlock snapshots."""

    if not isinstance(scope, EnrichmentScope):
        raise ModelError("invalid_scope", "scope must be an EnrichmentScope")
    if not isinstance(page, PageRelationSnapshot):
        raise ModelError("invalid_page_snapshot", "page must be a PageRelationSnapshot")

    blocks = tuple(sorted(_same_page_elements(page.blocks, page.page_id), key=lambda item: item.id))
    cross_sections = tuple(sorted(_same_page_elements(page.cross_sections, page.page_id), key=lambda item: item.id))
    relations: list[RelationCandidate] = []
    issues: list[EnrichmentIssue] = []

    for cross_section in cross_sections:
        cross_section_area = _bbox_area(cross_section.bbox)
        containing_blocks = tuple(
            block for block in blocks if _bbox_contains(block.bbox, cross_section.bbox)
        )
        selected_block = None
        containment_status = "contained"
        if containing_blocks:
            containing_candidates = tuple(
                sorted(
                    ((block, _bbox_area(block.bbox)) for block in containing_blocks),
                    key=lambda candidate: (candidate[1], candidate[0].id),
                )
            )
            smallest_area = containing_candidates[0][1]
            smallest_candidates = tuple(candidate for candidate in containing_candidates if candidate[1] == smallest_area)
            if len(smallest_candidates) > 1:
                relations.extend(
                    _make_section_candidate_relation(
                        scope,
                        block,
                        cross_section,
                        candidate_count=len(smallest_candidates),
                        overlap_area=_bbox_overlap_area(block.bbox, cross_section.bbox),
                        overlap_ratio=1.0,
                        containment_status="contained",
                        score=1 / (1 + area),
                        conflict_reason="multiple_containing_blocks",
                    )
                    for block, area in smallest_candidates
                )
                issues.append(
                    EnrichmentIssue(
                        category="section_candidate_ambiguous",
                        message="multiple containing drawing blocks have the same smallest bbox area",
                        severity="warning",
                        page_id=page.page_id,
                        element_id=cross_section.id,
                    )
                )
                continue
            selected_block = containing_candidates[0][0]
            overlap_area = _bbox_overlap_area(selected_block.bbox, cross_section.bbox)
            overlap_ratio = overlap_area / cross_section_area
        else:
            overlap_candidates = tuple(
                (
                    block,
                    _bbox_overlap_area(block.bbox, cross_section.bbox),
                    _bbox_overlap_area(block.bbox, cross_section.bbox) / cross_section_area,
                )
                for block in blocks
            )
            overlap_candidates = tuple(candidate for candidate in overlap_candidates if candidate[1] > 0)
            if not overlap_candidates:
                continue
            overlap_candidates = tuple(
                sorted(overlap_candidates, key=lambda candidate: (-candidate[1], candidate[0].id))
            )
            selected_block, overlap_area, overlap_ratio = overlap_candidates[0]
            if overlap_ratio < CROSS_SECTION_MIN_OVERLAP_RATIO:
                issues.append(
                    EnrichmentIssue(
                        category="section_candidate_low_evidence",
                        message="cross section overlap ratio is below the accepted geometry ownership threshold",
                        severity="warning",
                        page_id=page.page_id,
                        element_id=cross_section.id,
                    )
                )
                continue
            if len(overlap_candidates) > 1:
                next_overlap_area = overlap_candidates[1][1]
                next_overlap_ratio = overlap_candidates[1][2]
                if (
                    overlap_area == next_overlap_area
                    or overlap_ratio - next_overlap_ratio < CROSS_SECTION_AMBIGUOUS_RATIO_DELTA
                ):
                    ambiguous_candidates = tuple(
                        candidate
                        for candidate in overlap_candidates
                        if candidate[2] >= CROSS_SECTION_MIN_OVERLAP_RATIO
                        and overlap_ratio - candidate[2] < CROSS_SECTION_AMBIGUOUS_RATIO_DELTA
                    )
                    relations.extend(
                        _make_section_candidate_relation(
                            scope,
                            block,
                            cross_section,
                            candidate_count=len(ambiguous_candidates),
                            overlap_area=candidate_overlap_area,
                            overlap_ratio=candidate_overlap_ratio,
                            containment_status="overlapped",
                            score=candidate_overlap_ratio,
                            conflict_reason="overlap_evidence_too_close",
                        )
                        for block, candidate_overlap_area, candidate_overlap_ratio in ambiguous_candidates
                    )
                    issues.append(
                        EnrichmentIssue(
                            category="section_candidate_ambiguous",
                            message="overlapping drawing block candidates are too close to choose a stable owner",
                            severity="warning",
                            page_id=page.page_id,
                            element_id=cross_section.id,
                        )
                    )
                    continue
            containment_status = "overlapped"
        relations.append(
            RelationCandidate(
                start_id=selected_block.id,
                end_id=cross_section.id,
                relation_spec="block_section_mark",
                relation_type="HAS_SECTION_MARK",
                relation_batch_id=scope.relation_batch_id,
                rule_version=scope.rule_version,
                link_rule=CROSS_SECTION_GEOMETRY_OWNERSHIP_LINK_RULE,
                properties={
                    "overlap_area": overlap_area,
                    "overlap_ratio": overlap_ratio,
                    "containment_status": containment_status,
                },
            )
        )

    return EnrichmentResult(
        scope=scope,
        relations=relations,
        issues=issues,
        stats=EnrichmentStats(
            page_count=1,
            block_count=len(blocks),
            cross_section_count=len(cross_sections),
            relation_count=len(relations),
            candidate_count=sum(1 for relation in relations if relation.relation_spec == "candidate_section_mark"),
            ambiguous_count=sum(1 for issue in issues if issue.category == "section_candidate_ambiguous"),
            warning_count=sum(1 for issue in issues if issue.severity == "warning"),
            error_count=sum(1 for issue in issues if issue.severity == "error"),
        ),
    )


def enrich_table_captions(scope: EnrichmentScope, page: PageRelationSnapshot) -> EnrichmentResult:
    """Match same-page TableCaption snapshots to Table snapshots."""

    if not isinstance(scope, EnrichmentScope):
        raise ModelError("invalid_scope", "scope must be an EnrichmentScope")
    if not isinstance(page, PageRelationSnapshot):
        raise ModelError("invalid_page_snapshot", "page must be a PageRelationSnapshot")

    tables = tuple(sorted(_same_page_elements(page.tables, page.page_id), key=lambda item: item.id))
    table_captions = tuple(sorted(_same_page_elements(page.table_captions, page.page_id), key=lambda item: item.id))
    issues: list[EnrichmentIssue] = []
    relations: list[RelationCandidate] = []

    if table_captions and not tables:
        issues.append(
            EnrichmentIssue(
                category="table_caption_missing_table",
                message="table caption did not match any same-page table because the page has no table",
                severity="warning",
                page_id=page.page_id,
            )
        )
    else:
        try:
            matches = match_table_caption_inputs(
                tables=[TableCaptionMatchInput(id=table.id, bbox=table.bbox) for table in tables],
                captions=[
                    TableCaptionMatchInput(id=table_caption.id, bbox=table_caption.bbox)
                    for table_caption in table_captions
                ],
            )
        except CaptionMatchingError as error:
            issues.append(
                EnrichmentIssue(
                    category="table_caption_invalid_input",
                    message=str(error),
                    severity="error",
                    page_id=page.page_id,
                )
            )
            matches = []

        relations = [
            RelationCandidate(
                start_id=match.table_id,
                end_id=match.table_caption_id,
                relation_spec="table_caption",
                relation_type="HAS_CAPTION",
                relation_batch_id=scope.relation_batch_id,
                rule_version=scope.rule_version,
                link_rule=TABLE_CAPTION_BBOX_DISTANCE_LINK_RULE,
                properties={"distance": match.distance},
            )
            for match in matches
        ]

    return EnrichmentResult(
        scope=scope,
        relations=relations,
        issues=issues,
        stats=EnrichmentStats(
            page_count=1,
            table_count=len(tables),
            table_caption_count=len(table_captions),
            table_caption_relation_count=len(relations),
            relation_count=len(relations),
            warning_count=sum(1 for issue in issues if issue.severity == "warning"),
            error_count=sum(1 for issue in issues if issue.severity == "error"),
        ),
    )


def enrich_page_relations(
    scope: EnrichmentScope,
    page: PageRelationSnapshot,
    previous_page: PageRelationSnapshot | None = None,
    *,
    previous_page_context_available: bool = True,
) -> EnrichmentResult:
    """Combine the caption, basic-info, and annotation rules for one page."""

    if not isinstance(scope, EnrichmentScope):
        raise ModelError("invalid_scope", "scope must be an EnrichmentScope")
    if not isinstance(page, PageRelationSnapshot):
        raise ModelError("invalid_page_snapshot", "page must be a PageRelationSnapshot")
    if previous_page is not None and not isinstance(previous_page, PageRelationSnapshot):
        raise ModelError("invalid_page_snapshot", "previous_page must be a PageRelationSnapshot or None")
    if not isinstance(previous_page_context_available, bool):
        raise ModelError("invalid_context_flag", "previous_page_context_available must be a boolean")

    blocks = _same_page_elements(page.blocks, page.page_id)
    captions = _same_page_elements(page.captions, page.page_id)
    current_basic_infos = _same_page_elements(page.basic_infos, page.page_id)
    annotations = _same_page_elements(page.annotations, page.page_id)
    cross_sections = _same_page_elements(page.cross_sections, page.page_id)
    component_results: list[EnrichmentResult] = [enrich_table_captions(scope, page)]
    if blocks:
        component_results.extend(
            (
                enrich_block_captions(scope, page),
                enrich_current_page_basic_infos(scope, page),
                enrich_previous_page_basic_infos(
                    scope,
                    page,
                    previous_page,
                    previous_page_context_available=previous_page_context_available,
                ),
                enrich_page_annotations(scope, page),
                enrich_cross_sections(scope, page),
            )
        )
    relations = _dedupe_relations(
        relation
        for result in component_results
        for relation in result.relations
    )
    issues = tuple(
        issue
        for result in component_results
        for issue in result.issues
    )
    basic_info_count = (
        max(result.stats.basic_info_count for result in component_results)
        if blocks
        else len(current_basic_infos)
    )
    table_result = component_results[0]

    return EnrichmentResult(
        scope=scope,
        relations=relations,
        issues=issues,
        stats=EnrichmentStats(
            page_count=1,
            block_count=len(blocks),
            caption_count=len(captions),
            basic_info_count=basic_info_count,
            annotation_count=len(annotations),
            cross_section_count=len(cross_sections),
            table_count=table_result.stats.table_count,
            table_caption_count=table_result.stats.table_caption_count,
            table_caption_relation_count=table_result.stats.table_caption_relation_count,
            relation_count=len(relations),
            uses_basic_info_count=sum(result.stats.uses_basic_info_count for result in component_results),
            candidate_count=sum(result.stats.candidate_count for result in component_results),
            ambiguous_count=sum(result.stats.ambiguous_count for result in component_results),
            not_evaluated_count=sum(result.stats.not_evaluated_count for result in component_results),
            reviewing_count=sum(result.stats.reviewing_count for result in component_results),
            accepted_count=sum(result.stats.accepted_count for result in component_results),
            rejected_count=sum(result.stats.rejected_count for result in component_results),
            unresolved_count=sum(result.stats.unresolved_count for result in component_results),
            warning_count=sum(1 for issue in issues if issue.severity == "warning"),
            error_count=sum(1 for issue in issues if issue.severity == "error"),
        ),
    )


def _basic_info_previous_result(
    *,
    scope: EnrichmentScope,
    page: PageRelationSnapshot,
    blocks: tuple[PageElementSnapshot, ...],
    basic_infos: tuple[PageElementSnapshot, ...],
    relations: tuple[RelationCandidate, ...] | list[RelationCandidate],
    issues: tuple[EnrichmentIssue, ...],
) -> EnrichmentResult:
    not_evaluated_count = sum(
        1 for issue in issues if issue.category in {"basic_info_not_evaluated", "basic_info_partial"}
    )
    ambiguous_count = sum(1 for issue in issues if issue.category == "basic_info_ambiguous")
    return EnrichmentResult(
        scope=scope,
        relations=tuple(relations),
        issues=issues,
        stats=EnrichmentStats(
            page_count=1,
            block_count=len(blocks),
            basic_info_count=len(basic_infos),
            relation_count=len(relations),
            not_evaluated_count=not_evaluated_count,
            ambiguous_count=ambiguous_count,
            warning_count=sum(1 for issue in issues if issue.severity == "warning"),
            error_count=sum(1 for issue in issues if issue.severity == "error"),
        ),
    )


def _make_basic_info_issue(category: str, page: PageRelationSnapshot) -> EnrichmentIssue:
    return EnrichmentIssue(
        category=category,
        message="current page has no basic info available from the allowed previous-page context",
        severity="warning",
        page_id=page.page_id,
    )


def _is_immediate_previous_page(page: PageRelationSnapshot, previous_page: PageRelationSnapshot) -> bool:
    return (
        previous_page.drawing_set_id == page.drawing_set_id
        and previous_page.page_number == page.page_number - 1
    )


def _has_basic_info_anchor_conflict(basic_infos: tuple[PageElementSnapshot, ...]) -> bool:
    anchor_group_ids = {
        basic_info.properties.get("anchor_group_id")
        for basic_info in basic_infos
        if basic_info.properties.get("anchor_group_id")
    }
    return len(anchor_group_ids) > 1


@dataclass(frozen=True)
class _CaptionMatch:
    caption: PageElementSnapshot
    block: PageElementSnapshot
    distance: float
    direction: str


def _select_block_caption_match(
    caption: PageElementSnapshot,
    blocks: tuple[PageElementSnapshot, ...],
) -> _CaptionMatch | None:
    candidates = _select_block_caption_candidates(caption, blocks)
    if not candidates:
        return None
    return candidates[0]


def _select_block_caption_candidates(
    caption: PageElementSnapshot,
    blocks: tuple[PageElementSnapshot, ...],
) -> tuple[_CaptionMatch, ...]:
    matches = [_make_caption_match(caption, block) for block in blocks]
    below_matches = [match for match in matches if match.direction == "below"]
    above_matches = [match for match in matches if match.direction == "above"]
    candidates = below_matches or above_matches
    if not candidates:
        return ()
    return tuple(sorted(candidates, key=lambda match: (match.distance, match.block.id)))


def _caption_candidates_are_ambiguous(candidates: tuple[_CaptionMatch, ...]) -> bool:
    return (
        len(candidates) > 1
        and candidates[1].distance - candidates[0].distance <= BLOCK_CAPTION_AMBIGUOUS_DISTANCE_DELTA
    )


def _make_caption_candidate_relation(
    scope: EnrichmentScope,
    match: _CaptionMatch,
    *,
    candidate_count: int,
    conflict_reason: str,
) -> RelationCandidate:
    return RelationCandidate(
        start_id=match.caption.id,
        end_id=match.block.id,
        relation_spec="candidate_caption_of",
        relation_type="CANDIDATE_CAPTION_OF",
        relation_batch_id=scope.relation_batch_id,
        rule_version=scope.rule_version,
        link_rule=BLOCK_CAPTION_LINK_RULE,
        properties={
            "status": "candidate",
            "candidate_count": candidate_count,
            "score": 1 / (1 + match.distance),
            "distance": match.distance,
            "match_direction": match.direction,
            "conflict_reason": conflict_reason,
        },
    )


def _make_section_candidate_relation(
    scope: EnrichmentScope,
    block: PageElementSnapshot,
    cross_section: PageElementSnapshot,
    *,
    candidate_count: int,
    overlap_area: float,
    overlap_ratio: float,
    containment_status: str,
    score: float,
    conflict_reason: str,
) -> RelationCandidate:
    return RelationCandidate(
        start_id=block.id,
        end_id=cross_section.id,
        relation_spec="candidate_section_mark",
        relation_type="CANDIDATE_HAS_SECTION_MARK",
        relation_batch_id=scope.relation_batch_id,
        rule_version=scope.rule_version,
        link_rule=CROSS_SECTION_GEOMETRY_OWNERSHIP_LINK_RULE,
        properties={
            "status": "candidate",
            "candidate_count": candidate_count,
            "score": score,
            "overlap_area": overlap_area,
            "overlap_ratio": overlap_ratio,
            "containment_status": containment_status,
            "conflict_reason": conflict_reason,
        },
    )


def _make_caption_match(caption: PageElementSnapshot, block: PageElementSnapshot) -> _CaptionMatch:
    caption_center = _bbox_center(caption.bbox)
    block_center = _bbox_center(block.bbox)
    direction = "below" if block_center[1] > caption_center[1] else "above"
    return _CaptionMatch(
        caption=caption,
        block=block,
        distance=math.hypot(block_center[0] - caption_center[0], block_center[1] - caption_center[1]),
        direction=direction,
    )


def _bbox_center(bbox: BBox) -> tuple[float, float]:
    return ((bbox.x_min + bbox.x_max) / 2, (bbox.y_min + bbox.y_max) / 2)


def _bbox_area(bbox: BBox) -> float:
    return (bbox.x_max - bbox.x_min) * (bbox.y_max - bbox.y_min)


def _bbox_contains(container: BBox, contained: BBox) -> bool:
    return (
        container.x_min <= contained.x_min
        and container.y_min <= contained.y_min
        and container.x_max >= contained.x_max
        and container.y_max >= contained.y_max
    )


def _bbox_overlap_area(first: BBox, second: BBox) -> float:
    x_overlap = max(0.0, min(first.x_max, second.x_max) - max(first.x_min, second.x_min))
    y_overlap = max(0.0, min(first.y_max, second.y_max) - max(first.y_min, second.y_min))
    return x_overlap * y_overlap


def _choose_nearer_match(first: _CaptionMatch, second: _CaptionMatch) -> tuple[_CaptionMatch, _CaptionMatch]:
    if (second.distance, second.caption.id) < (first.distance, first.caption.id):
        return second, first
    return first, second


def _same_page_elements(
    elements: tuple[PageElementSnapshot, ...],
    page_id: str,
) -> tuple[PageElementSnapshot, ...]:
    return tuple(element for element in elements if element.page_id == page_id)


def _dedupe_elements_by_id(elements: tuple[PageElementSnapshot, ...]) -> tuple[PageElementSnapshot, ...]:
    unique: dict[str, PageElementSnapshot] = {}
    for element in elements:
        unique.setdefault(element.id, element)
    return tuple(unique[element_id] for element_id in sorted(unique))


def _dedupe_relations(relations: Any) -> tuple[RelationCandidate, ...]:
    unique_relations: dict[tuple[str, str, str, str, str], RelationCandidate] = {}
    for relation in relations:
        key = (
            relation.start_id,
            relation.end_id,
            relation.relation_spec,
            relation.relation_type,
            relation.rule_version,
            relation.link_rule,
        )
        unique_relations.setdefault(key, relation)
    return tuple(
        unique_relations[key]
        for key in sorted(unique_relations)
    )


def _require_text(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ModelError("missing_required_field", f"{field_name} must be a non-empty string")


def _require_optional_text(value: Any, field_name: str) -> None:
    if value is not None:
        _require_text(value, field_name)


def _require_positive_int(value: Any, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ModelError("invalid_page_number", f"{field_name} must be a positive integer")


def _require_non_negative_int(value: Any, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ModelError("invalid_count", f"{field_name} must be a non-negative integer")


def _read_snapshot_tuple(values: Any, field_name: str) -> tuple[PageElementSnapshot, ...]:
    if not isinstance(values, (list, tuple)):
        raise ModelError("invalid_sequence", f"{field_name} must be a list or tuple")
    snapshots = tuple(values)
    for index, snapshot in enumerate(snapshots):
        if not isinstance(snapshot, PageElementSnapshot):
            raise ModelError("invalid_sequence", f"{field_name}[{index}] must be a PageElementSnapshot")
    return snapshots


def _read_relation_tuple(values: Any, field_name: str) -> tuple[RelationCandidate, ...]:
    if not isinstance(values, (list, tuple)):
        raise ModelError("invalid_sequence", f"{field_name} must be a list or tuple")
    relations = tuple(values)
    for index, relation in enumerate(relations):
        if not isinstance(relation, RelationCandidate):
            raise ModelError("invalid_sequence", f"{field_name}[{index}] must be a RelationCandidate")
    return relations


def _read_issue_tuple(values: Any, field_name: str) -> tuple[EnrichmentIssue, ...]:
    if not isinstance(values, (list, tuple)):
        raise ModelError("invalid_sequence", f"{field_name} must be a list or tuple")
    issues = tuple(values)
    for index, issue in enumerate(issues):
        if not isinstance(issue, EnrichmentIssue):
            raise ModelError("invalid_sequence", f"{field_name}[{index}] must be an EnrichmentIssue")
    return issues


def _read_text_tuple(values: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise ModelError("invalid_sequence", f"{field_name} must be a list or tuple")
    text_values = tuple(values)
    for index, value in enumerate(text_values):
        try:
            _require_text(value, f"{field_name}[{index}]")
        except ModelError as error:
            raise ModelError("invalid_sequence", str(error)) from error
    return text_values


def _read_spatial_candidate_tuple(values: Any, field_name: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(values, (list, tuple)):
        raise ModelError("invalid_sequence", f"{field_name} must be a list or tuple")
    candidates = []
    for index, value in enumerate(values):
        if not isinstance(value, Mapping):
            raise ModelError("invalid_sequence", f"{field_name}[{index}] must be a mapping")
        candidate = dict(value)
        _require_text(candidate.get("target_id"), f"{field_name}[{index}].target_id")
        score = candidate.get("score")
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            raise ModelError("invalid_candidate_score", "candidate score must be a number")
        candidates.append(MappingProxyType(candidate))
    return tuple(candidates)


__all__ = (
    "ANNOTATION_SAME_PAGE_LINK_RULE",
    "BasicInfoContextResult",
    "BLOCK_CAPTION_LINK_RULE",
    "CROSS_SECTION_AMBIGUOUS_RATIO_DELTA",
    "CROSS_SECTION_GEOMETRY_OWNERSHIP_LINK_RULE",
    "CROSS_SECTION_MIN_OVERLAP_RATIO",
    "CURRENT_PAGE_BASIC_INFO_LINK_RULE",
    "PREVIOUS_PAGE_BASIC_INFO_LINK_RULE",
    "TABLE_CAPTION_BBOX_DISTANCE_LINK_RULE",
    "EnrichmentIssue",
    "EnrichmentResult",
    "EnrichmentScope",
    "EnrichmentStats",
    "PageElementSnapshot",
    "PageRelationSnapshot",
    "RelationCandidate",
    "SpatialCandidateGroup",
    "enrich_block_captions",
    "enrich_current_page_basic_infos",
    "enrich_cross_sections",
    "enrich_page_annotations",
    "enrich_page_relations",
    "enrich_previous_page_basic_infos",
    "enrich_table_captions",
)
