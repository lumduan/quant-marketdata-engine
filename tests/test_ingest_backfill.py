"""Tests for the best-effort csm-set parquet backfill."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from src.quant_marketdata_engine.ingest import backfill

_BKK = ZoneInfo("Asia/Bangkok")


def _write_fixture(dir_: Path) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    dts = [
        datetime(2026, 5, 29, 9, 0, tzinfo=_BKK),  # valid
        datetime(2026, 5, 30, 9, 0, tzinfo=_BKK),  # valid
        datetime(2026, 5, 31, 9, 0, tzinfo=_BKK),  # open <= 0 → skipped
        None,  # missing datetime → skipped
        datetime(2026, 6, 2, 9, 0, tzinfo=_BKK),  # NaN price → skipped via except
    ]
    table = pa.table(
        {
            "open": [10.0, 11.0, 0.0, 12.0, float("nan")],
            "high": [11.0, 12.0, 1.0, 13.0, 13.0],
            "low": [9.0, 10.0, 0.5, 11.0, 11.0],
            "close": [10.5, 11.5, 0.8, 12.5, 12.5],
            "volume": [100.0, 200.0, 300.0, 400.0, 500.0],
            "datetime": pa.array(dts, type=pa.timestamp("ms", tz="Asia/Bangkok")),
        }
    )
    # URL-encoded colon in the filename → symbol "SET:PTT".
    pq.write_table(table, dir_ / "SET%3APTT.parquet")  # type: ignore[no-untyped-call]


async def test_backfill_absent_dir_returns_zero(tmp_path: Path) -> None:
    n = await backfill.backfill_from_dir(object(), tmp_path / "missing")  # type: ignore[arg-type]
    assert n == 0


async def test_backfill_imports_valid_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[Any] = []

    async def _fake_upsert(_pool: Any, rows: Any) -> int:
        captured.extend(rows)
        return len(rows)

    monkeypatch.setattr(backfill, "upsert_ohlcv", _fake_upsert)
    src = tmp_path / "dividends"
    _write_fixture(src)

    total = await backfill.backfill_from_dir(object(), src)  # type: ignore[arg-type]
    assert total == 2  # 3 of 5 rows skipped (nonpositive / missing-dt / NaN)
    assert {b.symbol for b in captured} == {"SET:PTT"}
    assert all(b.source == "csm-backfill-div" for b in captured)
    # tz-aware Asia/Bangkok bar-open converted to UTC (09:00 BKK → 02:00 UTC).
    assert captured[0].ts.hour == 2


async def test_backfill_limit_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_upsert(_pool: Any, rows: Any) -> int:
        return len(rows)

    monkeypatch.setattr(backfill, "upsert_ohlcv", _fake_upsert)
    src = tmp_path / "d"
    _write_fixture(src)
    # limit_files=0 → no files processed.
    assert await backfill.backfill_from_dir(object(), src, limit_files=0) == 0  # type: ignore[arg-type]


async def test_backfill_skips_unreadable_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_upsert(_pool: Any, rows: Any) -> int:
        return len(rows)

    monkeypatch.setattr(backfill, "upsert_ohlcv", _fake_upsert)
    src = tmp_path / "bad"
    src.mkdir()
    (src / "SET%3AX.parquet").write_text("not a parquet file")
    assert await backfill.backfill_from_dir(object(), src) == 0  # type: ignore[arg-type]
