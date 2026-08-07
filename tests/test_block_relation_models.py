import dataclasses
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def make_bbox():
    from drawing_graph.models import BBox

    return BBox(x_min=10, y_min=20, x_max=110, y_max=120)


class BlockRelationModelsTest(unittest.TestCase):
    def test_scope_requires_project_batch_and_rule_version_with_optional_range(self):
        from drawing_graph.block_relation_enrichment import EnrichmentScope

        scope = EnrichmentScope(
            project_id="project:road",
            relation_batch_id="relation-batch:001",
            rule_version="block-rel-v1",
            drawing_set_id="set:road:a",
            page_id="page:road:a:road_24",
        )

        self.assertEqual("project:road", scope.project_id)
        self.assertEqual("set:road:a", scope.drawing_set_id)
        self.assertEqual("page:road:a:road_24", scope.page_id)
        self.assertEqual("relation-batch:001", scope.relation_batch_id)
        self.assertEqual("block-rel-v1", scope.rule_version)

    def test_scope_rejects_empty_required_ids(self):
        from drawing_graph.block_relation_enrichment import EnrichmentScope
        from drawing_graph.models import ModelError

        with self.assertRaises(ModelError) as context:
            EnrichmentScope(project_id="", relation_batch_id="batch:1", rule_version="v1")

        self.assertEqual("missing_required_field", context.exception.category)

    def test_page_snapshot_holds_block_caption_table_basic_info_annotation_and_cross_section_lists(self):
        from drawing_graph.block_relation_enrichment import PageElementSnapshot, PageRelationSnapshot

        block = PageElementSnapshot(id="block:1", page_id="page:1", bbox=make_bbox())
        caption = PageElementSnapshot(id="caption:1", page_id="page:1", bbox=make_bbox())
        table = PageElementSnapshot(id="table:1", page_id="page:1", bbox=make_bbox())
        table_caption = PageElementSnapshot(id="table-caption:1", page_id="page:1", bbox=make_bbox())
        basic_info = PageElementSnapshot(id="basic:1", page_id="page:1", bbox=make_bbox())
        annotation = PageElementSnapshot(id="annotation:1", page_id="page:1", bbox=make_bbox())
        cross_section = PageElementSnapshot(id="cross-section:1", page_id="page:1", bbox=make_bbox())

        snapshot = PageRelationSnapshot(
            page_id="page:1",
            drawing_set_id="set:1",
            page_number=24,
            blocks=[block],
            captions=[caption],
            tables=[table],
            table_captions=[table_caption],
            basic_infos=[basic_info],
            annotations=[annotation],
            cross_sections=[cross_section],
        )

        self.assertEqual((block,), snapshot.blocks)
        self.assertEqual((caption,), snapshot.captions)
        self.assertEqual((table,), snapshot.tables)
        self.assertEqual((table_caption,), snapshot.table_captions)
        self.assertEqual((basic_info,), snapshot.basic_infos)
        self.assertEqual((annotation,), snapshot.annotations)
        self.assertEqual((cross_section,), snapshot.cross_sections)

    def test_page_snapshot_defaults_table_fields_and_cross_sections_to_empty_tuple(self):
        from drawing_graph.block_relation_enrichment import PageRelationSnapshot

        snapshot = PageRelationSnapshot(page_id="page:1", drawing_set_id="set:1", page_number=24)

        self.assertEqual((), snapshot.tables)
        self.assertEqual((), snapshot.table_captions)
        self.assertEqual((), snapshot.cross_sections)

    def test_page_snapshot_rejects_non_table_snapshots(self):
        from drawing_graph.block_relation_enrichment import PageRelationSnapshot
        from drawing_graph.models import ModelError

        for field_name in ("tables", "table_captions", "cross_sections"):
            with self.subTest(field_name=field_name):
                with self.assertRaises(ModelError) as context:
                    PageRelationSnapshot(
                        page_id="page:1",
                        drawing_set_id="set:1",
                        page_number=24,
                        **{field_name: ["element:1"]},
                    )

                self.assertEqual("invalid_sequence", context.exception.category)

    def test_page_snapshot_rejects_non_sequence_table_snapshots(self):
        from drawing_graph.block_relation_enrichment import PageRelationSnapshot
        from drawing_graph.models import ModelError

        with self.assertRaises(ModelError) as context:
            PageRelationSnapshot(
                page_id="page:1",
                drawing_set_id="set:1",
                page_number=24,
                tables="table:1",
            )

        self.assertEqual("invalid_sequence", context.exception.category)

    def test_page_snapshot_and_elements_are_immutable(self):
        from drawing_graph.block_relation_enrichment import PageElementSnapshot, PageRelationSnapshot

        block = PageElementSnapshot(id="block:1", page_id="page:1", bbox=make_bbox(), properties={"label": "block"})
        snapshot = PageRelationSnapshot(page_id="page:1", drawing_set_id="set:1", page_number=1, blocks=[block])

        with self.assertRaises(dataclasses.FrozenInstanceError):
            snapshot.page_id = "changed"
        with self.assertRaises(dataclasses.FrozenInstanceError):
            block.id = "changed"
        with self.assertRaises(TypeError):
            block.properties["label"] = "changed"

    def test_relation_candidate_contains_required_audit_properties(self):
        from drawing_graph.block_relation_enrichment import RelationCandidate

        candidate = RelationCandidate(
            start_id="block:1",
            end_id="caption:1",
            relation_spec="block_caption",
            relation_type="HAS_CAPTION",
            relation_batch_id="relation-batch:001",
            rule_version="block-rel-v1",
            link_rule="block_caption_center_direction_v1",
            properties={"distance": 42.5, "match_direction": "below"},
        )

        self.assertEqual("block:1", candidate.start_id)
        self.assertEqual("caption:1", candidate.end_id)
        self.assertEqual("block_caption", candidate.relation_spec)
        self.assertEqual("HAS_CAPTION", candidate.relation_type)
        self.assertEqual("relation-batch:001", candidate.properties["relation_batch_id"])
        self.assertEqual("block-rel-v1", candidate.properties["rule_version"])
        self.assertEqual("block_caption_center_direction_v1", candidate.properties["link_rule"])
        self.assertEqual("below", candidate.properties["match_direction"])

    def test_relation_candidate_rejects_empty_endpoint(self):
        from drawing_graph.block_relation_enrichment import RelationCandidate
        from drawing_graph.models import ModelError

        with self.assertRaises(ModelError) as context:
            RelationCandidate(
                start_id="",
                end_id="caption:1",
                relation_spec="block_caption",
                relation_type="HAS_CAPTION",
                relation_batch_id="relation-batch:001",
                rule_version="block-rel-v1",
                link_rule="rule",
            )

        self.assertEqual("missing_required_field", context.exception.category)

    def test_relation_candidate_rejects_empty_relation_spec(self):
        from drawing_graph.block_relation_enrichment import RelationCandidate
        from drawing_graph.models import ModelError

        with self.assertRaises(ModelError) as context:
            RelationCandidate(
                start_id="block:1",
                end_id="caption:1",
                relation_spec="",
                relation_type="HAS_CAPTION",
                relation_batch_id="relation-batch:001",
                rule_version="block-rel-v1",
                link_rule="rule",
            )

        self.assertEqual("missing_required_field", context.exception.category)

    def test_relation_candidate_allows_candidate_relation_and_review_metadata(self):
        from drawing_graph.block_relation_enrichment import RelationCandidate

        candidate = RelationCandidate(
            start_id="caption:1",
            end_id="block:1",
            relation_spec="candidate_caption_of",
            relation_type="CANDIDATE_CAPTION_OF",
            relation_batch_id="relation-batch:001",
            rule_version="block-rel-v2",
            link_rule="block_caption_center_direction_v1",
            properties={
                "status": "candidate",
                "candidate_count": 2,
                "score": 0.8,
                "distance": 12.5,
                "conflict_reason": "distance_too_close",
                "review_status": "not_started",
                "review_run_id": "review-run:001",
            },
        )

        self.assertEqual("candidate_caption_of", candidate.relation_spec)
        self.assertEqual("CANDIDATE_CAPTION_OF", candidate.relation_type)
        self.assertEqual("candidate", candidate.properties["status"])
        self.assertEqual("not_started", candidate.properties["review_status"])
        self.assertEqual("review-run:001", candidate.properties["review_run_id"])

    def test_basic_info_context_result_records_page_level_decision(self):
        from drawing_graph.block_relation_enrichment import BasicInfoContextResult

        result = BasicInfoContextResult(
            page_id="page:1",
            status="confirmed",
            source="current_page",
            source_page_id="page:1",
            group_id="group:a",
            basic_info_ids=["basic-info:1"],
        )

        self.assertEqual("page:1", result.page_id)
        self.assertEqual("confirmed", result.status)
        self.assertEqual("current_page", result.source)
        self.assertEqual("page:1", result.source_page_id)
        self.assertEqual("group:a", result.group_id)
        self.assertEqual(("basic-info:1",), result.basic_info_ids)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.status = "partial"

    def test_basic_info_context_result_rejects_invalid_values(self):
        from drawing_graph.block_relation_enrichment import BasicInfoContextResult
        from drawing_graph.models import ModelError

        invalid_cases = (
            {"page_id": ""},
            {"status": "done"},
            {"source": "previous_page"},
            {"basic_info_ids": "basic-info:1"},
        )

        for overrides in invalid_cases:
            values = {
                "page_id": "page:1",
                "status": "not_evaluated",
                "source": "unavailable",
                "basic_info_ids": [],
            }
            values.update(overrides)
            with self.subTest(overrides=overrides):
                with self.assertRaises(ModelError):
                    BasicInfoContextResult(**values)

    def test_spatial_candidate_group_records_complete_candidate_set(self):
        from drawing_graph.block_relation_enrichment import SpatialCandidateGroup

        group = SpatialCandidateGroup(
            group_key="caption:1",
            relation_spec="candidate_caption_of",
            source_element_id="caption:1",
            candidates=[
                {
                    "target_id": "block:1",
                    "score": 0.8,
                    "distance": 12.5,
                    "match_direction": "below",
                },
                {
                    "target_id": "block:2",
                    "score": 0.75,
                    "distance": 13.0,
                    "match_direction": "below",
                },
            ],
            candidate_count=2,
            conflict_reason="distance_too_close",
        )

        self.assertEqual("candidate_caption_of", group.relation_spec)
        self.assertEqual("caption:1", group.source_element_id)
        self.assertEqual(2, group.candidate_count)
        self.assertEqual("distance_too_close", group.conflict_reason)
        self.assertEqual("block:1", group.candidates[0]["target_id"])
        with self.assertRaises(dataclasses.FrozenInstanceError):
            group.candidate_count = 1
        with self.assertRaises(TypeError):
            group.candidates[0]["score"] = 0.1

    def test_spatial_candidate_group_rejects_invalid_candidate_sets(self):
        from drawing_graph.block_relation_enrichment import SpatialCandidateGroup
        from drawing_graph.models import ModelError

        valid_candidate = {"target_id": "block:1", "score": 0.8}
        invalid_cases = (
            {"relation_spec": "block_caption"},
            {"candidates": [], "candidate_count": 1},
            {"candidates": [valid_candidate], "candidate_count": 2},
            {"candidates": [{"score": 0.8}], "candidate_count": 1},
            {"candidates": [{"target_id": "block:1", "score": "high"}], "candidate_count": 1},
        )

        for overrides in invalid_cases:
            values = {
                "group_key": "caption:1",
                "relation_spec": "candidate_caption_of",
                "source_element_id": "caption:1",
                "candidates": [valid_candidate],
                "candidate_count": 1,
            }
            values.update(overrides)
            with self.subTest(overrides=overrides):
                with self.assertRaises(ModelError):
                    SpatialCandidateGroup(**values)

    def test_result_records_relations_classified_issues_and_default_stats(self):
        from drawing_graph.block_relation_enrichment import (
            EnrichmentIssue,
            EnrichmentResult,
            EnrichmentScope,
            EnrichmentStats,
            RelationCandidate,
        )

        scope = EnrichmentScope(project_id="project:road", relation_batch_id="batch:1", rule_version="v1")
        relation = RelationCandidate(
            start_id="block:1",
            end_id="annotation:1",
            relation_spec="block_annotation",
            relation_type="HAS_ANNOTATION",
            relation_batch_id="batch:1",
            rule_version="v1",
            link_rule="annotation_same_page_shared_v1",
        )
        issue = EnrichmentIssue(
            category="annotation_not_found",
            message="page has no annotations",
            severity="warning",
            page_id="page:1",
        )
        result = EnrichmentResult(scope=scope, relations=[relation], issues=[issue])

        self.assertEqual(0, EnrichmentStats().page_count)
        self.assertEqual(0, EnrichmentStats().relation_count)
        self.assertEqual((relation,), result.relations)
        self.assertEqual((issue,), result.issues)
        self.assertEqual(1, result.stats.relation_count)
        self.assertEqual(1, result.stats.warning_count)
        self.assertEqual(0, result.stats.error_count)

    def test_cross_section_rule_constants_are_stable(self):
        from drawing_graph.block_relation_enrichment import (
            CROSS_SECTION_AMBIGUOUS_RATIO_DELTA,
            CROSS_SECTION_GEOMETRY_OWNERSHIP_LINK_RULE,
            CROSS_SECTION_MIN_OVERLAP_RATIO,
        )

        self.assertEqual("cross_section_geometry_ownership_v1", CROSS_SECTION_GEOMETRY_OWNERSHIP_LINK_RULE)
        self.assertEqual(0.5, CROSS_SECTION_MIN_OVERLAP_RATIO)
        self.assertEqual(0.05, CROSS_SECTION_AMBIGUOUS_RATIO_DELTA)

    def test_stats_records_cross_section_count_with_default(self):
        from drawing_graph.block_relation_enrichment import EnrichmentStats

        self.assertEqual(0, EnrichmentStats().cross_section_count)

        stats = EnrichmentStats(cross_section_count=3)

        self.assertEqual(3, stats.cross_section_count)
        self.assertEqual(0, stats.annotation_count)

    def test_stats_records_table_counts_with_defaults(self):
        from drawing_graph.block_relation_enrichment import EnrichmentStats

        self.assertEqual(0, EnrichmentStats().table_count)
        self.assertEqual(0, EnrichmentStats().table_caption_count)
        self.assertEqual(0, EnrichmentStats().table_caption_relation_count)

        stats = EnrichmentStats(table_count=2, table_caption_count=3, table_caption_relation_count=4)

        self.assertEqual(2, stats.table_count)
        self.assertEqual(3, stats.table_caption_count)
        self.assertEqual(4, stats.table_caption_relation_count)
        self.assertEqual(0, stats.relation_count)

    def test_stats_records_basic_info_candidate_and_review_status_counts(self):
        from drawing_graph.block_relation_enrichment import EnrichmentStats

        self.assertEqual(0, EnrichmentStats().uses_basic_info_count)
        self.assertEqual(0, EnrichmentStats().candidate_count)
        self.assertEqual(0, EnrichmentStats().ambiguous_count)
        self.assertEqual(0, EnrichmentStats().not_evaluated_count)
        self.assertEqual(0, EnrichmentStats().reviewing_count)
        self.assertEqual(0, EnrichmentStats().accepted_count)
        self.assertEqual(0, EnrichmentStats().rejected_count)
        self.assertEqual(0, EnrichmentStats().unresolved_count)

        stats = EnrichmentStats(
            uses_basic_info_count=1,
            candidate_count=2,
            ambiguous_count=3,
            not_evaluated_count=4,
            reviewing_count=5,
            accepted_count=6,
            rejected_count=7,
            unresolved_count=8,
        )

        self.assertEqual(1, stats.uses_basic_info_count)
        self.assertEqual(2, stats.candidate_count)
        self.assertEqual(3, stats.ambiguous_count)
        self.assertEqual(4, stats.not_evaluated_count)
        self.assertEqual(5, stats.reviewing_count)
        self.assertEqual(6, stats.accepted_count)
        self.assertEqual(7, stats.rejected_count)
        self.assertEqual(8, stats.unresolved_count)

    def test_stats_rejects_invalid_table_counts(self):
        from drawing_graph.block_relation_enrichment import EnrichmentStats
        from drawing_graph.models import ModelError

        for field_name in ("table_count", "table_caption_count", "table_caption_relation_count"):
            for invalid_count in (-1, True):
                with self.subTest(field_name=field_name, invalid_count=invalid_count):
                    with self.assertRaises(ModelError) as context:
                        EnrichmentStats(**{field_name: invalid_count})

                    self.assertEqual("invalid_count", context.exception.category)

    def test_stats_rejects_invalid_cross_section_count(self):
        from drawing_graph.block_relation_enrichment import EnrichmentStats
        from drawing_graph.models import ModelError

        for invalid_count in (-1, True):
            with self.subTest(invalid_count=invalid_count):
                with self.assertRaises(ModelError) as context:
                    EnrichmentStats(cross_section_count=invalid_count)

                self.assertEqual("invalid_count", context.exception.category)

    def test_stats_rejects_invalid_basic_info_candidate_and_review_status_counts(self):
        from drawing_graph.block_relation_enrichment import EnrichmentStats
        from drawing_graph.models import ModelError

        field_names = (
            "uses_basic_info_count",
            "candidate_count",
            "ambiguous_count",
            "not_evaluated_count",
            "reviewing_count",
            "accepted_count",
            "rejected_count",
            "unresolved_count",
        )
        for field_name in field_names:
            for invalid_count in (-1, True):
                with self.subTest(field_name=field_name, invalid_count=invalid_count):
                    with self.assertRaises(ModelError) as context:
                        EnrichmentStats(**{field_name: invalid_count})

                    self.assertEqual("invalid_count", context.exception.category)


if __name__ == "__main__":
    unittest.main()
