"""Bulk daily refresh — fetch a recent window for every tracked symbol.

The per-symbol path is unchanged (:func:`ingest_ohlcv`), so idempotent
``ON CONFLICT`` upserts, the single-flight lock and cache invalidation all still
apply. This module adds only what the single-symbol CLI lacked: symbol
enumeration, bounded concurrency, per-symbol error isolation, retries, and a
summary the caller (a cron job) can act on.

Two failure modes are deliberately distinguished:

* **Fatal, fail-fast** — public mode or a missing/malformed cookie. These are
  configuration problems that would fail identically for all N symbols, so they
  are checked once up front and raised rather than counted N times.
* **Per-symbol, isolated** — an upstream tvkit failure or an upsert failure on
  one symbol (delisted tickers, transient rate limits). These are retried,
  recorded, and never abort the run.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

import asyncpg
import redis.asyncio as aioredis
from pydantic import BaseModel, Field

from src.quant_marketdata_engine.config.settings import Settings
from src.quant_marketdata_engine.db.errors import RepositoryError
from src.quant_marketdata_engine.db.repositories import list_tracked_symbols
from src.quant_marketdata_engine.ingest.errors import IngestDisabledError, TvkitFetchError
from src.quant_marketdata_engine.ingest.service import ingest_ohlcv

logger = logging.getLogger(__name__)

DEFAULT_BARS = 30
DEFAULT_CONCURRENCY = 2
DEFAULT_RETRIES = 2
RETRY_BACKOFF_SECONDS = 2.0

# Every fetch opens a fresh tvkit client, and each client bootstraps its auth
# token with an HTTP GET to tradingview.com. Measured on 2026-07-31: a 692-symbol
# run at concurrency 4 sustained ~96 requests/min and TradingView began answering
# that bootstrap with 403 after 449 fetches (4m41s in). Pacing the *rate* — rather
# than only the concurrency — is what keeps a full-universe run under that ceiling,
# because concurrency alone lets fast responses spike the request rate.
DEFAULT_MIN_INTERVAL_SECONDS = 1.0


class _Pacer:
    """Serialises fetch starts so the request rate never exceeds 1/min_interval."""

    def __init__(self, min_interval: float) -> None:
        self._min_interval = min_interval
        self._lock = asyncio.Lock()
        self._next_at = 0.0

    async def wait(self) -> None:
        """Block until the next fetch is allowed to start."""
        if self._min_interval <= 0:
            return
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            if now < self._next_at:
                await asyncio.sleep(self._next_at - now)
                now = loop.time()
            self._next_at = now + self._min_interval


class DailyIngestResult(BaseModel):
    """Outcome of one bulk refresh — the summary a scheduled run reports."""

    timeframe: str
    attempted: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    rows_written: int = Field(ge=0)
    failures: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Whether the run is healthy enough to report success.

        A run with no symbols is a misconfiguration, not a no-op, and a run in
        which *every* symbol failed indicates a systemic fault (expired cookie,
        upstream outage) rather than a handful of delisted tickers.
        """
        return self.attempted > 0 and self.succeeded > 0


async def _ingest_one(
    *,
    settings: Settings,
    pool: asyncpg.Pool,
    redis: aioredis.Redis | None,
    symbol: str,
    timeframe: str,
    bars: int,
    retries: int,
    semaphore: asyncio.Semaphore,
    pacer: _Pacer,
) -> tuple[str, int | None]:
    """Ingest one symbol with retries. Returns ``(symbol, rows)``; rows is None on failure."""
    async with semaphore:
        for attempt in range(retries + 1):
            await pacer.wait()
            try:
                rows = await ingest_ohlcv(
                    settings=settings,
                    pool=pool,
                    redis=redis,
                    symbol=symbol,
                    timeframe=timeframe,
                    bars_count=bars,
                )
            except (TvkitFetchError, RepositoryError) as exc:
                if attempt == retries:
                    logger.warning(
                        "daily ingest gave up on %s after %d attempt(s): %s",
                        symbol,
                        retries + 1,
                        exc,
                    )
                    return symbol, None
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
            else:
                return symbol, rows
    return symbol, None  # pragma: no cover - loop always returns


async def run_daily_ingest(
    *,
    settings: Settings,
    pool: asyncpg.Pool,
    redis: aioredis.Redis | None,
    timeframe: str = "1d",
    bars: int = DEFAULT_BARS,
    symbols: Sequence[str] | None = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    retries: int = DEFAULT_RETRIES,
    limit: int | None = None,
    min_interval: float = DEFAULT_MIN_INTERVAL_SECONDS,
) -> DailyIngestResult:
    """Refresh a recent window for every tracked symbol at ``timeframe``.

    Args:
        settings: Engine settings (must be owner mode with a valid cookie).
        pool: asyncpg pool onto ``db_market_data``.
        redis: Redis client for the single-flight lock and cache invalidation.
        timeframe: One of ``1d`` / ``1h`` / ``5m``.
        bars: Recent bar depth per symbol — the refresh window.
        symbols: Explicit override; defaults to every symbol already in the store.
        concurrency: Max simultaneous tvkit fetches.
        retries: Retries per symbol after the first attempt.
        limit: Optional cap on symbol count (smoke tests).
        min_interval: Minimum seconds between fetch starts — the upstream rate
            ceiling. ``0`` disables pacing.

    Returns:
        A :class:`DailyIngestResult` summary.

    Raises:
        IngestDisabledError: if the service is in public (read-only) mode.
        CookieConfigError: if the tvkit cookie is missing or malformed.
        RepositoryError: if the symbol list cannot be read.
    """
    # Fail fast on configuration: these would fail identically for every symbol.
    if settings.public_mode:
        raise IngestDisabledError(
            "daily ingest is disabled in public mode (set MARKETDATA_ENGINE_PUBLIC_MODE=false)"
        )
    settings.tvkit_cookies()  # raises CookieConfigError; value never logged

    resolved = (
        list(symbols)
        if symbols is not None
        else await list_tracked_symbols(pool, timeframe=timeframe)
    )
    if limit is not None:
        resolved = resolved[:limit]

    logger.info(
        "daily ingest starting timeframe=%s symbols=%d bars=%d concurrency=%d min_interval=%.2fs",
        timeframe,
        len(resolved),
        bars,
        concurrency,
        min_interval,
    )
    if not resolved:
        logger.error(
            "daily ingest resolved 0 symbols for timeframe=%s — nothing to refresh", timeframe
        )
        return DailyIngestResult(
            timeframe=timeframe, attempted=0, succeeded=0, failed=0, rows_written=0
        )

    semaphore = asyncio.Semaphore(max(1, concurrency))
    pacer = _Pacer(min_interval)
    outcomes = await asyncio.gather(
        *(
            _ingest_one(
                settings=settings,
                pool=pool,
                redis=redis,
                symbol=symbol,
                timeframe=timeframe,
                bars=bars,
                retries=retries,
                semaphore=semaphore,
                pacer=pacer,
            )
            for symbol in resolved
        )
    )

    failures = [symbol for symbol, rows in outcomes if rows is None]
    written = sum(rows for _, rows in outcomes if rows is not None)
    result = DailyIngestResult(
        timeframe=timeframe,
        attempted=len(outcomes),
        succeeded=len(outcomes) - len(failures),
        failed=len(failures),
        rows_written=written,
        failures=failures,
    )
    logger.info(
        "daily ingest complete timeframe=%s attempted=%d succeeded=%d failed=%d rows=%d",
        result.timeframe,
        result.attempted,
        result.succeeded,
        result.failed,
        result.rows_written,
    )
    if failures:
        # Listed in full rather than truncated: a silent cap would read as
        # "everything succeeded" on the next person to look at the log.
        logger.warning("daily ingest failed symbols (%d): %s", len(failures), ", ".join(failures))
    return result
