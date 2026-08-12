"""Static boundary tests for product assistant retrieval modules."""

from pathlib import Path
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "src" / "drawing_graph"
ASSISTANT_PATTERN = "assistant_*.py"

FORBIDDEN_TOKENS = (
    "neo4j",
    "graphdatabase",
    "session",
    "transaction",
    "MATCH (",
    "MERGE ",
    "CREATE ",
    "relationrepository",
    "neo4jrepository",
    "semanticneo4jrepository",
    "candidatereviewservice",
    "scripts.import_json",
    "scripts.enrich_block_relations",
    "scripts.review_candidate_relations",
)

FORBIDDEN_CALLS = (
    "recognize_page_semantics(",
    "review_candidate_relation(",
    "write_back=True",
)


def assistant_sources() -> list[tuple[Path, str]]:
    sources = []
    for path in sorted(SOURCE_DIR.glob(ASSISTANT_PATTERN)):
        sources.append((path, path.read_text(encoding="utf-8")))
    return sources


class AssistantBoundaryTests(unittest.TestCase):
    def test_assistant_modules_avoid_forbidden_backend_tokens(self):
        sources = assistant_sources()
        self.assertTrue(sources)
        for path, source in sources:
            lowered = source.lower()
            for token in FORBIDDEN_TOKENS:
                self.assertNotIn(
                    token.lower(),
                    lowered,
                    f"{path.name} must not contain {token!r}",
                )

    def test_assistant_modules_never_call_recognition_review_or_write_back(self):
        sources = assistant_sources()
        for path, source in sources:
            for token in FORBIDDEN_CALLS:
                self.assertNotIn(
                    token,
                    source,
                    f"{path.name} must not contain {token!r}",
                )

    def test_qa_service_does_not_import_assistant_modules(self):
        qa_service_path = SOURCE_DIR / "qa_service.py"
        source = qa_service_path.read_text(encoding="utf-8")
        self.assertNotIn("assistant_", source)

    def test_assistant_qa_mapping_is_allowed_to_import_qa_models(self):
        mapping_path = SOURCE_DIR / "assistant_qa_mapping.py"
        source = mapping_path.read_text(encoding="utf-8")
        self.assertIn("qa_models", source)


if __name__ == "__main__":
    unittest.main()
