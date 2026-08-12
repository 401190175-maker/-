"""Question text normalization for rule-based routing.

只做文本整理，不改变问题语义；空字符串由上游 ``AssistantRequest``
负责拒绝，本模块对空输入直接报错，不吞掉错误。
"""

from __future__ import annotations


_FULL_WIDTH_PUNCTUATION = str.maketrans(
    {
        "\u3000": " ",
        "，": ",",
        "。": ".",
        "！": "!",
        "？": "?",
        "；": ";",
        "：": ":",
        "（": "(",
        "）": ")",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "～": "~",
        "—": "-",
    }
)


class QuestionTextNormalizer:
    """把用户问题整理为规则路由可稳定处理的形式。"""

    def normalize(self, question: str) -> str:
        """去除首尾空白、统一常见全角标点并折叠重复空白。"""

        if not isinstance(question, str) or not question.strip():
            raise ValueError("question must be a non-empty string")
        text = question.strip().translate(_FULL_WIDTH_PUNCTUATION)
        return " ".join(text.split())
