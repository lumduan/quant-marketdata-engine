# API — `POST /admin/ingest`

Owner-mode endpoint that fetches from tvkit and **idempotently upserts** raw bars into
`market_data.ohlcv`. This is the one place TradingView is called. It is **engine-direct, not
gateway-proxied** — the gateway forwards only the read contract.

| | |
|---|---|
| Method / path | `POST /admin/ingest` |
| Gateway-proxied | **No** (engine host `:8300` only) |
| Auth | `X-API-Key` **and** owner mode (`MARKETDATA_ENGINE_PUBLIC_MODE=false`) |
| Source | `src/quant_marketdata_engine/api/routes.py::admin_ingest` |

## Request body

| Field | Type | Required | Default | Range | Effect |
|-------|------|----------|---------|-------|--------|
| `symbol` | string | yes | — | length ≥ 1 | e.g. `SET:PTT` |
| `timeframe` | string | yes | — | `1d`\|`1h`\|`5m` | bar grain |
| `bars` | int | no | none | `1`–`20000` | bars_count to fetch (most recent N) |
| `start` | datetime | no | none | ISO UTC | fetch window start |
| `end` | datetime | no | none | ISO UTC | fetch window end |

```bash
curl -X POST http://localhost:8300/admin/ingest \
  -H "X-API-Key: <engine-read-key>" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "SET:PTT", "timeframe": "1d", "bars": 5000}'
```

## Response `200 OK`

```json
{
  "symbol": "SET:PTT",
  "timeframe": "1d",
  "rows_written": 5000
}
```

| Field | Type | Notes |
|-------|------|-------|
| `rows_written` | int | rows upserted (`ON CONFLICT … DO UPDATE`; re-running is safe) |

## Errors

| Status | When |
|--------|------|
| `401` | API key set and `X-API-Key` missing/incorrect |
| `403` | service is in public mode (`require_owner_mode`) — ingest disabled |
| `400` | ingest-side validation error (`IngestError`, e.g. bad params / public-mode refusal) |
| `502` | upstream tvkit fetch failed / session expired (`TvkitFetchError`) — the cookie is **never** included in the error |

## CLI equivalent

The same ingest path is available as a CLI (owner mode):

```bash
uv run python -m src.quant_marketdata_engine.ingest fetch --symbol SET:PTT --timeframe 1d --bars 5000
uv run python -m src.quant_marketdata_engine.ingest backfill --dir ../strategies/csm-set/data/raw/dividends
```

## Notes

- **Single-flight:** concurrent identical fetches dedupe on `(symbol, timeframe, range)` via
  the Redis lock (`cache/single_flight.py`) so TradingView is hit once.
- **Cookie safety:** `TVKIT_AUTH_TOKEN` is read but never logged; a session-expiry surfaces as
  a typed `TvkitFetchError` → `502` with a generic message.
- See [`../operations/configuration.md`](../operations/configuration.md) for owner-mode setup
  and safe cookie injection.
