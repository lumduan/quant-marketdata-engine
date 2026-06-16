"""Settlement domain model (boundary contract).

A :class:`SettlementQuote` is the engine's internal representation of one TFEX
series' daily settlement, fetched via ``settfex`` from the official TFEX public
API. Monetary fields are ``Decimal`` at the boundary — ``settfex`` returns plain
``float``, so every value is converted via ``Decimal(str(x))`` (never
``Decimal(float)``, which would carry binary-float noise).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


def _to_decimal(value: float | int | None) -> Decimal | None:
    """Convert a settfex float to an exact ``Decimal`` (via ``str``), or ``None``."""
    if value is None:
        return None
    return Decimal(str(value))


class SettlementQuote(BaseModel):
    """One TFEX series' daily settlement snapshot (frozen).

    ``as_of`` is the UTC time the engine fetched the quote (not a venue date).
    """

    model_config = ConfigDict(frozen=True)

    symbol: str
    settlement_price: Decimal | None
    prior_settlement_price: Decimal | None
    theoretical_price: Decimal | None
    im: Decimal | None
    mm: Decimal | None
    as_of: datetime

    @classmethod
    def from_settfex(cls, stats: Any, *, symbol: str) -> SettlementQuote:
        """Map a settfex ``TradingStatistics`` object to a :class:`SettlementQuote`.

        ``symbol`` is echoed from the caller's request (settfex may normalize the
        symbol on its own object). The fetch time is stamped as UTC ``now``.
        """
        return cls(
            symbol=symbol,
            settlement_price=_to_decimal(stats.settlement_price),
            prior_settlement_price=_to_decimal(stats.prior_settlement_price),
            theoretical_price=_to_decimal(stats.theoretical_price),
            im=_to_decimal(stats.im),
            mm=_to_decimal(stats.mm),
            as_of=datetime.now(UTC),
        )
