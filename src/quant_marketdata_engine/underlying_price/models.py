"""Underlying-price domain model (boundary contract).

An :class:`UnderlyingPriceQuote` is the engine's internal representation of the
**underlying instrument's** spot price for a TFEX series, fetched via ``settfex``
from the official TFEX public API. For SET50 index options/futures the underlying
is the SET50 index, so ``underlying_symbol`` is the underlying (e.g. ``"SET50"``),
**not** the series that was queried.

Price fields are ``Decimal`` at the boundary — ``settfex`` returns plain
``float``, so every value is converted via ``Decimal(str(x))`` (never
``Decimal(float)``, which would carry binary-float noise).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


def _to_decimal(value: float | int | None) -> Decimal | None:
    """Convert a settfex float to an exact ``Decimal`` (via ``str``), or ``None``."""
    if value is None:
        return None
    return Decimal(str(value))


class UnderlyingPriceQuote(BaseModel):
    """One TFEX series' underlying-instrument spot snapshot (frozen).

    ``symbol`` echoes the requested series; ``underlying_symbol`` is the settfex
    ``.symbol`` (the underlying instrument, e.g. ``"SET50"``). ``as_of`` is the
    venue statistics timestamp settfex reports (``statisticsAsOf``).
    """

    model_config = ConfigDict(frozen=True)

    symbol: str
    underlying_symbol: str
    last: Decimal | None
    prior: Decimal | None
    high: Decimal | None
    low: Decimal | None
    change: Decimal | None
    percent_change: Decimal | None
    market_status: str
    underlying_type: str
    pe: Decimal | None
    pbv: Decimal | None
    as_of: datetime

    @classmethod
    def from_settfex(cls, stats: Any, *, symbol: str) -> UnderlyingPriceQuote:
        """Map a settfex ``UnderlyingPrice`` object to an :class:`UnderlyingPriceQuote`.

        ``symbol`` is echoed from the caller's request (the queried series);
        ``underlying_symbol`` comes from settfex's own ``.symbol`` (the underlying
        instrument). ``as_of`` is taken from settfex's ``statistics_as_of``.
        """
        return cls(
            symbol=symbol,
            underlying_symbol=stats.symbol,
            last=_to_decimal(stats.last),
            prior=_to_decimal(stats.prior),
            high=_to_decimal(stats.high),
            low=_to_decimal(stats.low),
            change=_to_decimal(stats.change),
            percent_change=_to_decimal(stats.percent_change),
            market_status=stats.market_status,
            underlying_type=stats.underlying_type,
            pe=_to_decimal(stats.pe),
            pbv=_to_decimal(stats.pbv),
            as_of=stats.statistics_as_of,
        )
