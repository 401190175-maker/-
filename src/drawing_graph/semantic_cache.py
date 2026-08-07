"""Deterministic cache-key generation for semantic evidence reuse."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol

from .tool_models import BBox, ToolModelError


@dataclass(frozen=True)
class SemanticCacheKeyInput:
    """Versioned inputs that define one semantic cache key.

    The observation key deliberately has no alias-rule component: alias rules
    only invalidate section-match results, never raw text observations.
    """

    image_hash: str
    bbox: BBox | tuple[float, float, float, float]
    target_element_id: str
    task_type: str
    model_profile: str
    model_version: str
    prompt_version: str
    preprocessing_version: str
    normalization_rule_version: str
    contract_version: str

    def __post_init__(self) -> None:
        for field_name in (
            "image_hash",
            "target_element_id",
            "task_type",
            "model_profile",
            "model_version",
            "prompt_version",
            "preprocessing_version",
            "normalization_rule_version",
            "contract_version",
        ):
            _require_text(getattr(self, field_name), field_name)
        bbox = self.bbox if isinstance(self.bbox, BBox) else _bbox_tuple(self.bbox)
        object.__setattr__(self, "bbox", bbox)


def build_semantic_cache_key(inputs: SemanticCacheKeyInput) -> str:
    """Build a stable sha256 cache key from normalized cache inputs."""

    _require_cache_input(inputs)
    payload = {
        "image_hash": inputs.image_hash,
        "bbox": _bbox_values(inputs.bbox),
        "target_element_id": inputs.target_element_id,
        "task_type": inputs.task_type,
        "model_profile": inputs.model_profile,
        "model_version": inputs.model_version,
        "prompt_version": inputs.prompt_version,
        "preprocessing_version": inputs.preprocessing_version,
        "normalization_rule_version": inputs.normalization_rule_version,
        "contract_version": inputs.contract_version,
    }
    return _hash_payload(payload)


def build_section_match_cache_key(
    observation_keys: tuple[str, ...],
    candidate_scope: str,
    match_rule_version: str,
    alias_rule_version: str | None = None,
) -> str:
    """Build a cache key for section-match judgments.

    Unlike observations, the match key includes the applicable alias-rule
    version so alias changes only invalidate dependent matches.
    """

    if isinstance(observation_keys, (str, bytes)) or not isinstance(observation_keys, (list, tuple)):
        raise ToolModelError("invalid_observation_keys", "observation_keys must be a sequence of strings")
    keys = tuple(observation_keys)
    for key in keys:
        _require_text(key, "observation_key")
    _require_text(candidate_scope, "candidate_scope")
    _require_text(match_rule_version, "match_rule_version")
    _require_optional_text(alias_rule_version, "alias_rule_version")
    payload = {
        "observation_keys": keys,
        "candidate_scope": candidate_scope,
        "match_rule_version": match_rule_version,
    }
    if alias_rule_version is not None:
        payload["alias_rule_version"] = alias_rule_version
    return _hash_payload(payload)


def _require_cache_input(inputs: Any) -> None:
    if not isinstance(inputs, SemanticCacheKeyInput):
        raise ToolModelError("invalid_cache_input", "cache inputs must be a SemanticCacheKeyInput")


def _bbox_tuple(value: Any) -> tuple[float, float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ToolModelError("invalid_bbox", "bbox must be a BBox or four-coordinate sequence")
    bbox = BBox(value[0], value[1], value[2], value[3])
    return (bbox.x_min, bbox.y_min, bbox.x_max, bbox.y_max)


def _bbox_values(bbox: BBox | tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    if isinstance(bbox, BBox):
        return (bbox.x_min, bbox.y_min, bbox.x_max, bbox.y_max)
    return tuple(bbox)


def _hash_payload(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"semantic:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolModelError("missing_required_field", f"{field_name} must be a non-empty string")
    return value


def _require_optional_text(value: Any, field_name: str) -> None:
    if value is not None:
        _require_text(value, field_name)


class SemanticCacheService(Protocol):
    """Protocol for semantic result caching."""

    def get(self, cache_key: str) -> Any | None:
        """Return a cached semantic result for one key."""

    def put(self, cache_key: str, value: Any) -> None:
        """Store one semantic result under a key."""


class InMemorySemanticCacheService:
    """In-memory semantic cache for unit tests and lightweight runs."""

    def __init__(self):
        self._values: dict[str, Any] = {}

    def get(self, cache_key: str) -> Any | None:
        _require_text(cache_key, "cache_key")
        return self._values.get(cache_key)

    def put(self, cache_key: str, value: Any) -> None:
        _require_text(cache_key, "cache_key")
        self._values[cache_key] = value


__all__ = (
    "InMemorySemanticCacheService",
    "SemanticCacheKeyInput",
    "SemanticCacheService",
    "build_semantic_cache_key",
    "build_section_match_cache_key",
)
