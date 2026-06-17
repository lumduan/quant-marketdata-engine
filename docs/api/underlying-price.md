# API — `GET /underlying-price/{symbol}`

TFEX **underlying-instrument spot** for one series (futures or option). For SET50 index
options/futures the underlying is the **SET50 index**, so the response's
`underlying_symbol` (e.g. `SET50`) differs from the requested series. Resolved
**read-through** (Redis hot cache → single-flight'd `settfex` fetch → write-through).
Public TFEX exchange data — **not** auth-gated.

| | |
|---|---|
| Method / path | `GET /underlying-price/{symbol}` |
| Gateway-proxied | `GET /api/v2/engines/market-data/underlying-price/{symbol}` |
| Auth | **none** — public TFEX exchange data (unlike raw OHLCV) |
| Source | `src/quant_marketdata_engine/api/routes.py::get_underlying_price` |
| Upstream | official TFEX public API via the [`settfex`](https://pypi.org/project/settfex/) library (no broker credentials) |

## Path parameters

| Param | Type | Required | Example | Effect |
|-------|------|----------|---------|--------|
| `symbol` | string | yes | `S50M26` (futures), `S50M26C1000` (option) | TFEX series symbol |

## Request

```bash
curl "http://localhost:8300/underlying-price/S50M26"

# Via the gateway proxy:
curl "http://quant-api-gateway:8000/api/v2/engines/market-data/underlying-price/S50M26"
```

## Response `200 OK`

Price fields are `Decimal` **serialised as strings** (never float); any price field may be
`null` when TFEX does not publish it. `underlying_symbol` is the underlying instrument the
series tracks (e.g. `SET50`). `as_of` is the venue statistics timestamp (`statisticsAsOf`).

```json
{
  "symbol": "S50M26",
  "underlying_symbol": "SET50",
  "last": "1032.9",
  "prior": "1029.0",
  "high": "1035.4",
  "low": "1028.1",
  "change": "3.9",
  "percent_change": "0.38",
  "market_status": "Open",
  "underlying_type": "I",
  "pe": "18.2",
  "pbv": "1.7",
  "as_of": "2026-06-16T09:30:00+07:00"
}
```

| Field | Type | Notes |
|-------|------|-------|
| `symbol` | string | echoes the requested series |
| `underlying_symbol` | string | the underlying instrument (e.g. `SET50`) |
| `last` | decimal string \| null | last traded price of the underlying |
| `prior` | decimal string \| null | prior day's closing price |
| `high` | decimal string \| null | intraday high |
| `low` | decimal string \| null | intraday low |
| `change` | decimal string \| null | absolute change from prior close |
| `percent_change` | decimal string \| null | percent change from prior close |
| `market_status` | string | market status (e.g. `Open`, `Closed`) |
| `underlying_type` | string | underlying type (e.g. `I` for index) |
| `pe` | decimal string \| null | price-to-earnings ratio |
| `pbv` | decimal string \| null | price-to-book-value ratio |
| `as_of` | datetime | venue statistics timestamp (`statisticsAsOf`) |

## Errors

| Status | When |
|--------|------|
| `404` | unknown/unlisted series (settfex returns HTTP 404) |
| `502` | TFEX upstream returned a non-404 HTTP error |
| `503` | TFEX upstream unreachable (transport error / timeout) |

Via the gateway, an upstream timeout maps to `504`, upstream-unreachable to `503`, and an
upstream `5xx`/invalid body to `502`; upstream `4xx` (e.g. `404`) is forwarded verbatim.

## Notes

- **Public data.** The underlying spot comes from the official TFEX exchange API (via
  `settfex`), not from the proprietary tvkit OHLCV feed, so this endpoint is intentionally
  **not** behind the `X-API-Key` gate.
- **Cache TTL.** The underlying spot is intraday/live (unlike daily settlement); the
  read-through cache TTL defaults to `60` s
  (`MARKETDATA_ENGINE_UNDERLYING_PRICE_CACHE_TTL_SECONDS`). Concurrent cold requests for the
  same symbol are deduped by the engine's single-flight lock so TFEX is hit once.
- **Underlying vs series.** A TFEX series (e.g. `S50M26C1000`) and its underlying (`SET50`)
  are different symbols — read `underlying_symbol` from the body, not the request path.
