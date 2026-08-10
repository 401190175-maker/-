import unittest


class McpInputCommonTests(unittest.TestCase):
    """Common narrow-scope input rules shared by all MCP tool models."""

    def test_language_default_and_allowed_values(self):
        from drawing_graph.qa_mcp_models import (
            MCP_ALLOWED_LANGUAGES,
            MCP_DEFAULT_LANGUAGE,
            normalize_language,
        )

        self.assertEqual("zh", MCP_DEFAULT_LANGUAGE)
        self.assertEqual({"zh", "en"}, set(MCP_ALLOWED_LANGUAGES))
        self.assertEqual("zh", normalize_language(None))
        self.assertEqual("zh", normalize_language("zh"))
        self.assertEqual("en", normalize_language("en"))

    def test_unsupported_language_is_rejected(self):
        from drawing_graph.qa_mcp_models import McpInputError, normalize_language

        for value in ("fr", "EN", "", "  "):
            with self.assertRaises(McpInputError):
                normalize_language(value)

    def test_scope_id_is_stripped(self):
        from drawing_graph.qa_mcp_models import normalize_scope_id

        self.assertEqual("page:1", normalize_scope_id("  page:1  ", "page_id"))

    def test_missing_or_blank_scope_id_is_rejected(self):
        from drawing_graph.qa_mcp_models import McpInputError, normalize_scope_id

        for value in (None, "", "   "):
            with self.assertRaises(McpInputError) as context:
                normalize_scope_id(value, "page_id")
            self.assertIn("page_id", str(context.exception))

    def test_scope_id_length_limit_is_enforced(self):
        from drawing_graph.qa_mcp_models import MAX_SCOPE_ID_LENGTH, McpInputError, normalize_scope_id

        self.assertEqual(512, MAX_SCOPE_ID_LENGTH)
        valid = "x" * MAX_SCOPE_ID_LENGTH
        self.assertEqual(valid, normalize_scope_id(valid, "page_id"))

        with self.assertRaises(McpInputError) as context:
            normalize_scope_id("x" * (MAX_SCOPE_ID_LENGTH + 1), "page_id")
        self.assertIn(str(MAX_SCOPE_ID_LENGTH), str(context.exception))

    def test_validation_error_does_not_echo_input_value(self):
        from drawing_graph.qa_mcp_models import McpInputError, normalize_scope_id

        sentinel = "secret-input-value-xyz"
        with self.assertRaises(McpInputError) as context:
            normalize_scope_id(sentinel + ("x" * 600), "page_id")
        self.assertNotIn(sentinel, str(context.exception))

    def test_input_model_base_forbids_extra_fields(self):
        from drawing_graph.qa_mcp_models import McpInputModel

        self.assertEqual("forbid", McpInputModel.model_config.get("extra"))

    def test_common_contract_excludes_forbidden_fields(self):
        import drawing_graph.qa_mcp_models as module

        public_names = {name for name in dir(module) if not name.startswith("_")}
        for forbidden in (
            "write_back",
            "include_payload",
            "cypher",
            "credential",
            "password",
            "driver",
            "session",
            "transaction",
            "repository",
            "path",
        ):
            self.assertFalse(
                any(forbidden in name.lower() for name in public_names),
                f"public MCP input contract exposes forbidden name containing {forbidden}",
            )


class AskDrawingPageInputTests(unittest.TestCase):
    """AskDrawingPageInput must map narrowly to a read-only page_summary request."""

    def test_defaults_produce_read_only_page_summary_request(self):
        from drawing_graph.qa_mcp_models import AskDrawingPageInput
        from drawing_graph.qa_models import QuestionType

        tool_input = AskDrawingPageInput(page_id="page:road:24")
        request = tool_input.to_qa_request()

        self.assertEqual(QuestionType.PAGE_SUMMARY, request.question_type)
        self.assertEqual("page:road:24", request.scope.page_id)
        self.assertIsNone(request.scope.block_id)
        self.assertIsNone(request.scope.cross_section_id)
        self.assertFalse(request.write_back)
        self.assertFalse(request.include_payload)
        self.assertTrue(request.include_semantics)
        self.assertEqual("zh", request.language)

    def test_custom_language_and_include_semantics_are_preserved(self):
        from drawing_graph.qa_mcp_models import AskDrawingPageInput

        tool_input = AskDrawingPageInput(
            page_id="page:road:24",
            language="en",
            include_semantics=False,
        )
        request = tool_input.to_qa_request()

        self.assertEqual("en", request.language)
        self.assertFalse(request.include_semantics)
        self.assertEqual("page:road:24", request.scope.page_id)

    def test_blank_or_too_long_page_id_is_rejected(self):
        from drawing_graph.qa_mcp_models import AskDrawingPageInput
        from pydantic import ValidationError

        for page_id in ("", "   ", "x" * 513):
            with self.assertRaises(ValidationError):
                AskDrawingPageInput(page_id=page_id)

    def test_invalid_language_is_rejected(self):
        from drawing_graph.qa_mcp_models import AskDrawingPageInput
        from pydantic import ValidationError

        with self.assertRaises(ValidationError) as context:
            AskDrawingPageInput(page_id="page:1", language="fr")
        self.assertIn("language", str(context.exception))

    def test_write_back_and_payload_fields_are_rejected(self):
        from drawing_graph.qa_mcp_models import AskDrawingPageInput
        from pydantic import ValidationError

        for extra in ({"write_back": True}, {"include_payload": True}, {"question_type": "page_summary"}):
            with self.assertRaises(ValidationError):
                AskDrawingPageInput(page_id="page:1", **extra)

    def test_extra_field_error_does_not_echo_unrelated_input(self):
        from drawing_graph.qa_mcp_models import AskDrawingPageInput
        from pydantic import ValidationError

        sentinel = "page-id-not-to-be-echoed"
        with self.assertRaises(ValidationError) as context:
            AskDrawingPageInput(page_id=sentinel, write_back=True)
        self.assertNotIn(sentinel, str(context.exception))

    def test_scope_does_not_carry_other_business_ids(self):
        from drawing_graph.qa_mcp_models import AskDrawingPageInput

        request = AskDrawingPageInput(page_id="page:1").to_qa_request()
        scope_ids = {
            name: value
            for name, value in (
                ("project_id", request.scope.project_id),
                ("drawing_set_id", request.scope.drawing_set_id),
                ("page_id", request.scope.page_id),
                ("block_id", request.scope.block_id),
                ("cross_section_id", request.scope.cross_section_id),
                ("table_id", request.scope.table_id),
                ("table_caption_id", request.scope.table_caption_id),
                ("element_id", request.scope.element_id),
            )
            if value is not None
        }
        self.assertEqual({"page_id": "page:1"}, scope_ids)


class AskDrawingBlockInputTests(unittest.TestCase):
    """AskDrawingBlockInput must map narrowly to a read-only block_relations request."""

    def test_defaults_produce_read_only_block_relations_request(self):
        from drawing_graph.qa_mcp_models import AskDrawingBlockInput
        from drawing_graph.qa_models import QuestionType

        tool_input = AskDrawingBlockInput(block_id="block:road:24:abc")
        request = tool_input.to_qa_request()

        self.assertEqual(QuestionType.BLOCK_RELATIONS, request.question_type)
        self.assertEqual("block:road:24:abc", request.scope.block_id)
        self.assertIsNone(request.scope.page_id)
        self.assertFalse(request.write_back)
        self.assertFalse(request.include_payload)
        self.assertTrue(request.include_candidates)
        self.assertEqual("zh", request.language)

    def test_custom_language_and_include_candidates_are_preserved(self):
        from drawing_graph.qa_mcp_models import AskDrawingBlockInput

        tool_input = AskDrawingBlockInput(
            block_id="block:road:24:abc",
            language="en",
            include_candidates=False,
        )
        request = tool_input.to_qa_request()

        self.assertEqual("en", request.language)
        self.assertFalse(request.include_candidates)
        self.assertEqual("block:road:24:abc", request.scope.block_id)

    def test_blank_or_too_long_block_id_is_rejected(self):
        from drawing_graph.qa_mcp_models import AskDrawingBlockInput
        from pydantic import ValidationError

        for block_id in ("", "   ", "x" * 513):
            with self.assertRaises(ValidationError):
                AskDrawingBlockInput(block_id=block_id)

    def test_invalid_language_is_rejected(self):
        from drawing_graph.qa_mcp_models import AskDrawingBlockInput
        from pydantic import ValidationError

        with self.assertRaises(ValidationError) as context:
            AskDrawingBlockInput(block_id="block:1", language="fr")
        self.assertIn("language", str(context.exception))

    def test_page_scope_and_arbitrary_question_type_are_rejected(self):
        from drawing_graph.qa_mcp_models import AskDrawingBlockInput
        from pydantic import ValidationError

        for extra in (
            {"page_id": "page:1"},
            {"question_type": "block_relations"},
            {"write_back": True},
            {"include_payload": True},
        ):
            with self.assertRaises(ValidationError):
                AskDrawingBlockInput(block_id="block:1", **extra)

    def test_extra_field_error_does_not_echo_unrelated_input(self):
        from drawing_graph.qa_mcp_models import AskDrawingBlockInput
        from pydantic import ValidationError

        sentinel = "block-id-not-to-be-echoed"
        with self.assertRaises(ValidationError) as context:
            AskDrawingBlockInput(block_id=sentinel, write_back=True)
        self.assertNotIn(sentinel, str(context.exception))

    def test_scope_does_not_carry_other_business_ids(self):
        from drawing_graph.qa_mcp_models import AskDrawingBlockInput

        request = AskDrawingBlockInput(block_id="block:1").to_qa_request()
        scope_ids = {
            name: value
            for name, value in (
                ("project_id", request.scope.project_id),
                ("drawing_set_id", request.scope.drawing_set_id),
                ("page_id", request.scope.page_id),
                ("block_id", request.scope.block_id),
                ("cross_section_id", request.scope.cross_section_id),
                ("table_id", request.scope.table_id),
                ("table_caption_id", request.scope.table_caption_id),
                ("element_id", request.scope.element_id),
            )
            if value is not None
        }
        self.assertEqual({"block_id": "block:1"}, scope_ids)


class ListDrawingCandidatesInputTests(unittest.TestCase):
    """ListDrawingCandidatesInput must require exactly one page or block scope."""

    def test_page_scope_produces_read_only_candidate_request(self):
        from drawing_graph.qa_mcp_models import ListDrawingCandidatesInput
        from drawing_graph.qa_models import QuestionType

        tool_input = ListDrawingCandidatesInput(page_id="page:road:24")
        request = tool_input.to_qa_request()

        self.assertEqual(QuestionType.CANDIDATE_RELATIONS, request.question_type)
        self.assertEqual("page:road:24", request.scope.page_id)
        self.assertIsNone(request.scope.block_id)
        self.assertFalse(request.write_back)
        self.assertFalse(request.include_payload)
        self.assertEqual("zh", request.language)

    def test_block_scope_produces_read_only_candidate_request(self):
        from drawing_graph.qa_mcp_models import ListDrawingCandidatesInput

        tool_input = ListDrawingCandidatesInput(block_id="block:road:24:abc", language="en")
        request = tool_input.to_qa_request()

        self.assertEqual("block:road:24:abc", request.scope.block_id)
        self.assertIsNone(request.scope.page_id)
        self.assertEqual("en", request.language)

    def test_exactly_one_scope_is_required(self):
        from drawing_graph.qa_mcp_models import ListDrawingCandidatesInput
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            ListDrawingCandidatesInput()
        with self.assertRaises(ValidationError):
            ListDrawingCandidatesInput(page_id="page:1", block_id="block:1")

    def test_blank_or_too_long_ids_are_rejected(self):
        from drawing_graph.qa_mcp_models import ListDrawingCandidatesInput
        from pydantic import ValidationError

        for page_id in ("", "   ", "x" * 513):
            with self.assertRaises(ValidationError):
                ListDrawingCandidatesInput(page_id=page_id)
        for block_id in ("", "   ", "x" * 513):
            with self.assertRaises(ValidationError):
                ListDrawingCandidatesInput(block_id=block_id)

    def test_invalid_language_is_rejected(self):
        from drawing_graph.qa_mcp_models import ListDrawingCandidatesInput
        from pydantic import ValidationError

        with self.assertRaises(ValidationError) as context:
            ListDrawingCandidatesInput(page_id="page:1", language="fr")
        self.assertIn("language", str(context.exception))

    def test_relation_status_review_and_write_back_fields_are_rejected(self):
        from drawing_graph.qa_mcp_models import ListDrawingCandidatesInput
        from pydantic import ValidationError

        for extra in (
            {"relation_type": "candidate_section_mark"},
            {"status": "candidate"},
            {"review_run_id": "review:1"},
            {"write_back": True},
            {"include_payload": True},
        ):
            with self.assertRaises(ValidationError):
                ListDrawingCandidatesInput(page_id="page:1", **extra)

    def test_extra_field_error_does_not_echo_unrelated_input(self):
        from drawing_graph.qa_mcp_models import ListDrawingCandidatesInput
        from pydantic import ValidationError

        sentinel = "candidate-page-id-not-to-be-echoed"
        with self.assertRaises(ValidationError) as context:
            ListDrawingCandidatesInput(page_id=sentinel, write_back=True)
        self.assertNotIn(sentinel, str(context.exception))

    def test_scope_carries_only_the_selected_id(self):
        from drawing_graph.qa_mcp_models import ListDrawingCandidatesInput

        request = ListDrawingCandidatesInput(page_id="page:1").to_qa_request()
        scope_ids = {
            name: value
            for name, value in (
                ("project_id", request.scope.project_id),
                ("drawing_set_id", request.scope.drawing_set_id),
                ("page_id", request.scope.page_id),
                ("block_id", request.scope.block_id),
                ("cross_section_id", request.scope.cross_section_id),
                ("table_id", request.scope.table_id),
                ("table_caption_id", request.scope.table_caption_id),
                ("element_id", request.scope.element_id),
            )
            if value is not None
        }
        self.assertEqual({"page_id": "page:1"}, scope_ids)


class GetSectionMatchStatusInputTests(unittest.TestCase):
    """GetSectionMatchStatusInput must require exactly one section or page scope."""

    def test_cross_section_scope_produces_read_only_section_request(self):
        from drawing_graph.qa_mcp_models import GetSectionMatchStatusInput
        from drawing_graph.qa_models import QuestionType

        tool_input = GetSectionMatchStatusInput(cross_section_id="element:road:24:cs1")
        request = tool_input.to_qa_request()

        self.assertEqual(QuestionType.SECTION_MATCHES, request.question_type)
        self.assertEqual("element:road:24:cs1", request.scope.cross_section_id)
        self.assertIsNone(request.scope.page_id)
        self.assertFalse(request.write_back)
        self.assertFalse(request.include_payload)
        self.assertEqual("zh", request.language)

    def test_page_scope_produces_read_only_section_request(self):
        from drawing_graph.qa_mcp_models import GetSectionMatchStatusInput

        tool_input = GetSectionMatchStatusInput(page_id="page:road:24", language="en")
        request = tool_input.to_qa_request()

        self.assertEqual("page:road:24", request.scope.page_id)
        self.assertIsNone(request.scope.cross_section_id)
        self.assertEqual("en", request.language)

    def test_exactly_one_scope_is_required(self):
        from drawing_graph.qa_mcp_models import GetSectionMatchStatusInput
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            GetSectionMatchStatusInput()
        with self.assertRaises(ValidationError):
            GetSectionMatchStatusInput(
                cross_section_id="element:1",
                page_id="page:1",
            )

    def test_blank_or_too_long_ids_are_rejected(self):
        from drawing_graph.qa_mcp_models import GetSectionMatchStatusInput
        from pydantic import ValidationError

        for cross_section_id in ("", "   ", "x" * 513):
            with self.assertRaises(ValidationError):
                GetSectionMatchStatusInput(cross_section_id=cross_section_id)
        for page_id in ("", "   ", "x" * 513):
            with self.assertRaises(ValidationError):
                GetSectionMatchStatusInput(page_id=page_id)

    def test_invalid_language_is_rejected(self):
        from drawing_graph.qa_mcp_models import GetSectionMatchStatusInput
        from pydantic import ValidationError

        with self.assertRaises(ValidationError) as context:
            GetSectionMatchStatusInput(cross_section_id="element:1", language="fr")
        self.assertIn("language", str(context.exception))

    def test_rule_version_status_and_write_back_fields_are_rejected(self):
        from drawing_graph.qa_mcp_models import GetSectionMatchStatusInput
        from pydantic import ValidationError

        for extra in (
            {"rule_version": "section-match-v1"},
            {"status": "candidate"},
            {"write_back": True},
            {"include_payload": True},
        ):
            with self.assertRaises(ValidationError):
                GetSectionMatchStatusInput(cross_section_id="element:1", **extra)

    def test_extra_field_error_does_not_echo_unrelated_input(self):
        from drawing_graph.qa_mcp_models import GetSectionMatchStatusInput
        from pydantic import ValidationError

        sentinel = "section-id-not-to-be-echoed"
        with self.assertRaises(ValidationError) as context:
            GetSectionMatchStatusInput(cross_section_id=sentinel, write_back=True)
        self.assertNotIn(sentinel, str(context.exception))

    def test_scope_carries_only_the_selected_id(self):
        from drawing_graph.qa_mcp_models import GetSectionMatchStatusInput

        request = GetSectionMatchStatusInput(page_id="page:1").to_qa_request()
        scope_ids = {
            name: value
            for name, value in (
                ("project_id", request.scope.project_id),
                ("drawing_set_id", request.scope.drawing_set_id),
                ("page_id", request.scope.page_id),
                ("block_id", request.scope.block_id),
                ("cross_section_id", request.scope.cross_section_id),
                ("table_id", request.scope.table_id),
                ("table_caption_id", request.scope.table_caption_id),
                ("element_id", request.scope.element_id),
            )
            if value is not None
        }
        self.assertEqual({"page_id": "page:1"}, scope_ids)


class GetTableCaptionStatusInputTests(unittest.TestCase):
    """GetTableCaptionStatusInput must require exactly one of three scopes."""

    def test_page_scope_produces_read_only_table_caption_request(self):
        from drawing_graph.qa_mcp_models import GetTableCaptionStatusInput
        from drawing_graph.qa_models import QuestionType

        tool_input = GetTableCaptionStatusInput(page_id="page:road:24")
        request = tool_input.to_qa_request()

        self.assertEqual(QuestionType.TABLE_CAPTION_STATUS, request.question_type)
        self.assertEqual("page:road:24", request.scope.page_id)
        self.assertIsNone(request.scope.table_id)
        self.assertIsNone(request.scope.table_caption_id)
        self.assertFalse(request.write_back)
        self.assertFalse(request.include_payload)
        self.assertEqual("zh", request.language)

    def test_table_scope_produces_read_only_table_caption_request(self):
        from drawing_graph.qa_mcp_models import GetTableCaptionStatusInput

        tool_input = GetTableCaptionStatusInput(table_id="table:road:24:t1", language="en")
        request = tool_input.to_qa_request()

        self.assertEqual("table:road:24:t1", request.scope.table_id)
        self.assertIsNone(request.scope.page_id)
        self.assertIsNone(request.scope.table_caption_id)
        self.assertEqual("en", request.language)

    def test_table_caption_scope_produces_read_only_table_caption_request(self):
        from drawing_graph.qa_mcp_models import GetTableCaptionStatusInput

        tool_input = GetTableCaptionStatusInput(table_caption_id="caption:road:24:c1")
        request = tool_input.to_qa_request()

        self.assertEqual("caption:road:24:c1", request.scope.table_caption_id)
        self.assertIsNone(request.scope.page_id)
        self.assertIsNone(request.scope.table_id)

    def test_exactly_one_scope_is_required(self):
        from drawing_graph.qa_mcp_models import GetTableCaptionStatusInput
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            GetTableCaptionStatusInput()
        for extra in (
            {"page_id": "page:1", "table_id": "table:1"},
            {"page_id": "page:1", "table_caption_id": "caption:1"},
            {"table_id": "table:1", "table_caption_id": "caption:1"},
            {"page_id": "page:1", "table_id": "table:1", "table_caption_id": "caption:1"},
        ):
            with self.assertRaises(ValidationError):
                GetTableCaptionStatusInput(**extra)

    def test_blank_or_too_long_ids_are_rejected(self):
        from drawing_graph.qa_mcp_models import GetTableCaptionStatusInput
        from pydantic import ValidationError

        for field_name, bad_values in (
            ("table_id", ("", "   ", "x" * 513)),
            ("table_caption_id", ("", "   ", "x" * 513)),
            ("page_id", ("", "   ", "x" * 513)),
        ):
            for bad_value in bad_values:
                with self.assertRaises(ValidationError):
                    GetTableCaptionStatusInput(**{field_name: bad_value})

    def test_invalid_language_is_rejected(self):
        from drawing_graph.qa_mcp_models import GetTableCaptionStatusInput
        from pydantic import ValidationError

        with self.assertRaises(ValidationError) as context:
            GetTableCaptionStatusInput(page_id="page:1", language="fr")
        self.assertIn("language", str(context.exception))

    def test_block_scope_and_relation_inference_fields_are_rejected(self):
        from drawing_graph.qa_mcp_models import GetTableCaptionStatusInput
        from pydantic import ValidationError

        for extra in (
            {"block_id": "block:1"},
            {"relation_type": "HAS_CAPTION"},
            {"write_back": True},
            {"include_payload": True},
        ):
            with self.assertRaises(ValidationError):
                GetTableCaptionStatusInput(page_id="page:1", **extra)

    def test_extra_field_error_does_not_echo_unrelated_input(self):
        from drawing_graph.qa_mcp_models import GetTableCaptionStatusInput
        from pydantic import ValidationError

        sentinel = "table-caption-page-id-not-to-be-echoed"
        with self.assertRaises(ValidationError) as context:
            GetTableCaptionStatusInput(page_id=sentinel, write_back=True)
        self.assertNotIn(sentinel, str(context.exception))

    def test_scope_carries_only_the_selected_id(self):
        from drawing_graph.qa_mcp_models import GetTableCaptionStatusInput

        request = GetTableCaptionStatusInput(table_caption_id="caption:1").to_qa_request()
        scope_ids = {
            name: value
            for name, value in (
                ("project_id", request.scope.project_id),
                ("drawing_set_id", request.scope.drawing_set_id),
                ("page_id", request.scope.page_id),
                ("block_id", request.scope.block_id),
                ("cross_section_id", request.scope.cross_section_id),
                ("table_id", request.scope.table_id),
                ("table_caption_id", request.scope.table_caption_id),
                ("element_id", request.scope.element_id),
            )
            if value is not None
        }
        self.assertEqual({"table_caption_id": "caption:1"}, scope_ids)


if __name__ == "__main__":
    unittest.main()
