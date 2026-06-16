"""Tests for the public GET /settlements/{symbol} route (service overridden)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient
from src.quant_marketdata_engine.api import deps
from src.quant_marketdata_engine.api.main import create_app
from src.quant_marketdata_engine.settlement.errors import SettlementFetchError
from src.quant_marketdata_engine.settlement.models import SettlementQuote


class _StubService:
    """Stand-in SettlementService whose ``get`` returns/raises a canned value."""

    def __init__(self, *, quote: SettlementQuote | None = None, error: Exception | None = None):
        self._quote = quote
        self._error = error

    async def get(self, symbol: str) -> SettlementQuote:
        if self._error is not None:
            raise self._error
        assert self._quote is not None
        return self._quote


def _client(service: _StubService) -> TestClient:
    app = create_app()
    app.dependency_overrides[deps.get_settlement_service] = lambda: service
    return TestClient(app)


def _quote(**kw: Any) -> SettlementQuote:
    base: dict[str, Any] = {
        "symbol": "S50M26",
        "settlement_price": Decimal("1032.9"),
        "prior_settlement_price": Decimal("1029.0"),
        "theoretical_price": Decimal("1031.5"),
        "im": Decimal("9450.0"),
        "mm": Decimal("6615.0"),
        "as_of": datetime(2026, 6, 16, 9, 0, tzinfo=UTC),
    }
    base.update(kw)
    return SettlementQuote(**base)


def test_settlement_ok_serializes_decimal_as_string() -> None:
    client = _client(_StubService(quote=_quote()))
    resp = client.get("/settlements/S50M26")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "S50M26"
    assert body["settlement_price"] == "1032.9"
    assert body["prior_settlement_price"] == "1029.0"
    assert body["im"] == "9450.0"
    assert body["mm"] == "6615.0"


def test_settlement_is_public_no_api_key_needed() -> None:
    # An API key is configured for the engine, but settlement must stay open.
    client = _client(_StubService(quote=_quote()))
    assert client.get("/settlements/S50M26").status_code == 200


def test_settlement_null_fields_serialize_as_null() -> None:
    client = _client(_StubService(quote=_quote(settlement_price=None, im=None)))
    body = client.get("/settlements/S50M26").json()
    assert body["settlement_price"] is None
    assert body["im"] is None


def test_settlement_unknown_symbol_404() -> None:
    err = SettlementFetchError("unknown", status_code=404)
    resp = _client(_StubService(error=err)).get("/settlements/NOPE")
    assert resp.status_code == 404


def test_settlement_upstream_failure_502() -> None:
    err = SettlementFetchError("boom", status_code=500)
    resp = _client(_StubService(error=err)).get("/settlements/S50M26")
    assert resp.status_code == 502


def test_settlement_transport_failure_503() -> None:
    err = SettlementFetchError("timeout", status_code=None)
    resp = _client(_StubService(error=err)).get("/settlements/S50M26")
    assert resp.status_code == 503
