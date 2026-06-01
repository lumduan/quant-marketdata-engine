"""Pydantic V2 row models for the shared ``market_data`` store.

These map 1:1 to rows in ``db_market_data`` (Phase-1 schema in ``quant-infra-db``):
``market_data.ohlcv`` / ``.ohlcv_adjusted`` (view), ``.corporate_actions``,
``.universe_membership``. They intentionally mirror
``quant-infra-db/src/db/models.py`` — each service owns its own connectivity code
(``quant-infra-db`` is not an importable package).

OHLC prices are ``Decimal`` (DB ``numeric(18,6)``); ``volume``/``open_interest``
are ``Decimal`` (``numeric(20,4)``). ``open_interest`` is futures-only (``None``
for equities). ``ts`` is the **bar-open** time in UTC; for futures ``1d`` the
close is the settlement price (never a rollup of intraday).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ALLOWED_TIMEFRAMES: frozenset[str] = frozenset({"1d", "1h", "5m"})
ALLOWED_ACTION_TYPES: frozenset[str] = frozenset({"split", "dividend", "roll"})


def _ensure_utc(value: datetime) -> datetime:
    """Coerce naive datetimes to UTC; reject non-UTC tz-aware datetimes."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ValueError("datetime must be UTC")
    return value


class OHLCVBarRow(BaseModel):
    """One raw bar in ``market_data.ohlcv`` (Option A multi-timeframe model)."""

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(min_length=1, description="Instrument symbol (e.g. SET:PTT, S501!).")
    timeframe: str = Field(description="Bar timeframe: 1d, 1h, or 5m.")
    ts: datetime = Field(description="Bar-open timestamp (UTC).")
    open: Decimal = Field(gt=0, description="Open price.")
    high: Decimal = Field(gt=0, description="High price.")
    low: Decimal = Field(gt=0, description="Low price.")
    close: Decimal = Field(gt=0, description="Close price (settlement for futures 1d).")
    volume: Decimal = Field(default=Decimal(0), ge=0, description="Bar volume.")
    open_interest: Decimal | None = Field(
        default=None, ge=0, description="Open interest (futures only; None for equities)."
    )
    source: str = Field(default="tvkit", min_length=1, description="Provenance.")
    ingested_at: datetime | None = Field(
        default=None, description="Upsert audit time (UTC); DB-defaulted when None."
    )

    @field_validator("ts")
    @classmethod
    def _validate_ts(cls, value: datetime) -> datetime:
        return _ensure_utc(value)

    @field_validator("ingested_at")
    @classmethod
    def _validate_ingested_at(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _ensure_utc(value)

    @field_validator("timeframe")
    @classmethod
    def _validate_timeframe(cls, value: str) -> str:
        if value not in ALLOWED_TIMEFRAMES:
            raise ValueError(
                f"timeframe must be one of {sorted(ALLOWED_TIMEFRAMES)}, got {value!r}"
            )
        return value

    @model_validator(mode="after")
    def _validate_high_ge_low(self) -> OHLCVBarRow:
        if self.high < self.low:
            raise ValueError(f"high ({self.high}) must be >= low ({self.low})")
        return self


class CorporateActionRow(BaseModel):
    """One row of ``market_data.corporate_actions`` (splits/dividends + futures rolls)."""

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(min_length=1)
    ex_date: date = Field(description="Ex-date (the action applies from this date).")
    action_type: str = Field(description="One of split, dividend, roll.")
    ratio: Decimal | None = Field(
        default=None, gt=0, description="Price back-adjustment multiplier for prior bars."
    )
    amount: Decimal | None = Field(default=None, description="Raw event magnitude (audit).")
    note: str | None = Field(default=None)

    @field_validator("action_type")
    @classmethod
    def _validate_action_type(cls, value: str) -> str:
        if value not in ALLOWED_ACTION_TYPES:
            raise ValueError(
                f"action_type must be one of {sorted(ALLOWED_ACTION_TYPES)}, got {value!r}"
            )
        return value


class UniverseMembershipRow(BaseModel):
    """One row of ``market_data.universe_membership`` — as-of dated, point-in-time."""

    model_config = ConfigDict(frozen=True)

    as_of: date = Field(description="As-of date of the constituent snapshot.")
    symbol: str = Field(min_length=1)
    index_name: str = Field(default="SET", min_length=1, description="Index (e.g. SET, SET50).")
