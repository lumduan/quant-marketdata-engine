"""Single-flight fetch lock over the own Redis sidecar (ADR D8).

Dedupes concurrent identical work on ``(symbol, timeframe, range)`` via a Redis
``SET key value NX EX ttl`` lock, so two callers cannot both trigger a TradingView
fetch for the same key. Phase 2 wires this into ingest dedupe; the deferred
cold-path (auto-fetch-on-read) consumes the same primitive.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_LOCK_PREFIX = "mde:lock"

# Release only if we still own the lock (compare-and-delete), so we never delete
# a lock another holder acquired after ours expired.
_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


def lock_key(*, symbol: str, timeframe: str, range_key: str) -> str:
    """Build the lock key for a fetch identity."""
    return f"{_LOCK_PREFIX}:{symbol}:{timeframe}:{range_key}"


@asynccontextmanager
async def single_flight(
    client: aioredis.Redis | None,
    key: str,
    *,
    ttl_seconds: int = 30,
) -> AsyncIterator[bool]:
    """Yield ``True`` if this caller acquired the lock, ``False`` otherwise.

    When ``client`` is ``None`` (Redis unavailable) the lock is a no-op that
    yields ``True`` — correctness still holds because the underlying upsert is
    idempotent; the lock is purely an efficiency guard.
    """
    if client is None:
        yield True
        return
    token = uuid.uuid4().hex
    acquired = False
    try:
        acquired = bool(await client.set(key, token, nx=True, ex=ttl_seconds))
    except Exception:
        logger.warning("single-flight acquire failed for %s; proceeding", key, exc_info=True)
        acquired = True
    try:
        yield acquired
    finally:
        if acquired:
            try:
                await client.eval(_RELEASE_LUA, 1, key, token)
            except Exception:
                logger.warning("single-flight release failed for %s", key, exc_info=True)
