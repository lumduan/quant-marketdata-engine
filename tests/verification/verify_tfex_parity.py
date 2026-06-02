#!/usr/bin/env python3
"""tfex parity verification: engine read API vs legacy mirror Parquet store.

Reads raw OHLCV from the tfex mirror Parquet directory
(``strategies/tfex-s50-multi-tf-swing/data/raw/``) and compares each
contract+timeframe against what the Market Data Engine returns for the same
``(symbol, timeframe)`` via its ``GET /ohlcv`` endpoint.

The mirror Parquet store is the *ground truth* the tfex strategy was validated
on. Comparison is on the **shared columns** only:
``[time, open, high, low, close, volume]`` — ``open_interest`` is excluded
because the legacy mirror predates it.

Usage::

    uv run python tests/verification/verify_tfex_parity.py \\
        --mirror-dir ../strategies/tfex-s50-multi-tf-swing/data/raw \\
        --start 2025-01-01T00:00:00Z --end 2026-06-01T00:00:00Z \\
        --output reports/verification-tfex.json

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

import httpx
import polars as pl
from verification_utils import (
    add_shared_args,
    build_report,
    setup_logging,
    write_report,
)

logger: logging.Logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — matching tfex's raw-frame shape
# (data/engine_fetcher.py: _bars_to_frame + _PRICE_SCALE)
# ---------------------------------------------------------------------------

_SHARED_COLUMNS: list[str] = ["time", "open", "high", "low", "close", "volume"]
_PRICE_SCALE: Decimal = Decimal("0.0001")

# Timeframes the engine serves — 4h is intentionally absent.
_ENGINE_TIMEFRAMES: dict[str, str] = {"5m": "5m", "1h": "1h"}

# tfex contract code → engine symbol mapping (direct — same code).
# See tfex data/contracts.py:engine_symbol_for_contract.
_ENGINE_SYMBOL_PREFIX: str = "TFEX:" if False else ""  # no prefix for engine direct access


def _engine_symbol_for_contract(contract_code: str) -> str:
    """Map a tfex contract code to the engine symbol."""
    # Engine stores symbols as e.g. "TFEX:S50M2026" when ingested via tvkit,
    # but the verification scripts talk to the engine directly (not via the
    # gateway proxy with its prefix). The engine's /ohlcv endpoint accepts
    # whatever symbol was ingested. For direct host access, try both the
    # bare contract code and the TFEX: prefixed form.
    return contract_code


# ---------------------------------------------------------------------------
# Engine client (minimal — avoids cross-repo imports)
# ---------------------------------------------------------------------------


def _quantize(value: Decimal) -> Decimal:
    """Quantize an engine Decimal (scale 6) down to the store's scale 4."""
    return value.quantize(_PRICE_SCALE)


def _bars_to_polars_frame(
    bars: list[dict[str, Any]], *, start: datetime, end: datetime
) -> pl.DataFrame:
    """Convert engine JSON bars to the canonical tfex raw-frame shape.

    Matches ``EngineOhlcvFetcher._bars_to_frame``:
    Decimal(18,6) → Decimal(18,4), window-filter to [start, end), sort by time.
    """
    rows: list[dict[str, object]] = []
    for bar in bars:
        t: datetime = datetime.fromisoformat(bar["ts"])
        if t.tzinfo is None:
            t = t.replace(tzinfo=UTC)
        if t < start or t >= end:
            continue
        rows.append(
            {
                "time": t,
                "open": _quantize(Decimal(bar["open"])),
                "high": _quantize(Decimal(bar["high"])),
                "low": _quantize(Decimal(bar["low"])),
                "close": _quantize(Decimal(bar["close"])),
                "volume": _quantize(Decimal(bar["volume"])),
                "open_interest": (
                    _quantize(Decimal(bar["open_interest"]))
                    if bar.get("open_interest") is not None
                    else None
                ),
            }
        )

    if not rows:
        return pl.DataFrame(
            schema={
                "time": pl.Datetime(time_unit="us", time_zone="UTC"),
                "open": pl.Decimal(18, 4),
                "high": pl.Decimal(18, 4),
                "low": pl.Decimal(18, 4),
                "close": pl.Decimal(18, 4),
                "volume": pl.Decimal(18, 4),
                "open_interest": pl.Decimal(18, 4),
            }
        )

    return (
        pl.DataFrame(rows)
        .with_columns(
            [
                pl.col("time").dt.replace_time_zone("UTC"),
                pl.col("open").cast(pl.Decimal(18, 4)),
                pl.col("high").cast(pl.Decimal(18, 4)),
                pl.col("low").cast(pl.Decimal(18, 4)),
                pl.col("close").cast(pl.Decimal(18, 4)),
                pl.col("volume").cast(pl.Decimal(18, 4)),
                pl.col("open_interest").cast(pl.Decimal(18, 4)),
            ]
        )
        .sort("time")
    )


def _read_mirror_parquet(path: Path) -> pl.DataFrame:
    """Read a tfex mirror Parquet file into a Polars DataFrame."""
    frame: pl.DataFrame = pl.read_parquet(path)
    # Ensure shared columns exist
    for col in _SHARED_COLUMNS:
        if col not in frame.columns:
            raise ValueError(f"Mirror Parquet at {path} is missing column {col!r}")
    return frame.select(_SHARED_COLUMNS).sort("time")


# ---------------------------------------------------------------------------
# Main verification logic
# ---------------------------------------------------------------------------


async def _fetch_engine_bars(
    client: httpx.AsyncClient,
    engine_base_url: str,
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    api_key: str | None,
) -> list[dict[str, Any]]:
    """Fetch bars for a single contract+timeframe from the engine."""
    params: dict[str, str | int] = {
        "symbol": symbol,
        "timeframe": timeframe,
        "limit": 50000,
        "start": start.isoformat(),
        "end": end.isoformat(),
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


async def _verify_one_contract(
    client: httpx.AsyncClient,
    engine_base_url: str,
    contract: str,
    timeframe: str,
    mirror_dir: Path,
    start: datetime,
    end: datetime,
    api_key: str | None,
    tolerance_price: float,
    tolerance_volume: float,
    sem: asyncio.Semaphore,
) -> dict[str, Any]:
    """Verify one contract+timeframe — read mirror + engine, compare."""
    label: str = f"{contract}:{timeframe}"

    # --- Read mirror Parquet (ground truth) ---
    # tfex mirror stores: data/raw/<contract>/<timeframe>.parquet
    mirror_path: Path = mirror_dir / contract / f"{timeframe}.parquet"
    try:
        expected_pl: pl.DataFrame = _read_mirror_parquet(mirror_path)
    except FileNotFoundError:
        return {
            "symbol": label,
            "status": "no_data",
            "note": f"Mirror Parquet not found: {mirror_path}",
        }
    except Exception as exc:
        logger.error("Failed to read mirror for %s: %s", label, exc)
        return {"symbol": label, "status": "error", "note": str(exc)}

    # --- Read engine ---
    engine_symbol: str = _engine_symbol_for_contract(contract)
    async with sem:
        try:
            bars = await _fetch_engine_bars(
                client, engine_base_url, engine_symbol, timeframe, start, end, api_key
            )
        except httpx.HTTPStatusError as exc:
            logger.error("Engine returned %d for %s: %s", exc.response.status_code, label, exc)
            return {
                "symbol": label,
                "status": "error",
                "note": f"HTTP {exc.response.status_code}: {exc.response.text[:200]}",
            }
        except httpx.HTTPError as exc:
            logger.error("Engine transport error for %s: %s", label, exc)
            return {"symbol": label, "status": "error", "note": f"Transport error: {exc}"}

    actual_pl: pl.DataFrame = _bars_to_polars_frame(bars, start=start, end=end)

    # --- Compare on shared columns ---
    # Convert to pandas for comparison (compare_ohlcv_frames uses pandas)
    import pandas as pd

    expected_pd: pd.DataFrame = expected_pl.select(_SHARED_COLUMNS).to_pandas()
    actual_pd: pd.DataFrame = actual_pl.select(_SHARED_COLUMNS).to_pandas()

    # Set time index for alignment
    if "time" in expected_pd.columns:
        expected_pd = expected_pd.set_index("time")
    if "time" in actual_pd.columns:
        actual_pd = actual_pd.set_index("time")

    # Convert Decimal columns to float for comparison
    for col in ["open", "high", "low", "close", "volume"]:
        if col in expected_pd.columns:
            expected_pd[col] = expected_pd[col].astype(float)
        if col in actual_pd.columns:
            actual_pd[col] = actual_pd[col].astype(float)

    from verification_utils import compare_ohlcv_frames

    result: Any = compare_ohlcv_frames(
        expected_pd,
        actual_pd,
        tolerance_price=tolerance_price,
        tolerance_volume=tolerance_volume,
    )
    mismatch_count: int = len(result.mismatch_details)
    return {
        "symbol": label,
        "status": result.status,
        "expected_bars": len(expected_pd),
        "actual_bars": len(actual_pd),
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
            for m in result.mismatch_details[:50]
        ],
        "note": result.note,
    }


def _discover_contracts(mirror_dir: Path, timeframes: list[str]) -> list[tuple[str, str]]:
    """Discover (contract, timeframe) pairs from the mirror Parquet directory.

    tfex mirror structure: ``data/raw/<contract>/<timeframe>.parquet``
    """
    if not mirror_dir.is_dir():
        raise FileNotFoundError(f"Mirror directory not found: {mirror_dir}")

    pairs: list[tuple[str, str]] = []
    for contract_dir in sorted(mirror_dir.iterdir()):
        if not contract_dir.is_dir():
            continue
        contract: str = contract_dir.name
        for tf in timeframes:
            parquet_path: Path = contract_dir / f"{tf}.parquet"
            if parquet_path.exists():
                pairs.append((contract, tf))
    return pairs


async def main() -> int:
    """Entry point — parse args, discover contracts, run verification, write report."""
    parser = argparse.ArgumentParser(
        description="tfex parity: engine vs mirror Parquet OHLCV comparison"
    )
    add_shared_args(parser)
    parser.add_argument(
        "--mirror-dir",
        type=Path,
        required=True,
        help="Path to tfex data/raw/ directory",
    )
    parser.add_argument(
        "--contracts",
        default="ALL",
        help="Comma-separated contract list, or 'ALL' (default: ALL)",
    )
    parser.add_argument(
        "--timeframes",
        default="5m,1h",
        help="Comma-separated timeframes to verify (default: 5m,1h). "
        "4h is not served by the engine.",
    )
    parser.add_argument(
        "--start",
        type=str,
        required=True,
        help="UTC start datetime (ISO format), e.g. 2025-01-01T00:00:00Z",
    )
    parser.add_argument(
        "--end",
        type=str,
        required=True,
        help="UTC end datetime (ISO format), e.g. 2026-06-01T00:00:00Z",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Max concurrent engine requests (default: 4)",
    )
    args = parser.parse_args()
    setup_logging(args.verbose)

    start_dt: datetime = datetime.fromisoformat(args.start)
    end_dt: datetime = datetime.fromisoformat(args.end)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=UTC)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=UTC)

    start_time: datetime = datetime.now(UTC)

    # --- Validate timeframes ---
    requested_tfs: list[str] = [t.strip() for t in args.timeframes.split(",") if t.strip()]
    valid_tfs: list[str] = []
    skipped_4h: list[dict[str, str]] = []
    for tf in requested_tfs:
        if tf == "4h":
            skipped_4h.append(
                {
                    "symbol": "4h (all contracts)",
                    "reason": "Engine does not serve 4h (cagg_ohlcv_4h unrouted)",
                }
            )
        elif tf in _ENGINE_TIMEFRAMES:
            valid_tfs.append(tf)
        else:
            logger.warning("Unknown timeframe %r — skipping", tf)

    if not valid_tfs:
        logger.error("No valid timeframes to verify (requested: %s)", requested_tfs)
        return 1

    # --- Discover contracts ---
    all_pairs: list[tuple[str, str]] = _discover_contracts(args.mirror_dir, valid_tfs)
    if args.contracts != "ALL":
        requested_contracts: set[str] = {c.strip() for c in args.contracts.split(",") if c.strip()}
        all_pairs = [(c, t) for c, t in all_pairs if c in requested_contracts]

    if not all_pairs:
        logger.error("No contract+timeframe pairs found in %s", args.mirror_dir)
        return 1

    logger.info(
        "Verifying %d contract+timeframe pairs against %s, concurrency=%d",
        len(all_pairs),
        args.engine_base_url,
        args.concurrency,
    )

    # --- Run verification ---
    sem: asyncio.Semaphore = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(timeout=60.0) as client:
        tasks: list[asyncio.Task[dict[str, Any]]] = [
            asyncio.create_task(
                _verify_one_contract(
                    client,
                    args.engine_base_url,
                    contract,
                    timeframe,
                    args.mirror_dir,
                    start_dt,
                    end_dt,
                    args.api_key,
                    args.tolerance_price,
                    args.tolerance_volume,
                    sem,
                )
            )
            for contract, timeframe in all_pairs
        ]
        results: list[dict[str, Any]] = await asyncio.gather(*tasks)

    # --- Build report ---
    symbols_report: dict[str, dict[str, Any]] = {}
    for r in results:
        label: str = r.pop("symbol")
        symbols_report[label] = r

    report: dict[str, Any] = build_report(
        verification="tfex_parity",
        engine_base_url=args.engine_base_url,
        start_time=start_time,
        symbols=symbols_report,
        skipped=skipped_4h,
        tolerance_price=args.tolerance_price,
        tolerance_volume=args.tolerance_volume,
    )
    write_report(report, args.output)

    # --- Summary to stderr ---
    summary: dict[str, Any] = report["summary"]
    logger.info(
        "tfex verification: %d total, %d matched, %d tolerance, "
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
