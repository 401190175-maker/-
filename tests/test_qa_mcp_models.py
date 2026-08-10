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


if __name__ == "__main__":
    unittest.main()
