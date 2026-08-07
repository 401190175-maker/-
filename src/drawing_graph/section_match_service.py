"""Section-caption candidate and formal match judgment service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .section_alias_rules import SectionAliasRuleStore
from .section_label_normalization import SectionLabelNormalizer, SectionSymbolSystem
from .semantic_models import TextObservation
from .tool_models import ToolModelError


@dataclass(frozen=True)
class SectionCandidateMatch:
    """One candidate section-caption match summary."""

    candidate_group_id: str
    cross_section_id: str
    block_caption_id: str
    page_id: str
    status: str
    candidate_count: int
    score: float
    conflict_reason: str | None
    observation_ids: tuple[str, ...]
    rule_version: str
    logical_key: str
    symbol_system: SectionSymbolSystem | str

    def __post_init__(self) -> None:
        for field_name in (
            "candidate_group_id",
            "cross_section_id",
            "block_caption_id",
            "page_id",
            "status",
            "rule_version",
            "logical_key",
        ):
            _require_text(getattr(self, field_name), field_name)
        if not isinstance(self.candidate_count, int) or isinstance(self.candidate_count, bool) or self.candidate_count < 1:
            raise ToolModelError("invalid_candidate_count", "candidate_count must be a positive integer")
        if not isinstance(self.score, (int, float)) or isinstance(self.score, bool) or not 0 <= self.score <= 1:
            raise ToolModelError("invalid_score", "score must be between 0 and 1")
        _require_optional_text(self.conflict_reason, "conflict_reason")
        object.__setattr__(self, "observation_ids", _read_text_tuple(self.observation_ids, "observation_ids"))


@dataclass(frozen=True)
class SectionMatchDecision:
    """Formal-vs-candidate decision for one cross-section label."""

    cross_section_id: str
    page_id: str
    status: str
    fact_kind: str
    logical_key: str | None
    symbol_system: SectionSymbolSystem | str | None
    matched_caption_id: str | None
    candidate_count: int
    conflict_reason: str | None
    observation_ids: tuple[str, ...]
    rule_version: str
    alias_rule_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("cross_section_id", "page_id", "status", "fact_kind", "rule_version"):
            _require_text(getattr(self, field_name), field_name)
        if self.status not in {"formal", "candidate", "ambiguous", "match_not_found"}:
            raise ToolModelError("invalid_match_status", "status must be a supported match status")
        if self.fact_kind not in {"candidate_relation", "formal_relation"}:
            raise ToolModelError("invalid_fact_kind", "fact_kind must be candidate_relation or formal_relation")
        if self.status == "formal" and self.fact_kind != "formal_relation":
            raise ToolModelError("invalid_fact_kind", "formal decisions must use fact_kind='formal_relation'")
        if not isinstance(self.candidate_count, int) or isinstance(self.candidate_count, bool) or self.candidate_count < 0:
            raise ToolModelError("invalid_candidate_count", "candidate_count must be a non-negative integer")
        _require_optional_text(self.logical_key, "logical_key")
        _require_optional_text(self.matched_caption_id, "matched_caption_id")
        _require_optional_text(self.conflict_reason, "conflict_reason")
        _require_optional_text(self.alias_rule_id, "alias_rule_id")
        object.__setattr__(self, "observation_ids", _read_text_tuple(self.observation_ids, "observation_ids"))


class SectionMatchService:
    """Build candidate and formal section-caption matches from observations."""

    def __init__(
        self,
        normalizer: SectionLabelNormalizer | None = None,
        alias_rule_store: SectionAliasRuleStore | None = None,
    ):
        self.normalizer = normalizer or SectionLabelNormalizer()
        self.alias_rule_store = alias_rule_store or SectionAliasRuleStore()

    def generate_candidates(
        self,
        *,
        cross_section_observation: TextObservation | None,
        caption_observations: tuple[TextObservation, ...],
        page_id: str,
        rule_version: str,
    ) -> tuple[SectionCandidateMatch, ...]:
        """Generate candidate matches only from comparable text evidence.

        Spatial proximity is deliberately ignored: text equality is the only
        evidence used to form candidates.
        """

        _require_text(page_id, "page_id")
        _require_text(rule_version, "rule_version")
        if cross_section_observation is None:
            return ()
        _require_observation_type(cross_section_observation, "CrossSection")
        _require_observation_tuple(caption_observations)
        cross_section_key = self._normalize_to_key(cross_section_observation)
        if cross_section_key is None:
            return ()
        matching_captions = tuple(
            observation
            for observation in caption_observations
            if _require_observation_type(observation, "BlockCaption")
            and self._normalize_to_key(observation) == cross_section_key
        )
        if not matching_captions:
            return ()
        candidate_group_id = f"section-match:{cross_section_observation.target_element_id}:{page_id}:{rule_version}"
        return tuple(
            SectionCandidateMatch(
                candidate_group_id=candidate_group_id,
                cross_section_id=cross_section_observation.target_element_id,
                block_caption_id=observation.target_element_id,
                page_id=page_id,
                status="candidate",
                candidate_count=len(matching_captions),
                score=observation.confidence,
                conflict_reason="multiple same-key captions" if len(matching_captions) > 1 else None,
                observation_ids=(cross_section_observation.observation_id, observation.observation_id),
                rule_version=rule_version,
                logical_key=cross_section_key,
                symbol_system=self._symbol_system(cross_section_observation),
            )
            for observation in matching_captions
        )

    def _normalize_to_key(self, observation: TextObservation) -> str | None:
        label = observation.normalized_text or observation.raw_text
        _, value, _ = self.normalizer.normalize(label)
        if value is None:
            return None
        result = self.normalizer.normalize_pair(label, label)
        return result.normalized_key if result.deterministic else None

    def _symbol_system(self, observation: TextObservation) -> SectionSymbolSystem:
        label = observation.normalized_text or observation.raw_text
        system, _, _ = self.normalizer.normalize(label)
        return system

    def evaluate_formal_match(
        self,
        *,
        cross_section_observation: TextObservation | None,
        caption_observations: tuple[TextObservation, ...],
        page_id: str,
        rule_version: str,
        conflicting_caption_ids: tuple[str, ...] = (),
    ) -> SectionMatchDecision:
        """Apply hard rules and return formal, candidate, or ambiguous decisions.

        Formal output requires traceable observations on both sides, a
        non-unknown logical key, a confirmed alias rule when symbol systems
        differ, exactly one candidate, and no block-caption conflict.
        """

        _require_text(page_id, "page_id")
        _require_text(rule_version, "rule_version")
        if isinstance(conflicting_caption_ids, (str, bytes)) or not isinstance(conflicting_caption_ids, (list, tuple)):
            raise ToolModelError("invalid_conflicts", "conflicting_caption_ids must be a sequence of strings")
        conflict_ids = tuple(conflicting_caption_ids)
        for caption_id in conflict_ids:
            _require_text(caption_id, "conflicting_caption_id")
        if cross_section_observation is None:
            return SectionMatchDecision(
                cross_section_id="unknown",
                page_id=page_id,
                status="match_not_found",
                fact_kind="candidate_relation",
                logical_key=None,
                symbol_system=None,
                matched_caption_id=None,
                candidate_count=0,
                conflict_reason="missing cross-section observation",
                observation_ids=(),
                rule_version=rule_version,
            )
        _require_observation_type(cross_section_observation, "CrossSection")
        _require_observation_tuple(caption_observations)
        cross_section_key = self._normalize_to_key(cross_section_observation)
        cross_section_system = self._symbol_system(cross_section_observation)
        if cross_section_key is None:
            return _ambiguous_decision(
                cross_section_observation,
                page_id,
                rule_version,
                "section label cannot be normalized",
                cross_section_observation.observation_id,
            )
        caption_keys = {
            observation: self._normalize_to_key(observation)
            for observation in caption_observations
            if _require_observation_type(observation, "BlockCaption")
        }
        matched_captions = []
        alias_rule_id = None
        for observation, caption_key in caption_keys.items():
            if caption_key is None:
                continue
            caption_system = self._symbol_system(observation)
            if caption_system is cross_section_system and caption_key == cross_section_key:
                matched_captions.append(observation)
                continue
            if caption_system is not cross_section_system:
                applicable_rules = self.alias_rule_store.find_applicable(
                    scope=page_id,
                    from_symbol_system=cross_section_system,
                    to_symbol_system=caption_system,
                )
                for alias_rule in applicable_rules:
                    if alias_rule.mapping.get(cross_section_key) == caption_key:
                        matched_captions.append(observation)
                        alias_rule_id = alias_rule.alias_rule_id
                        break
        if not matched_captions:
            return SectionMatchDecision(
                cross_section_id=cross_section_observation.target_element_id,
                page_id=page_id,
                status="candidate",
                fact_kind="candidate_relation",
                logical_key=cross_section_key,
                symbol_system=cross_section_system,
                matched_caption_id=None,
                candidate_count=0,
                conflict_reason="no caption matches the normalized section key",
                observation_ids=(cross_section_observation.observation_id,),
                rule_version=rule_version,
            )
        all_observation_ids = tuple(
            observation.observation_id for observation in (cross_section_observation, *matched_captions)
        )
        if len(matched_captions) > 1:
            return SectionMatchDecision(
                cross_section_id=cross_section_observation.target_element_id,
                page_id=page_id,
                status="ambiguous",
                fact_kind="candidate_relation",
                logical_key=cross_section_key,
                symbol_system=cross_section_system,
                matched_caption_id=None,
                candidate_count=len(matched_captions),
                conflict_reason="multiple same-key captions",
                observation_ids=all_observation_ids,
                rule_version=rule_version,
                alias_rule_id=alias_rule_id,
            )
        unique_caption = matched_captions[0]
        if unique_caption.target_element_id in conflict_ids:
            return SectionMatchDecision(
                cross_section_id=cross_section_observation.target_element_id,
                page_id=page_id,
                status="ambiguous",
                fact_kind="candidate_relation",
                logical_key=cross_section_key,
                symbol_system=cross_section_system,
                matched_caption_id=unique_caption.target_element_id,
                candidate_count=1,
                conflict_reason="caption has a conflicting block relation",
                observation_ids=all_observation_ids,
                rule_version=rule_version,
                alias_rule_id=alias_rule_id,
            )
        return SectionMatchDecision(
            cross_section_id=cross_section_observation.target_element_id,
            page_id=page_id,
            status="formal",
            fact_kind="formal_relation",
            logical_key=cross_section_key,
            symbol_system=cross_section_system,
            matched_caption_id=unique_caption.target_element_id,
            candidate_count=1,
            conflict_reason=None,
            observation_ids=all_observation_ids,
            rule_version=rule_version,
            alias_rule_id=alias_rule_id,
        )


def _ambiguous_decision(
    cross_section_observation: TextObservation,
    page_id: str,
    rule_version: str,
    reason: str,
    observation_id: str,
) -> SectionMatchDecision:
    return SectionMatchDecision(
        cross_section_id=cross_section_observation.target_element_id,
        page_id=page_id,
        status="ambiguous",
        fact_kind="candidate_relation",
        logical_key=None,
        symbol_system=None,
        matched_caption_id=None,
        candidate_count=0,
        conflict_reason=reason,
        observation_ids=(observation_id,),
        rule_version=rule_version,
    )


def _require_observation_type(observation: TextObservation, expected_type: str) -> TextObservation:
    if not isinstance(observation, TextObservation):
        raise ToolModelError("invalid_observation", "observation must be a TextObservation")
    if observation.target_element_type != expected_type:
        raise ToolModelError(
            "invalid_observation_type",
            f"observation must target {expected_type}",
        )
    return observation


def _require_observation_tuple(observations: tuple[TextObservation, ...]) -> None:
    if not isinstance(observations, tuple) or not all(isinstance(item, TextObservation) for item in observations):
        raise ToolModelError("invalid_observations", "caption observations must be a tuple of TextObservation")


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolModelError("missing_required_field", f"{field_name} must be a non-empty string")
    return value


def _require_optional_text(value: Any, field_name: str) -> None:
    if value is not None:
        _require_text(value, field_name)


def _read_text_tuple(values: Any, field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
        raise ToolModelError("invalid_sequence", f"{field_name} must be a sequence of strings")
    for value in values:
        _require_text(value, field_name)
    return tuple(values)


__all__ = ("SectionCandidateMatch", "SectionMatchDecision", "SectionMatchService")
