"""Normalization of CrossSection endpoint labels and BlockCaption titles."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class SectionSymbolSystem(str, Enum):
    ALPHABETIC = "alphabetic"
    ROMAN = "roman"
    NUMERIC = "numeric"
    ALPHANUMERIC = "alphanumeric"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SectionLabelNormalizationResult:
    """Outcome of normalizing one section-label pair."""

    symbol_system: SectionSymbolSystem
    normalized_key: str | None
    deterministic: bool
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.symbol_system, SectionSymbolSystem):
            raise ValueError("symbol_system must be a SectionSymbolSystem")
        if not isinstance(self.deterministic, bool):
            raise ValueError("deterministic must be a boolean")
        if self.normalized_key is not None and not isinstance(self.normalized_key, str):
            raise ValueError("normalized_key must be a string when provided")
        if self.reason is not None and not isinstance(self.reason, str):
            raise ValueError("reason must be a string when provided")


class SectionLabelNormalizer:
    """Recognize symbol systems and build deterministic logical keys."""

    _SEPARATOR = re.compile(r"[\s\-—–－~～]+")

    def normalize(self, label: str) -> tuple[SectionSymbolSystem, str | None, str | None]:
        """Normalize one endpoint label into (symbol_system, value, reason)."""

        if not isinstance(label, str) or not label.strip():
            return SectionSymbolSystem.UNKNOWN, None, "label is empty"
        parts = [part for part in self._SEPARATOR.split(label.strip()) if part]
        if not parts:
            return SectionSymbolSystem.UNKNOWN, None, "label contains no symbols"
        if len(parts) > 1 and parts[0] != parts[1]:
            return SectionSymbolSystem.UNKNOWN, None, "endpoint labels differ within one label"
        cleaned = parts[0]
        if re.fullmatch(r"[0-9]+", cleaned):
            return SectionSymbolSystem.NUMERIC, cleaned, None
        if re.fullmatch(r"[IVXLCDMivxlcdm]+", cleaned):
            return SectionSymbolSystem.ROMAN, cleaned.upper(), None
        if re.fullmatch(r"[A-Za-z]+", cleaned):
            return SectionSymbolSystem.ALPHABETIC, cleaned.upper(), None
        if re.fullmatch(r"[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+", cleaned):
            return SectionSymbolSystem.ROMAN, cleaned, None
        if re.fullmatch(r"[A-Za-z0-9]+", cleaned):
            return SectionSymbolSystem.ALPHANUMERIC, cleaned.upper(), None
        return SectionSymbolSystem.UNKNOWN, None, "label symbol system is not supported"

    def normalize_pair(
        self,
        start_label: str,
        end_label: str,
    ) -> SectionLabelNormalizationResult:
        """Normalize a section-label pair and decide whether a logical key is deterministic."""

        start_system, start_value, start_reason = self.normalize(start_label)
        end_system, end_value, end_reason = self.normalize(end_label)
        if start_system is SectionSymbolSystem.UNKNOWN or end_system is SectionSymbolSystem.UNKNOWN:
            return SectionLabelNormalizationResult(
                symbol_system=SectionSymbolSystem.UNKNOWN,
                normalized_key=None,
                deterministic=False,
                reason=start_reason or end_reason or "label symbol system is not supported",
            )
        if start_system is not end_system:
            return SectionLabelNormalizationResult(
                symbol_system=start_system,
                normalized_key=None,
                deterministic=False,
                reason="cross-symbol-system matching requires a confirmed alias rule",
            )
        if start_value != end_value:
            return SectionLabelNormalizationResult(
                symbol_system=start_system,
                normalized_key=None,
                deterministic=False,
                reason="section label endpoints do not match",
            )
        key_prefix = {
            SectionSymbolSystem.ALPHABETIC: "ALPHA",
            SectionSymbolSystem.ROMAN: "ROMAN",
            SectionSymbolSystem.NUMERIC: "NUMERIC",
            SectionSymbolSystem.ALPHANUMERIC: "ALPHANUMERIC",
            SectionSymbolSystem.UNKNOWN: "UNKNOWN",
        }[start_system]
        return SectionLabelNormalizationResult(
            symbol_system=start_system,
            normalized_key=f"SECTION_{key_prefix}_{start_value}",
            deterministic=True,
        )


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


__all__ = (
    "SectionLabelNormalizationResult",
    "SectionLabelNormalizer",
    "SectionSymbolSystem",
)
