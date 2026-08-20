"""Contract tests for the page_content_search question type."""

from __future__ import annotations

import unittest

from drawing_graph.assistant_clarification import _REQUIRED_SCOPE_FIELDS
from drawing_graph.assistant_evidence_templates import EvidenceRequirementFactory
from drawing_graph.assistant_models import (
    AssistantRequest,
    AssistantScope,
    EvidenceType,
    QuestionType,
)


def _request() -> AssistantRequest:
    return AssistantRequest(request_id="req:search-contract", question="哪些图关于排水")


class PageContentSearchContractTests(unittest.TestCase):
    def test_question_type_value(self) -> None:
        self.assertEqual(QuestionType.PAGE_CONTENT_SEARCH.value, "page_content_search")

    def test_evidence_template_maps_to_search_evidence(self) -> None:
        factory = EvidenceRequirementFactory()
        requirements = factory.build(
            QuestionType.PAGE_CONTENT_SEARCH,
            AssistantScope(drawing_set_id="set:road-project:lslq_yhd_2_2"),
            _request(),
        )
        types = tuple(item.evidence_type for item in requirements)
        self.assertEqual(
            types,
            (
                EvidenceType.DRAWING_SET_PAGES,
                EvidenceType.PAGE_SOURCE_FACTS,
                EvidenceType.TEXT_OBSERVATIONS,
                EvidenceType.STRUCTURED_INTERPRETATIONS,
            ),
        )

    def test_clarification_requires_drawing_set_id(self) -> None:
        self.assertEqual(_REQUIRED_SCOPE_FIELDS["page_content_search"], ("drawing_set_id",))


if __name__ == "__main__":
    unittest.main()
