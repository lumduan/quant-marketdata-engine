#!/usr/bin/env python3
"""csm-set parity verification: engine read API vs legacy Parquet store.

Reads dividend-adjusted OHLCV from the csm-set Parquet directory
(``strategies/csm-set/data/raw/dividends/*.parquet``) and compares each
symbol's bars against what the Market Data Engine returns for the same
``(symbol, timeframe)`` via its ``GET /ohlcv`` endpoint.

The Parquet store is the *ground truth* the csm-set strategy was validated
on; the engine DB is seeded from those same files via ``backfill.py``, so
this is a deterministic end-to-end test of the full read pipeline.

Usage::

    uv run python tests/verification/verify_csm_parity.py \\
        --parquet-dir ../strategies/csm-set/data/raw/dividends \\
        --output reports/verification-csm.json

Exit code 0 on 100% parity; non-zero on any mismatch / missing data / error.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx
import pandas as pd
from verification_utils import (
    add_shared_args,
    build_report,
    compare_ohlcv_frames,
    setup_logging,
    write_report,
)

logger: logging.Logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — matching csm-set's canonical OHLCV DataFrame shape
# (csm.data.engine_loader._OHLCV_COLUMNS + TIMEZONE)
# ---------------------------------------------------------------------------

_OHLCV_COLUMNS: list[str] = ["open", "high", "low", "close", "volume"]
_TIMEZONE: str = "Asia/Bangkok"

# Symbols known to be deferred from Phase 3 — skip these with a note.
_DEFERRED_PATTERNS: tuple[str, ...] = ("SET:SET", "SET:S10", "SET:S50", "SET:S100")


# ---------------------------------------------------------------------------
# Engine client (minimal — avoids cross-repo imports)
# ---------------------------------------------------------------------------


class _EngineOhlcvBar:
    """Parsed engine bar — mirror of ``EngineOHLCVBar`` from the read API."""

    __slots__ = ("ts", "open", "high", "low", "close", "volume", "open_interest")

    def __init__(self, raw: dict[str, Any]) -> None:
        self.ts: datetime = datetime.fromisoformat(raw["ts"])
        self.open = Decimal(raw["open"])
        self.high = Decimal(raw["high"])
        self.low = Decimal(raw["low"])
        self.close = Decimal(raw["close"])
        self.volume = Decimal(raw["volume"])
        self.open_interest: Decimal | None = (
            Decimal(raw["open_interest"]) if raw.get("open_interest") is not None else None
        )


def _engine_response_to_csm_frame(bars: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert engine JSON bars to the canonical csm OHLCV DataFrame shape.

    Matches ``MarketDataEngineLoader._response_to_frame``:
    Decimal → float, UTC ts → Asia/Bangkok DatetimeIndex, sorted.
    """
    empty_index: pd.DatetimeIndex = pd.DatetimeIndex([], tz=_TIMEZONE, name="datetime")
    if not bars:
        return pd.DataFrame(columns=_OHLCV_COLUMNS, index=empty_index)

    records: list[dict[str, float]] = [
        {
            "open": float(bar["open"]),
            "high": float(bar["high"]),
            "low": float(bar["low"]),
            "close": float(bar["close"]),
            "volume": float(bar["volume"]),
        }
        for bar in bars
    ]
    raw_index: pd.DatetimeIndex = pd.DatetimeIndex([bar["ts"] for bar in bars])
    if raw_index.tz is None:
        raw_index = raw_index.tz_localize("UTC")
    index: pd.DatetimeIndex = raw_index.tz_convert(_TIMEZONE)
    index.name = "datetime"
    frame: pd.DataFrame = pd.DataFrame.from_records(records, index=index)
    return frame[_OHLCV_COLUMNS].sort_index()


def _read_parquet_frame(path: Path) -> pd.DataFrame:
    """Read a csm-set OHLCV Parquet file into the canonical DataFrame shape.

    csm-set Parquet files have columns ``[open, high, low, close, volume]``
    (float64) and a ``datetime`` index (Asia/Bangkok tz-aware). The schema is
    verified before returning.
    """
    frame: pd.DataFrame = pd.read_parquet(path)

    # Ensure index is a tz-aware DatetimeIndex named "datetime"
    if frame.index.name != "datetime" or not isinstance(frame.index, pd.DatetimeIndex):
        # Try to recover: look for a "datetime" column
        if "datetime" in frame.columns:
            frame["datetime"] = pd.to_datetime(frame["datetime"])
            frame = frame.set_index("datetime")
        else:
            raise ValueError(f"Parquet at {path} has no DatetimeIndex named 'datetime'")

    if frame.index.tz is None:
        frame.index = frame.index.tz_localize(_TIMEZONE)

    # Keep only OHLCV columns in the expected order
    for col in _OHLCV_COLUMNS:
        if col not in frame.columns:
            raise ValueError(f"Parquet at {path} is missing column {col!r}")
    return frame[_OHLCV_COLUMNS].sort_index()


# ---------------------------------------------------------------------------
# Main verification logic
# ---------------------------------------------------------------------------


async def _fetch_engine_bars(
    client: httpx.AsyncClient,
    engine_base_url: str,
    symbol: str,
    timeframe: str,
    limit: int,
    api_key: str | None,
) -> list[dict[str, Any]]:
    """Fetch bars for a single symbol from the engine read API.

    Returns the raw ``bars`` list from the JSON response, or raises on error.
    """
    params: dict[str, str | int] = {
        "symbol": symbol,
        "timeframe": timeframe,
        "limit": limit,
    }
    headers: dict[str, str] = {}
    if api_key is not None:
        headers["X-API-Key"] = api_key

    url: str = f"{engine_base_url.rstrip('/')}/ohlcv"
    response: httpx.Response = await client.get(url, params=params, headers=headers)
    response.raise_for_status()
    payload: dict[str, Any] = response.json()
    bars: list[dict[str, Any]] = payload.get("bars", [])
    return bars


async def _verify_one_symbol(
    client: httpx.AsyncClient,
    engine_base_url: str,
    symbol: str,
    parquet_dir: Path,
    timeframe: str,
    limit: int,
    api_key: str | None,
    tolerance_price: float,
    tolerance_volume: float,
    sem: asyncio.Semaphore,
) -> dict[str, Any]:
    """Verify one symbol — read Parquet + engine, compare, return result dict."""
    # --- Read Parquet (ground truth) ---
    from urllib.parse import quote

    parquet_path: Path = parquet_dir / f"{quote(symbol, safe='')}.parquet"
    try:
        expected: pd.DataFrame = _read_parquet_frame(parquet_path)
    except FileNotFoundError:
        return {
            "symbol": symbol,
            "status": "no_data",
            "note": f"Parquet file not found: {parquet_path}",
        }
    except Exception as exc:
        logger.error("Failed to read Parquet for %s: %s", symbol, exc)
        return {"symbol": symbol, "status": "error", "note": str(exc)}

    # --- Read engine ---
    async with sem:
        try:
            bars = await _fetch_engine_bars(
                client, engine_base_url, symbol, timeframe, limit, api_key
            )
        except httpx.HTTPStatusError as exc:
            logger.error("Engine returned %d for %s: %s", exc.response.status_code, symbol, exc)
            return {
                "symbol": symbol,
                "status": "error",
                "note": f"HTTP {exc.response.status_code}: {exc.response.text[:200]}",
            }
        except httpx.HTTPError as exc:
            logger.error("Engine transport error for %s: %s", symbol, exc)
            return {"symbol": symbol, "status": "error", "note": f"Transport error: {exc}"}

    actual: pd.DataFrame = _engine_response_to_csm_frame(bars)

    # --- Compare ---
    result: Any = compare_ohlcv_frames(
        expected,
        actual,
        tolerance_price=tolerance_price,
        tolerance_volume=tolerance_volume,
    )
    mismatch_count: int = len(result.mismatch_details)
    return {
        "symbol": symbol,
        "status": result.status,
        "expected_bars": len(expected),
        "actual_bars": len(actual),
        "max_price_diff": result.max_price_diff,
        "max_volume_diff": result.max_volume_diff,
        "mismatch_count": mismatch_count,
        "missing_in_expected": result.missing_in_expected,
        "missing_in_actual": result.missing_in_actual,
        "mismatches": [
            {
                "timestamp": m.timestamp,
                "column": m.column,
                "expected_value": m.expected_value,
                "actual_value": m.actual_value,
                "absolute_diff": m.absolute_diff,
            }
            for m in result.mismatch_details[:50]  # cap to avoid huge reports
        ],
        "note": result.note,
    }


def _is_deferred(symbol: str) -> bool:
    """Check if a symbol is a known-deferred index/sector."""
    return any(symbol == p or symbol.startswith(p + ":") for p in _DEFERRED_PATTERNS)


async def main() -> int:
    """Entry point — parse args, discover symbols, run verification, write report."""
    parser = argparse.ArgumentParser(
        description="csm-set parity: engine vs Parquet OHLCV comparison"
    )
    add_shared_args(parser)
    parser.add_argument(
        "--parquet-dir",
        type=Path,
        required=True,
        help="Path to csm-set data/raw/dividends/ directory",
    )
    parser.add_argument(
        "--symbols",
        default="ALL",
        help="Comma-separated symbol list, or 'ALL' (default: ALL)",
    )
    parser.add_argument("--timeframe", default="1d", help="Engine timeframe (default: 1d)")
    parser.add_argument(
        "--limit", type=int, default=5000, help="Max bars per symbol (default: 5000)"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Max concurrent engine requests (default: 4)",
    )
    args = parser.parse_args()
    setup_logging(args.verbose)

    start_time: datetime = datetime.now(UTC)

    # --- Discover symbols ---
    all_symbols: list[str] = sorted(
        s
        for s in (unquote(p.stem) for p in args.parquet_dir.glob("*.parquet"))
        if not _is_deferred(s)
    )
    if args.symbols != "ALL":
        requested: set[str] = {s.strip() for s in args.symbols.split(",") if s.strip()}
        all_symbols = [s for s in all_symbols if s in requested]

    if not all_symbols:
        logger.error("No symbols found in %s", args.parquet_dir)
        return 1

    # --- Identify deferred ---
    deferred_all: list[str] = sorted(
        s for s in (unquote(p.stem) for p in args.parquet_dir.glob("*.parquet")) if _is_deferred(s)
    )
    skipped: list[dict[str, str]] = [
        {"symbol": s, "reason": "Known deferred (Phase 3: SET index/sectors)"} for s in deferred_all
    ]

    logger.info(
        "Verifying %d symbols against %s (skipping %d deferred), concurrency=%d",
        len(all_symbols),
        args.engine_base_url,
        len(skipped),
        args.concurrency,
    )

    # --- Run verification ---
    sem: asyncio.Semaphore = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks: list[asyncio.Task[dict[str, Any]]] = [
            asyncio.create_task(
                _verify_one_symbol(
                    client,
                    args.engine_base_url,
                    symbol,
                    args.parquet_dir,
                    args.timeframe,
                    args.limit,
                    args.api_key,
                    args.tolerance_price,
                    args.tolerance_volume,
                    sem,
                )
            )
            for symbol in all_symbols
        ]
        results: list[dict[str, Any]] = await asyncio.gather(*tasks)

    # --- Build report ---
    symbols_report: dict[str, dict[str, Any]] = {}
    for r in results:
        sym: str = r.pop("symbol")
        symbols_report[sym] = r

    report: dict[str, Any] = build_report(
        verification="csm_parity",
        engine_base_url=args.engine_base_url,
        start_time=start_time,
        symbols=symbols_report,
        skipped=skipped,
        tolerance_price=args.tolerance_price,
        tolerance_volume=args.tolerance_volume,
    )
    write_report(report, args.output)

    # --- Summary to stderr ---
    summary: dict[str, Any] = report["summary"]
    logger.info(
        "csm-set verification: %d total, %d matched, %d tolerance, "
        "%d mismatched, %d missing, %d errors, %d skipped → parity=%s",
        summary["total_symbols"],
        summary["matched_exactly"],
        summary["matched_with_tolerance"],
        summary["mismatched"],
        summary["missing_data"],
        summary["errors"],
        summary["skipped"],
        summary["overall_parity"],
    )

    return 0 if summary["overall_parity"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
