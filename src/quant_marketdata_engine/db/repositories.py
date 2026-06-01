"""Async asyncpg repository helpers for the ``market_data`` store.

Each function takes an ``asyncpg.Pool`` connected to ``db_market_data`` and uses
parameterized SQL — symbols/timeframes never interpolate into SQL text, so the
read API is injection-safe. Writes are idempotent
(``INSERT … ON CONFLICT (…) DO UPDATE``); ``ingested_at`` is DB-defaulted so a
re-run does not churn the audit column for unchanged bars.

Mirrors ``quant-infra-db/src/db/repositories.py`` (the authoritative reference);
the engine owns its copy because ``quant-infra-db`` is not an importable package.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date, datetime

import asyncpg

from src.quant_marketdata_engine.db.errors import RepositoryError
from src.quant_marketdata_engine.db.models import (
    CorporateActionRow,
    OHLCVBarRow,
    UniverseMembershipRow,
)

logger = logging.getLogger(__name__)

# Column list shared by the base table and the adjust-on-read view (same shape).
_BAR_COLUMNS = (
    "symbol, timeframe, ts, open, high, low, close, volume, open_interest, source, ingested_at"
)

_OHLCV_UPSERT_SQL = """
INSERT INTO market_data.ohlcv (
    symbol, timeframe, ts, open, high, low, close, volume, open_interest, source
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
ON CONFLICT (symbol, timeframe, ts) DO UPDATE SET
    open          = EXCLUDED.open,
    high          = EXCLUDED.high,
    low           = EXCLUDED.low,
    close         = EXCLUDED.close,
    volume        = EXCLUDED.volume,
    open_interest = EXCLUDED.open_interest,
    source        = EXCLUDED.source,
    ingested_at   = now()
"""

_CORPORATE_ACTION_UPSERT_SQL = """
INSERT INTO market_data.corporate_actions (
    symbol, ex_date, action_type, ratio, amount, note
)
VALUES ($1, $2, $3, $4, $5, $6)
ON CONFLICT (symbol, ex_date, action_type) DO UPDATE SET
    ratio       = EXCLUDED.ratio,
    amount      = EXCLUDED.amount,
    note        = EXCLUDED.note,
    ingested_at = now()
"""

_UNIVERSE_MEMBERSHIP_UPSERT_SQL = """
INSERT INTO market_data.universe_membership (as_of, symbol, index_name)
VALUES ($1, $2, $3)
ON CONFLICT (as_of, symbol, index_name) DO UPDATE SET
    ingested_at = now()
"""


async def upsert_ohlcv(pool: asyncpg.Pool, rows: Sequence[OHLCVBarRow]) -> int:
    """Idempotently upsert a batch of raw OHLCV bars. Returns the row count."""
    if not rows:
        return 0
    payload = [
        (
            r.symbol,
            r.timeframe,
            r.ts,
            r.open,
            r.high,
            r.low,
            r.close,
            r.volume,
            r.open_interest,
            r.source,
        )
        for r in rows
    ]
    try:
        async with pool.acquire() as conn:
            await conn.executemany(_OHLCV_UPSERT_SQL, payload)
    except Exception as exc:
        raise RepositoryError(f"upsert_ohlcv failed: {exc}") from exc
    logger.info("upserted %d market_data.ohlcv rows", len(payload))
    return len(payload)


def _rows_from_records(records: Sequence[asyncpg.Record]) -> list[OHLCVBarRow]:
    """Map asyncpg records (model column shape) to ``OHLCVBarRow``."""
    return [OHLCVBarRow(**dict(r)) for r in records]


async def _fetch_bars(
    pool: asyncpg.Pool,
    *,
    relation: str,
    symbol: str,
    timeframe: str,
    start: datetime | None,
    end: datetime | None,
    limit: int,
) -> list[OHLCVBarRow]:
    """Fetch bars (ascending by ``ts``) from ``market_data.ohlcv`` or the view.

    ``relation`` is a trusted literal chosen by the caller (never user input).
    """
    clauses = ["symbol = $1", "timeframe = $2"]
    args: list[object] = [symbol, timeframe]
    if start is not None:
        args.append(start)
        clauses.append(f"ts >= ${len(args)}")
    if end is not None:
        args.append(end)
        clauses.append(f"ts <= ${len(args)}")
    args.append(limit)
    where = " AND ".join(clauses)
    sql = f"SELECT {_BAR_COLUMNS} FROM {relation} WHERE {where} ORDER BY ts ASC LIMIT ${len(args)}"
    try:
        async with pool.acquire() as conn:
            records = await conn.fetch(sql, *args)
    except Exception as exc:
        raise RepositoryError(f"fetch from {relation} failed: {exc}") from exc
    return _rows_from_records(records)


async def fetch_ohlcv(
    pool: asyncpg.Pool,
    *,
    symbol: str,
    timeframe: str,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 5000,
) -> list[OHLCVBarRow]:
    """Fetch raw bars for ``(symbol, timeframe)`` in ``[start, end]`` (index-backed)."""
    return await _fetch_bars(
        pool,
        relation="market_data.ohlcv",
        symbol=symbol,
        timeframe=timeframe,
        start=start,
        end=end,
        limit=limit,
    )


async def fetch_ohlcv_adjusted(
    pool: asyncpg.Pool,
    *,
    symbol: str,
    timeframe: str,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 5000,
) -> list[OHLCVBarRow]:
    """Fetch adjust-on-read bars from the ``market_data.ohlcv_adjusted`` view."""
    return await _fetch_bars(
        pool,
        relation="market_data.ohlcv_adjusted",
        symbol=symbol,
        timeframe=timeframe,
        start=start,
        end=end,
        limit=limit,
    )


async def upsert_corporate_actions(pool: asyncpg.Pool, rows: Sequence[CorporateActionRow]) -> int:
    """Idempotently upsert corporate-action / roll rows. Returns the row count."""
    if not rows:
        return 0
    payload = [(r.symbol, r.ex_date, r.action_type, r.ratio, r.amount, r.note) for r in rows]
    try:
        async with pool.acquire() as conn:
            await conn.executemany(_CORPORATE_ACTION_UPSERT_SQL, payload)
    except Exception as exc:
        raise RepositoryError(f"upsert_corporate_actions failed: {exc}") from exc
    logger.info("upserted %d market_data.corporate_actions rows", len(payload))
    return len(payload)


async def upsert_universe_membership(
    pool: asyncpg.Pool, rows: Sequence[UniverseMembershipRow]
) -> int:
    """Idempotently upsert universe-membership rows. Returns the row count."""
    if not rows:
        return 0
    payload = [(r.as_of, r.symbol, r.index_name) for r in rows]
    try:
        async with pool.acquire() as conn:
            await conn.executemany(_UNIVERSE_MEMBERSHIP_UPSERT_SQL, payload)
    except Exception as exc:
        raise RepositoryError(f"upsert_universe_membership failed: {exc}") from exc
    logger.info("upserted %d market_data.universe_membership rows", len(payload))
    return len(payload)


async def fetch_universe(
    pool: asyncpg.Pool,
    *,
    as_of: date,
    index_name: str = "SET",
) -> tuple[date | None, list[str]]:
    """Return ``(resolved_as_of, symbols)`` point-in-time for ``index_name``.

    Resolves to the latest snapshot on or before ``as_of`` (no look-ahead). When
    no snapshot exists at/before ``as_of``, returns ``(None, [])``.
    """
    try:
        async with pool.acquire() as conn:
            resolved: date | None = await conn.fetchval(
                "SELECT max(as_of) FROM market_data.universe_membership "
                "WHERE index_name = $1 AND as_of <= $2",
                index_name,
                as_of,
            )
            if resolved is None:
                return None, []
            records = await conn.fetch(
                "SELECT symbol FROM market_data.universe_membership "
                "WHERE index_name = $1 AND as_of = $2 ORDER BY symbol ASC",
                index_name,
                resolved,
            )
    except Exception as exc:
        raise RepositoryError(f"fetch_universe failed: {exc}") from exc
    return resolved, [str(r["symbol"]) for r in records]
