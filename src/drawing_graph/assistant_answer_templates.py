"""Deterministic Chinese answer template renderer for the 06 layer.

本模块把已通过校验的 ``MachineAnswer`` 渲染为始终可用的简短中文模板。模板
按固定章节顺序输出，不引入 machine answer 之外的新 claim，也不改变事实等级。
"""

from __future__ import annotations

from .assistant_models import (
    AnswerStatus,
    Claim,
    ClaimStatus,
    FactKind,
    MachineAnswer,
)

_STATUS_CONCLUSION = {
    AnswerStatus.ANSWERED: "已得出答案",
    AnswerStatus.PARTIAL: "部分可答",
    AnswerStatus.CLARIFICATION_REQUIRED: "需要补充信息",
    AnswerStatus.UNSUPPORTED: "当前问题不受支持",
    AnswerStatus.RECOGNITION_FAILED: "识别失败，无法给出语义结论",
}

_FACT_KIND_WORDING = {
    FactKind.SOURCE_FACT: "来源事实",
    FactKind.DERIVED_RELATION: "派生关系",
    FactKind.SEMANTIC_OBSERVATION: "图中观察到",
    FactKind.SEMANTIC_INTERPRETATION: "语义解释为",
    FactKind.CANDIDATE_RELATION: "候选关系",
    FactKind.FORMAL_RELATION: "正式关系",
    FactKind.DIAGNOSTIC: "运行状态",
    FactKind.UNSUPPORTED: "未支持",
}

_CLAIM_STATUS_WORDING = {
    ClaimStatus.SUPPORTED: "已确认",
    ClaimStatus.QUALIFIED: "已确认（含限定）",
    ClaimStatus.CONFLICTING: "存在冲突",
    ClaimStatus.FORMAL_REVIEW_REQUIRED: "候选待复核",
    ClaimStatus.DIAGNOSTIC: "运行状态",
}


def fact_kind_wording(fact_kind: FactKind) -> str:
    """返回某事实等级的确定性中文措辞，不提升候选/解释为正式/来源事实。"""

    return _FACT_KIND_WORDING.get(fact_kind, fact_kind.value)


def claim_status_wording(status: ClaimStatus | str) -> str:
    value = status.value if isinstance(status, ClaimStatus) else status
    return _CLAIM_STATUS_WORDING.get(ClaimStatus(value), value)


class ChineseAnswerTemplateRenderer:
    """按固定章节把 MachineAnswer 渲染为简短中文文本。"""

    def render(self, answer_core: MachineAnswer) -> str:
        lines: list[str] = []

        lines.append(f"结论：{_status_conclusion(answer_core.status)}")
        lines.append("")

        lines.append("依据：")
        if answer_core.claims:
            for index, claim in enumerate(answer_core.claims, 1):
                lines.append(f"{index}. {_claim_line(claim)}")
        else:
            lines.append("（无依据）")
        lines.append("")

        lines.append("候选/冲突/限定语：")
        constrained = [
            claim
            for claim in answer_core.claims
            if claim.qualifiers
            or _claim_status(claim.status)
            in (ClaimStatus.QUALIFIED, ClaimStatus.CONFLICTING, ClaimStatus.FORMAL_REVIEW_REQUIRED)
        ]
        if constrained:
            for claim in constrained:
                qualifiers = "、".join(claim.qualifiers) if claim.qualifiers else ""
                suffix = f"（{qualifiers}）" if qualifiers else ""
                lines.append(f"- {claim.statement}{suffix}")
        else:
            lines.append("（无）")
        lines.append("")

        lines.append("注意：")
        notes: list[str] = []
        if answer_core.unsupported_parts:
            notes.append(f"未支持部分：{'、'.join(answer_core.unsupported_parts)}")
        if answer_core.warnings:
            notes.append(f"警告：{'、'.join(str(item) for item in answer_core.warnings)}")
        if notes:
            lines.extend(f"- {note}" for note in notes)
        else:
            lines.append("（无）")
        lines.append("")

        lines.append("后续动作：")
        if answer_core.follow_up_actions:
            lines.extend(f"- {action}" for action in answer_core.follow_up_actions)
        else:
            lines.append("（无）")

        return "\n".join(lines)


def _claim_line(claim: Claim) -> str:
    kinds = tuple(fact_kind_wording(kind) for kind in claim.fact_kinds)
    kind_label = "、".join(kinds)
    citation_label = "、".join(claim.citation_ids) if claim.citation_ids else ""
    label = f"[{kind_label}] {claim.statement}"
    if citation_label:
        label += f"（引用：{citation_label}）"
    return label


def _claim_status(status: str | None) -> ClaimStatus | None:
    if isinstance(status, ClaimStatus):
        return status
    if isinstance(status, str):
        try:
            return ClaimStatus(status)
        except ValueError:
            return None
    return None


def _status_conclusion(status: AnswerStatus | str) -> str:
    value = status.value if isinstance(status, AnswerStatus) else status
    return _STATUS_CONCLUSION.get(AnswerStatus(value), value)
