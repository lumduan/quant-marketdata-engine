"""Command-line ingest entrypoint (owner mode only).

    uv run python -m src.quant_marketdata_engine.ingest fetch \
        --symbol SET:PTT --timeframe 1d --bars 5000
    uv run python -m src.quant_marketdata_engine.ingest daily \
        --timeframe 1d --bars 30
    uv run python -m src.quant_marketdata_engine.ingest backfill \
        --dir ../strategies/csm-set/data/raw/dividends

Owner mode (``MARKETDATA_ENGINE_PUBLIC_MODE=false``) + a valid ``TVKIT_AUTH_TOKEN``
are required for ``fetch`` and ``daily``; ``backfill`` only needs DB access.

``daily`` is the scheduled bulk refresh — it re-fetches a recent window for every
symbol already in the store. See ``docs/operations/scheduled-ingest.md``.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

from src.quant_marketdata_engine.cache.redis_client import close_redis, create_redis
from src.quant_marketdata_engine.config.settings import Settings, get_settings
from src.quant_marketdata_engine.db.postgres import close_pool, create_pool, get_pool
from src.quant_marketdata_engine.ingest.backfill import backfill_from_dir
from src.quant_marketdata_engine.ingest.daily import (
    DEFAULT_BARS,
    DEFAULT_CONCURRENCY,
    DEFAULT_MIN_INTERVAL_SECONDS,
    DEFAULT_RETRIES,
    run_daily_ingest,
)
from src.quant_marketdata_engine.ingest.service import ingest_ohlcv
from src.quant_marketdata_engine.logging_config import configure_logging

logger = logging.getLogger(__name__)


def _parse_ts(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def build_parser() -> argparse.ArgumentParser:
    """Build the ingest CLI argument parser."""
    parser = argparse.ArgumentParser(prog="quant_marketdata_engine.ingest")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="Fetch bars from tvkit and upsert.")
    fetch.add_argument("--symbol", required=True, help="e.g. SET:PTT, TFEX:S501!")
    fetch.add_argument("--timeframe", required=True, choices=["1d", "1h", "5m"])
    fetch.add_argument("--bars", type=int, default=None, help="Bar depth (premium >5000).")
    fetch.add_argument("--start", default=None, help="ISO-8601 UTC start (optional).")
    fetch.add_argument("--end", default=None, help="ISO-8601 UTC end (optional).")

    backfill = sub.add_parser("backfill", help="Backfill from csm-set parquet dir.")
    backfill.add_argument("--dir", required=True, help="Source directory of *.parquet.")
    backfill.add_argument("--timeframe", default="1d", choices=["1d", "1h", "5m"])
    backfill.add_argument("--limit-files", type=int, default=None)

    daily = sub.add_parser("daily", help="Bulk-refresh every tracked symbol (scheduled run).")
    daily.add_argument("--timeframe", default="1d", choices=["1d", "1h", "5m"])
    daily.add_argument(
        "--bars", type=int, default=DEFAULT_BARS, help="Recent bar depth per symbol."
    )
    daily.add_argument("--symbols", default=None, help="Comma-separated override list.")
    daily.add_argument("--symbols-file", default=None, help="Newline-delimited symbol file.")
    daily.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    daily.add_argument("--retries", type=int, default=DEFAULT_RETRIES)
    daily.add_argument(
        "--min-interval",
        type=float,
        default=DEFAULT_MIN_INTERVAL_SECONDS,
        help="Min seconds between fetch starts (upstream rate ceiling; 0 disables).",
    )
    daily.add_argument("--limit", type=int, default=None, help="Cap symbol count (smoke tests).")
    return parser


def _resolve_symbols(args: argparse.Namespace) -> list[str] | None:
    """Resolve an explicit symbol override from ``--symbols`` / ``--symbols-file``."""
    if getattr(args, "symbols", None):
        return [s.strip() for s in str(args.symbols).split(",") if s.strip()]
    path = getattr(args, "symbols_file", None)
    if path:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        return [s.strip() for s in lines if s.strip() and not s.lstrip().startswith("#")]
    return None


async def _run(args: argparse.Namespace, settings: Settings) -> int:
    await create_pool(
        settings.pg_dsn,
        min_size=settings.pg_pool_min_size,
        max_size=settings.pg_pool_max_size,
    )
    redis = create_redis(settings.redis_url)
    try:
        if args.command == "fetch":
            return await ingest_ohlcv(
                settings=settings,
                pool=get_pool(),
                redis=redis,
                symbol=args.symbol,
                timeframe=args.timeframe,
                bars_count=args.bars,
                start=_parse_ts(args.start),
                end=_parse_ts(args.end),
            )
        if args.command == "daily":
            result = await run_daily_ingest(
                settings=settings,
                pool=get_pool(),
                redis=redis,
                timeframe=args.timeframe,
                bars=args.bars,
                symbols=_resolve_symbols(args),
                concurrency=args.concurrency,
                retries=args.retries,
                limit=args.limit,
                min_interval=args.min_interval,
            )
            # ``__main__`` maps a negative return to exit 1, so a run that
            # resolved no symbols or lost every symbol surfaces to cron as a
            # failure instead of a silent success.
            return result.rows_written if result.ok else -1
        return await backfill_from_dir(
            get_pool(),
            Path(args.dir),
            timeframe=args.timeframe,
            limit_files=args.limit_files,
        )
    finally:
        await close_redis()
        await close_pool()


def main(argv: list[str] | None = None) -> int:
    """Parse args, run the ingest/backfill, and return the rows-written count."""
    args = build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    rows = asyncio.run(_run(args, settings))
    logger.info("%s wrote %d rows", args.command, rows)
    return rows
