"""Security and dependency boundary tests for feedback modules."""

import ast
import unittest
from pathlib import Path

from drawing_graph.assistant_models import FeedbackEvent
from drawing_graph.assistant_feedback_models import FeedbackPermission
from drawing_graph.assistant_feedback_permissions import FeedbackPermissionPolicy
from drawing_graph.assistant_feedback_service import FeedbackService
from drawing_graph.assistant_feedback_store import InMemoryFeedbackStore
from drawing_graph.assistant_trace_models import ClaimTrace
from drawing_graph.assistant_trace_store import InMemoryTraceStore

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src" / "drawing_graph"

FEEDBACK_MODULES = (
    "assistant_feedback_models",
    "assistant_feedback_store",
    "assistant_feedback_permissions",
    "assistant_feedback_state_machine",
    "assistant_candidate_review_adapter",
    "assistant_feedback_service",
)

FORBIDDEN_MODULES = (
    "neo4j",
    "neo4j_repository",
    "relation_repository",
    "semantic_repository",
    "semantic_neo4j_repository",
    "qa_service",
    "qa_http",
    "qa_mcp",
    "import_service",
    "qwen_semantic_client",
    "semantic_client",
    "semantic_service",
    "recognition_execution",
    "tool_factory",
    "assistant_semantic_write_back",
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


class _Actor:
    def __init__(self, permissions=()):
        self.permissions = frozenset(permissions)


class FeedbackModuleBoundaryTests(unittest.TestCase):
    def test_feedback_modules_do_not_import_forbidden_backends(self):
        for module_name in FEEDBACK_MODULES:
            with self.subTest(module=module_name):
                imported = _module_imports(module_name)
                for forbidden in FORBIDDEN_MODULES:
                    self.assertNotIn(forbidden, imported)

    def test_feedback_modules_do_not_call_formal_promotion(self):
        for module_name in FEEDBACK_MODULES:
            with self.subTest(module=module_name):
                source = (SRC_DIR / f"{module_name}.py").read_text(encoding="utf-8")
                self.assertNotIn("promote_candidate_relation", source)


class _SecretLeakingStore:
    def append_feedback(self, event):
        raise RuntimeError("secret-token-123")

    def append_audit(self, audit):
        raise RuntimeError("secret-token-123")

    def get_feedback(self, feedback_id):
        return None

    def list_feedback_for_request(self, request_id):
        return ()

    def list_audit(self, feedback_id):
        return ()

    def set_status(self, feedback_id, status):
        raise RuntimeError("secret-token-123")

    def get_status(self, feedback_id):
        return None


class FeedbackSafetyTests(unittest.TestCase):
    def test_confirm_and_correct_never_promote_formal(self):
        store = InMemoryTraceStore()
        store.append_claim_trace(
            ClaimTrace(claim_id="claim:1", request_id="req:1", fact_kinds=())
        )
        service = FeedbackService(store=InMemoryFeedbackStore(), trace_store=store)
        for action in ("confirm", "correct"):
            result = service.submit_feedback(
                FeedbackEvent(
                    feedback_id=f"feedback:{action}",
                    request_id="req:1",
                    claim_id="claim:1",
                    action=action,
                ),
                _Actor((FeedbackPermission.RECORD_FEEDBACK,)),
            )
            self.assertEqual("recorded", result.status.value, action)
            self.assertIsNone(result.candidate_review_result)

    def test_store_failure_does_not_leak_secret(self):
        service = FeedbackService(store=_SecretLeakingStore(), trace_store=InMemoryTraceStore())
        result = service.submit_feedback(
            FeedbackEvent(
                feedback_id="feedback:1",
                request_id="req:1",
                claim_id="claim:1",
                action="confirm",
            ),
            _Actor((FeedbackPermission.RECORD_FEEDBACK,)),
        )
        self.assertNotIn("secret-token-123", repr(result))


if __name__ == "__main__":
    unittest.main()
