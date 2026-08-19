"""Security and output-minimization tests for the 06 answer-generation layer."""

import unittest

from drawing_graph.assistant_answer_generation import (
    AnswerGenerationService,
    AnswerValidationError,
)
from drawing_graph.assistant_evidence_fusion_models import (
    Answerability,
    AnswerabilityResult,
    ClaimCapability,
    ClaimSupportAssessment,
    ClaimSupportStatus,
    EvidenceBundle,
    FusionEvidence,
    FusionMetadata,
)
from drawing_graph.assistant_models import (
    AnswerGenerationRequest,
    AssistantRequest,
    AssistantScope,
    EvidenceItem,
    EvidenceRequirement,
    EvidenceType,
    FactKind,
    QuestionUnderstandingResult,
    ReasonCode,
)


class AnswerOutputSecurityTests(unittest.TestCase):
    def _sensitive_request(self):
        fusion = FusionEvidence(
            item=EvidenceItem(
                evidence_id="evidence:1",
                fact_kind=FactKind.SEMANTIC_OBSERVATION,
                scope=AssistantScope(page_id="page:1", element_id="element:1"),
                value={
                    "observation_id": "obs:1",
                    "image_path": "C:/secret/image.png",
                    "database_uri": "bolt://user:pass@host:7687",
                    "full_payload": {"secret": "token-12345"},
                },
                payload_ref="payload:1",
                evidence_metadata={
                    "cypher": "MATCH (n) RETURN n",
                    "api_key": "key-abc",
                },
            ),
            metadata=FusionMetadata(),
        )
        assessment = ClaimSupportAssessment(
            requirement_id="req:1",
            claim_capability=ClaimCapability.OBSERVED_TEXT_OR_SYMBOL,
            status=ClaimSupportStatus.SUPPORTED,
            supporting_evidence_ids=("evidence:1",),
        )
        bundle = EvidenceBundle(
            request_id="req:1",
            accepted_evidence=(fusion,),
            claim_support=(assessment,),
            answerability=AnswerabilityResult(status=Answerability.ANSWERABLE),
        )
        question_result = QuestionUnderstandingResult(
            request_id="req:1",
            question_type="page_summary",
            required_evidence=(
                EvidenceRequirement(
                    requirement_id="req:1",
                    evidence_type=EvidenceType.TEXT_OBSERVATIONS,
                    target_scope=AssistantScope(page_id="page:1", element_id="element:1"),
                ),
            ),
        )
        return AnswerGenerationRequest(
            assistant_request=AssistantRequest(request_id="req:1", question="q"),
            question_result=question_result,
            evidence_bundle=bundle,
        )

    def test_sensitive_fields_absent_from_json(self):
        service = AnswerGenerationService()
        package = service.generate(self._sensitive_request())
        json_text = service.serializer.serialize(package.machine_answer)
        self.assertNotIn("secret", json_text)
        self.assertNotIn("image.png", json_text)
        self.assertNotIn("bolt://", json_text)
        self.assertNotIn("MATCH", json_text)
        self.assertNotIn("token-12345", json_text)
        self.assertNotIn("key-abc", json_text)

    def test_payload_ref_preserved_but_not_dereferenced(self):
        service = AnswerGenerationService()
        package = service.generate(self._sensitive_request())
        citation = package.citations[0]
        self.assertEqual("payload:1", citation.payload_ref)
        self.assertNotIn("full_payload", service.serializer.serialize(package.machine_answer))

    def test_error_message_is_safe_and_stable(self):
        error = AnswerValidationError(
            "evidence bundle is required",
            ReasonCode.ANSWER_VALIDATION_FAILED,
        )
        self.assertEqual(ReasonCode.ANSWER_VALIDATION_FAILED, error.reason_code)
        message = str(error).lower()
        self.assertNotIn("secret", message)
        self.assertNotIn("traceback", message)
        self.assertNotIn("c:\\", message)


if __name__ == "__main__":
    unittest.main()
