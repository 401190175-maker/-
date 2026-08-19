"""Answer generation (06) deterministic collaborators.

本模块是 06 的确定性内核：答案状态解析、权威 MachineAnswer 构造、canonical
JSON 序列化与 AnswerPackage 一致性校验。所有协作者只消费 DTO，不执行持久化
查询、不调用视觉识别、不执行写回、不提升候选关系、不调用文本模型。
"""

from __future__ import annotations

import dataclasses
import json
from enum import Enum
from typing import Any, Mapping, Sequence

from .assistant_evidence_fusion_models import Answerability, AnswerabilityResult
from .assistant_models import (
    ANSWER_CONTRACT_VERSION,
    AnswerGenerationPolicy,
    AnswerGenerationRequest,
    AnswerPackage,
    AnswerStatus,
    Citation,
    Claim,
    ClaimStatus,
    FactKind,
    MachineAnswer,
    QuestionType,
    ReasonCode,
    RecognitionFailure,
    TextRenderMode,
)
from .qa_serialization import to_jsonable
from .assistant_claim_builder import ClaimBuilder
from .assistant_citation_builder import CitationBuilder, bind_claim_citations
from .assistant_answer_templates import ChineseAnswerTemplateRenderer
from .assistant_answer_text import (
    ConstrainedAnswerTextGenerator,
    ConstrainedClaimInput,
    ConstrainedTextRequest,
    ConstrainedTextValidator,
    render_text_with_fallback,
)


class AnswerValidationError(ValueError):
    """答案合同一致性校验失败时抛出的稳定错误。"""

    def __init__(self, message: str, reason_code: ReasonCode | None = None):
        self.reason_code = reason_code
        super().__init__(message)


_SEMANTIC_KINDS = frozenset(
    {FactKind.SEMANTIC_OBSERVATION, FactKind.SEMANTIC_INTERPRETATION}
)


def _is_diagnostic_claim(claim: Claim) -> bool:
    status = claim.status
    return status == ClaimStatus.DIAGNOSTIC.value or status is ClaimStatus.DIAGNOSTIC


def _has_semantic_kind(claim: Claim) -> bool:
    return any(kind in _SEMANTIC_KINDS for kind in claim.fact_kinds)


class AnswerStatusResolver:
    """按 answerability、claim、冲突与识别失败解析唯一 AnswerStatus。

    优先级与 design 6.3 一致：clarification -> unsupported -> recognition_failed
    -> partial -> answered；不按异常文案推导状态。
    """

    def resolve(
        self,
        answerability: AnswerabilityResult | None,
        claims: Sequence[Claim] = (),
        recognition_failures: Sequence[RecognitionFailure] = (),
        blocking_conflicts: bool = False,
    ) -> AnswerStatus:
        engineering = [claim for claim in claims if not _is_diagnostic_claim(claim)]
        semantic = [claim for claim in engineering if _has_semantic_kind(claim)]
        status = answerability.status if answerability is not None else None

        if status is Answerability.CLARIFICATION_REQUIRED and not engineering:
            return AnswerStatus.CLARIFICATION_REQUIRED

        if status is Answerability.UNSUPPORTED and not engineering:
            return AnswerStatus.UNSUPPORTED

        if recognition_failures and not semantic:
            return AnswerStatus.RECOGNITION_FAILED

        if (
            blocking_conflicts
            or recognition_failures
            or status is Answerability.PARTIALLY_ANSWERABLE
            or (
                status in (Answerability.UNSUPPORTED, Answerability.CLARIFICATION_REQUIRED)
                and engineering
            )
        ):
            return AnswerStatus.PARTIAL

        return AnswerStatus.ANSWERED


def _claim_sort_key(claim: Claim) -> tuple:
    return (claim.subrequest_id or "", claim.claim_id)


def _reason_value(code: ReasonCode | str) -> str:
    return code.value if isinstance(code, ReasonCode) else str(code)


def _warning_key(value: object) -> str:
    if isinstance(value, str):
        return value
    reason = getattr(value, "reason_code", None)
    reason_value = reason.value if isinstance(reason, Enum) else str(reason or "")
    message = getattr(value, "message", "")
    return f"{reason_value}:{message}"


def _dedup_sorted_strings(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted(dict.fromkeys(str(value) for value in values)))


class MachineAnswerBuilder:
    """从同一组已批准输出构造权威 ``MachineAnswer``，稳定排序全部集合。"""

    def build(
        self,
        *,
        request_id: str,
        question_type: str,
        scope: Any = None,
        status: AnswerStatus | str,
        claims: Sequence[Claim] = (),
        citations: Sequence[Citation] = (),
        subanswers: Sequence[object] = (),
        warnings: Sequence[object] = (),
        unsupported_parts: Sequence[str] = (),
        recognition_run_ids: Sequence[str] = (),
        follow_up_actions: Sequence[str] = (),
        reason_codes: Sequence[ReasonCode | str] = (),
    ) -> MachineAnswer:
        return MachineAnswer(
            answer_contract_version=ANSWER_CONTRACT_VERSION,
            request_id=request_id,
            question_type=question_type,
            scope=scope,
            status=status,
            subanswers=tuple(subanswers),
            claims=tuple(sorted(claims, key=_claim_sort_key)),
            citations=tuple(citations),
            warnings=tuple(sorted(dict.fromkeys(_warning_key(item) for item in warnings))),
            unsupported_parts=_dedup_sorted_strings(unsupported_parts),
            recognition_run_ids=_dedup_sorted_strings(recognition_run_ids),
            follow_up_actions=_dedup_sorted_strings(follow_up_actions),
            reason_codes=tuple(
                sorted(
                    dict.fromkeys(
                        ReasonCode(code) if not isinstance(code, ReasonCode) else code
                        for code in reason_codes
                    ),
                    key=_reason_value,
                )
            ),
        )


class CanonicalAnswerSerializer:
    """把 ``MachineAnswer`` 序列化为字节一致的 UTF-8 产品答案 JSON。

    复用 ``to_jsonable`` 的 JSON-safe 转换，采用 ``ensure_ascii=False`` 与固定
    separators，并拒绝 NaN/Infinity 与不可序列化对象。
    """

    def serialize(self, machine_answer: MachineAnswer) -> str:
        jsonable = to_jsonable(machine_answer)
        return json.dumps(
            jsonable,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )


class AnswerPackageValidator:
    """校验 AnswerPackage 顶层字段与 machine_answer 同源且 claim/citation 一致。

    双份数据不一致、孤立引用、非法事实提升均 fail closed；合法 package 不被修改。
    """

    def validate(self, package: AnswerPackage) -> None:
        if package.answer_contract_version != ANSWER_CONTRACT_VERSION:
            raise AnswerValidationError(
                "answer contract version mismatch: "
                f"{package.answer_contract_version!r}"
            )
        machine = package.machine_answer
        if isinstance(machine, MachineAnswer):
            self._validate_machine_consistency(package, machine)
            self.validate_machine_answer(machine)
        else:
            self._validate_claims_citations(package.claims, package.citations)

    @staticmethod
    def validate_machine_answer(machine: MachineAnswer) -> None:
        """在渲染前校验 machine answer 的 claim/citation 完整性与事实等级。"""

        AnswerPackageValidator._validate_claims_citations(machine.claims, machine.citations)
        for claim in machine.claims:
            AnswerPackageValidator._validate_fact_level(claim)

    @staticmethod
    def _validate_machine_consistency(package: AnswerPackage, machine: MachineAnswer) -> None:
        if package.status != machine.status.value:
            raise AnswerValidationError(
                f"status mismatch: package={package.status!r} machine={machine.status.value!r}"
            )
        if tuple(package.claims) != tuple(machine.claims):
            raise AnswerValidationError("claims mismatch between package and machine_answer")
        if tuple(package.citations) != tuple(machine.citations):
            raise AnswerValidationError("citations mismatch between package and machine_answer")

    @staticmethod
    def _validate_claims_citations(
        claims: Sequence[Claim],
        citations: Sequence[Citation],
    ) -> None:
        claim_ids = {claim.claim_id for claim in claims}
        citation_ids = {citation.citation_id for citation in citations}
        for claim in claims:
            for citation_id in claim.citation_ids:
                if citation_id not in citation_ids:
                    raise AnswerValidationError(
                        f"claim {claim.claim_id} references unknown citation {citation_id}"
                    )
        for citation in citations:
            for claim_id in citation.claim_ids:
                if claim_id not in claim_ids:
                    raise AnswerValidationError(
                        f"citation {citation.citation_id} references unknown claim {claim_id}"
                    )
        for claim in claims:
            if not _is_diagnostic_claim(claim) and not claim.citation_ids:
                raise AnswerValidationError(
                    f"non-diagnostic claim {claim.claim_id} has no citation"
                )

    @staticmethod
    def _validate_fact_level(claim: Claim) -> None:
        kinds = set(claim.fact_kinds)
        candidate_only = (
            FactKind.CANDIDATE_RELATION in kinds
            and FactKind.FORMAL_RELATION not in kinds
        )
        if (
            candidate_only
            and claim.claim_type == "confirmed_relation"
            and claim.status == "supported"
        ):
            raise AnswerValidationError("candidate relation promoted to confirmed relation")
        if (
            FactKind.SEMANTIC_INTERPRETATION in kinds
            and claim.claim_type == "identity_and_location"
        ):
            raise AnswerValidationError("semantic interpretation written as source fact")


_TERMINAL_QUESTION_TYPES = frozenset(
    {
        QuestionType.CLARIFICATION_REQUIRED.value,
        QuestionType.UNKNOWN_OR_UNSUPPORTED.value,
    }
)


class AnswerGenerationService:
    """06 唯一编排入口，固定执行确定性流水线。

    只消费 DTO 与可选文本 port，不访问 facade、repository、driver、环境或模型；
    ``machine_answer`` 是权威输出，文本生成只是表现层。
    """

    def __init__(
        self,
        claim_builder: ClaimBuilder | None = None,
        citation_builder: CitationBuilder | None = None,
        status_resolver: AnswerStatusResolver | None = None,
        machine_builder: MachineAnswerBuilder | None = None,
        package_validator: AnswerPackageValidator | None = None,
        serializer: CanonicalAnswerSerializer | None = None,
        template_renderer: ChineseAnswerTemplateRenderer | None = None,
        text_generator: ConstrainedAnswerTextGenerator | None = None,
        text_validator: ConstrainedTextValidator | None = None,
    ) -> None:
        self.claim_builder = claim_builder or ClaimBuilder()
        self.citation_builder = citation_builder or CitationBuilder()
        self.status_resolver = status_resolver or AnswerStatusResolver()
        self.machine_builder = machine_builder or MachineAnswerBuilder()
        self.package_validator = package_validator or AnswerPackageValidator()
        self.serializer = serializer or CanonicalAnswerSerializer()
        self.template_renderer = template_renderer or ChineseAnswerTemplateRenderer()
        self.text_generator = text_generator
        self.text_validator = text_validator or ConstrainedTextValidator()

    def generate(
        self,
        request: AnswerGenerationRequest,
        policy: AnswerGenerationPolicy | None = None,
    ) -> AnswerPackage:
        policy = policy or AnswerGenerationPolicy()
        self._validate_input(request)
        if request.evidence_bundle is None:
            return self._terminal_answer(request)
        return self._generate_with_evidence(request, policy)

    @staticmethod
    def _validate_input(request: AnswerGenerationRequest) -> None:
        if request.evidence_bundle is None:
            question_type = request.question_result.question_type
            if question_type not in _TERMINAL_QUESTION_TYPES:
                raise AnswerValidationError(
                    f"evidence bundle is required for non-terminal question type {question_type!r}"
                )

    def _terminal_answer(self, request: AnswerGenerationRequest) -> AnswerPackage:
        question_result = request.question_result
        status = self._terminal_status(question_result.question_type)
        machine = self.machine_builder.build(
            request_id=question_result.request_id,
            question_type=question_result.question_type,
            scope=question_result.scope,
            status=status,
            unsupported_parts=question_result.unsupported_parts,
        )
        text = self.template_renderer.render(machine)
        package = AnswerPackage(
            request_id=machine.request_id,
            question_type=machine.question_type,
            scope=machine.scope,
            status=machine.status.value,
            machine_answer=machine,
            text_answer=text,
            claims=(),
            citations=(),
            unsupported_parts=machine.unsupported_parts,
            follow_up_actions=machine.follow_up_actions,
            render_mode=TextRenderMode.TEMPLATE,
            reason_codes=machine.reason_codes,
        )
        self.package_validator.validate(package)
        return package

    @staticmethod
    def _terminal_status(question_type: str) -> AnswerStatus:
        if question_type == QuestionType.CLARIFICATION_REQUIRED.value:
            return AnswerStatus.CLARIFICATION_REQUIRED
        return AnswerStatus.UNSUPPORTED

    def _generate_with_evidence(
        self,
        request: AnswerGenerationRequest,
        policy: AnswerGenerationPolicy,
    ) -> AnswerPackage:
        bundle = request.evidence_bundle
        question_result = request.question_result

        claims = self.claim_builder.build(question_result, bundle)
        self._enforce_limit(
            len(claims),
            policy.max_claims,
            ReasonCode.MAX_CLAIMS_EXCEEDED,
            "claims",
        )
        citations = self.citation_builder.build(claims, bundle)
        self._enforce_limit(
            len(citations),
            policy.max_citations,
            ReasonCode.MAX_CITATIONS_EXCEEDED,
            "citations",
        )
        claims = bind_claim_citations(claims, citations)

        blocking_conflicts = any(conflict.blocks_answer for conflict in bundle.conflicts)
        status = self.status_resolver.resolve(
            bundle.answerability,
            claims,
            recognition_failures=request.recognition_failures,
            blocking_conflicts=blocking_conflicts,
        )

        machine = self.machine_builder.build(
            request_id=question_result.request_id,
            question_type=question_result.question_type,
            scope=question_result.scope,
            status=status,
            claims=claims,
            citations=citations,
            warnings=list(request.stage_warnings) + list(bundle.warnings),
            unsupported_parts=bundle.unsupported_claims,
            recognition_run_ids=self._recognition_run_ids(bundle),
            follow_up_actions=self._follow_up_actions(bundle),
            reason_codes=bundle.reason_codes,
        )

        self.package_validator.validate_machine_answer(machine)

        template_text = self.template_renderer.render(machine)
        render_mode, text, text_warnings = self._render_text(machine, template_text, policy)
        text, truncation_warnings = self._truncate_text(text, policy)

        package = AnswerPackage(
            request_id=machine.request_id,
            question_type=machine.question_type,
            scope=machine.scope,
            status=machine.status.value,
            machine_answer=machine,
            text_answer=text,
            claims=machine.claims,
            citations=machine.citations,
            warnings=tuple(machine.warnings) + tuple(text_warnings) + tuple(truncation_warnings),
            unsupported_parts=machine.unsupported_parts,
            recognition_run_ids=machine.recognition_run_ids,
            follow_up_actions=machine.follow_up_actions,
            render_mode=render_mode,
            reason_codes=machine.reason_codes,
        )
        self.package_validator.validate(package)
        return package

    @staticmethod
    def _enforce_limit(
        count: int,
        limit: int | None,
        reason_code: ReasonCode,
        name: str,
    ) -> None:
        if limit is not None and count > limit:
            raise AnswerValidationError(
                f"{name} exceed the resource limit ({count} > {limit})",
                reason_code,
            )

    @staticmethod
    def _truncate_text(text: str, policy: AnswerGenerationPolicy) -> tuple[str, tuple[str, ...]]:
        if policy.max_text_length is not None and len(text) > policy.max_text_length:
            return text[: policy.max_text_length], (ReasonCode.RESULT_TRUNCATED.value,)
        return text, ()

    @staticmethod
    def _recognition_run_ids(bundle) -> tuple[str, ...]:
        ids: set[str] = set()
        for fusion in tuple(bundle.accepted_evidence) + tuple(bundle.conflicting_evidence):
            run_id = fusion.item.recognition_run_id
            if run_id:
                ids.add(run_id)
        return tuple(sorted(ids))

    @staticmethod
    def _follow_up_actions(bundle) -> tuple[str, ...]:
        actions: list[str] = []
        if bundle.unsupported_claims:
            actions.append("请缩小问题范围或补充更多信息")
        if any(conflict.review_recommended for conflict in bundle.conflicts):
            actions.append("建议人工复核冲突证据")
        return tuple(actions)

    def _render_text(
        self,
        machine: MachineAnswer,
        template_text: str,
        policy: AnswerGenerationPolicy,
    ) -> tuple[TextRenderMode, str, tuple[str, ...]]:
        if not policy.enable_constrained_text or self.text_generator is None:
            return TextRenderMode.TEMPLATE, template_text, ()
        request = self._build_text_request(machine)
        text, warnings = render_text_with_fallback(
            self.text_generator,
            request,
            self.text_validator,
            template_text,
            policy.text_generation_timeout_seconds,
        )
        mode = TextRenderMode.CONSTRAINED_TEXT if not warnings else TextRenderMode.TEMPLATE
        return mode, text, warnings

    @staticmethod
    def _build_text_request(machine: MachineAnswer) -> ConstrainedTextRequest:
        claims = tuple(
            ConstrainedClaimInput(
                claim_id=claim.claim_id,
                statement=claim.statement,
                status=claim.status or "",
                qualifiers=claim.qualifiers,
            )
            for claim in machine.claims
        )
        citation_ids = tuple(
            citation.citation_id
            for citation in machine.citations
            if citation.citation_id is not None
        )
        return ConstrainedTextRequest(
            claims=claims,
            citation_ids=citation_ids,
            sections=("conclusion", "evidence", "notes"),
        )
