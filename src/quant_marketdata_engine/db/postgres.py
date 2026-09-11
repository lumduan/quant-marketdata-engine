"""asyncpg connection-pool management.

A single module-level pool is created eagerly in the FastAPI lifespan (and by the
ingest CLI) via :func:`create_pool`, retrieved with :func:`get_pool`, and closed
with :func:`close_pool`. The pool is bounded by ``Settings.pg_pool_{min,max}_size``.

🔴 Startup is NOT the only chance to open the pool, and it must not be.

On 2026-09-10 the host rebooted and this container started **0.324 s before**
``quant-postgres``. ``create_pool`` raised, the lifespan swallowed it, ``_pool``
stayed ``None`` for the life of the process, and the read API served
``503 database unavailable`` for 33 h against a database that was healthy the
whole time. Nothing retried, because ``create_pool`` is called exactly once.
Compose could not have ordered it either: Postgres lives in a different compose
project (``quant-infra-db``), so a ``depends_on`` is not expressible here.

:func:`ensure_pool` is the fix — every reader asks for the pool through it, and a
failed startup heals on the next request instead of persisting forever.
"""

from __future__ import annotations

import logging
import time

import asyncpg

from src.quant_marketdata_engine.db.errors import PoolNotInitializedError, RepositoryError

logger = logging.getLogger(__name__)

#: Minimum gap between reconnect attempts. A tight loop against a down database
#: would otherwise add a connect attempt per inbound request.
RETRY_COOLDOWN_SECONDS: float = 5.0

_pool: asyncpg.Pool | None = None
_last_attempt: float | None = None


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


async def ensure_pool(
    dsn: str,
    *,
    min_size: int = 1,
    max_size: int = 10,
    cooldown_seconds: float = RETRY_COOLDOWN_SECONDS,
) -> asyncpg.Pool:
    """Return the pool, opening it on demand if an earlier attempt failed.

    This is the accessor every request path should use. :func:`get_pool` is a
    pure getter and cannot recover; calling it alone is what let a lost startup
    race persist for the life of the process (see the module docstring).

    Raises:
        PoolNotInitializedError: The pool is not open and could not be opened —
            either the reconnect attempt failed, or we are inside the cooldown
            window after a recent failure. Callers map this to ``503``.
    """
    global _last_attempt
    if _pool is not None:
        return _pool
    now = time.monotonic()
    if _last_attempt is not None and (now - _last_attempt) < cooldown_seconds:
        raise PoolNotInitializedError(
            "asyncpg pool is not initialized; reconnect is in cooldown "
            f"({cooldown_seconds:.0f}s) after a recent failure"
        )
    _last_attempt = now
    try:
        pool = await create_pool(dsn, min_size=min_size, max_size=max_size)
    except RepositoryError as exc:
        raise PoolNotInitializedError(f"asyncpg pool could not be opened: {exc}") from exc
    logger.info("asyncpg pool opened on demand after an earlier failure")
    _last_attempt = None
    return pool


async def close_pool() -> None:
    """Close and clear the module-level pool (no-op if uninitialized)."""
    global _pool, _last_attempt
    _last_attempt = None
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
