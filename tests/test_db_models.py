"""Tests for the market_data Pydantic row models."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError
from src.quant_marketdata_engine.db.models import (
    CorporateActionRow,
    OHLCVBarRow,
    UniverseMembershipRow,
)


def _bar(**kw: object) -> OHLCVBarRow:
    base: dict[str, object] = {
        "symbol": "SET:PTT",
        "timeframe": "1d",
        "ts": datetime(2026, 5, 29, tzinfo=UTC),
        "open": Decimal("10"),
        "high": Decimal("11"),
        "low": Decimal("9"),
        "close": Decimal("10.5"),
    }
    base.update(kw)
    return OHLCVBarRow(**base)  # type: ignore[arg-type]


def test_valid_bar_defaults() -> None:
    bar = _bar()
    assert bar.volume == Decimal(0)
    assert bar.open_interest is None
    assert bar.source == "tvkit"


def test_naive_ts_coerced_to_utc() -> None:
    bar = _bar(ts=datetime(2026, 5, 29, 9, 0))
    assert bar.ts.tzinfo == UTC


def test_non_utc_ts_rejected() -> None:
    bkk = timezone(timedelta(hours=7))
    with pytest.raises(ValidationError, match="must be UTC"):
        _bar(ts=datetime(2026, 5, 29, 9, 0, tzinfo=bkk))


def test_high_below_low_rejected() -> None:
    with pytest.raises(ValidationError, match="must be >= low"):
        _bar(high=Decimal("8"), low=Decimal("9"))


def test_bad_timeframe_rejected() -> None:
    with pytest.raises(ValidationError, match="timeframe must be one of"):
        _bar(timeframe="2h")


def test_nonpositive_price_rejected() -> None:
    with pytest.raises(ValidationError):
        _bar(open=Decimal("0"))


def test_ingested_at_validation() -> None:
    bar = _bar(ingested_at=datetime(2026, 5, 30, 1, 2, 3))
    assert bar.ingested_at is not None and bar.ingested_at.tzinfo == UTC


def test_corporate_action_bad_type() -> None:
    with pytest.raises(ValidationError, match="action_type must be one of"):
        CorporateActionRow(symbol="SET:PTT", ex_date=date(2026, 5, 1), action_type="merge")


def test_corporate_action_valid() -> None:
    row = CorporateActionRow(
        symbol="SET:PTT", ex_date=date(2026, 5, 1), action_type="dividend", ratio=Decimal("0.98")
    )
    assert row.action_type == "dividend"


def test_universe_membership_default_index() -> None:
    row = UniverseMembershipRow(as_of=date(2026, 5, 1), symbol="SET:PTT")
    assert row.index_name == "SET"
