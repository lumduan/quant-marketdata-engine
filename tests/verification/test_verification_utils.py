"""Unit tests for verification_utils.py — comparison logic, report generation.

Uses synthetic pandas DataFrames only; no live engine or Parquet needed.
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from tests.verification.verification_utils import (
    ComparisonResult,
    MismatchRecord,
    add_shared_args,
    build_report,
    compare_ohlcv_frames,
    discover_parquet_symbols,
    write_report,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TZ: str = "Asia/Bangkok"

# Pre-built OHLCV row dict for a single date to keep test lines short.
_DT1: str = "2025-01-02T00:00:00+07:00"
_DT2: str = "2025-01-03T00:00:00+07:00"
_DT3: str = "2025-01-04T00:00:00+07:00"

_ROW1: dict[str, float] = {"open": 10.0, "high": 11.0, "low": 9.5, "close": 10.5, "volume": 1000.0}
_ROW2: dict[str, float] = {"open": 10.5, "high": 12.0, "low": 10.0, "close": 11.5, "volume": 2000.0}
_ROW3: dict[str, float] = {"open": 11.0, "high": 13.0, "low": 11.0, "close": 12.5, "volume": 3000.0}

# Slightly perturbed rows for tolerance tests.
_ROW1_TOL: dict[str, float] = {
    "open": 10.005,
    "high": 11.003,
    "low": 9.498,
    "close": 10.502,
    "volume": 1000.0,
}
_ROW1_VOL_TOL: dict[str, float] = {
    "open": 10.0,
    "high": 11.0,
    "low": 9.5,
    "close": 10.5,
    "volume": 1000.5,
}
# Row with price diff > 0.01 (mismatch).
_ROW1_BAD: dict[str, float] = {
    "open": 10.5,
    "high": 11.5,
    "low": 10.0,
    "close": 11.0,
    "volume": 1000.0,
}
# Row with volume diff > 1 (mismatch).
_ROW1_VOL_BAD: dict[str, float] = {
    "open": 10.0,
    "high": 11.0,
    "low": 9.5,
    "close": 10.5,
    "volume": 1100.0,
}
_ROW2_BAD_CLOSE: dict[str, float] = {
    "open": 10.5,
    "high": 12.0,
    "low": 10.0,
    "close": 12.5,
    "volume": 2000.0,
}  # close diff = 1.0


def _frame(
    pairs: list[tuple[str, dict[str, float]]],
    tz: str = _TZ,
) -> pd.DataFrame:
    """Build a canonical csm-style OHLCV DataFrame from (datetime_str, row) pairs."""
    records: list[dict[str, float]] = []
    index_vals: list[datetime] = []
    for dt_str, row_data in pairs:
        ts: datetime = datetime.fromisoformat(dt_str)
        records.append(row_data)
        index_vals.append(ts)
    idx: pd.DatetimeIndex = pd.DatetimeIndex(index_vals, tz=tz, name="datetime")
    return pd.DataFrame.from_records(records, index=idx).sort_index()


def _empty_frame() -> pd.DataFrame:
    """Return an empty canonical OHLCV DataFrame."""
    return pd.DataFrame(
        columns=["open", "high", "low", "close", "volume"],
        index=pd.DatetimeIndex([], tz=_TZ, name="datetime"),
    )


# ---------------------------------------------------------------------------
# compare_ohlcv_frames tests
# ---------------------------------------------------------------------------


class TestCompareExactMatch:
    """Identical frames should report 'match'."""

    def test_identical_frames(self) -> None:
        df: pd.DataFrame = _frame([(_DT1, _ROW1), (_DT2, _ROW2)])
        result: ComparisonResult = compare_ohlcv_frames(df, df.copy())
        assert result.status == "match"
        assert result.max_price_diff == 0.0
        assert result.max_volume_diff == 0.0
        assert len(result.mismatch_details) == 0
        assert result.missing_in_expected == 0
        assert result.missing_in_actual == 0

    def test_single_row(self) -> None:
        df: pd.DataFrame = _frame([(_DT1, _ROW1)])
        result: ComparisonResult = compare_ohlcv_frames(df, df.copy())
        assert result.status == "match"

    def test_both_empty(self) -> None:
        empty: pd.DataFrame = _empty_frame()
        result: ComparisonResult = compare_ohlcv_frames(empty, empty.copy())
        assert result.status == "match"
        assert result.note == "both frames empty"


class TestCompareToleranceMatch:
    """Frames with diffs within tolerance should report 'tolerance_match'."""

    def test_price_within_tolerance(self) -> None:
        expected: pd.DataFrame = _frame([(_DT1, _ROW1)])
        actual: pd.DataFrame = _frame([(_DT1, _ROW1_TOL)])
        result: ComparisonResult = compare_ohlcv_frames(
            expected,
            actual,
            tolerance_price=0.01,
            tolerance_volume=1.0,
        )
        assert result.status == "tolerance_match"
        assert 0 < result.max_price_diff <= 0.01
        assert result.max_volume_diff == 0.0
        assert len(result.mismatch_details) == 0

    def test_volume_within_tolerance(self) -> None:
        expected: pd.DataFrame = _frame([(_DT1, _ROW1)])
        actual: pd.DataFrame = _frame([(_DT1, _ROW1_VOL_TOL)])
        result: ComparisonResult = compare_ohlcv_frames(
            expected,
            actual,
            tolerance_volume=1.0,
        )
        assert result.status == "tolerance_match"
        assert result.max_volume_diff == 0.5

    def test_missing_rows_same_data(self) -> None:
        """Extra rows on one side but overlapping rows match → tolerance_match."""
        expected: pd.DataFrame = _frame([(_DT1, _ROW1)])
        actual: pd.DataFrame = _frame([(_DT1, _ROW1), (_DT2, _ROW2)])
        result: ComparisonResult = compare_ohlcv_frames(expected, actual)
        assert result.status == "tolerance_match"
        assert result.missing_in_expected == 1
        assert result.missing_in_actual == 0


class TestCompareMismatch:
    """Frames with diffs exceeding tolerance should report 'mismatch'."""

    def test_price_outside_tolerance(self) -> None:
        expected: pd.DataFrame = _frame([(_DT1, _ROW1)])
        actual: pd.DataFrame = _frame([(_DT1, _ROW1_BAD)])
        result: ComparisonResult = compare_ohlcv_frames(
            expected,
            actual,
            tolerance_price=0.01,
        )
        assert result.status == "mismatch"
        assert result.max_price_diff > 0.01
        assert len(result.mismatch_details) > 0

    def test_volume_outside_tolerance(self) -> None:
        expected: pd.DataFrame = _frame([(_DT1, _ROW1)])
        actual: pd.DataFrame = _frame([(_DT1, _ROW1_VOL_BAD)])
        result: ComparisonResult = compare_ohlcv_frames(
            expected,
            actual,
            tolerance_volume=1.0,
        )
        assert result.status == "mismatch"
        assert result.max_volume_diff > 1.0
        assert len(result.mismatch_details) > 0
        detail: MismatchRecord = result.mismatch_details[0]
        assert detail.column == "volume"

    def test_no_overlapping_timestamps(self) -> None:
        expected: pd.DataFrame = _frame([(_DT1, _ROW1)])
        actual: pd.DataFrame = _frame([(_DT2, _ROW2)])
        result: ComparisonResult = compare_ohlcv_frames(expected, actual)
        assert result.status == "mismatch"
        assert result.note == "no overlapping timestamps"
        assert result.missing_in_expected == 1
        assert result.missing_in_actual == 1


class TestCompareEmpty:
    """Edge cases where one side has no data."""

    def test_expected_empty(self) -> None:
        empty: pd.DataFrame = _empty_frame()
        actual: pd.DataFrame = _frame([(_DT1, _ROW1)])
        result: ComparisonResult = compare_ohlcv_frames(empty, actual)
        assert result.status == "no_data"
        assert result.note == "expected frame is empty"

    def test_actual_empty(self) -> None:
        expected: pd.DataFrame = _frame([(_DT1, _ROW1)])
        empty: pd.DataFrame = _empty_frame()
        result: ComparisonResult = compare_ohlcv_frames(expected, empty)
        assert result.status == "no_data"
        assert result.note == "actual (engine) frame is empty"


class TestCompareMultipleRows:
    """Multi-row scenarios with mixed outcomes."""

    def test_mixed_match_and_mismatch(self) -> None:
        expected: pd.DataFrame = _frame([(_DT1, _ROW1), (_DT2, _ROW2), (_DT3, _ROW3)])
        actual: pd.DataFrame = _frame(
            [(_DT1, _ROW1), (_DT2, _ROW2_BAD_CLOSE), (_DT3, _ROW3)],
        )
        result: ComparisonResult = compare_ohlcv_frames(
            expected,
            actual,
            tolerance_price=0.01,
        )
        assert result.status == "mismatch"
        assert result.max_price_diff == 1.0
        assert len(result.mismatch_details) == 1
        assert result.mismatch_details[0].timestamp == "2025-01-03 00:00:00+07:00"
        assert result.mismatch_details[0].column == "close"


# ---------------------------------------------------------------------------
# Report generation tests
# ---------------------------------------------------------------------------


class TestBuildReport:
    """build_report should produce a well-formed JSON-serialisable dict."""

    def test_all_match(self) -> None:
        symbols: dict[str, dict[str, Any]] = {
            "SET:PTT": {"status": "match", "expected_bars": 100, "actual_bars": 100},
            "SET:AOT": {"status": "match", "expected_bars": 100, "actual_bars": 100},
        }
        report: dict[str, Any] = build_report(
            verification="test_parity",
            engine_base_url="http://localhost:8300",
            start_time=datetime(2025, 1, 1, tzinfo=UTC),
            symbols=symbols,
            skipped=[],
            tolerance_price=0.01,
            tolerance_volume=1.0,
        )
        assert report["verification"] == "test_parity"
        assert report["summary"]["total_symbols"] == 2
        assert report["summary"]["matched_exactly"] == 2
        assert report["summary"]["overall_parity"] is True

    def test_mixed_results(self) -> None:
        symbols: dict[str, dict[str, Any]] = {
            "SET:PTT": {"status": "match", "expected_bars": 100, "actual_bars": 100},
            "SET:ABC": {
                "status": "mismatch",
                "expected_bars": 100,
                "actual_bars": 100,
                "max_price_diff": 0.5,
            },
            "SET:XYZ": {"status": "no_data", "note": "not found in engine"},
        }
        report: dict[str, Any] = build_report(
            verification="test_parity",
            engine_base_url="http://localhost:8300",
            start_time=datetime(2025, 1, 1, tzinfo=UTC),
            symbols=symbols,
            skipped=[],
            tolerance_price=0.01,
            tolerance_volume=1.0,
        )
        assert report["summary"]["total_symbols"] == 3
        assert report["summary"]["matched_exactly"] == 1
        assert report["summary"]["mismatched"] == 1
        assert report["summary"]["missing_data"] == 1
        assert report["summary"]["overall_parity"] is False

    def test_with_skipped(self) -> None:
        symbols: dict[str, dict[str, Any]] = {
            "SET:PTT": {"status": "match", "expected_bars": 100, "actual_bars": 100},
        }
        skipped: list[dict[str, str]] = [
            {"symbol": "SET:SET", "reason": "Known deferred (Phase 3)"},
        ]
        report: dict[str, Any] = build_report(
            verification="test_parity",
            engine_base_url="http://localhost:8300",
            start_time=datetime(2025, 1, 1, tzinfo=UTC),
            symbols=symbols,
            skipped=skipped,
            tolerance_price=0.01,
            tolerance_volume=1.0,
        )
        assert report["summary"]["skipped"] == 1
        assert report["skipped"] == skipped

    def test_output_is_json_serialisable(self) -> None:
        symbols: dict[str, dict[str, Any]] = {
            "SET:PTT": {"status": "match", "expected_bars": 100, "actual_bars": 100},
        }
        report: dict[str, Any] = build_report(
            verification="test_parity",
            engine_base_url="http://localhost:8300",
            start_time=datetime(2025, 1, 1, tzinfo=UTC),
            symbols=symbols,
            skipped=[],
            tolerance_price=0.01,
            tolerance_volume=1.0,
        )
        # Should not raise
        json.dumps(report, default=str)


class TestWriteReport:
    """write_report should write a JSON file to disk."""

    def test_writes_file(self) -> None:
        report: dict[str, Any] = {
            "verification": "test",
            "summary": {"overall_parity": True},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path: Path = Path(tmpdir) / "report.json"
            write_report(report, out_path)
            assert out_path.exists()
            loaded: dict[str, Any] = json.loads(out_path.read_text())
            assert loaded["verification"] == "test"


# ---------------------------------------------------------------------------
# CLI helpers tests
# ---------------------------------------------------------------------------


class TestSharedArgs:
    """add_shared_args should register the expected flags."""

    def test_shared_args_registered(self) -> None:
        import argparse

        parser: argparse.ArgumentParser = argparse.ArgumentParser()
        add_shared_args(parser)
        ns: argparse.Namespace = parser.parse_args(["--output", "/tmp/report.json"])
        assert ns.engine_base_url == "http://localhost:8300"
        assert ns.api_key is None
        assert ns.tolerance_price == 0.01
        assert ns.tolerance_volume == 1.0
        assert ns.output == Path("/tmp/report.json")
        assert ns.verbose is False


# ---------------------------------------------------------------------------
# Symbol discovery tests
# ---------------------------------------------------------------------------


class TestDiscoverParquetSymbols:
    """discover_parquet_symbols should decode URL-encoded filenames."""

    def test_decodes_symbols(self, tmp_path: Path) -> None:
        """Create dummy Parquet files with URL-encoded names."""
        pd.DataFrame({"open": [1.0]}).to_parquet(tmp_path / "SET%3APTT.parquet")
        pd.DataFrame({"open": [2.0]}).to_parquet(tmp_path / "SET%3AAOT.parquet")
        (tmp_path / "README.txt").write_text("ignored")

        symbols: list[str] = discover_parquet_symbols(tmp_path)
        assert symbols == ["SET:AOT", "SET:PTT"]  # sorted

    def test_empty_directory(self, tmp_path: Path) -> None:
        symbols: list[str] = discover_parquet_symbols(tmp_path)
        assert symbols == []

    def test_missing_directory(self) -> None:
        with pytest.raises(FileNotFoundError):
            discover_parquet_symbols(Path("/nonexistent/path"))
