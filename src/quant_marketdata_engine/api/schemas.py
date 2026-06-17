"""Read-API request/response models (ADR §5 read contract).

All monetary/numeric fields are ``Decimal`` serialised **as strings** on the wire
(never float); ``ts`` is the bar-open time in UTC. Edge clients display
Asia/Bangkok.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, PlainSerializer

Timeframe = Literal["1d", "1h", "5m"]

# Serialise Decimal as a plain decimal string in JSON output (preserve precision).
DecimalStr = Annotated[
    Decimal,
    PlainSerializer(lambda v: format(v, "f"), return_type=str, when_used="json"),
]


class OHLCVBar(BaseModel):
    """One bar in a read response."""

    ts: datetime = Field(description="Bar-open timestamp (UTC).")
    open: DecimalStr
    high: DecimalStr
    low: DecimalStr
    close: DecimalStr
    volume: DecimalStr
    open_interest: DecimalStr | None = Field(default=None)


class OHLCVResponse(BaseModel):
    """A bar series for ``(symbol, timeframe)``."""

    symbol: str
    timeframe: Timeframe
    adjusted: bool
    bars: list[OHLCVBar]


class UniverseResponse(BaseModel):
    """As-of dated, point-in-time index constituents."""

    as_of: date | None = Field(description="Resolved snapshot date (<= requested), or null.")
    index_name: str
    symbols: list[str]


class HealthResponse(BaseModel):
    """Readiness payload — dependency reachability + cookie presence (never value)."""

    status: str
    db: bool
    redis: bool
    cookie_present: bool


class IngestRequest(BaseModel):
    """Owner-mode ingest request body."""

    symbol: str = Field(min_length=1)
    timeframe: Timeframe
    bars: int | None = Field(default=None, ge=1, le=20000)
    start: datetime | None = None
    end: datetime | None = None


class IngestResponse(BaseModel):
    """Owner-mode ingest result."""

    symbol: str
    timeframe: Timeframe
    rows_written: int


class SettlementResponse(BaseModel):
    """TFEX daily settlement for one series (public TFEX data via settfex).

    Monetary fields are ``Decimal`` serialised **as strings** on the wire.
    ``as_of`` is the UTC time the engine fetched the quote.
    """

    symbol: str
    settlement_price: DecimalStr | None = Field(default=None)
    prior_settlement_price: DecimalStr | None = Field(default=None)
    theoretical_price: DecimalStr | None = Field(default=None)
    im: DecimalStr | None = Field(default=None)
    mm: DecimalStr | None = Field(default=None)
    as_of: datetime = Field(description="UTC time the quote was fetched.")


class UnderlyingPriceResponse(BaseModel):
    """TFEX underlying-instrument spot for one series (public TFEX data via settfex).

    The underlying is the instrument a TFEX series tracks — for SET50 index
    options/futures, the SET50 index — so ``underlying_symbol`` (e.g. ``"SET50"``)
    differs from the requested ``symbol``. Price fields are ``Decimal`` serialised
    **as strings** on the wire; ``as_of`` is the venue statistics timestamp.
    """

    symbol: str = Field(description="The requested TFEX series symbol.")
    underlying_symbol: str = Field(description="The underlying instrument (e.g. 'SET50').")
    last: DecimalStr | None = Field(default=None)
    prior: DecimalStr | None = Field(default=None)
    high: DecimalStr | None = Field(default=None)
    low: DecimalStr | None = Field(default=None)
    change: DecimalStr | None = Field(default=None)
    percent_change: DecimalStr | None = Field(default=None)
    market_status: str
    underlying_type: str = Field(description="Underlying type (e.g. 'I' for index).")
    pe: DecimalStr | None = Field(default=None)
    pbv: DecimalStr | None = Field(default=None)
    as_of: datetime = Field(description="Venue statistics timestamp (statisticsAsOf).")
