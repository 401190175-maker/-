import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "review_candidate_relations.py"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class FakeConfig:
    project_slug = "road-project"
    neo4j_uri = "bolt://example"
    neo4j_user = "neo4j"
    neo4j_password = "secret"


class FakeRepository:
    def update_candidate_review(self, **kwargs):
        self.review_update = kwargs

    def promote_candidate_relation(self, **kwargs):
        self.promotion = kwargs


class FakeClient:
    def review(self, request):
        return {
            "status": "accepted",
            "accepted_candidate_id": "candidate:caption:1:block:1",
            "model_version": "vision-model-v1",
            "prompt_version": "candidate-review-v1",
            "score": 0.9,
            "reason": "best candidate",
        }


class CandidateReviewCliTest(unittest.TestCase):
    def test_candidate_group_scope_triggers_explicit_review_and_prints_status(self):
        module = _load_candidate_review_cli()

        exit_code, stdout, stderr = _run_main_with_output(
            module,
            [
                "candidate-group",
                "--relation-spec",
                "candidate_caption_of",
                "--group-key",
                "caption:1",
                "--source-element-id",
                "caption:1",
                "--page-id",
                "page:road:set-a:road_24",
                "--rule-version",
                "relation-rules-v1",
                "--review-run-id",
                "review-run:test",
                "--candidate",
                "candidate:caption:1:block:1,caption:1,block:1",
                "--evidence-ref",
                "crop:caption:1",
            ],
            config_loader=lambda: FakeConfig(),
            repository_factory=lambda config: FakeRepository(),
            review_client_factory=lambda config: FakeClient(),
        )

        self.assertEqual(0, exit_code)
        self.assertEqual("", stderr)
        self.assertIn("'review_run_id': 'review-run:test'", stdout)
        self.assertIn("'review_status': 'accepted'", stdout)
        self.assertIn("'accepted_candidate_id': 'candidate:caption:1:block:1'", stdout)

    def test_missing_required_arguments_return_two_before_service_creation(self):
        module = _load_candidate_review_cli()
        created_repositories = []

        exit_code = _run_main(
            module,
            ["candidate-group", "--relation-spec", "candidate_caption_of"],
            config_loader=lambda: FakeConfig(),
            repository_factory=lambda config: created_repositories.append(FakeRepository()),
            review_client_factory=lambda config: FakeClient(),
        )

        self.assertEqual(2, exit_code)
        self.assertEqual([], created_repositories)

    def test_config_error_is_sanitized(self):
        module = _load_candidate_review_cli()

        exit_code, stdout, stderr = _run_main_with_output(
            module,
            [
                "candidate-group",
                "--relation-spec",
                "candidate_caption_of",
                "--group-key",
                "caption:1",
                "--source-element-id",
                "caption:1",
                "--page-id",
                "page:road:set-a:road_24",
                "--rule-version",
                "relation-rules-v1",
                "--review-run-id",
                "review-run:test",
                "--candidate",
                "candidate:caption:1:block:1,caption:1,block:1",
                "--evidence-ref",
                "crop:caption:1",
            ],
            config_loader=lambda: (_ for _ in ()).throw(RuntimeError("password=secret")),
            repository_factory=lambda config: FakeRepository(),
            review_client_factory=lambda config: FakeClient(),
        )

        self.assertEqual(2, exit_code)
        self.assertEqual("", stdout)
        self.assertNotIn("secret", stderr)

    def test_help_text_explains_review_statuses(self):
        module = _load_candidate_review_cli()

        exit_code, stdout, stderr = _run_main_with_output(module, ["--help"])

        self.assertEqual(0, exit_code)
        self.assertEqual("", stderr)
        self.assertIn("accepted", stdout)
        self.assertIn("rejected", stdout)
        self.assertIn("unresolved", stdout)


def _load_candidate_review_cli():
    module_name = "drawing_graph_candidate_review_cli_under_test"
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
