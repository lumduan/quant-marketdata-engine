# API — `GET /settlements/{symbol}`

TFEX **daily settlement** for one series (futures or option). Resolved **read-through**
(Redis hot cache → single-flight'd `settfex` fetch → write-through). Public TFEX exchange
data — **not** auth-gated.

| | |
|---|---|
| Method / path | `GET /settlements/{symbol}` |
| Gateway-proxied | `GET /api/v2/engines/market-data/settlements/{symbol}` |
| Auth | **none** — public TFEX exchange data (unlike raw OHLCV) |
| Source | `src/quant_marketdata_engine/api/routes.py::get_settlement` |
| Upstream | official TFEX public API via the [`settfex`](https://pypi.org/project/settfex/) library (no broker credentials) |

## Path parameters

| Param | Type | Required | Example | Effect |
|-------|------|----------|---------|--------|
| `symbol` | string | yes | `S50M26` (futures), `S50M26C1000` (option) | TFEX series symbol |

## Request

```bash
curl "http://localhost:8300/settlements/S50M26"

# Via the gateway proxy:
curl "http://quant-api-gateway:8000/api/v2/engines/market-data/settlements/S50M26"
```

## Response `200 OK`

Monetary fields are `Decimal` **serialised as strings** (never float); any field may be
`null` when TFEX does not publish it. `as_of` is the UTC time the engine fetched the quote.

```json
{
  "symbol": "S50M26",
  "settlement_price": "1032.9",
  "prior_settlement_price": "1029.0",
  "theoretical_price": "1031.5",
  "im": "9450.0",
  "mm": "6615.0",
  "as_of": "2026-06-16T09:00:00Z"
}
```

| Field | Type | Notes |
|-------|------|-------|
| `symbol` | string | echoes the request |
| `settlement_price` | decimal string \| null | current daily settlement |
| `prior_settlement_price` | decimal string \| null | prior session's settlement |
| `theoretical_price` | decimal string \| null | theoretical price (options) |
| `im` | decimal string \| null | initial margin |
| `mm` | decimal string \| null | maintenance margin |
| `as_of` | datetime | UTC fetch time |

## Errors

| Status | When |
|--------|------|
| `404` | unknown/unlisted series (settfex returns HTTP 404) |
| `502` | TFEX upstream returned a non-404 HTTP error |
| `503` | TFEX upstream unreachable (transport error / timeout) |

Via the gateway, an upstream timeout maps to `504`, upstream-unreachable to `503`, and an
upstream `5xx`/invalid body to `502`; upstream `4xx` (e.g. `404`) is forwarded verbatim.

## Notes

- **Public data.** Settlement comes from the official TFEX exchange API (via `settfex`),
  not from the proprietary tvkit OHLCV feed, so this endpoint is intentionally **not**
  behind the `X-API-Key` gate.
- **Cache TTL.** Settlement is daily/stable; the read-through cache TTL defaults to
  `3600` s (`MARKETDATA_ENGINE_SETTLEMENT_CACHE_TTL_SECONDS`). Concurrent cold requests for
  the same symbol are deduped by the engine's single-flight lock so TFEX is hit once.
- **The Liberator order-book feed does not carry settlement** — this engine (the canonical
  public-data producer) is the right home for it.
