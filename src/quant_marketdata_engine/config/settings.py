"""Service configuration via ``pydantic-settings``.

All runtime config is read from the environment (or a gitignored ``.env`` for
local dev). The ``MARKETDATA_ENGINE_*`` prefix namespaces this service's own
knobs; the **unprefixed** ``TVKIT_AUTH_TOKEN`` is the shared TradingView cookie
that *only this service* owns (a JSON cookie string, NOT a JWT). It is read here
but **never logged** and is only parsed/validated when ingest actually runs.
"""

from __future__ import annotations

import json
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.quant_marketdata_engine.config.errors import CookieConfigError


class Settings(BaseSettings):
    """Typed settings for the Market Data engine.

    ``TVKIT_AUTH_TOKEN`` has no prefix (it is a shared, cross-tool name); every
    other field uses the ``MARKETDATA_ENGINE_`` prefix.
    """

    model_config = SettingsConfigDict(
        env_prefix="MARKETDATA_ENGINE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    app_env: str = Field(default="development", description="Deployment environment label.")
    log_level: str = Field(default="INFO", description="Root log level.")

    public_mode: bool = Field(
        default=True,
        description="Read-only when true; refuses tvkit ingest. Owner mode sets this false.",
    )
    host_port: int = Field(default=8300, description="Host port mapping (container is :8000).")

    pg_dsn: str = Field(
        default="postgresql://quant:quant@quant-postgres:5432/db_market_data",
        description="asyncpg DSN for the canonical db_market_data store.",
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Own Redis sidecar URL (hot-window cache + single-flight lock).",
    )
    api_key: str | None = Field(
        default=None,
        description="X-API-Key for the private read API. When unset, endpoints log a warning.",
    )

    pg_pool_min_size: int = Field(default=1, ge=0, description="asyncpg pool minimum size.")
    pg_pool_max_size: int = Field(default=10, ge=1, description="asyncpg pool maximum size.")
    cache_ttl_seconds: int = Field(default=300, ge=0, description="Hot-window cache TTL.")
    tvkit_timeout_seconds: float = Field(
        default=30.0, gt=0, description="Upper bound on a single tvkit fetch."
    )

    # Unprefixed shared credential — sole owner is this service. NEVER logged.
    tvkit_auth_token: str | None = Field(
        default=None,
        validation_alias="TVKIT_AUTH_TOKEN",
        description="TradingView cookie as a JSON string (required key: sessionid).",
    )

    @property
    def has_cookie(self) -> bool:
        """Whether a non-empty tvkit cookie is configured (presence only)."""
        return bool(self.tvkit_auth_token and self.tvkit_auth_token.strip())

    def tvkit_cookies(self) -> dict[str, str]:
        """Parse ``TVKIT_AUTH_TOKEN`` into a cookie dict.

        Raises:
            CookieConfigError: if the token is missing, not valid JSON, not an
                object, or is missing the required ``sessionid`` key.
        """
        if not self.has_cookie:
            raise CookieConfigError("TVKIT_AUTH_TOKEN is not set")
        assert self.tvkit_auth_token is not None  # narrowed by has_cookie
        try:
            parsed: object = json.loads(self.tvkit_auth_token)
        except json.JSONDecodeError as exc:
            # Do not include the token value in the message.
            raise CookieConfigError("TVKIT_AUTH_TOKEN is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise CookieConfigError("TVKIT_AUTH_TOKEN must be a JSON object")
        if "sessionid" not in parsed:
            raise CookieConfigError("TVKIT_AUTH_TOKEN is missing required key 'sessionid'")
        return {str(k): str(v) for k, v in parsed.items()}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached :class:`Settings` instance."""
    return Settings()
