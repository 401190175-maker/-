import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "import_json.py"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class FakeConfig:
    def __init__(self):
        self.data_root = Path("data")
        self.project_slug = "road-project"
        self.neo4j_uri = "bolt://example"
        self.neo4j_user = "neo4j"
        self.neo4j_password = "secret"
        self.batch_size = 123


class FakeResult:
    def __init__(self, status, batch_id="batch:1", page_id="page:1", drawing_set_id="set:1"):
        self.status = status
        self.batch_id = batch_id
        self.page_id = page_id
        self.drawing_set_id = drawing_set_id
        self.total_count = 1
        self.success_count = 1 if status == "success" else 0
        self.skipped_count = 1 if status == "skipped" else 0
        self.failed_count = 1 if status == "failed" else 0
        self.warning_count = 0
        self.warnings = ()
        self.errors = () if status == "success" else ("failed",)


class FakeService:
    def __init__(self, config, repository):
        self.config = config
        self.repository = repository
        self.calls = []
        repository.services.append(self)

    def import_all(self):
        self.calls.append(("all",))
        return FakeResult("success")

    def import_drawing_set(self, batch_id, drawing_set_path):
        self.calls.append(("drawing-set", batch_id, Path(drawing_set_path)))
        return FakeResult("success", drawing_set_id="set:road-project:set-a")

    def import_page(self, batch_id, json_path):
        self.calls.append(("page", batch_id, Path(json_path)))
        return FakeResult("success", page_id="page:road-project:set-a:road_1")


class FailingService(FakeService):
    def import_all(self):
        self.calls.append(("all",))
        return FakeResult("failed", batch_id="batch:failed")


class FakeRepository:
    def __init__(self):
        self.services = []


class ImportCliTest(unittest.TestCase):
    def test_all_mode_calls_import_all_and_returns_zero(self):
        module = _load_import_cli()
        repository = FakeRepository()

        exit_code = _run_main(
            module,
            ["all"],
            config_loader=lambda: FakeConfig(),
            repository_factory=lambda config: repository,
            service_factory=FakeService,
        )

        self.assertEqual(0, exit_code)
        self.assertEqual([("all",)], repository.services[0].calls)

    def test_drawing_set_mode_passes_batch_and_path_to_service(self):
        module = _load_import_cli()
        repository = FakeRepository()

        exit_code = _run_main(
            module,
            ["drawing-set", "batch:1", "data/set-a"],
            config_loader=lambda: FakeConfig(),
            repository_factory=lambda config: repository,
            service_factory=FakeService,
        )

        self.assertEqual(0, exit_code)
        self.assertEqual([("drawing-set", "batch:1", Path("data/set-a"))], repository.services[0].calls)

    def test_page_mode_passes_batch_and_json_path_to_service(self):
        module = _load_import_cli()
        repository = FakeRepository()

        exit_code = _run_main(
            module,
            ["page", "batch:1", "data/set-a/road_1.json"],
            config_loader=lambda: FakeConfig(),
            repository_factory=lambda config: repository,
            service_factory=FakeService,
        )

        self.assertEqual(0, exit_code)
        self.assertEqual([("page", "batch:1", Path("data/set-a/road_1.json"))], repository.services[0].calls)

    def test_failed_import_returns_non_zero(self):
        module = _load_import_cli()

        exit_code = _run_main(
            module,
            ["all"],
            config_loader=lambda: FakeConfig(),
            repository_factory=lambda config: FakeRepository(),
            service_factory=FailingService,
        )

        self.assertEqual(1, exit_code)

    def test_missing_config_returns_non_zero_without_password_leak(self):
        module = _load_import_cli()

        exit_code = _run_main(
            module,
            ["all"],
            config_loader=lambda: (_ for _ in ()).throw(RuntimeError("missing password=secret")),
            repository_factory=lambda config: FakeRepository(),
            service_factory=FakeService,
        )

        self.assertEqual(2, exit_code)

    def test_invalid_arguments_return_non_zero_before_service_creation(self):
        module = _load_import_cli()
        created_repositories = []

        exit_code = _run_main(
            module,
            ["page", "batch:1"],
            config_loader=lambda: FakeConfig(),
            repository_factory=lambda config: created_repositories.append(FakeRepository()),
            service_factory=FakeService,
        )

        self.assertEqual(2, exit_code)
        self.assertEqual([], created_repositories)


def _load_import_cli():
    module_name = "drawing_graph_import_cli_under_test"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _run_main(module, argv, **kwargs):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        return module.main(argv, **kwargs)


if __name__ == "__main__":
    unittest.main()
