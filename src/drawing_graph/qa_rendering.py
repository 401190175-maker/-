"""Short Chinese rendering for structured QA answers.

渲染层只读取 :class:`QAAnswer`，不调用 facade、不读取环境变量、不访问
Neo4j，也不修改事实类型或状态。JSON 仍是权威输出，本模块只服务 CLI 的
``--format zh-brief``。
"""

from __future__ import annotations

from .qa_models import QAAnswer, QAAnswerStatus


FACT_KIND_LABELS = {
    "source_fact": "来源事实",
    "derived_relation": "派生关系",
    "semantic_observation": "语义观察",
    "semantic_interpretation": "语义解释",
    "candidate_relation": "候选关系",
    "formal_relation": "正式关系",
    "diagnostic": "诊断",
    "unsupported": "未支持",
}

STATUS_LABELS = {
    "confirmed": "已确认",
    "candidate": "候选",
    "partial": "部分可用",
    "ambiguous": "歧义",
    "not_found": "未找到",
    "not_recognized": "未识别",
    "recognition_failed": "识别失败",
    "not_enhanced": "未增强",
    "answered": "已回答",
    "unsupported": "不受支持",
    "failed": "失败",
}


def render_qa_answer_zh_brief(answer: QAAnswer) -> str:
    """Render one structured QA answer as short Chinese text."""

    lines = [
        f"状态：{_status_label(answer.status)}",
        f"摘要：{answer.summary}",
    ]
    if answer.facts:
        lines.append("事实：")
        for fact in answer.facts:
            kind_label = FACT_KIND_LABELS.get(fact.fact_kind, fact.fact_kind)
            lines.append(f"- [{kind_label}] {fact.label}（{_status_label(fact.status)}）")
    if answer.warnings:
        lines.append("警告：")
        lines.extend(f"- {warning}" for warning in answer.warnings)
    if answer.unsupported_parts:
        lines.append("未支持部分：")
        lines.extend(f"- {part}" for part in answer.unsupported_parts)
    return "\n".join(lines)


def _status_label(status: QAAnswerStatus | str) -> str:
    value = status.value if isinstance(status, QAAnswerStatus) else status
    return STATUS_LABELS.get(value, str(value))


__all__ = ("render_qa_answer_zh_brief",)
