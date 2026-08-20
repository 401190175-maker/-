"""Deterministic Chinese-aware text matching for page content search."""

from __future__ import annotations

import re


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
