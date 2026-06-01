"""Command-line ingest entrypoint (owner mode only).

    uv run python -m src.quant_marketdata_engine.ingest fetch \
        --symbol SET:PTT --timeframe 1d --bars 5000
    uv run python -m src.quant_marketdata_engine.ingest backfill \
        --dir ../strategies/csm-set/data/raw/dividends

Owner mode (``MARKETDATA_ENGINE_PUBLIC_MODE=false``) + a valid ``TVKIT_AUTH_TOKEN``
are required for ``fetch``; ``backfill`` only needs DB access.
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
    return parser


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
