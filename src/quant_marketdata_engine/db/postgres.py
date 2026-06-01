"""asyncpg connection-pool management.

A single module-level pool is created eagerly in the FastAPI lifespan (and by the
ingest CLI) via :func:`create_pool`, retrieved with :func:`get_pool`, and closed
with :func:`close_pool`. The pool is bounded by ``Settings.pg_pool_{min,max}_size``.
"""

from __future__ import annotations

import logging

import asyncpg

from src.quant_marketdata_engine.db.errors import PoolNotInitializedError, RepositoryError

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def create_pool(
    dsn: str,
    *,
    min_size: int = 1,
    max_size: int = 10,
) -> asyncpg.Pool:
    """Create (or return the existing) module-level asyncpg pool."""
    global _pool
    if _pool is not None:
        return _pool
    try:
        _pool = await asyncpg.create_pool(dsn=dsn, min_size=min_size, max_size=max_size)
    except Exception as exc:  # asyncpg raises a broad family on connect failure
        raise RepositoryError(f"failed to create asyncpg pool: {exc}") from exc
    logger.info("asyncpg pool created (min=%d max=%d)", min_size, max_size)
    return _pool


def get_pool() -> asyncpg.Pool:
    """Return the initialized pool, or raise if ``create_pool`` was not called."""
    if _pool is None:
        raise PoolNotInitializedError("asyncpg pool is not initialized; call create_pool first")
    return _pool


async def close_pool() -> None:
    """Close and clear the module-level pool (no-op if uninitialized)."""
    global _pool
    if _pool is None:
        return
    await _pool.close()
    _pool = None
    logger.info("asyncpg pool closed")


async def ping(pool: asyncpg.Pool) -> bool:
    """Return ``True`` if a trivial query round-trips, else ``False``."""
    try:
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
    except Exception:  # health check must never raise
        logger.warning("postgres ping failed", exc_info=True)
        return False
    return True
