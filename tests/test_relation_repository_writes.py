import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class FakeTransaction:
    def __init__(self, legacy_records=()):
        self.calls = []
        self.legacy_records = list(legacy_records)

    def run(self, cypher, **parameters):
        self.calls.append((cypher, parameters))
        if "legacy_start.id AS legacy_start_id" in cypher:
            return list(self.legacy_records)
        return []


class FakeSession:
    def __init__(self, legacy_records=()):
        self.transaction = FakeTransaction(legacy_records)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute_write(self, callback):
        return callback(self.transaction)


class FakeDriver:
    def __init__(self, legacy_records=()):
        self.sessions = []
        self.legacy_records = list(legacy_records)

    def session(self):
        session = FakeSession(self.legacy_records)
        self.sessions.append(session)
        return session


def relation(start_id, end_id, relation_type, **properties):
    from drawing_graph.block_relation_enrichment import RelationCandidate

    return RelationCandidate(
        start_id=start_id,
        end_id=end_id,
        relation_spec=properties.pop("relation_spec", _default_relation_spec(relation_type)),
        relation_type=relation_type,
        relation_batch_id=properties.pop("relation_batch_id", "relation-batch:001"),
        rule_version=properties.pop("rule_version", "v1"),
        link_rule=properties.pop("link_rule", "test_rule_v1"),
        properties=properties,
    )


def _default_relation_spec(relation_type):
    return {
        "HAS_CAPTION": "block_caption",
        "HAS_BASIC_INFO": "block_basic_info",
        "HAS_ANNOTATION": "block_annotation",
        "HAS_SECTION_MARK": "block_section_mark",
        "USES_BASIC_INFO": "page_uses_basic_info",
        "CANDIDATE_CAPTION_OF": "candidate_caption_of",
        "CANDIDATE_HAS_SECTION_MARK": "candidate_section_mark",
    }.get(relation_type, "invalid_relation_spec")


class RelationRepositoryWritesTest(unittest.TestCase):
    def test_writes_caption_and_annotation_relations_with_parameterized_properties(self):
        from drawing_graph.relation_repository import RelationRepository

        driver = FakeDriver()
        repository = RelationRepository(driver)

        repository.write_relations(
            (
                relation("block:1", "caption:1", "HAS_CAPTION", distance=12.5, match_direction="below"),
                relation("block:1", "annotation:1", "HAS_ANNOTATION", match_direction="same_page_shared"),
            )
        )

        calls = driver.sessions[0].transaction.calls
        self.assertEqual(2, len(calls))
        caption_cypher, caption_parameters = calls[0]
        self.assertIn("UNWIND $relations AS relation", caption_cypher)
        self.assertIn("MATCH (start:DrawingBlock {id: relation.start_id})", caption_cypher)
        self.assertIn("MATCH (end:BlockCaption {id: relation.end_id})", caption_cypher)
        self.assertIn("MERGE (start)-[r:HAS_CAPTION {rule_version: relation.properties.rule_version}]->(end)", caption_cypher)
        self.assertIn("SET r += relation.properties", caption_cypher)
        self.assertNotIn("relation-batch:001", caption_cypher)
        self.assertNotIn("12.5", caption_cypher)
        self.assertNotIn("id(start)", caption_cypher)
        self.assertNotIn("elementId", caption_cypher)
        self.assertEqual(
            [
                {
                    "start_id": "block:1",
                    "end_id": "caption:1",
                    "properties": {
                        "distance": 12.5,
                        "match_direction": "below",
                        "relation_batch_id": "relation-batch:001",
                        "rule_version": "v1",
                        "link_rule": "test_rule_v1",
                    },
                }
            ],
            caption_parameters["relations"],
        )

    def test_relation_specs_include_page_and_candidate_specs_and_mark_block_basic_info_legacy_only(self):
        from drawing_graph.relation_repository import RELATION_SPECS

        self.assertEqual("DrawingPage", RELATION_SPECS["page_uses_basic_info"]["start_label"])
        self.assertEqual("USES_BASIC_INFO", RELATION_SPECS["page_uses_basic_info"]["relation_type"])
        self.assertEqual("DrawingBasicInfo", RELATION_SPECS["page_uses_basic_info"]["end_label"])
        self.assertEqual("BlockCaption", RELATION_SPECS["candidate_caption_of"]["start_label"])
        self.assertEqual("CANDIDATE_CAPTION_OF", RELATION_SPECS["candidate_caption_of"]["relation_type"])
        self.assertEqual("DrawingBlock", RELATION_SPECS["candidate_caption_of"]["end_label"])
        self.assertEqual("DrawingBlock", RELATION_SPECS["candidate_section_mark"]["start_label"])
        self.assertEqual("CANDIDATE_HAS_SECTION_MARK", RELATION_SPECS["candidate_section_mark"]["relation_type"])
        self.assertEqual("CrossSection", RELATION_SPECS["candidate_section_mark"]["end_label"])
        self.assertTrue(RELATION_SPECS["block_basic_info"]["legacy_only"])

    def test_rejects_block_basic_info_as_new_enrichment_write_before_query_runs(self):
        from drawing_graph.relation_repository import RelationRepository, RelationRepositoryError

        driver = FakeDriver()
        repository = RelationRepository(driver)

        with self.assertRaises(RelationRepositoryError) as context:
            repository.write_relations(
                (relation("block:1", "basic-info:1", "HAS_BASIC_INFO", match_direction="current_page"),)
            )

        self.assertEqual("legacy_relation_spec_not_writable", context.exception.category)
        self.assertEqual([], driver.sessions)

    def test_writes_page_uses_basic_info_with_fixed_endpoints_and_parameters(self):
        from drawing_graph.relation_repository import RelationRepository

        driver = FakeDriver()
        repository = RelationRepository(driver)

        repository.write_relations(
            (
                relation(
                    "page:1",
                    "basic-info:1",
                    "USES_BASIC_INFO",
                    status="confirmed",
                    source="current_page",
                    source_page_id="page:1",
                    group_id="group:a",
                ),
            )
        )

        cypher, parameters = driver.sessions[0].transaction.calls[0]
        self.assertIn("MATCH (start:DrawingPage {id: relation.start_id})", cypher)
        self.assertIn("MATCH (end:DrawingBasicInfo {id: relation.end_id})", cypher)
        self.assertIn("MERGE (start)-[r:USES_BASIC_INFO {rule_version: relation.properties.rule_version}]->(end)", cypher)
        self.assertNotIn("MATCH (start:DrawingBlock", cypher)
        self.assertNotIn("page:1", cypher)
        self.assertEqual("confirmed", parameters["relations"][0]["properties"]["status"])
        self.assertEqual("current_page", parameters["relations"][0]["properties"]["source"])
        self.assertEqual("page:1", parameters["relations"][0]["properties"]["source_page_id"])

    def test_writes_candidate_caption_of_with_fixed_endpoints_and_candidate_properties(self):
        from drawing_graph.relation_repository import RelationRepository

        driver = FakeDriver()
        repository = RelationRepository(driver)

        repository.write_relations(
            (
                relation(
                    "caption:1",
                    "block:1",
                    "CANDIDATE_CAPTION_OF",
                    status="candidate",
                    candidate_count=2,
                    score=0.8,
                    distance=12.5,
                    match_direction="below",
                    conflict_reason="distance_too_close",
                ),
            )
        )

        cypher, parameters = driver.sessions[0].transaction.calls[0]
        self.assertIn("MATCH (start:BlockCaption {id: relation.start_id})", cypher)
        self.assertIn("MATCH (end:DrawingBlock {id: relation.end_id})", cypher)
        self.assertIn("MERGE (start)-[r:CANDIDATE_CAPTION_OF {rule_version: relation.properties.rule_version}]->(end)", cypher)
        self.assertNotIn("MERGE (start)-[r:HAS_CAPTION", cypher)
        self.assertEqual("candidate", parameters["relations"][0]["properties"]["status"])
        self.assertEqual(2, parameters["relations"][0]["properties"]["candidate_count"])
        self.assertEqual(0.8, parameters["relations"][0]["properties"]["score"])

    def test_writes_candidate_section_mark_with_fixed_endpoints_and_candidate_properties(self):
        from drawing_graph.relation_repository import RelationRepository

        driver = FakeDriver()
        repository = RelationRepository(driver)

        repository.write_relations(
            (
                relation(
                    "block:1",
                    "cross-section:1",
                    "CANDIDATE_HAS_SECTION_MARK",
                    status="candidate",
                    candidate_count=2,
                    score=0.9,
                    overlap_area=100.0,
                    overlap_ratio=0.6,
                    containment_status="overlapped",
                    conflict_reason="overlap_too_close",
                ),
            )
        )

        cypher, parameters = driver.sessions[0].transaction.calls[0]
        self.assertIn("MATCH (start:DrawingBlock {id: relation.start_id})", cypher)
        self.assertIn("MATCH (end:CrossSection {id: relation.end_id})", cypher)
        self.assertIn(
            "MERGE (start)-[r:CANDIDATE_HAS_SECTION_MARK {rule_version: relation.properties.rule_version}]->(end)",
            cypher,
        )
        self.assertNotIn("MERGE (start)-[r:HAS_SECTION_MARK", cypher)
        self.assertEqual("candidate", parameters["relations"][0]["properties"]["status"])
        self.assertEqual(0.6, parameters["relations"][0]["properties"]["overlap_ratio"])

    def test_updates_candidate_review_status_with_fixed_candidate_spec_and_parameters(self):
        from drawing_graph.relation_repository import RelationRepository

        driver = FakeDriver()
        repository = RelationRepository(driver)

        repository.update_candidate_review(
            relation_spec="candidate_caption_of",
            start_id="caption:1",
            end_id="block:1",
            rule_version="v1",
            review_status="accepted",
            review_run_id="review-run:001",
            review_model_version="vision-model:v1",
            review_prompt_version="prompt:v1",
            review_score=0.91,
            review_reason="caption belongs to this block",
            reviewed_at="2026-08-05T10:00:00Z",
        )

        cypher, parameters = driver.sessions[0].transaction.calls[0]
        self.assertIn("MATCH (start:BlockCaption {id: $start_id})", cypher)
        self.assertIn("MATCH (end:DrawingBlock {id: $end_id})", cypher)
        self.assertIn("MATCH (start)-[r:CANDIDATE_CAPTION_OF {rule_version: $rule_version}]->(end)", cypher)
        self.assertIn("SET r += $properties", cypher)
        self.assertNotIn("HAS_CAPTION", cypher)
        self.assertEqual("caption:1", parameters["start_id"])
        self.assertEqual("block:1", parameters["end_id"])
        self.assertEqual("accepted", parameters["properties"]["review_status"])
        self.assertEqual("review-run:001", parameters["properties"]["review_run_id"])

    def test_rejects_invalid_candidate_review_update_before_query_runs(self):
        from drawing_graph.relation_repository import RelationRepository, RelationRepositoryError

        invalid_cases = (
            {"relation_spec": "block_caption", "review_status": "accepted", "category": "invalid_candidate_relation_spec"},
            {"relation_spec": "candidate_caption_of", "review_status": "done", "category": "invalid_review_status"},
        )

        for invalid_case in invalid_cases:
            driver = FakeDriver()
            repository = RelationRepository(driver)
            with self.subTest(invalid_case=invalid_case):
                with self.assertRaises(RelationRepositoryError) as context:
                    repository.update_candidate_review(
                        relation_spec=invalid_case["relation_spec"],
                        start_id="caption:1",
                        end_id="block:1",
                        rule_version="v1",
                        review_status=invalid_case["review_status"],
                        review_run_id="review-run:001",
                    )

                self.assertEqual(invalid_case["category"], context.exception.category)
                self.assertEqual([], driver.sessions)

    def test_promotes_accepted_caption_candidate_to_formal_caption_relation_and_marks_candidate(self):
        from drawing_graph.relation_repository import RelationRepository

        driver = FakeDriver()
        repository = RelationRepository(driver)

        repository.promote_candidate_relation(
            relation_spec="candidate_caption_of",
            candidate_start_id="caption:1",
            candidate_end_id="block:1",
            candidate_rule_version="v1",
            review_status="accepted",
            review_run_id="review-run:001",
            formal_rule_version="v2",
            confirmation_method="multimodal_llm",
        )

        cypher, parameters = driver.sessions[0].transaction.calls[0]
        self.assertIn("MATCH (candidate_start:BlockCaption {id: $candidate_start_id})", cypher)
        self.assertIn("MATCH (candidate_end:DrawingBlock {id: $candidate_end_id})", cypher)
        self.assertIn(
            "MATCH (candidate_start)-[candidate:CANDIDATE_CAPTION_OF {rule_version: $candidate_rule_version, review_status: 'accepted'}]->(candidate_end)",
            cypher,
        )
        self.assertIn("MERGE (candidate_end)-[formal:HAS_CAPTION {rule_version: $formal_rule_version}]->(candidate_start)", cypher)
        self.assertIn("SET formal += $formal_properties", cypher)
        self.assertIn("SET candidate.status = 'promoted'", cypher)
        self.assertEqual("caption:1", parameters["candidate_start_id"])
        self.assertEqual("block:1", parameters["candidate_end_id"])
        self.assertEqual("review-run:001", parameters["formal_properties"]["review_run_id"])
        self.assertEqual("multimodal_llm", parameters["formal_properties"]["confirmation_method"])

    def test_promotes_accepted_section_candidate_to_formal_section_mark_relation(self):
        from drawing_graph.relation_repository import RelationRepository

        driver = FakeDriver()
        repository = RelationRepository(driver)

        repository.promote_candidate_relation(
            relation_spec="candidate_section_mark",
            candidate_start_id="block:1",
            candidate_end_id="cross-section:1",
            candidate_rule_version="v1",
            review_status="accepted",
            review_run_id="review-run:001",
            formal_rule_version="v2",
            confirmation_method="multimodal_llm",
        )

        cypher, _ = driver.sessions[0].transaction.calls[0]
        self.assertIn("MATCH (candidate_start:DrawingBlock {id: $candidate_start_id})", cypher)
        self.assertIn("MATCH (candidate_end:CrossSection {id: $candidate_end_id})", cypher)
        self.assertIn("MERGE (candidate_start)-[formal:HAS_SECTION_MARK {rule_version: $formal_rule_version}]->(candidate_end)", cypher)

    def test_rejects_unaccepted_candidate_promotion_before_query_runs(self):
        from drawing_graph.relation_repository import RelationRepository, RelationRepositoryError

        driver = FakeDriver()
        repository = RelationRepository(driver)

        with self.assertRaises(RelationRepositoryError) as context:
            repository.promote_candidate_relation(
                relation_spec="candidate_caption_of",
                candidate_start_id="caption:1",
                candidate_end_id="block:1",
                candidate_rule_version="v1",
                review_status="unresolved",
                review_run_id="review-run:001",
                formal_rule_version="v2",
                confirmation_method="multimodal_llm",
            )

        self.assertEqual("candidate_not_accepted", context.exception.category)
        self.assertEqual([], driver.sessions)

    def test_writes_table_caption_relation_with_fixed_endpoints_and_parameters(self):
        from drawing_graph.relation_repository import RelationRepository

        driver = FakeDriver()
        repository = RelationRepository(driver)

        repository.write_relations(
            (
                relation(
                    "table:1",
                    "table-caption:1",
                    "HAS_CAPTION",
                    relation_spec="table_caption",
                    link_rule="table_caption_bbox_distance_v1",
                    distance=99.0,
                ),
                relation(
                    "table:1",
                    "table-caption:1",
                    "HAS_CAPTION",
                    relation_spec="table_caption",
                    link_rule="table_caption_bbox_distance_v1",
                    distance=10.0,
                ),
            )
        )

        calls = driver.sessions[0].transaction.calls
        self.assertEqual(2, len(calls))
        precheck_cypher, precheck_parameters = calls[0]
        cypher, parameters = calls[1]
        self.assertIn("legacy_start.id AS legacy_start_id", precheck_cypher)
        self.assertIn("MATCH (start:Table {id: $start_id})", cypher)
        self.assertIn("MATCH (end:TableCaption {id: $end_id})", cypher)
        self.assertIn("MERGE (start)-[r:HAS_CAPTION {rule_version: $rule_version}]->(end)", cypher)
        self.assertNotIn("table:1", cypher)
        self.assertNotIn("table-caption:1", cypher)
        self.assertEqual("table:1", precheck_parameters["start_id"])
        self.assertEqual("table-caption:1", precheck_parameters["end_id"])
        self.assertEqual("table:1", parameters["start_id"])
        self.assertEqual("table-caption:1", parameters["end_id"])
        self.assertEqual("v1", parameters["rule_version"])
        self.assertEqual(10.0, parameters["properties"]["distance"])

    def test_writes_table_caption_relation_when_optional_legacy_precheck_returns_null(self):
        from drawing_graph.relation_repository import RelationRepository

        driver = FakeDriver(legacy_records=({"legacy_start_id": None},))
        repository = RelationRepository(driver)

        repository.write_relations(
            (
                relation(
                    "table:1",
                    "table-caption:1",
                    "HAS_CAPTION",
                    relation_spec="table_caption",
                    link_rule="table_caption_bbox_distance_v1",
                    distance=10.0,
                ),
            )
        )

        calls = driver.sessions[0].transaction.calls
        self.assertEqual(2, len(calls))
        write_cypher, parameters = calls[1]
        self.assertIn("MERGE (start)-[r:HAS_CAPTION", write_cypher)
        self.assertEqual("table:1", parameters["start_id"])
        self.assertEqual("table-caption:1", parameters["end_id"])
        self.assertEqual(10.0, parameters["properties"]["distance"])

    def test_adopts_same_owner_legacy_table_caption_relation(self):
        from drawing_graph.relation_repository import RelationRepository

        driver = FakeDriver(legacy_records=({"legacy_start_id": "table:1"},))
        repository = RelationRepository(driver)

        repository.write_relations(
            (
                relation(
                    "table:1",
                    "table-caption:1",
                    "HAS_CAPTION",
                    relation_spec="table_caption",
                    link_rule="table_caption_bbox_distance_v1",
                    distance=10.0,
                ),
            )
        )

        calls = driver.sessions[0].transaction.calls
        self.assertEqual(2, len(calls))
        precheck_cypher, precheck_parameters = calls[0]
        adopt_cypher, adopt_parameters = calls[1]
        self.assertIn("legacy_start.id AS legacy_start_id", precheck_cypher)
        self.assertIn("SET legacy += $properties", adopt_cypher)
        self.assertNotIn("MERGE (start)-[r:HAS_CAPTION", adopt_cypher)
        self.assertEqual("table:1", precheck_parameters["start_id"])
        self.assertEqual("table-caption:1", precheck_parameters["end_id"])
        self.assertTrue(adopt_parameters["properties"]["legacy_adopted"])
        self.assertEqual("table:1", adopt_parameters["start_id"])

    def test_rejects_different_owner_legacy_table_caption_relation(self):
        from drawing_graph.relation_repository import RelationRepository, RelationRepositoryError

        driver = FakeDriver(legacy_records=({"legacy_start_id": "table:legacy"},))
        repository = RelationRepository(driver)

        with self.assertRaises(RelationRepositoryError) as context:
            repository.write_relations(
                (
                    relation(
                        "table:new",
                        "table-caption:1",
                        "HAS_CAPTION",
                        relation_spec="table_caption",
                        link_rule="table_caption_bbox_distance_v1",
                        distance=10.0,
                    ),
                )
            )

        self.assertEqual("table_caption_legacy_conflict", context.exception.category)
        calls = driver.sessions[0].transaction.calls
        self.assertEqual(1, len(calls))
        self.assertIn("legacy_start.id AS legacy_start_id", calls[0][0])

    def test_relation_schema_reuses_existing_types_without_block_type_or_near(self):
        from drawing_graph.neo4j_repository import ALLOWED_RELATION_TYPES

        schema = (PROJECT_ROOT / "scripts" / "create_schema.cypher").read_text(encoding="utf-8")

        self.assertIn("HAS_CAPTION", ALLOWED_RELATION_TYPES)
        self.assertIn("HAS_BASIC_INFO", ALLOWED_RELATION_TYPES)
        self.assertIn("HAS_ANNOTATION", ALLOWED_RELATION_TYPES)
        self.assertIn("HAS_SECTION_MARK", ALLOWED_RELATION_TYPES)
        self.assertNotIn("NEAR", schema)
        self.assertNotIn("block_type", schema)

    def test_allows_section_mark_relation_type_with_cross_section_endpoint(self):
        from drawing_graph.relation_repository import RELATION_END_LABELS, RelationRepository

        driver = FakeDriver()
        repository = RelationRepository(driver)

        repository.write_relations(
            (
                relation(
                    "block:1",
                    "cross-section:1",
                    "HAS_SECTION_MARK",
                    overlap_area=100.0,
                    overlap_ratio=1.0,
                    containment_status="contained",
                ),
            )
        )

        cypher, parameters = driver.sessions[0].transaction.calls[0]
        self.assertEqual("CrossSection", RELATION_END_LABELS["HAS_SECTION_MARK"])
        self.assertIn("MATCH (end:CrossSection {id: relation.end_id})", cypher)
        self.assertIn("MERGE (start)-[r:HAS_SECTION_MARK {rule_version: relation.properties.rule_version}]->(end)", cypher)
        self.assertNotIn("cross-section:1", cypher)
        self.assertEqual("cross-section:1", parameters["relations"][0]["end_id"])
        self.assertEqual(
            {
                "relation_batch_id": "relation-batch:001",
                "rule_version": "v1",
                "link_rule": "test_rule_v1",
                "overlap_area": 100.0,
                "overlap_ratio": 1.0,
                "containment_status": "contained",
            },
            parameters["relations"][0]["properties"],
        )

    def test_rejects_section_mark_without_required_geometry_evidence_before_query_runs(self):
        from drawing_graph.relation_repository import RelationRepository, RelationRepositoryError

        required_fields = ("overlap_area", "overlap_ratio", "containment_status")

        for missing_field in required_fields:
            driver = FakeDriver()
            repository = RelationRepository(driver)
            properties = {
                "overlap_area": 100.0,
                "overlap_ratio": 1.0,
                "containment_status": "contained",
            }
            del properties[missing_field]
            with self.subTest(missing_field=missing_field):
                with self.assertRaises(RelationRepositoryError) as context:
                    repository.write_relations(
                        (
                            relation(
                                "block:1",
                                "cross-section:1",
                                "HAS_SECTION_MARK",
                                **properties,
                            ),
                        )
                    )
                self.assertEqual("missing_section_mark_evidence", context.exception.category)
                self.assertEqual([], driver.sessions)

    def test_rejects_non_block_level_relation_type_before_query_runs(self):
        from drawing_graph.relation_repository import RelationRepository, RelationRepositoryError

        driver = FakeDriver()
        repository = RelationRepository(driver)

        with self.assertRaises(RelationRepositoryError) as context:
            repository.write_relations((relation("block:1", "caption:1", "HAS_TEXT"),))

        self.assertEqual("invalid_relation_type", context.exception.category)
        self.assertEqual([], driver.sessions)

    def test_rejects_unknown_relation_spec_before_query_runs(self):
        from drawing_graph.relation_repository import RelationRepository, RelationRepositoryError

        driver = FakeDriver()
        repository = RelationRepository(driver)

        with self.assertRaises(RelationRepositoryError) as context:
            repository.write_relations(
                (relation("block:1", "caption:1", "HAS_CAPTION", relation_spec="unknown_spec"),)
            )

        self.assertEqual("invalid_relation_spec", context.exception.category)
        self.assertEqual([], driver.sessions)

    def test_rejects_relation_spec_type_mismatch_before_query_runs(self):
        from drawing_graph.relation_repository import RelationRepository, RelationRepositoryError

        driver = FakeDriver()
        repository = RelationRepository(driver)

        with self.assertRaises(RelationRepositoryError) as context:
            repository.write_relations(
                (relation("block:1", "caption:1", "HAS_BASIC_INFO", relation_spec="block_caption"),)
            )

        self.assertEqual("relation_spec_type_mismatch", context.exception.category)
        self.assertEqual([], driver.sessions)

    def test_rejects_missing_relation_endpoints_before_query_runs(self):
        from drawing_graph.relation_repository import RelationRepository, RelationRepositoryError

        for start_id, end_id in ((" ", "caption:1"), ("block:1", " ")):
            driver = FakeDriver()
            repository = RelationRepository(driver)
            with self.subTest(start_id=start_id, end_id=end_id):
                with self.assertRaises(RelationRepositoryError) as context:
                    repository.write_relations((relation(start_id, end_id, "HAS_CAPTION"),))
                self.assertEqual("missing_relation_endpoint", context.exception.category)
                self.assertEqual([], driver.sessions)

    def test_deduplicates_same_rule_version_relations_with_latest_properties(self):
        from drawing_graph.relation_repository import RelationRepository

        driver = FakeDriver()
        repository = RelationRepository(driver)

        repository.write_relations(
            (
                relation("block:1", "caption:1", "HAS_CAPTION", distance=99.0, match_direction="below"),
                relation("block:1", "caption:1", "HAS_CAPTION", distance=12.5, match_direction="below"),
            )
        )

        _, parameters = driver.sessions[0].transaction.calls[0]
        self.assertEqual(1, len(parameters["relations"]))
        self.assertEqual(12.5, parameters["relations"][0]["properties"]["distance"])

    def test_keeps_different_rule_versions_as_separate_relation_payloads(self):
        from drawing_graph.relation_repository import RelationRepository

        driver = FakeDriver()
        repository = RelationRepository(driver)

        repository.write_relations(
            (
                relation("block:1", "caption:1", "HAS_CAPTION", rule_version="v1", distance=12.5, match_direction="below"),
                relation("block:1", "caption:1", "HAS_CAPTION", rule_version="v2", distance=8.0, match_direction="below"),
            )
        )

        _, parameters = driver.sessions[0].transaction.calls[0]
        self.assertEqual(
            ["v1", "v2"],
            [payload["properties"]["rule_version"] for payload in parameters["relations"]],
        )

    def test_empty_relation_input_does_not_open_session(self):
        from drawing_graph.relation_repository import RelationRepository

        driver = FakeDriver()
        repository = RelationRepository(driver)

        repository.write_relations(())

        self.assertEqual([], driver.sessions)


if __name__ == "__main__":
    unittest.main()
