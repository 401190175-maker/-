"""Offline end-to-end tests for the product read-only CLI and orchestration.

These tests use a fake facade and the real 01—06 services; no Neo4j or network
dependency exists. They do not claim live Neo4j or live provider validation.
"""

import importlib.util
import io
import json
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "drawing_assistant.py"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from drawing_graph.assistant_models import (
    AnswerPackage,
    AnswerStatus,
    AssistantRequest,
    MachineAnswer,
)
from drawing_graph.drawing_assistant_factory import create_drawing_assistant_service
from drawing_graph.tool_models import (
    BBox,
    BlockRelations,
    BlockTrace,
    ElementEvidence,
    PageSourceFacts,
)


def _load_cli():
    spec = importlib.util.spec_from_file_location("drawing_assistant_e2e_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _FakeConfig:
    neo4j_uri = "bolt://example"
    neo4j_user = "neo4j"
    neo4j_password = "secret"


class _FakeDriver:
    def close(self):
        pass


class FakeFacade:
    def __init__(self, page_facts=None, block_trace=None, block_relations=None, recognize_error=None):
        self.page_facts = page_facts or {}
        self.block_trace = block_trace
        self.block_relations = block_relations
        self.recognize_error = recognize_error

    def get_page_source_facts(self, page_id, element_types=None, include_image_meta=True):
        return self.page_facts.get(page_id)

    def get_block_trace(self, block_id):
        return self.block_trace

    def get_block_relations(self, block_id):
        return self.block_relations

    def list_text_observations(self, **kwargs):
        return ()

    def list_interpretations(self, **kwargs):
        return ()

    def list_candidate_relations(self, **kwargs):
        return ()

    def list_section_matches(self, **kwargs):
        return ()

    def list_drawing_sets(self, **kwargs):
        return ()

    def list_pages(self, **kwargs):
        return ()

    def recognize_semantic_targets(self, targets, write_back=False, **kwargs):
        if self.recognize_error is not None:
            raise self.recognize_error
        return None


def _page_facts():
    return {
        "page:1": PageSourceFacts(
            page_id="page:1",
            image_path=None,
            elements=(
                ElementEvidence(
                    element_id="element:1",
                    element_type="Block",
                    bbox=BBox(1, 2, 3, 4),
                    normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
                    source_label="l1",
                ),
            ),
        ),
    }


def _run(module, facade, argv):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = module.main(
            argv,
            config_loader=lambda: _FakeConfig(),
            driver_factory=lambda uri, auth: _FakeDriver(),
            facade_factory=lambda d: facade,
            service_factory=lambda f: create_drawing_assistant_service(f),
        )
    return exit_code, stdout.getvalue(), stderr.getvalue()


class DrawingAssistantE2ETests(unittest.TestCase):
    def test_clarification_offline(self):
        module = _load_cli()
        exit_code, stdout, stderr = _run(module, FakeFacade(), ["--question", "这个图块有哪些关系", "--request-id", "req:1"])
        self.assertEqual(0, exit_code)
        self.assertEqual("", stderr)
        payload = json.loads(stdout)
        self.assertEqual("clarification_required", payload["data"]["status"])

    def test_unsupported_offline(self):
        module = _load_cli()
        exit_code, stdout, _ = _run(module, FakeFacade(), ["--question", "今天天气怎么样", "--request-id", "req:1"])
        self.assertEqual(0, exit_code)
        payload = json.loads(stdout)
        self.assertEqual("unsupported", payload["data"]["status"])

    def test_page_summary_partial_offline(self):
        module = _load_cli()
        exit_code, stdout, stderr = _run(
            module,
            FakeFacade(page_facts=_page_facts()),
            ["--question", "page:1 这张图主要讲什么", "--request-id", "req:1"],
        )
        self.assertEqual(0, exit_code)
        self.assertEqual("", stderr)
        payload = json.loads(stdout)
        self.assertTrue(payload["ok"])
        self.assertIn(payload["data"]["status"], ("answered", "partial"))

    def test_recognition_question_offline(self):
        module = _load_cli()
        block_trace = BlockTrace(
            block_id="block:1",
            project_id="project:1",
            drawing_set_id="set:1",
            page_id="page:1",
            bbox=BBox(1, 2, 3, 4),
            normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
        )
        facade = FakeFacade(
            page_facts=_page_facts(),
            block_trace=block_trace,
            recognize_error=RuntimeError("provider down"),
        )
        exit_code, stdout, stderr = _run(
            module,
            facade,
            ["--question", "block:1 这个构件是什么", "--allow-recognition", "--request-id", "req:1"],
        )
        self.assertEqual(0, exit_code)
        self.assertEqual("", stderr)
        payload = json.loads(stdout)
        self.assertTrue(payload["ok"])

    def test_answered_via_fake_service(self):
        module = _load_cli()
        package = AnswerPackage(
            request_id="req:1",
            question_type="page_summary",
            status="answered",
            machine_answer=MachineAnswer(
                answer_contract_version="drawing-assistant-answer-v1",
                request_id="req:1",
                question_type="page_summary",
                status=AnswerStatus.ANSWERED,
            ),
            text_answer="答案",
        )

        class FakeService:
            def answer(self, request, policy=None):
                return package

        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = module.main(
                ["--question", "q", "--request-id", "req:1"],
                config_loader=lambda: _FakeConfig(),
                driver_factory=lambda uri, auth: _FakeDriver(),
                facade_factory=lambda d: FakeFacade(),
                service_factory=lambda f: FakeService(),
            )
        self.assertEqual(0, exit_code)
        payload = json.loads(stdout.getvalue())
        self.assertEqual("answered", payload["data"]["status"])

    def test_all_statuses_via_fake_service(self):
        module = _load_cli()
        for status in ("answered", "partial", "clarification_required", "unsupported", "recognition_failed"):
            package = AnswerPackage(
                request_id="req:1",
                question_type="page_summary",
                status=status,
                machine_answer=MachineAnswer(
                    answer_contract_version="drawing-assistant-answer-v1",
                    request_id="req:1",
                    question_type="page_summary",
                    status=AnswerStatus(status),
                ),
                text_answer="答案",
            )

            class FakeService:
                def answer(self, request, policy=None):
                    return package

            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = module.main(
                    ["--question", "q", "--request-id", "req:1"],
                    config_loader=lambda: _FakeConfig(),
                    driver_factory=lambda uri, auth: _FakeDriver(),
                    facade_factory=lambda d: FakeFacade(),
                    service_factory=lambda f: FakeService(),
                )
            self.assertEqual(0, exit_code, status)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(status, payload["data"]["status"], status)

    def test_cli_json_preserves_warnings_and_unsupported_parts(self):
        module = _load_cli()
        package = AnswerPackage(
            request_id="req:1",
            question_type="page_summary",
            status="partial",
            machine_answer=MachineAnswer(
                answer_contract_version="drawing-assistant-answer-v1",
                request_id="req:1",
                question_type="page_summary",
                status=AnswerStatus.PARTIAL,
                warnings=("warn-a",),
                unsupported_parts=("part-b",),
            ),
            text_answer="答案",
            warnings=("warn-a",),
            unsupported_parts=("part-b",),
        )

        class FakeService:
            def answer(self, request, policy=None):
                return package

        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = module.main(
                ["--question", "q", "--request-id", "req:1"],
                config_loader=lambda: _FakeConfig(),
                driver_factory=lambda uri, auth: _FakeDriver(),
                facade_factory=lambda d: FakeFacade(),
                service_factory=lambda f: FakeService(),
            )
        self.assertEqual(0, exit_code)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(["warn-a"], payload["data"]["machine_answer"]["warnings"])
        self.assertEqual(["part-b"], payload["data"]["machine_answer"]["unsupported_parts"])
        self.assertEqual("答案", payload["data"]["text_answer"])


class CliSubprocessSmokeTests(unittest.TestCase):
    """Subprocess smoke for the product CLI; fake runtime, no Neo4j/network."""

    def _clean_env(self):
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("NEO4J_", "DRAWING_GRAPH_", "DASHSCOPE_"))
        }
        env["PYTHONPATH"] = str(SRC_ROOT)
        return env

    def test_script_import_has_no_side_effects(self):
        result = subprocess.run(
            [sys.executable, "-c", "import drawing_assistant; print('import-ok')"],
            cwd=str(PROJECT_ROOT / "scripts"),
            env=self._clean_env(),
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("import-ok", result.stdout)

    def test_missing_question_exits_two(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            cwd=str(PROJECT_ROOT),
            env=self._clean_env(),
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(2, result.returncode)
        self.assertEqual("", result.stdout)

    def test_config_error_is_sanitized(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--question", "q"],
            cwd=str(PROJECT_ROOT),
            env=self._clean_env(),
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(2, result.returncode)
        self.assertEqual("", result.stdout)
        payload = json.loads(result.stderr)
        self.assertFalse(payload["ok"])
        self.assertEqual("configuration_failed", payload["error"]["code"])
        self.assertNotIn("secret", result.stderr.lower())
        self.assertNotIn("password", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
