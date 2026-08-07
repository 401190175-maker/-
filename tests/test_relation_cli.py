import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "enrich_block_relations.py"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class FakeConfig:
    def __init__(self):
        self.project_slug = "road-project"
        self.neo4j_uri = "bolt://example"
        self.neo4j_user = "neo4j"
        self.neo4j_password = "secret"


class FakeRepository:
    def __init__(self):
        self.services = []


class FakeService:
    def __init__(self, repository):
        self.repository = repository
        self.calls = []
        self.summaries = {}
        repository.services.append(self)

    def enrich_project(self, scope):
        self.calls.append(("project", scope))
        self.summaries[scope.relation_batch_id] = {"status": "success"}

    def enrich_drawing_set(self, scope):
        self.calls.append(("drawing-set", scope))
        self.summaries[scope.relation_batch_id] = {"status": "success"}

    def enrich_page(self, scope):
        self.calls.append(("page", scope))
        self.summaries[scope.relation_batch_id] = {"status": "success"}

    def get_batch_summary(self, relation_batch_id):
        return self.summaries[relation_batch_id]


class FailingBatchService(FakeService):
    def enrich_project(self, scope):
        self.calls.append(("project", scope))
        self.summaries[scope.relation_batch_id] = {"status": "failed"}


class RaisingService(FakeService):
    def enrich_project(self, scope):
        self.calls.append(("project", scope))
        raise RuntimeError("write failed")


class RelationCliTest(unittest.TestCase):
    def test_project_scope_calls_project_service_and_returns_zero(self):
        module = _load_relation_cli()
        repository = FakeRepository()

        exit_code = _run_main(
            module,
            ["project", "--rule-version", "rules-v1"],
            config_loader=lambda: FakeConfig(),
            repository_factory=lambda config: repository,
            service_factory=FakeService,
            batch_id_factory=lambda: "relation-batch:test",
        )

        self.assertEqual(0, exit_code)
        self.assertEqual(1, len(repository.services[0].calls))
        mode, scope = repository.services[0].calls[0]
        self.assertEqual("project", mode)
        self.assertEqual("project:road-project", scope.project_id)
        self.assertEqual("relation-batch:test", scope.relation_batch_id)
        self.assertEqual("rules-v1", scope.rule_version)
        self.assertIsNone(scope.drawing_set_id)
        self.assertIsNone(scope.page_id)

    def test_drawing_set_scope_calls_drawing_set_service(self):
        module = _load_relation_cli()
        repository = FakeRepository()

        exit_code = _run_main(
            module,
            ["drawing-set", "set:road-project:set-a", "--rule-version", "rules-v1"],
            config_loader=lambda: FakeConfig(),
            repository_factory=lambda config: repository,
            service_factory=FakeService,
            batch_id_factory=lambda: "relation-batch:test",
        )

        self.assertEqual(0, exit_code)
        mode, scope = repository.services[0].calls[0]
        self.assertEqual("drawing-set", mode)
        self.assertEqual("set:road-project:set-a", scope.drawing_set_id)
        self.assertIsNone(scope.page_id)

    def test_page_scope_calls_page_service(self):
        module = _load_relation_cli()
        repository = FakeRepository()

        exit_code = _run_main(
            module,
            ["page", "page:road-project:set-a:road_1", "--rule-version", "rules-v1"],
            config_loader=lambda: FakeConfig(),
            repository_factory=lambda config: repository,
            service_factory=FakeService,
            batch_id_factory=lambda: "relation-batch:test",
        )

        self.assertEqual(0, exit_code)
        mode, scope = repository.services[0].calls[0]
        self.assertEqual("page", mode)
        self.assertEqual("page:road-project:set-a:road_1", scope.page_id)
        self.assertIsNone(scope.drawing_set_id)

    def test_all_scopes_print_section_mark_and_table_summary_fields(self):
        module = _load_relation_cli()

        for argv in (
            ["project", "--rule-version", "rules-v1"],
            ["drawing-set", "set:road-project:set-a", "--rule-version", "rules-v1"],
            ["page", "page:road-project:set-a:road_1", "--rule-version", "rules-v1"],
        ):
            with self.subTest(argv=argv):
                exit_code, stdout, stderr = _run_main_with_output(
                    module,
                    argv,
                    config_loader=lambda: FakeConfig(),
                    repository_factory=lambda config: FakeRepository(),
                    service_factory=FakeService,
                    batch_id_factory=lambda: "relation-batch:test",
                )

                self.assertEqual(0, exit_code)
                self.assertEqual("", stderr)
                self.assertIn("'cross_section_count': 0", stdout)
                self.assertIn("'table_count': 0", stdout)
                self.assertIn("'table_caption_count': 0", stdout)
                self.assertIn("'table_caption_relation_count': 0", stdout)
                self.assertIn("'uses_basic_info_count': 0", stdout)
                self.assertIn("'candidate_count': 0", stdout)
                self.assertIn("'ambiguous_count': 0", stdout)
                self.assertIn("'not_evaluated_count': 0", stdout)
                self.assertIn("'relation_count': 0", stdout)
                self.assertIn("'issue_summary': {}", stdout)

    def test_help_text_states_enrichment_does_not_auto_review_candidates(self):
        module = _load_relation_cli()

        exit_code, stdout, stderr = _run_main_with_output(module, ["--help"])

        self.assertEqual(0, exit_code)
        self.assertEqual("", stderr)
        self.assertIn("does not automatically run AI candidate review", stdout)

    def test_missing_rule_version_returns_two_before_service_creation(self):
        module = _load_relation_cli()
        created_repositories = []

        exit_code = _run_main(
            module,
            ["project"],
            config_loader=lambda: FakeConfig(),
            repository_factory=lambda config: created_repositories.append(FakeRepository()),
            service_factory=FakeService,
        )

        self.assertEqual(2, exit_code)
        self.assertEqual([], created_repositories)

    def test_invalid_arguments_return_two_before_service_creation(self):
        module = _load_relation_cli()
        created_repositories = []

        exit_code = _run_main(
            module,
            ["page", "--rule-version", "rules-v1"],
            config_loader=lambda: FakeConfig(),
            repository_factory=lambda config: created_repositories.append(FakeRepository()),
            service_factory=FakeService,
        )

        self.assertEqual(2, exit_code)
        self.assertEqual([], created_repositories)

    def test_missing_config_returns_two_without_password_leak(self):
        module = _load_relation_cli()

        exit_code, stdout, stderr = _run_main_with_output(
            module,
            ["project", "--rule-version", "rules-v1"],
            config_loader=lambda: (_ for _ in ()).throw(RuntimeError("missing password=secret")),
            repository_factory=lambda config: FakeRepository(),
            service_factory=FakeService,
        )

        self.assertEqual(2, exit_code)
        self.assertEqual("", stdout)
        self.assertNotIn("secret", stderr)

    def test_failed_batch_returns_non_zero(self):
        module = _load_relation_cli()

        exit_code = _run_main(
            module,
            ["project", "--rule-version", "rules-v1"],
            config_loader=lambda: FakeConfig(),
            repository_factory=lambda config: FakeRepository(),
            service_factory=FailingBatchService,
            batch_id_factory=lambda: "relation-batch:failed",
        )

        self.assertEqual(1, exit_code)

    def test_service_exception_returns_non_zero(self):
        module = _load_relation_cli()

        exit_code = _run_main(
            module,
            ["project", "--rule-version", "rules-v1"],
            config_loader=lambda: FakeConfig(),
            repository_factory=lambda config: FakeRepository(),
            service_factory=RaisingService,
            batch_id_factory=lambda: "relation-batch:failed",
        )

        self.assertEqual(1, exit_code)


def _load_relation_cli():
    module_name = "drawing_graph_relation_cli_under_test"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _run_main(module, argv, **kwargs):
    exit_code, _, _ = _run_main_with_output(module, argv, **kwargs)
    return exit_code


def _run_main_with_output(module, argv, **kwargs):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = module.main(argv, **kwargs)
    return exit_code, stdout.getvalue(), stderr.getvalue()


if __name__ == "__main__":
    unittest.main()
