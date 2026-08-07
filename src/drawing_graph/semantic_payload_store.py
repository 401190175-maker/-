"""Immutable external payload storage for full semantic parse results."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping, Protocol

from .tool_models import ToolModelError


class SemanticPayloadStore(Protocol):
    """Persistence boundary for immutable JSON parse payloads.

    Payloads are referenced by ``payload_ref`` and are never embedded as large
    nested properties on Neo4j nodes.
    """

    def put_payload(self, payload: Mapping[str, Any], content_hash: str) -> str:
        """Store an immutable payload and return a stable payload_ref."""

    def get_payload(self, payload_ref: str) -> Mapping[str, Any]:
        """Return one immutable payload or raise a classified NOT_FOUND error."""


class InMemorySemanticPayloadStore:
    """In-memory payload store for unit tests and lightweight deployments."""

    def __init__(self):
        self._payloads: dict[str, Mapping[str, Any]] = {}
        self._refs_by_hash: dict[str, str] = {}
        self._meta: dict[str, dict[str, str]] = {}

    def put_payload(
        self,
        payload: Mapping[str, Any],
        content_hash: str,
        contract_version: str = "1",
    ) -> str:
        _require_mapping(payload, "payload")
        _require_text(content_hash, "content_hash")
        _require_text(contract_version, "contract_version")
        existing_ref = self._refs_by_hash.get(content_hash)
        if existing_ref is not None:
            return existing_ref
        payload_ref = f"payload:{content_hash}"
        self._payloads[payload_ref] = _freeze(payload)
        self._meta[payload_ref] = {
            "content_hash": content_hash,
            "contract_version": contract_version,
        }
        self._refs_by_hash[content_hash] = payload_ref
        return payload_ref

    def get_payload(self, payload_ref: str) -> Mapping[str, Any]:
        _require_text(payload_ref, "payload_ref")
        try:
            return self._payloads[payload_ref]
        except KeyError as exc:
            raise ToolModelError("NOT_FOUND", "semantic payload was not found") from exc

    def get_payload_meta(self, payload_ref: str) -> Mapping[str, str]:
        """Return content hash and contract version for one payload ref."""

        _require_text(payload_ref, "payload_ref")
        try:
            return MappingProxyType(dict(self._meta[payload_ref]))
        except KeyError as exc:
            raise ToolModelError("NOT_FOUND", "semantic payload was not found") from exc


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _require_mapping(value: Any, field_name: str) -> None:
    if not isinstance(value, Mapping):
        raise ToolModelError("invalid_payload", f"{field_name} must be a mapping")


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolModelError("missing_required_field", f"{field_name} must be a non-empty string")
    return value


__all__ = ("InMemorySemanticPayloadStore", "SemanticPayloadStore")
