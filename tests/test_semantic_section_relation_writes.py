import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.block_relation_enrichment import RelationCandidate
from drawing_graph.relation_repository import RELATION_END_LABELS, RELATION_SPECS, RelationRepository


class FakeTransaction:
    def __init__(self):
        self.calls = []

    def run(self, cypher, **parameters):
        self.calls.append((cypher, parameters))
        return []


class FakeSession:
    def __init__(self):
        self.transaction = FakeTransaction()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute_write(self, callback):
        return callback(self.transaction)


class FakeDriver:
    def __init__(self):
        self.sessions = []

    def session(self):
        session = FakeSession()
        self.sessions.append(session)
        return session


def relation(
    relation_spec,
    relation_type,
    start_id="cross-section:1",
    end_id="caption:1",
    **properties,
):
    return RelationCandidate(
        start_id=start_id,
        end_id=end_id,
        relation_spec=relation_spec,
        relation_type=relation_type,
        relation_batch_id="semantic-batch:1",
        rule_version=properties.pop("rule_version", "match-v1"),
        link_rule=properties.pop("link_rule", "section_match_v1"),
        properties=properties,
    )


def candidate_properties(**overrides):
    properties = {
        "status": "candidate",
        "candidate_group_id": "group:1",
        "candidate_count": 2,
        "score": 0.8,
        "conflict_reason": "multiple same-key captions",
        "observation_ids": ["obs:1", "obs:2"],
        "rule_version": "match-v1",
    }
    properties.update(overrides)
    return properties


class SemanticSectionRelationWritesTest(unittest.TestCase):
    def test_specs_whitelist_candidate_and_formal_section_caption_relations(self):
        candidate_spec = RELATION_SPECS["candidate_matches_section_caption"]
        formal_spec = RELATION_SPECS["matches_section_caption"]

        self.assertEqual("CrossSection", candidate_spec["start_label"])
        self.assertEqual("CANDIDATE_MATCHES_SECTION_CAPTION", candidate_spec["relation_type"])
        self.assertEqual("BlockCaption", candidate_spec["end_label"])
        self.assertEqual("CrossSection", formal_spec["start_label"])
        self.assertEqual("MATCHES_SECTION_CAPTION", formal_spec["relation_type"])
        self.assertEqual("BlockCaption", formal_spec["end_label"])
        self.assertEqual("BlockCaption", RELATION_END_LABELS["CANDIDATE_MATCHES_SECTION_CAPTION"])
        self.assertEqual("BlockCaption", RELATION_END_LABELS["MATCHES_SECTION_CAPTION"])

    def test_writes_candidate_matches_section_caption_with_parameters(self):
        driver = FakeDriver()
        repository = RelationRepository(driver)

        repository.write_relations(
            (
                relation(
                    "candidate_matches_section_caption",
                    "CANDIDATE_MATCHES_SECTION_CAPTION",
                    **candidate_properties(),
                ),
            )
        )

        cypher, parameters = driver.sessions[0].transaction.calls[0]
        self.assertIn("MATCH (start:CrossSection {id: relation.start_id})", cypher)
        self.assertIn("MATCH (end:BlockCaption {id: relation.end_id})", cypher)
        self.assertIn(
            "MERGE (start)-[r:CANDIDATE_MATCHES_SECTION_CAPTION {rule_version: relation.properties.rule_version}]->(end)",
            cypher,
        )
        self.assertNotIn("cross-section:1", cypher)
        self.assertNotIn("caption:1", cypher)
        self.assertNotIn("id(start)", cypher)
        self.assertNotIn("elementId", cypher)
        payload = parameters["relations"][0]
        self.assertEqual("cross-section:1", payload["start_id"])
        self.assertEqual("caption:1", payload["end_id"])
        self.assertEqual("group:1", payload["properties"]["candidate_group_id"])
        self.assertEqual(["obs:1", "obs:2"], payload["properties"]["observation_ids"])

    def test_writes_formal_matches_section_caption_with_parameters(self):
        driver = FakeDriver()
        repository = RelationRepository(driver)

        repository.write_relations(
            (
                relation(
                    "matches_section_caption",
                    "MATCHES_SECTION_CAPTION",
                    confirmation_method="deterministic_rule",
                    observation_ids=["obs:1", "obs:2"],
                ),
            )
        )

        cypher, parameters = driver.sessions[0].transaction.calls[0]
        self.assertIn("MATCH (start:CrossSection {id: relation.start_id})", cypher)
        self.assertIn("MATCH (end:BlockCaption {id: relation.end_id})", cypher)
        self.assertIn(
            "MERGE (start)-[r:MATCHES_SECTION_CAPTION {rule_version: relation.properties.rule_version}]->(end)",
            cypher,
        )
        self.assertEqual("deterministic_rule", parameters["relations"][0]["properties"]["confirmation_method"])
        self.assertEqual("match-v1", parameters["relations"][0]["properties"]["rule_version"])

    def test_updates_candidate_review_for_section_caption_candidate(self):
        driver = FakeDriver()
        repository = RelationRepository(driver)

        repository.update_candidate_review(
            relation_spec="candidate_matches_section_caption",
            start_id="cross-section:1",
            end_id="caption:1",
            rule_version="match-v1",
            review_status="accepted",
            review_run_id="review-run:1",
        )

        cypher, parameters = driver.sessions[0].transaction.calls[0]
        self.assertIn("MATCH (start:CrossSection {id: $start_id})", cypher)
        self.assertIn("MATCH (end:BlockCaption {id: $end_id})", cypher)
        self.assertIn("MATCH (start)-[r:CANDIDATE_MATCHES_SECTION_CAPTION {rule_version: $rule_version}]->(end)", cypher)
        self.assertEqual("accepted", parameters["properties"]["review_status"])

    def test_promotes_accepted_section_caption_candidate_to_formal_relation(self):
        driver = FakeDriver()
        repository = RelationRepository(driver)

        repository.promote_candidate_relation(
            relation_spec="candidate_matches_section_caption",
            candidate_start_id="cross-section:1",
            candidate_end_id="caption:1",
            candidate_rule_version="match-v1",
            review_status="accepted",
            review_run_id="review-run:1",
            formal_rule_version="match-v2",
            confirmation_method="deterministic_rule",
        )

        cypher, parameters = driver.sessions[0].transaction.calls[0]
        self.assertIn("MATCH (candidate_start:CrossSection {id: $candidate_start_id})", cypher)
        self.assertIn("MATCH (candidate_end:BlockCaption {id: $candidate_end_id})", cypher)
        self.assertIn(
            "MATCH (candidate_start)-[candidate:CANDIDATE_MATCHES_SECTION_CAPTION "
            "{rule_version: $candidate_rule_version, review_status: 'accepted'}]->(candidate_end)",
            cypher,
        )
        self.assertIn(
            "MERGE (candidate_start)-[formal:MATCHES_SECTION_CAPTION {rule_version: $formal_rule_version}]->(candidate_end)",
            cypher,
        )
        self.assertEqual("match-v2", parameters["formal_rule_version"])
        self.assertEqual("deterministic_rule", parameters["formal_properties"]["confirmation_method"])

    def test_rejects_uncontrolled_relation_type_before_query_runs(self):
        from drawing_graph.relation_repository import RelationRepositoryError

        driver = FakeDriver()
        repository = RelationRepository(driver)

        with self.assertRaises(RelationRepositoryError):
            repository.write_relations(
                (relation("candidate_matches_section_caption", "HAS_CAPTION", **candidate_properties()),)
            )

        self.assertEqual([], driver.sessions)


if __name__ == "__main__":
    unittest.main()
