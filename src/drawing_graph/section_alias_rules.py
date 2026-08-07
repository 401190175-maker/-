"""Graph-external section-label alias rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from .section_label_normalization import SectionSymbolSystem


class SectionAliasRuleStatus(str, Enum):
    CONFIRMED = "confirmed"
    REVOKED = "revoked"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class SectionLabelAliasRule:
    """One versioned, scoped, graph-external alias rule.

    Only ``confirmed`` rules whose scope matches may participate in
    deterministic section matching. This module never creates graph nodes.
    """

    alias_rule_id: str
    alias_rule_version: str
    scope: str
    from_symbol_system: SectionSymbolSystem | str
    to_symbol_system: SectionSymbolSystem | str
    mapping: Mapping[str, str]
    status: SectionAliasRuleStatus | str = SectionAliasRuleStatus.CONFIRMED
    evidence_ref: str | None = None
    source_system: str | None = None
    confirmed_by: str | None = None
    created_at: str | None = None
    revoked_at: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("alias_rule_id", "alias_rule_version", "scope"):
            _require_text(getattr(self, field_name), field_name)
        from_system = _coerce_symbol_system(self.from_symbol_system, "from_symbol_system")
        to_system = _coerce_symbol_system(self.to_symbol_system, "to_symbol_system")
        if from_system is SectionSymbolSystem.UNKNOWN or to_system is SectionSymbolSystem.UNKNOWN:
            raise ValueError("alias rules cannot use the unknown symbol system")
        if from_system is to_system:
            raise ValueError("alias rules must map between different symbol systems")
        status = self.status if isinstance(self.status, SectionAliasRuleStatus) else SectionAliasRuleStatus(self.status)
        _require_mapping(self.mapping, "mapping")
        mapping = {str(key): str(value) for key, value in self.mapping.items()}
        if not mapping:
            raise ValueError("mapping must not be empty")
        for field_name in ("evidence_ref", "source_system", "confirmed_by", "created_at", "revoked_at"):
            _require_optional_text(getattr(self, field_name), field_name)
        object.__setattr__(self, "from_symbol_system", from_system)
        object.__setattr__(self, "to_symbol_system", to_system)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "mapping", MappingProxyType(mapping))


class SectionAliasRuleStore:
    """In-memory store of graph-external alias rules."""

    def __init__(self, rules: tuple[SectionLabelAliasRule, ...] = ()):
        self._rules: dict[str, SectionLabelAliasRule] = {}
        for rule in rules:
            self.add_rule(rule)

    def add_rule(self, rule: SectionLabelAliasRule) -> None:
        """Register one rule; a later same-id rule replaces the earlier one."""

        if not isinstance(rule, SectionLabelAliasRule):
            raise TypeError("rule must be a SectionLabelAliasRule")
        self._rules[rule.alias_rule_id] = rule

    def find_applicable(
        self,
        *,
        scope: str,
        from_symbol_system: SectionSymbolSystem | str,
        to_symbol_system: SectionSymbolSystem | str,
    ) -> tuple[SectionLabelAliasRule, ...]:
        """Return confirmed, scope-matching rules between two symbol systems."""

        _require_text(scope, "scope")
        from_system = _coerce_symbol_system(from_symbol_system, "from_symbol_system")
        to_system = _coerce_symbol_system(to_symbol_system, "to_symbol_system")
        return tuple(
            rule
            for rule in self._rules.values()
            if rule.status is SectionAliasRuleStatus.CONFIRMED
            and (rule.scope == scope or rule.scope == "*")
            and rule.from_symbol_system is from_system
            and rule.to_symbol_system is to_system
        )

    def can_match(
        self,
        *,
        scope: str,
        from_symbol_system: SectionSymbolSystem | str,
        to_symbol_system: SectionSymbolSystem | str,
    ) -> bool:
        """Return whether a confirmed applicable alias rule exists."""

        return bool(
            self.find_applicable(
                scope=scope,
                from_symbol_system=from_symbol_system,
                to_symbol_system=to_symbol_system,
            )
        )


def _coerce_symbol_system(value: SectionSymbolSystem | str, field_name: str) -> SectionSymbolSystem:
    try:
        return value if isinstance(value, SectionSymbolSystem) else SectionSymbolSystem(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a supported symbol system") from exc


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _require_optional_text(value: Any, field_name: str) -> None:
    if value is not None:
        _require_text(value, field_name)


def _require_mapping(value: Any, field_name: str) -> None:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a mapping")


__all__ = (
    "SectionAliasRuleStatus",
    "SectionAliasRuleStore",
    "SectionLabelAliasRule",
)
