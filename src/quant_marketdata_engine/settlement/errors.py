"""Settlement-layer errors."""

from __future__ import annotations

from src.quant_marketdata_engine.errors import MarketDataEngineError


class SettlementError(MarketDataEngineError):
    """Base for settlement-side problems."""


class SettlementFetchError(SettlementError):
    """A TFEX settlement fetch (via ``settfex``) failed.

    Carries the upstream HTTP ``status_code`` when one is known (e.g. a 404 for
    an unknown/unlisted series), so the API layer can map an unknown symbol to a
    ``404`` and a genuine upstream failure to ``502``/``503``. ``status_code`` is
    ``None`` when the failure was not HTTP-shaped (timeout, transport error).

    ⚠️ This promise was UNACHIEVABLE from the day it was written until 2026-11-14
    (TK-0655): the only code that set ``status_code`` sat behind
    ``except httpx.HTTPStatusError``, which can never fire because settfex does
    not use httpx. The populating handler now catches
    ``settfex.exceptions.FetchError``, which is the class that carries the status.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
