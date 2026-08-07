"""Environment-backed import configuration for the drawing graph ETL."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(ValueError):
    """Raised when environment variables cannot produce a valid config."""


@dataclass(frozen=True)
class ImportConfig:
    """Immutable runtime settings loaded from environment variables."""

    data_root: Path
    project_slug: str
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str = field(repr=False)
    batch_size: int = 500
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "ImportConfig":
        """Create a validated configuration from process environment variables."""

        data_root = _required_env("DRAWING_GRAPH_DATA_ROOT")
        project_slug = _required_env("DRAWING_GRAPH_PROJECT_SLUG")
        neo4j_uri = _required_env("NEO4J_URI")
        neo4j_user = _required_env("NEO4J_USER")
        neo4j_password = _required_env("NEO4J_PASSWORD")
        batch_size = _read_batch_size(os.environ.get("DRAWING_GRAPH_BATCH_SIZE", "500"))
        log_level = os.environ.get("DRAWING_GRAPH_LOG_LEVEL", "INFO").strip().upper()

        if not log_level:
            raise ConfigError("DRAWING_GRAPH_LOG_LEVEL must not be empty")

        return cls(
            data_root=Path(data_root).expanduser(),
            project_slug=project_slug,
            neo4j_uri=neo4j_uri,
            neo4j_user=neo4j_user,
            neo4j_password=neo4j_password,
            batch_size=batch_size,
            log_level=log_level,
        )

    def __repr__(self) -> str:
        """Return a debug representation with the database password masked."""

        return (
            "ImportConfig("
            f"data_root={self.data_root!r}, "
            f"project_slug={self.project_slug!r}, "
            f"neo4j_uri={self.neo4j_uri!r}, "
            f"neo4j_user={self.neo4j_user!r}, "
            "neo4j_password='********', "
            f"batch_size={self.batch_size!r}, "
            f"log_level={self.log_level!r}"
            ")"
        )


@dataclass(frozen=True)
class ToolFacadeConfig:
    """Controlled settings for creating a tool facade."""

    default_write_back: bool = False
    model_profile: str = "default"
    prompt_version: str = "default"
    run_log_path: Path | None = None
    run_log_store: str = "in_memory"
    payload_store: str = "in_memory"
    semantic_repository: str = "in_memory"
    cache_store: str = "in_memory"
    section_match_rule_version: str = "section-match-v1"

    @classmethod
    def from_mapping(cls, values: dict[str, object]) -> "ToolFacadeConfig":
        """Create facade config from controlled non-secret values."""

        forbidden = {
            "neo4j_uri",
            "neo4j_user",
            "neo4j_password",
            "api_key",
            "provider_api_key",
            "token",
            "secret",
        }
        if forbidden.intersection(key.lower() for key in values):
            raise ValueError("Tool facade config must not accept database or provider secrets")
        default_write_back = values.get("default_write_back", False)
        if not isinstance(default_write_back, bool):
            raise ValueError("default_write_back must be a boolean")
        model_profile = str(values.get("model_profile", "default")).strip()
        prompt_version = str(values.get("prompt_version", "default")).strip()
        if not model_profile or not prompt_version:
            raise ValueError("model_profile and prompt_version must not be empty")
        run_log_raw = values.get("run_log_path")
        run_log_path = Path(str(run_log_raw)).expanduser() if run_log_raw is not None else None
        run_log_store = _store_type(values.get("run_log_store", "in_memory"), "run_log_store")
        payload_store = _store_type(values.get("payload_store", "in_memory"), "payload_store")
        semantic_repository = _store_type(values.get("semantic_repository", "in_memory"), "semantic_repository")
        cache_store = _store_type(values.get("cache_store", "in_memory"), "cache_store")
        section_match_rule_version = str(values.get("section_match_rule_version", "section-match-v1")).strip()
        if not section_match_rule_version:
            raise ValueError("section_match_rule_version must not be empty")
        return cls(
            default_write_back=default_write_back,
            model_profile=model_profile,
            prompt_version=prompt_version,
            run_log_path=run_log_path,
            run_log_store=run_log_store,
            payload_store=payload_store,
            semantic_repository=semantic_repository,
            cache_store=cache_store,
            section_match_rule_version=section_match_rule_version,
        )


def _store_type(value: object, field_name: str) -> str:
    store_type = str(value).strip().lower()
    if store_type != "in_memory":
        raise ValueError(f"{field_name} must be a supported store type")
    return store_type


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is required")
    return value


def _read_batch_size(value: str) -> int:
    try:
        batch_size = int(value)
    except ValueError as error:
        raise ConfigError("DRAWING_GRAPH_BATCH_SIZE must be a positive integer") from error

    if batch_size < 1:
        raise ConfigError("DRAWING_GRAPH_BATCH_SIZE must be a positive integer")

    return batch_size
