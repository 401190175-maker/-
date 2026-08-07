import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from drawing_graph.qa_models import (
    QAAnswer,
    QAAnswerStatus,
    QAError,
    QAErrorCode,
    QARequest,
    QAScope,
    QuestionType,
)
from drawing_graph.qa_service import DrawingGraphQAService


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "drawing_graph_qa.py"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class FakeConfig:
    neo4j_uri = "bolt://example"
    neo4j_user = "neo4j"
    neo4j_password = "secret"


class FakeDriver:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeFacade:
    pass


class FakeQAService:
    def __init__(self, facade):
        self.facade = facade
        self.requests = []

    def ask(self, request):
        self.requests.append(request)
        return QAAnswer(
            question_type=request.question_type,
            scope=request.scope,
            status=QAAnswerStatus.ANSWERED,
            summary="页面存在，共 3 个元素",
        )


class QaCliMappingTests(unittest.TestCase):
    def test_ask_page_builds_page_summary_request_and_prints_json(self):
        module = _load_qa_cli()
        fake_driver = FakeDriver()
        fake_service = FakeQAService(FakeFacade())

        exit_code, stdout, stderr = _run_main(
            module,
            ["ask-page", "--page-id", "page:1", "--format", "json"],
            config_loader=lambda: FakeConfig(),
            driver_factory=lambda uri, auth: fake_driver,
            facade_factory=lambda driver: fake_service.facade,
            service_factory=lambda facade: fake_service,
        )

        self.assertEqual(0, exit_code)
        self.assertEqual("", stderr)
        payload = json.loads(stdout)
        self.assertEqual("ok", payload["status"])
        self.assertEqual("answered", payload["data"]["status"])
        self.assertEqual("page_summary", payload["data"]["question_type"])
        self.assertEqual("page:1", payload["data"]["scope"]["page_id"])
        self.assertEqual(1, len(fake_service.requests))
        self.assertIs(QuestionType.PAGE_SUMMARY, fake_service.requests[0].question_type)
        self.assertTrue(fake_driver.closed)

    def test_ask_block_prints_zh_brief(self):
        module = _load_qa_cli()
        fake_service = FakeQAService(FakeFacade())

        exit_code, stdout, stderr = _run_main(
            module,
            ["ask-block", "--block-id", "block:1", "--format", "zh-brief"],
            config_loader=lambda: FakeConfig(),
            driver_factory=lambda uri, auth: FakeDriver(),
            facade_factory=lambda driver: fake_service.facade,
            service_factory=lambda facade: fake_service,
        )

        self.assertEqual(0, exit_code)
        self.assertEqual("", stderr)
        self.assertIn("页面存在，共 3 个元素", stdout)
        self.assertEqual(1, len(fake_service.requests))
        self.assertIs(QuestionType.BLOCK_RELATIONS, fake_service.requests[0].question_type)
        self.assertEqual("block:1", fake_service.requests[0].scope.block_id)

    def test_ask_candidates_maps_page_scope(self):
        module = _load_qa_cli()
        fake_service = FakeQAService(FakeFacade())

        exit_code, stdout, stderr = _run_main(
            module,
            ["ask-candidates", "--page-id", "page:1"],
            config_loader=lambda: FakeConfig(),
            driver_factory=lambda uri, auth: FakeDriver(),
            facade_factory=lambda driver: fake_service.facade,
            service_factory=lambda facade: fake_service,
        )

        self.assertEqual(0, exit_code)
        request = fake_service.requests[0]
        self.assertIs(QuestionType.CANDIDATE_RELATIONS, request.question_type)
        self.assertEqual("page:1", request.scope.page_id)
        self.assertIsNone(request.scope.block_id)
        self.assertEqual("json", request.format_hint)

    def test_ask_table_caption_maps_table_id_scope(self):
        module = _load_qa_cli()
        fake_service = FakeQAService(FakeFacade())

        exit_code, stdout, stderr = _run_main(
            module,
            ["ask-table-caption", "--table-id", "table:1"],
            config_loader=lambda: FakeConfig(),
            driver_factory=lambda uri, auth: FakeDriver(),
            facade_factory=lambda driver: fake_service.facade,
            service_factory=lambda facade: fake_service,
        )

        self.assertEqual(0, exit_code)
        request = fake_service.requests[0]
        self.assertIs(QuestionType.TABLE_CAPTION_STATUS, request.question_type)
        self.assertEqual("table:1", request.scope.table_id)

    def test_default_format_is_json(self):
        module = _load_qa_cli()
        fake_service = FakeQAService(FakeFacade())

        exit_code, stdout, stderr = _run_main(
            module,
            ["diagnose", "--page-id", "page:1"],
            config_loader=lambda: FakeConfig(),
            driver_factory=lambda uri, auth: FakeDriver(),
            facade_factory=lambda driver: fake_service.facade,
            service_factory=lambda facade: fake_service,
        )

        self.assertEqual(0, exit_code)
        payload = json.loads(stdout)
        self.assertEqual("ok", payload["status"])
        self.assertIs(QuestionType.DIAGNOSTIC_STATUS, fake_service.requests[0].question_type)


class QaCliErrorTests(unittest.TestCase):
    def test_qa_error_is_sanitized_and_returns_one(self):
        module = _load_qa_cli()

        class FailingService:
            def __init__(self, facade):
                self.facade = facade

            def ask(self, request):
                raise QAError(QAErrorCode.NOT_FOUND, "password=secret leaked")

        exit_code, stdout, stderr = _run_main(
            module,
            ["ask-page", "--page-id", "page:1"],
            config_loader=lambda: FakeConfig(),
            driver_factory=lambda uri, auth: FakeDriver(),
            facade_factory=lambda driver: FakeFacade(),
            service_factory=lambda facade: FailingService(facade),
        )

        self.assertEqual(1, exit_code)
        self.assertEqual("", stdout)
        payload = json.loads(stderr)
        self.assertEqual("NOT_FOUND", payload["category"])
        self.assertNotIn("secret", stderr)
        self.assertNotIn("password", stderr)

    def test_missing_required_id_is_business_error(self):
        module = _load_qa_cli()
        created_drivers = []

        exit_code, stdout, stderr = _run_main(
            module,
            ["ask-page"],
            config_loader=lambda: FakeConfig(),
            driver_factory=lambda uri, auth: created_drivers.append(FakeDriver()),
            facade_factory=lambda driver: FakeFacade(),
            service_factory=lambda facade: DrawingGraphQAService(facade),
        )

        self.assertEqual(1, exit_code)
        self.assertEqual("", stdout)
        self.assertIn("INVALID_ARGUMENT", stderr)
        self.assertEqual(1, len(created_drivers))

    def test_config_error_is_sanitized_and_returns_two_without_driver(self):
        module = _load_qa_cli()
        created_drivers = []

        exit_code, stdout, stderr = _run_main(
            module,
            ["ask-page", "--page-id", "page:1"],
            config_loader=lambda: (_ for _ in ()).throw(RuntimeError("password=secret")),
            driver_factory=lambda uri, auth: created_drivers.append(FakeDriver()),
            facade_factory=lambda driver: FakeFacade(),
            service_factory=lambda facade: FakeQAService(facade),
        )

        self.assertEqual(2, exit_code)
        self.assertEqual("", stdout)
        self.assertEqual([], created_drivers)
        self.assertNotIn("secret", stderr)

    def test_facade_initialization_error_returns_two(self):
        module = _load_qa_cli()
        created_drivers = []

        exit_code, stdout, stderr = _run_main(
            module,
            ["ask-page", "--page-id", "page:1"],
            config_loader=lambda: FakeConfig(),
            driver_factory=lambda uri, auth: created_drivers.append(FakeDriver()) or created_drivers[-1],
            facade_factory=lambda driver: (_ for _ in ()).throw(RuntimeError("bolt://broken")),
            service_factory=lambda facade: FakeQAService(facade),
        )

        self.assertEqual(2, exit_code)
        self.assertEqual("", stdout)
        self.assertIn("initialization_failed", stderr)
        self.assertTrue(created_drivers[0].closed)

    def test_unknown_command_is_parse_error(self):
        module = _load_qa_cli()
        exit_code, stdout, stderr = _run_main(module, ["not-a-command"])
        self.assertEqual(2, exit_code)
        self.assertEqual("", stdout)


def _load_qa_cli():
    module_name = "drawing_graph_qa_cli_under_test"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _run_main(module, argv, **kwargs):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = module.main(argv, **kwargs)
    return exit_code, stdout.getvalue(), stderr.getvalue()


if __name__ == "__main__":
    unittest.main()
