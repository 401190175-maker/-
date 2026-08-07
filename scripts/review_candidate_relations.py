"""Explicit CLI for reviewing persisted candidate relations."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from drawing_graph.candidate_review import CandidateReviewRequest, CandidateReviewService
from drawing_graph.config import ImportConfig
from drawing_graph.relation_repository import RelationRepository


def main(
    argv: list[str] | None = None,
    *,
    config_loader: Any = ImportConfig.from_env,
    repository_factory: Any | None = None,
    review_client_factory: Any | None = None,
    service_factory: Any = CandidateReviewService,
) -> int:
    """Parse CLI arguments and explicitly review one complete candidate group."""

    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code)

    try:
        config = config_loader()
    except Exception as error:  # pragma: no cover - exact config failures depend on environment
        _print_error("config_error", error)
        return 2

    try:
        repository = (
            repository_factory(config) if repository_factory is not None else _build_repository(config)
        )
        review_client = (
            review_client_factory(config) if review_client_factory is not None else _missing_review_client()
        )
        service = service_factory(review_client, repository=repository)
        result = service.review_candidate_group(_build_request(args))
    except Exception as error:
        _print_error("candidate_review_failed", error)
        return 1

    print(_result_for_output(result))
    return 0 if result.issue_category is None else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Explicitly review CANDIDATE_* relations. Review statuses are "
            "accepted, rejected, or unresolved."
        )
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)
    group_parser = subparsers.add_parser("candidate-group", help="Review one complete candidate group.")
    group_parser.add_argument("--relation-spec", required=True, choices=("candidate_caption_of", "candidate_section_mark"))
    group_parser.add_argument("--group-key", required=True)
    group_parser.add_argument("--source-element-id", required=True)
    group_parser.add_argument("--page-id", required=True)
    group_parser.add_argument("--rule-version", required=True)
    group_parser.add_argument("--review-run-id", required=True)
    group_parser.add_argument(
        "--candidate",
        required=True,
        action="append",
        help="Candidate tuple: candidate_id,start_id,end_id",
    )
    group_parser.add_argument("--evidence-ref", required=True, action="append")
    return parser


def _build_repository(config: Any) -> RelationRepository:
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(config.neo4j_uri, auth=(config.neo4j_user, config.neo4j_password))
    return RelationRepository(driver)


def _missing_review_client() -> Any:
    raise RuntimeError("candidate review client is not configured")


def _build_request(args: argparse.Namespace) -> CandidateReviewRequest:
    return CandidateReviewRequest(
        review_run_id=args.review_run_id,
        relation_spec=args.relation_spec,
        group_key=args.group_key,
        source_element_id=args.source_element_id,
        page_id=args.page_id,
        rule_version=args.rule_version,
        candidates=tuple(_parse_candidate(value, args.relation_spec, args.page_id) for value in args.candidate),
        evidence_refs=tuple(args.evidence_ref),
    )


def _parse_candidate(value: str, relation_spec: str, page_id: str) -> dict[str, object]:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 3 or any(not part for part in parts):
        raise ValueError("--candidate must use candidate_id,start_id,end_id")
    return {
        "candidate_id": parts[0],
        "start_id": parts[1],
        "end_id": parts[2],
        "page_id": page_id,
        "relation_spec": relation_spec,
    }


def _result_for_output(result: Any) -> dict[str, object]:
    return {
        "review_run_id": result.review_run_id,
        "review_status": result.status,
        "accepted_candidate_id": result.accepted_candidate_id,
        "issue_category": result.issue_category,
    }


def _print_error(category: str, error: Exception) -> None:
    print(f"{category}: {_sanitize_message(str(error))}", file=sys.stderr)


def _sanitize_message(message: str) -> str:
    if "password" in message.lower():
        return "sensitive configuration value is missing or invalid"
    return message


if __name__ == "__main__":
    raise SystemExit(main())
