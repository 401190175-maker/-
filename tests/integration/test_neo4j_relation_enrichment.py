import os
import sys
import unittest
from pathlib import Path
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


NEO4J_TEST_URI = os.environ.get("NEO4J_TEST_URI")
NEO4J_TEST_USER = os.environ.get("NEO4J_TEST_USER")
NEO4J_TEST_PASSWORD = os.environ.get("NEO4J_TEST_PASSWORD")


@unittest.skipUnless(
    NEO4J_TEST_URI and NEO4J_TEST_USER and NEO4J_TEST_PASSWORD,
    "NEO4J_TEST_URI, NEO4J_TEST_USER, and NEO4J_TEST_PASSWORD are required",
)
class Neo4jRelationEnrichmentIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from neo4j import GraphDatabase
        except ImportError as error:
            raise unittest.SkipTest("neo4j package is required for integration tests") from error

        cls.driver = GraphDatabase.driver(
            NEO4J_TEST_URI,
            auth=(NEO4J_TEST_USER, NEO4J_TEST_PASSWORD),
        )
        cls.driver.verify_connectivity()

    @classmethod
    def tearDownClass(cls):
        cls.driver.close()

    def setUp(self):
        self.project_slug = f"relation-integration-{uuid4().hex}"
        self.project_id = f"project:{self.project_slug}"
        self.drawing_set_id = f"set:{self.project_slug}:sample_set"
        self.previous_page_id = f"page:{self.project_slug}:sample_set:road_1"
        self.current_page_id = f"page:{self.project_slug}:sample_set:road_2"
        self.block_id = f"block:{self.project_slug}:sample_set:road_2:block"
        self.caption_candidate_peer_block_id = f"block:{self.project_slug}:sample_set:road_2:caption-candidate-peer"
        self.section_candidate_block_id = f"block:{self.project_slug}:sample_set:road_2:section-candidate"
        self.section_candidate_peer_block_id = f"block:{self.project_slug}:sample_set:road_2:section-candidate-peer"
        self.caption_id = f"element:{self.project_slug}:sample_set:road_2:caption"
        self.candidate_caption_id = f"element:{self.project_slug}:sample_set:road_2:candidate-caption"
        self.basic_info_id = f"element:{self.project_slug}:sample_set:road_1:basic"
        self.current_basic_info_id = f"element:{self.project_slug}:sample_set:road_2:basic"
        self.annotation_id = f"element:{self.project_slug}:sample_set:road_2:annotation"
        self.cross_section_id = f"element:{self.project_slug}:sample_set:road_2:section"
        self.candidate_cross_section_id = f"element:{self.project_slug}:sample_set:road_2:candidate-section"
        self.table_id = f"element:{self.project_slug}:sample_set:road_2:table"
        self.table_caption_id = f"element:{self.project_slug}:sample_set:road_2:table-caption"
        self.legacy_table_id = f"element:{self.project_slug}:sample_set:road_2:legacy-table"
        self.legacy_caption_id = f"element:{self.project_slug}:sample_set:road_2:legacy-caption"
        self.conflict_table_id = f"element:{self.project_slug}:sample_set:road_2:conflict-table"
        self.conflict_legacy_table_id = f"element:{self.project_slug}:sample_set:road_2:conflict-legacy-table"
        self.conflict_caption_id = f"element:{self.project_slug}:sample_set:road_2:conflict-caption"
        self.ok_table_id = f"element:{self.project_slug}:sample_set:road_2:ok-table"
        self.ok_caption_id = f"element:{self.project_slug}:sample_set:road_2:ok-caption"
        self.relation_batch_ids = []
        self._run_schema()
        self._create_imported_page_graph()

    def tearDown(self):
        self._cleanup_test_data()

    def test_relation_enrichment_writes_queryable_idempotent_block_relations(self):
        from drawing_graph.block_relation_enrichment import EnrichmentScope
        from drawing_graph.query_service import QueryService
        from drawing_graph.relation_repository import RelationRepository
        from drawing_graph.relation_service import RelationEnrichmentService

        repository = RelationRepository(self.driver)
        service = RelationEnrichmentService(repository)
        query_service = QueryService(self.driver)

        before = query_service.get_block_relations(self.block_id)
        self.assertEqual("partial", before["relation_status"])
        self.assertEqual([self.current_basic_info_id], before["basic_info_ids"])
        self.assertEqual("confirmed", before["basic_info_status"])
        self.assertEqual([], before["section_mark_ids"])
        self.assertEqual([], before["candidate_caption_ids"])
        self.assertEqual([], before["candidate_section_mark_ids"])

        first_batch_id = "relation-batch:first-" + uuid4().hex
        self.relation_batch_ids.append(first_batch_id)
        first_scope = EnrichmentScope(
            project_id=self.project_id,
            drawing_set_id=self.drawing_set_id,
            relation_batch_id=first_batch_id,
            rule_version="integration-rules-v1",
        )
        first_result = service.enrich_drawing_set(first_scope)
        first_summary = service.get_batch_summary(first_batch_id)

        self.assertEqual("partial", first_summary["status"])
        self.assertEqual(
            {
                "caption_candidate_ambiguous": 1,
                "section_candidate_ambiguous": 1,
                "table_caption_legacy_conflict": 1,
            },
            first_summary["issue_summary"],
        )
        self.assertEqual(2, first_result.stats.page_count)
        self.assertEqual(4, first_result.stats.block_count)
        self.assertEqual(5, first_result.stats.table_count)
        self.assertEqual(4, first_result.stats.table_caption_count)
        self.assertEqual(4, first_result.stats.table_caption_relation_count)
        self.assertEqual(2, first_result.stats.cross_section_count)
        self.assertEqual(1, first_result.stats.uses_basic_info_count)
        self.assertEqual(6, first_result.stats.candidate_count)
        self.assertEqual(17, first_result.stats.relation_count)

        relations = query_service.get_block_relations(self.block_id)
        self.assertEqual(
            {
                "block_id": self.block_id,
                "caption_ids": [self.caption_id],
                "basic_info_ids": [self.current_basic_info_id],
                "basic_info_status": "confirmed",
                "basic_info_source": "current_page",
                "annotation_ids": [self.annotation_id],
                "section_mark_ids": [self.cross_section_id],
                "candidate_caption_ids": [self.candidate_caption_id],
                "candidate_section_mark_ids": [],
                "relation_status": "candidate",
            },
            relations,
        )
        section_candidate_relations = query_service.get_block_relations(self.section_candidate_block_id)
        self.assertEqual([self.candidate_cross_section_id], section_candidate_relations["candidate_section_mark_ids"])
        self.assertEqual("candidate", section_candidate_relations["relation_status"])

        first_counts = self._relation_counts()
        self.assertEqual(
            {
                "HAS_CAPTION": 1,
                "HAS_ANNOTATION": 1,
                "HAS_SECTION_MARK": 1,
                "USES_BASIC_INFO": 1,
                "CANDIDATE_CAPTION_OF": 1,
                "CANDIDATE_HAS_SECTION_MARK": 0,
            },
            first_counts,
        )
        candidate_counts = self._candidate_relation_counts()
        self.assertEqual(
            {
                "CANDIDATE_CAPTION_OF": 4,
                "CANDIDATE_HAS_SECTION_MARK": 2,
                "formal_block_relation_count": 6,
            },
            candidate_counts,
        )
        table_counts = self._table_caption_relation_counts()
        self.assertEqual(
            {
                "total_count": 4,
                "current_rule_count": 3,
                "legacy_adopted_count": 1,
                "conflict_legacy_count": 1,
                "conflict_new_count": 0,
                "ok_count": 1,
            },
            table_counts,
        )
        self.assertEqual(
            {
                "relation_batch_id": first_batch_id,
                "rule_version": "integration-rules-v1",
                "link_rule": "cross_section_geometry_ownership_v1",
                "overlap_area": 100.0,
                "overlap_ratio": 1.0,
                "containment_status": "contained",
            },
            self._section_mark_relation_properties(),
        )
        self.assertEqual(
            {
                "status": "confirmed",
                "source": "current_page",
                "source_page_id": self.current_page_id,
                "rule_version": "integration-rules-v1",
            },
            self._uses_basic_info_relation_properties(),
        )
        self.assertEqual(
            {
                "status": "candidate",
                "candidate_count": 4,
                "review_status": None,
                "review_run_id": None,
            },
            self._candidate_caption_relation_properties(self.candidate_caption_id, self.block_id),
        )

        repository.update_candidate_review(
            relation_spec="candidate_caption_of",
            start_id=self.candidate_caption_id,
            end_id=self.block_id,
            rule_version="integration-rules-v1",
            review_status="unresolved",
            review_run_id="review-run:" + uuid4().hex,
            review_model_version="integration-review-model",
            review_prompt_version="integration-review-prompt",
            review_score=0.42,
            review_reason="integration ambiguity fixture",
        )
        reviewed_candidate = self._candidate_caption_relation_properties(self.candidate_caption_id, self.block_id)
        self.assertEqual("unresolved", reviewed_candidate["review_status"])
        self.assertTrue(reviewed_candidate["review_run_id"].startswith("review-run:"))

        second_batch_id = "relation-batch:second-" + uuid4().hex
        self.relation_batch_ids.append(second_batch_id)
        second_scope = EnrichmentScope(
            project_id=self.project_id,
            drawing_set_id=self.drawing_set_id,
            relation_batch_id=second_batch_id,
            rule_version="integration-rules-v1",
        )
        service.enrich_drawing_set(second_scope)

        self.assertEqual(first_counts, self._relation_counts())
        self.assertEqual(candidate_counts, self._candidate_relation_counts())
        self.assertEqual(table_counts, self._table_caption_relation_counts())
        self.assertEqual(relations, query_service.get_block_relations(self.block_id))
        self.assertEqual("unresolved", self._candidate_caption_relation_properties(self.candidate_caption_id, self.block_id)["review_status"])

    def _run_schema(self):
        statements = _schema_statements(PROJECT_ROOT / "scripts" / "create_schema.cypher")
        with self.driver.session() as session:
            for statement in statements:
                session.execute_write(lambda transaction, cypher=statement: transaction.run(cypher).consume())

    def _create_imported_page_graph(self):
        with self.driver.session() as session:
            session.execute_write(lambda transaction: _create_imported_page_graph(transaction, self))

    def _relation_counts(self):
        with self.driver.session() as session:
            return session.execute_read(lambda transaction: _relation_counts(transaction, self))

    def _candidate_relation_counts(self):
        with self.driver.session() as session:
            return session.execute_read(lambda transaction: _candidate_relation_counts(transaction, self))

    def _section_mark_relation_properties(self):
        with self.driver.session() as session:
            return session.execute_read(
                lambda transaction: _section_mark_relation_properties(
                    transaction,
                    self.block_id,
                    self.cross_section_id,
                )
            )

    def _uses_basic_info_relation_properties(self):
        with self.driver.session() as session:
            return session.execute_read(lambda transaction: _uses_basic_info_relation_properties(transaction, self))

    def _candidate_caption_relation_properties(self, caption_id, block_id):
        with self.driver.session() as session:
            return session.execute_read(
                lambda transaction: _candidate_caption_relation_properties(transaction, caption_id, block_id)
            )

    def _table_caption_relation_counts(self):
        with self.driver.session() as session:
            return session.execute_read(lambda transaction: _table_caption_relation_counts(transaction, self))

    def _cleanup_test_data(self):
        with self.driver.session() as session:
            session.execute_write(lambda transaction: _cleanup_test_data(transaction, self.project_slug, self.relation_batch_ids))


def _schema_statements(schema_path):
    text = schema_path.read_text(encoding="utf-8")
    return tuple(statement.strip() for statement in text.split(";") if statement.strip())


def _create_imported_page_graph(transaction, test_case):
    bbox = [10.0, 40.0, 50.0, 90.0]
    caption_candidate_peer_bbox = [40.0, 40.0, 80.0, 90.0]
    section_candidate_block_bbox = [1000.0, 1000.0, 1060.0, 1060.0]
    section_candidate_peer_block_bbox = [1000.0, 1000.0, 1060.0, 1060.0]
    caption_bbox = [10.0, 10.0, 50.0, 30.0]
    candidate_caption_bbox = [25.0, 10.0, 65.0, 30.0]
    basic_bbox = [0.0, 0.0, 20.0, 20.0]
    current_basic_bbox = [20.0, 0.0, 40.0, 20.0]
    annotation_bbox = [60.0, 40.0, 90.0, 70.0]
    cross_section_bbox = [20.0, 50.0, 30.0, 60.0]
    candidate_cross_section_bbox = [1010.0, 1010.0, 1020.0, 1020.0]
    table_bbox = [100.0, 100.0, 180.0, 160.0]
    table_caption_bbox = [100.0, 170.0, 180.0, 190.0]
    legacy_table_bbox = [300.0, 100.0, 380.0, 160.0]
    legacy_caption_bbox = [300.0, 170.0, 380.0, 190.0]
    conflict_table_bbox = [500.0, 100.0, 580.0, 160.0]
    conflict_legacy_table_bbox = [900.0, 100.0, 980.0, 160.0]
    conflict_caption_bbox = [500.0, 170.0, 580.0, 190.0]
    ok_table_bbox = [700.0, 100.0, 780.0, 160.0]
    ok_caption_bbox = [700.0, 170.0, 780.0, 190.0]
    normalized_bbox = [0.1, 0.1, 0.5, 0.9]
    transaction.run(
        """
        MERGE (project:Project {id: $project_id})
        SET project.name = $project_id
        MERGE (drawing_set:DrawingSet {id: $drawing_set_id})
        SET drawing_set.name = 'sample_set', drawing_set.page_count = 2
        MERGE (project)-[:HAS_SET]->(drawing_set)
        MERGE (previous_page:DrawingPage {id: $previous_page_id})
        SET previous_page.page_number = 1,
            previous_page.file_name = 'road_1.json',
            previous_page.image_path = 'tests/fixtures/road_1.png'
        MERGE (current_page:DrawingPage {id: $current_page_id})
        SET current_page.page_number = 2,
            current_page.file_name = 'road_2.json',
            current_page.image_path = 'tests/fixtures/road_2.png'
        MERGE (drawing_set)-[:HAS_PAGE]->(previous_page)
        MERGE (drawing_set)-[:HAS_PAGE]->(current_page)
        MERGE (block:DrawingBlock {id: $block_id})
        SET block.label = 'block',
            block.confidence = 0.98,
            block.bbox = $bbox,
            block.normalized_bbox = $normalized_bbox
        MERGE (caption_candidate_peer:DrawingBlock {id: $caption_candidate_peer_block_id})
        SET caption_candidate_peer.label = 'block',
            caption_candidate_peer.confidence = 0.97,
            caption_candidate_peer.bbox = $caption_candidate_peer_bbox,
            caption_candidate_peer.normalized_bbox = $normalized_bbox
        MERGE (section_candidate_block:DrawingBlock {id: $section_candidate_block_id})
        SET section_candidate_block.label = 'block',
            section_candidate_block.confidence = 0.96,
            section_candidate_block.bbox = $section_candidate_block_bbox,
            section_candidate_block.normalized_bbox = $normalized_bbox
        MERGE (section_candidate_peer_block:DrawingBlock {id: $section_candidate_peer_block_id})
        SET section_candidate_peer_block.label = 'block',
            section_candidate_peer_block.confidence = 0.95,
            section_candidate_peer_block.bbox = $section_candidate_peer_block_bbox,
            section_candidate_peer_block.normalized_bbox = $normalized_bbox
        MERGE (caption:BlockCaption {id: $caption_id})
        SET caption.bbox = $caption_bbox
        MERGE (candidate_caption:BlockCaption {id: $candidate_caption_id})
        SET candidate_caption.bbox = $candidate_caption_bbox
        MERGE (basic_info:DrawingBasicInfo {id: $basic_info_id})
        SET basic_info.bbox = $basic_bbox
        MERGE (current_basic_info:DrawingBasicInfo {id: $current_basic_info_id})
        SET current_basic_info.bbox = $current_basic_bbox
        MERGE (annotation:DrawingAnnotation {id: $annotation_id})
        SET annotation.bbox = $annotation_bbox
        MERGE (cross_section:CrossSection {id: $cross_section_id})
        SET cross_section.bbox = $cross_section_bbox
        MERGE (candidate_cross_section:CrossSection {id: $candidate_cross_section_id})
        SET candidate_cross_section.bbox = $candidate_cross_section_bbox
        MERGE (table:Table {id: $table_id})
        SET table.bbox = $table_bbox
        MERGE (table_caption:TableCaption {id: $table_caption_id})
        SET table_caption.bbox = $table_caption_bbox
        MERGE (legacy_table:Table {id: $legacy_table_id})
        SET legacy_table.bbox = $legacy_table_bbox
        MERGE (legacy_caption:TableCaption {id: $legacy_caption_id})
        SET legacy_caption.bbox = $legacy_caption_bbox
        MERGE (conflict_table:Table {id: $conflict_table_id})
        SET conflict_table.bbox = $conflict_table_bbox
        MERGE (conflict_legacy_table:Table {id: $conflict_legacy_table_id})
        SET conflict_legacy_table.bbox = $conflict_legacy_table_bbox
        MERGE (conflict_caption:TableCaption {id: $conflict_caption_id})
        SET conflict_caption.bbox = $conflict_caption_bbox
        MERGE (ok_table:Table {id: $ok_table_id})
        SET ok_table.bbox = $ok_table_bbox
        MERGE (ok_caption:TableCaption {id: $ok_caption_id})
        SET ok_caption.bbox = $ok_caption_bbox
        MERGE (current_page)-[:HAS_BLOCK]->(block)
        MERGE (current_page)-[:HAS_BLOCK]->(caption_candidate_peer)
        MERGE (current_page)-[:HAS_BLOCK]->(section_candidate_block)
        MERGE (current_page)-[:HAS_BLOCK]->(section_candidate_peer_block)
        MERGE (current_page)-[:HAS_ELEMENT]->(caption)
        MERGE (current_page)-[:HAS_ELEMENT]->(candidate_caption)
        MERGE (previous_page)-[:HAS_BASIC_INFO]->(basic_info)
        MERGE (current_page)-[:HAS_BASIC_INFO]->(current_basic_info)
        MERGE (current_page)-[:HAS_ANNOTATION]->(annotation)
        MERGE (current_page)-[:HAS_ELEMENT]->(cross_section)
        MERGE (current_page)-[:HAS_ELEMENT]->(candidate_cross_section)
        MERGE (current_page)-[:HAS_TABLE]->(table)
        MERGE (current_page)-[:HAS_ELEMENT]->(table_caption)
        MERGE (current_page)-[:HAS_TABLE]->(legacy_table)
        MERGE (current_page)-[:HAS_ELEMENT]->(legacy_caption)
        MERGE (current_page)-[:HAS_TABLE]->(conflict_table)
        MERGE (current_page)-[:HAS_TABLE]->(conflict_legacy_table)
        MERGE (current_page)-[:HAS_ELEMENT]->(conflict_caption)
        MERGE (current_page)-[:HAS_TABLE]->(ok_table)
        MERGE (current_page)-[:HAS_ELEMENT]->(ok_caption)
        MERGE (legacy_table)-[:HAS_CAPTION]->(legacy_caption)
        MERGE (conflict_legacy_table)-[:HAS_CAPTION]->(conflict_caption)
        """,
        project_id=test_case.project_id,
        drawing_set_id=test_case.drawing_set_id,
        previous_page_id=test_case.previous_page_id,
        current_page_id=test_case.current_page_id,
        block_id=test_case.block_id,
        caption_candidate_peer_block_id=test_case.caption_candidate_peer_block_id,
        section_candidate_block_id=test_case.section_candidate_block_id,
        section_candidate_peer_block_id=test_case.section_candidate_peer_block_id,
        caption_id=test_case.caption_id,
        candidate_caption_id=test_case.candidate_caption_id,
        basic_info_id=test_case.basic_info_id,
        current_basic_info_id=test_case.current_basic_info_id,
        annotation_id=test_case.annotation_id,
        cross_section_id=test_case.cross_section_id,
        candidate_cross_section_id=test_case.candidate_cross_section_id,
        table_id=test_case.table_id,
        table_caption_id=test_case.table_caption_id,
        legacy_table_id=test_case.legacy_table_id,
        legacy_caption_id=test_case.legacy_caption_id,
        conflict_table_id=test_case.conflict_table_id,
        conflict_legacy_table_id=test_case.conflict_legacy_table_id,
        conflict_caption_id=test_case.conflict_caption_id,
        ok_table_id=test_case.ok_table_id,
        ok_caption_id=test_case.ok_caption_id,
        bbox=bbox,
        caption_candidate_peer_bbox=caption_candidate_peer_bbox,
        section_candidate_block_bbox=section_candidate_block_bbox,
        section_candidate_peer_block_bbox=section_candidate_peer_block_bbox,
        caption_bbox=caption_bbox,
        candidate_caption_bbox=candidate_caption_bbox,
        basic_bbox=basic_bbox,
        current_basic_bbox=current_basic_bbox,
        annotation_bbox=annotation_bbox,
        cross_section_bbox=cross_section_bbox,
        candidate_cross_section_bbox=candidate_cross_section_bbox,
        table_bbox=table_bbox,
        table_caption_bbox=table_caption_bbox,
        legacy_table_bbox=legacy_table_bbox,
        legacy_caption_bbox=legacy_caption_bbox,
        conflict_table_bbox=conflict_table_bbox,
        conflict_legacy_table_bbox=conflict_legacy_table_bbox,
        conflict_caption_bbox=conflict_caption_bbox,
        ok_table_bbox=ok_table_bbox,
        ok_caption_bbox=ok_caption_bbox,
        normalized_bbox=normalized_bbox,
    ).consume()


def _relation_counts(transaction, test_case):
    result = transaction.run(
        """
        MATCH (block:DrawingBlock {id: $block_id})-[relation]->()
        WHERE type(relation) IN ['HAS_CAPTION', 'HAS_ANNOTATION', 'HAS_SECTION_MARK', 'CANDIDATE_HAS_SECTION_MARK']
        RETURN type(relation) AS relation_type, count(relation) AS relation_count
        ORDER BY relation_type ASC
        """,
        block_id=test_case.block_id,
    )
    counts = {record["relation_type"]: record["relation_count"] for record in result}
    uses_basic_info_count = transaction.run(
        """
        MATCH (:DrawingPage {id: $page_id})-[relation:USES_BASIC_INFO]->(:DrawingBasicInfo {id: $basic_info_id})
        RETURN count(relation) AS relation_count
        """,
        page_id=test_case.current_page_id,
        basic_info_id=test_case.current_basic_info_id,
    ).single()["relation_count"]
    incoming_candidate_caption_count = transaction.run(
        """
        MATCH (:BlockCaption)-[relation:CANDIDATE_CAPTION_OF]->(:DrawingBlock {id: $block_id})
        RETURN count(relation) AS relation_count
        """,
        block_id=test_case.block_id,
    ).single()["relation_count"]
    return {
        "HAS_CAPTION": counts.get("HAS_CAPTION", 0),
        "HAS_ANNOTATION": counts.get("HAS_ANNOTATION", 0),
        "HAS_SECTION_MARK": counts.get("HAS_SECTION_MARK", 0),
        "USES_BASIC_INFO": uses_basic_info_count,
        "CANDIDATE_CAPTION_OF": incoming_candidate_caption_count,
        "CANDIDATE_HAS_SECTION_MARK": counts.get("CANDIDATE_HAS_SECTION_MARK", 0),
    }


def _candidate_relation_counts(transaction, test_case):
    result = transaction.run(
        """
        MATCH (node)-[relation]->()
        WHERE node.id STARTS WITH $block_prefix OR node.id STARTS WITH $element_prefix
        RETURN type(relation) AS relation_type, count(relation) AS relation_count
        ORDER BY relation_type ASC
        """,
        block_prefix=f"block:{test_case.project_slug}:",
        element_prefix=f"element:{test_case.project_slug}:",
    )
    counts = {record["relation_type"]: record["relation_count"] for record in result}
    formal_block_relation_count = transaction.run(
        """
        MATCH (:DrawingBlock)-[relation]->()
        WHERE type(relation) IN ['HAS_CAPTION', 'HAS_ANNOTATION', 'HAS_SECTION_MARK']
          AND startNode(relation).id STARTS WITH $block_prefix
        RETURN count(relation) AS relation_count
        """,
        block_prefix=f"block:{test_case.project_slug}:",
    ).single()["relation_count"]
    return {
        "CANDIDATE_CAPTION_OF": counts.get("CANDIDATE_CAPTION_OF", 0),
        "CANDIDATE_HAS_SECTION_MARK": counts.get("CANDIDATE_HAS_SECTION_MARK", 0),
        "formal_block_relation_count": formal_block_relation_count,
    }


def _section_mark_relation_properties(transaction, block_id, cross_section_id):
    result = transaction.run(
        """
        MATCH (block:DrawingBlock {id: $block_id})-[relation:HAS_SECTION_MARK]->(cross_section:CrossSection {id: $cross_section_id})
        RETURN relation.relation_batch_id AS relation_batch_id,
               relation.rule_version AS rule_version,
               relation.link_rule AS link_rule,
               relation.overlap_area AS overlap_area,
               relation.overlap_ratio AS overlap_ratio,
               relation.containment_status AS containment_status
        LIMIT 1
        """,
        block_id=block_id,
        cross_section_id=cross_section_id,
    )
    records = list(result)
    if not records:
        return None
    record = records[0]
    return {
        "relation_batch_id": record["relation_batch_id"],
        "rule_version": record["rule_version"],
        "link_rule": record["link_rule"],
        "overlap_area": record["overlap_area"],
        "overlap_ratio": record["overlap_ratio"],
        "containment_status": record["containment_status"],
    }


def _uses_basic_info_relation_properties(transaction, test_case):
    result = transaction.run(
        """
        MATCH (:DrawingPage {id: $page_id})-[relation:USES_BASIC_INFO]->(:DrawingBasicInfo {id: $basic_info_id})
        RETURN relation.status AS status,
               relation.source AS source,
               relation.source_page_id AS source_page_id,
               relation.rule_version AS rule_version
        LIMIT 1
        """,
        page_id=test_case.current_page_id,
        basic_info_id=test_case.current_basic_info_id,
    )
    record = result.single()
    if record is None:
        return None
    return {
        "status": record["status"],
        "source": record["source"],
        "source_page_id": record["source_page_id"],
        "rule_version": record["rule_version"],
    }


def _candidate_caption_relation_properties(transaction, caption_id, block_id):
    result = transaction.run(
        """
        MATCH (:BlockCaption {id: $caption_id})-[relation:CANDIDATE_CAPTION_OF]->(:DrawingBlock {id: $block_id})
        RETURN relation.status AS status,
               relation.candidate_count AS candidate_count,
               relation.review_status AS review_status,
               relation.review_run_id AS review_run_id
        LIMIT 1
        """,
        caption_id=caption_id,
        block_id=block_id,
    )
    record = result.single()
    if record is None:
        return None
    return {
        "status": record["status"],
        "candidate_count": record["candidate_count"],
        "review_status": record["review_status"],
        "review_run_id": record["review_run_id"],
    }


def _table_caption_relation_counts(transaction, test_case):
    result = transaction.run(
        """
        MATCH (page:DrawingPage {id: $page_id})
        OPTIONAL MATCH (table:Table)-[relation:HAS_CAPTION]->(caption:TableCaption)
        WHERE table.id STARTS WITH $element_prefix
        OPTIONAL MATCH (table)-[versioned:HAS_CAPTION]->(caption)
        WHERE versioned.rule_version = $rule_version
        OPTIONAL MATCH (:Table {id: $legacy_table_id})-[adopted:HAS_CAPTION]->(:TableCaption {id: $legacy_caption_id})
        WHERE adopted.legacy_adopted = true
        OPTIONAL MATCH (:Table {id: $conflict_legacy_table_id})-[conflict_legacy:HAS_CAPTION]->(:TableCaption {id: $conflict_caption_id})
        WHERE conflict_legacy.rule_version IS NULL
        OPTIONAL MATCH (:Table {id: $conflict_table_id})-[conflict_new:HAS_CAPTION]->(:TableCaption {id: $conflict_caption_id})
        OPTIONAL MATCH (:Table {id: $ok_table_id})-[ok:HAS_CAPTION]->(:TableCaption {id: $ok_caption_id})
        WHERE ok.rule_version = $rule_version
        RETURN count(relation) AS total_count,
               count(DISTINCT versioned) AS current_rule_count,
               count(DISTINCT adopted) AS legacy_adopted_count,
               count(DISTINCT conflict_legacy) AS conflict_legacy_count,
               count(DISTINCT conflict_new) AS conflict_new_count,
               count(DISTINCT ok) AS ok_count
        """,
        page_id=test_case.current_page_id,
        element_prefix=f"element:{test_case.project_slug}:sample_set:road_2:",
        rule_version="integration-rules-v1",
        legacy_table_id=test_case.legacy_table_id,
        legacy_caption_id=test_case.legacy_caption_id,
        conflict_legacy_table_id=test_case.conflict_legacy_table_id,
        conflict_caption_id=test_case.conflict_caption_id,
        conflict_table_id=test_case.conflict_table_id,
        ok_table_id=test_case.ok_table_id,
        ok_caption_id=test_case.ok_caption_id,
    )
    record = result.single()
    return {
        "total_count": record["total_count"],
        "current_rule_count": record["current_rule_count"],
        "legacy_adopted_count": record["legacy_adopted_count"],
        "conflict_legacy_count": record["conflict_legacy_count"],
        "conflict_new_count": record["conflict_new_count"],
        "ok_count": record["ok_count"],
    }


def _cleanup_test_data(transaction, project_slug, relation_batch_ids):
    transaction.run(
        """
        MATCH (node)
        WHERE node.id STARTS WITH $project_prefix
           OR node.id STARTS WITH $set_prefix
           OR node.id STARTS WITH $page_prefix
           OR node.id STARTS WITH $block_prefix
           OR node.id STARTS WITH $element_prefix
           OR node.id IN $relation_batch_ids
        DETACH DELETE node
        """,
        project_prefix=f"project:{project_slug}",
        set_prefix=f"set:{project_slug}:",
        page_prefix=f"page:{project_slug}:",
        block_prefix=f"block:{project_slug}:",
        element_prefix=f"element:{project_slug}:",
        relation_batch_ids=[batch_id for batch_id in relation_batch_ids if batch_id],
    ).consume()


if __name__ == "__main__":
    unittest.main()

