"""FastAPI dependencies: resource accessors + auth / mode guards.

Resource accessors return the module-level asyncpg pool / Redis client so routes
stay thin; tests override them via ``app.dependency_overrides``.
"""

from __future__ import annotations

import hmac
import logging

import asyncpg
import redis.asyncio as aioredis
from fastapi import Depends, Header, HTTPException, status

from src.quant_marketdata_engine.cache.redis_client import get_redis
from src.quant_marketdata_engine.config.settings import Settings, get_settings
from src.quant_marketdata_engine.db.postgres import get_pool

logger = logging.getLogger(__name__)


def get_settings_dep() -> Settings:
    """Return process settings."""
    return get_settings()


def get_pool_dep() -> asyncpg.Pool:
    """Return the initialized asyncpg pool."""
    return get_pool()


def get_redis_dep() -> aioredis.Redis | None:
    """Return the Redis client (or None when unavailable — cache is optional)."""
    return get_redis()


async def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    settings: Settings = Depends(get_settings_dep),
) -> None:
    """Enforce ``X-API-Key`` when an API key is configured.

    When no key is configured the endpoint is open but logs a warning (raw OHLCV
    is private-side — operators should set a key in any shared deployment).
    """
    expected = settings.api_key
    if not expected:
        logger.warning("MARKETDATA_ENGINE_API_KEY unset — read API is unauthenticated")
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing API key",
        )


async def require_owner_mode(
    settings: Settings = Depends(get_settings_dep),
) -> None:
    """Reject write/ingest endpoints when the service is in public (read-only) mode."""
    if settings.public_mode:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="endpoint disabled in public mode",
        )
