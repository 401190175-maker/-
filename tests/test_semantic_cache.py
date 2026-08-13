import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.semantic_cache import (
    SemanticCacheKeyInput,
    build_section_match_cache_key,
    build_semantic_cache_key,
)
from drawing_graph.tool_models import BBox, ToolModelError


def cache_inputs(**overrides):
    values = {
        "image_hash": "image-hash:1",
        "bbox": (0.1, 0.2, 0.3, 0.4),
        "target_element_id": "block:1",
        "task_type": "text_observation",
        "model_profile": "vision-v1",
        "model_version": "1.2.0",
        "prompt_version": "prompt-v1",
        "preprocessing_version": "preprocess-v1",
        "normalization_rule_version": "normalize-v1",
        "contract_version": "1",
    }
    values.update(overrides)
    return SemanticCacheKeyInput(**values)


class SemanticCacheTest(unittest.TestCase):
    def test_same_input_generates_same_key(self):
        first = build_semantic_cache_key(cache_inputs())
        second = build_semantic_cache_key(cache_inputs())

        self.assertEqual(first, second)
        self.assertTrue(first.startswith("semantic:"))

    def test_any_component_change_generates_different_key(self):
        base = cache_inputs()
        base_key = build_semantic_cache_key(base)

        for field_name in (
            "image_hash",
            "target_element_id",
            "task_type",
            "model_profile",
            "model_version",
            "prompt_version",
            "preprocessing_version",
            "normalization_rule_version",
            "contract_version",
        ):
            changed = build_semantic_cache_key(cache_inputs(**{field_name: getattr(base, field_name) + "-changed"}))
            with self.subTest(field_name=field_name):
                self.assertNotEqual(base_key, changed)

        bbox_changed = build_semantic_cache_key(cache_inputs(bbox=(0.11, 0.2, 0.3, 0.4)))
        self.assertNotEqual(base_key, bbox_changed)

    def test_bbox_instance_and_tuple_normalize_to_same_key(self):
        tuple_key = build_semantic_cache_key(cache_inputs())
        bbox_key = build_semantic_cache_key(cache_inputs(bbox=BBox(0.1, 0.2, 0.3, 0.4)))

        self.assertEqual(tuple_key, bbox_key)

    def test_observation_key_never_includes_alias_rule_version(self):
        parameters = inspect.signature(build_semantic_cache_key).parameters

        self.assertNotIn("alias_rule_version", parameters)
        self.assertNotIn("alias", repr(build_semantic_cache_key(cache_inputs())))

    def test_section_match_key_includes_alias_rule_version(self):
        base = build_section_match_cache_key(
            observation_keys=("obs:1", "obs:2"),
            candidate_scope="page:1",
            match_rule_version="match-v1",
            alias_rule_version="alias-v1",
        )
        without_alias = build_section_match_cache_key(
            observation_keys=("obs:1", "obs:2"),
            candidate_scope="page:1",
            match_rule_version="match-v1",
        )
        different_alias = build_section_match_cache_key(
            observation_keys=("obs:1", "obs:2"),
            candidate_scope="page:1",
            match_rule_version="match-v1",
            alias_rule_version="alias-v2",
        )
        different_scope = build_section_match_cache_key(
            observation_keys=("obs:1", "obs:2"),
            candidate_scope="page:2",
            match_rule_version="match-v1",
            alias_rule_version="alias-v1",
        )

        self.assertNotEqual(base, without_alias)
        self.assertNotEqual(base, different_alias)
        self.assertNotEqual(base, different_scope)
        self.assertEqual(base, build_section_match_cache_key(
            observation_keys=("obs:1", "obs:2"),
            candidate_scope="page:1",
            match_rule_version="match-v1",
            alias_rule_version="alias-v1",
        ))

    def test_rejects_invalid_bbox_and_missing_components(self):
        with self.assertRaises(ToolModelError):
            cache_inputs(bbox=(0.3, 0.2, 0.1, 0.4))
        with self.assertRaises(ToolModelError):
            cache_inputs(target_element_id="")
        with self.assertRaises(ToolModelError):
            build_section_match_cache_key(observation_keys="obs:1", candidate_scope="page:1", match_rule_version="v1")

    def test_execution_task_and_contract_versions_participate_in_cache_identity(self):
        base = build_semantic_cache_key(cache_inputs(task_type="element_text_observation"))
        changed_contract = build_semantic_cache_key(
            cache_inputs(task_type="element_text_observation", contract_version="2")
        )
        changed_preprocessing = build_semantic_cache_key(
            cache_inputs(task_type="element_text_observation", preprocessing_version="preprocess-v2")
        )

        self.assertTrue(base.startswith("semantic:"))
        self.assertNotEqual(base, changed_contract)
        self.assertNotEqual(base, changed_preprocessing)


if __name__ == "__main__":
    unittest.main()
