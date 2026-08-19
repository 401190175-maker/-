"""Tests for the product-level read-only CLI adapter."""

import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "drawing_assistant.py"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from drawing_graph.assistant_models import AnswerPackage, AnswerStatus, MachineAnswer
from drawing_graph.drawing_assistant_service import (
    AssistantExecutionError,
    ReadOnlyViolationError,
)


def _load_cli():
    module_name = "drawing_assistant_cli_under_test"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _parse(module, argv):
    return module.build_parser().parse_args(argv)


def _run_main(module, argv, **kwargs):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = module.main(argv, **kwargs)
    return exit_code, stdout.getvalue(), stderr.getvalue()


class _FakeConfig:
    neo4j_uri = "bolt://example"
    neo4j_user = "neo4j"
    neo4j_password = "secret"


class _FakeDriver:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _FakeFacade:
    pass


def _make_package(status="answered", request_id="req:1", text="答案文本"):
    machine = MachineAnswer(
        answer_contract_version="drawing-assistant-answer-v1",
        request_id=request_id,
        question_type="page_summary",
        status=AnswerStatus(status),
    )
    return AnswerPackage(
        request_id=request_id,
        question_type="page_summary",
        status=status,
        machine_answer=machine,
        text_answer=text,
    )


class _FakeService:
    def __init__(self, facade, package=None, error=None):
        self.facade = facade
        self.package = package or _make_package()
        self.error = error
        self.calls = 0
        self.last_request = None

    def answer(self, request, policy=None):
        self.calls += 1
        self.last_request = request
        if self.error is not None:
            raise self.error
        return self.package


class CliArgumentMappingTests(unittest.TestCase):
    def test_question_and_request_id_map(self):
        module = _load_cli()
        args = _parse(module, ["--question", "该页面包含哪些图块？", "--request-id", "req:1"])
        request = module.build_request(args)
        self.assertEqual("该页面包含哪些图块？", request.question)
        self.assertEqual("req:1", request.request_id)
        self.assertFalse(request.allow_write_back)

    def test_scope_args_map(self):
        module = _load_cli()
        args = _parse(module, ["--question", "q", "--page-id", "page:1", "--block-id", "block:2"])
        request = module.build_request(args)
        self.assertEqual("page:1", request.scope_hint.page_id)
        self.assertEqual("block:2", request.scope_hint.block_id)

    def test_no_scope_args_gives_none_hint(self):
        module = _load_cli()
        args = _parse(module, ["--question", "q"])
        request = module.build_request(args)
        self.assertIsNone(request.scope_hint)

    def test_default_no_recognition(self):
        module = _load_cli()
        args = _parse(module, ["--question", "q"])
        self.assertFalse(module.build_request(args).allow_recognition)

    def test_allow_recognition_flag(self):
        module = _load_cli()
        args = _parse(module, ["--question", "q", "--allow-recognition"])
        self.assertTrue(module.build_request(args).allow_recognition)

    def test_no_recognition_overrides_allow(self):
        module = _load_cli()
        args = _parse(module, ["--question", "q", "--allow-recognition", "--no-recognition"])
        self.assertFalse(module.build_request(args).allow_recognition)

    def test_text_generation_maps_to_policy(self):
        module = _load_cli()
        args = _parse(module, ["--question", "q", "--text-generation"])
        self.assertTrue(module.build_policy(args).enable_constrained_text)

    def test_default_output_is_json(self):
        module = _load_cli()
        args = _parse(module, ["--question", "q"])
        self.assertEqual("json", args.output)

    def test_no_write_back_or_secret_args(self):
        module = _load_cli()
        parser = module.build_parser()
        dests = {action.dest for action in parser._actions}
        for forbidden in ("write_back", "write-back", "password", "token", "uri", "user", "api_key", "neo4j"):
            self.assertNotIn(forbidden, dests)


class CliLifecycleTests(unittest.TestCase):
    def test_service_called_once_and_driver_closed(self):
        module = _load_cli()
        driver = _FakeDriver()
        service = _FakeService(_FakeFacade())

        exit_code, stdout, stderr = _run_main(
            module,
            ["--question", "q", "--request-id", "req:1"],
            config_loader=lambda: _FakeConfig(),
            driver_factory=lambda uri, auth: driver,
            facade_factory=lambda d: _FakeFacade(),
            service_factory=lambda f: service,
        )
        self.assertEqual(0, exit_code)
        self.assertEqual(1, service.calls)
        self.assertTrue(driver.closed)
        self.assertEqual("", stderr)

    def test_config_error_does_not_create_driver(self):
        module = _load_cli()
        created = []

        def boom():
            raise RuntimeError("password=secret")

        exit_code, stdout, stderr = _run_main(
            module,
            ["--question", "q"],
            config_loader=boom,
            driver_factory=lambda uri, auth: created.append(1) or _FakeDriver(),
            facade_factory=lambda d: _FakeFacade(),
            service_factory=lambda f: _FakeService(f),
        )
        self.assertEqual(2, exit_code)
        self.assertEqual([], created)
        self.assertNotIn("secret", stderr)


class CliOutputTests(unittest.TestCase):
    def test_json_output_is_single_envelope(self):
        module = _load_cli()
        exit_code, stdout, stderr = _run_main(
            module,
            ["--question", "q", "--request-id", "req:1"],
            config_loader=lambda: _FakeConfig(),
            driver_factory=lambda uri, auth: _FakeDriver(),
            facade_factory=lambda d: _FakeFacade(),
            service_factory=lambda f: _FakeService(f),
        )
        self.assertEqual(0, exit_code)
        self.assertEqual("", stderr)
        payload = json.loads(stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual("answered", payload["data"]["status"])
        self.assertEqual("req:1", payload["data"]["request_id"])

    def test_text_output_is_pure_text(self):
        module = _load_cli()
        exit_code, stdout, stderr = _run_main(
            module,
            ["--question", "q", "--request-id", "req:1", "--output", "text"],
            config_loader=lambda: _FakeConfig(),
            driver_factory=lambda uri, auth: _FakeDriver(),
            facade_factory=lambda d: _FakeFacade(),
            service_factory=lambda f: _FakeService(f),
        )
        self.assertEqual(0, exit_code)
        self.assertEqual("答案文本", stdout.strip())

    def test_same_request_id_is_byte_identical(self):
        module = _load_cli()

        def run():
            return _run_main(
                module,
                ["--question", "q", "--request-id", "req:1"],
                config_loader=lambda: _FakeConfig(),
                driver_factory=lambda uri, auth: _FakeDriver(),
                facade_factory=lambda d: _FakeFacade(),
                service_factory=lambda f: _FakeService(f),
            )[1]

        first = run()
        second = run()
        self.assertEqual(first, second)


class CliExitCodeTests(unittest.TestCase):
    def _run_status(self, module, status):
        return _run_main(
            module,
            ["--question", "q", "--request-id", "req:1"],
            config_loader=lambda: _FakeConfig(),
            driver_factory=lambda uri, auth: _FakeDriver(),
            facade_factory=lambda d: _FakeFacade(),
            service_factory=lambda f: _FakeService(f, package=_make_package(status=status)),
        )[0]

    def test_business_statuses_exit_zero(self):
        module = _load_cli()
        for status in ("answered", "partial", "clarification_required", "unsupported", "recognition_failed"):
            self.assertEqual(0, self._run_status(module, status), status)

    def test_runtime_failure_exits_one(self):
        module = _load_cli()
        exit_code, stdout, stderr = _run_main(
            module,
            ["--question", "q"],
            config_loader=lambda: _FakeConfig(),
            driver_factory=lambda uri, auth: _FakeDriver(),
            facade_factory=lambda d: _FakeFacade(),
            service_factory=lambda f: _FakeService(
                f, error=AssistantExecutionError("retrieval_failed", "secret leaked")
            ),
        )
        self.assertEqual(1, exit_code)
        self.assertEqual("", stdout)
        payload = json.loads(stderr)
        self.assertFalse(payload["ok"])
        self.assertEqual("retrieval_failed", payload["error"]["code"])
        self.assertNotIn("secret", stderr)

    def test_read_only_violation_exits_two(self):
        module = _load_cli()
        exit_code, _, stderr = _run_main(
            module,
            ["--question", "q"],
            config_loader=lambda: _FakeConfig(),
            driver_factory=lambda uri, auth: _FakeDriver(),
            facade_factory=lambda d: _FakeFacade(),
            service_factory=lambda f: _FakeService(
                f, error=ReadOnlyViolationError("write-back forbidden")
            ),
        )
        self.assertEqual(2, exit_code)
        payload = json.loads(stderr)
        self.assertEqual("read_only_violation", payload["error"]["code"])

    def test_missing_question_exits_two(self):
        module = _load_cli()
        exit_code, stdout, _ = _run_main(
            module,
            [],
            config_loader=lambda: _FakeConfig(),
            driver_factory=lambda uri, auth: _FakeDriver(),
            facade_factory=lambda d: _FakeFacade(),
            service_factory=lambda f: _FakeService(f),
        )
        self.assertEqual(2, exit_code)
        self.assertEqual("", stdout)


if __name__ == "__main__":
    unittest.main()
