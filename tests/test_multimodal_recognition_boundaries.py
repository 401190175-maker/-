"""Static architecture and data-minimization boundaries for the 04 layer."""

from __future__ import annotations

import dataclasses
import unittest
from pathlib import Path

from drawing_graph.recognition_models import (
    RecognitionAttempt,
    RecognitionCandidateEvidence,
    RecognitionExecutionRequest,
    ValidatedRecognitionOutput,
    ValidatedRecognitionRequest,
)
from drawing_graph.recognition_redaction import SafeRecognitionError
from drawing_graph.semantic_client import RecognitionClientResult
from drawing_graph.semantic_models import RecognitionRunSummary


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "drawing_graph"


EXECUTION_MODULES = (
    "recognition_models.py",
    "recognition_tasks.py",
    "recognition_input_validation.py",
    "recognition_image_preprocessing.py",
    "recognition_prompting.py",
    "recognition_output_validation.py",
    "recognition_retry.py",
    "recognition_metrics.py",
    "recognition_redaction.py",
    "recognition_attempt_log.py",
    "recognition_execution.py",
)


FORBIDDEN_IMPORTS = (
    "neo4j",
    "repository",
    "cypher",
    "qa_mcp",
    "qa_http",
    "qa_service",
    "tool_adapter",
    "run_log",
    "payload_store",
    "attempt_log",
    "cache",
    "semantic_service",
)


def _import_lines(module_path: Path) -> str:
    source = module_path.read_text(encoding="utf-8")
    return "\n".join(
        line.strip().lower()
        for line in source.splitlines()
        if line.strip().startswith(("import ", "from "))
    )


class RecognitionLayerBoundaryTests(unittest.TestCase):
    """The execution layer never imports graph, adapter or persistence internals."""

    def test_execution_modules_do_not_import_forbidden_layers(self) -> None:
        for module_name in EXECUTION_MODULES:
            with self.subTest(module=module_name):
                imports = _import_lines(SRC / module_name)
                for forbidden in FORBIDDEN_IMPORTS:
                    self.assertNotIn(forbidden, imports)

    def test_execution_modules_do_not_read_environment_or_secrets(self) -> None:
        for module_name in EXECUTION_MODULES:
            with self.subTest(module=module_name):
                imports = _import_lines(SRC / module_name)
                self.assertNotIn("os.environ", imports)
                self.assertNotIn("getenv", imports)


class QwenAdapterBoundaryTests(unittest.TestCase):
    """The Qwen adapter never reimplements task, crop, retry, cost or redaction."""

    def test_qwen_adapter_has_no_execution_logic_imports(self) -> None:
        source = (SRC / "qwen_semantic_client.py").read_text(encoding="utf-8")
        imports = _import_lines(SRC / "qwen_semantic_client.py")
        for forbidden in (
            "recognition_tasks",
            "recognition_prompting",
            "recognition_output_validation",
            "recognition_metrics",
            "recognition_redaction",
            "recognition_attempt_log",
            "recognition_execution",
            "semantic_service",
            "tool_facade",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, imports)

    def test_qwen_adapter_source_has_no_retry_or_write_back_logic(self) -> None:
        source = (SRC / "qwen_semantic_client.py").read_text(encoding="utf-8")
        for token in (
            "RecognitionAttemptExecutor",
            "RecognitionRetryPolicy",
            "RecognitionUsageMeter",
            "RecognitionRedactor",
            "RecognitionTaskRegistry",
            "write_back",
            "crop(",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, source)


class RecognitionDtoBoundaryTests(unittest.TestCase):
    """Public run/attempt/payload/error DTOs never carry sensitive fields."""

    FORBIDDEN_FIELD_NAMES = {
        "api_key",
        "token",
        "password",
        "secret",
        "authorization",
        "header",
        "traceback",
        "prompt",
        "image_path",
        "image_bytes",
        "base64",
    }

    def test_public_dtos_have_no_sensitive_fields(self) -> None:
        dto_types = (
            RecognitionAttempt,
            RecognitionExecutionRequest,
            ValidatedRecognitionOutput,
            RecognitionClientResult,
            SafeRecognitionError,
            RecognitionRunSummary,
        )
        for dto_type in dto_types:
            with self.subTest(dto=dto_type.__name__):
                field_names = {field.name for field in dataclasses.fields(dto_type)}
                self.assertTrue(self.FORBIDDEN_FIELD_NAMES.isdisjoint(field_names))

    def test_internal_validated_request_hides_image_path_from_repr(self) -> None:
        fields = {field.name: field for field in dataclasses.fields(ValidatedRecognitionRequest)}
        self.assertIn("image_path", fields)
        self.assertFalse(fields["image_path"].repr)

    def test_candidate_evidence_cannot_be_formal(self) -> None:
        self.assertEqual("candidate_relation", RecognitionCandidateEvidence.status)

    def test_write_back_defaults_to_false_everywhere(self) -> None:
        self.assertIs(False, RecognitionExecutionRequest.write_back)
        self.assertIs(False, ValidatedRecognitionRequest.write_back)


if __name__ == "__main__":
    unittest.main()
