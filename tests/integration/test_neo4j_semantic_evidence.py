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
class Neo4jSemanticEvidenceIntegrationTest(unittest.TestCase):
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
        self.project_slug = f"semantic-integration-{uuid4().hex}"
        self.project_id = f"project:{self.project_slug}"
        self.drawing_set_id = f"set:{self.project_slug}:sample_set"
        self.page_id = f"page:{self.project_slug}:sample_set:road_1"
        self.block_id = f"block:{self.project_slug}:sample_set:road_1:block"
        self.cross_section_id = f"element:{self.project_slug}:sample_set:road_1:section"
        self.caption_id = f"element:{self.project_slug}:sample_set:road_1:caption"
        self.basic_info_id = f"element:{self.project_slug}:sample_set:road_1:basic"
        self.table_id = f"element:{self.project_slug}:sample_set:road_1:table"
        self.observation_ids = (
            f"observation:{self.project_slug}:cross-section",
            f"observation:{self.project_slug}:caption",
            f"observation:{self.project_slug}:block",
        )
        self.interpretation_ids = (
            f"interpretation:{self.project_slug}:block",
            f"interpretation:{self.project_slug}:basic",
            f"interpretation:{self.project_slug}:table",
        )
        self._run_schema()
        self._create_source_graph()

    def tearDown(self):
        self._cleanup_test_data()

    def test_semantic_evidence_and_section_match_writes_are_queryable_and_idempotent(self):
        from drawing_graph.block_relation_enrichment import RelationCandidate
        from drawing_graph.relation_repository import RelationRepository
        from drawing_graph.semantic_models import (
            BasicInfoInterpretation,
            BlockInterpretation,
            TableInterpretation,
            TextObservation,
        )
        from drawing_graph.semantic_neo4j_repository import SemanticNeo4jRepository
        from drawing_graph.tool_factory import create_neo4j_tool_facade
        from drawing_graph.tool_models import BBox

        semantic_repository = SemanticNeo4jRepository(self.driver)
        relation_repository = RelationRepository(self.driver)
        observations = (
            TextObservation(
                observation_id=self.observation_ids[0],
                recognition_run_id=f"run:{self.project_slug}:recognition",
                target_element_id=self.cross_section_id,
                target_element_type="CrossSection",
                page_id=self.page_id,
                raw_text="A",
                normalized_text="A",
                bbox=BBox(10, 10, 20, 20),
                normalized_bbox=BBox(0.1, 0.1, 0.2, 0.2),
                confidence=0.96,
                status="confirmed",
                image_hash=f"image-hash:{self.project_slug}",
                cache_key=f"cache:{self.project_slug}:section",
                model_profile="integration-model",
                prompt_version="integration-prompt",
                created_at="2026-08-06T00:00:00Z",
            ),
            TextObservation(
                observation_id=self.observation_ids[1],
                recognition_run_id=f"run:{self.project_slug}:recognition",
                target_element_id=self.caption_id,
                target_element_type="BlockCaption",
                page_id=self.page_id,
                raw_text="A-A",
                normalized_text="A-A",
                bbox=BBox(30, 10, 60, 20),
                normalized_bbox=BBox(0.3, 0.1, 0.6, 0.2),
                confidence=0.94,
                status="matched_candidate",
                image_hash=f"image-hash:{self.project_slug}",
                cache_key=f"cache:{self.project_slug}:caption",
                model_profile="integration-model",
                prompt_version="integration-prompt",
                created_at="2026-08-06T00:00:01Z",
            ),
            TextObservation(
                observation_id=self.observation_ids[2],
                recognition_run_id=f"run:{self.project_slug}:interpretation",
                target_element_id=self.block_id,
                target_element_type="DrawingBlock",
                page_id=self.page_id,
                raw_text="beam detail",
                normalized_text="beam detail",
                bbox=BBox(10, 30, 80, 90),
                normalized_bbox=BBox(0.1, 0.3, 0.8, 0.9),
                confidence=0.9,
                status="partial",
                image_hash=f"image-hash:{self.project_slug}",
                cache_key=f"cache:{self.project_slug}:block-text",
                model_profile="integration-model",
                prompt_version="integration-prompt",
                created_at="2026-08-06T00:00:02Z",
            ),
        )
        interpretations = (
            BlockInterpretation(
                interpretation_id=self.interpretation_ids[0],
                recognition_run_id=f"run:{self.project_slug}:interpretation",
                block_id=self.block_id,
                summary="Beam section detail with partial internal text.",
                page_id=self.page_id,
                interpreted_type="section_detail",
                components=("beam",),
                materials=("concrete",),
                dimensions=("partial",),
                construction_features=("reinforcement",),
                spatial_relations=("supported_by_wall",),
                analysis_status="partial",
                uncertainties=("dimension text incomplete",),
                supported_by_observation_ids=(self.observation_ids[2],),
                payload_ref=f"payload:{self.project_slug}:block",
                cache_key=f"cache:{self.project_slug}:block-interpretation",
                contract_version="1",
            ),
            BasicInfoInterpretation(
                interpretation_id=self.interpretation_ids[1],
                recognition_run_id=f"run:{self.project_slug}:interpretation",
                basic_info_id=self.basic_info_id,
                raw_text="Project A",
                summary="Project A basic information.",
                page_id=self.page_id,
                project_name="Project A",
                analysis_status="interpreted",
                payload_ref=f"payload:{self.project_slug}:basic",
                cache_key=f"cache:{self.project_slug}:basic-interpretation",
                contract_version="1",
            ),
            TableInterpretation(
                interpretation_id=self.interpretation_ids[2],
                recognition_run_id=f"run:{self.project_slug}:interpretation",
                table_id=self.table_id,
                summary="Schedule table.",
                page_id=self.page_id,
                caption_ref=self.caption_id,
                analysis_status="interpreted",
                payload_ref=f"payload:{self.project_slug}:table",
                cache_key=f"cache:{self.project_slug}:table-interpretation",
                contract_version="1",
            ),
        )
        candidate_relation = RelationCandidate(
            start_id=self.cross_section_id,
            end_id=self.caption_id,
            relation_spec="candidate_matches_section_caption",
            relation_type="CANDIDATE_MATCHES_SECTION_CAPTION",
            relation_batch_id=f"semantic-batch:{self.project_slug}",
            rule_version="semantic-integration-v1",
            link_rule="section_match_v1",
            properties={
                "status": "candidate",
                "candidate_group_id": f"section-match:{self.project_slug}",
                "candidate_count": 1,
                "score": 0.94,
                "conflict_reason": None,
                "observation_ids": list(self.observation_ids[:2]),
                "rule_version": "semantic-integration-v1",
            },
        )
        block_candidate_relation = RelationCandidate(
            start_id=self.block_id,
            end_id=self.cross_section_id,
            relation_spec="candidate_section_mark",
            relation_type="CANDIDATE_HAS_SECTION_MARK",
            relation_batch_id=f"semantic-batch:{self.project_slug}",
            rule_version="semantic-integration-v1",
            link_rule="section_mark_geometry_v1",
            properties={
                "status": "candidate",
                "candidate_count": 1,
                "score": 0.91,
                "overlap_area": 100.0,
                "overlap_ratio": 0.5,
                "containment_status": "overlap",
                "conflict_reason": "semantic integration candidate",
                "observation_ids": list(self.observation_ids[:2]),
                "rule_version": "semantic-integration-v1",
            },
        )
        formal_relation = RelationCandidate(
            start_id=self.cross_section_id,
            end_id=self.caption_id,
            relation_spec="matches_section_caption",
            relation_type="MATCHES_SECTION_CAPTION",
            relation_batch_id=f"semantic-batch:{self.project_slug}",
            rule_version="semantic-integration-v1",
            link_rule="section_match_v1",
            properties={
                "confirmation_method": "deterministic_rule",
                "rule_version": "semantic-integration-v1",
                "observation_ids": list(self.observation_ids[:2]),
            },
        )

        for _ in range(2):
            semantic_repository.save_observations(observations)
            semantic_repository.save_interpretations(interpretations)
            relation_repository.write_relations((candidate_relation, block_candidate_relation, formal_relation))

        self.assertEqual(
            {
                "text_observation_count": 3,
                "has_observation_count": 3,
                "block_interpretation_count": 1,
                "basic_info_interpretation_count": 1,
                "table_interpretation_count": 1,
                "has_interpretation_count": 3,
                "supported_by_count": 1,
                "candidate_match_count": 1,
                "formal_match_count": 1,
                "recognition_run_node_count": 0,
            },
            self._semantic_counts(),
        )
        repository_observations = semantic_repository.find_by_page(self.page_id)
        self.assertEqual(set(self.observation_ids), {item.observation_id for item in repository_observations})
        repository_interpretations = semantic_repository.find_interpretations(
            element_id=self.block_id,
            statuses=("partial",),
        )
        self.assertEqual((self.interpretation_ids[0],), tuple(item.interpretation_id for item in repository_interpretations))
        self.assertEqual(
            {
                "recognition_run_id": f"run:{self.project_slug}:recognition",
                "raw_text": "A",
                "normalized_text": "A",
                "status": "confirmed",
                "target_element_type": "CrossSection",
            },
            self._cross_section_observation_projection(),
        )
        self.assertEqual(
            {
                "summary": "Beam section detail with partial internal text.",
                "analysis_status": "partial",
                "interpreted_type": "section_detail",
                "supported_observation_id": self.observation_ids[2],
            },
            self._block_interpretation_projection(),
        )
        self.assertEqual(
            {
                "candidate_status": "candidate",
                "candidate_count": 1,
                "candidate_observation_ids": list(self.observation_ids[:2]),
                "confirmation_method": "deterministic_rule",
                "formal_observation_ids": list(self.observation_ids[:2]),
            },
            self._section_match_projection(),
        )
        facade = create_neo4j_tool_facade(self.driver)
        candidate_summaries = facade.list_candidate_relations(
            block_id=self.block_id,
            relation_type="candidate_section_mark",
            status="candidate",
        )
        self.assertEqual((self.block_id,), tuple(item.block_id for item in candidate_summaries))
        self.assertEqual(("candidate_section_mark",), tuple(item.relation_type for item in candidate_summaries))
        section_matches = facade.list_section_matches(
            cross_section_id=self.cross_section_id,
            statuses=("candidate", "confirmed"),
        )
        self.assertEqual(
            ("candidate_relation", "formal_relation"),
            tuple(item.fact_kind for item in section_matches),
        )

    def _run_schema(self):
        statements = _schema_statements(PROJECT_ROOT / "scripts" / "create_schema.cypher")
        with self.driver.session() as session:
            for statement in statements:
                session.execute_write(lambda transaction, cypher=statement: transaction.run(cypher).consume())

    def _create_source_graph(self):
        with self.driver.session() as session:
            session.execute_write(lambda transaction: _create_source_graph(transaction, self))

    def _semantic_counts(self):
        with self.driver.session() as session:
            return session.execute_read(lambda transaction: _semantic_counts(transaction, self))

    def _cross_section_observation_projection(self):
        with self.driver.session() as session:
            return session.execute_read(lambda transaction: _cross_section_observation_projection(transaction, self))

    def _block_interpretation_projection(self):
        with self.driver.session() as session:
            return session.execute_read(lambda transaction: _block_interpretation_projection(transaction, self))

    def _section_match_projection(self):
        with self.driver.session() as session:
            return session.execute_read(lambda transaction: _section_match_projection(transaction, self))

    def _cleanup_test_data(self):
        with self.driver.session() as session:
            session.execute_write(lambda transaction: _cleanup_test_data(transaction, self.project_slug))


def _schema_statements(schema_path):
    text = schema_path.read_text(encoding="utf-8")
    return tuple(statement.strip() for statement in text.split(";") if statement.strip())


def _create_source_graph(transaction, test_case):
    bbox = [10.0, 10.0, 80.0, 90.0]
    transaction.run(
        """
        MERGE (project:Project {id: $project_id})
        MERGE (drawing_set:DrawingSet {id: $drawing_set_id})
        MERGE (page:DrawingPage {id: $page_id})
        SET page.page_number = 1,
            page.file_name = 'road_1.json',
            page.image_path = 'tests/fixtures/road_1.png'
        MERGE (project)-[:HAS_SET]->(drawing_set)
        MERGE (drawing_set)-[:HAS_PAGE]->(page)
        MERGE (block:DrawingBlock {id: $block_id})
        SET block.bbox = $bbox
        MERGE (cross_section:CrossSection {id: $cross_section_id})
        SET cross_section.bbox = $bbox
        MERGE (caption:BlockCaption {id: $caption_id})
        SET caption.bbox = $bbox
        MERGE (basic_info:DrawingBasicInfo {id: $basic_info_id})
        SET basic_info.bbox = $bbox
        MERGE (table:Table {id: $table_id})
        SET table.bbox = $bbox
        MERGE (page)-[:HAS_BLOCK]->(block)
        MERGE (page)-[:HAS_ELEMENT]->(cross_section)
        MERGE (page)-[:HAS_ELEMENT]->(caption)
        MERGE (page)-[:HAS_BASIC_INFO]->(basic_info)
        MERGE (page)-[:HAS_TABLE]->(table)
        """,
        project_id=test_case.project_id,
        drawing_set_id=test_case.drawing_set_id,
        page_id=test_case.page_id,
        block_id=test_case.block_id,
        cross_section_id=test_case.cross_section_id,
        caption_id=test_case.caption_id,
        basic_info_id=test_case.basic_info_id,
        table_id=test_case.table_id,
        bbox=bbox,
    ).consume()


def _semantic_counts(transaction, test_case):
    observation_prefix = f"observation:{test_case.project_slug}:"
    interpretation_prefix = f"interpretation:{test_case.project_slug}:"
    run_prefix = f"run:{test_case.project_slug}:"

    def count(cypher, **parameters):
        return transaction.run(cypher, **parameters).single()["count"]

    return {
        "text_observation_count": count(
            """
            MATCH (observation:TextObservation)
            WHERE observation.id STARTS WITH $observation_prefix
            RETURN count(DISTINCT observation) AS count
            """,
            observation_prefix=observation_prefix,
        ),
        "has_observation_count": count(
            """
            MATCH ()-[has_observation:HAS_OBSERVATION]->(observation:TextObservation)
            WHERE observation.id STARTS WITH $observation_prefix
            RETURN count(DISTINCT has_observation) AS count
            """,
            observation_prefix=observation_prefix,
        ),
        "block_interpretation_count": count(
            """
            MATCH (interpretation:BlockInterpretation)
            WHERE interpretation.id STARTS WITH $interpretation_prefix
            RETURN count(DISTINCT interpretation) AS count
            """,
            interpretation_prefix=interpretation_prefix,
        ),
        "basic_info_interpretation_count": count(
            """
            MATCH (interpretation:BasicInfoInterpretation)
            WHERE interpretation.id STARTS WITH $interpretation_prefix
            RETURN count(DISTINCT interpretation) AS count
            """,
            interpretation_prefix=interpretation_prefix,
        ),
        "table_interpretation_count": count(
            """
            MATCH (interpretation:TableInterpretation)
            WHERE interpretation.id STARTS WITH $interpretation_prefix
            RETURN count(DISTINCT interpretation) AS count
            """,
            interpretation_prefix=interpretation_prefix,
        ),
        "has_interpretation_count": count(
            """
            MATCH ()-[has_interpretation:HAS_INTERPRETATION]->(interpretation)
            WHERE interpretation.id STARTS WITH $interpretation_prefix
            RETURN count(DISTINCT has_interpretation) AS count
            """,
            interpretation_prefix=interpretation_prefix,
        ),
        "supported_by_count": count(
            """
            MATCH (interpretation)-[supported_by:SUPPORTED_BY]->(:TextObservation)
            WHERE interpretation.id STARTS WITH $interpretation_prefix
            RETURN count(DISTINCT supported_by) AS count
            """,
            interpretation_prefix=interpretation_prefix,
        ),
        "candidate_match_count": count(
            """
            MATCH (:CrossSection {id: $cross_section_id})-[candidate:CANDIDATE_MATCHES_SECTION_CAPTION]->(:BlockCaption {id: $caption_id})
            RETURN count(DISTINCT candidate) AS count
            """,
            cross_section_id=test_case.cross_section_id,
            caption_id=test_case.caption_id,
        ),
        "formal_match_count": count(
            """
            MATCH (:CrossSection {id: $cross_section_id})-[formal:MATCHES_SECTION_CAPTION]->(:BlockCaption {id: $caption_id})
            RETURN count(DISTINCT formal) AS count
            """,
            cross_section_id=test_case.cross_section_id,
            caption_id=test_case.caption_id,
        ),
        "recognition_run_node_count": count(
            """
            MATCH (run)
            WHERE run.id STARTS WITH $run_prefix AND 'RecognitionRun' IN labels(run)
            RETURN count(DISTINCT run) AS count
            """,
            run_prefix=run_prefix,
        ),
    }


def _cross_section_observation_projection(transaction, test_case):
    result = transaction.run(
        """
        MATCH (:CrossSection {id: $cross_section_id})-[:HAS_OBSERVATION]->(observation:TextObservation {id: $observation_id})
        RETURN observation.recognition_run_id AS recognition_run_id,
               observation.raw_text AS raw_text,
               observation.normalized_text AS normalized_text,
               observation.status AS status,
               observation.target_element_type AS target_element_type
        """,
        cross_section_id=test_case.cross_section_id,
        observation_id=test_case.observation_ids[0],
    )
    record = result.single()
    return {
        "recognition_run_id": record["recognition_run_id"],
        "raw_text": record["raw_text"],
        "normalized_text": record["normalized_text"],
        "status": record["status"],
        "target_element_type": record["target_element_type"],
    }


def _block_interpretation_projection(transaction, test_case):
    result = transaction.run(
        """
        MATCH (:DrawingBlock {id: $block_id})-[:HAS_INTERPRETATION]->(interpretation:BlockInterpretation {id: $interpretation_id})
        OPTIONAL MATCH (interpretation)-[:SUPPORTED_BY]->(observation:TextObservation)
        RETURN interpretation.summary AS summary,
               interpretation.analysis_status AS analysis_status,
               interpretation.interpreted_type AS interpreted_type,
               observation.id AS supported_observation_id
        """,
        block_id=test_case.block_id,
        interpretation_id=test_case.interpretation_ids[0],
    )
    record = result.single()
    return {
        "summary": record["summary"],
        "analysis_status": record["analysis_status"],
        "interpreted_type": record["interpreted_type"],
        "supported_observation_id": record["supported_observation_id"],
    }


def _section_match_projection(transaction, test_case):
    result = transaction.run(
        """
        MATCH (:CrossSection {id: $cross_section_id})-[candidate:CANDIDATE_MATCHES_SECTION_CAPTION]->(:BlockCaption {id: $caption_id})
        MATCH (:CrossSection {id: $cross_section_id})-[formal:MATCHES_SECTION_CAPTION]->(:BlockCaption {id: $caption_id})
        RETURN candidate.status AS candidate_status,
               candidate.candidate_count AS candidate_count,
               candidate.observation_ids AS candidate_observation_ids,
               formal.confirmation_method AS confirmation_method,
               formal.observation_ids AS formal_observation_ids
        """,
        cross_section_id=test_case.cross_section_id,
        caption_id=test_case.caption_id,
    )
    record = result.single()
    return {
        "candidate_status": record["candidate_status"],
        "candidate_count": record["candidate_count"],
        "candidate_observation_ids": record["candidate_observation_ids"],
        "confirmation_method": record["confirmation_method"],
        "formal_observation_ids": record["formal_observation_ids"],
    }


def _cleanup_test_data(transaction, project_slug):
    transaction.run(
        """
        MATCH (node)
        WHERE node.id STARTS WITH $project_prefix
           OR node.id STARTS WITH $set_prefix
           OR node.id STARTS WITH $page_prefix
           OR node.id STARTS WITH $block_prefix
           OR node.id STARTS WITH $element_prefix
           OR node.id STARTS WITH $observation_prefix
           OR node.id STARTS WITH $interpretation_prefix
        DETACH DELETE node
        """,
        project_prefix=f"project:{project_slug}",
        set_prefix=f"set:{project_slug}:",
        page_prefix=f"page:{project_slug}:",
        block_prefix=f"block:{project_slug}:",
        element_prefix=f"element:{project_slug}:",
        observation_prefix=f"observation:{project_slug}:",
        interpretation_prefix=f"interpretation:{project_slug}:",
    ).consume()


if __name__ == "__main__":
    unittest.main()
