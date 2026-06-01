"""Tests for the DB → Parquet snapshot exporter (round-trip)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest
from src.quant_marketdata_engine.db.models import OHLCVBarRow
from src.quant_marketdata_engine.snapshot import exporter


def _bar(oi: Decimal | None = None) -> OHLCVBarRow:
    return OHLCVBarRow(
        symbol="S501!",
        timeframe="5m",
        ts=datetime(2026, 5, 29, 7, 0, tzinfo=UTC),
        open=Decimal("912.400000"),
        high=Decimal("913.100000"),
        low=Decimal("912.000000"),
        close=Decimal("912.800000"),
        volume=Decimal("1210.0000"),
        open_interest=oi,
    )


def test_bars_to_table_preserves_decimal() -> None:
    table = exporter.bars_to_table([_bar(Decimal("412330"))])
    col = table.column("open").to_pylist()
    assert col == [Decimal("912.400000")]
    assert table.column("open_interest").to_pylist() == [Decimal("412330.0000")]


async def test_export_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_fetch(_pool: Any, **kw: Any) -> list[OHLCVBarRow]:
        return [_bar(), _bar()]

    monkeypatch.setattr(exporter, "fetch_ohlcv", _fake_fetch)
    out = tmp_path / "nested" / "snap.parquet"
    n = await exporter.export_ohlcv(object(), symbol="S501!", timeframe="5m", out_path=out)  # type: ignore[arg-type]
    assert n == 2
    assert out.exists()
    table = pq.read_table(out)  # type: ignore[no-untyped-call]
    assert table.num_rows == 2
    assert table.column("close").to_pylist()[0] == Decimal("912.800000")


async def test_export_adjusted_uses_view(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, bool] = {"adjusted": False}

    async def _fake_adj(_pool: Any, **kw: Any) -> list[OHLCVBarRow]:
        called["adjusted"] = True
        return [_bar()]

    monkeypatch.setattr(exporter, "fetch_ohlcv_adjusted", _fake_adj)
    out = tmp_path / "adj.parquet"
    n = await exporter.export_ohlcv(
        object(),
        symbol="S501!",
        timeframe="5m",
        out_path=out,
        adjusted=True,  # type: ignore[arg-type]
    )
    assert n == 1 and called["adjusted"] is True
