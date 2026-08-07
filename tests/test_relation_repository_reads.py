import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class FakeTransaction:
    def __init__(self, records=()):
        self.records = list(records)
        self.calls = []

    def run(self, cypher, **parameters):
        self.calls.append((cypher, parameters))
        return list(self.records)


class FakeSession:
    def __init__(self, records=()):
        self.transaction = FakeTransaction(records)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute_read(self, callback):
        return callback(self.transaction)


class FakeDriver:
    def __init__(self, records=()):
        self.records = list(records)
        self.sessions = []

    def session(self):
        session = FakeSession(self.records)
        self.sessions.append(session)
        return session


def bbox():
    return {"x_min": 10, "y_min": 20, "x_max": 110, "y_max": 120}


def page_record(**overrides):
    record = {
        "page_id": "page:road:set-a:road_24",
        "drawing_set_id": "set:road:set-a",
        "page_number": 24,
        "blocks": ({"id": "block:1", "page_id": "page:road:set-a:road_24", "bbox": bbox(), "properties": {"label": "block"}},),
        "captions": ({"id": "caption:1", "page_id": "page:road:set-a:road_24", "bbox": bbox(), "properties": {}},),
        "tables": ({"id": "table:1", "page_id": "page:road:set-a:road_24", "bbox": bbox(), "properties": {"label": "table"}},),
        "table_captions": ({"id": "table-caption:1", "page_id": "page:road:set-a:road_24", "bbox": bbox(), "properties": {"label": "table caption"}},),
        "basic_infos": ({"id": "basic-info:1", "page_id": "page:road:set-a:road_24", "bbox": bbox(), "properties": {}},),
        "annotations": ({"id": "annotation:1", "page_id": "page:road:set-a:road_24", "bbox": bbox(), "properties": {}},),
        "cross_sections": (),
        "node_id": 99,
    }
    record.update(overrides)
    return record


def scope(**overrides):
    from drawing_graph.block_relation_enrichment import EnrichmentScope

    values = {
        "project_id": "project:road",
        "relation_batch_id": "relation-batch:001",
        "rule_version": "v1",
    }
    values.update(overrides)
    return EnrichmentScope(**values)


class RelationRepositoryReadsTest(unittest.TestCase):
    def test_read_pages_by_project_returns_page_snapshots_with_current_elements(self):
        from drawing_graph.block_relation_enrichment import PageRelationSnapshot
        from drawing_graph.relation_repository import RelationRepository

        driver = FakeDriver(records=(page_record(),))
        repository = RelationRepository(driver)

        pages = repository.read_pages(scope(), limit=25)

        self.assertEqual(1, len(pages))
        self.assertIsInstance(pages[0], PageRelationSnapshot)
        self.assertEqual("page:road:set-a:road_24", pages[0].page_id)
        self.assertEqual("set:road:set-a", pages[0].drawing_set_id)
        self.assertEqual(24, pages[0].page_number)
        self.assertEqual("block:1", pages[0].blocks[0].id)
        self.assertEqual("caption:1", pages[0].captions[0].id)
        self.assertEqual("table:1", pages[0].tables[0].id)
        self.assertEqual("table-caption:1", pages[0].table_captions[0].id)
        self.assertEqual("basic-info:1", pages[0].basic_infos[0].id)
        self.assertEqual("annotation:1", pages[0].annotations[0].id)
        self.assertEqual("block", pages[0].blocks[0].properties["label"])

        cypher, _ = driver.sessions[0].transaction.calls[0]
        self.assertIn("OPTIONAL MATCH (page)-[:HAS_TABLE]->(table:Table)", cypher)
        self.assertIn("OPTIONAL MATCH (page)-[:HAS_ELEMENT]->(table_caption:TableCaption)", cypher)
        self.assertIn("tables", cypher)
        self.assertIn("table_captions", cypher)

    def test_read_pages_returns_cross_sections_from_page_elements(self):
        from drawing_graph.relation_repository import RelationRepository

        driver = FakeDriver(
            records=(
                page_record(
                    cross_sections=(
                        {
                            "id": "cross-section:1",
                            "page_id": "page:road:set-a:road_24",
                            "bbox": bbox(),
                            "properties": {"label": "cross section"},
                        },
                    )
                ),
            )
        )
        repository = RelationRepository(driver)

        pages = repository.read_pages(scope(), limit=25)

        self.assertEqual("cross-section:1", pages[0].cross_sections[0].id)
        self.assertEqual("page:road:set-a:road_24", pages[0].cross_sections[0].page_id)
        self.assertEqual("cross section", pages[0].cross_sections[0].properties["label"])
        cypher, parameters = driver.sessions[0].transaction.calls[0]
        self.assertIn("OPTIONAL MATCH (page)-[:HAS_ELEMENT]->(cross_section:CrossSection)", cypher)
        self.assertIn("cross_sections", cypher)
        self.assertEqual({"project_id": "project:road", "limit": 25}, parameters)

    def test_read_pages_by_drawing_set_limits_scope_with_parameters(self):
        from drawing_graph.relation_repository import RelationRepository

        driver = FakeDriver(records=())
        repository = RelationRepository(driver)

        repository.read_pages(scope(drawing_set_id="set:road:set-a"), limit=10)

        cypher, parameters = driver.sessions[0].transaction.calls[0]
        self.assertIn("MATCH (project:Project {id: $project_id})-[:HAS_SET]->(drawing_set:DrawingSet {id: $drawing_set_id})", cypher)
        self.assertIn("-[:HAS_PAGE]->(page:DrawingPage)", cypher)
        self.assertIn("LIMIT $limit", cypher)
        self.assertNotIn("set:road:set-a", cypher)
        self.assertNotIn("id(page)", cypher)
        self.assertNotIn("elementId", cypher)
        self.assertEqual({"project_id": "project:road", "drawing_set_id": "set:road:set-a", "limit": 10}, parameters)

    def test_read_single_page_limits_scope_with_parameters(self):
        from drawing_graph.relation_repository import RelationRepository

        driver = FakeDriver(records=())
        repository = RelationRepository(driver)

        repository.read_pages(scope(page_id="page:road:set-a:road_24"), limit=5)

        cypher, parameters = driver.sessions[0].transaction.calls[0]
        self.assertIn("MATCH (project:Project {id: $project_id})-[:HAS_SET]->(drawing_set:DrawingSet)", cypher)
        self.assertIn("-[:HAS_PAGE]->(page:DrawingPage {id: $page_id})", cypher)
        self.assertIn("LIMIT $limit", cypher)
        self.assertNotIn("page:road:set-a:road_24", cypher)
        self.assertEqual({"project_id": "project:road", "page_id": "page:road:set-a:road_24", "limit": 5}, parameters)

    def test_read_pages_rejects_invalid_limit_before_query_runs(self):
        from drawing_graph.relation_repository import RelationRepository, RelationRepositoryError

        for invalid_limit in (0, -1, True, "10"):
            driver = FakeDriver(records=())
            repository = RelationRepository(driver)
            with self.subTest(invalid_limit=invalid_limit):
                with self.assertRaises(RelationRepositoryError) as context:
                    repository.read_pages(scope(), limit=invalid_limit)
                self.assertEqual("invalid_limit", context.exception.category)
                self.assertEqual([], driver.sessions)

    def test_read_previous_page_basic_infos_uses_same_drawing_set_only(self):
        from drawing_graph.block_relation_enrichment import PageRelationSnapshot
        from drawing_graph.relation_repository import RelationRepository

        current_page = PageRelationSnapshot(
            page_id="page:road:set-a:road_24",
            drawing_set_id="set:road:set-a",
            page_number=24,
        )
        driver = FakeDriver(
            records=(
                page_record(
                    page_id="page:road:set-a:road_23",
                    drawing_set_id="set:road:set-a",
                    page_number=23,
                    blocks=(),
                    captions=(),
                    annotations=(),
                    basic_infos=(
                        {"id": "basic-info:previous", "page_id": "page:road:set-a:road_23", "bbox": bbox(), "properties": {}},
                    ),
                ),
            )
        )
        repository = RelationRepository(driver)

        previous_page = repository.read_previous_page_basic_infos(current_page)

        self.assertEqual("page:road:set-a:road_23", previous_page.page_id)
        self.assertEqual("basic-info:previous", previous_page.basic_infos[0].id)
        cypher, parameters = driver.sessions[0].transaction.calls[0]
        self.assertIn("MATCH (drawing_set:DrawingSet {id: $drawing_set_id})-[:HAS_PAGE]->(page:DrawingPage)", cypher)
        self.assertIn("page.page_number = $previous_page_number", cypher)
        self.assertNotIn("set:road:set-a", cypher)
        self.assertEqual({"drawing_set_id": "set:road:set-a", "previous_page_number": 23}, parameters)

    def test_previous_page_from_other_drawing_set_is_rejected(self):
        from drawing_graph.block_relation_enrichment import PageRelationSnapshot
        from drawing_graph.relation_repository import RelationRepository, RelationRepositoryError

        current_page = PageRelationSnapshot(
            page_id="page:road:set-a:road_24",
            drawing_set_id="set:road:set-a",
            page_number=24,
        )
        repository = RelationRepository(
            FakeDriver(
                records=(
                    page_record(
                        page_id="page:road:set-b:road_23",
                        drawing_set_id="set:road:set-b",
                        page_number=23,
                    ),
                )
            )
        )

        with self.assertRaises(RelationRepositoryError) as context:
            repository.read_previous_page_basic_infos(current_page)

        self.assertEqual("previous_page_drawing_set_mismatch", context.exception.category)

    def test_malformed_element_bbox_is_rejected(self):
        from drawing_graph.relation_repository import RelationRepository, RelationRepositoryError

        malformed_page = page_record(
            blocks=(
                {"id": "block:bad", "page_id": "page:road:set-a:road_24", "bbox": {"x_min": 1}, "properties": {}},
            )
        )
        repository = RelationRepository(FakeDriver(records=(malformed_page,)))

        with self.assertRaises(RelationRepositoryError) as context:
            repository.read_pages(scope())

        self.assertEqual("invalid_bbox", context.exception.category)

    def test_candidate_relation_port_projects_persisted_candidates(self):
        from drawing_graph.relation_repository import RelationRepository, RelationRepositoryCandidateRelationPort
        from drawing_graph.tool_models import CandidateRelationSummary

        driver = FakeDriver(
            records=(
                {
                    "candidate_group_id": "caption:1:block:1:v1",
                    "page_id": "page:1",
                    "block_id": "block:1",
                    "relation_type": "candidate_caption_of",
                    "status": "matched_candidate",
                    "score": 0.82,
                    "conflict_reason": None,
                    "evidence_ids": ["obs:1"],
                    "recognition_run_id": "run:1",
                },
            )
        )
        port = RelationRepositoryCandidateRelationPort(RelationRepository(driver))

        candidates = port.list_candidate_relations(page_id="page:1", status="matched_candidate")

        self.assertEqual(1, len(candidates))
        self.assertIsInstance(candidates[0], CandidateRelationSummary)
        self.assertEqual("caption:1:block:1:v1", candidates[0].candidate_group_id)
        self.assertEqual("candidate_caption_of", candidates[0].relation_type)
        self.assertEqual(("obs:1",), candidates[0].evidence_ids)
        cypher, parameters = driver.sessions[0].transaction.calls[0]
        self.assertIn("CANDIDATE_CAPTION_OF", cypher)
        self.assertIn("CANDIDATE_HAS_SECTION_MARK", cypher)
        self.assertNotIn("page:1", cypher)
        self.assertEqual(
            {
                "page_id": "page:1",
                "block_id": None,
                "relation_type": None,
                "status": "matched_candidate",
            },
            parameters,
        )

    def test_section_match_query_port_projects_candidate_and_formal_matches(self):
        from drawing_graph.relation_repository import RelationRepository, RelationRepositorySectionMatchQueryPort
        from drawing_graph.tool_models import SectionMatchSummary

        driver = FakeDriver(
            records=(
                {
                    "cross_section_id": "cross:1",
                    "match_status": "candidate",
                    "logical_key": "SECTION_1",
                    "matched_caption_id": "caption:1",
                    "candidate_count": 2,
                    "conflict_reason": "multiple same-key captions",
                    "observation_ids": ["obs:cross", "obs:caption"],
                    "rule_version": "section-match-v1",
                    "fact_kind": "candidate_relation",
                    "status": "candidate",
                    "page_id": "page:1",
                },
                {
                    "cross_section_id": "cross:1",
                    "match_status": "formal",
                    "logical_key": "SECTION_1",
                    "matched_caption_id": "caption:1",
                    "candidate_count": 1,
                    "conflict_reason": None,
                    "observation_ids": ["obs:cross", "obs:caption"],
                    "rule_version": "section-match-v1",
                    "fact_kind": "formal_relation",
                    "status": "confirmed",
                    "page_id": "page:1",
                },
            )
        )
        port = RelationRepositorySectionMatchQueryPort(RelationRepository(driver))

        matches = port.list_section_matches(cross_section_id="cross:1", statuses=("candidate", "confirmed"))

        self.assertEqual(2, len(matches))
        self.assertTrue(all(isinstance(item, SectionMatchSummary) for item in matches))
        self.assertEqual(("caption:1",), matches[0].matched_caption_ids)
        self.assertEqual("candidate_relation", matches[0].fact_kind)
        self.assertEqual("formal_relation", matches[1].fact_kind)
        self.assertEqual({"page_id": "page:1"}, dict(matches[0].evidence))
        cypher, parameters = driver.sessions[0].transaction.calls[0]
        self.assertIn("CANDIDATE_MATCHES_SECTION_CAPTION", cypher)
        self.assertIn("MATCHES_SECTION_CAPTION", cypher)
        self.assertNotIn("cross:1", cypher)
        self.assertEqual(
            {
                "cross_section_id": "cross:1",
                "page_id": None,
                "statuses": ("candidate", "confirmed"),
            },
            parameters,
        )


if __name__ == "__main__":
    unittest.main()
