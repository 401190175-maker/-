"""Tests for scope resolution, merging, and reference resolution."""

import unittest

from drawing_graph.assistant_models import AssistantScope
from drawing_graph.assistant_scope_resolution import ScopeResolver


class ScopeResolverExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.resolver = ScopeResolver()

    def test_extracts_page_id_from_question_text(self):
        result = self.resolver.resolve("page:1 的主要图块有哪些")
        self.assertEqual("page:1", result.scope.page_id)
        self.assertIn("question_text", result.scope_sources)

    def test_extracts_all_stable_business_id_prefixes(self):
        result = self.resolver.resolve(
            "请查看 page:1 block:2 element:3 cross_section:4 "
            "table:5 table_caption:6 claim:7"
        )
        self.assertEqual("page:1", result.scope.page_id)
        self.assertEqual("block:2", result.scope.block_id)
        self.assertEqual("element:3", result.scope.element_id)
        self.assertEqual("cross_section:4", result.scope.cross_section_id)
        self.assertEqual("table:5", result.scope.table_id)
        self.assertEqual("table_caption:6", result.scope.table_caption_id)
        self.assertEqual("claim:7", result.scope.claim_id)

    def test_extracted_ids_are_recorded_by_scope_field(self):
        result = self.resolver.resolve("page:1 的图块")
        self.assertEqual({"page_id": "page:1"}, dict(result.extracted_ids))

    def test_question_without_scope_returns_empty_result(self):
        result = self.resolver.resolve("这张图主要讲什么")
        self.assertIsNone(result.scope)
        self.assertEqual({}, dict(result.extracted_ids))

    def test_rejects_cypher_snippet_as_scope(self):
        result = self.resolver.resolve(
            "MATCH (b:Block) WHERE b.page_id = 'page:1' RETURN b"
        )
        self.assertIsNone(result.scope)

    def test_rejects_driver_uri_and_file_path_as_scope(self):
        result = self.resolver.resolve(
            "连接 neo4j://localhost:7687 并读取 C:\\Users\\1.json"
        )
        self.assertIsNone(result.scope)


class ScopeHintMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.resolver = ScopeResolver()

    def test_scope_hint_and_text_id_merge_when_consistent(self):
        hint = AssistantScope(page_id="page:1", project_id="project:1")
        result = self.resolver.resolve("page:1 的图块有哪些", scope_hint=hint)
        self.assertEqual("page:1", result.scope.page_id)
        self.assertEqual("project:1", result.scope.project_id)
        self.assertIn("question_text", result.scope_sources)
        self.assertIn("scope_hint", result.scope_sources)

    def test_conflicting_page_ids_return_scope_conflict_without_silent_choice(self):
        hint = AssistantScope(page_id="page:1")
        result = self.resolver.resolve("page:2 的图块", scope_hint=hint)
        self.assertIn("scope_conflict", result.conflicts)
        self.assertIsNone(result.scope)

    def test_scope_hint_alone_is_used_when_text_has_no_id(self):
        hint = AssistantScope(page_id="page:9", block_id="block:9")
        result = self.resolver.resolve("这个图块是什么", scope_hint=hint)
        self.assertEqual("page:9", result.scope.page_id)
        self.assertEqual("block:9", result.scope.block_id)
        self.assertIn("scope_hint", result.scope_sources)

    def test_non_conflicting_hint_fields_survive_text_conflict(self):
        hint = AssistantScope(page_id="page:1", block_id="block:1")
        result = self.resolver.resolve("page:2 的图块", scope_hint=hint)
        self.assertIn("scope_conflict", result.conflicts)
        self.assertIsNone(result.scope.page_id)
        self.assertEqual("block:1", result.scope.block_id)


class ConversationReferenceResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.resolver = ScopeResolver()

    def test_this_page_resolves_when_context_has_single_page(self):
        context = "上一轮讨论了 page:1 的图块"
        result = self.resolver.resolve("这张图主要讲什么", conversation_context=context)
        self.assertEqual("page:1", result.scope.page_id)
        self.assertIn("conversation_context", result.scope_sources)

    def test_this_block_resolves_when_context_has_single_block(self):
        context = "上一轮讨论了 block:7 的关系"
        result = self.resolver.resolve("这个图块是什么构件", conversation_context=context)
        self.assertEqual("block:7", result.scope.block_id)
        self.assertIn("conversation_context", result.scope_sources)

    def test_multiple_context_candidates_return_ambiguous_reference(self):
        context = "先看 block:1，再看 block:2"
        result = self.resolver.resolve("这个图块是什么构件", conversation_context=context)
        self.assertIn("ambiguous_reference", result.ambiguities)
        self.assertIsNone(result.scope)

    def test_explicit_text_id_is_not_overridden_by_context(self):
        context = "上一轮讨论了 page:1 的图块"
        result = self.resolver.resolve("page:9 这张图的关系", conversation_context=context)
        self.assertEqual("page:9", result.scope.page_id)
        self.assertNotEqual("page:1", result.scope.page_id)

    def test_context_does_not_override_scope_hint(self):
        context = "上一轮讨论了 page:1 的图块"
        hint = AssistantScope(page_id="page:3")
        result = self.resolver.resolve(
            "这张图的关系",
            scope_hint=hint,
            conversation_context=context,
        )
        self.assertEqual("page:3", result.scope.page_id)


if __name__ == "__main__":
    unittest.main()
