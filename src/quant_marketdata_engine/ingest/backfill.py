"""One-time best-effort backfill from on-disk csm-set Parquet OHLCV.

Seeds ``market_data.ohlcv`` from the fresh fetch already on disk
(``strategies/csm-set/data/raw/dividends/``) so Phase 2 need not re-pull ~700
symbols from TradingView. **Best-effort:** if the source directory is absent or a
file is unreadable, it logs and skips — it never raises for missing data and is
never part of the quality gate.

Provenance note: the csm-set ``dividends/`` bars are **dividend-adjusted** daily
bars (total-return). They are tagged ``source='csm-backfill-div'`` so a later
phase can re-derive the raw + adjust-on-read series; full adjustment-math parity
is a documented Phase-5 cutover concern, not a Phase-2 requirement.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import unquote

import asyncpg
import pyarrow.parquet as pq

from src.quant_marketdata_engine.db.models import OHLCVBarRow
from src.quant_marketdata_engine.db.repositories import upsert_ohlcv

logger = logging.getLogger(__name__)

_BACKFILL_SOURCE = "csm-backfill-div"
_PRICE_COLUMNS = ("open", "high", "low", "close")


def _rows_from_parquet(path: Path, *, symbol: str, timeframe: str) -> list[OHLCVBarRow]:
    """Map a csm-set OHLCV parquet file to ``OHLCVBarRow`` (UTC, Decimal).

    Rows with non-positive prices (which would violate the DB CHECK) are skipped.
    """
    table = pq.read_table(path)  # type: ignore[no-untyped-call]
    records = table.to_pylist()
    rows: list[OHLCVBarRow] = []
    skipped = 0
    for rec in records:
        dt = rec.get("datetime")
        if dt is None:
            skipped += 1
            continue
        try:
            prices = {c: Decimal(str(rec[c])) for c in _PRICE_COLUMNS}
            if any(p <= 0 for p in prices.values()):
                skipped += 1
                continue
            volume = Decimal(str(rec.get("volume", 0)))
            rows.append(
                OHLCVBarRow(
                    symbol=symbol,
                    timeframe=timeframe,
                    ts=dt.astimezone(UTC),
                    open=prices["open"],
                    high=prices["high"],
                    low=prices["low"],
                    close=prices["close"],
                    volume=volume,
                    open_interest=None,
                    source=_BACKFILL_SOURCE,
                )
            )
        except (InvalidOperation, ValueError, KeyError):
            skipped += 1
    if skipped:
        logger.warning("backfill %s: skipped %d invalid rows", symbol, skipped)
    return rows


def _iter_parquet_files(source_dir: Path, limit_files: int | None) -> Sequence[Path]:
    files = sorted(source_dir.glob("*.parquet"))
    return files if limit_files is None else files[:limit_files]


async def backfill_from_dir(
    pool: asyncpg.Pool,
    source_dir: Path,
    *,
    timeframe: str = "1d",
    limit_files: int | None = None,
) -> int:
    """Backfill ``market_data.ohlcv`` from a directory of csm-set parquet files.

    The symbol is the URL-decoded filename stem (``SET%3APTT`` → ``SET:PTT``).
    Returns the total number of bars upserted (0 if the directory is absent).
    """
    if not source_dir.is_dir():
        logger.warning("backfill source dir not found: %s — skipping", source_dir)
        return 0

    total = 0
    files = _iter_parquet_files(source_dir, limit_files)
    logger.info("backfill starting: %d parquet files from %s", len(files), source_dir)
    for path in files:
        symbol = unquote(path.stem)
        try:
            rows = _rows_from_parquet(path, symbol=symbol, timeframe=timeframe)
        except Exception:
            logger.warning("backfill: failed to read %s — skipping", path, exc_info=True)
            continue
        if rows:
            total += await upsert_ohlcv(pool, rows)
    logger.info("backfill complete: %d bars upserted from %s", total, source_dir)
    return total
