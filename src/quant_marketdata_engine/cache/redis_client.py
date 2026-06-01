"""Own Redis sidecar client management.

A single module-level async ``redis.asyncio.Redis`` is created in the FastAPI
lifespan and reused. This Redis is **distinct from the gateway's** response cache
(ADR D8): it holds the OHLCV hot-window cache and the single-flight fetch lock.
"""

from __future__ import annotations

import logging

import redis.asyncio as aioredis

from src.quant_marketdata_engine.cache.errors import CacheError

logger = logging.getLogger(__name__)

_client: aioredis.Redis | None = None


def create_redis(url: str) -> aioredis.Redis:
    """Create (or return the existing) module-level Redis client."""
    global _client
    if _client is not None:
        return _client
    try:
        _client = aioredis.from_url(url, encoding="utf-8", decode_responses=True)
    except Exception as exc:
        raise CacheError(f"failed to create redis client: {exc}") from exc
    logger.info("redis client created")
    return _client


def get_redis() -> aioredis.Redis | None:
    """Return the Redis client, or ``None`` if not initialized (cache optional)."""
    return _client


async def close_redis() -> None:
    """Close and clear the module-level Redis client (no-op if uninitialized)."""
    global _client
    if _client is None:
        return
    await _client.aclose()
    _client = None
    logger.info("redis client closed")


async def ping(client: aioredis.Redis) -> bool:
    """Return ``True`` if Redis answers PING, else ``False`` (never raises)."""
    try:
        await client.ping()
    except Exception:
        logger.warning("redis ping failed", exc_info=True)
        return False
    return True
