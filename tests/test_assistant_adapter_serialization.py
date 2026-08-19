"""Tests for the shared product adapter serialization and error mapping."""

import ast
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
MODULE_PATH = SRC_ROOT / "drawing_graph" / "assistant_adapter_serialization.py"


class EnvelopeTests(unittest.TestCase):
    def test_answer_package_projects_to_json_safe_data(self):
        from drawing_graph.assistant_adapter_serialization import answer_package_to_data
        from drawing_graph.assistant_models import (
            AnswerPackage,
            AnswerStatus,
            Claim,
            Citation,
            MachineAnswer,
        )

        claim = Claim(
            claim_id="claim:1",
            statement="图块标题关系",
            status="supported",
            fact_kinds=("derived_relation",),
        )
        citation = Citation(citation_id="citation:1", page_id="page:1", claim_ids=("claim:1",))
        machine = MachineAnswer(
            answer_contract_version="drawing-assistant-answer-v1",
            request_id="req:1",
            question_type="page_summary",
            status=AnswerStatus.ANSWERED,
            claims=(claim,),
            citations=(citation,),
        )
        package = AnswerPackage(
            request_id="req:1",
            question_type="page_summary",
            status="answered",
            machine_answer=machine,
            text_answer="答案",
            claims=(claim,),
            citations=(citation,),
            warnings=("warn-a",),
            unsupported_parts=("part-b",),
            recognition_run_ids=("run:1",),
        )

        data = answer_package_to_data(package)

        self.assertEqual("req:1", data["request_id"])
        self.assertEqual("answered", data["status"])
        self.assertEqual("答案", data["text_answer"])
        self.assertEqual(["warn-a"], data["warnings"])
        self.assertEqual(["part-b"], data["unsupported_parts"])
        self.assertEqual(["run:1"], data["recognition_run_ids"])
        self.assertEqual("answered", data["machine_answer"]["status"])
        self.assertEqual("claim:1", data["claims"][0]["claim_id"])
        self.assertEqual("page:1", data["citations"][0]["page_id"])
        self.assertEqual(["claim:1"], data["citations"][0]["claim_ids"])

    def test_success_envelope_has_ok_and_meta(self):
        from drawing_graph.assistant_adapter_serialization import build_success_envelope

        envelope = build_success_envelope({"status": "answered"}, meta={"request_id": "req:1"})
        self.assertTrue(envelope["ok"])
        self.assertEqual({"status": "answered"}, envelope["data"])
        self.assertEqual({"request_id": "req:1"}, envelope["meta"])

    def test_error_envelope_uses_code_not_category(self):
        from drawing_graph.assistant_adapter_serialization import build_error_envelope

        envelope = build_error_envelope(
            "read_only_violation",
            "write-back is not allowed",
            retryable=False,
            meta={"request_id": "req:1"},
        )
        self.assertFalse(envelope["ok"])
        self.assertEqual("read_only_violation", envelope["error"]["code"])
        self.assertEqual("write-back is not allowed", envelope["error"]["message"])
        self.assertFalse(envelope["error"]["retryable"])
        self.assertEqual({"request_id": "req:1"}, envelope["meta"])


class ErrorMappingTests(unittest.TestCase):
    def test_read_only_violation_maps_to_stable_code(self):
        from drawing_graph.assistant_adapter_serialization import map_exception_to_error
        from drawing_graph.drawing_assistant_service import ReadOnlyViolationError

        code, retryable = map_exception_to_error(ReadOnlyViolationError("write-back forbidden"))
        self.assertEqual("read_only_violation", code)
        self.assertFalse(retryable)

    def test_assistant_execution_error_maps_to_call_failed(self):
        from drawing_graph.assistant_adapter_serialization import map_exception_to_error
        from drawing_graph.drawing_assistant_service import AssistantExecutionError

        code, retryable = map_exception_to_error(
            AssistantExecutionError("retrieval_failed", "retrieval failed")
        )
        self.assertEqual("assistant_call_failed", code)
        self.assertFalse(retryable)

    def test_answer_validation_error_maps_to_call_failed(self):
        from drawing_graph.assistant_adapter_serialization import map_exception_to_error
        from drawing_graph.assistant_answer_generation import AnswerValidationError

        code, retryable = map_exception_to_error(AnswerValidationError("invalid answer"))
        self.assertEqual("assistant_call_failed", code)
        self.assertFalse(retryable)

    def test_adapter_error_preserves_code_and_retryable(self):
        from drawing_graph.assistant_adapter_serialization import (
            AssistantAdapterError,
            map_exception_to_error,
        )

        error = AssistantAdapterError("timeout", "timed out", retryable=True)
        code, retryable = map_exception_to_error(error)
        self.assertEqual("timeout", code)
        self.assertTrue(retryable)

    def test_value_error_maps_to_invalid_argument(self):
        from drawing_graph.assistant_adapter_serialization import map_exception_to_error

        code, retryable = map_exception_to_error(ValueError("question is required"))
        self.assertEqual("invalid_argument", code)
        self.assertFalse(retryable)

    def test_unexpected_error_maps_to_internal_error(self):
        from drawing_graph.assistant_adapter_serialization import map_exception_to_error

        code, retryable = map_exception_to_error(RuntimeError("bolt://user:secret@host"))
        self.assertEqual("internal_error", code)
        self.assertFalse(retryable)


class SanitizationTests(unittest.TestCase):
    def test_error_envelope_sanitizes_secrets(self):
        from drawing_graph.assistant_adapter_serialization import build_error_envelope

        envelope = build_error_envelope(
            "internal_error",
            "failed bolt://user:password@host traceback neo4j://driver token=abc",
            retryable=False,
        )
        message = envelope["error"]["message"]
        self.assertNotIn("password", message)
        self.assertNotIn("bolt://", message)
        self.assertNotIn("traceback", message)
        self.assertNotIn("token", message)

    def test_sanitize_error_message_is_available(self):
        from drawing_graph.assistant_adapter_serialization import sanitize_error_message

        self.assertEqual("ok", sanitize_error_message("ok"))
        self.assertNotIn("secret", sanitize_error_message("secret leaked"))


class BoundaryTests(unittest.TestCase):
    def test_module_does_not_import_forbidden_backends(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        forbidden = {
            "fastapi",
            "uvicorn",
            "mcp",
            "neo4j",
            "semantic_neo4j_repository",
            "neo4j_repository",
            "relation_repository",
            "semantic_repository",
            "qwen_semantic_client",
            "semantic_client",
            "assistant_http",
            "assistant_http_models",
            "assistant_http_runtime",
            "assistant_mcp",
            "assistant_mcp_models",
            "assistant_mcp_tools",
            "assistant_mcp_runtime",
            "assistant_mcp_server",
            "assistant_semantic_write_back",
            "block_relation_enrichment",
        }
        self.assertFalse(imported.intersection(forbidden))


if __name__ == "__main__":
    unittest.main()
