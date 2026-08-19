"""Static boundary and redaction tests for the 05 fusion layer."""

import ast
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src" / "drawing_graph"

FUSION_MODULES = (
    "assistant_evidence_fusion",
    "assistant_evidence_fusion_models",
    "assistant_evidence_fusion_factory",
    "assistant_recognition_projection",
    "assistant_evidence_normalization",
    "assistant_evidence_deduplication",
    "assistant_evidence_lineage",
    "assistant_evidence_conflicts",
    "assistant_claim_support",
    "assistant_answerability",
    "assistant_cache_closure",
    "assistant_evidence_rules",
)

FORBIDDEN_MODULES = (
    "neo4j",
    "semantic_neo4j_repository",
    "relation_repository",
    "candidate_review",
    "qwen_semantic_client",
    "qa_http",
    "qa_http_models",
    "qa_http_runtime",
    "qa_mcp",
    "qa_mcp_models",
    "qa_mcp_tools",
    "qa_mcp_server",
    "qa_service",
    "tool_facade",
    "tool_factory",
)


def _module_imports(name):
    source = (SRC_DIR / f"{name}.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


class FusionDependencyBoundaryTests(unittest.TestCase):
    def test_fusion_modules_do_not_import_forbidden_backends(self):
        for module_name in FUSION_MODULES:
            with self.subTest(module=module_name):
                imported = _module_imports(module_name)
                for forbidden in FORBIDDEN_MODULES:
                    self.assertNotIn(forbidden, imported)

    def test_write_back_adapter_does_not_import_neo4j_or_cypher(self):
        source = (SRC_DIR / "assistant_semantic_write_back.py").read_text(encoding="utf-8").lower()
        self.assertNotIn("neo4j", source)
        self.assertNotIn("semantic_neo4j_repository", source)
        self.assertNotIn("cypher", source)

    def test_facade_does_not_depend_on_fusion(self):
        source = (SRC_DIR / "tool_facade.py").read_text(encoding="utf-8")
        self.assertNotIn("assistant_evidence_fusion", source)
        self.assertNotIn("assistant_semantic_write_back", source)

    def test_qa_service_http_mcp_do_not_depend_on_fusion(self):
        for module_name in ("qa_service", "qa_http", "qa_http_models", "qa_mcp_models", "qa_mcp_tools", "qa_mcp_server"):
            source = (SRC_DIR / f"{module_name}.py").read_text(encoding="utf-8")
            self.assertNotIn("assistant_evidence_fusion", source)
            self.assertNotIn("assistant_semantic_write_back", source)

    def test_fusion_factory_does_not_import_forbidden_backends(self):
        imported = _module_imports("assistant_evidence_fusion_factory")
        for forbidden in FORBIDDEN_MODULES:
            self.assertNotIn(forbidden, imported)


class FusionRedactionTests(unittest.TestCase):
    def test_fusion_error_messages_are_safe(self):
        from drawing_graph.assistant_evidence_fusion import FusionInputError
        from drawing_graph.assistant_models import ReasonCode

        error = FusionInputError(ReasonCode.FUSION_INPUT_INVALID, "request IDs must be identical")
        message = str(error).lower()
        self.assertNotIn("secret", message)
        self.assertNotIn("password", message)
        self.assertNotIn("c:\\", message)
        self.assertNotIn("traceback", message)
        self.assertEqual(ReasonCode.FUSION_INPUT_INVALID, error.reason_code)

    def test_diagnostic_does_not_expand_payload(self):
        from drawing_graph.assistant_recognition_projection import RecognitionEvidenceProjector
        from drawing_graph.semantic_service import SemanticRecognitionResult

        result = SemanticRecognitionResult(
            recognition_run_id="run:1",
            status="succeeded",
            observations=(),
            persisted=False,
        )
        projection = RecognitionEvidenceProjector().project(result)
        diagnostic = projection.diagnostics[0]
        value = diagnostic.value
        self.assertIn("run_status", value)
        self.assertIn("payload_ref", value)
        self.assertNotIn("full_payload", value)
        self.assertNotIn("image_bytes", value)


class FusionResourceLimitTests(unittest.TestCase):
    def test_invalid_limits_are_rejected(self):
        from drawing_graph.assistant_evidence_fusion import FusionResourceLimits

        with self.assertRaises(ValueError):
            FusionResourceLimits(max_evidence=0)
        with self.assertRaises(ValueError):
            FusionResourceLimits(max_conflicts=-1)

    def test_invalid_write_batch_limits_are_rejected(self):
        from drawing_graph.assistant_semantic_write_back import WriteBatchLimits

        with self.assertRaises(ValueError):
            WriteBatchLimits(max_evidence=0)

    def test_evidence_over_limit_is_truncated_deterministically(self):
        from drawing_graph.assistant_evidence_fusion import EvidenceFusionService, FusionResourceLimits
        from drawing_graph.assistant_evidence_fusion_models import EvidenceFusionRequest
        from drawing_graph.assistant_models import (
            AssistantRequest,
            EvidenceItem,
            FactKind,
            QuestionUnderstandingResult,
            RetrievalBundle,
            SemanticGapDecision,
        )

        items = tuple(
            EvidenceItem(evidence_id=f"evidence:{index}", fact_kind=FactKind.DIAGNOSTIC, value={})
            for index in range(5)
        )
        request = EvidenceFusionRequest(
            assistant_request=AssistantRequest(request_id="req:1", question="q"),
            question_result=QuestionUnderstandingResult(request_id="req:1", question_type="page_summary"),
            retrieval_bundle=RetrievalBundle(request_id="req:1", diagnostics=items),
            semantic_gap_decision=SemanticGapDecision(request_id="req:1"),
        )
        service = EvidenceFusionService(resource_limits=FusionResourceLimits(max_evidence=2))
        bundle = service.fuse(request)
        self.assertIn("result_truncated", [code.value for code in bundle.reason_codes])

    def test_conflict_detector_limits_group_size(self):
        from drawing_graph.assistant_evidence_conflicts import EvidenceConflictDetector

        detector = EvidenceConflictDetector(max_group_size=2)
        self.assertEqual(2, detector.max_group_size)


if __name__ == "__main__":
    unittest.main()
