"""Tests for the market_data repository helpers (fake asyncpg pool)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from src.quant_marketdata_engine.db import repositories as repo
from src.quant_marketdata_engine.db.errors import RepositoryError
from src.quant_marketdata_engine.db.models import (
    CorporateActionRow,
    OHLCVBarRow,
    UniverseMembershipRow,
)

from tests._fakes import FakeConn, FakePool, make_bar_record


def _bar() -> OHLCVBarRow:
    return OHLCVBarRow(
        symbol="SET:PTT",
        timeframe="1d",
        ts=datetime(2026, 5, 29, tzinfo=UTC),
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10.5"),
    )


async def test_upsert_ohlcv_empty_returns_zero() -> None:
    pool = FakePool(FakeConn())
    assert await repo.upsert_ohlcv(pool, []) == 0  # type: ignore[arg-type]


async def test_upsert_ohlcv_writes_batch() -> None:
    conn = FakeConn()
    pool = FakePool(conn)
    n = await repo.upsert_ohlcv(pool, [_bar(), _bar()])  # type: ignore[arg-type]
    assert n == 2
    assert conn.calls[0][0] == "executemany"
    assert "ON CONFLICT (symbol, timeframe, ts)" in conn.calls[0][1]


async def test_upsert_ohlcv_error_wrapped() -> None:
    pool = FakePool(FakeConn(raise_on={"executemany"}))
    with pytest.raises(RepositoryError, match="upsert_ohlcv failed"):
        await repo.upsert_ohlcv(pool, [_bar()])  # type: ignore[arg-type]


async def test_fetch_ohlcv_maps_rows_and_builds_range_sql() -> None:
    conn = FakeConn(fetch_result=[make_bar_record()])
    pool = FakePool(conn)
    rows = await repo.fetch_ohlcv(
        pool,  # type: ignore[arg-type]
        symbol="SET:PTT",
        timeframe="1d",
        start=datetime(2026, 1, 1, tzinfo=UTC),
        end=datetime(2026, 6, 1, tzinfo=UTC),
        limit=10,
    )
    assert len(rows) == 1 and rows[0].symbol == "SET:PTT"
    sql = conn.calls[0][1]
    assert "FROM market_data.ohlcv " in sql
    assert "ts >= $3" in sql and "ts <= $4" in sql


async def test_fetch_ohlcv_no_range() -> None:
    conn = FakeConn(fetch_result=[])
    pool = FakePool(conn)
    rows = await repo.fetch_ohlcv(pool, symbol="X", timeframe="5m")  # type: ignore[arg-type]
    assert rows == []
    assert "ts >=" not in conn.calls[0][1]


async def test_fetch_ohlcv_error_wrapped() -> None:
    pool = FakePool(FakeConn(raise_on={"fetch"}))
    with pytest.raises(RepositoryError, match="fetch from market_data.ohlcv failed"):
        await repo.fetch_ohlcv(pool, symbol="X", timeframe="1d")  # type: ignore[arg-type]


async def test_fetch_ohlcv_adjusted_uses_view() -> None:
    conn = FakeConn(fetch_result=[make_bar_record()])
    pool = FakePool(conn)
    await repo.fetch_ohlcv_adjusted(pool, symbol="X", timeframe="1d")  # type: ignore[arg-type]
    assert "FROM market_data.ohlcv_adjusted " in conn.calls[0][1]


async def test_upsert_corporate_actions() -> None:
    conn = FakeConn()
    pool = FakePool(conn)
    rows = [CorporateActionRow(symbol="X", ex_date=date(2026, 5, 1), action_type="dividend")]
    assert await repo.upsert_corporate_actions(pool, rows) == 1  # type: ignore[arg-type]
    assert await repo.upsert_corporate_actions(pool, []) == 0  # type: ignore[arg-type]


async def test_upsert_corporate_actions_error() -> None:
    pool = FakePool(FakeConn(raise_on={"executemany"}))
    rows = [CorporateActionRow(symbol="X", ex_date=date(2026, 5, 1), action_type="roll")]
    with pytest.raises(RepositoryError, match="upsert_corporate_actions failed"):
        await repo.upsert_corporate_actions(pool, rows)  # type: ignore[arg-type]


async def test_upsert_universe_membership() -> None:
    conn = FakeConn()
    pool = FakePool(conn)
    rows = [UniverseMembershipRow(as_of=date(2026, 5, 1), symbol="X")]
    assert await repo.upsert_universe_membership(pool, rows) == 1  # type: ignore[arg-type]
    assert await repo.upsert_universe_membership(pool, []) == 0  # type: ignore[arg-type]


async def test_upsert_universe_membership_error() -> None:
    pool = FakePool(FakeConn(raise_on={"executemany"}))
    rows = [UniverseMembershipRow(as_of=date(2026, 5, 1), symbol="X")]
    with pytest.raises(RepositoryError, match="upsert_universe_membership failed"):
        await repo.upsert_universe_membership(pool, rows)  # type: ignore[arg-type]


async def test_fetch_universe_resolves_and_lists() -> None:
    conn = FakeConn(
        fetchval_result=date(2026, 4, 30),
        fetch_result=[{"symbol": "SET:AOT"}, {"symbol": "SET:PTT"}],
    )
    pool = FakePool(conn)
    resolved, symbols = await repo.fetch_universe(
        pool,
        as_of=date(2026, 5, 15),
        index_name="SET",  # type: ignore[arg-type]
    )
    assert resolved == date(2026, 4, 30)
    assert symbols == ["SET:AOT", "SET:PTT"]


async def test_fetch_universe_empty() -> None:
    pool = FakePool(FakeConn(fetchval_result=None))
    resolved, symbols = await repo.fetch_universe(pool, as_of=date(2026, 5, 1))  # type: ignore[arg-type]
    assert resolved is None and symbols == []


async def test_fetch_universe_error() -> None:
    pool = FakePool(FakeConn(raise_on={"fetchval"}))
    with pytest.raises(RepositoryError, match="fetch_universe failed"):
        await repo.fetch_universe(pool, as_of=date(2026, 5, 1))  # type: ignore[arg-type]
