"""Tests for the public GET /underlying-price/{symbol} route (service overridden)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient
from src.quant_marketdata_engine.api import deps
from src.quant_marketdata_engine.api.main import create_app
from src.quant_marketdata_engine.underlying_price.errors import UnderlyingPriceFetchError
from src.quant_marketdata_engine.underlying_price.models import UnderlyingPriceQuote


class _StubService:
    """Stand-in UnderlyingPriceService whose ``get`` returns/raises a canned value."""

    def __init__(
        self, *, quote: UnderlyingPriceQuote | None = None, error: Exception | None = None
    ):
        self._quote = quote
        self._error = error

    async def get(self, symbol: str) -> UnderlyingPriceQuote:
        if self._error is not None:
            raise self._error
        assert self._quote is not None
        return self._quote


def _client(service: _StubService) -> TestClient:
    app = create_app()
    app.dependency_overrides[deps.get_underlying_price_service] = lambda: service
    return TestClient(app)


def _quote(**kw: Any) -> UnderlyingPriceQuote:
    base: dict[str, Any] = {
        "symbol": "S50M26",
        "underlying_symbol": "SET50",
        "last": Decimal("1032.9"),
        "prior": Decimal("1029.0"),
        "high": Decimal("1035.4"),
        "low": Decimal("1028.1"),
        "change": Decimal("3.9"),
        "percent_change": Decimal("0.38"),
        "market_status": "Open",
        "underlying_type": "I",
        "pe": Decimal("18.2"),
        "pbv": Decimal("1.7"),
        "as_of": datetime(2026, 6, 16, 9, 30, tzinfo=UTC),
    }
    base.update(kw)
    return UnderlyingPriceQuote(**base)


def test_underlying_price_ok_serializes_decimal_as_string() -> None:
    client = _client(_StubService(quote=_quote()))
    resp = client.get("/underlying-price/S50M26")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "S50M26"
    assert body["underlying_symbol"] == "SET50"
    assert body["last"] == "1032.9"
    assert body["prior"] == "1029.0"
    assert body["change"] == "3.9"
    assert body["percent_change"] == "0.38"
    assert body["pe"] == "18.2"
    assert body["pbv"] == "1.7"
    assert body["market_status"] == "Open"
    assert body["underlying_type"] == "I"


def test_underlying_price_is_public_no_api_key_needed() -> None:
    # An API key is configured for the engine, but underlying-price must stay open.
    client = _client(_StubService(quote=_quote()))
    assert client.get("/underlying-price/S50M26").status_code == 200


def test_underlying_price_null_fields_serialize_as_null() -> None:
    client = _client(_StubService(quote=_quote(last=None, pe=None)))
    body = client.get("/underlying-price/S50M26").json()
    assert body["last"] is None
    assert body["pe"] is None


def test_underlying_price_unknown_symbol_404() -> None:
    err = UnderlyingPriceFetchError("unknown", status_code=404)
    resp = _client(_StubService(error=err)).get("/underlying-price/NOPE")
    assert resp.status_code == 404


def test_underlying_price_upstream_failure_502() -> None:
    err = UnderlyingPriceFetchError("boom", status_code=500)
    resp = _client(_StubService(error=err)).get("/underlying-price/S50M26")
    assert resp.status_code == 502


def test_underlying_price_transport_failure_503() -> None:
    err = UnderlyingPriceFetchError("timeout", status_code=None)
    resp = _client(_StubService(error=err)).get("/underlying-price/S50M26")
    assert resp.status_code == 503
