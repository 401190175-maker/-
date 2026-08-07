import sys
import unittest
from pathlib import Path
from types import MappingProxyType

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawing_graph.semantic_payload_store import InMemorySemanticPayloadStore
from drawing_graph.tool_models import ToolModelError


class SemanticPayloadStoreTest(unittest.TestCase):
    def test_puts_and_gets_immutable_payload_by_ref(self):
        store = InMemorySemanticPayloadStore()

        payload_ref = store.put_payload({"summary": "wall", "items": [{"name": "A"}]}, "hash:1")
        stored = store.get_payload(payload_ref)

        self.assertTrue(payload_ref.startswith("payload:"))
        self.assertEqual("wall", stored["summary"])
        self.assertIsInstance(stored, MappingProxyType)
        self.assertEqual(("name",), tuple(stored["items"][0].keys()))

    def test_same_content_hash_reuses_same_payload_ref(self):
        store = InMemorySemanticPayloadStore()

        first_ref = store.put_payload({"summary": "wall"}, "hash:same")
        second_ref = store.put_payload({"summary": "wall"}, "hash:same")

        self.assertEqual(first_ref, second_ref)

    def test_missing_payload_returns_stable_not_found(self):
        store = InMemorySemanticPayloadStore()

        with self.assertRaises(ToolModelError) as error:
            store.get_payload("payload:missing")

        self.assertEqual("NOT_FOUND", error.exception.category)

    def test_stored_payload_is_isolated_from_caller_mutation(self):
        store = InMemorySemanticPayloadStore()
        source = {"summary": "wall", "items": [{"name": "A"}]}
        payload_ref = store.put_payload(source, "hash:1")

        source["summary"] = "changed"
        source["items"][0]["name"] = "changed"

        stored = store.get_payload(payload_ref)
        self.assertEqual("wall", stored["summary"])
        self.assertEqual("A", stored["items"][0]["name"])

    def test_rejects_invalid_payload_and_content_hash(self):
        store = InMemorySemanticPayloadStore()

        with self.assertRaises(ToolModelError):
            store.put_payload([1, 2, 3], "hash:1")
        with self.assertRaises(ToolModelError):
            store.put_payload({"summary": "wall"}, "")
        with self.assertRaises(ToolModelError):
            store.get_payload("")


if __name__ == "__main__":
    unittest.main()
