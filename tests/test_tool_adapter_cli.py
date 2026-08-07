import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "drawing_graph_tool.py"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from drawing_graph.tool_models import (
    BBox,
    CandidateRelationSummary,
    DrawingSetSummary,
    SectionMatchSummary,
    SemanticObservationSummary,
    ToolModelError,
)


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
    def __init__(self):
        self.calls = []

    def list_drawing_sets(self, project_id, limit=100):
        self.calls.append(("list_drawing_sets", project_id, limit))
        return (DrawingSetSummary(project_id, "set:1", "第一册", page_count=2),)

    def list_text_observations(self, page_id=None, element_id=None, recognition_run_id=None, statuses=None):
        self.calls.append(("list_text_observations", page_id, element_id, recognition_run_id, statuses))
        return (
            SemanticObservationSummary(
                observation_id="obs:1",
                recognition_run_id="run:1",
                target_element_id="caption:1",
                target_element_type="BlockCaption",
                page_id=page_id or "page:1",
                raw_text="1-1",
                normalized_text="SECTION_1",
                bbox=BBox(1, 2, 3, 4),
                normalized_bbox=BBox(0.1, 0.2, 0.3, 0.4),
                confidence=0.88,
                status="confirmed",
                persisted=True,
            ),
        )

    def list_candidate_relations(self, page_id=None, block_id=None, relation_type=None, status=None):
        self.calls.append(("list_candidate_relations", page_id, block_id, relation_type, status))
        return (
            CandidateRelationSummary(
                candidate_group_id="group:1",
                page_id=page_id or "page:1",
                block_id=block_id or "block:1",
                relation_type=relation_type or "candidate_caption_of",
                status=status or "candidate",
            ),
        )

    def list_section_matches(self, cross_section_id=None, page_id=None, statuses=None):
        self.calls.append(("list_section_matches", cross_section_id, page_id, statuses))
        return (
            SectionMatchSummary(
                cross_section_id=cross_section_id or "cross:1",
                match_status="formal",
                matched_caption_ids=("caption:1",),
                candidate_count=1,
                fact_kind="formal_relation",
                status="confirmed",
            ),
        )


class DrawingGraphToolCliTest(unittest.TestCase):
    def test_list_drawing_sets_builds_driver_and_prints_json(self):
        module = _load_tool_cli()
        fake_driver = FakeDriver()
        fake_facade = FakeFacade()

        exit_code, stdout, stderr = _run_main_with_output(
            module,
            ["list-drawing-sets", "--project-id", "road-project", "--limit", "5"],
            config_loader=lambda: FakeConfig(),
            driver_factory=lambda uri, auth: fake_driver,
            facade_factory=lambda driver: fake_facade,
        )

        self.assertEqual(0, exit_code)
        self.assertEqual("", stderr)
        payload = json.loads(stdout)
        self.assertEqual("ok", payload["status"])
        self.assertEqual("set:1", payload["data"][0]["drawing_set_id"])
        self.assertEqual([["list_drawing_sets", "road-project", 5]], [list(call) for call in fake_facade.calls])
        self.assertTrue(fake_driver.closed)

    def test_text_observation_query_maps_exactly_one_filter_and_statuses(self):
        module = _load_tool_cli()
        fake_facade = FakeFacade()

        exit_code, stdout, stderr = _run_main_with_output(
            module,
            [
                "list-text-observations",
                "--page-id",
                "page:1",
                "--status",
                "confirmed",
                "--status",
                "partial",
            ],
            config_loader=lambda: FakeConfig(),
            driver_factory=lambda uri, auth: FakeDriver(),
            facade_factory=lambda driver: fake_facade,
        )

        self.assertEqual(0, exit_code)
        self.assertEqual("", stderr)
        payload = json.loads(stdout)
        self.assertEqual("obs:1", payload["data"][0]["observation_id"])
        self.assertEqual(
            [("list_text_observations", "page:1", None, None, ("confirmed", "partial"))],
            fake_facade.calls,
        )

    def test_facade_error_is_sanitized_and_returns_non_zero(self):
        module = _load_tool_cli()

        class FailingFacade:
            def list_drawing_sets(self, project_id, limit=100):
                raise ToolModelError("NEO4J_UNAVAILABLE", "password=secret MATCH leak")

        exit_code, stdout, stderr = _run_main_with_output(
            module,
            ["list-drawing-sets", "--project-id", "road-project"],
            config_loader=lambda: FakeConfig(),
            driver_factory=lambda uri, auth: FakeDriver(),
            facade_factory=lambda driver: FailingFacade(),
        )

        self.assertEqual(1, exit_code)
        self.assertEqual("", stdout)
        payload = json.loads(stderr)
        self.assertEqual("NEO4J_UNAVAILABLE", payload["category"])
        self.assertNotIn("secret", stderr)
        self.assertNotIn("MATCH", stderr)

    def test_normal_not_found_message_is_not_sanitized_as_backend_detail(self):
        module = _load_tool_cli()

        class NotFoundFacade:
            def list_section_matches(self, cross_section_id=None, page_id=None, statuses=None):
                raise ToolModelError("NOT_FOUND", "section matches were not found")

        exit_code, stdout, stderr = _run_main_with_output(
            module,
            ["list-section-matches", "--page-id", "page:1"],
            config_loader=lambda: FakeConfig(),
            driver_factory=lambda uri, auth: FakeDriver(),
            facade_factory=lambda driver: NotFoundFacade(),
        )

        self.assertEqual(1, exit_code)
        self.assertEqual("", stdout)
        payload = json.loads(stderr)
        self.assertEqual("NOT_FOUND", payload["category"])
        self.assertEqual("section matches were not found", payload["message"])

    def test_candidate_relation_command_maps_filters_to_facade(self):
        module = _load_tool_cli()
        fake_facade = FakeFacade()

        exit_code, stdout, stderr = _run_main_with_output(
            module,
            [
                "list-candidate-relations",
                "--page-id",
                "page:1",
                "--relation-type",
                "candidate_caption_of",
                "--status",
                "candidate",
            ],
            config_loader=lambda: FakeConfig(),
            driver_factory=lambda uri, auth: FakeDriver(),
            facade_factory=lambda driver: fake_facade,
        )

        self.assertEqual(0, exit_code)
        self.assertEqual("", stderr)
        payload = json.loads(stdout)
        self.assertEqual("group:1", payload["data"][0]["candidate_group_id"])
        self.assertEqual(
            [("list_candidate_relations", "page:1", None, "candidate_caption_of", "candidate")],
            fake_facade.calls,
        )

    def test_section_match_command_maps_filters_to_facade(self):
        module = _load_tool_cli()
        fake_facade = FakeFacade()

        exit_code, stdout, stderr = _run_main_with_output(
            module,
            [
                "list-section-matches",
                "--cross-section-id",
                "cross:1",
                "--status",
                "candidate",
                "--status",
                "confirmed",
            ],
            config_loader=lambda: FakeConfig(),
            driver_factory=lambda uri, auth: FakeDriver(),
            facade_factory=lambda driver: fake_facade,
        )

        self.assertEqual(0, exit_code)
        self.assertEqual("", stderr)
        payload = json.loads(stdout)
        self.assertEqual("cross:1", payload["data"][0]["cross_section_id"])
        self.assertEqual(
            [("list_section_matches", "cross:1", None, ("candidate", "confirmed"))],
            fake_facade.calls,
        )

    def test_config_error_is_sanitized_before_driver_creation(self):
        module = _load_tool_cli()
        created_drivers = []

        exit_code, stdout, stderr = _run_main_with_output(
            module,
            ["list-drawing-sets", "--project-id", "road-project"],
            config_loader=lambda: (_ for _ in ()).throw(RuntimeError("password=secret")),
            driver_factory=lambda uri, auth: created_drivers.append(FakeDriver()),
            facade_factory=lambda driver: FakeFacade(),
        )

        self.assertEqual(2, exit_code)
        self.assertEqual("", stdout)
        self.assertEqual([], created_drivers)
        self.assertNotIn("secret", stderr)


def _load_tool_cli():
    module_name = "drawing_graph_tool_cli_under_test"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _run_main_with_output(module, argv, **kwargs):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = module.main(argv, **kwargs)
    return exit_code, stdout.getvalue(), stderr.getvalue()


if __name__ == "__main__":
    unittest.main()
