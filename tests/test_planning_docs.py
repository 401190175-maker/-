import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLANNING_DOCS = ("proposal.md", "design.md", "tasks.md")


def _read_planning_doc(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        raise AssertionError(f"missing planning document: {name}")
    return path.read_text(encoding="utf-8")


class PlanningDocsConsistencyTests(unittest.TestCase):
    def test_planning_docs_cover_target_relations_and_ai_review(self):
        required_keywords = (
            "USES_BASIC_INFO",
            "CANDIDATE_CAPTION_OF",
            "CANDIDATE_HAS_SECTION_MARK",
            "AI 复核",
            "review_run_id",
            "规划边界",
            "不声称代码已实现",
        )

        missing = {
            name: [keyword for keyword in required_keywords if keyword not in _read_planning_doc(name)]
            for name in PLANNING_DOCS
        }
        missing = {name: keywords for name, keywords in missing.items() if keywords}

        self.assertEqual(
            {},
            missing,
            f"missing required planning keywords by file: {missing}",
        )

    def test_planning_docs_do_not_restore_block_basic_info_as_target_relation(self):
        legacy_relation = "DrawingBlock -[:HAS_BASIC_INFO]-> DrawingBasicInfo"
        forbidden_context = "目标关系"
        allowed_context_markers = (
            "不再作为目标关系",
            "不是目标关系",
            "旧实现",
            "历史实现",
            "迁移兼容",
            "不把",
        )

        offending = {}
        for name in PLANNING_DOCS:
            text = _read_planning_doc(name)
            for line_number, line in enumerate(text.splitlines(), start=1):
                if legacy_relation not in line:
                    continue
                if forbidden_context in line and not any(marker in line for marker in allowed_context_markers):
                    offending.setdefault(name, []).append(f"line {line_number}: {line}")

        self.assertEqual(
            {},
            offending,
            f"legacy block basic-info relation must not be documented as target relation: {offending}",
        )

if __name__ == "__main__":
    unittest.main()
