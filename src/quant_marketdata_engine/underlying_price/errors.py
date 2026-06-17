"""Underlying-price-layer errors."""

from __future__ import annotations

from src.quant_marketdata_engine.errors import MarketDataEngineError


class UnderlyingPriceError(MarketDataEngineError):
    """Base for underlying-price-side problems."""


class UnderlyingPriceFetchError(UnderlyingPriceError):
    """A TFEX underlying-price fetch (via ``settfex``) failed.

    Carries the upstream HTTP ``status_code`` when one is known (e.g. a 404 for
    an unknown/unlisted series), so the API layer can map an unknown symbol to a
    ``404`` and a genuine upstream failure to ``502``/``503``. ``status_code`` is
    ``None`` when the failure was not HTTP-shaped (timeout, transport error).
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
