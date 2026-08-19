"""Constrained answer text generation port, fake and validator for the 06 layer.

本模块定义供应商无关的受约束文本生成 port、请求/结果 DTO、无网络 fake 实现、
输出校验器与模板回退。文本生成器只能重排或连接已批准 claim，不能新增、删除
或改绑 claim/citation，不能新增数字/业务 ID/实体或删除不可删限定语。模块不
读取环境变量、不访问网络、不读取图谱或完整 payload。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

from .assistant_models import ReasonCode


class TextGenerationError(ValueError):
    """文本生成或校验失败时的稳定错误。"""


class TextGenerationTimeout(TextGenerationError):
    """文本生成超时。"""


@dataclass(frozen=True)
class ConstrainedClaimInput:
    """脱敏后的已批准 claim：只含 ID、statement、status 与限定语。"""

    claim_id: str
    statement: str
    status: str
    qualifiers: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.claim_id, str) or not self.claim_id.strip():
            raise ValueError("claim_id must be a non-empty string")
        if not isinstance(self.statement, str) or not self.statement.strip():
            raise ValueError("statement must be a non-empty string")
        if not isinstance(self.status, str) or not self.status.strip():
            raise ValueError("status must be a non-empty string")
        if not isinstance(self.qualifiers, tuple):
            raise ValueError("qualifiers must be a tuple")


@dataclass(frozen=True)
class ConstrainedTextRequest:
    """受约束文本生成请求：只含已批准 claim、公开 citation ID 与允许章节。"""

    claims: tuple[ConstrainedClaimInput, ...]
    citation_ids: tuple[str, ...] = field(default_factory=tuple)
    sections: tuple[str, ...] = field(default_factory=tuple)
    language: str = "zh-CN"

    def __post_init__(self) -> None:
        for claim in self.claims:
            if not isinstance(claim, ConstrainedClaimInput):
                raise ValueError("claims must contain only ConstrainedClaimInput instances")
        if not isinstance(self.citation_ids, tuple):
            raise ValueError("citation_ids must be a tuple")
        if not isinstance(self.sections, tuple):
            raise ValueError("sections must be a tuple")
        if not isinstance(self.language, str) or not self.language.strip():
            raise ValueError("language must be a non-empty string")


@dataclass(frozen=True)
class ConstrainedTextResult:
    """受约束文本生成结果：章节文本与使用的 claim/citation ID。"""

    sections: tuple[str, ...]
    used_claim_ids: tuple[str, ...] = field(default_factory=tuple)
    used_citation_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.sections, tuple):
            raise ValueError("sections must be a tuple")
        if not isinstance(self.used_claim_ids, tuple):
            raise ValueError("used_claim_ids must be a tuple")
        if not isinstance(self.used_citation_ids, tuple):
            raise ValueError("used_citation_ids must be a tuple")


@dataclass(frozen=True)
class ValidatedTextResult:
    """受约束文本校验结果。"""

    valid: bool
    reason_codes: tuple[ReasonCode, ...] = field(default_factory=tuple)
    message: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.valid, bool):
            raise ValueError("valid must be a boolean")
        if not isinstance(self.reason_codes, tuple):
            raise ValueError("reason_codes must be a tuple")
        if not isinstance(self.message, str):
            raise ValueError("message must be a string")


class ConstrainedAnswerTextGenerator:
    """供应商无关的受约束文本生成 port。"""

    def generate(self, request: ConstrainedTextRequest) -> ConstrainedTextResult:
        raise NotImplementedError


class FakeConstrainedTextGenerator(ConstrainedAnswerTextGenerator):
    """确定性、无网络的 fake 文本生成器，用于离线测试。"""

    def generate(self, request: ConstrainedTextRequest) -> ConstrainedTextResult:
        lines: list[str] = []
        for claim in request.claims:
            qualifier_text = (
                f"（{'；'.join(claim.qualifiers)}）" if claim.qualifiers else ""
            )
            lines.append(f"{claim.statement}{qualifier_text}")
        for citation_id in request.citation_ids:
            lines.append(f"[{citation_id}]")
        return ConstrainedTextResult(
            sections=tuple(lines),
            used_claim_ids=tuple(claim.claim_id for claim in request.claims),
            used_citation_ids=request.citation_ids,
        )


class ConstrainedTextValidator:
    """校验受约束文本结果，拒绝新增、遗漏、改绑 claim/citation 与语义门禁失败。"""

    def validate(
        self,
        request: ConstrainedTextRequest,
        result: ConstrainedTextResult,
    ) -> ValidatedTextResult:
        reasons = list(self._identifier_reasons(request, result))
        reasons.extend(self._semantic_reasons(request, result))
        reason_codes = tuple(dict.fromkeys(reasons))
        if reason_codes:
            return ValidatedTextResult(valid=False, reason_codes=reason_codes)
        return ValidatedTextResult(valid=True)

    @staticmethod
    def _identifier_reasons(
        request: ConstrainedTextRequest,
        result: ConstrainedTextResult,
    ) -> list[ReasonCode]:
        reasons: list[ReasonCode] = []
        request_claim_ids = [claim.claim_id for claim in request.claims]
        used_claim_ids = list(result.used_claim_ids)

        if set(used_claim_ids) != set(request_claim_ids):
            reasons.append(ReasonCode.TEXT_OUTPUT_INVALID)
        if len(used_claim_ids) != len(set(used_claim_ids)):
            reasons.append(ReasonCode.TEXT_OUTPUT_INVALID)

        used_citation_ids = list(result.used_citation_ids)
        allowlist = set(request.citation_ids)
        if len(used_citation_ids) != len(set(used_citation_ids)):
            reasons.append(ReasonCode.TEXT_OUTPUT_INVALID)
        if not set(used_citation_ids) <= allowlist:
            reasons.append(ReasonCode.TEXT_OUTPUT_INVALID)
        return reasons

    @staticmethod
    def _semantic_reasons(
        request: ConstrainedTextRequest,
        result: ConstrainedTextResult,
    ) -> list[ReasonCode]:
        reasons: list[ReasonCode] = []
        text = "\n".join(result.sections)

        for claim in request.claims:
            for qualifier in claim.qualifiers:
                if qualifier not in text:
                    reasons.append(ReasonCode.TEXT_OUTPUT_INVALID)
                    break

        if not _numbers(text) <= _input_numbers(request):
            reasons.append(ReasonCode.TEXT_OUTPUT_INVALID)

        if not _ids(text) <= _input_ids(request):
            reasons.append(ReasonCode.TEXT_OUTPUT_INVALID)

        return reasons


_ID_PATTERN = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*:[a-zA-Z0-9-]+")


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+", text))


def _ids(text: str) -> set[str]:
    return set(_ID_PATTERN.findall(text))


def _input_numbers(request: ConstrainedTextRequest) -> set[str]:
    numbers: set[str] = set()
    for claim in request.claims:
        numbers.update(_numbers(claim.statement))
        numbers.update(_numbers(claim.claim_id))
        numbers.update(_numbers(" ".join(claim.qualifiers)))
    numbers.update(_numbers(" ".join(request.citation_ids)))
    return numbers


def _input_ids(request: ConstrainedTextRequest) -> set[str]:
    ids: set[str] = set()
    for claim in request.claims:
        ids.update(_ids(claim.statement))
        ids.update(_ids(claim.claim_id))
        ids.update(_ids(" ".join(claim.qualifiers)))
    ids.update(_ids(" ".join(request.citation_ids)))
    return ids


def _generate_with_timeout(
    generator: ConstrainedAnswerTextGenerator,
    request: ConstrainedTextRequest,
    timeout_seconds: float | None,
) -> ConstrainedTextResult:
    if timeout_seconds is None:
        return generator.generate(request)
    import threading

    box: dict = {}

    def run() -> None:
        try:
            box["result"] = generator.generate(request)
        except Exception as exc:  # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=run)
    thread.daemon = True
    thread.start()
    thread.join(timeout_seconds)
    if thread.is_alive():
        raise TextGenerationTimeout("text generation timed out")
    if "error" in box:
        raise box["error"]
    return box["result"]


def render_text_with_fallback(
    generator: ConstrainedAnswerTextGenerator | None,
    request: ConstrainedTextRequest,
    validator: ConstrainedTextValidator,
    template_text: str,
    timeout_seconds: float | None = None,
) -> tuple[str, tuple[str, ...]]:
    """在生成器不可用、超时、异常或校验失败时回退中文模板。

    返回 ``(text, warnings)``；machine answer 由调用方保持权威不变，
    生成器原始响应不进入输出。
    """

    if generator is None:
        return template_text, ()
    try:
        result = _generate_with_timeout(generator, request, timeout_seconds)
    except Exception:  # noqa: BLE001
        return template_text, (ReasonCode.TEXT_GENERATION_FAILED.value,)
    validated = validator.validate(request, result)
    if not validated.valid:
        return template_text, tuple(code.value for code in validated.reason_codes)
    return "\n".join(result.sections), ()
