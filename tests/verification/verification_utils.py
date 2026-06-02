"""Shared utilities for Phase 5 verification scripts.

Provides:
- :class:`ComparisonResult` — structured outcome of a single symbol/contract comparison
- :func:`compare_ohlcv_frames` — tolerance-aware DataFrame diffing
- :func:`build_report` / :func:`write_report` — JSON report generation
- CLI argument helpers for shared flags

The module is independent of the engine's src/ tree so verification scripts can
run with minimal dependencies (httpx + pandas/polars + pyarrow).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd

logger: logging.Logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

Status = Literal["match", "tolerance_match", "mismatch", "no_data", "error"]


@dataclass
class MismatchRecord:
    """One row-column mismatch between expected and actual."""

    timestamp: str
    column: str
    expected_value: float
    actual_value: float
    absolute_diff: float


@dataclass
class ComparisonResult:
    """Structured outcome of comparing two OHLCV DataFrames."""

    status: Status
    max_price_diff: float = 0.0
    max_volume_diff: float = 0.0
    mismatch_details: list[MismatchRecord] = field(default_factory=list)
    missing_in_expected: int = 0
    missing_in_actual: int = 0
    note: str | None = None


# ---------------------------------------------------------------------------
# Core comparison
# ---------------------------------------------------------------------------

DEFAULT_PRICE_COLS: tuple[str, ...] = ("open", "high", "low", "close")
DEFAULT_VOLUME_COL: str = "volume"


def compare_ohlcv_frames(
    expected: pd.DataFrame,
    actual: pd.DataFrame,
    *,
    price_cols: tuple[str, ...] = DEFAULT_PRICE_COLS,
    volume_col: str = DEFAULT_VOLUME_COL,
    tolerance_price: float = 0.01,
    tolerance_volume: float = 1.0,
) -> ComparisonResult:
    """Compare two OHLCV DataFrames with column-group tolerances.

    Args:
        expected: Reference DataFrame (legacy / Parquet path).
        actual: Candidate DataFrame (engine path).
        price_cols: Columns subject to ``tolerance_price``.
        volume_col: Column subject to ``tolerance_volume``.
        tolerance_price: Absolute tolerance for price columns.
        tolerance_volume: Absolute tolerance for the volume column.

    Returns:
        A :class:`ComparisonResult` with status and mismatch detail.
    """
    # --- Empty-data guard ---
    if expected.empty and actual.empty:
        return ComparisonResult(status="match", note="both frames empty")
    if expected.empty:
        return ComparisonResult(status="no_data", note="expected frame is empty")
    if actual.empty:
        return ComparisonResult(status="no_data", note="actual (engine) frame is empty")

    # --- Align on timestamp index ---
    common_idx: pd.DatetimeIndex = expected.index.intersection(actual.index)  # type: ignore[assignment]
    missing_in_expected = len(actual.index.difference(expected.index))  # type: ignore[arg-type]
    missing_in_actual = len(expected.index.difference(actual.index))  # type: ignore[arg-type]

    if len(common_idx) == 0:
        return ComparisonResult(
            status="mismatch",
            missing_in_expected=missing_in_expected,
            missing_in_actual=missing_in_actual,
            note="no overlapping timestamps",
        )

    exp_aligned: pd.DataFrame = expected.loc[common_idx]
    act_aligned: pd.DataFrame = actual.loc[common_idx]

    # --- Per-column diff ---
    max_price_diff: float = 0.0
    max_volume_diff: float = 0.0
    mismatches: list[MismatchRecord] = []

    for col in price_cols:
        if col not in exp_aligned.columns or col not in act_aligned.columns:
            continue
        diff: pd.Series = (exp_aligned[col] - act_aligned[col]).abs()  # type: ignore[operator]
        col_max: float = float(diff.max())
        if col_max > max_price_diff:
            max_price_diff = col_max
        over: pd.Series = diff[diff > tolerance_price]
        for ts_idx, abs_diff in over.items():  # type: ignore[assignment]
            mismatches.append(
                MismatchRecord(
                    timestamp=str(ts_idx),
                    column=col,
                    expected_value=float(exp_aligned.loc[ts_idx, col]),  # type: ignore[arg-type]
                    actual_value=float(act_aligned.loc[ts_idx, col]),  # type: ignore[arg-type]
                    absolute_diff=float(abs_diff),
                )
            )

    if volume_col in exp_aligned.columns and volume_col in act_aligned.columns:
        vol_diff: pd.Series = (exp_aligned[volume_col] - act_aligned[volume_col]).abs()  # type: ignore[operator]
        col_max_vol: float = float(vol_diff.max())
        if col_max_vol > max_volume_diff:
            max_volume_diff = col_max_vol
        over_vol: pd.Series = vol_diff[vol_diff > tolerance_volume]
        for ts_idx, abs_diff in over_vol.items():  # type: ignore[assignment]
            mismatches.append(
                MismatchRecord(
                    timestamp=str(ts_idx),
                    column=volume_col,
                    expected_value=float(exp_aligned.loc[ts_idx, volume_col]),  # type: ignore[arg-type]
                    actual_value=float(act_aligned.loc[ts_idx, volume_col]),  # type: ignore[arg-type]
                    absolute_diff=float(abs_diff),
                )
            )

    # --- Determine status ---
    if mismatches:
        return ComparisonResult(
            status="mismatch",
            max_price_diff=max_price_diff,
            max_volume_diff=max_volume_diff,
            mismatch_details=mismatches,
            missing_in_expected=missing_in_expected,
            missing_in_actual=missing_in_actual,
        )
    if max_price_diff > 0 or max_volume_diff > 0:
        return ComparisonResult(
            status="tolerance_match",
            max_price_diff=max_price_diff,
            max_volume_diff=max_volume_diff,
            missing_in_expected=missing_in_expected,
            missing_in_actual=missing_in_actual,
        )
    if missing_in_expected > 0 or missing_in_actual > 0:
        return ComparisonResult(
            status="tolerance_match",
            max_price_diff=0.0,
            max_volume_diff=0.0,
            missing_in_expected=missing_in_expected,
            missing_in_actual=missing_in_actual,
            note="rows differ in count but all overlapping rows match exactly",
        )
    return ComparisonResult(status="match")


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def build_report(
    *,
    verification: str,
    engine_base_url: str,
    start_time: datetime,
    symbols: dict[str, dict[str, Any]],
    skipped: list[dict[str, str]],
    tolerance_price: float,
    tolerance_volume: float,
) -> dict[str, Any]:
    """Build a JSON-serialisable verification report.

    Args:
        verification: Report name (e.g. ``"csm_parity"``).
        engine_base_url: Engine URL used.
        start_time: When the verification run started.
        symbols: Per-symbol result dicts keyed by symbol name.
        skipped: List of ``{"symbol": ..., "reason": ...}`` dicts.
        tolerance_price: Price tolerance used.
        tolerance_volume: Volume tolerance used.

    Returns:
        Report dict ready for JSON serialisation.
    """
    total = len(symbols)
    matched = sum(1 for s in symbols.values() if s.get("status") == "match")
    tolerance = sum(1 for s in symbols.values() if s.get("status") == "tolerance_match")
    mismatched = sum(1 for s in symbols.values() if s.get("status") == "mismatch")
    missing = sum(1 for s in symbols.values() if s.get("status") == "no_data")
    errors = sum(1 for s in symbols.values() if s.get("status") == "error")
    overall = mismatched == 0 and missing == 0 and errors == 0

    return {
        "verification": verification,
        "timestamp": datetime.now(UTC).isoformat(),
        "start_time": start_time.isoformat(),
        "engine_base_url": engine_base_url,
        "tolerances": {
            "price": tolerance_price,
            "volume": tolerance_volume,
        },
        "summary": {
            "total_symbols": total,
            "matched_exactly": matched,
            "matched_with_tolerance": tolerance,
            "mismatched": mismatched,
            "missing_data": missing,
            "errors": errors,
            "skipped": len(skipped),
            "overall_parity": overall,
        },
        "symbols": symbols,
        "skipped": skipped,
    }


def write_report(report: dict[str, Any], path: Path) -> None:
    """Write a verification report as JSON to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str, ensure_ascii=False)
    logger.info("Verification report written to %s", path)


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def add_shared_args(parser: argparse.ArgumentParser) -> None:
    """Register CLI flags shared by all verification scripts."""
    parser.add_argument(
        "--engine-base-url",
        default="http://localhost:8300",
        help="Market Data Engine base URL (default: http://localhost:8300)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Optional X-API-Key for the engine read API",
    )
    parser.add_argument(
        "--tolerance-price",
        type=float,
        default=0.01,
        help="Absolute tolerance for price columns (default: 0.01)",
    )
    parser.add_argument(
        "--tolerance-volume",
        type=float,
        default=1.0,
        help="Absolute tolerance for volume column (default: 1.0)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path for the JSON verification report",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging",
    )


def setup_logging(verbose: bool) -> None:
    """Configure root logger for verification scripts."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


# ---------------------------------------------------------------------------
# Symbol discovery helpers
# ---------------------------------------------------------------------------


def discover_parquet_symbols(parquet_dir: Path) -> list[str]:
    """Discover symbol names from csm-set Parquet filenames.

    csm-set stores files as ``SET%3APTT.parquet`` where the stem is a
    URL-encoded symbol string.

    Args:
        parquet_dir: Path to csm-set's ``data/raw/dividends/`` directory.

    Returns:
        Sorted list of decoded symbol names.
    """
    from urllib.parse import unquote

    if not parquet_dir.is_dir():
        raise FileNotFoundError(f"Parquet directory not found: {parquet_dir}")

    symbols: list[str] = []
    for entry in sorted(parquet_dir.iterdir()):
        if entry.suffix != ".parquet":
            continue
        symbols.append(unquote(entry.stem))
    return symbols


__all__: list[str] = [
    "ComparisonResult",
    "MismatchRecord",
    "Status",
    "add_shared_args",
    "build_report",
    "compare_ohlcv_frames",
    "discover_parquet_symbols",
    "setup_logging",
    "write_report",
]
