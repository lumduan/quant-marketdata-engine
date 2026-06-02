# API — `GET /ohlcv`

Raw (unadjusted base) OHLCV bars for one `(symbol, timeframe)`. Resolved **hot/warm**
(Redis → TimescaleDB → write-through). Auth-gated.

| | |
|---|---|
| Method / path | `GET /ohlcv` |
| Gateway-proxied | `GET /api/v2/engines/market-data/ohlcv` |
| Auth | `X-API-Key` (when the engine sets `MARKETDATA_ENGINE_API_KEY`) |
| Source | `src/quant_marketdata_engine/api/routes.py::get_ohlcv` |

## Query parameters

| Param | Type | Required | Default | Allowed / range | Effect |
|-------|------|----------|---------|-----------------|--------|
| `symbol` | string | yes | — | length 1–64 | e.g. `SET:PTT`, `TFEX:S50M2026` |
| `timeframe` | string | yes | — | `1d` \| `1h` \| `5m` | bar grain (`4h` is **not** served — see Notes) |
| `start` | datetime | no | none | ISO-8601 (UTC) | lower bound on `ts` (inclusive) |
| `end` | datetime | no | none | ISO-8601 (UTC) | upper bound on `ts` (inclusive); `start > end` → `422` |
| `limit` | int | no | `5000` | `1`–`50000` | max bars returned (most-recent first in storage order) |

## Request

```bash
curl -H "X-API-Key: <engine-read-key>" \
  "http://localhost:8300/ohlcv?symbol=SET:PTT&timeframe=1d&limit=3"

# Via the gateway proxy:
curl -H "X-API-Key: <engine-read-key>" \
  "http://quant-api-gateway:8000/api/v2/engines/market-data/ohlcv?symbol=SET:PTT&timeframe=1d&limit=3"
```

## Response `200 OK`

Prices are `Decimal` **serialised as strings**; `ts` is the bar-open time in **UTC**
(display Asia/Bangkok at the edge). `open_interest` is `null` for equities.

```json
{
  "symbol": "SET:PTT",
  "timeframe": "1d",
  "adjusted": false,
  "bars": [
    {
      "ts": "2026-05-29T00:00:00Z",
      "open": "34.500000",
      "high": "34.750000",
      "low": "34.250000",
      "close": "34.500000",
      "volume": "41250000.0000",
      "open_interest": null
    }
  ]
}
```

| Field | Type | Notes |
|-------|------|-------|
| `symbol` | string | echoes the request |
| `timeframe` | string | `1d` \| `1h` \| `5m` |
| `adjusted` | bool | always `false` for this endpoint |
| `bars[].ts` | datetime | bar-open, UTC |
| `bars[].open/high/low/close` | decimal string | `numeric(18,6)` |
| `bars[].volume` | decimal string | `numeric(20,4)` |
| `bars[].open_interest` | decimal string \| null | futures only |

## Errors

| Status | When |
|--------|------|
| `401` | `MARKETDATA_ENGINE_API_KEY` is set and `X-API-Key` is missing/incorrect |
| `422` | invalid `timeframe`, out-of-range `limit`, or `start > end` |
| `503` | DB pool unavailable (startup could not reach Postgres) |

Via the gateway, an upstream timeout maps to `504`, upstream-unreachable to `503`, and an
upstream `5xx`/invalid body to `502`; upstream `4xx` (e.g. `401`/`422`) is forwarded verbatim.

## Notes

- **`4h` is not served.** The read API exposes `1d | 1h | 5m`; the `cagg_ohlcv_4h` aggregate
  exists in the DB but is unrouted (tfex declines `4h` client-side, Phase 4). Routing `4h` is a
  tracked follow-up.
- For dividend/split-adjusted prices use [`ohlcv-adjusted.md`](ohlcv-adjusted.md).
