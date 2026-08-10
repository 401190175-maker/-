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


@dataclass(frozen=True)
class QAHttpConfig:
    """Immutable HTTP service settings loaded from environment variables.

    只服务 HTTP adapter：默认监听 loopback、默认只读、默认关闭 CORS 和
    OpenAPI docs。Neo4j 密码与 API token 使用 ``repr=False`` 并在自定义
    ``__repr__`` 中屏蔽，不进入错误输出或日志。
    """

    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str = field(repr=False)
    host: str = "127.0.0.1"
    port: int = 8000
    allow_remote: bool = False
    allowed_origins: tuple[str, ...] = ()
    api_token: str = field(default="", repr=False)
    max_request_bytes: int = 65536
    request_timeout_seconds: float = 30.0
    max_concurrent_requests: int = 8
    docs_enabled: bool = False
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "QAHttpConfig":
        """Create a validated HTTP configuration from process environment variables."""

        env = os.environ
        return cls(
            neo4j_uri=_required_env("NEO4J_URI"),
            neo4j_user=_required_env("NEO4J_USER"),
            neo4j_password=_required_env("NEO4J_PASSWORD"),
            host=_required_text(env.get("DRAWING_GRAPH_QA_HTTP_HOST", "127.0.0.1"), "DRAWING_GRAPH_QA_HTTP_HOST"),
            port=_read_int(
                env.get("DRAWING_GRAPH_QA_HTTP_PORT", "8000"),
                "DRAWING_GRAPH_QA_HTTP_PORT",
                minimum=1,
                maximum=65535,
            ),
            allow_remote=_read_bool(
                env.get("DRAWING_GRAPH_QA_HTTP_ALLOW_REMOTE", "false"),
                "DRAWING_GRAPH_QA_HTTP_ALLOW_REMOTE",
            ),
            allowed_origins=_read_origins(env.get("DRAWING_GRAPH_QA_HTTP_ALLOWED_ORIGINS", "")),
            api_token=env.get("DRAWING_GRAPH_QA_HTTP_API_TOKEN", "").strip(),
            max_request_bytes=_read_int(
                env.get("DRAWING_GRAPH_QA_HTTP_MAX_REQUEST_BYTES", "65536"),
                "DRAWING_GRAPH_QA_HTTP_MAX_REQUEST_BYTES",
                minimum=1,
            ),
            request_timeout_seconds=_read_number(
                env.get("DRAWING_GRAPH_QA_HTTP_REQUEST_TIMEOUT_SECONDS", "30"),
                "DRAWING_GRAPH_QA_HTTP_REQUEST_TIMEOUT_SECONDS",
                exclusive_minimum=0,
            ),
            max_concurrent_requests=_read_int(
                env.get("DRAWING_GRAPH_QA_HTTP_MAX_CONCURRENT_REQUESTS", "8"),
                "DRAWING_GRAPH_QA_HTTP_MAX_CONCURRENT_REQUESTS",
                minimum=1,
            ),
            docs_enabled=_read_bool(
                env.get("DRAWING_GRAPH_QA_HTTP_DOCS_ENABLED", "false"),
                "DRAWING_GRAPH_QA_HTTP_DOCS_ENABLED",
            ),
            log_level=_read_log_level(env.get("DRAWING_GRAPH_QA_HTTP_LOG_LEVEL", "INFO")),
        )

    def __post_init__(self) -> None:
        if self.port < 1 or self.port > 65535:
            raise ConfigError("DRAWING_GRAPH_QA_HTTP_PORT must be between 1 and 65535")
        if self.max_request_bytes < 1:
            raise ConfigError("DRAWING_GRAPH_QA_HTTP_MAX_REQUEST_BYTES must be a positive integer")
        if self.request_timeout_seconds <= 0:
            raise ConfigError("DRAWING_GRAPH_QA_HTTP_REQUEST_TIMEOUT_SECONDS must be positive")
        if self.max_concurrent_requests < 1:
            raise ConfigError("DRAWING_GRAPH_QA_HTTP_MAX_CONCURRENT_REQUESTS must be a positive integer")
        if not _is_loopback(self.host):
            if not self.allow_remote:
                raise ConfigError("non-loopback host requires DRAWING_GRAPH_QA_HTTP_ALLOW_REMOTE=true")
            if not self.api_token:
                raise ConfigError("non-loopback host requires DRAWING_GRAPH_QA_HTTP_API_TOKEN")
        if self.docs_enabled and not _is_loopback(self.host):
            raise ConfigError("DRAWING_GRAPH_QA_HTTP_DOCS_ENABLED=true is only allowed on loopback hosts")
        for origin in self.allowed_origins:
            if origin == "*" or not origin.startswith(("http://", "https://")):
                raise ConfigError("DRAWING_GRAPH_QA_HTTP_ALLOWED_ORIGINS must be explicit http/https origins")

    def __repr__(self) -> str:
        """Return a debug representation with secrets masked."""

        return (
            "QAHttpConfig("
            f"neo4j_uri={self.neo4j_uri!r}, "
            f"neo4j_user={self.neo4j_user!r}, "
            "neo4j_password='********', "
            f"host={self.host!r}, "
            f"port={self.port!r}, "
            f"allow_remote={self.allow_remote!r}, "
            f"allowed_origins={self.allowed_origins!r}, "
            "api_token='********', "
            f"max_request_bytes={self.max_request_bytes!r}, "
            f"request_timeout_seconds={self.request_timeout_seconds!r}, "
            f"max_concurrent_requests={self.max_concurrent_requests!r}, "
            f"docs_enabled={self.docs_enabled!r}, "
            f"log_level={self.log_level!r}"
            ")"
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


def _required_text(value: str, name: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ConfigError(f"{name} must not be empty")
    return stripped


def _read_int(value: str, name: str, *, minimum: int, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise ConfigError(f"{name} must be an integer") from error
    if parsed < minimum:
        raise ConfigError(f"{name} must be at least {minimum}")
    if maximum is not None and parsed > maximum:
        raise ConfigError(f"{name} must be at most {maximum}")
    return parsed


def _read_number(value: str, name: str, *, exclusive_minimum: float) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise ConfigError(f"{name} must be a number") from error
    if parsed <= exclusive_minimum:
        raise ConfigError(f"{name} must be greater than {exclusive_minimum}")
    return parsed


def _read_bool(value: str, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be a boolean")


def _read_origins(value: str) -> tuple[str, ...]:
    if not value.strip():
        return ()
    origins = tuple(origin.strip() for origin in value.split(",") if origin.strip())
    if not origins:
        raise ConfigError("DRAWING_GRAPH_QA_HTTP_ALLOWED_ORIGINS must not be empty when provided")
    return origins


def _read_log_level(value: str) -> str:
    level = value.strip().upper()
    if not level:
        raise ConfigError("DRAWING_GRAPH_QA_HTTP_LOG_LEVEL must not be empty")
    return level


def _is_loopback(host: str) -> bool:
    return host.strip().lower() in {"127.0.0.1", "::1", "localhost"}
