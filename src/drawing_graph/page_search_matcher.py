"""Deterministic Chinese-aware text matching for page content search."""

from __future__ import annotations

import re
from typing import Mapping


_TOKEN_SPLIT = re.compile(r"[\s,，。；;:：!！?？()（）]+")
_STRIP = re.compile(r"[^\w\u4e00-\u9fff]+", re.UNICODE)


def normalize_text(text: str) -> str:
    """Lowercase and strip punctuation/space, keeping CJK and ASCII word chars."""

    return _STRIP.sub("", (text or "").lower())


class TextMatcher:
    """Substring token matcher: every normalized query token must appear in text."""

    def __init__(self, tokenizer=None) -> None:
        self._tokenizer = tokenizer or _TOKEN_SPLIT.split

    def query_tokens(self, query: str) -> tuple[str, ...]:
        """Return normalized, non-empty query tokens."""

        parts = self._tokenizer(query)
        return tuple(normalize_text(part) for part in parts if normalize_text(part))

    def matches(self, query: str, text: str) -> bool:
        """Return True when every query token is a substring of the text."""

        tokens = self.query_tokens(query)
        if not tokens:
            return False
        normalized = normalize_text(text)
        return all(token in normalized for token in tokens)


DOMAIN_SYNONYMS = {
    "排水": ("雨水", "雨水口", "雨水管", "管道", "排水沟"),
    "雨水": ("排水", "雨水口", "雨水管"),
    "挡土墙": ("挡墙", "挡土结构"),
    "挡墙": ("挡土墙", "挡土结构"),
    "混凝土": ("砼",),
    "砼": ("混凝土",),
    "路基": ("路床",),
    "路面": ("面层", "铺装"),
    "断面": ("剖面", "截面"),
    "涵洞": ("箱涵", "管涵"),
    "桥梁": ("桥",),
    "标高": ("高程",),
    "护栏": ("防撞栏",),
    "沥青": ("柏油",),
}


class SynonymExpansionMatcher(TextMatcher):
    """TextMatcher with domain synonym expansion on query tokens."""

    def __init__(
        self,
        tokenizer=None,
        synonyms: Mapping[str, tuple[str, ...]] | None = None,
    ) -> None:
        super().__init__(tokenizer)
        self._synonyms = dict(synonyms or DOMAIN_SYNONYMS)

    def matches(self, query: str, text: str) -> bool:
        tokens = self.query_tokens(query)
        if not tokens:
            return False
        normalized = normalize_text(text)
        for token in tokens:
            expanded = (token,) + tuple(self._synonyms.get(token, ()))
            if not any(item in normalized for item in expanded):
                return False
        return True
